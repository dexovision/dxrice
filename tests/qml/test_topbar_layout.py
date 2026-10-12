"""Top bar islands vs the panels that grow out of them, at narrow widths.

Quick Settings (680px, growing leftward from the right edge) ran over the
clock island at 1366px; narrower screens give the same conflict between
other pairs. The invariant: no VISIBLE island ever overlaps an open (or
opening, or closing) panel -- a covered island yields (fades out, takes no
input) and comes back once there is room again. Driven through the real
shell QML offscreen (see harness.py).

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
PANELS = {"quicksettings": "statusIsland", "calendar": "clockIsland"}
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

    @staticmethod
    def overlap(a, b):
        return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]

    def check_frame(self, panel_name, ctx):
        owner = self.island(PANELS[panel_name])
        for name in ISLANDS:
            if name == PANELS[panel_name]:
                continue
            other = self.island(name)
            if other["opacity"] > 0.01:
                self.assertFalse(self.overlap(owner, other),
                                 f"{ctx}: visible {name} {other} overlaps the {panel_name} surface {owner}")

    def sample(self, panel_name, ms, ctx):
        for _ in range(max(1, ms // 25)):
            self.s.wait(25)
            self.check_frame(panel_name, ctx)

    def topbar_input_rects(self):
        return [r for r in v(self.s.ev("inputRects()")) if r["surface"] == "TopBar"]

    def test_idle_islands_visible_and_clickable(self):
        for name in ISLANDS:
            i = self.island(name)
            self.assertEqual(i["opacity"], 1, f"{name} hidden at rest")
            self.assertTrue(i["enabled"])
        self.assertEqual(len(self.topbar_input_rects()), 3, "top bar should expose exactly its 3 islands at rest")

    def test_open_panels_never_overlap_a_visible_island(self):
        for panel in PANELS:
            with self.subTest(panel=panel):
                self.s.ev(f"panels.open('{panel}')")
                self.sample(panel, 600, f"{panel} opening")
                self.check_frame(panel, f"{panel} open")
                owner = self.island(PANELS[panel])
                for name in ISLANDS:
                    if name == PANELS[panel]:
                        continue
                    i = self.island(name)
                    if i["opacity"] < 0.01:
                        self.assertFalse(i["enabled"], f"hidden {name} still takes clicks")
                self.s.ev("panels.closeCurrent()")
                self.sample(panel, 700, f"{panel} closing")
                self.s.wait(400)
                for name in ISLANDS:
                    i = self.island(name)
                    self.assertEqual(i["opacity"], 1, f"{name} did not come back after {panel} closed")
                    self.assertTrue(i["enabled"])
                self.assertEqual(len(self.topbar_input_rects()), 3, f"island input not restored after {panel} closed")

    def test_wide_screen_keeps_every_island(self):
        """Nothing yields where nothing collides: on 1920px the clock stays
        put while Quick Settings is open, exactly as before."""
        if self.size[0] < 1920:
            self.skipTest("only meaningful on a wide screen")
        self.s.ev("panels.open('quicksettings')")
        self.s.wait(900)
        self.assertEqual(self.island("clockIsland")["opacity"], 1)
        self.s.ev("panels.closeCurrent()")
        self.s.wait(1100)

    def test_rapid_switching_settles_cleanly(self):
        for i in range(12):
            self.s.ev(f"panels.open('{['quicksettings', 'calendar'][i % 2]}')")
            self.s.wait(40 + (i * 13) % 60)
        self.s.ev("panels.closeCurrent()")
        self.s.wait(1200)
        for name in ISLANDS:
            self.assertEqual(self.island(name)["opacity"], 1, f"{name} stuck hidden after rapid switching")
        self.assertEqual(len(self.topbar_input_rects()), 3)


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
