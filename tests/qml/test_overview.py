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
import re
import math
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

REPO = Path(__file__).resolve().parents[2]

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


def bezier(x1, y1, x2, y2, u):
    """CSS/Qt cubic-bezier easing value at time fraction u."""
    def coord(t, a, b):
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if coord(mid, x1, x2) < u:
            lo = mid
        else:
            hi = mid
    return coord((lo + hi) / 2, y1, y2)


class OverviewScene:
    """The OverviewDesktop scene with a workspace loaded into it."""

    def __init__(self, clients, mon=None, uncapturable=(), layer_fade_ms=0, wallpaper=None):
        mon = mon or monitor()
        self.mon = mon
        # the surface is the monitor's LOGICAL size, as Quickshell gives it;
        # layer_fade_ms > 0 makes the stub surface fade in on map the way
        # Hyprland's fadeLayersIn does
        sc = mon.get("scale", 1) or 1
        def setup(b):
            b.layer_fade_ms = layer_fade_ms
            if wallpaper:        # a real image file as the theme's wallpaper
                t = b.config_home / "dxrice" / "theme.json"
                d = json.loads(t.read_text())
                d["wallpaper"] = wallpaper
                t.write_text(json.dumps(d))
        self.scene = Scene("OverviewDesktop.qml", width=round(mon["width"] / sc), height=round(mon["height"] / sc),
                           setup=setup)
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
        self.o.scene.wait(SETTLE)  # the real animation done; then step it by hand
        self.o.scene.ev("findNamed('overview').progress = 0")  # the zoom's first frame
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
        self.o.scene.wait(130)
        p0 = self.o.ov("progress")
        self.assertTrue(0 < p0 < 1, p0)
        import time
        T = self.o.ov("zoomMs")
        t0 = time.perf_counter()
        self.o.call("hide")
        seen = [(0.0, p0)]
        for _ in range(12):
            self.o.scene.wait(40)
            seen.append(((time.perf_counter() - t0) * 1000, self.o.ov("progress")))
        # monotonic all the way back, ending exactly on the real view, and
        # never ahead of the zoom's own curve (Overview.qml zoomCurve) for
        # the time actually elapsed -- the reversal eases
        # out of the current position rather than snapping. Judged against
        # measured time, not sample counts: the offscreen software renderer's
        # frames are irregular.
        ps = [p for _t, p in seen]
        self.assertTrue(all(b <= a + 1e-6 for a, b in zip(ps, ps[1:])), seen)
        self.assertEqual(ps[-1], 0.0)
        c = json.loads(self.o.scene.ev("JSON.stringify(findNamed('overview').zoomCurve)"))
        for t, p in seen[1:]:
            u = min(1.0, t / T)
            self.assertLessEqual(p0 - p, p0 * bezier(c[0], c[1], c[2], c[3], u) + 0.06, (t, p, seen))

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
        # the overview's own stacking: a fullscreen window lies at the bottom
        def level(o):
            return -1 if o["fullscreen"] else o["z"]
        above = [o for o in self.o.layout["windows"] if level(o) > level(w)]
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

    def fully_visible(self, w):
        W, H = self.o.layout["monitor"]["width"], self.o.layout["monitor"]["height"]
        return w["x"] >= 0 and w["y"] >= 0 and w["x"] + w["w"] <= W and w["y"] + w["h"] <= H

    def expected_pan(self, w):
        """Overview.qml's panDelta: nothing if w is entirely in view, else
        the one delta that centres it in the usable area."""
        W, H = self.o.layout["monitor"]["width"], self.o.layout["monitor"]["height"]
        if self.fully_visible(w):
            return 0, 0
        return round((W - w["w"]) / 2 - w["x"]), round((H - w["h"]) / 2 - w["y"])

    def test_one_click_on_every_window_focuses_exactly_that_window(self):
        """Every thumbnail -- on screen or not -- in ONE click: the overview
        closes and every focus request names that window's own Hyprland
        address (sent after the keyboard is released and once more after the
        overlay is gone). A window not entirely in view is brought there
        first by panning the whole desktop so it is centred: every floating
        window moved by that one delta (the spiral keeps its shape); a
        window already in view moves nothing at all."""
        mx, my = self.o.layout["monitor"]["x"], self.o.layout["monitor"]["y"]
        panned = still = 0
        for w in self.o.layout["windows"]:
            pt = self.visible_point(w)
            if pt is None:
                continue
            self.o.load(self.o.clients)  # the desktop as it is (no pan carried over)
            before = len(self.o.dispatches())
            self.o.call("show")
            self.o.scene.wait(SETTLE)
            self.o.click(*pt)
            self.o.scene.wait(SETTLE)
            sent = self.o.dispatches()[before:]
            move_reqs = [d for d in sent if "hl.dsp.window.move(" in d]
            moves = [re.search(r'hl\.dsp\.window\.move\(\{[^}]*\}\)', d).group(0) for d in move_reqs]
            focus = [d for d in sent if d.startswith("hl.dsp.focus")]
            self.assertTrue(focus, w["address"])
            self.assertEqual(set(focus), {self.lua(w["address"])}, (w["address"], sent))
            self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
            if self.fully_visible(w):
                self.assertEqual(moves, [], f"{w['address']} was in view: nothing may move")
                still += 1
                continue
            dx, dy = self.expected_pan(w)
            want = {f'hl.dsp.window.move({{ window = "address:{o["address"]}", x = {round(o["x"] + mx + dx)}, '
                    f'y = {round(o["y"] + my + dy)}, relative = false }})'
                    for o in self.o.layout["windows"] if o["floating"] and not o["pinned"] and not o["fullscreen"]}
            self.assertEqual(set(moves), want, w["address"])
            self.assertLess(sent.index(move_reqs[0]), sent.index(focus[0]), "moved after focusing")
            panned += 1
        self.assertGreaterEqual(still, 1)
        self.assertGreaterEqual(panned, 8)

    def test_focus_is_always_sent_in_lua_syntax(self):
        """DXrice's Hyprland runs hyprland.lua: the classic
        "focuswindow address:" form would be refused, whatever Quickshell's
        usingLua says."""
        self.o.scene.ev("hypr.usingLua = false")
        w = next(w for w in reversed(self.o.layout["windows"]) if self.fully_visible(w))
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.click(*self.visible_point(w))
        self.o.scene.wait(SETTLE)
        self.assertEqual(set(self.o.dispatches()), {self.lua(w["address"])})

    def test_fullscreen_pinned_and_tiled_windows_focus_without_a_pan(self):
        """Pinned and fullscreen windows belong to the screen, not the
        desktop; tiled ones are always in view: one click focuses them and
        nothing moves. Clicking the fullscreen one (on top of the stack)
        works; so does a pinned one beside it."""
        self.o.scene.close()
        cl = clients_for(self.rects[:6])
        cl.append({"address": "0xb01", "at": [100, 120], "size": [700, 500], "workspace": {"id": 1}, "monitor": 0,
                   "mapped": True, "floating": False, "focusHistoryID": 9, "class": "tiled", "title": "Tiled"})
        cl.append({"address": "0xb02", "at": [1500, 90], "size": [400, 300], "workspace": {"id": 4}, "monitor": 0,
                   "mapped": True, "floating": True, "pinned": True, "focusHistoryID": 8, "class": "pin", "title": "Pinned"})
        cl.append({"address": "0xb03", "at": [0, 0], "size": [1920, 1080], "workspace": {"id": 1}, "monitor": 0,
                   "mapped": True, "floating": False, "fullscreen": 2, "focusHistoryID": 0, "class": "game", "title": "Game"})
        self.o = OverviewScene(cl)
        for addr in ("0xb03", "0xb02", "0xb01"):
            w = next(x for x in self.o.layout["windows"] if x["address"] == addr)
            pt = self.visible_point(w)
            self.assertIsNotNone(pt, addr)
            before = len(self.o.dispatches())
            self.o.call("show")
            self.o.scene.wait(SETTLE)
            self.o.click(*pt)
            self.o.scene.wait(SETTLE)
            self.assertEqual(set(self.o.dispatches()[before:]), {self.lua(addr)}, addr)

    def test_a_window_that_just_closed_says_so(self):
        """Clicking a window that has closed since the last refresh: nothing
        is focused (it can't be), the overview stays open and says so."""
        w = self.o.layout["windows"][-1]
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        gone = w["address"].replace("0x", "")
        self.o.scene.ev(f"hypr.toplevels = ({{ values: hypr.toplevels.values.filter(t => t.address !== '{gone}') }})")
        self.o.click(*self.visible_point(w))
        self.o.scene.wait(300)
        self.assertEqual(self.o.dispatches(), [])
        self.assertTrue(self.o.ov("open"))
        self.assertIn("closed", self.o.scene.ev("findNamed('overviewOffScreenNote')").property("text"))

    def test_windows_opening_and_closing_mid_animation(self):
        """A window event during the zoom: the overview ends on the fresh
        layout, every tile in place, and the tiles of windows that were
        already there are updated, not rebuilt (their live pictures carry
        on)."""
        self.o.call("show")
        self.o.scene.wait(120)  # zoom under way
        built = self.o.ov("tilesBuilt")
        extra = clients_for(self.rects + [(2300, 900, 2900, 1300)])
        self.o.load(extra)
        self.o.scene.ev("hypr.rawEvent({ name: 'openwindow', data: 'a010,1,app,new' })")
        self.o.scene.wait(SETTLE + 400)
        self.assertEqual(self.o.state(), (True, 1.0, 1.0, True))
        self.assert_tiles_at("target")
        self.assertEqual(self.o.ov("tilesBuilt") - built, 1, "existing tiles were rebuilt")
        self.o.load(extra[:4])
        self.o.scene.ev("hypr.rawEvent({ name: 'closewindow', data: 'a010' })")
        self.o.call("hide")   # and closing at the same moment
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        self.assertEqual(self.o.tiles(), {})
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

    def settle_tiles(self, timeout_ms=3000):
        """Wait until the tiles have stopped gliding (a refresh is debounced,
        read, then animated; a fixed wait was 0.65 px short once under load)."""
        last, waited = None, 0
        while waited < timeout_ms:
            self.o.scene.wait(40)
            waited += 40
            now = self.o.tiles()
            if now == last and waited >= 400:
                return
            last = now

    def test_windows_opening_and_closing_while_open(self):
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        extra = clients_for(self.rects + [(2300, 900, 2900, 1300)])
        self.o.load(extra)
        self.o.scene.ev("hypr.rawEvent({ name: 'openwindow', data: 'a010,1,app,new' })")
        self.settle_tiles()
        self.assertTrue(self.o.ov("open"))
        self.assert_tiles_at("target")
        self.o.load(extra[:5])
        self.o.scene.ev("hypr.rawEvent({ name: 'closewindow', data: 'a010' })")
        self.settle_tiles()
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


