"""The desktop overview (Overview.qml) in the real shell, offscreen.

The shell reads synthetic `hyprctl -j clients` / `hyprctl -j monitors`
output (harness fixtures) and computes the geometry itself
(OverviewGeometry.js); the test's expectations come from the reference
implementation, dxrice_overview.py, on the same data. Window pictures are the
ScreencopyView stub; Hyprland.dispatch only records. Nothing here talks to a
compositor.

    python3 tests/qml/test_overview.py
"""
import json
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed (pip install PySide6-Essentials)")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from harness import Scene  # noqa: E402
import dxrice_overview as ov  # noqa: E402
import dxrice_spiral as sp  # noqa: E402

PAL = ["#5b6fa8", "#7a5ca8", "#3f8f86", "#a8743f", "#a35478", "#5a8f4a", "#9c8a3c", "#3f86a8"]
MIXED = [(1100, 700), (860, 560), (640, 400), (900, 620), (550, 300), (1000, 650), (820, 560), (480, 320),
         (700, 460), (760, 480), (600, 380), (920, 600), (520, 340), (780, 500), (660, 420), (840, 540)]
SETTLE = 1100  # ms: the opening fade + zoom (theme default animation speed) and some


def monitor(name="DP-1", w=1920, h=1080, reserved=(0, 52, 0, 68)):
    return {"id": 0, "name": name, "x": 0, "y": 0, "width": w, "height": h, "scale": 1, "transform": 0, "focused": True,
            "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}, "reserved": list(reserved)}


def clients_for(rects, **extra):
    out = []
    for i, r in enumerate(rects):
        c = {"address": f"0xa{i:03x}", "at": [r[0], r[1]], "size": [r[2] - r[0], r[3] - r[1]], "workspace": {"id": 1},
             "monitor": 0, "mapped": True, "floating": True, "focusHistoryID": len(rects) - i, "class": "app",
             "title": f"Window {i + 1}"}
        c.update(extra.get(i, {}))
        out.append(c)
    return out


class OverviewScene:
    """The OverviewDesktop scene with a workspace loaded into it."""

    def __init__(self, clients, mon=None, uncapturable=()):
        mon = mon or monitor()
        self.mon = mon
        self.scene = Scene("OverviewDesktop.qml", width=mon["width"], height=mon["height"])
        self.load(clients, uncapturable)

    def load(self, clients, uncapturable=()):
        self.clients = clients
        self.layout = ov.overview(clients, [self.mon])
        s = self.scene
        s.set_command("hyprctl -j clients", json.dumps(clients))
        s.set_command("hyprctl -j monitors", json.dumps([self.mon]))
        r = self.layout["reserved"]
        fake = [{"x": w["x"] + r[0], "y": w["y"] + r[1], "w": w["w"], "h": w["h"], "color": PAL[i % len(PAL)],
                 "title": w["title"]} for i, w in enumerate(self.layout["windows"])]
        s.ev("fakeWindows = " + json.dumps(fake))
        tl = [{"address": w["address"].replace("0x", ""),
               "wayland": {"color": PAL[i % len(PAL)], "title": w["title"], "logicalWidth": w["w"],
                           "noContent": w["address"] in uncapturable}}
              for i, w in enumerate(self.layout["windows"])]
        s.ev("hypr.toplevels = ({ values: " + json.dumps(tl) + " })")

    def ov(self, prop):
        return self.scene.ev(f"findNamed('overview').{prop}")

    def call(self, fn):
        self.scene.ev(f"findNamed('overview').{fn}()")

    def tiles(self):
        v = self.scene.ev("JSON.stringify(tileRects())")
        return json.loads(v)

    def dispatches(self):
        return json.loads(self.scene.ev("JSON.stringify(hypr.dispatchLog)"))

    def click(self, x, y):
        """A click straight into the scene: the overview covers the whole
        monitor while open, so nothing else could receive it."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(self.scene.view, Qt.LeftButton, Qt.NoModifier, QPointF(x, y).toPoint())

    def state(self):
        return (self.ov("open"), round(self.ov("progress"), 3), round(self.ov("fade"), 3), self.ov("visible"))


class TestOverview(unittest.TestCase):
    def setUp(self):
        self.rects = sp.arrange(MIXED, [], (0, 52, 1920, 1012), (32, 56))
        self.o = OverviewScene(clients_for(self.rects))

    def tearDown(self):
        self.o.scene.close()

    def assert_tiles_at(self, key):
        """Every tile's on-screen rect is the layout's real (key='real') or
        overview (key='target') rect, in monitor coordinates."""
        r = self.o.layout["reserved"]
        tiles = self.o.tiles()
        self.assertEqual(len(tiles), len(self.o.layout["windows"]))
        for w in self.o.layout["windows"]:
            got = tiles[w["address"]]
            want = ((w["x"], w["y"], w["w"], w["h"]) if key == "real" else (w["tx"], w["ty"], w["tw"], w["th"]))
            want = (want[0] + r[0], want[1] + r[1], want[2], want[3])
            for g, e in zip(got, want):
                self.assertAlmostEqual(g, e, delta=0.6, msg=(w["address"], got, want))

    def test_opens_to_the_fitted_view_and_closes_back_to_the_real_one(self):
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        self.o.call("toggle")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (True, 1.0, 1.0, True))
        self.assert_tiles_at("target")
        self.o.call("toggle")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        self.assertEqual(self.o.dispatches(), [], "the overview touched a window")
        # closed means idle: no tiles, nothing being captured
        self.assertEqual(self.o.tiles(), {})

    def test_the_first_and_last_frames_are_the_real_desktop(self):
        """With the picture fully faded in but not yet zoomed (and likewise
        on the way out), every tile lies exactly over its real window."""
        self.o.call("show")
        self.o.scene.wait(40)
        self.o.scene.ev("findNamed('overview').fade = 1")  # the opening fade done, the zoom not begun
        self.assertEqual(self.o.ov("progress"), 0)
        self.assert_tiles_at("real")

    def test_repeated_toggles_end_where_they_should(self):
        for k in range(6):
            self.o.call("toggle")
            self.o.scene.wait(SETTLE)
            self.assertEqual(self.o.state()[0], k % 2 == 0)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        for _ in range(7):  # quicker than the animation: each press reverses it
            self.o.call("toggle")
            self.o.scene.wait(120)
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (True, 1.0, 1.0, True))
        self.o.call("hide")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        self.assertEqual(self.o.dispatches(), [])

    def test_reversing_mid_zoom_never_jumps(self):
        self.o.call("show")
        self.o.scene.wait(450)
        p0 = self.o.ov("progress")
        self.assertTrue(0 < p0 < 1, p0)
        import time
        T = self.o.scene.ev("theme.durationExit") + 60
        t0 = time.perf_counter()
        self.o.call("hide")
        seen = [(0.0, p0)]
        for _ in range(12):
            self.o.scene.wait(40)
            seen.append(((time.perf_counter() - t0) * 1000, self.o.ov("progress")))
        # monotonic all the way back, ending exactly on the real view, and
        # never ahead of the ease-in-out curve for the time actually elapsed
        # (InOutCubic: 4t^3 in the first half) -- the reversal eases in
        # rather than snapping. Judged against measured time, not sample
        # counts: the offscreen software renderer's frames are irregular.
        ps = [p for _t, p in seen]
        self.assertTrue(all(b <= a + 1e-6 for a, b in zip(ps, ps[1:])), seen)
        self.assertEqual(ps[-1], 0.0)
        for t, p in seen[1:]:
            u = min(1.0, t / T)
            if u < 0.5:
                self.assertLessEqual(p0 - p, p0 * 4 * u ** 3 + 0.06, (t, p, seen))

    def test_show_and_hide_are_idempotent(self):
        self.o.call("show"); self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (True, 1.0, 1.0, True))
        self.o.call("hide"); self.o.call("hide")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))

    def test_escape_and_a_click_on_empty_space_close_without_touching_focus(self):
        from PySide6.QtCore import Qt
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.scene.ev("findNamed('overview').children[0].forceActiveFocus()")
        self.o.scene.key(Qt.Key_Escape)
        self.o.scene.wait(SETTLE)
        self.assertFalse(self.o.ov("open"))
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.click(8, self.o.mon["height"] // 2)  # the left margin: no tile there
        self.o.scene.wait(SETTLE)
        self.assertFalse(self.o.ov("open"))
        self.assertEqual(self.o.dispatches(), [])

    def visible_point(self, w):
        """A point of w's overview tile that no tile above it covers."""
        r = self.o.layout["reserved"]
        above = [o for o in self.o.layout["windows"] if o["z"] > w["z"]]
        for fy in (0.5, 0.25, 0.75, 0.1, 0.9):
            for fx in (0.5, 0.25, 0.75, 0.1, 0.9):
                x, y = w["tx"] + w["tw"] * fx, w["ty"] + w["th"] * fy
                if not any(o["tx"] <= x <= o["tx"] + o["tw"] and o["ty"] <= y <= o["ty"] + o["th"] for o in above):
                    return x + r[0], y + r[1]
        return None

    def on_screen(self, w):
        r = self.o.layout["reserved"]
        W, H = self.o.mon["width"], self.o.mon["height"]
        return w["x"] + r[0] < W and w["x"] + r[0] + w["w"] > 0 and w["y"] + r[1] < H and w["y"] + r[1] + w["h"] > 0

    @staticmethod
    def lua(address):
        return f'hl.dsp.focus({{ window = "address:{address}" }})'

    def runs(self):
        return [list(r) for r in self.o.scene.bridge.run_log]

    def test_clicking_every_window_focuses_exactly_that_window(self):
        """Every thumbnail, clicked: the overview closes and every focus
        request names that window's own Hyprland address (sent after the
        keyboard is released and once more after the overlay is gone -- see
        Overview.qml's focusLua). A window entirely off screen first says so
        (no focus); a second click pans the desktop there with
        dxrice_navigate_windows.py --to <that address>, then focuses it."""
        on, off = 0, 0
        for w in self.o.layout["windows"]:
            pt = self.visible_point(w)
            if pt is None:
                continue
            before = len(self.o.dispatches())
            self.o.call("show")
            self.o.scene.wait(SETTLE)
            self.o.click(*pt)
            self.o.scene.wait(250)
            if not self.on_screen(w):
                self.assertEqual(self.o.dispatches()[before:], [], w["address"])
                self.assertTrue(self.o.ov("open"))
                self.assertTrue(self.o.scene.ev("findNamed('overviewOffScreenNote')").property("visible"))
                self.o.click(*pt)
                self.o.scene.wait(SETTLE)
                pans = [r for r in self.runs() if "--to" in r]
                self.assertEqual(pans[-1][-2:], ["--to", w["address"]])
                off += 1
            else:
                self.o.scene.wait(SETTLE)
                on += 1
            sent = self.o.dispatches()[before:]
            self.assertTrue(sent, w["address"])
            self.assertEqual(set(sent), {self.lua(w["address"])}, (w["address"], sent))
            self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        self.assertGreaterEqual(on, 3)
        self.assertGreaterEqual(off, 6)

    def test_focus_is_always_sent_in_lua_syntax(self):
        """DXrice's Hyprland runs hyprland.lua: the classic
        "focuswindow address:" form would be refused, whatever Quickshell's
        usingLua says."""
        self.o.scene.ev("hypr.usingLua = false")
        w = next(w for w in reversed(self.o.layout["windows"]) if self.on_screen(w))
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.click(*self.visible_point(w))
        self.o.scene.wait(SETTLE)
        self.assertEqual(set(self.o.dispatches()), {self.lua(w["address"])})

    def test_a_window_entirely_off_screen_is_never_focused_silently(self):
        """One click on a window none of which is on the monitor: no focus,
        no pan, the overview stays open and says what a second click does.
        Clicking a different window instead cancels the pending pan."""
        off = [w for w in self.o.layout["windows"] if not self.on_screen(w) and self.visible_point(w)]
        self.assertGreaterEqual(len(off), 2, "the fixture needs off-screen windows")
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.click(*self.visible_point(off[0]))
        self.o.scene.wait(400)
        self.assertEqual(self.o.dispatches(), [])
        self.assertEqual([r for r in self.runs() if "--to" in r], [])
        self.assertTrue(self.o.ov("open"))
        note = self.o.scene.ev("findNamed('overviewOffScreenNote')")
        self.assertIn("off screen", note.property("text"))
        self.assertIn("Click it again", note.property("text"))
        self.o.click(*self.visible_point(off[1]))   # a different one: asks again, no pan
        self.o.scene.wait(400)
        self.assertEqual([r for r in self.runs() if "--to" in r], [])
        self.assertEqual(self.o.dispatches(), [])

    def test_the_keypress_gets_feedback_before_any_data(self):
        """The first frame after the keypress already shows the overview
        coming up (a dim over the real desktop), even if the window data
        never arrives; nothing stale is drawn meanwhile, and Esc still
        closes it."""
        from PySide6.QtCore import Qt
        self.o.scene.set_command("hyprctl -j clients", "__HANG__")
        self.o.call("show")
        self.o.scene.wait(20)
        self.assertTrue(self.o.ov("visible"))
        scrim = self.o.scene.ev("findNamed('overviewScrim')")
        self.assertGreater(scrim.property("opacity"), 0)
        self.assertEqual(self.o.tiles(), {})
        self.o.scene.ev("findNamed('overview').children[0].forceActiveFocus()")
        self.o.scene.key(Qt.Key_Escape)
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))

    def test_windows_opening_and_closing_while_open(self):
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        extra = clients_for(self.rects + [(2300, 900, 2900, 1300)])
        self.o.load(extra)
        self.o.scene.ev("hypr.rawEvent({ name: 'openwindow', data: 'a010,1,app,new' })")
        self.o.scene.wait(400)
        self.assertTrue(self.o.ov("open"))
        self.assert_tiles_at("target")
        self.o.load(extra[:5])
        self.o.scene.ev("hypr.rawEvent({ name: 'closewindow', data: 'a010' })")
        self.o.scene.wait(400)
        self.assertEqual(len(self.o.tiles()), 5)
        self.assert_tiles_at("target")
        # an unrelated event is ignored (no refresh: the stale fixture stays)
        self.o.load(extra)
        self.o.scene.ev("hypr.rawEvent({ name: 'activewindow', data: 'x' })")
        self.o.scene.wait(300)
        self.assertEqual(len(self.o.tiles()), 5)
        self.o.call("hide")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))

    def test_opening_closes_an_open_panel(self):
        self.o.scene.ev("panels.open('quicksettings')")
        self.o.scene.wait(100)
        self.o.call("show")
        self.o.scene.wait(100)
        self.assertEqual(self.o.scene.ev("panels.current"), "")

    def test_a_window_that_cannot_be_captured_shows_its_card(self):
        self.o.scene.close()
        self.o = OverviewScene(clients_for(self.rects), uncapturable={"0xa000"})
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.assertTrue(self.o.scene.ev(
            "(function(){ const ov = findNamed('overview'); const st = [ov]; let n = 0;"
            " while (st.length) { const it = st.pop(); if (!it) continue;"
            " if (it.objectName === 'overviewPlaceholder' && it.visible) n++;"
            " const k = it.data !== undefined ? it.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); }"
            " return n === 1; })()"))

    def test_no_compositor_answer_drops_the_request(self):
        self.o.scene.set_command("hyprctl -j clients", "")
        self.o.scene.set_command("hyprctl -j monitors", "")
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))


