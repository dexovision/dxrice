"""The one top bar and the panels that hang from it, at narrow widths.

When the bar was three pills that each grew into its panel, Quick Settings
(680px, growing leftward from the right edge) ran over the clock at 1366px
and covered pills had to fade out of the way. Now every panel hangs from
the bar's lower edge, so the invariant is stronger: no open (or opening, or
closing) panel ever overlaps any section of the bar, every section stays
visible and usable throughout, and the sections never overlap each other.
Driven through the real shell QML offscreen (see harness.py).

    python3 tests/qml/test_topbar_layout.py
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed (pip install PySide6-Essentials)")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402

ISLANDS = ("activityIsland", "clockIsland", "statusIsland")
PANELS = {"quicksettings": "statusIsland", "calendar": "clockIsland", "apps": "activityIsland", "status:network": "statusIsland"}
SIZES = ["1920x1080", "1366x768", "1280x720", "1024x768", "800x600"]


def v(x):
    return x.toVariant() if hasattr(x, "toVariant") else x


class TopBarLayoutTest(unittest.TestCase):
    size = (1920, 1080)

    @classmethod
    def setUpClass(cls):
        cls.s = Scene(width=cls.size[0], height=cls.size[1])
        cls.s.wait(600)

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def island(self, name):
        r = v(self.s.ev(f"(function(){{ const i = findNamed('{name}'); const p = i.mapToItem(null, 0, 0);"
                        f" return [p.x, p.y, i.width, i.height, i.opacity, i.enabled]; }})()"))
        return {"x": r[0], "y": r[1], "w": r[2], "h": r[3], "opacity": r[4], "enabled": r[5]}

    def body(self, name):
        r = v(self.s.ev(f"(function(){{ const b = findNamed('{name}').bodyItem; const p = b.mapToItem(null, 0, 0);"
                        f" return [p.x, p.y, b.width, b.visible ? b.height : 0]; }})()"))
        return {"x": r[0], "y": r[1], "w": r[2], "h": r[3]}

    def strip(self):
        r = v(self.s.ev("(function(){ const b = findNamed('barStrip'); const p = b.mapToItem(null, 0, 0); return [p.x, p.y, b.width, b.height]; })()"))
        return {"x": r[0], "y": r[1], "w": r[2], "h": r[3]}

    @staticmethod
    def overlap(a, b):
        return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]

    def check_frame(self, panel_name, ctx):
        body = self.body(PANELS[panel_name])
        bar = self.strip()
        if body["h"] > 0:
            self.assertGreaterEqual(body["y"], bar["y"] + bar["h"] - 0.5, f"{ctx}: the {panel_name} body {body} rides over the bar {bar}")
            self.assertGreaterEqual(body["x"], bar["x"] - 0.5, f"{ctx}: the {panel_name} body starts left of the bar")
            self.assertLessEqual(body["x"] + body["w"], bar["x"] + bar["w"] + 0.5, f"{ctx}: the {panel_name} body runs past the bar's end")
        for name in ISLANDS:
            i = self.island(name)
            self.assertEqual(i["opacity"], 1, f"{ctx}: {name} faded")
            self.assertTrue(i["enabled"], f"{ctx}: {name} stopped taking input")

    def sample(self, panel_name, ms, ctx):
        for _ in range(max(1, ms // 25)):
            self.s.wait(25)
            self.check_frame(panel_name, ctx)

    def topbar_input_rects(self):
        return [r for r in v(self.s.ev("inputRects()")) if r["surface"] == "TopBar" and r["w"] > 0 and r["h"] > 0]

    def test_idle_sections_sit_inside_the_bar_without_overlapping(self):
        bar = self.strip()
        rects = [self.island(n) for n in ISLANDS]
        for name, i in zip(ISLANDS, rects):
            self.assertEqual(i["opacity"], 1, f"{name} hidden at rest")
            self.assertTrue(i["enabled"])
            self.assertGreaterEqual(i["x"], bar["x"] - 0.5, name)
            self.assertLessEqual(i["x"] + i["w"], bar["x"] + bar["w"] + 0.5, name)
        for a in range(len(ISLANDS)):
            for b in range(a + 1, len(ISLANDS)):
                self.assertFalse(self.overlap(rects[a], rects[b]), f"{ISLANDS[a]} {rects[a]} overlaps {ISLANDS[b]} {rects[b]}")
        self.assertEqual(len(self.topbar_input_rects()), 1, "at rest the bar's input is exactly its strip")

    def test_open_panels_hang_below_the_bar_and_never_cover_it(self):
        for panel in PANELS:
            with self.subTest(panel=panel):
                self.s.ev(f"panels.open('{panel}')")
                self.sample(panel, 600, f"{panel} opening")
                self.check_frame(panel, f"{panel} open")
                self.s.ev("panels.closeCurrent()")
                self.sample(panel, 700, f"{panel} closing")
                self.s.wait(400)
                self.assertEqual(len(self.topbar_input_rects()), 1, f"bar input not restored after {panel} closed")

    def test_a_panel_reaching_an_end_of_the_bar_runs_flush_with_it(self):
        """Quick Settings and Applications reach the bar's right and left
        ends: they run flush (no joint), and the bar squares that corner
        off; the calendar, in the middle, has a joint on both sides."""
        self.s.ev("panels.open('quicksettings')")
        self.s.wait(900)
        self.assertTrue(self.s.ev("findNamed('statusIsland').flushRight"))
        self.assertFalse(self.s.ev("findNamed('statusIslandFilletRight').visible"))
        self.assertEqual(self.s.ev("findNamed('barStrip').bottomRightRadius"), 0)
        self.s.ev("panels.open('calendar')")
        self.s.wait(900)
        self.assertTrue(self.s.ev("findNamed('clockIslandFilletLeft').visible"))
        self.assertTrue(self.s.ev("findNamed('clockIslandFilletRight').visible"))
        self.s.ev("panels.closeCurrent()")
        self.s.wait(900)
        self.assertGreater(self.s.ev("findNamed('barStrip').bottomRightRadius"), 10, "the corner did not come back")

    def test_with_a_long_title_playing_the_sections_still_never_overlap(self):
        self.s.ev("setPlayer({ trackTitle: 'An Extremely Long Track Title That Goes On' })")
        self.s.wait(500)
        try:
            rects = [self.island(n) for n in ISLANDS]
            for a in range(len(ISLANDS)):
                for b in range(a + 1, len(ISLANDS)):
                    self.assertFalse(self.overlap(rects[a], rects[b]), f"{ISLANDS[a]} {rects[a]} overlaps {ISLANDS[b]} {rects[b]}")
            compact = self.s.ev("findNamed('statusIsland').parent.statusCompact")
            if self.size[0] >= 1920:
                self.assertFalse(compact, "a wide screen dropped the readings")
                self.assertEqual(self.s.ev("findNamed('barIndicator:media').label"), "An Extremely Long Tra…")
            # every indicator is still there, compact or not
            for name in ("media", "network", "audio", "notifications", "dashboard"):
                self.assertTrue(self.s.ev(f"findNamed('barIndicator:{name}').visible"), name)
        finally:
            self.s.ev("setPlayer(null)")
            self.s.wait(300)

    def test_rapid_switching_settles_cleanly(self):
        for i in range(12):
            self.s.ev(f"panels.open('{['quicksettings', 'calendar', 'apps'][i % 3]}')")
            self.s.wait(40 + (i * 13) % 60)
        self.s.ev("panels.closeCurrent()")
        self.s.wait(1200)
        for name in ISLANDS:
            self.assertEqual(self.island(name)["opacity"], 1, f"{name} stuck hidden after rapid switching")
            self.assertEqual(self.body(name)["h"], 0, f"{name}'s panel stuck open")
        self.assertEqual(len(self.topbar_input_rects()), 1)


def main():
    size = os.environ.get("DXRICE_TEST_SIZE")
    if size:
        TopBarLayoutTest.size = tuple(int(x) for x in size.split("x"))
        unittest.main(argv=[sys.argv[0], "-v"] + sys.argv[1:])
        return
    failed = []
    for sz in SIZES:
        print(f"===== {sz} =====", flush=True)
        if subprocess.call([sys.executable, __file__] + sys.argv[1:], env={**os.environ, "DXRICE_TEST_SIZE": sz}):
            failed.append(sz)
    print("FAILED sizes: " + ", ".join(failed) if failed else "ALL SIZES PASSED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
