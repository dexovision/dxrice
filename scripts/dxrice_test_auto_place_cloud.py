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
import dxrice_layout_apply as lap
import dxrice_auto_arrange as arr
import dxrice_window_class as wc

GAP = 5
import dxrice_spiral  # noqa: E402
LO = dxrice_spiral.SPACING_MIN_DEFAULT
HI = dxrice_spiral.widest_gap((dxrice_spiral.SPACING_MIN_DEFAULT, dxrice_spiral.SPACING_MAX_DEFAULT))


def _in_band(tc, gap, msg=None):
    """A neighbour at the composition spacing: never under the minimum,
    never further than the spiral's widest gap (its outer turns)."""
    tc.assertTrue(LO - 0.5 <= gap <= HI + 0.5, msg or f"{gap}px is not the composition spacing")
MON = (0, 0, 1920, 1080)


def _rect(c):
    return (c["at"][0], c["at"][1], c["at"][0] + c["size"][0], c["at"][1] + c["size"][1])


def _sep(a, b):
    """Daylight between two rects, the same in every direction (corner to
    corner for diagonal pairs, dxrice_spiral.dist); <= 0 touching or
    overlapping."""
    return dxrice_spiral.dist(a, b)


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
                       wc.x11_windows, lap.hyprctl_json, lap.batch_async)
        h = self.hypr
        apw.hyprctl_json, apw.dispatch_async, apw.batch_async = h.hyprctl_json, h.dispatch_async, h.batch_async
        apw.move_window_exact_async = h.move_window_exact_async
        lap.hyprctl_json, lap.batch_async = h.hyprctl_json, h.batch_async
        apw.get_monitor_bounds = lambda *_: MON
        apw.time.sleep = lambda s: None
        arr.hyprctl_json, arr.batch_async = h.hyprctl_json, h.batch_async
        arr.live_gap, arr.get_monitor_bounds = (lambda: GAP), (lambda *_: MON)
        wc.x11_windows = lambda display=None: self.X11
        apw.classify_clients = lambda clients: wc.classify_all(clients)

    def tearDown(self):
        (apw.hyprctl_json, apw.dispatch_async, apw.batch_async, apw.move_window_exact_async,
         apw.get_monitor_bounds, apw.time.sleep, apw.classify_clients,
         arr.hyprctl_json, arr.batch_async, arr.live_gap, arr.get_monitor_bounds,
         wc.x11_windows, lap.hyprctl_json, lap.batch_async) = self._saved
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
        prominence, so SUPER+G now re-winds about half of them (58/120 kept
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

    def test_first_window_mapped_centred_needs_no_move(self):
        """The first window is the spiral's anchor at the usable area's
        centre; one Hyprland already mapped there is not moved at all."""
        self.hypr.open("0xonly", 900, 600)
        self.assertEqual(apw.place_new_window("0xonly", 1, GAP), "placed")
        self.assertEqual(self.hypr.dispatched, [])

    def test_first_window_becomes_the_anchor_at_the_usable_centre(self):
        """Changed by the spiral-growth pass (this used to leave the first
        window wherever it mapped): it is moved to the centre of the usable
        area -- the monitor minus reserved bars (get_monitor_bounds)."""
        usable = (0, 52, 1920, 1012)
        apw.get_monitor_bounds = lambda *_: usable
        self.hypr.add("0xonly", 40, 600, 900, 600)
        self.assertEqual(apw.place_new_window("0xonly", 1, GAP), "placed")
        r = _rect(self.hypr.clients["0xonly"])
        self.assertEqual(((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), (960, 532))


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


class TestLauncherHandoff(_Base):
    """Bug report: the first three windows were placed right, the fourth
    landed far lower, and SUPER+G put it back. The sequence that does that:
    an app's launcher/updater/splash window is mapped first (and placed, as
    any window is), the real window maps while it is still up and is placed
    one step further along the spiral -- after the launcher -- and then the
    launcher closes. The real window kept a place reckoned from a window
    that no longer exists; SUPER+G replays the spiral without it. (Discord's
    updater window giving way to the main window is one documented case.)

    Driven through the real PlacementListener and place_new_window."""

    SIZES = [(1280, 720), (945, 521), (1065, 867)]

    def setUp(self):
        super().setUp()
        # these test the classic (Galaxy Spiral) placement and its launcher hand-off
        classic = os.path.join(self._tmp.name, "classic.json")
        with open(classic, "w") as f:
            json.dump({"layout_auto_place": "galaxy"}, f)
        self.listener = apw.PlacementListener(apw.ThemeSettings(classic))
        self.listener.settings.refresh()
        apw.PLACED.clear()
        self._err = contextlib.redirect_stderr(io.StringIO())
        self._err.__enter__()

    def tearDown(self):
        self._err.__exit__(None, None, None)
        super().tearDown()

    def open(self, addr, w, h, **kw):
        self.hypr.open(addr, w, h, **kw)
        return self.listener.handle_line(f"openwindow>>{addr[2:]},1,{kw.get('cls', 'app')},x")

    def close(self, addr):
        del self.hypr.clients[addr]
        return self.listener.handle_line(f"closewindow>>{addr[2:]}")

    def press(self):
        """SUPER+G; returns how far it moved each window."""
        before = {a: tuple(c["at"]) for a, c in self.hypr.clients.items()}
        with contextlib.redirect_stdout(io.StringIO()):
            arr.main()
        return {a: (c["at"][0] - before[a][0], c["at"][1] - before[a][1]) for a, c in self.hypr.clients.items()}

    def without_launcher(self, last):
        """Where `last` goes when there never was a launcher (control)."""
        saved = (dict(self.hypr.clients), dict(apw.PLACED))
        self.hypr.clients.clear()
        apw.PLACED.clear()
        for i, (w, h) in enumerate(self.SIZES):
            self.open(f"0xc{i}", w, h, cls=f"app{i}")
        self.open("0xcz", *last, cls="game")
        at = tuple(self.hypr.clients["0xcz"]["at"])
        self.hypr.clients.clear()
        self.hypr.clients.update(saved[0])
        apw.PLACED.clear()
        apw.PLACED.update(saved[1])
        return at

    def three(self):
        for i, (w, h) in enumerate(self.SIZES):
            self.assertEqual(self.open(f"0xw{i}", w, h, cls=f"app{i}"), "placed")

    def test_the_fourth_window_after_a_launcher_that_closes(self):
        want = self.without_launcher((924, 512))
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.open("0xw3", 924, 512, cls="game")
        status = self.close("0xla")
        self.assertEqual(tuple(self.hypr.clients["0xw3"]["at"]), want)
        self.assertEqual(set(self.press().values()), {(0, 0)}, "SUPER+G still had to fix the layout")
        self.assert_no_overlap()
        self.assertEqual(status, "reflowed")

    def test_launcher_closing_before_the_real_window_needs_nothing(self):
        want = self.without_launcher((924, 512))
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.assertEqual(self.close("0xla"), "closed")
        self.open("0xw3", 924, 512, cls="game")
        self.assertEqual(tuple(self.hypr.clients["0xw3"]["at"]), want)
        self.assertEqual(set(self.press().values()), {(0, 0)})

    def test_a_splash_that_was_the_first_window(self):
        """The splash was the anchor at the centre; the real window was put
        beside it. Once the splash goes, the real window is the anchor."""
        self.open("0xsp", 300, 350, cls="discord", pid=77)
        self.open("0xd", 1280, 720, cls="discord", pid=77)
        status = self.close("0xsp")
        for i, (w, h) in enumerate(self.SIZES[1:], 1):
            self.open(f"0xw{i}", w, h, cls=f"app{i}")
        self.assertEqual(set(self.press().values()), {(0, 0)})
        self.assert_no_overlap()
        self.assertEqual(status, "reflowed")

    def test_two_windows_after_the_launcher(self):
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.open("0xw3", 924, 512, cls="game")
        self.open("0xw4", 640, 400, cls="tool")
        status = self.close("0xla")
        self.assertEqual(set(self.press().values()), {(0, 0)})
        self.assert_no_overlap()
        self.assertEqual(status, "reflowed")

    def test_a_window_the_user_moved_stays_put(self):
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.open("0xw3", 924, 512, cls="game")
        self.hypr.clients["0xw3"]["at"] = [100, 100]   # dragged it already
        self.hypr.dispatched.clear()
        self.close("0xla")
        self.assertEqual(self.hypr.clients["0xw3"]["at"], [100, 100])
        self.assertEqual(self.hypr.dispatched, [])

    def test_a_window_sent_to_another_workspace_stays_put(self):
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.open("0xw3", 924, 512, cls="game")
        self.hypr.clients["0xw3"]["workspace"] = {"id": 3}   # SUPER+SHIFT+3 right after it opened
        self.hypr.dispatched.clear()
        self.close("0xla")
        self.assertEqual(self.hypr.dispatched, [])

    def test_closing_another_window_right_after_opening_one_moves_nothing(self):
        """Not a hand-off: the window closed isn't the one the new window
        was placed after, so the new window stays where it is (and the
        windows placed after the closed one were placed long ago)."""
        clock = [apw._now()]
        real_now = apw._now
        apw._now = lambda: clock[0]
        try:
            self.three()
            clock[0] += 30.0                       # the desktop has been in use a while
            self.open("0xw3", 924, 512, cls="term")
            clock[0] += 1.0
            self.hypr.dispatched.clear()
            self.assertEqual(self.close("0xw0"), "closed")   # the anchor, a second later
            self.assertEqual(self.close("0xw1"), "closed")
        finally:
            apw._now = real_now
        self.assertEqual(self.hypr.dispatched, [])

    def test_closing_an_old_window_the_new_one_followed_moves_nothing(self):
        """The window just before it, but opened long before (not a launcher
        handing over): closing it moves nothing either."""
        clock = [apw._now()]
        real_now = apw._now
        apw._now = lambda: clock[0]
        try:
            self.three()
            clock[0] += 120.0                      # w2 has been open two minutes
            self.open("0xw3", 924, 512, cls="term")
            clock[0] += 1.0
            self.hypr.dispatched.clear()
            self.assertEqual(self.close("0xw2"), "closed")
        finally:
            apw._now = real_now
        self.assertEqual(self.hypr.dispatched, [])

    def test_an_old_window_closing_moves_nothing(self):
        """Closing any window later is not a hand-off: the windows opened
        after it stay where they are (holes are SUPER+G's job)."""
        self.three()
        clock = [apw._now()]
        real_now = apw._now
        apw._now = lambda: clock[0]
        try:
            self.open("0xw3", 924, 512, cls="game")
            clock[0] += self.listener.HANDOFF_S + 0.5
            self.hypr.dispatched.clear()
            self.assertEqual(self.close("0xw2"), "closed")
        finally:
            apw._now = real_now
        self.assertEqual(self.hypr.dispatched, [])

    def test_a_window_on_another_workspace_is_not_affected(self):
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.hypr.open("0xo", 700, 500, cls="other", workspace={"id": 2})
        self.listener.handle_line("openwindow>>o,2,other,x")
        at = tuple(self.hypr.clients["0xo"]["at"])
        self.close("0xla")
        self.assertEqual(tuple(self.hypr.clients["0xo"]["at"]), at)

    def test_off_when_switched_off(self):
        self.three()
        self.open("0xla", 945, 521, cls="launcher")
        self.open("0xw3", 924, 512, cls="game")
        theme = os.path.join(self._tmp.name, "off.json")
        with open(theme, "w") as f:
            json.dump({"auto_place_windows": False}, f)
        self.listener.settings = apw.ThemeSettings(theme)
        self.hypr.dispatched.clear()
        self.assertEqual(self.close("0xla"), "closed")
        self.assertEqual(self.hypr.dispatched, [])

    def test_the_journal_names_no_titles(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.hypr.open("0xs", 900, 600, cls="kitty", title="secret-document.pdf - Viewer")
            self.listener.handle_line("openwindow>>s,1,kitty,x")
        self.assertIn("placement placed 0xs class='kitty' size=900x600", buf.getvalue())
        self.assertNotIn("secret", buf.getvalue())


class _MethodBase(_Base):
    """The real listener (nothing injected), the real algorithms and the
    fake Hyprland, with theme.json saying which method new windows use."""

    def theme(self, data):
        path = os.path.join(self._tmp.name, "theme.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def listener(self, data):
        L = apw.PlacementListener(apw.ThemeSettings(self.theme(data)))
        L.settings.refresh()
        return L

    def open(self, L, addr, w=900, h=600, **kw):
        self.hypr.open(addr, w, h, **kw)
        return L.handle_line(f"openwindow>>{addr[2:]},1,app{addr},x")

    def rects(self):
        return {a: tuple(c["at"]) + tuple(c["size"]) for a, c in self.hypr.clients.items()}

    def nearest_gap(self, addr):
        me = _rect(self.hypr.clients[addr])
        return min(_sep(me, _rect(c)) for a, c in self.hypr.clients.items() if a != addr)

    def spies(self):
        import unittest.mock as m
        place = m.patch.object(apw, "place_new_window", wraps=apw.place_new_window)
        p = place.start()
        self.addCleanup(place.stop)
        return p


SIZES5 = [(1100, 700), (900, 600), (820, 540), (760, 520), (700, 480)]


class TestMethodRouting(_MethodBase):
    """Which algorithm a new window gets: the saved method, reaching
    place_new_window as `method`. Galaxy and Spiral are one method; missing
    and unknown values are Galaxy."""

    def method_for(self, data):
        p = self.spies()
        L = self.listener(data)
        self.open(L, "0xa")
        return p.call_args.kwargs.get("method")

    def test_each_saved_method_reaches_the_placer(self):
        for saved, method in (("galaxy", "galaxy"), ("compact", "compact"), ("expansion", "expansion"),
                              ("spiral", "galaxy"), ("Compact ", "compact")):
            with self.subTest(saved=saved):
                self.hypr.clients.clear()
                self.assertEqual(self.method_for({"layout_auto_place": saved}), method)

    def test_missing_and_unknown_values_are_galaxy(self):
        for data in ({}, {"layout_auto_place": "grid"}, {"layout_auto_place": 7}, {"layout_auto_place": None}):
            with self.subTest(data=data):
                self.hypr.clients.clear()
                self.assertEqual(self.method_for(data), "galaxy")
        with open(os.path.join(self._tmp.name, "torn.json"), "w") as f:
            f.write('{"window_lay')
        self.assertEqual(lap.mode(os.path.join(self._tmp.name, "torn.json")), "galaxy")

    def test_there_are_exactly_three_methods(self):
        self.assertEqual(lap.CHOICES, ("galaxy", "compact", "expansion"))
        self.assertEqual(lap.resolve("spiral"), "galaxy")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_layouts.py")),
                         "the screen-bounded tiling layouts are gone")

    def test_a_settings_object_without_a_layout_means_galaxy(self):
        p = self.spies()

        class Bare:
            gap, enabled = 5, True

            def refresh(self):
                return self
        L = apw.PlacementListener(Bare())
        self.hypr.open("0xz", 700, 500)
        L.handle_line("openwindow>>z,1,app,x")
        self.assertEqual(p.call_args.kwargs.get("method"), "galaxy")

    def test_closing_a_window_moves_nothing_outside_galaxy(self):
        for mode in ("compact", "expansion"):
            with self.subTest(mode=mode):
                self.hypr.clients.clear()
                L = self.listener({"layout_auto_place": mode})
                for i, (w, h) in enumerate(SIZES5[:3]):
                    self.open(L, f"0xc{i}", w, h)
                before = self.rects()
                self.hypr.dispatched.clear()
                del self.hypr.clients["0xc1"]
                self.assertEqual(L.handle_line("closewindow>>c1"), "closed")
                self.assertEqual(self.hypr.dispatched, [])
                self.assertEqual({a: r for a, r in self.rects().items()}, {a: before[a] for a in ("0xc0", "0xc2")})


class TestMethodGeometry(_MethodBase):
    """What each method does to real windows opened one after another."""

    def stage(self, mode, sizes=SIZES5):
        L = self.listener({"layout_auto_place": mode})
        history = []
        for i, (w, h) in enumerate(sizes):
            before = self.rects()
            self.assertEqual(self.open(L, f"0xw{i}", w, h), "placed")
            after = self.rects()
            # opening a window never moves or resizes any other one
            self.assertEqual({a: after[a] for a in before}, before, f"{mode}: window {i} moved others")
            history.append(after)
        return history[-1]

    def test_galaxy_keeps_sizes_spaces_by_the_band_and_reaches_past_the_screen(self):
        sizes = [(1280, 720), (945, 521), (1065, 867), (800, 600), (900, 560), (700, 500)]
        r = self.stage("galaxy", sizes)
        for i, (w, h) in enumerate(sizes):
            self.assertEqual(r[f"0xw{i}"][2:], (w, h))
            if i:
                _in_band(self, self.nearest_gap(f"0xw{i}"))
        off = [a for a, (x, y, w, h) in r.items() if x < MON[0] or y < MON[1] or x + w > MON[2] or y + h > MON[3]]
        self.assertTrue(off, "six large windows must grow the spiral past the screen edge")
        self.assert_no_overlap()

    def test_galaxy_progression_is_the_spiral_geometry(self):
        sizes = [(1280, 720), (945, 521), (1065, 867)]
        r = self.stage("galaxy", sizes)
        expect = dxrice_spiral.arrange(sizes, [], MON, dxrice_spiral.read_spacing())
        self.assertEqual(r["0xw0"][:2], expect[0][:2], "the anchor is where the spiral starts")

    def test_compact_joins_tightly_at_the_hyprland_gap(self):
        self.stage("compact")
        for i in range(1, len(SIZES5)):
            self.assertLessEqual(self.nearest_gap(f"0xw{i}"), GAP + 0.5, f"window {i} is not packed against the cluster")
            self.assertGreaterEqual(self.nearest_gap(f"0xw{i}"), GAP - 0.5)
        self.assert_no_overlap()

    def test_expansion_keeps_sizes_and_the_airy_spacing(self):
        import dxrice_expansion
        r = self.stage("expansion")
        for i, (w, h) in enumerate(SIZES5):
            self.assertEqual(r[f"0xw{i}"][2:], (w, h))
            if i:
                self.assertAlmostEqual(self.nearest_gap(f"0xw{i}"), dxrice_expansion.spacing(), delta=1.5)
        self.assert_no_overlap()

    def test_expansion_grows_ring_by_ring_around_the_screen_centre(self):
        r = self.stage("expansion", [(900, 600)] * 5)
        centre = ((MON[0] + MON[2]) / 2, (MON[1] + MON[3]) / 2)
        c = {a: (x + w / 2, y + h / 2) for a, (x, y, w, h) in r.items()}
        self.assertLess(math.hypot(c["0xw0"][0] - centre[0], c["0xw0"][1] - centre[1]), 2, "the first window opens at the anchor")
        d = [math.hypot(c[f"0xw{i}"][0] - centre[0], c[f"0xw{i}"][1] - centre[1]) for i in range(5)]
        self.assertEqual(d, sorted(d), f"each new window is no nearer the centre than the last: {d}")
        # the second and third do not end up on the same side (no streak)
        v1 = (c["0xw1"][0] - centre[0], c["0xw1"][1] - centre[1])
        v2 = (c["0xw2"][0] - centre[0], c["0xw2"][1] - centre[1])
        self.assertLess(v1[0] * v2[0] + v1[1] * v2[1], 1, "the third window piled onto the second's side")

    def test_expansion_fills_the_same_spots_whatever_the_opening_order(self):
        import itertools
        spots = set()
        for order in itertools.islice(itertools.permutations(range(4)), 0, 24, 5):
            self.hypr.clients.clear()
            L = self.listener({"window_layout": "expansion"})
            for i in order:
                self.open(L, f"0xs{i}", 800, 500)
            spots.add(frozenset((x, y) for x, y, _w, _h in self.rects().values()))
        self.assertEqual(len(spots), 1, "the arrangement depended on which window opened first")

    def test_expansion_is_not_anchored_on_the_window_that_launched_it(self):
        # a terminal off to one side; a new window from the same program (same
        # pid, same size) still goes to the screen's middle, not beside it
        self.hypr.add("0xterm", 60, 60, 700, 450, pid=4242, **{"class": "kitty"})
        L = self.listener({"window_layout": "expansion"})
        self.hypr.open("0xnew", 700, 450, pid=4242, **{"class": "kitty"})
        L.handle_line("openwindow>>new,1,kitty,x")
        x, y, w, h = self.rects()["0xnew"]
        centre = ((MON[0] + MON[2]) / 2, (MON[1] + MON[3]) / 2)
        t = self.rects()["0xterm"]
        self.assertLess(math.hypot(x + w / 2 - centre[0], y + h / 2 - centre[1]),
                        math.hypot(x + w / 2 - (t[0] + t[2] / 2), y + h / 2 - (t[1] + t[3] / 2)),
                        "placed by its sibling, not by the composition")

    def test_expansion_ignores_windows_panned_out_of_view(self):
        # windows far off screen (the user panned away) are obstacles only:
        # they must not drag a new window off to them
        self.hypr.add("0xfar1", 5000, 3000, 900, 600)
        self.hypr.add("0xfar2", 6000, 3000, 900, 600)
        L = self.listener({"window_layout": "expansion"})
        self.open(L, "0xnew", 900, 600)
        x, y, w, h = self.rects()["0xnew"]
        self.assertTrue(MON[0] <= x and x + w <= MON[2] and MON[1] <= y and y + h <= MON[3], (x, y))

    def test_the_three_methods_place_the_same_windows_differently(self):
        placed = {}
        for mode in ("galaxy", "compact", "expansion"):
            self.hypr.clients.clear()
            placed[mode] = self.stage(mode)
        import itertools
        for a, b in itertools.combinations(placed, 2):
            d = sum(math.hypot(placed[a][k][0] + placed[a][k][2] / 2 - placed[b][k][0] - placed[b][k][2] / 2,
                               placed[a][k][1] + placed[a][k][3] / 2 - placed[b][k][1] - placed[b][k][3] / 2)
                    for k in placed[a]) / len(placed[a])
            self.assertGreater(d, 100, f"{a} and {b} put the windows in nearly the same places ({d:.0f}px)")

    def test_placement_is_deterministic(self):
        for mode in ("galaxy", "compact", "expansion"):
            with self.subTest(mode=mode):
                self.hypr.clients.clear()
                first = self.stage(mode)
                self.hypr.clients.clear()
                self.assertEqual(self.stage(mode), first)

    def test_pinned_fullscreen_and_hidden_windows_are_left_alone(self):
        for mode in ("galaxy", "compact", "expansion"):
            with self.subTest(mode=mode):
                self.hypr.clients.clear()
                L = self.listener({"layout_auto_place": mode})
                self.open(L, "0xa")
                self.hypr.add("0xpin", 1500, 80, 380, 220, pinned=True)
                self.hypr.add("0xfs", 0, 0, 1920, 1080, fullscreen=2, workspace={"id": 2})
                self.hypr.add("0xhid", 10, 10, 400, 300, hidden=True)
                keep = {a: (tuple(self.hypr.clients[a]["at"]), tuple(self.hypr.clients[a]["size"])) for a in ("0xpin", "0xfs", "0xhid")}
                self.open(L, "0xb")
                for a, v in keep.items():
                    self.assertEqual((tuple(self.hypr.clients[a]["at"]), tuple(self.hypr.clients[a]["size"])), v, a)


class TestExpansionAlgorithm(unittest.TestCase):
    """dxrice_expansion on its own: the Big Bang rules, in exact geometry."""

    def setUp(self):
        import dxrice_expansion
        self.E = dxrice_expansion
        self.band = (dxrice_spiral.SPACING_MIN_DEFAULT, dxrice_spiral.SPACING_MAX_DEFAULT)

    def arrange(self, windows, fixed=()):
        return self.E.arrange(windows, list(fixed), MON, self.band)

    @staticmethod
    def centre(r):
        return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)

    def test_sizes_are_kept_and_nothing_is_closer_than_the_spacing(self):
        wins = [(100 + 40 * i, 80 + 30 * i, w, h) for i, (w, h) in enumerate(SIZES5)]
        rs = self.arrange(wins)
        for (x, y, w, h), r in zip(wins, rs):
            self.assertEqual((r[2] - r[0], r[3] - r[1]), (w, h))
        gap = self.E.spacing(self.band)
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                apart = max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])
                self.assertGreaterEqual(apart, gap - 0.5, f"{i} and {j} are {apart}px apart")

    def test_the_largest_window_is_the_core_and_the_group_is_centred(self):
        wins = [(0, 0, 700, 480), (900, 0, 1100, 700), (0, 900, 820, 540), (900, 900, 760, 520)]
        rs = self.arrange(wins)
        bx = (min(r[0] for r in rs) + max(r[2] for r in rs)) / 2
        by = (min(r[1] for r in rs) + max(r[3] for r in rs)) / 2
        self.assertAlmostEqual(bx, 960, delta=1)
        self.assertAlmostEqual(by, 540, delta=1)
        core = rs[1]
        cc = self.centre(core)
        others = [math.hypot(*(a - b for a, b in zip(self.centre(r), cc))) for k, r in enumerate(rs) if k != 1]
        group = (sum(self.centre(r)[0] for r in rs) / 4, sum(self.centre(r)[1] for r in rs) / 4)
        self.assertLess(math.hypot(cc[0] - group[0], cc[1] - group[1]), min(others), "the largest window is the core")

    def test_windows_keep_their_order_around_the_centre(self):
        # four windows roughly at the compass points, in a scrambled list order
        wins = [(1500, 500, 600, 400), (900, 0, 600, 400), (300, 500, 600, 400), (900, 900, 600, 400), (800, 450, 900, 600)]
        rs = self.arrange(wins)
        def ring(rects, idx):
            c = (sum(self.centre(r)[0] for r in rects) / len(rects), sum(self.centre(r)[1] for r in rects) / len(rects))
            return sorted(idx, key=lambda k: math.atan2(self.centre(rects[k])[1] - c[1], self.centre(rects[k])[0] - c[0]))
        before = ring([(x, y, x + w, y + h) for x, y, w, h in wins], [0, 1, 2, 3])
        after = ring(rs, [0, 1, 2, 3])
        k = after.index(before[0])
        self.assertEqual(after[k:] + after[:k], before, "the cyclic order around the centre changed")

    def test_a_cascade_bursts_evenly_instead_of_into_a_line(self):
        wins = [(200 + 160 * i, 120 + 90 * i, w, h) for i, (w, h) in enumerate(SIZES5)]
        rs = self.arrange(wins)
        w = max(r[2] for r in rs) - min(r[0] for r in rs)
        h = max(r[3] for r in rs) - min(r[1] for r in rs)
        self.assertLess(max(w / h, h / w), 2.2, f"the burst is a streak ({w}x{h})")

    def test_a_fixed_window_is_kept_clear_of(self):
        fixed = [(860, 0, 1060, 1080)]     # a tall pinned strip through the middle
        rs = self.arrange([(0, 0, 600, 400), (0, 0, 500, 300), (0, 0, 400, 300)], fixed)
        for r in rs:
            self.assertTrue(r[2] <= fixed[0][0] or r[0] >= fixed[0][2], f"{r} lands on the fixed window")

    def test_it_is_deterministic(self):
        wins = [(100 + 40 * i, 80 + 30 * i, w, h) for i, (w, h) in enumerate(SIZES5)]
        self.assertEqual(self.arrange(wins), self.arrange(wins))

    def test_join_takes_the_nearest_free_spot_to_the_monitor_centre(self):
        layout = [(510, 240, 900, 600)]                  # one window, centred
        x, y = self.E.join((500, 300), layout, layout, MON, self.band)
        gap = self.E.spacing(self.band)
        r = (x, y, x + 500, y + 300)
        apart = max(r[0] - 1410, 510 - r[2], r[1] - 840, 240 - r[3])
        self.assertAlmostEqual(apart, gap, delta=1.5, msg="it sits one spacing from the centre window")

    def test_each_monitor_uses_its_own_centre(self):
        left = (0, 0, 1920, 1080)
        right = (1920, 0, 4480, 1440)
        for mon in (left, right):
            x, y = self.E.join((800, 500), [], [], mon, self.band)
            self.assertAlmostEqual(x + 400, (mon[0] + mon[2]) / 2, delta=1)
            self.assertAlmostEqual(y + 250, (mon[1] + mon[3]) / 2, delta=1)

    def test_it_is_not_the_spiral(self):
        sizes = SIZES5
        g = dxrice_spiral.arrange(sizes, [], MON, self.band)
        e = self.arrange([(100 + 40 * i, 80 + 30 * i, w, h) for i, (w, h) in enumerate(sizes)])
        d = sum(math.hypot(self.centre(a)[0] - self.centre(b)[0], self.centre(a)[1] - self.centre(b)[1]) for a, b in zip(g, e))
        self.assertGreater(d / len(sizes), 100)


