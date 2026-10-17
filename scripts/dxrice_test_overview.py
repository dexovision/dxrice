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
import re
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


class TestCompositorLayerFade(unittest.TestCase):
    """The double image seen on a real recording of SUPER+Tab: Hyprland fades
    every layer surface in and out (fadeLayersIn/Out, inherited from `fade`),
    so the opaque overview was composited at 0..100% over the real windows
    while its pictures moved. The template stops that for the overview's own
    namespace only (a layer rule with no_anim: in Hyprland 0.56 the animation
    tick finishes every animated value of such a layer at once, and its unmap
    takes no snapshot to fade); every other surface keeps its fade. Installs
    are brought forward by dxrice_hypr_migrate.py, which also takes out the
    global lines an earlier fix wrote."""

    TEMPLATE = TestKeybinds.TEMPLATE
    OVERVIEW_QML = os.path.join(os.path.dirname(TEMPLATE), "..", "quickshell", "Overview.qml")
    RULE = re.compile(r'hl\.layer_rule\(\{\s*name\s*=\s*"overview-no-anim",\s*'
                      r'match\s*=\s*\{\s*namespace\s*=\s*"([^"]+)"\s*\},\s*no_anim\s*=\s*true\s*\}\)')

    def test_the_rule_matches_the_overview_and_nothing_else(self):
        text = open(self.TEMPLATE).read()
        m = self.RULE.search(text)
        self.assertIsNotNone(m, "no overview-no-anim layer rule in the template")
        ns = re.search(r'WlrLayershell\.namespace:\s*"([^"]+)"', open(self.OVERVIEW_QML).read()).group(1)
        self.assertRegex(ns, m.group(1))
        for other in ("dxrice-bar-top", "dxrice-bar-dock", "dxrice-theme", "dxrice-osd", "wofi", "notifications"):
            self.assertIsNone(re.search(m.group(1), other), other)

    def test_every_other_surface_keeps_its_fade(self):
        text = open(self.TEMPLATE).read()
        self.assertNotIn("fadeLayers", re.sub(r"--[^\n]*", "", text), "a global layer-fade setting is back")
        self.assertRegex(text, r'hl\.animation\(\{ leaf = "fade", enabled = true')

    def verify(self, text):
        import shutil
        import subprocess
        import tempfile
        hypr = shutil.which("Hyprland")
        if not hypr:
            self.skipTest("Hyprland not installed")
        env = {k: v for k, v in os.environ.items()
               if k not in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DISPLAY")}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.lua")
            open(path, "w").write(text)
            r = subprocess.run([hypr, "--verify-config", "-c", path], capture_output=True, text=True,
                               timeout=60, env=env)
        return r.stdout + r.stderr

    def test_hyprland_accepts_the_rule(self):
        """Hyprland's own parser (nothing started or executed): the template
        is fine, and a made-up field in a copy is refused -- so no_anim is a
        real layer-rule field, not silently ignored."""
        text = open(self.TEMPLATE).read()
        self.assertIn("config ok", self.verify(text))
        self.assertIn("no_animm", self.verify(text.replace("no_anim = true", "no_animm = true")))

    def test_an_existing_install_is_told_about_the_rule(self):
        import dxrice_check_hypr_drift as drift
        self.assertIn("layer_rule:overview-no-anim", drift._identities(open(self.TEMPLATE).read()))


