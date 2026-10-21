#!/usr/bin/env python3
"""The three window layouts, run on the same windows: each is its own
method, so the same input gives three different compositions, each of them
sound (nothing overlaps, every pair keeps a gap); Galaxy and Expansion keep
every window's size; Expansion grows from the middle of the screen whatever
the windows' starting places; and one saved setting decides what both a
new window and SUPER+G use.

    python3 scripts/dxrice_test_layout_modes.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_compact  # noqa: E402
import dxrice_expansion  # noqa: E402
import dxrice_layout_apply as lap  # noqa: E402
import dxrice_spiral  # noqa: E402

MONITOR = (0, 52, 1920, 1080)
BAND = (32, 56)
GAP = 16
# six ordinary windows, in creation order, scattered where they opened
WINDOWS = [(300, 200, 900, 600), (1300, 150, 700, 500), (100, 700, 600, 420),
           (900, 650, 520, 380), (1500, 600, 480, 640), (600, 300, 800, 520)]


def as_rects_xywh(rects):
    return [(x0, y0, x1 - x0, y1 - y0) for x0, y0, x1, y1 in rects]


def galaxy():
    return as_rects_xywh(dxrice_spiral.arrange([(w, h) for _x, _y, w, h in WINDOWS], [], MONITOR, BAND))


def expansion(windows=WINDOWS):
    return as_rects_xywh(dxrice_expansion.arrange(windows, [], MONITOR, BAND))


def compact():
    eligible = [{"address": f"0x{i}", "at": [x, y], "size": [w, h]} for i, (x, y, w, h) in enumerate(WINDOWS)]
    out = {a: (x, y, w, h) for a, x, y, w, h in dxrice_compact.auto_arrange(eligible, [], MONITOR, GAP)}
    return [out[f"0x{i}"] for i in range(len(WINDOWS))]


def overlap(a, b, gap=0):
    return a[0] < b[0] + b[2] + gap and b[0] < a[0] + a[2] + gap and a[1] < b[1] + b[3] + gap and b[1] < a[1] + a[3] + gap


class ThreeMethodsTest(unittest.TestCase):
    def setUp(self):
        self.out = {"galaxy": galaxy(), "compact": compact(), "expansion": expansion()}

    def test_each_is_sound(self):
        for name, rects in self.out.items():
            self.assertEqual(len(rects), len(WINDOWS), name)
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    self.assertFalse(overlap(rects[i], rects[j], gap=GAP - 1), f"{name}: {rects[i]} and {rects[j]} touch or overlap")

    def test_the_three_give_three_different_compositions(self):
        names = list(self.out)
        for a in range(3):
            for b in range(a + 1, 3):
                ra, rb = self.out[names[a]], self.out[names[b]]
                moved = sum(1 for p, q in zip(ra, rb) if abs(p[0] - q[0]) + abs(p[1] - q[1]) > 40)
                self.assertGreaterEqual(moved, len(WINDOWS) // 2, f"{names[a]} and {names[b]} placed the windows alike")

    def test_galaxy_and_expansion_keep_every_size(self):
        for name in ("galaxy", "expansion"):
            self.assertEqual([(w, h) for _x, _y, w, h in self.out[name]], [(w, h) for _x, _y, w, h in WINDOWS], name)

    def test_expansion_grows_from_the_screens_middle_wherever_the_windows_were(self):
        cx, cy = (MONITOR[0] + MONITOR[2]) / 2, (MONITOR[1] + MONITOR[3]) / 2
        shifted = [(x - 2500, y + 1800, w, h) for x, y, w, h in WINDOWS]     # all panned far away
        for rects in (self.out["expansion"], expansion(shifted)):
            # the group's box is centred on the screen
            x0 = min(r[0] for r in rects); x1 = max(r[0] + r[2] for r in rects)
            y0 = min(r[1] for r in rects); y1 = max(r[1] + r[3] for r in rects)
            self.assertAlmostEqual((x0 + x1) / 2, cx, delta=2)
            self.assertAlmostEqual((y0 + y1) / 2, cy, delta=2)
        self.assertEqual(expansion(shifted), self.out["expansion"], "the anchor followed the windows instead of the screen")


class OneSettingTest(unittest.TestCase):
    def test_one_key_decides_new_windows_and_super_g(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "theme.json")
            for choice in lap.CHOICES:
                lap.save_mode(choice, path)
                self.assertEqual(lap.mode(path), choice)
                with open(path) as f:
                    text = f.read()
                self.assertIn('"window_layout"', text)
                self.assertNotIn("layout_auto_place", text)
                self.assertNotIn("layout_super_g", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
