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


class TestLayoutModes(_Base):
    """Expansion, Spiral and Compact (the screen-bounded modes, chosen in
    Settings; the Galaxy Spiral stays the default), through the real
    listener, the real planner and the fake Hyprland."""

    def theme(self, data):
        path = os.path.join(self._tmp.name, "theme.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def listener(self, data=None):
        L = apw.PlacementListener(apw.ThemeSettings(self.theme(data or {})))
        L.settings.refresh()
        return L

    def open(self, L, addr, w=900, h=600, **kw):
        self.hypr.open(addr, w, h, **kw)
        return L.handle_line(f"openwindow>>{addr[2:]},1,app,x")

    def rects(self):
        return {a: tuple(c["at"]) + tuple(c["size"]) for a, c in self.hypr.clients.items()}

    def stage(self, mode_data, n=4):
        L = self.listener(mode_data)
        for i in range(n):
            self.assertEqual(self.open(L, f"0xw{i}"), "placed")
        return L

    def test_a_fresh_config_keeps_the_galaxy_spiral(self):
        # was "a fresh config uses Expansion": that silently replaced the
        # Galaxy Spiral on every existing install (no key in theme.json)
        self.assertEqual(lap.setting("auto_place", os.path.join(self._tmp.name, "none.json")), "galaxy")
        self.stage({}, 3)
        r = self.rects()
        for a in ("0xw0", "0xw1", "0xw2"):
            self.assertEqual(r[a][2:], (900, 600), f"{a}: the Galaxy Spiral never resizes a window")
        self.assert_no_overlap()

    def test_expansion_when_chosen_gives_the_newest_window_the_room(self):
        self.stage({"layout_auto_place": "expansion"}, 3)
        r = self.rects()
        newest = r["0xw2"]
        for a in ("0xw0", "0xw1"):
            self.assertGreater(newest[2] * newest[3], 1.5 * r[a][2] * r[a][3])
        self.assert_no_overlap()

    def test_each_mode_places_windows_differently_and_without_overlap(self):
        seen = {}
        for mode in ("expansion", "spiral", "compact"):
            self.hypr.clients.clear()
            self.stage({"layout_auto_place": mode}, 4)
            self.assert_no_overlap()
            seen[mode] = tuple(sorted(self.rects().items()))
        self.assertEqual(len(set(seen.values())), 3)

    def test_unknown_and_missing_values_fall_back_to_the_galaxy_spiral(self):
        # was "... fall back to Expansion" (the regression); see above
        for bad in ({"layout_auto_place": "grid"}, {"layout_auto_place": 7}, {"layout_auto_place": None}, {}):
            self.assertEqual(lap.setting("auto_place", self.theme(bad)), "galaxy", bad)
        for mode in ("galaxy", "Galaxy ", "expansion", "spiral", "compact"):
            self.assertEqual(lap.setting("auto_place", self.theme({"layout_auto_place": mode})), mode.strip().lower())
        with open(os.path.join(self._tmp.name, "torn.json"), "w") as f:
            f.write('{"layout_auto_p')
        self.assertEqual(lap.setting("auto_place", os.path.join(self._tmp.name, "torn.json")), "galaxy")

    def test_auto_place_and_super_g_are_separate_settings(self):
        t = self.theme({"layout_auto_place": "compact", "layout_super_g": "spiral"})
        self.assertEqual((lap.setting("auto_place", t), lap.setting("super_g", t)), ("compact", "spiral"))

    def test_closing_a_window_lays_the_rest_out_again(self):
        L = self.stage({"layout_auto_place": "compact"}, 4)
        before = self.rects()
        del self.hypr.clients["0xw1"]
        self.assertEqual(L.handle_line("closewindow>>w1"), "relaid")
        after = self.rects()
        self.assertEqual(set(after), {"0xw0", "0xw2", "0xw3"})
        self.assertNotEqual({a: after[a] for a in after}, {a: before[a] for a in after})
        self.assert_no_overlap()

    def test_repeating_the_layout_changes_nothing(self):
        self.stage({"layout_auto_place": "spiral"}, 4)
        self.hypr.dispatched.clear()
        moved, unplaced = lap.apply("spiral", 1, newest_is_primary=True)
        self.assertEqual((moved, unplaced), (0, []))
        self.assertEqual(self.hypr.dispatched, [])

    def test_super_g_expands_the_focused_window(self):
        self.stage({"layout_auto_place": "compact"}, 4)
        lap.apply("expansion", 1, primary_address="0xw1", newest_is_primary=False)
        r = self.rects()
        big = r["0xw1"]
        for a in ("0xw0", "0xw2", "0xw3"):
            self.assertGreater(big[2] * big[3], 1.5 * r[a][2] * r[a][3])
        self.assert_no_overlap()

    def test_pinned_fullscreen_and_hidden_windows_are_left_alone(self):
        for data in ({}, {"layout_auto_place": "expansion"}):
            with self.subTest(data=data):
                self.hypr.clients.clear()
                self._pinned_fullscreen_hidden(data)

    def _pinned_fullscreen_hidden(self, data):
        L = self.listener(data)
        self.open(L, "0xa")
        self.hypr.add("0xpin", 1500, 80, 380, 220, pinned=True)
        self.hypr.add("0xfs", 0, 0, 1920, 1080, fullscreen=2, workspace={"id": 2})
        self.hypr.add("0xhid", 10, 10, 400, 300, hidden=True)
        keep = {a: (tuple(self.hypr.clients[a]["at"]), tuple(self.hypr.clients[a]["size"])) for a in ("0xpin", "0xfs", "0xhid")}
        self.open(L, "0xb")
        for a, v in keep.items():
            self.assertEqual((tuple(self.hypr.clients[a]["at"]), tuple(self.hypr.clients[a]["size"])), v, a)

    def test_a_window_that_vanished_before_it_was_laid_out_is_a_safe_no_op(self):
        L = self.listener({"layout_auto_place": "expansion"})
        self.hypr.dispatched.clear()
        self.assertEqual(L.handle_line("openwindow>>dead,1,app,x"), "gone")
        self.assertEqual(self.hypr.dispatched, [])

    def test_two_monitors_each_get_their_own_area(self):
        monitors = [{"id": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1, "transform": 0,
                     "reserved": [0, 52, 0, 0], "focused": True},
                    {"id": 1, "x": 1920, "y": 0, "width": 2560, "height": 1440, "scale": 1, "transform": 0,
                     "reserved": [0, 0, 0, 0], "focused": False}]
        clients = [{"address": f"0x{i}", "at": [10, 10], "size": [600, 400], "floating": True, "workspace": {"id": 1},
                    "monitor": i % 2, "class": f"c{i}", "pid": 100 + i, "stableId": f"{i:x}", "mapped": True,
                    "hidden": False, "fullscreen": 0, "pinned": False, "xwayland": False} for i in range(1, 5)]
        moves, unplaced = lap.plan("compact", clients, monitors, 1, 5)
        self.assertEqual(unplaced, [])
        by = dict(moves)
        for a, (x, y, w, h) in by.items():
            mon = clients[int(a[2:]) - 1]["monitor"]
            x0, y0, x1, y1 = (0, 52, 1920, 1080) if mon == 0 else (1920, 0, 4480, 1440)
            self.assertTrue(x >= x0 and y >= y0 and x + w <= x1 and y + h <= y1, (a, by[a], mon))


class TestGalaxyRouting(_Base):
    """Which algorithm runs, through the real listener and SUPER+G's real
    entry point with nothing injected: the Galaxy Spiral unless a bounded
    mode was chosen. (The listener used to skip mode routing whenever a test
    injected `place`, so the real default path had no coverage at all.)"""

    def theme(self, data):
        path = os.path.join(self._tmp.name, "theme.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def listener(self, data):
        L = apw.PlacementListener(apw.ThemeSettings(self.theme(data)))
        L.settings.refresh()
        return L

    def spies(self):
        import unittest.mock as m
        galaxy = m.patch.object(apw, "place_new_window", wraps=apw.place_new_window)
        bounded = m.patch.object(apw, "place_in_layout", wraps=apw.place_in_layout)
        relay = m.patch.object(apw, "relayout_after_close", wraps=apw.relayout_after_close)
        g, b, r = galaxy.start(), bounded.start(), relay.start()
        self.addCleanup(galaxy.stop)
        self.addCleanup(bounded.stop)
        self.addCleanup(relay.stop)
        return g, b, r

    def test_a_missing_key_places_new_windows_with_the_galaxy_spiral(self):
        g, b, _ = self.spies()
        L = self.listener({})
        self.hypr.open("0xa", 900, 600)
        self.assertEqual(L.handle_line("openwindow>>a,1,app,x"), "placed")
        self.assertEqual((g.call_count, b.call_count), (1, 0))

    def test_galaxy_spiral_progression_matches_the_spiral_geometry(self):
        """Three windows opened in turn land where dxrice_spiral grows them:
        the anchor first, each next one further along, sizes untouched."""
        L = self.listener({"layout_auto_place": "galaxy"})
        sizes = [(1280, 720), (945, 521), (1065, 867)]
        for i, (w, h) in enumerate(sizes):
            self.hypr.open(f"0xg{i}", w, h)
            self.assertEqual(L.handle_line(f"openwindow>>g{i},1,app{i},x"), "placed")
        got = [tuple(self.hypr.clients[f"0xg{i}"]["at"]) + tuple(self.hypr.clients[f"0xg{i}"]["size"]) for i in range(3)]
        for (x, y, w, h), (sw, sh) in zip(got, sizes):
            self.assertEqual((w, h), (sw, sh))
        mon = apw.get_monitor_bounds(0)
        expect = dxrice_spiral.arrange(sizes, [], mon, dxrice_spiral.read_spacing())
        self.assertEqual([(x, y) for x, y, _w, _h in got][0], expect[0][:2], "the anchor is not where the spiral starts")
        # every later window touches the cloud at a spiral spacing, never on top of it
        self.assert_no_overlap()

    def test_closing_under_galaxy_takes_the_classic_path_not_a_relayout(self):
        _, _, r = self.spies()
        L = self.listener({})
        for i in range(3):
            self.hypr.open(f"0xc{i}", 800, 500)
            L.handle_line(f"openwindow>>c{i},1,app{i},x")
        del self.hypr.clients["0xc1"]
        self.assertIn(L.handle_line("closewindow>>c1"), ("closed", "reflowed"))
        self.assertEqual(r.call_count, 0)

    def test_a_bounded_mode_routes_to_the_layout_engine(self):
        for mode in ("expansion", "spiral", "compact"):
            with self.subTest(mode=mode):
                self.hypr.clients.clear()
                g, b, _ = self.spies()
                L = self.listener({"layout_auto_place": mode})
                self.hypr.open("0xm", 900, 600)
                L.handle_line("openwindow>>m,1,app,x")
                self.assertEqual(g.call_count, 0)
                self.assertEqual(b.call_args[0][2], mode)

    def test_a_settings_object_without_a_layout_means_galaxy(self):
        g, b, _ = self.spies()

        class Bare:
            gap, enabled = 5, True

            def refresh(self):
                return self
        L = apw.PlacementListener(Bare())
        self.hypr.open("0xz", 700, 500)
        L.handle_line("openwindow>>z,1,app,x")
        self.assertEqual((g.call_count, b.call_count), (1, 0))


class TestSuperGRouting(unittest.TestCase):
    """SUPER+G (dxrice_auto_arrange.py -> dxrice_layout_apply.main): the
    saved mode decides; no key, an unknown one, or --mode galaxy run the
    classic arrangement (dxrice_auto_arrange.main), never a bounded mode."""

    def setUp(self):
        import unittest.mock as m
        self._tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self._tmp.name, "dxrice"))
        self.path = os.path.join(self._tmp.name, "dxrice", "theme.json")
        self._env = m.patch.dict(os.environ, {"XDG_CONFIG_HOME": self._tmp.name})
        self._env.start()
        self.classic = m.patch.object(arr, "main", return_value=0)
        self.bounded = m.patch.object(lap, "apply", return_value=(0, []))
        self.ws = m.patch.object(lap, "hyprctl_json", side_effect=lambda a: {"id": 1} if a == ["activeworkspace"] else {})
        self.c, self.b, _ = self.classic.start(), self.bounded.start(), self.ws.start()

    def tearDown(self):
        for p in (self.classic, self.bounded, self.ws, self._env):
            p.stop()
        self._tmp.cleanup()

    def write(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f)

    def run_main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return lap.main(list(argv))

    def test_no_key_runs_the_classic_arrangement(self):
        self.write({"accent": "e67878"})
        self.run_main()
        self.assertEqual((self.c.call_count, self.b.call_count), (1, 0))

    def test_an_unknown_value_runs_the_classic_arrangement(self):
        self.write({"layout_super_g": "grid"})
        self.run_main()
        self.assertEqual((self.c.call_count, self.b.call_count), (1, 0))

    def test_a_saved_bounded_mode_runs_that_mode(self):
        self.write({"layout_super_g": "compact"})
        self.run_main()
        self.assertEqual(self.c.call_count, 0)
        self.assertEqual(self.b.call_args[0][0], "compact")

    def test_mode_galaxy_with_save_saves_galaxy_and_runs_the_classic_arrangement(self):
        # this used to save and run Expansion: "galaxy" was normalised away
        self.write({"layout_super_g": "compact", "accent": "e67878"})
        self.run_main("--mode", "galaxy", "--save")
        self.assertEqual(json.load(open(self.path)), {"layout_super_g": "galaxy", "accent": "e67878"})
        self.assertEqual((self.c.call_count, self.b.call_count), (1, 0))

    def test_the_auto_arrange_script_goes_through_the_router(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_auto_arrange.py")).read()
        tail = src[src.index('if __name__ == "__main__":'):]
        self.assertIn("dxrice_layout_apply.main()", tail)


if __name__ == "__main__":
    unittest.main(verbosity=1)