MAGENTA = "#ff00ff"


def max_diff(a, b, step=7):
    """Largest per-channel difference between two frames, sampled."""
    d = 0
    for x in range(0, min(a.width(), b.width()), step):
        for y in range(0, min(a.height(), b.height()), step):
            p, q = a.pixelColor(x, y), b.pixelColor(x, y)
            d = max(d, abs(p.red() - q.red()), abs(p.green() - q.green()), abs(p.blue() - q.blue()))
    return d


def diff_fraction(a, b, tol=8, step=3):
    """Share of sampled pixels differing by more than tol in any channel."""
    n = bad = 0
    for x in range(0, min(a.width(), b.width()), step):
        for y in range(0, min(a.height(), b.height()), step):
            p, q = a.pixelColor(x, y), b.pixelColor(x, y)
            n += 1
            bad += max(abs(p.red() - q.red()), abs(p.green() - q.green()), abs(p.blue() - q.blue())) > tol
    return bad / n


def moved_to(dispatches):
    """{address: (x, y)} from the hl.dsp.window.move requests sent."""
    import re
    out = {}
    for d in dispatches:
        m = re.search(r'window\.move\(\{ window = "address:([^"]+)", x = (-?\d+), y = (-?\d+)', d)
        if m:
            out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


class TestSelectionCentring(unittest.TestCase):
    """Bug report: a window clicked in the overview ended up off centre,
    toward the side of the screen it had been on (the pan only nudged it
    24 px inside the nearest edge). It must land centred in the usable area
    -- bar, dock and the monitor's own position accounted for -- within
    2 px, by ONE delta applied to every movable window."""

    def run_case(self, target_rect, mon, extra=()):
        anchor = (mon["x"] + 760, mon["y"] + 400, mon["x"] + 1160, mon["y"] + 700)
        rects = [anchor, target_rect] + list(extra)
        cl = clients_for(rects)
        cl.append({"address": "0xp1n", "at": [mon["x"] + 1500, mon["y"] + 90], "size": [300, 200],
                   "workspace": {"id": 4}, "monitor": 0, "mapped": True, "floating": True, "pinned": True,
                   "focusHistoryID": 50, "class": "pin", "title": "Pinned"})
        o = OverviewScene(cl, mon)
        try:
            lay = o.layout
            target = next(w for w in lay["windows"] if w["address"] == "0xa001")
            o.call("show")
            o.scene.wait(SETTLE)
            # click the target's tile where nothing else covers it
            pt = TestOverview.visible_point(type("X", (), {"o": o})(), target)
            self.assertIsNotNone(pt)
            o.click(*pt)
            o.scene.wait(SETTLE)
            sent = o.dispatches()
            moves = moved_to(sent)
            ux, uy, uw, uh = lay["monitor"]["x"], lay["monitor"]["y"], lay["monitor"]["width"], lay["monitor"]["height"]
            tx, ty = moves["0xa001"]
            err = math.hypot(tx + target["w"] / 2 - (ux + uw / 2), ty + target["h"] / 2 - (uy + uh / 2))
            # and against the usable area worked out from the raw monitor
            # alone (logical size, offset, reserved strips) -- not from the
            # layout code this is testing
            sc = mon.get("scale", 1) or 1
            res = mon["reserved"]
            cx = mon["x"] + res[0] + (mon["width"] / sc - res[0] - res[2]) / 2
            cy = mon["y"] + res[1] + (mon["height"] / sc - res[1] - res[3]) / 2
            raw = math.hypot(tx + (target_rect[2] - target_rect[0]) / 2 - cx, ty + (target_rect[3] - target_rect[1]) / 2 - cy)
            self.assertLessEqual(raw, 2, ("centre vs the raw monitor", raw, (tx, ty), (cx, cy)))
            err = max(err, raw)
            # one delta for every movable window; the pinned one stays
            deltas = {(x - (w["x"] + ux), y - (w["y"] + uy))
                      for a, (x, y) in moves.items() for w in lay["windows"] if w["address"] == a}
            self.assertEqual(len(deltas), 1, deltas)
            self.assertNotIn("0xp1n", moves)
            self.assertEqual(set(moves), {w["address"] for w in lay["windows"] if w["floating"] and not w["pinned"]})
            # the closing animation's last frame is exactly the panned desktop
            (dx, dy), = deltas
            last = json.loads(o.scene.ev("JSON.stringify(findNamed('overview').lastCloseRects)"))
            for w in lay["windows"]:
                moved = w["floating"] and not w["pinned"] and not w["fullscreen"]
                want = [w["x"] + (dx if moved else 0), w["y"] + (dy if moved else 0), w["w"], w["h"]]
                for g, e in zip(last[w["address"]], want):
                    self.assertAlmostEqual(g, e, delta=0.6, msg=(w["address"], last[w["address"]], want))
            self.assertIn('hl.dsp.focus({ window = "address:0xa001" })', sent)
            return err
        finally:
            o.scene.close()

    def test_targets_in_every_direction_land_centred(self):
        mon = monitor()
        errors = {}
        for name, rect in (("left", (-1400, 300, -800, 700)), ("right", (2600, 200, 3300, 650)),
                           ("above", (700, -1300, 1300, -900)), ("below", (500, 1500, 1200, 1950)),
                           ("left and below", (-900, 1300, -300, 1700)), ("half off the right", (1600, 300, 2300, 700))):
            errors[name] = self.run_case(rect, mon)
        for name, e in errors.items():
            self.assertLessEqual(e, 2, (name, errors))

    def test_a_monitor_not_at_the_origin_with_a_bar_and_a_dock_on_the_side(self):
        mon = {"id": 0, "name": "HDMI-A-1", "x": 1920, "y": 120, "width": 2560, "height": 1440, "scale": 1,
               "transform": 0, "focused": True, "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0},
               "reserved": [64, 40, 0, 0]}
        for rect in ((1920 - 1500, 300, 1920 - 700, 800), (1920 + 3100, 900, 1920 + 3800, 1300)):
            self.assertLessEqual(self.run_case(rect, mon), 2, rect)

    def test_a_scaled_monitor(self):
        mon = monitor(w=2880, h=1620)
        mon["scale"] = 1.5  # logical 1920x1080
        self.assertLessEqual(self.run_case((2400, 500, 3000, 900), mon), 2)

    def test_a_target_larger_than_the_screen_is_centred(self):
        self.assertLessEqual(self.run_case((2200, -200, 2200 + 2400, -200 + 1300), monitor()), 2)

    def test_a_window_already_in_view_moves_nothing(self):
        cl = clients_for([(760, 400, 1160, 700), (100, 120, 600, 500)])
        o = OverviewScene(cl)
        try:
            w = next(x for x in o.layout["windows"] if x["address"] == "0xa001")
            o.call("show")
            o.scene.wait(SETTLE)
            o.click(*TestOverview.visible_point(type("X", (), {"o": o})(), w))
            o.scene.wait(SETTLE)
            self.assertEqual(moved_to(o.dispatches()), {})
        finally:
            o.scene.close()


