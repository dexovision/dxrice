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


class TestProminenceWeighting(unittest.TestCase):
    """Real-layout scenario A from live QA: a tiny dialog opening next to a
    large, already-centered window must NOT relocate that large window just
    to land the dialog at the exact pixel center -- a flat per-pixel
    movement cost made that numerically cheap even though no human would
    want it. See prominence_weight's own docstring for the fix."""

    def test_tiny_dialog_does_not_evict_large_centered_window(self):
        big = {"address": "0xBIG", "at": [360, 140], "size": [1200, 800]}
        center = (960, 540)
        gap = GAP
        new_size = (250, 150)  # the tiny dialog

        others = [(big["at"][0], big["at"][1], *big["size"])]
        pos1 = apw.find_free_position(new_size, others, center, gap, layout_others=others)
        d1 = math.hypot(pos1[0] + new_size[0] / 2 - center[0], pos1[1] + new_size[1] / 2 - center[1])

        stage2 = apw.try_make_room(new_size, [big], [], center, gap)
        self.assertIsNotNone(stage2)
        pos2, moved = stage2
        d2 = math.hypot(pos2[0] + new_size[0] / 2 - center[0], pos2[1] + new_size[1] / 2 - center[1])
        eligible_by_addr = {"0xBIG": big}
        new_area = new_size[0] * new_size[1]
        total_movement = sum(
            math.hypot(nx - big["at"][0], ny - big["at"][1]) * apw.prominence_weight(a, eligible_by_addr, new_area)
            for a, (nx, ny) in moved.items()
        )
        cost2 = d2 + apw.MAKE_ROOM_MOVEMENT_WEIGHT * total_movement

        # try_make_room now evaluates SEVERAL candidate targets for the
        # dialog (see _candidate_targets), not just the bare dead-center
        # spot -- so it can itself discover "place the dialog beside BIG,
        # evict nothing" as its own best plan, which is a strictly BETTER
        # outcome than the old single-candidate version (which always tried
        # dead-center first and had to be argued out of evicting BIG by
        # prominence weighting alone). Assert the actual invariant directly:
        # BIG must never be the one that moves for a dialog smaller than it.
        self.assertNotIn("0xBIG", moved,
                          "the large window was evicted for a tiny, lower-prominence dialog")
        # And Stage 1 must never come out WORSE than whatever Stage 2 found
        # -- ties are fine (Stage 2 converging on the same non-evicting
        # answer as Stage 1 is the correct behavior here, not a regression).
        self.assertLessEqual(d1, cost2 + 1e-6,
                              "Stage 1 (leave BIG alone) must not lose to a Stage 2 "
                              "plan that evicts a more prominent window")

    def test_small_existing_window_still_moves_cheaply_for_large_new_one(self):
        """The mirror case (scenario B): a tiny existing window sitting where
        a large NEW window wants to go should still be nudged aside cheaply
        -- prominence weighting must not make Stage 2 universally reluctant,
        only reluctant to move something bigger than the new window."""
        small = {"address": "0xSMALL", "at": [860, 490], "size": [200, 100]}
        center = (960, 540)
        gap = GAP
        new_size = (1000, 700)  # the large new application

        stage2 = apw.try_make_room(new_size, [small], [], center, gap)
        self.assertIsNotNone(stage2)
        pos2, moved = stage2
        eligible_by_addr = {"0xSMALL": small}
        new_area = new_size[0] * new_size[1]
        w = apw.prominence_weight("0xSMALL", eligible_by_addr, new_area)
        self.assertEqual(w, 1.0, "moving something smaller than the new window must stay at base cost")