class TestPanDispatchShapes(unittest.TestCase):
    """The overview's pan sends hl.dsp.window.set_prop({ prop = "no_anim",
    value = ..., window = ... }) around each window move (Overview.qml
    _noAnimLua). Hyprland's parser checks a dispatcher's table when it is
    built, so binding the exact shapes in a copy of the template and running
    --verify-config (nothing started or executed) proves Hyprland accepts
    them; one without `value` is refused, proving the check is real. (The
    prop name itself is only read when it runs: no_anim is in Hyprland
    0.56.2's ConfigActions setProp list.)"""

    def bound(self, *exprs):
        text = open(TestKeybinds.TEMPLATE).read()
        keys = ["F9", "F10", "F11", "F12"]
        return text + "".join(f'hl.bind(mainMod .. " + SHIFT + {k}", {e})\n' for k, e in zip(keys, exprs))

    def test_hyprland_accepts_the_set_prop_shapes(self):
        qml = open(TestCompositorLayerFade.OVERVIEW_QML).read()
        self.assertIn("'hl.dsp.window.set_prop({ prop = \"no_anim\", value = \"' + value + '\", window = \"address:' "
                      "+ address + '\" })'", qml)
        out = TestCompositorLayerFade.verify(self, self.bound(
            'hl.dsp.window.set_prop({ prop = "no_anim", value = "1", window = "address:0x5a5a" })',
            'hl.dsp.window.set_prop({ prop = "no_anim", value = "unset", window = "address:0x5a5a" })'))
        self.assertIn("config ok", out)
        bad = TestCompositorLayerFade.verify(self, self.bound(
            'hl.dsp.window.set_prop({ prop = "no_anim", window = "address:0x5a5a" })'))
        self.assertNotIn("config ok", bad)
        self.assertIn("set_prop", bad)


class TestLayerRuleMigration(unittest.TestCase):
    """dxrice_hypr_migrate.py's overview-no-anim: adds the rule, and removes
    the global layer-fade lines only in the exact forms DXrice wrote them."""

    def setUp(self):
        import dxrice_hypr_migrate as m
        self.m = m
        self.base = re.sub(r'hl\.layer_rule\(\{ name = "overview-no-anim"[^\n]*\n', "",
                           open(TestKeybinds.TEMPLATE).read())

    def with_global(self, comment):
        anchor = 'hl.animation({ leaf = "workspaces"'
        i = self.base.index(anchor)
        j = self.base.index("\n", i) + 1
        return self.base[:j] + comment + self.m._GLOBAL_FADE_PAIR + self.base[j:]

    def migrated(self, text):
        return self.m.migrate(text, {"overview-no-anim"})

    def test_each_form_dxrice_wrote_is_replaced_by_the_rule(self):
        for comment in self.m._GLOBAL_FADE_COMMENTS + ("",):
            out = self.migrated(self.with_global(comment))
            self.assertNotIn("fadeLayers", re.sub(r"--[^\n]*", "", out), "a global line survived")
            self.assertEqual(out.count('namespace = "^dxrice-overview$" }, no_anim = true'), 1)
            self.assertEqual(out, self.migrated(self.base), "anything but the global lines changed")

    def test_a_global_line_the_user_changed_stays(self):
        text = self.with_global("").replace('"fadeLayersOut", enabled = false', '"fadeLayersOut", enabled = true')
        out = self.migrated(text)
        self.assertIn('"fadeLayersIn",  enabled = false', out)
        self.assertIn('"fadeLayersOut", enabled = true', out)
        self.assertIn("overview-no-anim", out)

    def test_twice_is_once(self):
        once = self.migrated(self.with_global(self.m._GLOBAL_FADE_COMMENTS[0]))
        self.assertEqual(self.migrated(once), once)
        self.assertNotIn("overview-no-anim", [mid for mid, _d in self.m.pending(once)])

    def test_hyprland_accepts_the_migrated_file(self):
        out = self.migrated(self.with_global(self.m._GLOBAL_FADE_COMMENTS[1]))
        self.assertIn("config ok", TestCompositorLayerFade.verify(self, out))