class TestCompactAlgorithm(unittest.TestCase):
    """dxrice_compact (recovered) as SUPER+G runs it: it resizes, modestly,
    and is no grid. (Its full original suite is dxrice_test_compact.py.)"""

    def test_it_resizes_some_windows_within_bounds_and_overlaps_nothing(self):
        import dxrice_compact
        sizes = [(1100, 700), (900, 600), (820, 540), (760, 520), (700, 480), (660, 440)]
        eligible = [{"address": f"0x{i}", "at": [200 + 160 * i, 120 + 90 * i], "size": list(s), "class": f"a{i}", "pid": 10 + i}
                    for i, s in enumerate(sizes)]
        out = {a: (x, y, w, h) for a, x, y, w, h in dxrice_compact.auto_arrange(eligible, [], MON, GAP)}
        resized = [a for a, (_x, _y, w, h) in out.items() if (w, h) != tuple(sizes[int(a[2:])])]
        self.assertTrue(resized, "Compact is the method that resizes")
        for a, (_x, _y, w, h) in out.items():
            ow, oh = sizes[int(a[2:])]
            self.assertGreaterEqual(w, min(ow, apw.MIN_USABLE_WIDTH))
            self.assertGreaterEqual(h, min(oh, apw.MIN_USABLE_HEIGHT))
            self.assertGreaterEqual(w * h, ow * oh * (1 - apw.MAX_SHRINK_FRACTION) ** 2 - 1, "shrunk more than its bound")
        self.assertGreater(len({(w, h) for _x, _y, w, h in out.values()}), 1, "not every window gets one size")
        rs = [(x, y, x + w, y + h) for x, y, w, h in out.values()]
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                self.assertGreater(_sep(rs[i], rs[j]), 0, "overlap")


