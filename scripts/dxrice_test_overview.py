#!/usr/bin/env python3
"""The desktop overview's geometry (dxrice_overview.py): which windows it
shows, in what order, and where -- against synthetic `hyprctl` data, no
compositor.

    python3 scripts/dxrice_test_overview.py [-v]
"""
import io
import json
import os
import random
import sys
import time
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_overview as ov  # noqa: E402
import dxrice_spiral as sp  # noqa: E402
import dxrice_hypr_ipc  # noqa: E402

BAND = (sp.SPACING_MIN_DEFAULT, sp.SPACING_MAX_DEFAULT)
RESERVED = [0, 52, 0, 68]                      # DXrice's bar and dock
USABLE = (0, 52, 1920, 1012)


def monitor(name="DP-1", mid=0, x=0, y=0, w=1920, h=1080, scale=1.0, transform=0, ws=1, focused=True,
            reserved=None, special=0):
    return {"id": mid, "name": name, "x": x, "y": y, "width": w, "height": h, "scale": scale,
            "transform": transform, "focused": focused, "activeWorkspace": {"id": ws},
            "specialWorkspace": {"id": special}, "reserved": list(RESERVED if reserved is None else reserved)}


def client(i, rect, ws=1, mon=0, **extra):
    x0, y0, x1, y1 = rect
    c = {"address": f"0x{i:04x}", "at": [x0, y0], "size": [x1 - x0, y1 - y0], "workspace": {"id": ws},
         "monitor": mon, "mapped": True, "hidden": False, "floating": True, "fullscreen": 0, "pinned": False,
         "focusHistoryID": i, "class": "app", "title": f"w{i}"}
    c.update(extra)
    return c


def spiral_clients(sizes, usable=USABLE):
    return [client(i, r) for i, r in enumerate(sp.arrange(sizes, [], usable, BAND))]


