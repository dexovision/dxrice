#!/usr/bin/env python3
"""scripts/dxrice_layouts.py: Expansion, Spiral and Compact."""
import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_layouts as L  # noqa: E402

AREAS = [(0, 52, 1920, 1012), (0, 0, 2560, 1440), (0, 40, 1366, 740), (-1920, 0, 0, 1080),
         (100, 100, 1124, 868), (0, 0, 3440, 1440), (0, 0, 800, 600), (0, 0, 1080, 1920)]
GAPS = (0, 5, 12)


def inside(r, a):
    return r[0] >= a[0] and r[1] >= a[1] and r[0] + r[2] <= a[2] and r[1] + r[3] <= a[3]


def sep(a, b):
    """The gap between two rects (negative when they overlap)."""
    dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]))
    dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]))
    return max(dx, dy)


class Invariants(unittest.TestCase):
    def cases(self):
        for mode, area, gap, n in itertools.product(L.MODES, AREAS, GAPS, list(range(0, 13)) + [20, 33, 60]):
            yield mode, area, gap, n

    def test_every_rect_is_inside_the_area_and_none_overlap(self):
        for mode, area, gap, n in self.cases():
            rects = L.layout(mode, n, area, gap)
            self.assertEqual(len(rects), n, (mode, area, gap, n))
            placed = [r for r in rects if r is not None]
            for r in placed:
                self.assertGreater(r[2], 0)
                self.assertGreater(r[3], 0)
                self.assertTrue(inside(r, area), (mode, area, gap, n, r))
            for a, b in itertools.combinations(placed, 2):
                # integer rounding of two edges may take a pixel off the gap
                self.assertGreaterEqual(sep(a, b), gap - 1, (mode, area, gap, n, a, b))

    def test_a_window_is_unmanaged_not_shrunk_to_nothing(self):
        for mode, area, gap, n in self.cases():
            rects = L.layout(mode, n, area, gap)
            for i, r in enumerate(rects):
                if r is not None and not (mode == "expansion" and i == n - 1):
                    self.assertGreaterEqual(r[2], L.MIN_W, (mode, area, gap, n, r))
                    self.assertGreaterEqual(r[3], L.MIN_H, (mode, area, gap, n, r))

    def test_up_to_capacity_every_window_is_placed(self):
        for mode in L.MODES:
            for area in AREAS:
                cap = L.capacity(area, 5)
                for n in range(1, min(cap, 6) + 1):
                    rects = L.layout(mode, n, area, 5)
                    if mode == "spiral" and n > 5:
                        continue         # a spiral narrows by design; past ~5 it may run out of room first
                    self.assertNotIn(None, rects, (mode, area, n, cap))

    def test_deterministic(self):
        for mode, area, gap, n in self.cases():
            self.assertEqual(L.layout(mode, n, area, gap, n - 1 if n else None),
                             L.layout(mode, n, area, gap, n - 1 if n else None))

    def test_zero_windows(self):
        for mode in L.MODES:
            self.assertEqual(L.layout(mode, 0, AREAS[0], 5), [])


class Shapes(unittest.TestCase):
    A = (0, 52, 1920, 1012)

    def area(self, r):
        return r[2] * r[3]

    def test_expansion_gives_the_primary_a_generous_share_and_uses_the_space(self):
        for n in (2, 3, 4, 6, 9):
            rects = L.expansion(n, self.A, 5)
            p = rects[n - 1]
            others = [r for r in rects[:-1] if r]
            self.assertGreater(self.area(p), 1.6 * max(self.area(r) for r in others), n)
            total = sum(self.area(r) for r in rects if r)
            self.assertGreater(total / ((self.A[2] - self.A[0]) * (self.A[3] - self.A[1])), 0.93, n)

    def test_expansion_primary_can_be_any_window(self):
        a = L.expansion(5, self.A, 5, primary=1)
        self.assertGreater(self.area(a[1]), 1.6 * max(self.area(r) for i, r in enumerate(a) if i != 1))
        self.assertEqual(a[1][:2], (0, 52))

    def test_expansion_one_window_is_nearly_the_whole_area_but_centred(self):
        (r,) = L.expansion(1, self.A, 5)
        self.assertGreater(self.area(r), 0.8 * 1920 * 960)
        self.assertEqual(r[0] - 0, 1920 - (r[0] + r[2]))

    def test_expansion_newest_secondary_is_on_top(self):
        rects = L.expansion(4, self.A, 5)          # primary = 3; 2 is the newest of the rest
        self.assertLess(rects[2][1], rects[1][1])
        self.assertLess(rects[1][1], rects[0][1])

    def test_spiral_turns_clockwise_and_halves(self):
        r = L.spiral(4, self.A, 5)
        self.assertEqual(r[0][:2], (0, 52))                       # left half
        self.assertGreater(r[0][3], r[1][3] * 1.9)
        self.assertEqual(r[1][1], 52)                              # then top of the right
        self.assertGreater(r[2][0], r[3][0] - 1)                   # then right...
        self.assertGreater(r[3][1], r[1][1])                       # ...then bottom

    def test_spiral_runs_out_gracefully_with_many_windows(self):
        r = L.spiral(12, (0, 0, 1920, 1080), 5)
        self.assertGreaterEqual(len([x for x in r if x]), 6)

    def test_compact_has_no_favourite(self):
        r = L.compact(6, self.A, 5)
        areas = sorted(self.area(x) for x in r)
        self.assertLess(areas[-1] / areas[0], 1.1)

    def test_compact_last_row_is_stretched_over_the_full_width(self):
        r = L.compact(5, self.A, 5)
        last = [x for x in r if x[1] == max(y[1] for y in r)]
        self.assertEqual(last[0][0], 0)
        self.assertEqual(last[-1][0] + last[-1][2], 1920)

    def test_the_three_modes_are_different_layouts(self):
        for n in (3, 4, 5):
            seen = {m: tuple(L.layout(m, n, self.A, 5)) for m in L.MODES}
            self.assertEqual(len(set(seen.values())), 3, n)

    def test_capacity_and_overflow(self):
        small = (0, 0, 800, 600)
        self.assertLessEqual(L.capacity(small, 5), 6)
        rects = L.expansion(40, small, 5)
        self.assertGreater(len([r for r in rects if r is None]), 20)


class Settings(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(L.normalize(None), "expansion")
        self.assertEqual(L.normalize(""), "expansion")
        self.assertEqual(L.normalize("Spiral"), "spiral")
        self.assertEqual(L.normalize(" compact "), "compact")
        self.assertEqual(L.normalize("galaxy"), "expansion")      # not a layout mode
        self.assertEqual(L.normalize(7), "expansion")
        self.assertEqual(L.DEFAULT_MODE, "expansion")


if __name__ == "__main__":
    unittest.main()