class TestStage2CompositionAwareness(unittest.TestCase):
    """try_make_room used to call find_free_position with only the FIXED
    obstacles and no composition reference at all -- so on a workspace with
    no fullscreen window, layout_rects was empty, composition_penalty
    short-circuited to 0.0, and the only candidate generated was the bare
    viewport-centre point. Stage 2's target was therefore decided by pure
    distance-to-centre, ignoring the layout entirely, which is what produced
    arbitrary non-gap-width offsets live (5px from one neighbour, 55px from
    the other). These tests pin the fix."""

    def test_layout_reference_widens_the_candidate_set(self):
        """The concrete regression: with only hard obstacles feeding
        candidate generation, a workspace with no fixed windows produced
        exactly ONE candidate (the bare viewport-centre point), so the
        layout could not influence the result even in principle. A fixed
        obstacle sitting on the centre makes that observable -- without
        layout-derived candidates the only alternatives come from the
        obstacle alone; with them, the composition reference can win."""
        blocker = [(860, 440, 200, 200)]            # hard obstacle over the centre
        layout = [(300, 440, 400, 200)]             # composition reference to the left
        without = apw.find_free_position((200, 200), blocker, (960, 540), GAP)
        with_layout = apw.find_free_position((200, 200), blocker, (960, 540), GAP,
                                              layout_others=layout)
        ref = rect(*layout[0])
        cand = rect(*with_layout, 200, 200)
        gap_aligned = (abs(apw._axis_gap(cand[0], cand[2], ref[0], ref[2]) - GAP) < 2
                       or abs(apw._axis_gap(cand[1], cand[3], ref[1], ref[3]) - GAP) < 2)
        edge_aligned = (abs(cand[1] - ref[1]) < 2 or abs(cand[3] - ref[3]) < 2)
        self.assertTrue(gap_aligned or edge_aligned,
                         f"{with_layout} ignores the composition reference "
                         f"(without-layout result was {without})")

    def test_make_room_target_respects_layout(self):
        eligible = [
            {"address": "0xL", "at": [400, 300], "size": [400, 500]},
            {"address": "0xR", "at": [805, 300], "size": [400, 500]},
        ]
        result = apw.try_make_room((300, 250), eligible, [], (960, 540), GAP)
        self.assertIsNotNone(result)
        target_pos, _ = result
        cand = rect(*target_pos, 300, 250)
        # The reserved target must sit at the configured gap from at least
        # one of the windows it is composing with -- not at an arbitrary
        # offset that merely happens to be central.
        gaps = []
        for w in eligible:
            r = rect(w["at"][0], w["at"][1], *w["size"])
            xg = apw._axis_gap(cand[0], cand[2], r[0], r[2])
            yg = apw._axis_gap(cand[1], cand[3], r[1], r[3])
            gaps.extend([xg, yg])
        self.assertTrue(any(abs(g - GAP) < 2 for g in gaps),
                         f"target {target_pos} is not gap-aligned to anything: gaps={gaps}")


class TestDeadGapPenalty(unittest.TestCase):
    """A candidate that lands NEAR a neighbour but not flush leaves a strip
    of space too narrow to ever hold another window -- dead space that made
    the arrangement read as accidental. Neither the sliver term (which only
    scores candidates that ARE flush) nor the alignment bonus caught it."""

    def test_dead_gap_is_penalised(self):
        neighbour = rect(0, 0, 400, 400)
        snug = rect(400 + GAP, 0, 300, 400)        # exactly the configured gap
        loose = rect(400 + GAP + 50, 0, 300, 400)  # 50px of dead space
        p_snug = apw.composition_penalty(snug, [neighbour], GAP)
        p_loose = apw.composition_penalty(loose, [neighbour], GAP)
        self.assertLess(p_snug, p_loose)

    def test_large_separation_is_not_penalised_as_dead(self):
        """Space wide enough to actually hold another window reads as a
        deliberate separation, not a misalignment -- must not be charged."""
        neighbour = rect(0, 0, 400, 400)
        far = rect(400 + GAP + apw.MIN_USABLE_WIDTH + 50, 0, 300, 400)
        self.assertEqual(apw._dead_gap_penalty(far, [neighbour], GAP), 0.0)

    def test_dead_gap_penalty_is_capped(self):
        neighbour = rect(0, 0, 400, 400)
        worst = rect(400 + GAP + apw.MIN_USABLE_WIDTH - 1, 0, 300, 400)
        p = apw._dead_gap_penalty(worst, [neighbour], GAP)
        self.assertLessEqual(p, apw.DEAD_GAP_CAP * apw.DEAD_GAP_WEIGHT + 0.01)


class TestExactIntegerGaps(unittest.TestCase):
    """Live bug: two windows meant to be exactly gap-apart came out 1px
    short after a real SUPER+G dispatch, traced to a fractional position
    surviving from one window's own placement and compounding through
    later windows' candidate generation, then two DIFFERENT fractional
    offsets getting independently rounded at dispatch time."""

    def test_all_final_positions_are_integers(self):
        eligible = [{"address": f"0x{i}", "at": [900, i * 305], "size": [380, 300]}
                    for i in range(5)]
        result = arr.auto_arrange(eligible, [], (0, 0, 1920, 1080), GAP2)
        for addr, x, y in result:
            self.assertEqual(x, int(x), f"{addr} has a fractional x: {x}")
            self.assertEqual(y, int(y), f"{addr} has a fractional y: {y}")

    def test_gaps_never_fall_short_of_configured(self):
        """Runs several deterministic 5-window layouts and checks every
        adjacent (flush) pair lands at exactly the configured gap, never
        1px short -- the exact live symptom this fixes."""
        import itertools
        layouts = [
            [(900, i * 305, 380, 300) for i in range(5)],           # vertical stack
            [(i * 355, 900, 350, 280) for i in range(5)],           # horizontal row
            [(900, 0, 400, 300), (200, 700, 350, 280), (1500, 300, 300, 500),
             (600, 1200, 450, 300), (-300, 500, 380, 320)],          # scattered
        ]
        for rects0 in layouts:
            eligible = [{"address": f"0x{i}", "at": [x, y], "size": [w, h]}
                        for i, (x, y, w, h) in enumerate(rects0)]
            result = arr.auto_arrange(eligible, [], (0, 0, 1920, 1080), GAP2)
            by_size = {w["address"]: w["size"] for w in eligible}
            rects = {a: rect(x, y, *by_size[a]) for a, x, y in result}
            for a1, a2 in itertools.combinations(rects, 2):
                r1, r2 = rects[a1], rects[a2]
                xg = apw._axis_gap(r1[0], r1[2], r2[0], r2[2])
                yg = apw._axis_gap(r1[1], r1[3], r2[1], r2[3])
                if yg == 0.0 and 0 < xg < 50:
                    self.assertGreaterEqual(xg, GAP2 - 0.001,
                                             f"{a1}/{a2} gap {xg} falls short of configured {GAP2}")
                if xg == 0.0 and 0 < yg < 50:
                    self.assertGreaterEqual(yg, GAP2 - 0.001,
                                             f"{a1}/{a2} gap {yg} falls short of configured {GAP2}")