LUA_MOCK = r"""
local calls = {}
hl = { dsp = { window = {} } }
local function need(t, k) assert(type(t[k]) == "string" or type(t[k]) == "number", "missing " .. k); return t[k] end
function hl.dsp.window.set_prop(t)
    local p, v, w = need(t, "prop"), need(t, "value"), need(t, "window")
    return function() calls[#calls + 1] = "set_prop " .. p .. " " .. v .. " " .. w end
end
function hl.dsp.window.move(t)
    local w, x, y = need(t, "window"), need(t, "x"), need(t, "y")
    return function() calls[#calls + 1] = "move " .. w .. " " .. x .. " " .. y end
end
function hl.dsp.focus(t) return function() calls[#calls + 1] = "focus " .. need(t, "window") end end
function hl.dispatch(f) f(); return "ok" end
for line in io.lines() do
    -- what Hyprland does with `dispatch <line>` in a Lua config
    assert(load("return hl.dispatch(" .. line .. ")"))()
end
for _, c in ipairs(calls) do print(c) end
"""


def run_in_lua(dispatches):
    """The calls Hyprland makes for these dispatch strings, in order, with
    `hl.dsp` and `hl.dispatch` mocked (real Lua: syntax and evaluation order
    are the real thing)."""
    import shutil
    import subprocess
    lua = shutil.which("lua") or shutil.which("luajit")
    if not lua:
        raise unittest.SkipTest("no lua interpreter")
    r = subprocess.run([lua, "-e", LUA_MOCK], input="\n".join(dispatches) + "\n",
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.split("\n")[:-1]


class TestPanWithoutCompositorAnimation(unittest.TestCase):
    """Bug report: picking a DIFFERENT window in the overview, a ghost slid in
    from the side a moment after the overview closed; picking the window you
    started on, never. A different window is usually off screen, so picking
    it pans the desktop: every floating window is moved, and Hyprland
    animated those moves with its `windows` leaf -- a spring here, which
    runs on its own physics (hyprutils ignores `speed` for springs: ~1 s for
    the template's). The overlay let go after 480 ms (read from that speed),
    with the windows still 4-6 % short of their places, and they finished
    sliding in front of the user (a screen recording showed 350-720 ms of
    sliding after the overlay went). Now each window's move is sent with
    no_anim set first, in the same request, so it lands at once under the
    overlay; no_anim is unset again once the overview has let go."""

    def scene(self, target_rect):
        anchor = (760, 400, 1160, 700)
        return OverviewScene(clients_for([anchor, target_rect, (200, 150, 600, 380)]))

    def click(self, o, address="0xa001"):
        target = next(w for w in o.layout["windows"] if w["address"] == address)
        o.call("show")
        o.scene.wait(SETTLE)
        before = len(o.dispatches())
        o.click(*TestOverview.visible_point(type("X", (), {"o": o})(), target))
        return before

    def test_each_window_lands_at_once_then_animates_again(self):
        o = self.scene((2600, 200, 3300, 650))     # off screen: a pan
        try:
            before = self.click(o)
            o.scene.wait(2)
            during = o.dispatches()[before:]
            o.scene.wait(SETTLE)
            after = o.dispatches()[before:]
            calls = run_in_lua(after)
        finally:
            o.scene.close()
        moved = [c.split()[1] for c in calls if c.startswith("move ")]   # "address:0x..."
        self.assertEqual(len(moved), 3, calls)
        for w in moved:
            i_off = calls.index(f"set_prop no_anim 1 {w}")
            i_move = next(i for i, c in enumerate(calls) if c.startswith(f"move {w} "))
            i_on = calls.index(f"set_prop no_anim unset {w}")
            self.assertLess(i_off, i_move, "moved before its animation was off")
            self.assertLess(i_move, i_on)
        # the same request carries both: nothing can reorder them in transit
        for d in during:
            if "window.move(" in d:
                self.assertLess(d.index('prop = "no_anim", value = "1"'), d.index("window.move("))
        # not turned back on while the overview still covers the screen
        self.assertFalse(any('value = "unset"' in d for d in during))
        self.assertEqual(sum('value = "unset"' in d for d in after), 3)

    def test_a_click_without_a_pan_touches_no_animation(self):
        o = self.scene((100, 120, 600, 500))       # entirely in view
        try:
            before = self.click(o)
            o.scene.wait(SETTLE)
            sent = o.dispatches()[before:]
        finally:
            o.scene.close()
        self.assertFalse(any("set_prop" in d or "window.move(" in d for d in sent), sent)
        self.assertTrue(any(d.startswith("hl.dsp.focus") for d in sent))

    def test_the_close_is_the_zoom_length_even_after_a_pan(self):
        import time
        for rect in ((2600, 200, 3300, 650), (100, 120, 600, 500)):
            o = self.scene(rect)
            try:
                self.click(o)
                t0 = time.monotonic()
                while o.ov("covering") and time.monotonic() - t0 < 3:
                    o.scene.wait(5)
                waited = (time.monotonic() - t0) * 1000
                zoom = o.ov("zoomMs")
            finally:
                o.scene.close()
            # the zoom plus the release frames; the old 480 ms wait after a
            # pan exceeds it
            self.assertLess(waited, zoom + 150, (rect, waited))

    def test_reopening_mid_close_still_turns_animations_back_on(self):
        o = self.scene((2600, 200, 3300, 650))
        try:
            before = self.click(o)
            o.scene.wait(40)
            o.call("show")                          # SUPER+Tab again, mid-close
            o.scene.wait(SETTLE)
            self.assertTrue(o.ov("open"))
            self.assertFalse(any('value = "unset"' in d for d in o.dispatches()[before:]))
            o.call("hide")
            o.scene.wait(SETTLE)
            sent = o.dispatches()[before:]
        finally:
            o.scene.close()
        self.assertEqual(sum('value = "unset"' in d for d in sent), 3)


class GhostRig:
    """Eight windows, the first painted (real window and picture alike) a
    colour nothing else has, so a second copy of it is unmistakable."""

    LAYER_FADE_MS = 0

    def setUp(self):
        self.rects = sp.arrange(MIXED[:8], [], (0, 52, 1920, 1012), (32, 56))
        self.o = OverviewScene(clients_for(self.rects), layer_fade_ms=self.LAYER_FADE_MS)
        # paint one real window (and its picture) a colour nothing else has
        fake = json.loads(self.o.scene.ev("JSON.stringify(fakeWindows)"))
        self.target = self.o.layout["windows"][0]
        fake[0]["color"] = MAGENTA
        self.o.scene.ev("fakeWindows = " + json.dumps(fake))
        tl = json.loads(self.o.scene.ev("JSON.stringify(hypr.toplevels.values)"))
        tl[0]["wayland"]["color"] = MAGENTA
        self.o.scene.ev("hypr.toplevels = ({ values: " + json.dumps(tl) + " })")

    def tearDown(self):
        self.o.scene.close()

    def magenta_outside_tiles(self, img, tiles=None):
        """Pixels of the real target window's colour where no tile is: a
        second, ghost copy of it."""
        r = self.o.layout["reserved"]
        tiles = self.o.tiles() if tiles is None else tiles
        w = self.target
        hits = 0
        for i in range(2, int(w["w"]) - 1, 4):
            for j in range(2, int(w["h"]) - 1, 4):
                x = w["x"] + r[0] + i
                y = w["y"] + r[1] + j
                if not (0 <= x < img.width() and 0 <= y < img.height()):
                    continue
                if any(t[0] - 2 <= x <= t[0] + t[2] + 2 and t[1] - 2 <= y <= t[1] + t[3] + 2 for t in tiles.values()):
                    continue
                c = img.pixelColor(int(x), int(y))
                # magenta at any strength: a half-faded ghost counts too
                if c.red() - c.green() > 40 and c.blue() - c.green() > 40:
                    hits += 1
        return hits

    def frames(self, n=10, every=30):
        """(progress, covering, frame) every few ms. While the overview is
        not covering, the screen is the real desktop alone (checked by
        test_nothing_is_drawn_before_the_handover); while it is, any of the
        real window's colour outside the pictures is a second copy."""
        out = []
        for _ in range(n):
            self.o.scene.wait(every)
            img = self.o.scene.view.grabWindow()
            out.append((self.o.ov("progress"), self.o.ov("covering"), (img, self.o.tiles())))
        return out


class TestNoGhosting(GhostRig, unittest.TestCase):
    """The overview itself never shows a window twice: the overview takes
    over in one frame, pictures exactly over the real windows, zooms fully
    covering, and lets go the same way -- checked on rendered frames. (What
    the COMPOSITOR does to the surface on top of that is
    TestUnderTheCompositorFade.)"""

    def test_opening_never_shows_the_real_window_and_its_picture_together(self):
        self.o.call("show")
        seen = self.frames(14, 25)
        self.assertTrue(any(0.05 < p < 0.95 for p, _c, _i in seen), [p for p, _c, _i in seen])
        for p, covering, img in seen:
            if covering:
                self.assertEqual(self.magenta_outside_tiles(*img), 0, f"ghost at progress {p:.2f} {img[1]}")
            else:
                self.assertEqual(p, 0, "zooming before the overview covers the desktop")

    STEPS = (0.0, 0.02, 0.05, 0.08, 0.12, 0.16, 0.25, 0.4, 0.6, 0.8, 0.95, 1.0)

    def test_every_zoom_frame_has_one_copy_of_each_window(self):
        """The zoom stepped frame by frame (both directions draw the same
        frames): at no point does the real window show beside its moving
        picture. The old crossfade failed exactly here, for p < 1/6."""
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        bad = {}
        for p in self.STEPS:
            self.o.scene.ev(f"findNamed('overview').progress = {p}")
            self.o.scene.wait(1)
            img = self.o.scene.view.grabWindow()
            hits = self.magenta_outside_tiles(img, self.o.tiles())
            if hits:
                bad[p] = hits
        self.assertEqual(bad, {}, "progress: ghost pixels")

    def test_nothing_is_drawn_before_the_handover(self):
        """Until the pictures are ready the overlay draws nothing but the
        keypress's dim: the screen is exactly the desktop under a uniform
        black veil (here: held at that point by a window with no picture
        yet) -- no picture, no wallpaper, nothing moved."""
        tl = json.loads(self.o.scene.ev("JSON.stringify(hypr.toplevels.values)"))
        tl[0]["wayland"]["noContent"] = True
        self.o.scene.ev("hypr.toplevels = ({ values: " + json.dumps(tl) + " })")
        desk = self.o.scene.view.grabWindow()
        self.o.call("show")
        self.o.scene.wait(60)
        self.assertFalse(self.o.ov("covering"))
        self.assertTrue(self.o.ov("visible"))
        a = 0.22 * self.o.ov("fade") * (1 - self.o.ov("progress"))
        self.assertGreater(a, 0)
        now = self.o.scene.view.grabWindow()
        worst = 0
        for x in range(0, desk.width(), 7):
            for y in range(0, desk.height(), 7):
                d, g = desk.pixelColor(x, y), now.pixelColor(x, y)
                worst = max(worst, *(abs(c0 * (1 - a) - c1) for c0, c1 in
                                     ((d.red(), g.red()), (d.green(), g.green()), (d.blue(), g.blue()))))
        self.assertLessEqual(worst, 2, "something besides the dim is drawn before the handover")

    def test_closing_never_shows_two_copies_even_after_a_pan(self):
        """Closing after a click that pans: the real windows are moved at
        once (here: the compositor applying the moves to the scene), the
        pictures travel to them, and no real window shows until the
        pictures are exactly on them."""
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        off = next(w for w in reversed(self.o.layout["windows"])
                   if w["x"] + w["w"] < 0 or w["x"] > 1920 or w["y"] + w["h"] < 0 or w["y"] > 960)
        pt = TestOverview.visible_point(type("X", (), {"o": self.o})(), off)
        self.o.click(*pt)
        self.o.scene.wait(1)
        moves = moved_to(self.o.dispatches())
        r, mx, my = self.o.layout["reserved"], self.o.layout["monitor"]["x"], self.o.layout["monitor"]["y"]
        fake = json.loads(self.o.scene.ev("JSON.stringify(fakeWindows)"))
        for fw, w in zip(fake, self.o.layout["windows"]):
            if w["address"] in moves:
                fw["x"], fw["y"] = moves[w["address"]][0] - mx + r[0], moves[w["address"]][1] - my + r[1]
        self.o.scene.ev("fakeWindows = " + json.dumps(fake))
        (tx, ty) = moves[self.target["address"]]
        self.target = dict(self.target, x=tx - mx, y=ty - my)   # where the real window now is
        # Sample for as long as this close really lasts (the zoom, plus the
        # release frames). A fixed 14 x 25 ms only covered it when frame
        # grabs happened to be slow (the full suite).
        close_ms = self.o.ov("zoomMs")
        seen = self.frames(math.ceil((close_ms + 200) / 25), 25)
        self.assertFalse(seen[-1][1], "the overview never gave the screen back")
        for p, covering, img in seen:
            if covering:
                self.assertEqual(self.magenta_outside_tiles(*img), 0, f"ghost at progress {p:.2f} {img[1]}")

    def test_the_handover_frames_are_the_desktop_itself(self):
        """The first frame the overview covers, and the last before it goes,
        are pixel for pixel the desktop it replaces (the usable area: the bar
        and dock strips are the one thing the overlay hides)."""
        from PySide6.QtCore import QRect
        r = self.o.layout["reserved"]
        area = QRect(r[0], r[1], self.o.layout["monitor"]["width"], self.o.layout["monitor"]["height"])
        desk = self.o.scene.view.grabWindow().copy(area)
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.scene.ev("findNamed('overview').progress = 0")
        self.o.scene.ev("findNamed('overview').fade = 0")
        self.o.scene.wait(60)
        self.assertTrue(self.o.ov("covering"))
        cover = self.o.scene.view.grabWindow().copy(area)
        self.assertLessEqual(max_diff(desk, cover), 2, "the covered frame differs from the desktop")

    def test_the_last_frame_drawn_on_closing_is_the_desktop(self):
        """Closing for real (not stepped): the overview lets go only after
        the frame with every picture back on its window and no dim has been
        drawn, so the last frame it shows and the first without it match."""
        from PySide6.QtCore import QRect
        r = self.o.layout["reserved"]
        area = QRect(r[0], r[1], self.o.layout["monitor"]["width"], self.o.layout["monitor"]["height"])
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.call("hide")
        last = None
        for _ in range(400):
            self.o.scene.wait(3)
            if not self.o.ov("covering"):
                break
            last = self.o.scene.view.grabWindow().copy(area)
        self.assertIsNotNone(last)
        self.assertFalse(self.o.ov("covering"))
        after = self.o.scene.view.grabWindow().copy(area)
        self.assertLessEqual(max_diff(last, after, 3), 2, "the overlay vanished before its final frame was drawn")

    def test_reopening_in_the_release_frames_resumes(self):
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.call("hide")
        for _ in range(400):
            self.o.scene.wait(2)
            if self.o.ov("progress") == 0:
                break
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (True, 1.0, 1.0, True))
        self.assertTrue(self.o.ov("covering"))
        self.assertEqual(len(self.o.tiles()), len(self.o.layout["windows"]))

    def test_the_surface_draws_nothing_in_its_last_frames(self):
        """Hyprland fades a layer surface out from a snapshot of its last
        frame. So before it unmaps, the overview commits frames with nothing
        in them: the screen is exactly the desktop, and the last frame seen
        while the surface exists is one of those (the old code unmapped
        straight from the drawn overview, which then faded over the real
        windows on a real compositor)."""
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.call("hide")
        last_visible_covering = None
        empty_frames = []
        for _ in range(1500):
            self.o.scene.wait(1)
            if not self.o.ov("visible"):
                break
            covering = self.o.ov("covering")
            last_visible_covering = covering
            if not covering and not self.o.ov("open"):
                empty_frames.append(self.o.scene.view.grabWindow())
        # The desktop right after the unmap, not from before the open: the
        # bar's clock may have changed minute in between (it did, in 4 of 12
        # concurrent runs that crossed the same minute).
        desk = self.o.scene.view.grabWindow()
        self.assertFalse(self.o.ov("visible"), "the overview never unmapped")
        self.assertFalse(last_visible_covering, "unmapped straight from a drawn frame")
        self.assertGreaterEqual(len(empty_frames), 1, "no empty frame before the unmap")
        diffs = [max_diff(desk, f, 5) for f in empty_frames]
        self.assertLessEqual(max(diffs), 2, diffs)

    def test_the_handover_waits_for_the_pictures(self):
        """The overview doesn't take over while a visible window has no
        picture yet -- that window would vanish for a frame or two; it waits
        (150 ms at most, then that window shows its card)."""
        tl = json.loads(self.o.scene.ev("JSON.stringify(hypr.toplevels.values)"))
        tl[0]["wayland"]["noContent"] = True
        self.o.scene.ev("hypr.toplevels = ({ values: " + json.dumps(tl) + " })")
        self.o.call("show")
        self.o.scene.wait(60)
        self.assertFalse(self.o.ov("covering"))
        self.assertEqual(self.o.ov("progress"), 0)
        self.o.scene.wait(400)
        self.assertTrue(self.o.ov("covering"))

    def test_pressing_again_before_the_handover_backs_out_cleanly(self):
        self.o.call("show")
        self.o.scene.wait(5)
        self.o.call("toggle")
        self.o.scene.wait(SETTLE)
        self.assertEqual(self.o.state(), (False, 0.0, 0.0, False))
        self.assertFalse(self.o.ov("covering"))
        self.assertEqual(self.o.dispatches(), [])


