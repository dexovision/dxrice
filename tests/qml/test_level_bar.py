"""Performance meters (LevelBar) move straight to a new value: never past
it, never back. Their fill animated on an overshooting curve, so every
1.5s sample bounced a couple of pixels beyond the new value and back.
Driven through the real Quick Settings Performance tab offscreen.

    python3 tests/qml/test_level_bar.py
"""
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

FIND_BAR = """(function(){
    const st = [findPanel('currentTab')];
    while (st.length) {
        const it = st.pop();
        if (String(it).indexOf('LevelBar') === 0 && it.visible && it.width > 100) return it;
        for (let k = 0; k < it.children.length; k++) st.push(it.children[k]);
    }
    return null; })()"""


class LevelBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Scene(width=1920, height=1080)
        cls.s.ev("panels.open('quicksettings')")
        cls.s.wait(900)
        cls.s.ev("findPanel('currentTab').currentTab = 'performance'")
        cls.s.wait(800)
        cls.s.ev(f"(function(){{ const b = {FIND_BAR}; b.objectName = 'testLevelBar'; }})()")

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def fill(self):
        return self.s.ev("findNamed('testLevelBar').children[0].width")

    def track(self):
        return self.s.ev("findNamed('testLevelBar').width")

    def run_to(self, start, end):
        self.s.ev(f"findNamed('testLevelBar').value = {start}")
        self.s.wait(900)
        self.assertAlmostEqual(self.fill(), self.track() * start, delta=0.5)
        self.s.ev(f"findNamed('testLevelBar').value = {end}")
        samples = []
        for _ in range(140):
            self.s.wait(5)
            samples.append(self.fill())
        target = self.track() * end
        self.assertAlmostEqual(samples[-1], target, delta=0.5, msg="fill did not settle on the new value")
        return samples, target

    def test_rising_value_never_overshoots(self):
        samples, target = self.run_to(0.2, 0.9)
        self.assertLessEqual(max(samples), target + 0.5, f"fill overshot {target:.1f} to {max(samples):.1f}")
        backs = [b - a for a, b in zip(samples, samples[1:]) if b < a - 0.01]
        self.assertEqual(backs, [], "fill moved backwards on its way up")

    def test_falling_value_never_undershoots(self):
        samples, target = self.run_to(0.9, 0.1)
        self.assertGreaterEqual(min(samples), target - 0.5, f"fill dipped below {target:.1f} to {min(samples):.1f}")
        backs = [b - a for a, b in zip(samples, samples[1:]) if b > a + 0.01]
        self.assertEqual(backs, [], "fill moved backwards on its way down")


if __name__ == "__main__":
    unittest.main(verbosity=2)