def bbox(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


REF = [(381, 225)] + [(262, 125)] * 31
MIXED = [(1100, 700), (860, 560), (640, 400), (900, 620), (550, 300), (1000, 650), (820, 560), (480, 320),
         (700, 460), (760, 480), (600, 380), (920, 600), (520, 340), (780, 500), (660, 420), (840, 540)]


class TestMonitorArea(unittest.TestCase):
    def test_same_arithmetic_as_usable_bounds(self):
        """monitor_rect is a copy of dxrice_auto_place_window.usable_bounds
        (that module is too slow to import on a keypress): they must agree
        for every scale, rotation and reservation."""
        from dxrice_auto_place_window import usable_bounds
        for m in (monitor(), monitor(scale=1.25, w=2560, h=1440), monitor(transform=1), monitor(transform=3, scale=2),
                  monitor(x=1920, y=-200, reserved=[40, 0, 0, 30]), monitor(reserved=[2000, 0, 0, 0]),
                  monitor(reserved=None) | {"reserved": None}):
            self.assertEqual(ov.monitor_rect(m)[0], usable_bounds(m), m)


class TestMembers(unittest.TestCase):
    def test_the_active_workspace_and_pinned_windows_only(self):
        m = monitor(ws=3)
        cl = [client(1, (0, 0, 100, 100), ws=3), client(2, (0, 0, 100, 100), ws=4),
              client(3, (0, 0, 100, 100), ws=4, pinned=True), client(4, (0, 0, 100, 100), ws=4, pinned=True, monitor=1),
              client(5, (0, 0, 100, 100), ws=3, hidden=True), client(6, (0, 0, 100, 100), ws=3, mapped=False),
              client(7, (0, 0, 1, 1), ws=3)]
        # both floating: the more recently focused (lower focusHistoryID) on top
        self.assertEqual([c["address"] for c in ov.members(cl, m)], ["0x0003", "0x0001"])

    def test_a_shown_special_workspace_is_included(self):
        m = monitor(ws=2, special=-98)
        cl = [client(1, (0, 0, 100, 100), ws=2), client(2, (0, 0, 100, 100), ws=-98)]
        self.assertEqual(len(ov.members(cl, m)), 2)

    def test_stacking_order(self):
        """Bottom first: tiled, then floating/pinned, then fullscreen; within
        each, the least recently focused first (the most recent on top)."""
        cl = [client(1, (0, 0, 10, 10), floating=False, focusHistoryID=0),
              client(2, (0, 0, 10, 10), floating=False, focusHistoryID=3),
              client(3, (0, 0, 10, 10), focusHistoryID=1),
              client(4, (0, 0, 10, 10), focusHistoryID=5),
              client(5, (0, 0, 10, 10), fullscreen=2, focusHistoryID=9),
              client(6, (0, 0, 10, 10), pinned=True, focusHistoryID=2)]
        self.assertEqual([c["address"] for c in ov.members(cl, monitor())],
                         ["0x0002", "0x0001", "0x0004", "0x0006", "0x0003", "0x0005"])


class TestFit(unittest.TestCase):
    def test_windows_already_on_screen_are_not_zoomed(self):
        o = ov.overview([client(1, (300, 200, 1100, 800)), client(2, (1200, 300, 1800, 900))], [monitor()])
        self.assertTrue(o["fits"])
        self.assertEqual(o["scale"], 1.0)
        for w in o["windows"]:
            self.assertEqual((w["tx"], w["ty"], w["tw"], w["th"]), (w["x"], w["y"], w["w"], w["h"]))

    def test_one_window_on_screen_is_left_exactly_where_it_is(self):
        o = ov.overview([client(1, (410, 182, 1510, 882))], [monitor()])
        w = o["windows"][0]
        self.assertEqual((w["x"], w["y"]), (410, 130))  # relative to the usable area (bar: 52 px)
        self.assertEqual((w["tx"], w["ty"], w["tw"], w["th"]), (410, 130, 1100, 700))

    def test_a_window_past_the_edge_zooms_out_to_show_it(self):
        o = ov.overview([client(1, (300, 200, 1100, 800)), client(2, (1700, 600, 2500, 1300))], [monitor()])
        self.assertFalse(o["fits"])
        self.assertLess(o["scale"], 1.0)
        self.assert_inside(o)

    def assert_inside(self, o, margin=ov.OVERVIEW_MARGIN):
        W, H = o["monitor"]["width"], o["monitor"]["height"]
        for w in o["windows"]:
            self.assertGreaterEqual(w["tx"], margin - 0.6, w)
            self.assertGreaterEqual(w["ty"], margin - 0.6, w)
            self.assertLessEqual(w["tx"] + w["tw"], W - margin + 0.6, w)
            self.assertLessEqual(w["ty"] + w["th"], H - margin + 0.6, w)

    def assert_one_view_transform(self, o):
        """Every window goes through the same p' = p*scale + d: relative
        positions, sizes, spacing and aspect ratios are all kept -- the
        composition is shrunk, not rearranged."""
        s = o["scale"]
        w0 = o["windows"][0]
        dx, dy = w0["tx"] - w0["x"] * s, w0["ty"] - w0["y"] * s
        for w in o["windows"]:
            # positions are rounded to 1/100 px
            self.assertAlmostEqual(w["tx"], w["x"] * s + dx, delta=0.05)
            self.assertAlmostEqual(w["ty"], w["y"] * s + dy, delta=0.05)
            self.assertAlmostEqual(w["tw"], w["w"] * s, delta=0.05)
            self.assertAlmostEqual(w["th"], w["h"] * s, delta=0.05)

    def assert_centred(self, o):
        W, H = o["monitor"]["width"], o["monitor"]["height"]
        b = bbox([(w["tx"], w["ty"], w["tx"] + w["tw"], w["ty"] + w["th"]) for w in o["windows"]])
        self.assertAlmostEqual((b[0] + b[2]) / 2, W / 2, delta=1)
        self.assertAlmostEqual((b[1] + b[3]) / 2, H / 2, delta=1)

    def test_spirals_of_every_size_fit_centred_and_unchanged_in_shape(self):
        for name, sizes in (("2 windows", MIXED[:2]), ("6", MIXED[:6]), ("12", MIXED[:12]), ("16 mixed", MIXED),
                            ("16 reference", REF[:16]), ("32 reference", REF)):
            with self.subTest(name):
                o = ov.overview(spiral_clients(sizes), [monitor()])
                self.assertEqual(len(o["windows"]), len(sizes))
                if o["fits"]:
                    continue
                self.assert_inside(o)
                self.assert_one_view_transform(o)
                self.assert_centred(o)
                # tight on at least one axis: zoomed exactly as far as needed
                W, H = o["monitor"]["width"], o["monitor"]["height"]
                b = bbox([(w["tx"], w["ty"], w["tx"] + w["tw"], w["ty"] + w["th"]) for w in o["windows"]])
                self.assertTrue(abs((b[2] - b[0]) - (W - 2 * ov.OVERVIEW_MARGIN)) < 1
                                or abs((b[3] - b[1]) - (H - 2 * ov.OVERVIEW_MARGIN)) < 1, b)

    def test_extreme_wide_and_tall_windows(self):
        wide = [(1500, 420), (1300, 300), (900, 260), (1600, 340), (1100, 280), (1400, 360), (1000, 300), (1500, 320)]
        tall = [(700, 900), (380, 900), (300, 760), (420, 1000), (340, 820), (400, 940), (320, 780), (360, 880)]
        for sizes in (wide, tall):
            o = ov.overview(spiral_clients(sizes), [monitor()])
            self.assert_inside(o)
            self.assert_one_view_transform(o)

    def test_a_huge_composition_stops_at_the_minimum_scale(self):
        cl = [client(1, (-20000, -20000, -19000, -19500)), client(2, (20000, 20000, 21000, 20500))]
        o = ov.overview(cl, [monitor()])
        self.assertEqual(o["scale"], ov.MIN_SCALE)
        self.assertTrue(o["clipped"])
        self.assert_centred(o)
        self.assert_one_view_transform(o)

    def test_fullscreen_and_pinned_windows_are_shown_where_they_are(self):
        cl = spiral_clients(MIXED[:6])
        cl.append(client(50, (0, 0, 1920, 1080), fullscreen=2, focusHistoryID=0))
        cl.append(client(51, (1500, 80, 1900, 380), ws=7, pinned=True))
        o = ov.overview(cl, [monitor()])
        self.assertEqual(o["windows"][-1]["address"], "0x0032", "the fullscreen window isn't on top")
        self.assertTrue(o["windows"][-1]["fullscreen"])
        self.assertIn("0x0033", [w["address"] for w in o["windows"]])
        self.assert_one_view_transform(o)
        self.assert_inside(o)

    def test_other_monitors_their_scale_and_rotation(self):
        """Each monitor shows its own active workspace, fitted to its own
        logical size; rects are relative to its usable area."""
        left = monitor("DP-1", 0, 0, 0, 1920, 1080, ws=1, focused=False)
        right = monitor("HDMI-A-1", 1, 1920, 0, 3200, 1800, scale=1.25, ws=2, focused=True, reserved=[0, 40, 0, 0])
        tall = monitor("DP-2", 2, -1080, 0, 1920, 1080, transform=1, ws=3, focused=False, reserved=[0, 0, 0, 0])
        r_rects = sp.arrange(MIXED[:10], [], (1920, 40, 1920 + 2560, 1440), BAND)
        cl = [client(i, r, ws=2, mon=1) for i, r in enumerate(r_rects)] + [client(90, (100, 100, 900, 700), ws=1)]
        cl += [client(91, (-1000, 100, -200, 1500), ws=3, mon=2)]
        o = ov.overview(cl, [left, right, tall])
        self.assertEqual(o["monitor"]["name"], "HDMI-A-1")
        self.assertEqual((o["monitor"]["width"], o["monitor"]["height"]), (2560, 1400))
        self.assertEqual(len(o["windows"]), 10)
        self.assert_inside(o)
        o2 = ov.overview(cl, [left, right, tall], "DP-2")
        self.assertEqual((o2["monitor"]["width"], o2["monitor"]["height"]), (1080, 1920))
        self.assertEqual([w["address"] for w in o2["windows"]], ["0x005b"])
        self.assertEqual((o2["windows"][0]["x"], o2["windows"][0]["y"]), (80, 100))

    def test_windows_opening_and_closing_while_open(self):
        """The overview re-reads Hyprland on every window event: the same
        inputs always give the same view, and a window opening or closing
        only adds or drops its own tile (the rest re-fit around it)."""
        cl = spiral_clients(MIXED[:10])
        a = ov.overview(cl, [monitor()])
        self.assertEqual(ov.overview(json.loads(json.dumps(cl)), [monitor()]), a)
        more = ov.overview(cl + [client(77, (2400, 900, 3000, 1300))], [monitor()])
        self.assertEqual(len(more["windows"]), 11)
        gone = cl[-1]["address"]
        less = ov.overview(cl[:-1], [monitor()])
        self.assertEqual([w["address"] for w in less["windows"]],
                         [w["address"] for w in a["windows"] if w["address"] != gone])
        for o in (more, less):
            self.assert_inside(o)

    def test_an_empty_workspace(self):
        o = ov.overview([client(1, (0, 0, 100, 100), ws=5)], [monitor(ws=1)])
        self.assertEqual(o["windows"], [])
        self.assertEqual(o["scale"], 1.0)


class TestReadOnly(unittest.TestCase):
    def test_main_only_reads(self):
        """Opening the overview can never move, resize or refocus a window:
        the module's entry point only ever queries Hyprland."""
        cl = spiral_clients(MIXED)
        calls = []

        def fake_json(args, timeout=2):
            calls.append(args[0])
            return {"clients": cl, "monitors": [monitor()]}[args[0]]

        def forbid(*a, **k):
            raise AssertionError("the overview dispatched something")

        saved = (ov.hyprctl_json, dxrice_hypr_ipc.dispatch, dxrice_hypr_ipc.batch, dxrice_hypr_ipc.batch_async,
                 dxrice_hypr_ipc.dispatch_async)
        ov.hyprctl_json = fake_json
        dxrice_hypr_ipc.dispatch = dxrice_hypr_ipc.batch = forbid
        dxrice_hypr_ipc.batch_async = dxrice_hypr_ipc.dispatch_async = forbid
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(ov.main([]), 0)
        finally:
            (ov.hyprctl_json, dxrice_hypr_ipc.dispatch, dxrice_hypr_ipc.batch, dxrice_hypr_ipc.batch_async,
             dxrice_hypr_ipc.dispatch_async) = saved
        self.assertEqual(sorted(set(calls)), ["clients", "monitors"])
        self.assertEqual(len(json.loads(buf.getvalue())["windows"]), 16)
        src = open(ov.__file__).read()
        for word in ("dispatch(", "batch(", "batch_async(", "move_window", "resize_window"):
            self.assertNotIn(word, src.replace("dispatches", ""), word)

    def test_no_compositor_prints_an_empty_overview(self):
        def boom(args, timeout=2):
            raise OSError("no socket")
        saved = ov.hyprctl_json
        ov.hyprctl_json = boom
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(ov.main([]), 1)
        finally:
            ov.hyprctl_json = saved
        self.assertIsNone(json.loads(buf.getvalue())["monitor"])


class TestPanTo(unittest.TestCase):
    def test_pan_to_centres_one_window_by_moving_all_floating_ones_together(self):
        """dxrice_navigate_windows.py --to ADDRESS (the overview's confirmed
        click on an off-screen window): every floating window of the active
        workspace moves by the same delta, the target ends up centred on the
        focused monitor, tiled windows and other workspaces are untouched,
        nothing but moves is sent."""
        import dxrice_navigate_windows as nav
        cl = spiral_clients(MIXED)
        cl.append(client(80, (100, 100, 900, 700), floating=False))
        cl.append(client(81, (100, 100, 900, 700), ws=2))
        sent = []
        saved = (nav.hyprctl_json, nav.batch_async, nav.focus_window)

        def fake(args, timeout=2):
            return {"activeworkspace": {"id": 1}, "clients": cl, "monitors": [monitor()]}[args[0]]
        nav.hyprctl_json, nav.batch_async = fake, sent.extend
        nav.focus_window = lambda *a: self.fail("pan_to focused something (the caller does)")
        try:
            target = cl[12]
            dx, dy = nav.pan_to(target["address"])
            self.assertIsNone(nav.pan_to("0xdead"))
        finally:
            nav.hyprctl_json, nav.batch_async, nav.focus_window = saved
        floating = [c for c in cl if c["workspace"]["id"] == 1 and c["floating"]]
        self.assertEqual(len(sent), len(floating))
        for c, expr in zip(floating, sent):
            self.assertIn(f'address:{c["address"]}', expr)
            self.assertIn(f'x = {int(c["at"][0] + dx)}, y = {int(c["at"][1] + dy)}', expr)
        self.assertEqual((target["at"][0] + target["size"][0] // 2 + dx, target["at"][1] + target["size"][1] // 2 + dy),
                         (960, 540))


class TestKeybinds(unittest.TestCase):
    """The overview's keys in the hyprland.lua template: present, unique,
    accepted by Hyprland's own parser, and visible to the drift checker
    (so an existing install is told they are new)."""

    TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hypr", "hyprland.lua")
    # ONE key for the overview: SUPER+Tab opens it and closes it again.
    KEYS = {" + Tab": "toggle"}
    # the separate zoom keys an earlier version bound -- gone for good
    OBSOLETE = (" + minus", " + KP_Subtract", " + SHIFT + equal", " + equal", " + KP_Add")
    SHELL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quickshell", "shell.qml")
    # `qs ipc` subcommands: `qs ipc call <target> show` runs `qs ipc show`
    # (lists the targets) and never calls the function -- which is how
    # SUPER+minus, bound to "show", silently did nothing.
    QS_IPC_SUBCOMMANDS = {"show", "call", "wait", "listen", "prop"}

    def ipc_functions(self):
        import re
        text = open(self.SHELL).read()
        out = {}
        for m in re.finditer(r'IpcHandler\s*\{\s*target:\s*"(\w+)"(.*?)\n    \}', text, re.S):
            out[m.group(1)] = re.findall(r'function\s+(\w+)\s*\(', m.group(2))
        return out

    def test_no_ipc_function_is_shadowed_by_a_qs_subcommand(self):
        funcs = self.ipc_functions()
        self.assertIn("overview", funcs)
        for target, names in funcs.items():
            self.assertEqual(set(names) & self.QS_IPC_SUBCOMMANDS, set(), target)

    def test_every_overview_bind_calls_a_function_that_exists(self):
        _text, found = self.binds()
        have = set(self.ipc_functions()["overview"])
        for key, action in found:
            self.assertIn(action, have, key)

    def binds(self):
        import re
        text = open(self.TEMPLATE).read()
        return text, re.findall(r'hl\.bind\(\s*mainMod\s*\.\.\s*"([^"]+)"\s*,\s*overview\("(\w+)"\)', text)

    def test_every_overview_key_and_its_action(self):
        _text, found = self.binds()
        self.assertEqual(found, list(self.KEYS.items()), "SUPER+Tab must be the overview's only key")

    def assert_no_obsolete_zoom_keys(self, text):
        import re
        for key in self.OBSOLETE:
            self.assertIsNone(re.search(r'hl\.bind\(\s*\w+\s*\.\.\s*"' + re.escape(key) + '"', text), key)
        self.assertNotIn("zoomOut", text)
        self.assertNotIn("zoomIn", text)

    def test_no_separate_zoom_keys_in_the_template(self):
        self.assert_no_obsolete_zoom_keys(open(self.TEMPLATE).read())

    def test_no_separate_zoom_keys_in_the_live_config(self):
        """The deployed ~/.config/hypr/hyprland.lua, where there is one (a
        real session; skipped in a sandbox with a throwaway HOME)."""
        live = os.path.join(os.path.expanduser("~"), ".config", "hypr", "hyprland.lua")
        if not os.path.exists(live):
            self.skipTest("no deployed hyprland.lua here")
        text = open(live).read()
        if "overview(" not in text:
            self.skipTest("the overview isn't wired into this config")
        self.assert_no_obsolete_zoom_keys(text)
        self.assertIn('mainMod .. " + Tab", overview("toggle")', text)

    def test_no_key_is_bound_twice(self):
        import re
        from collections import Counter
        text = open(self.TEMPLATE).read()
        combos = [b.strip().upper().replace(" ", "")
                  for b in re.findall(r'hl\.bind\(\s*(?:mainMod\s*\.\.\s*)?"([^"]+)"', text)]
        self.assertEqual([k for k, v in Counter(combos).items() if v > 1], [])

    def test_the_drift_checker_sees_them(self):
        import dxrice_check_hypr_drift as drift
        ids = drift._identities(open(self.TEMPLATE).read())
        for key in self.KEYS:
            self.assertIn(f"bind:{key}", ids)

    def test_hyprland_parses_every_key(self):
        """Hyprland's own --verify-config (no compositor started, nothing
        executed) on the real template; a bogus key name in a copy must be
        rejected, proving key names really are checked."""
        import shutil
        import subprocess
        import tempfile
        hypr = shutil.which("Hyprland")
        if not hypr:
            self.skipTest("Hyprland not installed")
        env = {k: v for k, v in os.environ.items()
               if k not in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DISPLAY")}
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.lua")
            bad = os.path.join(d, "bad.lua")
            text = open(self.TEMPLATE).read()
            open(good, "w").write(text)
            open(bad, "w").write(text.replace('mainMod .. " + Tab"', 'mainMod .. " + Tabbb"'))
            ok = subprocess.run([hypr, "--verify-config", "-c", good], capture_output=True, text=True,
                                timeout=60, env=env)
            self.assertIn("config ok", ok.stdout + ok.stderr)
            no = subprocess.run([hypr, "--verify-config", "-c", bad], capture_output=True, text=True,
                                timeout=60, env=env)
            self.assertIn("Tabbb", no.stdout + no.stderr)


class TestPerformance(unittest.TestCase):
    def test_layout_cost(self):
        """Computing the view is negligible next to starting Python: a few
        milliseconds even for 200 windows."""
        rng = random.Random(1)
        cl = [client(i, (x, y, x + rng.randint(200, 1200), y + rng.randint(150, 900)))
              for i in range(200) for x, y in [(rng.randint(-4000, 6000), rng.randint(-3000, 4000))]]
        t = time.perf_counter()
        for _ in range(20):
            ov.overview(cl, [monitor()])
        per = (time.perf_counter() - t) / 20 * 1000
        self.assertLess(per, 20, f"{per:.1f} ms")


if __name__ == "__main__":
    unittest.main()