class TestUnderTheCompositorFade(GhostRig, unittest.TestCase):
    """What a real recording of SUPER+Tab showed: every window twice for
    ~300 ms, the overview's pictures moving over a real desktop still
    visible through them. Hyprland's fadeLayersIn (inherited from `fade`,
    3.03 ds, bezier `quick`) composites the whole overlay surface at 0..100%
    as it maps, however opaque Overview.qml paints it. The stub surface here
    does the same (layer_fade_ms), reproducing it in the real QML path."""

    LAYER_FADE_MS = 303

    def test_control_the_recorded_double_image_is_reproduced(self):
        """With the fade on (no overview-no-anim rule) the real window shows
        through while its picture moves. This is the control: it proves these
        frames can see the artifact, so the ghost-free results with the fade
        off (TestNoGhosting) mean something.

        Held, not sampled in real time: a frame mid-zoom with the surface
        mid-fade (the moment the recording caught). Sampling the running fade
        was the intermittent failure: under load each frame grab took so long
        that the 303 ms fade was over before the zoom had moved anything."""
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        for p, alpha in ((0.2, 0.5), (0.35, 0.7)):
            self.o.scene.ev(f"findNamed('overview').progress = {p}")
            self.o.scene.ev(f"findNamed('overview').layerAlpha = {alpha}")
            self.o.scene.wait(60)
            img = self.o.scene.view.grabWindow()
            self.assertGreater(self.magenta_outside_tiles(img, self.o.tiles()), 200,
                               f"no second copy at zoom {p}, surface alpha {alpha}")
        # and the same frame with the surface opaque has none
        self.o.scene.ev("findNamed('overview').layerAlpha = 1")
        self.o.scene.wait(60)
        self.assertEqual(self.magenta_outside_tiles(self.o.scene.view.grabWindow(), self.o.tiles()), 0)

    def test_the_overlay_equals_the_desktop_until_it_moves(self):
        """The one thing the shell controls: the surface's content, from the
        moment it covers until the zoom begins, is the desktop itself -- so
        whatever alpha the compositor has it at over that stretch is
        invisible. (Held at progress 0 and a 40% surface alpha, the frame is
        the desktop.)"""
        from PySide6.QtCore import QRect
        r = self.o.layout["reserved"]
        area = QRect(r[0], r[1], self.o.layout["monitor"]["width"], self.o.layout["monitor"]["height"])
        desk = self.o.scene.view.grabWindow().copy(area)
        self.o.call("show")
        self.o.scene.wait(SETTLE)
        self.o.scene.ev("findNamed('overview').progress = 0")
        self.o.scene.ev("findNamed('overview').fade = 0")        # the uniform keypress dim is not a copy
        self.o.scene.ev("findNamed('overview').layerAlpha = 0.4")  # the compositor mid-fade
        self.o.scene.wait(60)
        self.assertTrue(self.o.ov("covering"))
        self.assertEqual(self.o.ov("layerAlpha"), 0.4)
        # not bit-exact: the flattened surface's texture resamples the
        # anti-aliased edges of text -- a handful of pixels in tens of thousands
        self.assertLess(diff_fraction(desk, self.o.scene.view.grabWindow().copy(area)), 0.001)