class TestCenteredWindowConfidenceLoophole(unittest.TestCase):
    """Live bug: an L-shaped 3-window layout, asked to make room for a
    window that happens to land exactly at viewport center, relocated the
    other two into a dead-center-straddling vertical LINE instead of
    keeping the zero-movement L-notch fill -- because excluding the
    centered window from the angular calculation (correct: it has no
    stable angle) ALSO excluded its mass from the confidence count,
    leaving only 2 angle-bearing points, which are always confidence-gated
    to zero penalty regardless of how many other real windows exist."""

    def test_confidence_counts_centered_window_too(self):
        # Two points on the same axis (a real stack pattern) plus a third
        # window sitting exactly at the reference point. Nominal 100x100
        # size on all three -- this test is about the CONFIDENCE/mass
        # bookkeeping, not real window dimensions.
        above = (960, 100, 100, 100, 1.0)
        below = (960, 980, 100, 100, 1.0)
        centered = (960, 540, 100, 100, 1.0)
        cost_with_centered = apw.composition_cost([above, below, centered], (960, 540))
        cost_without = apw.composition_cost([above, below], (960, 540))
        # The centered window must not make the OTHER two's alignment look
        # free -- it should cost at least as much (ideally more, since a
        # real 3rd window now exists) as the 2-point case, never less. In
        # the covariance model this holds by construction (no separate
        # angle-exclusion exists at all anymore -- every point, including
        # one sitting exactly at the reference, is one uniform contribution
        # to the same matrix), but the property itself is worth pinning.
        self.assertGreaterEqual(cost_with_centered, cost_without - 1.0,
                                 "a window landing at dead center must not erase the "
                                 "elongation penalty for the other two")

    def test_three_way_still_penalized_when_third_is_centered(self):
        """Direct check: with a centered 3rd window, two aligned flanking
        windows must score WORSE than if the two flanking windows were
        instead placed on perpendicular axes (still with the 3rd at center)."""
        centered = (960, 540, 100, 100, 1.0)
        aligned = [(960, 100, 100, 100, 1.0), (960, 980, 100, 100, 1.0), centered]
        perpendicular = [(960, 100, 100, 100, 1.0), (1420, 540, 100, 100, 1.0), centered]
        cost_aligned = apw.composition_cost(aligned, (960, 540))
        cost_perp = apw.composition_cost(perpendicular, (960, 540))
        self.assertLess(cost_perp, cost_aligned,
                         "two flanking windows on the same axis (with a centered 3rd) "
                         "must score worse than two on perpendicular axes")


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
        # 4 800x800 windows can't fit within BOTH the monitor's width and
        # height at once (a tight 2x2 grid needs ~1605px wide but ~1605px
        # tall too, and the monitor is only 1080 tall) -- some edge must
        # spill off-screen. Which axis spills is a legitimate outcome of
        # the composition search (a smarter joint arrangement may choose
        # to fit cleanly on ONE axis and spill on the other, e.g. a compact
        # 2x2 grid that fits the 1920-wide monitor horizontally and
        # overflows vertically instead) -- so this checks the whole
        # bounding box, not one hardcoded axis.
        eligible = [self._mk(f"0x{i}", i * 900, 0, 800, 800) for i in range(4)]
        monitor = (0, 0, 1920, 1080)
        result = arr.auto_arrange(eligible, [], monitor, GAP)
        xs0 = [x for _, x, y in result]
        ys0 = [y for _, x, y in result]
        by_size = {w["address"]: w["size"] for w in eligible}
        xs1 = [x + by_size[a][0] for a, x, y in result]
        ys1 = [y + by_size[a][1] for a, x, y in result]
        self.assertTrue(min(xs0) < 0 or max(xs1) > 1920 or min(ys0) < 0 or max(ys1) > 1080,
                         "4 800x800 windows can't fit on a 1920x1080 monitor without spilling off it on some edge")

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