class TestGeometryParity(unittest.TestCase):
    """The shell's geometry (OverviewGeometry.js) and the reference
    (dxrice_overview.py) agree on hundreds of random workspaces: monitors of
    every scale/rotation/reservation, hidden and unmapped windows, pinned and
    fullscreen ones, other workspaces."""

    def test_js_equals_python(self):
        import random
        from PySide6.QtQml import QJSEngine
        from harness import app
        app()  # the harness's GUI application: a bare QCoreApplication would starve later scenes of screens
        eng = QJSEngine()
        src = (Path(__file__).resolve().parents[2] / "quickshell" / "OverviewGeometry.js").read_text()
        eng.evaluate(src.replace(".pragma library", ""))
        js_overview = eng.globalObject().property("overview")
        stringify = eng.evaluate("JSON.stringify")
        rng = random.Random(4)
        for k in range(300):
            mons = [{"id": 0, "name": "A", "x": rng.choice([0, 1920, -1080]), "y": 0,
                     "width": rng.choice([1920, 2560, 3840]), "height": rng.choice([1080, 1440, 2160]),
                     "scale": rng.choice([1, 1.25, 1.5, 2]), "transform": rng.choice([0, 0, 1, 3]), "focused": True,
                     "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": rng.choice([0, 0, -98])},
                     "reserved": [rng.choice([0, 30]), rng.choice([0, 40, 52]), 0, rng.choice([0, 68])]}]
            cl = []
            for i in range(rng.randint(0, 20)):
                cl.append({"address": f"0x{i:x}", "at": [rng.randint(-3000, 5000), rng.randint(-2000, 3000)],
                           "size": [rng.randint(1, 1500), rng.randint(1, 1000)],
                           "workspace": {"id": rng.choice([1, 1, 1, 2, -98])}, "monitor": rng.choice([0, 0, 1]),
                           "mapped": rng.random() > 0.05, "hidden": rng.random() < 0.05,
                           "floating": rng.random() > 0.3, "fullscreen": rng.choice([0, 0, 0, 2]),
                           "pinned": rng.random() < 0.1, "focusHistoryID": rng.randint(0, 10), "class": "c", "title": "t"})
            py = ov.overview(cl, mons)
            js = json.loads(stringify.call([js_overview.call([eng.toScriptValue(cl), eng.toScriptValue(mons)])]).toString())
            for key in ("monitor", "reserved", "workspace", "fits", "clipped"):
                self.assertEqual(js[key], py[key], (k, key))
            self.assertAlmostEqual(js["scale"], py["scale"], places=9)
            self.assertEqual([w["address"] for w in js["windows"]], [w["address"] for w in py["windows"]], k)
            for a, b in zip(js["windows"], py["windows"]):
                for f in ("x", "y", "w", "h", "tx", "ty", "tw", "th"):
                    self.assertAlmostEqual(a[f], b[f], delta=0.011, msg=(k, f))


class TestOtherMonitor(unittest.TestCase):
    def test_a_1440p_monitor_with_no_dock(self):
        mon = monitor("HDMI-A-1", 2560, 1440, reserved=(0, 40, 0, 0))
        rects = sp.arrange(MIXED, [], (0, 40, 2560, 1440), (32, 56))
        o = OverviewScene(clients_for(rects), mon)
        try:
            o.call("show")
            o.scene.wait(SETTLE)
            self.assertEqual(o.state(), (True, 1.0, 1.0, True))
            self.assertEqual((o.ov("monitorWidth"), o.ov("monitorHeight")), (2560, 1440))
            for addr, (x, y, w, h) in o.tiles().items():
                self.assertTrue(0 <= x and 40 <= y and x + w <= 2560 and y + h <= 1440, (addr, x, y, w, h))
        finally:
            o.scene.close()


if __name__ == "__main__":
    unittest.main()