# (theme.json contents, the method both new windows and SUPER+G must use)
MIGRATION = [
    ({}, "galaxy"),
    ({"window_layout": "compact"}, "compact"),
    ({"window_layout": "expansion", "layout_auto_place": "compact", "layout_super_g": "galaxy"}, "expansion"),
    ({"window_layout": "spiral"}, "galaxy"),
    ({"window_layout": "grid", "layout_auto_place": "compact"}, "galaxy"),
    ({"layout_auto_place": "expansion", "layout_super_g": "galaxy"}, "expansion"),
    ({"layout_auto_place": "galaxy", "layout_super_g": "compact"}, "galaxy"),
    ({"layout_super_g": "compact"}, "compact"),
    ({"layout_auto_place": "spiral"}, "galaxy"),
    ({"layout_auto_place": None, "layout_super_g": "expansion"}, "expansion"),
]


class TestOneSetting(_MethodBase):
    """ONE method for new windows and SUPER+G (theme.json "window_layout"),
    with the documented migration from the two old settings."""

    def test_new_windows_and_super_g_resolve_the_same_method_from_any_file(self):
        import unittest.mock as m
        import dxrice_compact
        for data, expect in MIGRATION:
            with self.subTest(data=data):
                # new windows: the real listener
                self.hypr.clients.clear()
                p = self.spies()
                L = self.listener(data)
                self.open(L, "0xa")
                placed_with = p.call_args.kwargs.get("method")
                # SUPER+G: the real router, each algorithm's entry stubbed
                with m.patch.dict(os.environ, {"XDG_CONFIG_HOME": self._tmp.name}), \
                        m.patch.object(arr, "main", return_value=0) as g, \
                        m.patch.object(dxrice_compact, "main", return_value=0) as c, \
                        m.patch.object(lap, "expansion_main", return_value=0) as e:
                    os.makedirs(os.path.join(self._tmp.name, "dxrice"), exist_ok=True)
                    with open(os.path.join(self._tmp.name, "dxrice", "theme.json"), "w") as f:
                        json.dump(data, f)
                    with contextlib.redirect_stdout(io.StringIO()):
                        lap.main([])
                    ran = {"galaxy": g.call_count, "compact": c.call_count, "expansion": e.call_count}
                self.assertEqual(placed_with, expect)
                self.assertEqual(ran, {k: int(k == expect) for k in ran})

    def test_reading_never_writes(self):
        path = self.theme({"layout_auto_place": "compact", "layout_super_g": "expansion"})
        before = open(path).read()
        lap.mode(path)
        apw.ThemeSettings(path).refresh()
        self.assertEqual(open(path).read(), before)

    def test_saving_writes_the_one_key_and_drops_the_old_ones(self):
        path = self.theme({"layout_auto_place": "expansion", "layout_super_g": "galaxy", "accent": "e67878"})
        lap.save_mode("compact", path)
        self.assertEqual(json.load(open(path)), {"window_layout": "compact", "accent": "e67878"})
        lap.save_mode("spiral", path)
        self.assertEqual(json.load(open(path))["window_layout"], "galaxy")

    def test_a_change_reaches_a_running_listener(self):
        path = self.theme({"window_layout": "galaxy"})
        S = apw.ThemeSettings(path)
        S.refresh()
        self.assertEqual(S.layout, "galaxy")
        lap.save_mode("expansion", path)
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))   # a later write, as on disk
        S.refresh()
        self.assertEqual(S.layout, "expansion")