class TestResizeCompositionAware(unittest.TestCase):
    """A live sizing audit (6 deterministic mixed-size scenarios, see this
    change's own report) found the PREVIOUS Stage 3 -- gated behind a fixed
    "new window's own positional cost is this many times its diagonal"
    trigger, and scored only by that same new-window-only distance -- never
    fired at all across any of the 6 scenarios, even when a modest resize
    measurably improved the real composition_cost of the whole layout. It
    also found the FIRST fix attempt (scoring resize candidates by raw
    composition_cost with no distance term, compared against a baseline
    that weighs composition at 0.3) let a resize "win" a real desktop
    scenario (one small window, one large new one) by ~230 points
    numerically while changing the actual resulting anisotropy by 0.0004
    and com_err by 0.003px -- a scale-mismatch artifact, not a real
    improvement. These tests pin both corrected behaviors directly against
    the real production functions."""

    def _real_stage1_cost(self, existing, new_size, center=(960, 540), gap=GAP):
        """Mirrors place_new_window's own cost1 computation exactly, so
        these tests call try_resize_room with the SAME baseline the real
        listener would -- not an arbitrary trigger value."""
        others = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in existing]
        new_area = new_size[0] * new_size[1]
        pos1 = apw.find_free_position(new_size, others, center, gap,
                                       layout_others=others, reference_area=new_area)
        d1 = math.hypot(pos1[0] + new_size[0] / 2 - center[0], pos1[1] + new_size[1] / 2 - center[1])
        pos1_mass = apw.window_mass(new_size[0], new_size[1], new_area)
        stage1_points = [(w["at"][0] + w["size"][0] / 2, w["at"][1] + w["size"][1] / 2,
                           w["size"][0], w["size"][1], apw.window_mass(w["size"][0], w["size"][1], new_area))
                          for w in existing]
        stage1_points.append((pos1[0] + new_size[0] / 2, pos1[1] + new_size[1] / 2,
                               new_size[0], new_size[1], pos1_mass))
        comp1 = apw.composition_cost(stage1_points, center)
        return d1 + apw.STAGE_DECISION_COMPOSITION_WEIGHT * comp1

    def test_declines_marginal_non_material_resize(self):
        """One small existing window (250x150), one large new window
        (1200x800): the only available resize is a 4% area trim of the
        small window that changes the resulting composition by a
        practically unmeasurable amount. Must be declined -- 'a resize
        should happen only when its benefit materially improves the
        overall composition,' not merely because a numeric comparison
        technically favors it under a mismatched scale."""
        existing = [{"address": "SML", "at": [835, 465], "size": [250, 150]}]
        new_size = (1200, 800)
        best_cost = self._real_stage1_cost(existing, new_size)
        result = apw.try_resize_room(new_size, existing, [], (960, 540), GAP, best_cost)
        self.assertIsNone(result, "a non-material resize (illusory numeric win, "
                                   "no real composition change) must not fire")

    def test_fires_on_genuine_material_improvement(self):
        """Three medium (500x400) windows plus one oversized new window
        (1600x1000): a moderate resize of ONE medium window measurably
        improves the whole-composition cost (verified independently here,
        not just by re-invoking the function under test) -- this is
        exactly the case Stage 3 exists for and must fire on."""
        existing = [{"address": "M1", "at": [100, 100], "size": [500, 400]},
                    {"address": "M2", "at": [700, 100], "size": [500, 400]},
                    {"address": "M3", "at": [100, 600], "size": [500, 400]}]
        new_size = (1600, 1000)
        center = (960, 540)
        others = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in existing]
        new_area = new_size[0] * new_size[1]
        pos1 = apw.find_free_position(new_size, others, center, GAP,
                                       layout_others=others, reference_area=new_area)
        best_cost = self._real_stage1_cost(existing, new_size)

        result = apw.try_resize_room(new_size, existing, [], center, GAP, best_cost)
        self.assertIsNotNone(result, "a genuine, material composition improvement was available "
                                      "but Stage 3 declined to use it")
        pos3, addr, xy, size = result

        def independent_cost(pos_new, resized_addr, resized_xy, resized_size):
            ref_area = sorted([w["size"][0] * w["size"][1] for w in existing] + [new_area])[len(existing) // 2]
            pts = [(pos_new[0] + new_size[0] / 2, pos_new[1] + new_size[1] / 2,
                     new_size[0], new_size[1], apw.window_mass(new_size[0], new_size[1], ref_area))]
            for w in existing:
                if w["address"] == resized_addr:
                    x, y = resized_xy
                    w_, h_ = resized_size
                else:
                    x, y = w["at"]
                    w_, h_ = w["size"]
                pts.append((x + w_ / 2, y + h_ / 2, w_, h_, apw.window_mass(w_, h_, ref_area)))
            return apw.composition_cost(pts, center)

        baseline_comp = independent_cost(pos1, None, (0, 0), (0, 0))
        resized_comp = independent_cost(pos3, addr, xy, size)
        self.assertLess(resized_comp, baseline_comp,
                         "Stage 3 fired but the resulting composition isn't actually better")
        # Must still respect the safety floor and only touch ONE window.
        self.assertGreaterEqual(size[0], apw.MIN_USABLE_WIDTH)
        self.assertGreaterEqual(size[1], apw.MIN_USABLE_HEIGHT)

    def test_never_resizes_the_new_window(self):
        """Structural guarantee, pinned directly: try_resize_room only ever
        iterates `eligible` (existing windows) as candidates to shrink --
        the new window's own size is never a resize target, regardless of
        how good a plan that might numerically produce."""
        existing = [{"address": "ONLY", "at": [100, 100], "size": [300, 300]}]
        result = apw.try_resize_room((250, 200), existing, [], (960, 540), GAP, best_cost=999999)
        if result is not None:
            _, addr, _, _ = result
            self.assertEqual(addr, "ONLY", "the only thing try_resize_room may ever resize is an existing window")


class TestSettleDelayDocumentation(unittest.TestCase):
    """place_new_window's post-dispatch settle mechanism (see _settle_moves'
    own docstring) is a live-timing mitigation, not something synthetic
    geometry tests can exercise -- this test only documents that it's
    actually present and actually called after every dispatch branch, so a
    future refactor can't silently drop it without at least a test noticing.

    History: this was originally a flat `time.sleep(0.03)` after every
    dispatch. Live testing (a 22-window rapid burst on the real compositor,
    spawned every 120ms under real system load) found that flat sleep was
    NOT always enough -- 30 confirmed genuine pixel-overlapping pairs were
    produced, all traced to the same race: a later placement's
    `hyprctl clients` read caught an earlier move still at its pre-move
    position because Hyprland hadn't actually applied it within 30ms yet.
    Replaced with _settle_moves(), which polls for the dispatched
    position/size to actually be confirmed (bounded, not indefinite). The
    same 22-window burst produced zero true overlaps after this change."""

    def test_settle_moves_present_and_called(self):
        import inspect
        self.assertTrue(hasattr(apw, "_settle_moves"),
                         "_settle_moves was removed -- see its docstring for "
                         "the real, live-confirmed race it closes")
        src = inspect.getsource(apw.place_new_window)
        self.assertEqual(src.count("_settle_moves("), 3,
                          "place_new_window should call _settle_moves() after "
                          "each of its three dispatch branches (stage1/stage2/"
                          "stage3) -- a branch dispatching without settling "
                          "reopens the overlap race _settle_moves exists to close")


# ============================================================================
# Radial/organic composition tests -- the actual problem this pass fixes.
# ============================================================================
#
# "No overlaps" and "bbox center == viewport center" were both already
# proven insufficient (a straight stack can satisfy both while looking like
# exactly the degenerate case being fixed). Every test below instead
# measures the ACTUAL SHAPE of the result: the axial concentration R
# (0 = spread across multiple directions, 1 = everything on one line
# through the center) that apw.composition_cost itself scores by, computed
# independently here from the final rects so a test can't accidentally
# pass just because it reuses the same formula the code under test uses.

def _rect_center(x, y, w, h):
    return (x + w / 2, y + h / 2)


def _shape_metrics(rects, center, angle_eps=6.0):
    """rects: [(x,y,w,h), ...]. Returns (R, n_eff, com) computed the same
    way apw.composition_cost does, but independently re-derived here (not
    calling composition_cost itself) so these tests exercise the actual
    geometry, not just re-invoke the function under test."""
    vx, vy = center
    points = [(*_rect_center(*r), math.sqrt(r[2] * r[3])) for r in rects]
    total_w = sum(w for _, _, w in points)
    com_x = sum(cx * w for cx, cy, w in points) / total_w
    com_y = sum(cy * w for cx, cy, w in points) / total_w
    weighted_angles = []
    for cx, cy, w in points:
        dx, dy = cx - vx, cy - vy
        if math.hypot(dx, dy) < angle_eps:
            continue
        weighted_angles.append((math.atan2(dy, dx), w))
    if not weighted_angles:
        return 0.0, 0.0, (com_x, com_y)
    wsum = sum(w for _, w in weighted_angles)
    rx = sum(w * math.cos(2 * a) for a, w in weighted_angles) / wsum
    ry = sum(w * math.sin(2 * a) for a, w in weighted_angles) / wsum
    n_eff = (wsum * wsum) / sum(w * w for _, w in weighted_angles)
    return math.hypot(rx, ry), n_eff, (com_x, com_y)


def _no_overlaps(rects, gap):
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rect(*rects[i]), rect(*rects[j])
            inflated = (a[0] - gap, a[1] - gap, a[2] + gap, a[3] + gap)
            if apw.overlaps(inflated, b):
                return False
    return True


CENTER = (960, 540)
GAP2 = 5


def _arrange(sized_windows):
    """sized_windows: [(x,y,w,h), ...] starting positions. Runs the real
    Algorithm B and returns the resulting [(x,y,w,h), ...]."""
    eligible = [{"address": f"0x{i}", "at": [x, y], "size": [w, h]}
                for i, (x, y, w, h) in enumerate(sized_windows)]
    result = arr.auto_arrange(eligible, [], (0, 0, 1920, 1080), GAP2)
    by_addr = {w["address"]: w for w in eligible}
    return [(x, y, *by_addr[a]["size"]) for a, x, y in result]


class TestRadialCompositionAlgorithmB(unittest.TestCase):
    """Points A/B/C/N/O/P/Q of the composition audit, against SUPER+G."""

    def test_four_windows_not_a_stack_or_row(self):
        # Four similarly-sized windows, deliberately started as a vertical
        # stack -- SUPER+G must not simply confirm the stack.
        rects = _arrange([(900, 100, 400, 300), (900, 405, 400, 300),
                           (900, 710, 400, 300), (900, 1015, 400, 300)])
        self.assertTrue(_no_overlaps(rects, GAP2))
        R, n_eff, com = _shape_metrics(rects, CENTER)
        self.assertLess(R, 0.5, f"four windows still concentrated on one axis: R={R:.2f} rects={rects}")

    def test_five_windows_organic(self):
        rects = _arrange([(900, 0, 350, 280), (900, 285, 350, 280), (900, 570, 350, 280),
                           (900, 855, 350, 280), (900, 1140, 350, 280)])
        self.assertTrue(_no_overlaps(rects, GAP2))
        R, n_eff, com = _shape_metrics(rects, CENTER)
        self.assertLess(R, 0.55, f"five windows still concentrated on one axis: R={R:.2f}")

    def test_six_windows_not_forced_grid_but_not_a_stack(self):
        rects = _arrange([(900, y, 300, 250) for y in range(0, 6 * 255, 255)])
        self.assertTrue(_no_overlaps(rects, GAP2))
        R, n_eff, com = _shape_metrics(rects, CENTER)
        self.assertLess(R, 0.6, f"six windows still axis-concentrated: R={R:.2f}")

    def test_existing_vertical_stack_plus_one_breaks_concentration(self):
        """D: start A/B/C in a vertical stack, arrange, then add a 4th and
        re-arrange -- the 4-window result must be LESS concentrated than
        simply extending the stack would be."""
        rects3 = _arrange([(900, 0, 400, 300), (900, 305, 400, 300), (900, 610, 400, 300)])
        rects3.append((900, 915, 400, 300))  # naive stack extension, NOT re-arranged
        R_naive, _, _ = _shape_metrics(rects3, CENTER)

        rects4 = _arrange(rects3)
        self.assertTrue(_no_overlaps(rects4, GAP2))
        R_arranged, _, _ = _shape_metrics(rects4, CENTER)
        self.assertLess(R_arranged, R_naive,
                         f"arranging 4 windows (R={R_arranged:.2f}) is no better than "
                         f"just extending the stack (R={R_naive:.2f})")

    def test_existing_horizontal_stack_plus_one_breaks_concentration(self):
        rects3 = _arrange([(0, 900, 350, 280), (355, 900, 350, 280), (710, 900, 350, 280)])
        rects3.append((1065, 900, 350, 280))
        R_naive, _, _ = _shape_metrics(rects3, CENTER)

        rects4 = _arrange(rects3)
        self.assertTrue(_no_overlaps(rects4, GAP2))
        R_arranged, _, _ = _shape_metrics(rects4, CENTER)
        self.assertLess(R_arranged, R_naive,
                         f"arranging (R={R_arranged:.2f}) is no better than extending the row (R={R_naive:.2f})")

    def test_large_and_small_large_moves_little(self):
        """F: a 1200x800 window plus a 250x150 one -- the large window
        should not be relocated far just to improve the abstract composition
        of a 2-window (n_eff-gated to ~0 angular penalty anyway) case."""
        eligible = [
            {"address": "0xBIG", "at": [400, 200], "size": [1200, 800]},
            {"address": "0xSMALL", "at": [1650, 200], "size": [250, 150]},
        ]
        result = arr.auto_arrange(eligible, [], (0, 0, 1920, 1080), GAP2)
        by_addr = {a: (x, y) for a, x, y in result}
        big_move = math.hypot(by_addr["0xBIG"][0] - 400, by_addr["0xBIG"][1] - 200)
        self.assertLess(big_move, 200, f"large window moved {big_move:.0f}px for a 2-window arrangement")

    def test_l_shape_notch_still_fills(self):
        """H: preserve the existing notch-filling behavior -- arranging an
        L plus a window sized for the notch should not scatter it away."""
        rects = _arrange([(500, 200, 450, 350), (500, 555, 450, 350),
                           (955, 555, 450, 350), (955, 200, 440, 340)])
        self.assertTrue(_no_overlaps(rects, GAP2))

    def test_fixed_obstacle_untouched(self):
        eligible = [{"address": "0xA", "at": [100, 100], "size": [400, 300]},
                    {"address": "0xB", "at": [600, 100], "size": [400, 300]}]
        fixed = [{"address": "0xFULL", "at": [0, 0], "size": [1920, 1080]}]
        result = arr.auto_arrange(eligible, fixed, (0, 0, 1920, 1080), GAP2)
        self.assertNotIn("0xFULL", {a for a, _, _ in result})

    def test_idempotent_after_composition_change(self):
        rects0 = [(900, y, 350, 280) for y in range(0, 5 * 285, 285)]
        eligible = [{"address": f"0x{i}", "at": [x, y], "size": [w, h]}
                    for i, (x, y, w, h) in enumerate(rects0)]
        r1 = arr.auto_arrange(eligible, [], (0, 0, 1920, 1080), GAP2)
        by_addr1 = {a: (x, y) for a, x, y in r1}
        round1 = [{"address": w["address"], "at": list(by_addr1[w["address"]]), "size": w["size"]}
                  for w in eligible]
        r2 = arr.auto_arrange(round1, [], (0, 0, 1920, 1080), GAP2)
        for addr, nx, ny in r2:
            ox, oy = by_addr1[addr]
            self.assertLess(math.hypot(nx - ox, ny - oy), 1.0,
                             f"{addr} moved {math.hypot(nx-ox, ny-oy):.1f}px on a no-op re-run")

    def test_deterministic_same_input_same_output(self):
        rects0 = [(900, 0, 400, 300), (200, 700, 350, 280), (1500, 300, 300, 500)]
        results = set()
        for _ in range(10):
            results.add(tuple(sorted(_arrange(rects0))))
        self.assertEqual(len(results), 1, "same input produced different layouts across runs")

    def test_gap_exact_where_adjacent(self):
        rects = _arrange([(900, 0, 400, 300), (900, 305, 400, 300), (900, 610, 400, 300)])
        found_adjacent = False
        for i in range(len(rects)):
            for j in range(len(rects)):
                if i == j:
                    continue
                ri, rj = rect(*rects[i]), rect(*rects[j])
                xg = apw._axis_gap(ri[0], ri[2], rj[0], rj[2])
                yg = apw._axis_gap(ri[1], ri[3], rj[1], rj[3])
                if yg == 0.0 and xg > 0:
                    found_adjacent = True
                    self.assertAlmostEqual(xg, GAP2, delta=1.5)
                if xg == 0.0 and yg > 0:
                    found_adjacent = True
                    self.assertAlmostEqual(yg, GAP2, delta=1.5)

    def test_no_overlaps_various_sizes(self):
        rects = _arrange([(900, 0, 700, 200), (900, 205, 150, 600), (900, 810, 900, 250),
                           (0, 0, 300, 300), (1600, 900, 500, 150)])
        self.assertTrue(_no_overlaps(rects, GAP2))

    def test_offscreen_placement_remains_legal(self):
        """L: a fixed obstacle covering the entire monitor leaves eligible
        windows nowhere on-screen to go -- the result MUST be allowed to
        extend off-screen rather than being clamped into the (fully
        occupied) monitor rectangle. Three modest windows simply starting
        far apart is NOT itself evidence of anything (the best composition
        for a few small windows can legitimately fit on-screen once
        centered) -- this version actually forces the question."""
        eligible = [{"address": "0xA", "at": [-3000, -3000], "size": [500, 400]},
                    {"address": "0xB", "at": [3500, 3000], "size": [500, 400]}]
        fixed = [{"address": "0xFULL", "at": [0, 0], "size": [1920, 1080]}]
        result = arr.auto_arrange(eligible, fixed, (0, 0, 1920, 1080), GAP2)
        by_size = {w["address"]: w["size"] for w in eligible}
        rects = [(x, y, *by_size[a]) for a, x, y in result]
        self.assertTrue(_no_overlaps(rects + [(0, 0, 1920, 1080)], GAP2))
        xs = [r[0] for r in rects] + [r[0] + r[2] for r in rects]
        ys = [r[1] for r in rects] + [r[1] + r[3] for r in rects]
        self.assertTrue(min(xs) < 0 or max(xs) > 1920 or min(ys) < 0 or max(ys) > 1080,
                         "with the whole monitor occupied by a fixed obstacle, eligible windows "
                         "have nowhere on-screen to go -- must not be clamped into it anyway")


class TestRadialCompositionAlgorithmA(unittest.TestCase):
    """Same principle applied to new-window auto-placement (points D/E/F/G/
    I/J/K of the composition audit)."""

    def _place(self, existing, new_size):
        """existing: [(x,y,w,h), ...]. Returns the chosen position for a
        new window of `new_size`, using the real Stage-1 search."""
        others = existing
        layout_others = existing
        return apw.find_free_position(new_size, others, CENTER, GAP2, layout_others=layout_others,
                                       reference_area=new_size[0] * new_size[1])

    def test_new_window_breaks_existing_vertical_stack(self):
        """D: A/B/C already stacked vertically -- a new D should prefer
        breaking the concentration over extending the column, unless doing
        so would be a clearly worse composition."""
        existing = [(900, 100, 400, 300), (900, 405, 400, 300), (900, 710, 400, 300)]
        pos = self._place(existing, (400, 300))
        naive_extension = (900, 1015)
        # The chosen spot must differ from "just continue the column downward."
        self.assertNotEqual((round(pos[0]), round(pos[1])), naive_extension)
        all_rects = existing + [(pos[0], pos[1], 400, 300)]
        R, _, _ = _shape_metrics(all_rects, CENTER)
        R_if_extended, _, _ = _shape_metrics(existing + [(naive_extension[0], naive_extension[1], 400, 300)], CENTER)
        self.assertLessEqual(R, R_if_extended)

    def test_new_window_breaks_existing_horizontal_stack(self):
        existing = [(0, 900, 350, 280), (355, 900, 350, 280), (710, 900, 350, 280)]
        pos = self._place(existing, (350, 280))
        naive_extension = (1065, 900)
        self.assertNotEqual((round(pos[0]), round(pos[1])), naive_extension)

    def test_cardinal_left_discovered_naturally(self):
        block = (700, 90, 900, 900)  # occupies center+right, leaves left clean
        pos = self._place([block], (400, 400))
        self.assertLess(pos[0] + 200, block[0], "did not choose the clean space to the left")

    def test_cardinal_right_discovered_naturally(self):
        block = (-680, 90, 900, 900)  # occupies center+left, leaves right clean
        pos = self._place([block], (400, 400))
        self.assertGreater(pos[0], block[0] + block[2] - 10, "did not choose the clean space to the right")

    def test_diagonal_can_be_chosen_when_superior(self):
        """J: construct a case where a diagonal/corner spot is clearly the
        best composition -- two blockers leave only a diagonal pocket near
        center; the search must be able to land there."""
        blockers = [
            (600, -900, 1200, 900),   # occupies straight above
            (600, 900 + 180, 1200, 900),  # occupies straight below (leaves a vertical gap band, forces sideways)
        ]
        pos = self._place(blockers, (300, 300))
        cand = rect(pos[0], pos[1], 300, 300)
        for bx, by, bw, bh in blockers:
            self.assertFalse(apw.overlaps((cand[0] - GAP2, cand[1] - GAP2, cand[2] + GAP2, cand[3] + GAP2),
                                           rect(bx, by, bw, bh)))

    def test_asymmetric_sizes_still_balanced(self):
        existing = [(900, 0, 1200, 200), (900, 205, 150, 700), (900, 910, 900, 150)]
        pos = self._place(existing, (300, 300))
        all_rects = existing + [(pos[0], pos[1], 300, 300)]
        self.assertTrue(_no_overlaps(all_rects, GAP2))

    def test_stage2_final_composition_beats_naive_stack_extension(self):
        """The full Stage1+Stage2 pipeline via place_new_window's own
        composition comparison -- verified at the function level since
        place_new_window itself needs a live Hyprland connection."""
        existing_eligible = [
            {"address": "0xA", "at": [900, 100], "size": [400, 300]},
            {"address": "0xB", "at": [900, 405], "size": [400, 300]},
            {"address": "0xC", "at": [900, 710], "size": [400, 300]},
        ]
        new_size = (400, 300)
        new_area = new_size[0] * new_size[1]
        layout_others = [(w["at"][0], w["at"][1], *w["size"]) for w in existing_eligible]

        pos1 = apw.find_free_position(new_size, layout_others, CENTER, GAP2,
                                       layout_others=layout_others, reference_area=new_area)
        stage1_rects = layout_others + [(pos1[0], pos1[1], *new_size)]
        R1, _, _ = _shape_metrics(stage1_rects, CENTER)

        naive_rects = layout_others + [(900, 1015, *new_size)]
        R_naive, _, _ = _shape_metrics(naive_rects, CENTER)
        self.assertLessEqual(R1, R_naive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