class TestRecordingProbe(unittest.TestCase):
    """scripts/dxrice_overview_probe.py tells a one-frame handover from a
    compositor fade by how many frames the bar takes to go, on synthetic
    recordings (a fixed 'bar' pattern replaced by 'wallpaper', instantly or
    blended over a quick-bezier ramp, under a uniform dim)."""

    def setUp(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("numpy not installed")
        import dxrice_overview_probe as probe
        self.np, self.probe = numpy, probe
        rng = numpy.random.RandomState(7)
        self.bar = rng.randint(0, 255, (40, 180)).astype(float)
        self.wall = rng.randint(60, 120, (40, 180)).astype(float)

    def clip(self, alphas, dims):
        """Frames of bar*(1-a) + wallpaper*a, darkened by dim."""
        frames = [(self.bar * (1 - a) + self.wall * a) * (1 - d) for a, d in zip(alphas, dims)]
        return self.np.array(frames)

    def run_probe(self, alphas, dims):
        strips = self.clip(alphas, dims)
        times = [i / 60.0 for i in range(len(strips))]
        return self.probe.transitions(self.probe.correlations(strips), times)

    def test_a_one_frame_handover_is_clean_even_while_the_overview_darkens(self):
        alphas = [0] * 10 + [1] * 30 + [0] * 10
        dims = [0] * 10 + [0.38 * min(1, i / 18) for i in range(30)] + [0] * 10
        found = self.run_probe(alphas, dims)
        self.assertEqual([f[0] for f in found], ["covers", "uncovers"])
        for kind, a, b, frames, ms in found:
            self.assertLessEqual(frames, self.probe.CLEAN_MAX_FRAMES, (kind, frames))

    def test_a_compositor_fade_in_and_out_is_flagged(self):
        quick = lambda u: 1 - (1 - u) ** 3     # a fast-start ease, like `quick`
        ramp = [quick(i / 18) for i in range(1, 18)]
        alphas = [0] * 10 + ramp + [1] * 20 + ramp[::-1] + [0] * 10
        found = self.run_probe(alphas, [0.0] * len(alphas))
        self.assertEqual([f[0] for f in found], ["covers", "uncovers"])
        for kind, a, b, frames, ms in found:
            self.assertGreater(frames, self.probe.CLEAN_MAX_FRAMES, (kind, frames))

    def test_noise_in_one_frame_does_not_split_or_hide_a_transition(self):
        quick = lambda u: 1 - (1 - u) ** 3
        alphas = [0] * 10 + [quick(i / 18) for i in range(1, 18)] + [1] * 20
        alphas[14] = 0.0   # one stray frame back to the bar
        found = self.run_probe(alphas, [0.0] * len(alphas))
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0][3], self.probe.CLEAN_MAX_FRAMES)


class TestSlideAfterClose(unittest.TestCase):
    """dxrice_overview_probe.slide_after: the ghost after picking another
    window was the desktop still sliding once the overlay had gone. On
    synthetic 1/4-size frames: a slide that decays over ~20 frames is
    measured; a uniform fade, or a video playing inside a window, is not a
    slide."""

    def setUp(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("numpy not installed")
        import dxrice_overview_probe as probe
        self.np, self.probe = numpy, probe
        rng = numpy.random.RandomState(3)
        self.scene = rng.randint(0, 255, (300, 520)).astype(float)

    def crop(self, x, y):
        return self.scene[y:y + 200, x:x + 400].copy()

    def test_a_decaying_slide_is_measured(self):
        xs, x = [], 60.0
        for k in range(20):                 # 60 -> ~0 quarter-px, like a spring settling
            xs.append(round(x))
            x *= 0.8
        xs += [0] * 10
        frames = [self.crop(int(v), 40) for v in xs]
        n, dist = self.probe.slide_after(frames, 0)
        self.assertGreater(n, self.probe.SLIDE_MAX_FRAMES)
        self.assertAlmostEqual(dist, xs[0] * self.probe.SLIDE_SCALE, delta=4 * self.probe.SLIDE_SCALE)

    def test_a_fade_or_moving_content_is_not_a_slide(self):
        base = self.crop(20, 20)
        fading = [base * (0.6 + 0.04 * k) for k in range(10)]
        self.assertEqual(self.probe.slide_after(fading, 0)[0], 0)
        rng = self.np.random.RandomState(9)
        video = []
        for k in range(10):
            f = base.copy()
            f[50:120, 80:220] = rng.randint(0, 255, (70, 140))   # a playing video
            video.append(f)
        self.assertEqual(self.probe.slide_after(video, 0)[0], 0)


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
