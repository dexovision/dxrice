#!/usr/bin/env python3
"""New-window placement joins the cloud (SUPER+G's own per-window step),
never reacts to anything but a real window opening, never touches transient
surfaces, and can be switched off in Settings without affecting SUPER+G.

Everything here runs against in-memory fakes: no compositor, no X server,
no theme.json outside a temp dir.

    python3 scripts/dxrice_test_auto_place_cloud.py
"""
import contextlib
import io
import json
import math
import os
import random
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_auto_place_window as apw
import dxrice_auto_arrange as arr
import dxrice_window_class as wc

GAP = 5
import dxrice_spiral  # noqa: E402
LO, HI = dxrice_spiral.SPACING_MIN_DEFAULT, dxrice_spiral.SPACING_MAX_DEFAULT


def _in_band(tc, gap, msg=None):
    """A neighbour at the composition spacing (16-24 px by default; exact
    5 px before the spiral redesign)."""
    tc.assertTrue(LO - 0.5 <= gap <= HI + 0.5, msg or f"{gap}px is not the composition spacing")
MON = (0, 0, 1920, 1080)


def _rect(c):
    return (c["at"][0], c["at"][1], c["at"][0] + c["size"][0], c["at"][1] + c["size"][1])


def _sep(a, b):
    """Daylight between two rects (negative = overlap)."""
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


class FakeHypr:
    """Just enough Hyprland: `clients`, `monitors`, and the move/resize
    dispatches placement sends (resizes centre-anchored, like Hyprland)."""

    def __init__(self):
        self._pid = 1000
        self.clients = {}
        self.dispatched = []
        self.on_clients_read = None  # hook: called before each `clients` read
        self.scale = 1.0

    def add(self, addr, x, y, w, h, **extra):
        c = {"address": addr, "at": [x, y], "size": [w, h], "floating": True, "fullscreen": 0,
             "workspace": {"id": 1}, "title": addr, "class": extra.pop("cls", addr), "pid": extra.pop("pid", None),
             "xwayland": False, "pinned": False, "mapped": True, "hidden": False}
        c.update(extra)
        if c["pid"] is None:  # every window its own process unless a test says otherwise
            self._pid += 1
            c["pid"] = self._pid
        c["initialClass"] = c["class"]
        self.clients[addr] = c
        return c

    def open(self, addr, w, h, **extra):
        """Mapped where Hyprland maps a new floating window: centred."""
        return self.add(addr, round((MON[0] + MON[2] - w) / 2), round((MON[1] + MON[3] - h) / 2), w, h, **extra)

    def hyprctl_json(self, args, **kw):
        if args and args[0] == "clients":
            if self.on_clients_read:
                self.on_clients_read(self)
            return [json.loads(json.dumps(c)) for c in self.clients.values()]
        if args and args[0] == "activeworkspace":
            return {"id": 1}
        if args and args[0] == "monitors":
            return [{"x": 0, "y": 0, "width": 1920, "height": 1080, "focused": True, "scale": self.scale}]
        return None

    def dispatch_async(self, expr):
        self.batch_async([expr])

    def move_window_exact_async(self, x, y, address):
        self.batch_async([apw.move_window_exact_lua(x, y, address)])

    def batch_async(self, exprs):
        for e in exprs:
            self.dispatched.append(e)
            m = re.search(r'window\.(move|resize)\(\{ window = "address:([^"]+)", x = (-?\d+), y = (-?\d+)', e)
            kind, addr, a, b = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            c = self.clients.get(addr)
            if not c:
                continue
            if kind == "move":
                c["at"] = [a, b]
            else:
                cx, cy = c["at"][0] + c["size"][0] / 2, c["at"][1] + c["size"][1] / 2
                c["size"] = [a, b]
                c["at"] = [round(cx - a / 2), round(cy - b / 2)]

    def snapshot(self, but=None):
        return {a: (tuple(c["at"]), tuple(c["size"])) for a, c in self.clients.items() if a != but}


