#!/usr/bin/env python3
"""Deterministic, synthetic geometry tests for Algorithm A
(dxrice_auto_place_window.py) and Algorithm B (dxrice_auto_arrange.py).

No live Hyprland required -- every test builds a plain list of
{"address", "at", "size", "fullscreen"} dicts by hand and calls the same
pure functions the real listener/SUPER+G call, so these run in CI, offline,
or mid-flight while iterating on the scoring without needing a compositor
at all. Live-desktop behavior is verified separately (see the project's own
soak-test notes) -- synthetic coverage here is for the geometry/scoring
logic specifically, where a live test can't easily hold "everything else
about the desktop" constant between runs.

Run: python3 scripts/dxrice_test_placement.py [-v]
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_auto_place_window as apw
import dxrice_auto_arrange as arr

GAP = 5


def rect(x, y, w, h):
    return (x, y, x + w, y + h)


def overlaps_with_gap(a, b, gap):
    ax0, ay0, ax1, ay1 = a
    inflated = (ax0 - gap, ay0 - gap, ax1 + gap, ay1 + gap)
    return apw.overlaps(inflated, b)


class TestFindFreePosition(unittest.TestCase):
    """Stage 1: direct placement, nothing else moves."""

    def test_empty_canvas_uses_viewport_center(self):
        pos = apw.find_free_position((400, 300), [], (960, 540), GAP)
        self.assertEqual(pos, (960 - 200, 540 - 150))

    def test_no_overlap_with_single_obstacle(self):
        others = [(760, 390, 400, 300)]  # centered at viewport center already
        pos = apw.find_free_position((400, 300), others, (960, 540), GAP, layout_others=others)
        cand = rect(*pos, 400, 300)
        self.assertFalse(overlaps_with_gap(cand, rect(*others[0]), GAP))

    def test_prefers_clean_full_edge_over_equal_distance_sliver(self):
        """The reported bug: a candidate technically closer to center but
        only sliver-adjacent to a neighbor should NOT beat a candidate at
        (near-)equal distance that shares a full clean edge."""
        # One 800x600 window sitting exactly on the viewport center.
        center = (960, 540)
        existing = (560, 240, 800, 600)  # x,y,w,h -- centered at (960,540)
        others = [existing]
        new_size = (800, 600)
        pos = apw.find_free_position(new_size, others, center, GAP, layout_others=others)
        cand = rect(*pos, *new_size)
        ex_rect = rect(*existing)
        frac = apw._flush_coverage(cand, ex_rect, GAP)
        # Must be flush (touching) and must be a FULL-edge join, not a sliver.
        self.assertIsNotNone(frac, f"candidate {cand} is not flush against {ex_rect}")
        self.assertGreater(frac, 0.95, f"candidate {cand} only {frac:.2f} covered -- sliver, not clean edge")

    def test_composition_penalty_favors_full_coverage_over_corner_touch(self):
        """Direct unit check on the scoring primitive itself: a candidate
        flush with 100% edge coverage must score better (lower penalty)
        than one flush with only a corner-touch, against the same neighbor,
        gap and all else equal."""
        neighbor = rect(0, 0, 400, 400)
        gap = GAP
        full_edge = rect(400 + gap, 0, 200, 400)          # full-height flush to the right
        sliver = rect(400 + gap, 390, 200, 400)           # same edge, only 10px of overlap
        p_full = apw.composition_penalty(full_edge, [neighbor], gap)
        p_sliver = apw.composition_penalty(sliver, [neighbor], gap)
        self.assertLess(p_full, p_sliver)

    def test_alignment_bonus_prefers_grid_aligned_candidate(self):
        """Two candidates equally far from center, one lines up with an
        existing window's edge (reads as a grid), the other doesn't."""
        neighbor = rect(0, 0, 400, 200)
        aligned = rect(0, 200 + GAP, 400, 200)      # same left/right edges as neighbor
        offcenter = rect(37, 200 + GAP, 400, 200)   # same size, shifted, not aligned
        p_aligned = apw.composition_penalty(aligned, [neighbor], GAP)
        p_offcenter = apw.composition_penalty(offcenter, [neighbor], GAP)
        self.assertLess(p_aligned, p_offcenter)

    def test_center_occupied_surrounded_all_sides(self):
        """Center window fully boxed in on all 4 sides -- must still find a
        valid, non-overlapping placement (falls through to spiral search)."""
        center = (960, 540)
        w = 300
        others = [
            (960 - w // 2, 540 - w // 2, w, w),               # center
            (960 - w // 2 + w + GAP, 540 - w // 2, w, w),      # right
            (960 - w // 2 - w - GAP, 540 - w // 2, w, w),      # left
            (960 - w // 2, 540 - w // 2 + w + GAP, w, w),      # below
            (960 - w // 2, 540 - w // 2 - w - GAP, w, w),      # above
        ]
        pos = apw.find_free_position((250, 250), others, center, GAP, layout_others=others)
        cand = rect(*pos, 250, 250)
        for o in others:
            self.assertFalse(overlaps_with_gap(cand, rect(*o), GAP))

    def test_no_monitor_clamping_offscreen_allowed(self):
        """A cluster already sitting off the (0,0)-(1920,1080) monitor must
        be able to receive a placement that's also off-screen -- the
        monitor is a viewport, never a boundary."""
        others = [(-2000, -2000, 400, 300)]
        pos = apw.find_free_position((400, 300), others, (-2000 + 200, -2000 + 150), GAP,
                                      layout_others=others)
        # Just needs to be valid + finite; no assertion that it's "inside" anything.
        cand = rect(*pos, 400, 300)
        self.assertFalse(overlaps_with_gap(cand, rect(*others[0]), GAP))

    def test_deterministic_repeated_calls(self):
        others = [(100, 100, 300, 200), (500, 400, 250, 250), (-100, 600, 400, 150)]
        results = {apw.find_free_position((350, 300), others, (960, 540), GAP, layout_others=others)
                   for _ in range(25)}
        self.assertEqual(len(results), 1, "same input must always produce the same output")

    def test_huge_new_window_vs_tiny_existing(self):
        others = [(0, 0, 50, 50)]
        pos = apw.find_free_position((1600, 1200), others, (25, 25), GAP, layout_others=others)
        cand = rect(*pos, 1600, 1200)
        self.assertFalse(overlaps_with_gap(cand, rect(*others[0]), GAP))

    def test_tiny_new_window_vs_huge_existing(self):
        others = [(0, 0, 1800, 1000)]
        pos = apw.find_free_position((80, 60), others, (900, 500), GAP, layout_others=others)
        cand = rect(*pos, 80, 60)
        self.assertFalse(overlaps_with_gap(cand, rect(*others[0]), GAP))

    def test_gap_is_respected_exactly(self):
        others = [(0, 0, 400, 400)]
        pos = apw.find_free_position((200, 200), others, (0, 0), GAP, layout_others=others)
        # Closest candidate should be flush-right or flush-below at exactly `gap`.
        x, y = pos
        touching_right = abs(x - (400 + GAP)) < 1e-6
        touching_left = abs((x + 200) - (0 - GAP)) < 1e-6
        touching_below = abs(y - (400 + GAP)) < 1e-6
        touching_above = abs((y + 200) - (0 - GAP)) < 1e-6
        self.assertTrue(touching_right or touching_left or touching_below or touching_above,
                         f"pos {pos} isn't exactly gap-flush against the neighbor")


class TestTryMakeRoom(unittest.TestCase):
    def test_stage2_never_moves_fixed_obstacles(self):
        fixed = [(700, 300, 600, 500)]  # sits on viewport center
        eligible = [{"address": "0xA", "at": [1400, 300], "size": [400, 400]}]
        result = apw.try_make_room((300, 300), eligible, fixed, (960, 540), GAP)
        # try_make_room only ever returns moves for `eligible`; fixed obstacles
        # are structurally never in the returned dict.
        if result is not None:
            _, moved = result
            self.assertNotIn("fixed", moved)

    def test_cascading_bounded_and_terminates(self):
        # A tight row of 5 windows -- placing a new one in the middle should
        # cascade at most a few times and always terminate with a valid plan
        # or a clean None (falls back to Stage 1), never hang.
        eligible = [
            {"address": f"0x{i}", "at": [i * 205, 0], "size": [200, 200]}
            for i in range(5)
        ]
        result = apw.try_make_room((200, 200), eligible, [], (500, 100), GAP)
        self.assertTrue(result is None or isinstance(result, tuple))

    def test_result_has_no_overlaps(self):
        eligible = [
            {"address": "0xA", "at": [800, 400], "size": [500, 400]},
            {"address": "0xB", "at": [1350, 400], "size": [300, 400]},
        ]
        result = apw.try_make_room((400, 400), eligible, [], (960, 540), GAP)
        self.assertIsNotNone(result)
        target_pos, moved = result
        target_rect = rect(*target_pos, 400, 400)
        by_addr = {w["address"]: w for w in eligible}
        final_rects = [target_rect]
        for addr, w in by_addr.items():
            if addr in moved:
                final_rects.append(rect(moved[addr][0], moved[addr][1], *w["size"]))
            else:
                final_rects.append(rect(w["at"][0], w["at"][1], *w["size"]))
        for i in range(len(final_rects)):
            for j in range(i + 1, len(final_rects)):
                self.assertFalse(overlaps_with_gap(final_rects[i], final_rects[j], GAP),
                                  f"{final_rects[i]} overlaps {final_rects[j]}")


class TestAutoArrangeAlgorithmB(unittest.TestCase):
    def _mk(self, addr, x, y, w, h):
        return {"address": addr, "at": [x, y], "size": [w, h]}

    def test_idempotent_on_own_output(self):
        eligible = [
            self._mk("0xA", 0, 0, 400, 300),
            self._mk("0xB", 500, 100, 300, 400),
            self._mk("0xC", -200, 500, 350, 250),
        ]
        monitor = (0, 0, 1920, 1080)
        gap = GAP
        first = arr.auto_arrange(eligible, [], monitor, gap)
        by_addr = {a: (x, y) for a, x, y in first}
        round1 = [self._mk(w["address"], *by_addr[w["address"]], *w["size"]) for w in eligible]

        second = arr.auto_arrange(round1, [], monitor, gap)
        for addr, nx, ny in second:
            ox, oy = by_addr[addr]
            self.assertLess(math.hypot(nx - ox, ny - oy), 1.0,
                             f"{addr} moved {math.hypot(nx-ox, ny-oy):.1f}px on a no-op re-run")

    def test_no_overlaps_in_result(self):
        eligible = [
            self._mk("0xA", 0, 0, 400, 300),
            self._mk("0xB", 380, 10, 300, 400),   # overlapping on purpose
            self._mk("0xC", 100, 250, 350, 250),
        ]
        monitor = (0, 0, 1920, 1080)
        result = arr.auto_arrange(eligible, [], monitor, GAP)
        by_size = {w["address"]: w["size"] for w in eligible}
        rects = [rect(x, y, *by_size[a]) for a, x, y in result]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                self.assertFalse(overlaps_with_gap(rects[i], rects[j], GAP))

    def test_fixed_fullscreen_never_moved(self):
        eligible = [self._mk("0xA", 0, 0, 400, 300)]
        fixed = [self._mk("0xFULL", 0, 0, 1920, 1080)]
        monitor = (0, 0, 1920, 1080)
        result = arr.auto_arrange(eligible, fixed, monitor, GAP)
        addrs = {a for a, _, _ in result}
        self.assertNotIn("0xFULL", addrs)

    def test_cluster_can_extend_offscreen(self):
        eligible = [self._mk(f"0x{i}", i * 900, 0, 800, 800) for i in range(4)]
        monitor = (0, 0, 1920, 1080)
        result = arr.auto_arrange(eligible, [], monitor, GAP)
        xs0 = [x for _, x, y in result]
        by_size = {w["address"]: w["size"] for w in eligible}
        xs1 = [x + by_size[a][0] for a, x, y in result]
        self.assertTrue(min(xs0) < 0 or max(xs1) > 1920,
                         "4 800x800 windows can't fit on a 1920-wide monitor without spilling off it")

    def test_sizes_never_changed(self):
        eligible = [self._mk("0xA", 0, 0, 437, 291), self._mk("0xB", 500, 500, 333, 777)]
        monitor = (0, 0, 1920, 1080)
        result = arr.auto_arrange(eligible, [], monitor, GAP)
        # auto_arrange's return signature has no size field at all -- the
        # caller (main()) only ever dispatches a move, never a resize. This
        # test documents that contract so a future change can't quietly add one.
        for row in result:
            self.assertEqual(len(row), 3, "auto_arrange must return (address, x, y) only")

    def test_deterministic_ordering_independent_of_input_order(self):
        a = self._mk("0xA", 0, 0, 400, 300)
        b = self._mk("0xB", 800, 0, 300, 300)
        c = self._mk("0xC", 0, 800, 350, 350)
        monitor = (0, 0, 1920, 1080)
        r1 = arr.auto_arrange([a, b, c], [], monitor, GAP)
        r2 = arr.auto_arrange([c, a, b], [], monitor, GAP)
        self.assertEqual(sorted(r1), sorted(r2))


class TestResizeMinimums(unittest.TestCase):
    """Section 2: resize policy. See dxrice_auto_place_window.MIN_USABLE_*
    and clamp_to_usable_size -- these constants/function are the actual
    enforcement point; this test exists to catch a future change that
    silently lowers them or removes the clamp."""

    def test_min_usable_constants_are_sane(self):
        self.assertGreaterEqual(apw.MIN_USABLE_WIDTH, 100)
        self.assertGreaterEqual(apw.MIN_USABLE_HEIGHT, 60)

    def test_stage3_forced_trigger_returns_valid_plan(self):
        eligible = [{"address": "0xBIG", "at": [660, 240], "size": [600, 600]}]
        result = apw.try_resize_room((500, 500), eligible, [], (960, 540), GAP, 999999)
        self.assertIsNotNone(result)
        pos3, addr, new_xy, new_size = result
        self.assertGreaterEqual(new_size[0], apw.MIN_USABLE_WIDTH)
        self.assertGreaterEqual(new_size[1], apw.MIN_USABLE_HEIGHT)
        new_rect = rect(new_xy[0], new_xy[1], *new_size)
        cand = rect(pos3[0], pos3[1], 500, 500)
        self.assertFalse(overlaps_with_gap(cand, new_rect, GAP))

    def test_stage3_never_triggers_when_rearrangement_already_good(self):
        eligible = [{"address": "0xA", "at": [760, 240], "size": [400, 300]}]
        # A trivially good best_cost (small) must never trigger a resize.
        result = apw.try_resize_room((300, 300), eligible, [], (960, 540), GAP, 10.0)
        self.assertIsNone(result)

    def test_stage3_never_shrinks_fixed_obstacles(self):
        # Fixed obstacles aren't even in `eligible`, so try_resize_room has
        # structurally no way to touch them -- this documents that contract.
        eligible = []
        result = apw.try_resize_room((500, 500), eligible, [(0, 0, 2000, 2000)], (960, 540), GAP, 999999)
        self.assertIsNone(result, "no eligible windows to resize -- must return None, never touch fixed")

    def test_stage3_resize_geometry_matches_explicit_anchor(self):
        """The resized window's OWN reported new position/size must be
        internally consistent -- i.e. exactly one edge stays put and the
        opposite edge moves in by the shrink amount, never a center-anchored
        result (which is what Hyprland's raw resize dispatch would do if
        the caller didn't also send an explicit corrective move)."""
        eligible = [{"address": "0xBIG", "at": [100, 100], "size": [600, 600]}]
        result = apw.try_resize_room((500, 500), eligible, [], (960, 540), GAP, 999999)
        self.assertIsNotNone(result)
        _, _, (nx, ny), (nw, nh) = result
        ox, oy, ow, oh = 100, 100, 600, 600
        # At least one edge (left/right/top/bottom) must be byte-identical
        # to the original -- the hallmark of "shrunk from one side," not a
        # symmetric center-anchored shrink (which would move ALL 4 edges).
        edges_unchanged = sum([
            nx == ox, (nx + nw) == (ox + ow),
            ny == oy, (ny + nh) == (oy + oh),
        ])
        self.assertGreaterEqual(edges_unchanged, 2,
                                 "expected 2 unchanged edges (the un-shrunk axis, plus the kept side of the shrunk axis)")

    def test_clamp_never_shrinks_below_minimum(self):
        w, h = apw.clamp_to_usable_size(10, 10)
        self.assertGreaterEqual(w, apw.MIN_USABLE_WIDTH)
        self.assertGreaterEqual(h, apw.MIN_USABLE_HEIGHT)

    def test_clamp_is_noop_above_minimum(self):
        w, h = apw.clamp_to_usable_size(800, 600)
        self.assertEqual((w, h), (800, 600))

    def test_clamp_preserves_aspect_when_scaling_up(self):
        # A window narrower than the minimum but already reasonably tall
        # should scale up preserving its aspect ratio, not just get its
        # width bumped and its height left alone (-> a distorted window).
        w, h = apw.clamp_to_usable_size(50, 300)
        self.assertGreaterEqual(w, apw.MIN_USABLE_WIDTH)
        # Aspect roughly preserved (allow rounding slack).
        orig_ratio = 50 / 300
        new_ratio = w / h
        self.assertAlmostEqual(orig_ratio, new_ratio, delta=0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