class TestOpeningDoesNoHeavyWork(unittest.TestCase):
    """Bug report: SUPER+Tab felt delayed and the zoom's first frames rough.
    The overview decoded the wallpaper on every open, synchronously, at full
    size, on the thread that runs the animation: the user's 3840x2160 PNG
    (16.6 MB) takes ~400 ms. Now it is decoded once, in the background, at
    the screen's width, and kept; opening only shows it."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from PySide6.QtGui import QImage
        cls.tmp = tempfile.TemporaryDirectory()
        # a 4K PNG that doesn't compress, like a photo wallpaper, and what
        # decoding it costs on this machine (the user's took ~400 ms)
        import os
        import time
        from PySide6.QtGui import QImageReader
        buf = bytearray(os.urandom(3840 * 2160 * 4))
        img = QImage(buf, 3840, 2160, 3840 * 4, QImage.Format_RGB32).copy()
        cls.wall = cls.tmp.name + "/wall.png"
        assert img.save(cls.wall, "PNG", 0)
        t = time.perf_counter()
        QImageReader(cls.wall).read()
        cls.decode_ms = (time.perf_counter() - t) * 1000

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def scene(self):
        rects = sp.arrange(MIXED[:6], [], (0, 52, 1920, 1012), (32, 56))
        return OverviewScene(clients_for(rects), wallpaper=self.wall)

    def img(self, o, expr):
        return o.scene.ev(f"(function() {{ const ov = findNamed('overview'); const st = [ov]; "
                          f"while (st.length) {{ const it = st.pop(); if (!it) continue; "
                          f"if (it.sourceSize !== undefined && it.fillMode !== undefined && String(it.source).indexOf('wall') >= 0) "
                          f"return {expr}; const k = it.data !== undefined ? it.data : []; "
                          f"for (let i = 0; i < k.length; i++) st.push(k[i]); }} return null; }})()")

    def test_the_wallpaper_is_ready_before_any_open_and_stays(self):
        import time
        o = self.scene()
        try:
            t0 = time.monotonic()
            while self.img(o, "it.status") != 1 and time.monotonic() - t0 < 10:   # Image.Ready
                o.scene.wait(20)
            self.assertEqual(self.img(o, "it.status"), 1, "never decoded while closed")
            self.assertTrue(self.img(o, "it.asynchronous"), "decoded on the GUI thread")
            self.assertEqual(self.img(o, "it.sourceSize.width"), 1920, "kept at 4K")
            src = self.img(o, "String(it.source)")
            for _ in range(2):
                o.call("show"); o.scene.wait(SETTLE)
                o.call("hide"); o.scene.wait(SETTLE)
            self.assertEqual(self.img(o, "String(it.source)"), src)
            self.assertEqual(self.img(o, "it.status"), 1, "the decoded wallpaper was let go")
        finally:
            o.scene.close()

    def test_opening_doesnt_decode_the_wallpaper(self):
        """The keypress's own work (show(), which runs on the GUI thread and
        blocks the animation while it runs) costs far less than decoding
        the wallpaper: it no longer includes it. Old code: show() took the
        whole decode, every time."""
        import time
        o = self.scene()
        try:
            t0 = time.monotonic()
            while self.img(o, "it.status") != 1 and time.monotonic() - t0 < 10:
                o.scene.wait(20)
            blocked, covered = [], []
            for _ in range(3):
                t1 = time.perf_counter()
                o.call("show")
                blocked.append((time.perf_counter() - t1) * 1000)
                while not o.ov("covering") and time.perf_counter() - t1 < 3:
                    o.scene.wait(2)
                covered.append((time.perf_counter() - t1) * 1000)
                o.scene.wait(SETTLE)
                o.call("hide")
                o.scene.wait(SETTLE)
        finally:
            o.scene.close()
        self.assertGreater(self.decode_ms, 40, "the test wallpaper decodes too fast to tell")
        self.assertLess(max(blocked), self.decode_ms / 2,
                        f"show() blocked {max(blocked):.0f} ms; decoding the wallpaper takes {self.decode_ms:.0f} ms")
        self.assertLess(max(covered), 150, f"{max(covered):.0f} ms from the key to the overview covering")


class TestOverviewKeysAndLayouts(unittest.TestCase):
    """Keyboard selection, the focused window's highlight, captions, and
    the layout chips."""

    def scene(self, n=5, focused=3):
        rects = sp.arrange(MIXED[:n], [], (0, 52, 1920, 1012), (32, 56))
        clients = clients_for(rects)
        clients[focused]["focusHistoryID"] = 0
        o = OverviewScene(clients)
        o.call("show")
        o.scene.wait(SETTLE)
        o.scene.ev("findNamed('overview').children[0].forceActiveFocus()")
        return o

    def sel(self, o):
        return o.ov("selectedAddress")

    def key(self, o, k):
        o.scene.key(k)
        o.scene.wait(60)

    def test_selection_starts_on_the_window_that_had_focus(self):
        o = self.scene(focused=3)
        try:
            self.assertEqual(o.ov("focusedAddress"), "0xa003")
            self.assertEqual(self.sel(o), "0xa003")
        finally:
            o.scene.close()

    def test_arrows_move_to_the_neighbour_in_that_direction(self):
        from PySide6.QtCore import Qt
        o = self.scene(n=6, focused=0)
        try:
            tiles = {w["address"]: w for w in o.layout["windows"]}
            for key, dx, dy in ((Qt.Key_Right, 1, 0), (Qt.Key_Down, 0, 1), (Qt.Key_Left, -1, 0), (Qt.Key_Up, 0, -1)):
                before = self.sel(o)
                self.key(o, key)
                after = self.sel(o)
                if after == before:
                    continue          # nothing lies that way from here
                a, b = tiles[before], tiles[after]
                moved = ((b["tx"] + b["tw"] / 2) - (a["tx"] + a["tw"] / 2)) * dx + \
                        ((b["ty"] + b["th"] / 2) - (a["ty"] + a["th"] / 2)) * dy
                self.assertGreater(moved, 0, (key, before, after))
            self.assertIn(self.sel(o), tiles)
        finally:
            o.scene.close()

    def test_tab_visits_every_window_and_wraps(self):
        from PySide6.QtCore import Qt
        o = self.scene(n=5, focused=0)
        try:
            seen = [self.sel(o)]
            for _ in range(5):
                self.key(o, Qt.Key_Tab)
                seen.append(self.sel(o))
            self.assertEqual(set(seen[:5]), {w["address"] for w in o.layout["windows"]})
            self.assertEqual(seen[0], seen[5], "Tab didn't wrap")
            self.key(o, Qt.Key_Backtab)
            self.assertEqual(self.sel(o), seen[4])
        finally:
            o.scene.close()

    def test_enter_focuses_the_selected_window_in_one_go(self):
        from PySide6.QtCore import Qt
        o = self.scene(n=4, focused=0)
        try:
            self.key(o, Qt.Key_Tab)
            target = self.sel(o)
            self.assertNotEqual(target, "0xa000")
            before = len(o.dispatches())
            self.key(o, Qt.Key_Return)
            o.scene.wait(SETTLE)
            sent = o.dispatches()[before:]
            self.assertIn(f'hl.dsp.focus({{ window = "address:{target}" }})', sent)
            self.assertFalse(o.ov("open"))
        finally:
            o.scene.close()

    def test_the_selected_window_shows_its_title(self):
        o = self.scene(n=4, focused=0)
        try:
            from PySide6.QtCore import Qt
            self.key(o, Qt.Key_Tab)
            o.scene.wait(400)
            sel = self.sel(o)
            vis = {w["address"]: o.scene.ev(f"findNamed('overviewCaption:{w['address']}').opacity") for w in o.layout["windows"]}
            self.assertGreater(vis[sel], 0.9)
            for a, op in vis.items():
                if a not in (sel, o.ov("focusedAddress")):
                    self.assertLess(op, 0.05, a)
        finally:
            o.scene.close()

    def test_the_pointer_takes_the_selection_over(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        o = self.scene(n=5, focused=0)
        try:
            w = o.layout["windows"][3]
            x, y = TestOverview.visible_point(type("X", (), {"o": o})(), w)
            QTest.mouseMove(o.scene.view, QPoint(int(x), int(y)))
            o.scene.wait(100)
            self.assertEqual(self.sel(o), w["address"])
        finally:
            o.scene.close()

    def test_a_window_that_closes_while_selected_moves_the_selection_on(self):
        o = self.scene(n=4, focused=0)
        try:
            from PySide6.QtCore import Qt
            self.key(o, Qt.Key_Tab)
            gone = self.sel(o)
            o.load([c for c in o.clients if c["address"] != gone])
            o.scene.ev(f"hypr.rawEvent({{ name: 'closewindow', data: '{gone[2:]}' }})")
            o.scene.wait(800)
            self.assertNotEqual(self.sel(o), gone)
            self.assertIn(self.sel(o), o.tiles())
        finally:
            o.scene.close()

    def test_layout_chips_apply_and_save_the_layout(self):
        o = self.scene(n=4, focused=0)
        try:
            self.assertTrue(o.scene.ev("findNamed('overviewLayoutChips').visible"))
            self.assertEqual(o.ov("layoutMode"), "expansion")
            x, y = o.scene.ev("(function(){ const b = findNamed('overviewLayout:spiral'); const p = b.mapToItem(null, b.width/2, b.height/2); return [p.x, p.y]; })()").toVariant()
            o.click(x, y)
            o.scene.wait(300)
            self.assertEqual(o.ov("layoutMode"), "spiral")
            ran = [r for r in o.scene.bridge.run_log if "dxrice_layout_apply.py" in " ".join(r)]
            self.assertEqual(len(ran), 1)
            self.assertEqual(ran[0][-3:], ["--mode", "spiral", "--save"])
        finally:
            o.scene.close()

    def test_no_layout_chips_for_one_window_or_none(self):
        o = self.scene(n=1, focused=0)
        try:
            self.assertFalse(o.scene.ev("findNamed('overviewLayoutChips').visible"))
        finally:
            o.scene.close()


class TestHoveredWindowForSuperC(unittest.TestCase):
    """SUPER+C in the overview closes the window under the pointer: the
    overview reports it (hoveredTarget, the `overview hovered` IPC call)."""

    def test_hover_reports_that_window_and_nothing_else(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        rects = sp.arrange(MIXED[:6], [], (0, 52, 1920, 1012), (32, 56))
        o = OverviewScene(clients_for(rects))
        try:
            self.assertEqual(o.scene.ev("findNamed('overview').hoveredTarget()"), "closed")
            o.call("show")
            o.scene.wait(SETTLE)
            w = o.layout["windows"][2]
            x, y = TestOverview.visible_point(type("X", (), {"o": o})(), w)
            QTest.mouseMove(o.scene.view, QPoint(int(x), int(y)))
            o.scene.wait(80)
            self.assertEqual(o.scene.ev("findNamed('overview').hoveredTarget()"), f"{w['address']}\t{w['class']}")
            QTest.mouseMove(o.scene.view, QPoint(6, o.mon["height"] // 2))      # empty margin
            o.scene.wait(80)
            self.assertEqual(o.scene.ev("findNamed('overview').hoveredTarget()"), "")
            # hovered, then closed (SUPER+C did its job): no stale target
            QTest.mouseMove(o.scene.view, QPoint(int(x), int(y)))
            o.scene.wait(80)
            o.load([c for c in o.clients if c["address"] != w["address"]])
            o.scene.ev(f"hypr.rawEvent({{ name: 'closewindow', data: '{w['address'][2:]}' }})")
            o.scene.wait(800)
            self.assertNotIn(w["address"], o.tiles())
            self.assertNotIn(w["address"], o.scene.ev("findNamed('overview').hoveredTarget()"))
            self.assertTrue(o.ov("open"))
        finally:
            o.scene.close()


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