class _Base(unittest.TestCase):
    """Wires apw/arr to a FakeHypr and a fake X server answer."""

    X11 = None  # what x11_windows() would return; None = no X server

    def setUp(self):
        self.hypr = FakeHypr()
        self._tmp = tempfile.TemporaryDirectory()
        self._env = {k: os.environ.get(k) for k in ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME")}
        os.environ["XDG_RUNTIME_DIR"] = self._tmp.name
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name
        self._saved = (apw.hyprctl_json, apw.dispatch_async, apw.batch_async, apw.move_window_exact_async,
                       apw.get_monitor_bounds, apw.time.sleep, apw.classify_clients,
                       arr.hyprctl_json, arr.batch_async, arr.live_gap, arr.get_monitor_bounds,
                       wc.x11_windows)
        h = self.hypr
        apw.hyprctl_json, apw.dispatch_async, apw.batch_async = h.hyprctl_json, h.dispatch_async, h.batch_async
        apw.move_window_exact_async = h.move_window_exact_async
        apw.get_monitor_bounds = lambda: MON
        apw.time.sleep = lambda s: None
        arr.hyprctl_json, arr.batch_async = h.hyprctl_json, h.batch_async
        arr.live_gap, arr.get_monitor_bounds = (lambda: GAP), (lambda: MON)
        wc.x11_windows = lambda display=None: self.X11
        apw.classify_clients = lambda clients: wc.classify_all(clients)

    def tearDown(self):
        (apw.hyprctl_json, apw.dispatch_async, apw.batch_async, apw.move_window_exact_async,
         apw.get_monitor_bounds, apw.time.sleep, apw.classify_clients,
         arr.hyprctl_json, arr.batch_async, arr.live_gap, arr.get_monitor_bounds,
         wc.x11_windows) = self._saved
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def cluster(self):
        """Three ordinary windows already arranged around the viewport."""
        self.hypr.add("0xterm", 300, 200, 860, 560)
        self.hypr.add("0xfiles", 1165, 200, 500, 420)
        self.hypr.add("0xchat", 300, 765, 700, 300)

    def assert_no_overlap(self):
        rects = [(a, _rect(c)) for a, c in self.hypr.clients.items()
                 if wc.is_arrangeable(wc.classify(c, self.X11))]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                self.assertGreaterEqual(_sep(rects[i][1], rects[j][1]), GAP - 0.5,
                                        f"{rects[i][0]} and {rects[j][0]} closer than {GAP}px")


# ---------------------------------------------------------------------------
# Hover, tooltips, menus: never placement
# ---------------------------------------------------------------------------

def _x11(geom, override_redirect=False, types=(), transient_for=None):
    return {"geometry": tuple(geom), "override_redirect": override_redirect, "types": set(types),
            "transient_for": tuple(transient_for) if transient_for else None}


class TestTransientSurfacesAreNeverPlaced(_Base):
    """The reported bug: hovering a link (or a tab, or anything with a
    tooltip) in an XWayland app maps an override-redirect popup, which
    Hyprland reports as an ordinary new floating window. The old placer
    moved it -- away from the thing it was pointing at -- and could move the
    windows around it to make room for it. Measured on a nested Hyprland
    with a real GTK override-redirect popup (see dxrice_window_class.py)."""

    def _tooltip(self, **x11):
        self.cluster()
        tip = self.hypr.add("0xtip", 1170, 115, 260, 60, xwayland=True, cls="Brave-browser")
        self.X11 = [_x11((1170, 115, 260, 60), **x11)]
        return tip

    def test_override_redirect_hover_popup_is_left_alone(self):
        self._tooltip(override_redirect=True)
        before = self.hypr.snapshot()
        self.assertEqual(apw.place_new_window("0xtip", 1, GAP), "ignored")
        self.assertEqual(self.hypr.dispatched, [], "a hover popup made placement dispatch something")
        self.assertEqual(self.hypr.snapshot(), before)

    def test_managed_x11_popup_types_are_left_alone(self):
        for t in ("_NET_WM_WINDOW_TYPE_TOOLTIP", "_NET_WM_WINDOW_TYPE_POPUP_MENU",
                  "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU", "_NET_WM_WINDOW_TYPE_DND", "_NET_WM_WINDOW_TYPE_COMBO",
                  "_NET_WM_WINDOW_TYPE_NOTIFICATION", "_NET_WM_WINDOW_TYPE_SPLASH"):
            with self.subTest(t):
                self.hypr.clients.clear()
                self.hypr.dispatched.clear()
                self._tooltip(types=[t])
                self.assertEqual(apw.place_new_window("0xtip", 1, GAP), "ignored")
                self.assertEqual(self.hypr.dispatched, [])

    def test_small_xwayland_window_with_no_x_server_answer_is_left_alone(self):
        self._tooltip()
        self.X11 = None  # X unreachable: can't tell -- don't move a probable popup
        self.assertEqual(apw.place_new_window("0xtip", 1, GAP), "ignored")
        self.assertEqual(self.hypr.dispatched, [])

    def test_large_xwayland_window_with_no_x_server_answer_is_still_placed(self):
        self.cluster()
        self.hypr.open("0xgame", 1100, 700, xwayland=True)
        self.X11 = None
        self.assertEqual(apw.place_new_window("0xgame", 1, GAP), "placed")
        self.assert_no_overlap()

    def test_tiny_and_shell_surfaces_are_left_alone(self):
        self.cluster()
        self.hypr.open("0xime", 1, 1)
        self.hypr.open("0xwifi", 380, 220, cls="org.quickshell")
        for addr in ("0xime", "0xwifi"):
            self.assertEqual(apw.place_new_window(addr, 1, GAP), "ignored", addr)
        self.assertEqual(self.hypr.dispatched, [])

    def test_open_tooltip_is_not_an_obstacle_or_part_of_the_layout(self):
        """A tooltip that happens to be open while a real window opens (or
        while SUPER+G runs) must not shape where anything goes."""
        self.cluster()
        self.hypr.open("0xnew", 640, 420)
        self.assertEqual(apw.place_new_window("0xnew", 1, GAP), "placed")
        without = tuple(self.hypr.clients["0xnew"]["at"])
        # Same again, with a popup sitting right where the new window went.
        self.hypr.clients.pop("0xnew")
        self.hypr.dispatched.clear()
        x, y = without
        self.hypr.add("0xtip", x + 20, y + 20, 300, 80, xwayland=True)
        self.X11 = [_x11((x + 20, y + 20, 300, 80), override_redirect=True)]
        self.hypr.open("0xnew", 640, 420)
        self.assertEqual(apw.place_new_window("0xnew", 1, GAP), "placed")
        self.assertEqual(tuple(self.hypr.clients["0xnew"]["at"]), without)

    def test_super_g_neither_moves_nor_arranges_around_a_tooltip(self):
        self.cluster()
        self.hypr.add("0xtip", 1500, 900, 300, 80, xwayland=True)
        self.X11 = [_x11((1500, 900, 300, 80), override_redirect=True)]
        with contextlib.redirect_stdout(io.StringIO()):
            arr.main()
        self.assertEqual(self.hypr.clients["0xtip"]["at"], [1500, 900])
        self.assertFalse(any("0xtip" in e for e in self.hypr.dispatched))


class TestX11Classification(unittest.TestCase):
    """dxrice_window_class.classify against what the X server reports."""

    def test_kinds(self):
        c = {"address": "0x1", "at": [10, 20], "size": [300, 200], "xwayland": True}
        cases = [
            ([_x11((10, 20, 300, 200), override_redirect=True)], wc.TRANSIENT),
            ([_x11((10, 20, 300, 200), types=["_NET_WM_WINDOW_TYPE_NORMAL"])], wc.NORMAL),
            ([_x11((10, 20, 300, 200), types=["_NET_WM_WINDOW_TYPE_DIALOG"])], wc.DIALOG),
            ([_x11((10, 20, 300, 200), transient_for=(0, 0, 900, 700))], wc.DIALOG),
            ([_x11((10, 20, 300, 200), types=["_NET_WM_WINDOW_TYPE_SPLASH"])], wc.SPLASH),
            ([_x11((11, 20, 300, 200), override_redirect=True)], wc.UNKNOWN),  # no geometry match
            (None, wc.UNKNOWN),
        ]
        for x11, want in cases:
            with self.subTest(want=want, x11=x11):
                self.assertEqual(wc.classify(c, x11), want)

    def test_wayland_windows_need_no_x_server(self):
        calls = []
        kinds, _ = wc.classify_all([{"address": "0xa", "at": [0, 0], "size": [800, 600], "xwayland": False}],
                                   x11_query=lambda d: calls.append(d))
        self.assertEqual(kinds, {"0xa": wc.NORMAL})
        self.assertEqual(calls, [], "asked the X server about a Wayland-only desktop")

    def test_partition(self):
        cs = [{"address": a, "at": [0, 0], "size": [400, 300], "floating": True, "workspace": {"id": ws},
               "fullscreen": fs, "pinned": pin, "hidden": hid}
              for a, ws, fs, pin, hid in (("0xe", 1, 0, False, False), ("0xfs", 1, 2, False, False),
                                          ("0xpin", 1, 0, True, False), ("0xother", 2, 0, False, False),
                                          ("0xhid", 1, 0, False, True), ("0xtip", 1, 0, False, False))]
        eligible, fixed = wc.partition(cs, 1, {"0xtip": wc.TRANSIENT})
        self.assertEqual([c["address"] for c in eligible], ["0xe"])
        self.assertEqual(sorted(c["address"] for c in fixed), ["0xfs", "0xpin"])

    def test_fractional_scaling_still_finds_the_popup(self):
        """With a 1.5x monitor and force_zero_scaling, XWayland's geometry
        is the layout geometry times the scale, and its origin need not
        line up -- exact matching found nothing, and a large popup (a
        menu) was then treated as an ordinary window."""
        c = {"address": "0x1", "at": [100, 100], "size": [400, 300], "xwayland": True}
        scaled_or = [_x11((150, 150, 600, 450), override_redirect=True)]
        self.assertEqual(wc.classify(c, scaled_or), wc.UNKNOWN, "exact matching alone can't see it")
        self.assertEqual(wc.classify(c, scaled_or, scales=[1.0, 1.5]), wc.TRANSIENT)
        offset_or = [_x11((2070, 40, 601, 449), override_redirect=True)]   # other monitor's origin, rounding
        self.assertEqual(wc.classify(c, offset_or, scales=[1.5]), wc.TRANSIENT)
        normal = [_x11((150, 150, 600, 450), types=["_NET_WM_WINDOW_TYPE_NORMAL"])]
        self.assertEqual(wc.classify(c, normal, scales=[1.5]), wc.NORMAL)

    def test_ambiguous_scaled_match_prefers_leaving_it_alone(self):
        c = {"address": "0x1", "at": [0, 0], "size": [400, 300], "xwayland": True}
        both = [_x11((10, 10, 600, 450), types=["_NET_WM_WINDOW_TYPE_NORMAL"]),
                _x11((900, 10, 600, 450), override_redirect=True)]
        self.assertEqual(wc.classify(c, both, scales=[1.5]), wc.TRANSIENT)

    def test_an_exact_match_wins_over_a_scaled_one(self):
        c = {"address": "0x1", "at": [0, 0], "size": [400, 300], "xwayland": True}
        x11 = [_x11((0, 0, 400, 300), types=["_NET_WM_WINDOW_TYPE_NORMAL"]),
               _x11((0, 0, 600, 450), override_redirect=True)]
        self.assertEqual(wc.classify(c, x11, scales=[1.5]), wc.NORMAL)

    def test_monitor_scales(self):
        self.assertEqual(wc.monitor_scales([{"scale": 1.0}, {"scale": 1.5}, {"scale": 1.5}, {"scale": "x"}, {}]),
                         [1.0, 1.5])
        self.assertEqual(wc.monitor_scales(None), [])

    def test_live_query_degrades_without_display(self):
        self.assertIsNone(wc.x11_windows(display=""))


class TestDialogs(_Base):
    def test_x11_dialog_goes_beside_its_wm_transient_for_parent(self):
        """The X server names the parent outright, so a dialog lands beside
        it even when pid and class say nothing (a helper process)."""
        self.cluster()
        self.hypr.add("0xparent", 1200, 640, 600, 400, xwayland=True, pid=7, cls="App")
        self.hypr.open("0xdlg", 420, 260, xwayland=True, pid=99, cls="Helper")
        dlg = self.hypr.clients["0xdlg"]
        self.X11 = [_x11((1200, 640, 600, 400)),
                    _x11((dlg["at"][0], dlg["at"][1], 420, 260), types=["_NET_WM_WINDOW_TYPE_DIALOG"],
                         transient_for=(1200, 640, 600, 400))]
        self.assertEqual(apw.place_new_window("0xdlg", 1, GAP), "placed")
        _in_band(self, _sep(_rect(self.hypr.clients["0xdlg"]), (1200, 640, 1800, 1040)))
        self.assert_no_overlap()

    def test_scaled_popup_and_dialog_through_the_real_classification_seam(self):
        """End to end with the placer's own seam (monitor scales read from
        Hyprland): on a 1.5x monitor a large XWayland menu is still left
        alone, and a dialog still finds its parent."""
        apw.classify_clients = apw._classify_with_scales
        self.hypr.scale = 1.5
        self.cluster()
        self.hypr.add("0xparent", 1200, 640, 600, 400, xwayland=True, pid=7, cls="App")
        self.hypr.add("0xmenu", 300, 200, 500, 420, xwayland=True, pid=7, cls="App")   # big: > 5% of the screen
        self.X11 = [_x11((1800, 960, 900, 600)), _x11((450, 300, 750, 630), override_redirect=True)]
        self.assertEqual(apw.place_new_window("0xmenu", 1, GAP), "ignored")
        self.assertEqual(self.hypr.dispatched, [])
        self.hypr.clients.pop("0xmenu")
        self.hypr.open("0xdlg", 420, 260, xwayland=True, pid=99, cls="Helper")
        d = self.hypr.clients["0xdlg"]
        self.X11 = [_x11((1800, 960, 900, 600)),
                    _x11((d["at"][0] * 1.5, d["at"][1] * 1.5, 630, 390), types=["_NET_WM_WINDOW_TYPE_DIALOG"],
                         transient_for=(1800, 960, 900, 600))]
        self.assertEqual(apw.place_new_window("0xdlg", 1, GAP), "placed")
        _in_band(self, _sep(_rect(self.hypr.clients["0xdlg"]), (1200, 640, 1800, 1040)))

    def test_small_dialog_never_moves_anything_else(self):
        self.cluster()
        before = self.hypr.snapshot()
        self.hypr.open("0xconfirm", 420, 180, cls="0xterm")  # same class as the terminal: its dialog
        self.assertEqual(apw.place_new_window("0xconfirm", 1, GAP), "placed")
        self.assertEqual(self.hypr.snapshot(but="0xconfirm"), before)
        self.assertEqual(tuple(self.hypr.clients["0xconfirm"]["size"]), (420, 180))


# ---------------------------------------------------------------------------
# Joining the cloud
# ---------------------------------------------------------------------------

APPS = {"terminal": (860, 560), "browser": (1600, 1000), "files": (900, 620), "settings": (820, 560),
        "editor": (1300, 850), "chat": (1100, 750), "media": (640, 400), "pip": (550, 300)}


class TestJoinsTheCloud(_Base):

    def test_uses_super_g_step_not_a_separate_algorithm(self):
        """place_new_window's target is join_composition's, and
        join_composition is the shared spiral composer's join step
        (dxrice_spiral.join -- the same candidates, spacing and spiral
        preference a SUPER+G build step scores)."""
        self.cluster()
        self.hypr.open("0xnew", 700, 450)
        layout = [tuple(c["at"]) + tuple(c["size"]) for a, c in self.hypr.clients.items() if a != "0xnew"]
        want = arr.join_composition((700, 450), layout, layout, MON, GAP)
        self.assertEqual(apw.place_new_window("0xnew", 1, GAP), "placed")
        self.assertEqual(tuple(self.hypr.clients["0xnew"]["at"]), want)

        calls = []
        real = dxrice_spiral.join
        dxrice_spiral.join = lambda *a, **k: calls.append(1) or real(*a, **k)
        try:
            arr.join_composition((700, 450), layout, layout, MON, GAP)
        finally:
            dxrice_spiral.join = real
        self.assertEqual(calls, [1])

    def test_sequences_keep_gaps_sizes_and_existing_windows(self):
        """200 realistic opening sequences: every new window keeps its size,
        lands the composition spacing from a neighbour (exactly one 5 px gap
        before the spiral redesign), keeps at least the spacing minimum from
        everything, and no existing window ever moves or changes size."""
        rng = random.Random(7)
        opens = 0
        for _ in range(200):
            self.hypr.clients.clear()
            for i in range(rng.randint(2, 8)):
                cls = rng.choice(list(APPS))
                w, h = (int(v * rng.uniform(0.85, 1.12)) for v in APPS[cls])
                addr = f"0x{cls}{i}"
                before = self.hypr.snapshot()
                self.hypr.open(addr, w, h, cls=cls, pid=1000 + i)
                self.assertEqual(apw.place_new_window(addr, 1, GAP), "placed")
                opens += 1
                self.assertEqual(self.hypr.snapshot(but=addr), before, f"opening {addr} moved another window")
                new = self.hypr.clients[addr]
                others = [_rect(c) for a, c in self.hypr.clients.items() if a != addr]
                if others:
                    gaps = [_sep(_rect(new), r) for r in others]
                    self.assertGreaterEqual(min(gaps), LO - 0.5, "overlap or closer than the spacing")
                    _in_band(self, min(gaps), f"{addr} not at the spacing from anything: {min(gaps)}")
        self.assertGreater(opens, 900)

    def test_result_is_a_composition_super_g_accepts(self):
        """What sequential opening builds is a finished composition by the
        spiral's own rules -- no overlap, no window closer than the spacing
        minimum, every window at the spacing from a neighbour -- and the
        shape follows the screen (wider than tall; the round target the old
        placer used left 80/200 of these taller than wide). SUPER+G on it
        is final after ONE press.

        Changed by the spiral redesign: this used to require that SUPER+G's
        "already a good arrangement" test accept nearly all of these
        (117/120). Auto-placement composes in opening order and never moves
        an existing window, while SUPER+G orders the whole set by
        prominence, so SUPER+G now re-winds about 40% of them (68/120 kept
        as they are on this seed) -- measured and reported in
        docs/phase1/REPORT_SPIRAL.md, not hidden behind a looser bound."""
        rng = random.Random(11)
        wide = 0
        for _ in range(120):
            self.hypr.clients.clear()
            for i in range(rng.randint(3, 7)):
                cls = rng.choice(list(APPS))
                self.hypr.open(f"0x{cls}{i}", *APPS[cls], cls=cls, pid=1000 + i)
                apw.place_new_window(f"0x{cls}{i}", 1, GAP)
            rects = [_rect(c) for c in self.hypr.clients.values()]
            for k, r in enumerate(rects):
                seps = [_sep(r, o) for j2, o in enumerate(rects) if j2 != k]
                self.assertGreaterEqual(min(seps), LO - 0.5, "closer than the spacing minimum")
                _in_band(self, min(seps), f"a window is not at the spacing from any neighbour: {min(seps)}")
            bw = max(r[2] for r in rects) - min(r[0] for r in rects)
            bh = max(r[3] for r in rects) - min(r[1] for r in rects)
            wide += bw >= bh
            el = [{"address": a, "at": list(c["at"]), "size": list(c["size"])} for a, c in self.hypr.clients.items()]
            first = arr.auto_arrange(el, [], MON, GAP)
            locked = frozenset(a for (a, x, y, w, h), e in zip(first, el) if (w, h) != tuple(e["size"]))
            again = arr.auto_arrange([{"address": a, "at": [x, y], "size": [w, h]} for a, x, y, w, h in first],
                                     [], MON, GAP, resize_locked=locked)
            self.assertEqual(sorted(again), sorted(first), "SUPER+G needed a second press")
        self.assertGreaterEqual(wide, 96)

    def test_fullscreen_and_pinned_windows_are_obstacles_not_layout(self):
        self.hypr.add("0xfs", 0, 0, 1920, 1080, fullscreen=2)
        self.hypr.add("0xpin", 1500, 60, 380, 240, pinned=True)
        self.hypr.add("0xterm", 400, 300, 860, 560)
        self.hypr.open("0xnew", 700, 450)
        self.assertEqual(apw.place_new_window("0xnew", 1, GAP), "placed")
        new = _rect(self.hypr.clients["0xnew"])
        self.assertGreaterEqual(_sep(new, _rect(self.hypr.clients["0xpin"])), GAP - 0.5)
        self.assertEqual(self.hypr.clients["0xfs"]["at"], [0, 0])
        self.assertEqual(self.hypr.clients["0xpin"]["at"], [1500, 60])

    def test_a_cluster_panned_out_of_view_does_not_pull_the_new_window_off_screen(self):
        self.hypr.add("0xfar1", 5000, 3000, 860, 560)
        self.hypr.add("0xfar2", 5865, 3000, 860, 560)
        self.hypr.open("0xnew", 700, 450)
        self.assertEqual(apw.place_new_window("0xnew", 1, GAP), "placed")
        x, y = self.hypr.clients["0xnew"]["at"]
        self.assertTrue(0 <= x and x + 700 <= 1920 and 0 <= y and y + 450 <= 1080, (x, y))

    def test_first_window_is_left_where_it_mapped(self):
        self.hypr.open("0xonly", 900, 600)
        self.assertEqual(apw.place_new_window("0xonly", 1, GAP), "placed")
        self.assertEqual(self.hypr.dispatched, [])


class TestRobustness(_Base):

    def test_window_that_closes_before_placement(self):
        self.cluster()
        self.assertEqual(apw.place_new_window("0xnever", 1, GAP), "gone")
        self.assertEqual(self.hypr.dispatched, [])

    def test_geometry_that_arrives_late_is_waited_for(self):
        self.cluster()
        reads = {"n": 0}

        def late(h):
            reads["n"] += 1
            if reads["n"] == 4 and "0xslow" not in h.clients:
                h.open("0xslow", 640, 400)
        self.hypr.on_clients_read = late
        self.assertEqual(apw.place_new_window("0xslow", 1, GAP), "placed")
        self.assertGreaterEqual(reads["n"], 4)
        self.assert_no_overlap()

    def test_window_settling_its_own_size_is_placed_at_the_settled_size(self):
        """zenity maps 320x246 and settles to 300x226: placing against the
        transient size leaves a 20px-wider gap than the composition spacing
        (15px where 5 was configured, before the spiral redesign)."""
        self.cluster()
        self.hypr.open("0xz", 320, 246)
        reads = {"n": 0}

        def shrink(h):
            reads["n"] += 1
            if reads["n"] == 2:
                c = h.clients["0xz"]
                c["size"] = [300, 226]
                c["at"] = [c["at"][0] + 10, c["at"][1] + 10]
        self.hypr.on_clients_read = shrink
        self.assertEqual(apw.place_new_window("0xz", 1, GAP), "placed")
        z = _rect(self.hypr.clients["0xz"])
        _in_band(self, min(_sep(z, _rect(c)) for a, c in self.hypr.clients.items() if a != "0xz"))

    def test_window_the_user_already_moved_is_left_where_they_put_it(self):
        self.cluster()
        self.hypr.open("0xnew", 640, 400)
        state = {"armed": False, "reads": 0}

        def user_drags(h):
            state["reads"] += 1
            # The last read before dispatch is the one that sees the drag.
            if state["armed"]:
                h.clients["0xnew"]["at"] = [77, 88]
        self.hypr.on_clients_read = user_drags
        real_join = arr.join_composition

        def join_then_drag(*a, **k):
            state["armed"] = True
            return real_join(*a, **k)
        arr.join_composition = join_then_drag
        try:
            self.assertEqual(apw.place_new_window("0xnew", 1, GAP), "user-moved")
        finally:
            arr.join_composition = real_join
        self.assertEqual(self.hypr.clients["0xnew"]["at"], [77, 88])
        self.assertEqual(self.hypr.dispatched, [])


# ---------------------------------------------------------------------------
# The event stream: only a window opening starts a placement
# ---------------------------------------------------------------------------

class TestEventStream(_Base):

    def setUp(self):
        super().setUp()
        self.theme = os.path.join(self._tmp.name, "dxrice", "theme.json")
        os.makedirs(os.path.dirname(self.theme))
        self.write_theme({"hypr_gaps_in": 5, "schema_version": 1, "my_custom_key": [1, 2]})
        self.calls = []
        self.listener = apw.PlacementListener(apw.ThemeSettings(self.theme), place=self.fake_place)
        self.status = {}

    def write_theme(self, data):
        tmp = self.theme + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        st = os.stat(tmp)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))  # distinct mtime even on coarse clocks
        os.replace(tmp, self.theme)

    def fake_place(self, addr, ws, gap):
        self.calls.append(addr)
        return self.status.get(addr, "placed")

    def feed(self, *lines):
        return [self.listener.handle_line(l) for l in lines]

    # What moving the pointer around a desktop with follow_mouse produces,
    # plus what this listener's own moves and a browser hovering links emit.
    NOISE = ["activewindow>>Brave-browser,Example - Brave", "activewindowv2>>5621aa", "focusedmon>>DP-1,1",
             "windowtitle>>5621aa", "windowtitlev2>>5621aa,https://example.com/hovered-link",
             "movewindow>>5621aa,1", "movewindowv2>>5621aa,1,1", "workspace>>1", "workspacev2>>1,1",
             "urgent>>5621aa", "activelayout>>kbd,us", "submap>>", "minimized>>5621aa,0",
             "openlayer>>dxrice-osd", "closelayer>>dxrice-osd", "pin>>5621aa,0", "bell>>5621aa", "",
             "garbage without separator", "openwindow>>", "openwindow>>zz,notanumber,a,b"]

    def test_pointer_focus_titles_and_own_moves_never_place_anything(self):
        self.feed(*self.NOISE * 20)
        self.assertEqual(self.calls, [])

    def test_each_window_is_placed_once(self):
        self.feed("openwindow>>a1,1,kitty,kitty", *self.NOISE,
                  "openwindow>>a1,1,kitty,kitty", "openwindow>>a1,1,kitty,kitty")
        self.assertEqual(self.calls, ["0xa1"])
        # Closed and mapped again: a new window as far as the user can tell.
        self.feed("closewindow>>a1", "openwindow>>a1,1,kitty,kitty")
        self.assertEqual(self.calls, ["0xa1", "0xa1"])

    def test_rapid_opens_are_each_placed_in_order(self):
        self.feed(*[f"openwindow>>b{i},1,kitty,kitty" for i in range(8)])
        self.assertEqual(self.calls, [f"0xb{i}" for i in range(8)])

    def test_window_mapped_fullscreen_is_placed_once_when_it_leaves_fullscreen(self):
        self.status["0xg"] = "fullscreen"
        self.feed("openwindow>>g,1,sober,Sober")
        self.feed("fullscreen>>1", "fullscreen>>1")
        self.status["0xg"] = "placed"
        self.feed("fullscreen>>0", "fullscreen>>0", "changefloatingmode>>g,1")
        self.assertEqual(self.calls, ["0xg"] * 4)

    def test_failing_placement_does_not_stop_the_listener(self):
        def boom(addr, ws, gap):
            self.calls.append(addr)
            raise OSError("socket gone")
        self.listener._place = boom
        with contextlib.redirect_stderr(io.StringIO()):
            self.feed("openwindow>>c1,1,x,x", "openwindow>>c2,1,x,x", "openwindow>>c1,1,x,x")
        self.assertEqual(self.calls, ["0xc1", "0xc2"])

    def test_switched_off_places_nothing_and_back_on_works_without_restart(self):
        self.write_theme({"hypr_gaps_in": 5, "auto_place_windows": False})
        self.feed("openwindow>>d1,1,kitty,kitty", "openwindow>>d2,1,kitty,kitty")
        self.assertEqual(self.calls, [])
        self.write_theme({"hypr_gaps_in": 5, "auto_place_windows": True})
        self.feed("openwindow>>d3,1,kitty,kitty", "openwindow>>d1,1,kitty,kitty")
        self.assertEqual(self.calls, ["0xd3"], "a window opened while off was placed later, or d3 wasn't")

    def test_switched_off_drops_windows_waiting_to_leave_fullscreen(self):
        self.status["0xg"] = "fullscreen"
        self.feed("openwindow>>g,1,sober,Sober")
        self.write_theme({"auto_place_windows": False})
        self.status["0xg"] = "placed"
        self.feed("fullscreen>>0")
        self.assertEqual(self.calls, ["0xg"])

    def test_settings_file_states(self):
        s = apw.ThemeSettings(self.theme)
        self.assertTrue(s.refresh().enabled, "a theme.json without the key must mean on (today's behaviour)")
        self.write_theme({"auto_place_windows": False, "hypr_gaps_in": 9})
        self.assertFalse(s.refresh().enabled)
        self.assertEqual(s.gap, 9)
        with open(self.theme, "w") as f:
            f.write('{"auto_place_windows": tr')  # caught mid-write
        self.assertFalse(s.refresh().enabled, "a torn theme.json flipped the switch")
        self.assertEqual(s.gap, 9)
        os.remove(self.theme)
        self.assertFalse(s.refresh().enabled)
        self.assertTrue(apw.ThemeSettings(self.theme + ".missing").refresh().enabled)

    def test_super_g_still_arranges_when_switched_off(self):
        self.write_theme({"hypr_gaps_in": 5, "auto_place_windows": False})
        self.hypr.add("0xa", 0, 0, 800, 600)
        self.hypr.add("0xb", 1500, 900, 800, 600)  # stranded far from the other one
        with contextlib.redirect_stdout(io.StringIO()):
            arr.main()
        self.assertTrue(self.hypr.dispatched, "SUPER+G did nothing with auto-placement off")
        a, b = _rect(self.hypr.clients["0xa"]), _rect(self.hypr.clients["0xb"])
        _in_band(self, _sep(a, b))


class TestRealListenerAgainstFakeHyprland(_Base):
    """The real PlacementListener and real place_new_window together, fed a
    burst: windows mapped faster than they are placed (all already sitting
    on top of each other at the compositor's default spot) end up with no
    overlaps and exact gaps."""

    def test_burst(self):
        self.cluster()
        for i in range(6):
            self.hypr.open(f"0xk{i}", 640 + 20 * i, 400)
        listener = apw.PlacementListener(apw.ThemeSettings(os.path.join(self._tmp.name, "none.json")))
        statuses = [listener.handle_line(f"openwindow>>k{i},1,kitty,kitty") for i in range(6)]
        self.assertEqual(statuses, ["placed"] * 6)
        self.assert_no_overlap()


if __name__ == "__main__":
    unittest.main(verbosity=1)