class TestSuperGRouting(unittest.TestCase):
    """SUPER+G (dxrice_auto_arrange.py -> dxrice_layout_apply.main) runs the
    one saved method; an overview chip (--mode M --save) changes it."""

    def setUp(self):
        import unittest.mock as m
        import dxrice_compact
        self._tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self._tmp.name, "dxrice"))
        self.path = os.path.join(self._tmp.name, "dxrice", "theme.json")
        self._patches = [m.patch.dict(os.environ, {"XDG_CONFIG_HOME": self._tmp.name}),
                         m.patch.object(arr, "main", return_value=0),
                         m.patch.object(dxrice_compact, "main", return_value=0),
                         m.patch.object(lap, "expansion_main", return_value=0)]
        started = [p.start() for p in self._patches]
        self.galaxy, self.compact, self.expansion = started[1], started[2], started[3]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def write(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f)

    def ran(self):
        return (self.galaxy.call_count, self.compact.call_count, self.expansion.call_count)

    def run_main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return lap.main(list(argv))

    def test_each_method_runs_its_own_algorithm(self):
        for saved, expect in (("galaxy", (1, 0, 0)), ("compact", (0, 1, 0)), ("expansion", (0, 0, 1)),
                              ("spiral", (1, 0, 0)), (None, (1, 0, 0)), ("grid", (1, 0, 0))):
            with self.subTest(saved=saved):
                for mk in (self.galaxy, self.compact, self.expansion):
                    mk.reset_mock()
                self.write({} if saved is None else {"window_layout": saved})
                self.run_main()
                self.assertEqual(self.ran(), expect)

    def test_a_chip_with_save_changes_the_one_method(self):
        self.write({"layout_auto_place": "compact", "layout_super_g": "expansion", "accent": "e67878"})
        self.run_main("--mode", "galaxy", "--save")
        self.assertEqual(json.load(open(self.path)), {"window_layout": "galaxy", "accent": "e67878"})
        self.assertEqual(self.ran(), (1, 0, 0))
        self.assertEqual(lap.mode(), "galaxy")

    def test_expansion_super_g_moves_only_and_keeps_sizes(self):
        eligible = [{"address": f"0x{i}", "at": [100 + 50 * i, 100 + 40 * i], "size": list(s)} for i, s in enumerate(SIZES5)]
        moves = lap.expansion_moves(eligible, [], MON)
        self.assertTrue(moves)
        self.assertEqual({len(m) for m in moves}, {3}, "Expansion only moves (address, x, y), never resizes")

    def test_the_auto_arrange_script_goes_through_the_router(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_auto_arrange.py")).read()
        tail = src[src.index('if __name__ == "__main__":'):]
        self.assertIn("dxrice_layout_apply.main()", tail)

    def test_nothing_else_reads_the_old_settings(self):
        here = os.path.dirname(os.path.abspath(__file__))
        repo = os.path.dirname(here)
        hits = []
        for d in ("scripts", "quickshell"):
            for name in os.listdir(os.path.join(repo, d)):
                if name.startswith("dxrice_test_") or not name.endswith((".py", ".qml", ".js")):
                    continue
                text = open(os.path.join(repo, d, name)).read()
                for key in ("layout_auto_place", "layout_super_g"):
                    if key in text and name not in ("dxrice_layout_apply.py", "Theme.qml", "ThemeEditor.qml"):
                        hits.append((name, key))
        self.assertEqual(hits, [], "only the migration rule and the editor's clean-up may name the old keys")


if __name__ == "__main__":
    unittest.main(verbosity=1)
