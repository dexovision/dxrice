#!/usr/bin/env python3
"""The Galaxy Spiral as it grows: new-window placement builds the spiral
from the first window, SUPER+G uses the same model, and transient surfaces
stay out of it. Everything runs against the in-memory Hyprland of
dxrice_test_auto_place_cloud.py (no compositor, nothing on screen).

    python3 scripts/dxrice_test_spiral_growth.py [-v]
"""
import contextlib
import io
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_auto_arrange as arr  # noqa: E402
import dxrice_auto_place_window as apw  # noqa: E402
import dxrice_spiral as sp  # noqa: E402
import dxrice_test_auto_place_cloud as cloud  # noqa: E402
from dxrice_test_placement import spacing_violations, assert_composed  # noqa: E402

GAP = 5
USABLE = (0, 52, 1920, 1012)          # a 1920x1080 screen minus a 52px bar and a 68px dock
MIXED = [(1500, 950), (860, 560), (1100, 750), (640, 400), (900, 620), (550, 300),
         (1300, 850), (820, 560), (480, 320), (700, 460)]


def _centre(r):
    return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)


class _Growth(cloud._Base):
    def setUp(self):
        super().setUp()
        apw.get_monitor_bounds = lambda: USABLE
        arr.get_monitor_bounds = lambda: USABLE

    def open_seq(self, sizes, prefix="0xw"):
        """Opens windows one at a time through the real place_new_window;
        asserts nothing already open moves. Returns their addresses."""
        out = []
        for i, (w, h) in enumerate(sizes):
            addr = f"{prefix}{len(self.hypr.clients):02d}"
            before = self.hypr.snapshot()
            self.hypr.open(addr, w, h, cls=f"app{addr}")
            self.assertEqual(apw.place_new_window(addr, 1, GAP), "placed")
            self.assertEqual(self.hypr.snapshot(but=addr), before, f"opening {addr} moved another window")
            out.append(addr)
        return out

    def rows(self, only=None):
        return [(a, *c["at"], *c["size"]) for a, c in self.hypr.clients.items() if only is None or a in only]

    def rect(self, addr):
        return cloud._rect(self.hypr.clients[addr])

    def press(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            arr.main()
        return buf.getvalue().strip()


class TestGrowsFromTheFirstWindow(_Growth):
    def test_1_one_window_is_the_anchor_at_the_usable_centre(self):
        (a,) = self.open_seq([(1100, 700)])
        self.assertEqual(_centre(self.rect(a)), (960, 532))

    def test_2_the_second_window_joins_the_first(self):
        a, b = self.open_seq([(1100, 700), (860, 560)])
        self.assertEqual(_centre(self.rect(a)), (960, 532), "the anchor moved")
        assert_composed(self, self.rows())

    def test_3_six_mixed_windows_grow_an_organic_spiral(self):
        addrs = self.open_seq(MIXED[:6])
        rows = self.rows()
        assert_composed(self, rows)
        rects = [self.rect(a) for a in addrs]
        self.assertEqual(sp.rigidity(rects), 0, f"rows/columns/grid: {rows}")
        self.assertEqual(_centre(rects[0]), _centre(USABLE), "the first window stopped being the anchor")
        # the arm turns clockwise round the anchor, every step
        hub = _centre(rects[0])
        ang = [math.atan2(_centre(r)[1] - hub[1], _centre(r)[0] - hub[0]) for r in rects[1:]]
        steps = [sp._wrap(b - a) for a, b in zip(ang, ang[1:])]
        self.assertTrue(all(s > 0 for s in steps), [round(math.degrees(s)) for s in steps])

    RING = [(900, 600)] + [(700, 450)] * 15

    def test_4_more_windows_continue_outward(self):
        """Sixteen windows round a moderate anchor: the arm turns clockwise
        all the way round the anchor, then carries on in a wider second
        turn. (Twelve did this with the old fixed 42 px gap; the expanding
        spiral holds more windows in its roomier first turn.)"""
        addrs = self.open_seq(self.RING)
        rects = [self.rect(a) for a in addrs]
        assert_composed(self, self.rows())
        self.assertEqual(_centre(rects[0]), _centre(USABLE))
        co = sp.spiral_coords(rects)
        steps = [b[0] - a[0] for a, b in zip(co, co[1:])]
        self.assertTrue(all(0 < s < math.pi for s in steps), [round(math.degrees(s)) for s in steps])
        self.assertGreater(co[-1][0], 2 * math.pi, "it never came all the way round")
        # a window a full turn on sits further out than the one it passes
        for (phi, rad) in co:
            inner = [r for p, r in co if 2 * math.pi - 0.5 < phi - p < 2 * math.pi + 0.5]
            for r in inner:
                self.assertGreater(rad, r, "the second turn isn't outside the first")

    def test_7_opening_never_moves_existing_windows(self):
        # open_seq asserts it on every open; a longer, mixed run here
        self.open_seq(MIXED + MIXED[:4])

    def test_8_closing_a_window_leaves_the_rest_and_its_hole_can_be_reused(self):
        """Closing moves nothing (nothing listens for it). Geometry model: a
        hole in the MIDDLE of the arm is not back-filled -- the next window
        continues the arm from its tip, exactly where it would have gone had
        nothing closed (the spiral step reads only the anchor, the tip and
        what it must clear), so the progression stays predictable."""
        addrs = self.open_seq(self.RING)
        layout = [self.rect(a) for a in addrs]
        gone = addrs[2]
        del self.hypr.clients[gone]
        before = self.hypr.snapshot()
        new = self.open_seq([(700, 450)], prefix="0xn")[0]
        self.assertEqual(self.hypr.snapshot(but=new), before)
        assert_composed(self, self.rows())
        want = sp.next_rect((700, 450), layout, [], sp.read_spacing())
        self.assertEqual(self.rect(new), want, "the arm didn't continue from its tip as if nothing had closed")

    def test_8c_closing_the_tip_lets_the_next_window_take_its_place(self):
        """The one hole that fits the progression: the newest window's own.
        Close it and the next window of that size goes back where it was."""
        addrs = self.open_seq(MIXED[:7])
        tip = self.rect(addrs[-1])
        del self.hypr.clients[addrs[-1]]
        new = self.open_seq([MIXED[6]], prefix="0xn")[0]
        self.assertEqual(self.rect(new), tip)

    def test_8d_closing_the_anchor_hands_it_to_the_earliest_survivor(self):
        """The anchor closed: nothing moves; the earliest-created survivor is
        the anchor from now on, and the arm carries on from the tip without
        touching anything."""
        # windows small enough that the survivors stay on screen (if none
        # did, the new window would rightly start a new anchor instead)
        addrs = self.open_seq([(600, 380), (420, 300), (500, 320), (380, 260), (460, 300), (520, 340)])
        del self.hypr.clients[addrs[0]]
        before = self.hypr.snapshot()
        new = self.open_seq([(700, 450)], prefix="0xn")[0]
        self.assertEqual(self.hypr.snapshot(but=new), before)
        layout = [self.rect(a) for a in addrs[1:]]
        self.assertEqual(self.rect(new), sp.next_rect((700, 450), layout, [], sp.read_spacing()))
        # Clear of everything, never under the minimum. Not asserted: that it
        # sits within reach of a neighbour -- the arm was wound round the
        # closed anchor, so continuing it round the survivor can land in open
        # space (REPORT_GEOMETRY.md, limitations); the next SUPER+G re-winds.
        self.assertEqual(spacing_violations(self.rows()), [])
        self.press()
        assert_composed(self, self.rows())

    def test_8b_a_gap_in_the_open_lets_the_arm_carry_on(self):
        """A window closed on the airy outside leaves no enclosed hole: the
        next window continues the arm from its tip -- beside the newest
        window -- and nothing moves."""
        addrs = self.open_seq(MIXED[:7])
        gone = addrs[2]
        del self.hypr.clients[gone]
        before = self.hypr.snapshot()
        tip = addrs[-1]
        new = self.open_seq([(700, 450)], prefix="0xn")[0]
        self.assertEqual(self.hypr.snapshot(but=new), before)
        assert_composed(self, self.rows())
        self.assertLessEqual(cloud._sep(self.rect(new), self.rect(tip)), sp.widest_gap(sp.read_spacing()) + 1,
                             "the arm didn't continue from its tip")

    def test_9_fullscreen_and_fixed_windows_are_never_overlapped(self):
        self.hypr.add("0xfs", 0, 0, 1920, 1080, fullscreen=2)
        self.hypr.add("0xpin", 1500, 100, 400, 300, pinned=True)
        addrs = self.open_seq(MIXED[:5])
        for a in addrs:
            for f in ("0xfs", "0xpin"):
                self.assertGreaterEqual(cloud._sep(self.rect(a), self.rect(f)), sp.SPACING_MIN_DEFAULT - 0.5, (a, f))


class TestSuperGSameModel(_Growth):
    def scatter(self, sizes):
        import random
        rng = random.Random(4)
        for i, (w, h) in enumerate(sizes):
            self.hypr.add(f"0xs{i}", rng.randint(-300, 1500), rng.randint(-200, 800), w, h)

    def test_5_scattered_windows_become_a_galaxy_spiral(self):
        self.scatter(MIXED[:8])
        out = self.press()
        self.assertIn("moved", out)
        rows = self.rows()
        assert_composed(self, rows)
        self.assertEqual(sp.rigidity([cloud._rect(c) for c in self.hypr.clients.values()]), 0)

    def test_6_repeated_presses_converge(self):
        self.scatter(MIXED[:8])
        self.press()
        first = self.hypr.snapshot()
        self.assertIn("0 moved, 0 resized", self.press())
        self.assertEqual(self.hypr.snapshot(), first)
        self.assertIn("0 moved, 0 resized", self.press())

    def test_super_g_on_an_auto_grown_spiral_needs_one_press_at_most(self):
        """One model: auto-placement grew exactly SUPER+G's spiral, so the
        very first press moves nothing."""
        self.open_seq(MIXED[:7])
        self.assertIn("0 moved, 0 resized", self.press())
        self.assertIn("0 moved, 0 resized", self.press())

    def test_opening_after_super_g_continues_super_gs_own_arm(self):
        """One model: after SUPER+G, a newly opened window lands exactly
        where SUPER+G's replay puts it -- so the next press moves nothing."""
        self.scatter(MIXED[:6])
        self.press()
        before = self.hypr.snapshot()
        new = self.open_seq([(600, 400)], prefix="0xn")[0]
        self.assertEqual(self.hypr.snapshot(but=new), before)
        assert_composed(self, self.rows())
        self.assertIn("0 moved, 0 resized", self.press())

    def test_super_g_after_a_close_rebuilds_only_what_came_after(self):
        """SUPER+G replays the spiral from creation order, so after a window
        closes, the windows created before it stay exactly where they are
        and those after it close up the arm -- the deliberate tidy-up of an
        explicit press (closing alone moves nothing: test_8)."""
        addrs = self.open_seq(MIXED[:8])
        del self.hypr.clients[addrs[3]]
        before = {a: self.rect(a) for a in addrs if a != addrs[3]}
        self.press()
        for a in addrs[:3]:
            self.assertEqual(self.rect(a), before[a], f"{a}, created before the closed window, moved")
        assert_composed(self, self.rows())
        self.assertIn("0 moved, 0 resized", self.press())

    def test_10_an_oversized_composition_keeps_its_anchor_on_screen(self):
        """The live test's case: six 826x493 terminals cover more than the
        screen; centring the whole group cut the anchor off at the top."""
        for i in range(6):
            self.hypr.add(f"0xt{i}", 100 + 140 * i, 80 + 60 * i, 826, 493)
        self.press()
        anchor = cloud._rect(self.hypr.clients["0xt0"])  # the first created
        self.assertLessEqual(math.dist(_centre(anchor), _centre(USABLE)), 0.75)
        m = sp.ANCHOR_MARGIN
        self.assertTrue(USABLE[0] + m <= anchor[0] and anchor[2] <= USABLE[2] - m
                        and USABLE[1] + m <= anchor[1] and anchor[3] <= USABLE[3] - m,
                        f"anchor {anchor} not comfortably inside {USABLE}")
        self.assertIn("0 moved, 0 resized", self.press())

    def test_13_no_overlap_no_repeated_shrink_spacing_kept(self):
        self.scatter([(1900, 1100), (700, 500), (650, 450), (600, 420), (560, 380), (500, 340)])
        sizes = []
        for _ in range(3):
            self.press()
            sizes.append({a: tuple(c["size"]) for a, c in self.hypr.clients.items()})
        self.assertEqual(sizes[1], sizes[0])
        self.assertEqual(sizes[2], sizes[0])
        self.assertEqual(spacing_violations(self.rows()), [])


class TestGeometryModel(unittest.TestCase):
    """dxrice_spiral's deterministic model on its own: the properties the
    visual reference asks for, over random mixed window sets."""

    BAND = (sp.SPACING_MIN_DEFAULT, sp.SPACING_MAX_DEFAULT)

    def sets(self, n=200, seed=11, lo=(250, 150), hi=(1700, 1000), obstacles=True, count=(2, 16)):
        import random
        rng = random.Random(seed)
        for k in range(n):
            sizes = [(rng.randint(lo[0], hi[0]), rng.randint(lo[1], hi[1])) for _ in range(rng.randint(*count))]
            obs = []
            if obstacles and k % 3 == 0:
                obs = [(rng.randint(-200, 1800), rng.randint(0, 900), rng.randint(200, 600), rng.randint(150, 500))]
            yield sizes, obs

    def test_replay_equals_incremental_growth(self):
        """SUPER+G (arrange) and new-window placement (join, one window at a
        time) produce bit-identical layouts, with and without obstacles."""
        for sizes, obs in self.sets():
            fixed = [sp._rect(*o) for o in obs]
            replay = sp.arrange(sizes, fixed, USABLE, self.BAND)
            layout = []
            for w, h in sizes:
                x, y = sp.join((w, h), layout, obs + layout, USABLE, self.BAND)
                layout.append((x, y, w, h))
            self.assertEqual([sp._rect(*r) for r in layout], replay, (sizes, obs))

    def test_spacing_is_a_hard_constraint(self):
        """Never under the minimum -- as the true distance between
        rectangles, corner to corner for diagonal pairs -- from windows or
        fixed windows; every window at least the inner turn's gap from all
        that came before it, and (with nothing in the way) no further than
        the spiral's widest gap from its nearest neighbour."""
        g0, widest = sp.target_gap(self.BAND), sp.widest_gap(self.BAND)
        for sizes, obs in self.sets():
            fixed = [sp._rect(*o) for o in obs]
            rects = sp.arrange(sizes, fixed, USABLE, self.BAND)
            for i, r in enumerate(rects):
                for o in rects[:i] + fixed:
                    self.assertGreaterEqual(sp.dist(r, o), sp.SPACING_MIN_DEFAULT, (sizes, obs))
                if i:
                    self.assertGreaterEqual(min(sp.dist(r, o) for o in rects[:i] + fixed), g0 - 1, (i, sizes, obs))
                    if not fixed:
                        self.assertLessEqual(min(sp.dist(r, o) for o in rects[:i]), widest + 1, (i, sizes, obs))

    def test_starts_upper_right_and_turns_clockwise(self):
        for sizes, _ in self.sets(n=60, obstacles=False):
            rects = sp.arrange(sizes, [], USABLE, self.BAND)
            hub = _centre(rects[0])
            self.assertLessEqual(math.dist(hub, _centre(USABLE)), 0.75)  # half a pixel each way
            b2 = math.degrees(math.atan2(_centre(rects[1])[1] - hub[1], _centre(rects[1])[0] - hub[0]))
            self.assertTrue(-90 < b2 < 0, f"window 2 isn't upper right of the anchor: {b2:.0f}")

    def test_bounded_advance_and_outward_growth(self):
        """Realistic sizes: every window advances clockwise along the spiral
        -- never back -- by a bounded step: 99% by at most 100 degrees, none
        by more than half a turn. Its radius on the spiral (its own frame,
        spiral_coords) never shrinks. (Not its edge distance from the
        anchor: a bigger window's edges come closer at the same radius.)"""
        steps = []
        for sizes, obs in self.sets(lo=(400, 260), hi=(1300, 900)):
            rects = sp.arrange(sizes, [sp._rect(*o) for o in obs], USABLE, self.BAND)
            co = sp.spiral_coords(rects)
            for (p0, r0), (p1, r1) in zip(co, co[1:]):
                step = math.degrees(p1 - p0)
                self.assertTrue(0 < step <= 180, (step, sizes, obs))
                self.assertGreaterEqual(r1, r0 - 0.75, (sizes, obs))
                steps.append(step)
        steps.sort()
        self.assertLessEqual(steps[int(0.99 * len(steps))], 100, "the arm skips round too often")

    def test_it_is_an_archimedean_spiral(self):
        """The radius grows in step with the angle: a straight line through
        (cumulative angle, radius) fits every set closely -- a ring (flat
        radius) or windows appended at random radii would not."""
        import statistics as st
        fits = []
        for sizes, _ in self.sets(n=150, lo=(220, 110), hi=(1300, 900), obstacles=False):
            co = sp.spiral_coords(sp.arrange(sizes, [], USABLE, self.BAND))
            if len(co) < 6:
                continue
            ph, rad = zip(*co)
            mp, mr = st.mean(ph), st.mean(rad)
            slope = sum((p - mp) * (r - mr) for p, r in zip(ph, rad)) / sum((p - mp) ** 2 for p in ph)
            self.assertGreater(slope, 0, "the radius doesn't grow with the angle")
            res = sum((r - mr - slope * (p - mp)) ** 2 for p, r in zip(ph, rad))
            fits.append(1 - res / sum((r - mr) ** 2 for r in rad))
        fits.sort()
        self.assertGreater(fits[len(fits) // 2], 0.99)
        self.assertGreater(fits[len(fits) // 10], 0.97)

    def test_gaps_widen_turn_by_turn(self):
        """The gap each window keeps from those before it widens gently with
        the spiral: about 42-50 px on the inner turn, 50-59 on the middle
        one, 59-67 further out (theme default), the medians in order. (Was
        42-56 / 56-80 / 80+ until the user asked for a gentler outward
        growth with the inner gaps kept.)"""
        import statistics as st
        per_turn = {0: [], 1: [], 2: []}
        for sizes, _ in self.sets(n=120, lo=(240, 120), hi=(300, 160), obstacles=False, count=(20, 40)):
            rects = sp.arrange(sizes, [], USABLE, self.BAND)
            for i, (phi, _r) in enumerate(sp.spiral_coords(rects), 1):
                turn = int(phi / (2 * math.pi))
                if turn in per_turn:
                    per_turn[turn].append(min(sp.dist(rects[i], o) for o in rects[:i]))
        med = {t: st.median(v) for t, v in per_turn.items()}
        self.assertTrue(44 <= med[0] <= 52, med)
        self.assertTrue(52 <= med[1] <= 60, med)
        self.assertTrue(57 <= med[2] <= 66, med)
        self.assertTrue(med[0] < med[1] < med[2], med)

    def test_gap_progression_is_smooth(self):
        """Unobstructed, a window's gap never comes in narrower than the one
        before it by more than a few px (mixed sizes shift the typical
        window a little) -- no erratic alternation."""
        for sizes, _ in self.sets(n=150, lo=(220, 110), hi=(1300, 900), obstacles=False):
            rects = sp.arrange(sizes, [], USABLE, self.BAND)
            near = [min(sp.dist(r, o) for o in rects[:i]) for i, r in enumerate(rects) if i >= 2]
            for a, b in zip(near, near[1:]):
                self.assertGreaterEqual(b, a - 8, (sizes, near))

    def test_the_same_distance_rule_in_every_direction(self):
        """Neighbours side by side, stacked or diagonal keep the same gap: the
        median nearest gap of windows at axis bearings and at diagonal ones
        is within a few px -- no axis-aligned shortcut."""
        import statistics as st
        axis, diag = [], []
        for sizes, _ in self.sets(n=150, lo=(240, 120), hi=(700, 450), obstacles=False):
            rects = sp.arrange(sizes, [], USABLE, self.BAND)
            hub = _centre(rects[0])
            for i, r in enumerate(rects[1:], 1):
                b = math.degrees(math.atan2(_centre(r)[1] - hub[1], _centre(r)[0] - hub[0])) % 90
                (axis if b < 15 or b > 75 else diag).append(min(sp.dist(r, o) for o in rects[:i]))
        self.assertLessEqual(abs(st.median(axis) - st.median(diag)), 4, (st.median(axis), st.median(diag)))

    def test_past_the_march_cap_the_gap_is_still_kept(self):
        """If the march ever runs out (MARCH_MAX: eight turns, which only an
        obstacle far bigger than a screen could cause), the window steps
        straight outward until clear -- the gap is kept even there. Forced
        here by shrinking the cap to 3 degrees with an obstacle across the
        start of the curve."""
        saved = sp.MARCH_MAX
        sp.MARCH_MAX = math.radians(3)
        self.addCleanup(setattr, sp, "MARCH_MAX", saved)
        anchor = sp.first_rect((800, 500), [], USABLE, self.BAND)
        block = sp._rect(anchor[2] - 100, anchor[1] - 700, 900, 640)  # upper right, where window 2 starts
        plain = sp.next_rect((700, 450), [anchor], [], self.BAND)
        self.assertLess(sp.dist(plain, block), sp.target_gap(self.BAND), "the obstacle must block the start")
        r = sp.next_rect((700, 450), [anchor], [block], self.BAND)
        self.assertGreaterEqual(sp.dist(r, block), sp.target_gap(self.BAND) - 1)
        self.assertGreaterEqual(sp.dist(r, anchor), sp.target_gap(self.BAND) - 1)

    def test_obstacles_are_gone_round_along_the_spiral(self):
        """A fixed window in the way: the arm advances along the same spiral
        round it -- radius still never shrinking, the detour bounded (under
        a full turn) -- and nothing comes closer to it than the gap."""
        g0 = sp.target_gap(self.BAND)
        for sizes, obs in self.sets(n=150):
            if not obs:
                continue
            fixed = [sp._rect(*o) for o in obs]
            rects = sp.arrange(sizes, fixed, USABLE, self.BAND)
            co = sp.spiral_coords(rects)
            for (p0, r0), (p1, r1) in zip(co, co[1:]):
                self.assertTrue(0 < p1 - p0 < 2 * math.pi, (sizes, obs))
                self.assertGreaterEqual(r1, r0 - 0.75, (sizes, obs))
            for r in rects:
                self.assertGreaterEqual(sp.dist(r, fixed[0]), g0 - 1, (sizes, obs))


class TestTransientsStayOutOfTheSpiral(_Growth):
    def test_11a_tooltip_is_neither_placed_nor_arranged(self):
        self.open_seq(MIXED[:3])
        self.hypr.add("0xtip", 700, 300, 260, 40, xwayland=True)
        self.X11 = [cloud._x11((700, 300, 260, 40), override_redirect=True)]
        before = self.hypr.snapshot()
        self.assertEqual(apw.place_new_window("0xtip", 1, GAP), "ignored")
        self.assertEqual(self.hypr.snapshot(), before)
        self.press()
        self.assertEqual(tuple(self.hypr.clients["0xtip"]["at"]), (700, 300), "SUPER+G moved a tooltip")

    def test_11b_menu_and_link_preview_are_left_alone(self):
        self.open_seq(MIXED[:3])
        self.hypr.add("0xmenu", 900, 400, 300, 420, xwayland=True)
        self.hypr.add("0xcard", 400, 200, 360, 220, xwayland=True)
        self.X11 = [cloud._x11((900, 400, 300, 420), types=["_NET_WM_WINDOW_TYPE_POPUP_MENU"]),
                    cloud._x11((400, 200, 360, 220), override_redirect=True)]
        before = self.hypr.snapshot()
        for a in ("0xmenu", "0xcard"):
            self.assertEqual(apw.place_new_window(a, 1, GAP), "ignored")
        self.assertEqual(self.hypr.snapshot(), before)

    def test_11c_unknown_small_xwayland_surface_is_left_alone_by_both(self):
        """X server unreachable: a small XWayland surface is treated as a
        popup by new-window placement AND by SUPER+G -- one rule
        (dxrice_window_class.settle_unknown); SUPER+G used to arrange it."""
        self.open_seq(MIXED[:3])
        self.X11 = None
        self.hypr.add("0xpop", 1700, 900, 300, 180, xwayland=True)
        self.assertEqual(apw.place_new_window("0xpop", 1, GAP), "ignored")
        self.press()
        self.assertEqual(tuple(self.hypr.clients["0xpop"]["at"]), (1700, 900))

    def test_11d_attached_dialog_moves_with_its_parent_not_as_a_member(self):
        """A dialog with WM_TRANSIENT_FOR is part of its parent: SUPER+G moves
        it by its parent's own move instead of laying it out."""
        self.hypr.add("0xparent", 2000, 1500, 1200, 800, xwayland=True)
        self.hypr.add("0xother", -900, -700, 900, 600)
        self.hypr.add("0xdlg", 2300, 1700, 500, 300, xwayland=True)
        self.X11 = [cloud._x11((2000, 1500, 1200, 800)),
                    cloud._x11((2300, 1700, 500, 300), types=["_NET_WM_WINDOW_TYPE_DIALOG"],
                               transient_for=(2000, 1500, 1200, 800))]
        out = self.press()
        p, d = self.hypr.clients["0xparent"]["at"], self.hypr.clients["0xdlg"]["at"]
        self.assertNotEqual(p, [2000, 1500], "the parent wasn't arranged")
        self.assertEqual((d[0] - p[0], d[1] - p[1]), (300, 200), "the dialog came loose from its parent")
        self.assertIn("Arranged 2 window(s)", out)

    def test_11e_a_small_real_application_window_is_still_placed(self):
        """Small is not transient: a native Wayland 320x260 calculator joins
        the composition like any other window."""
        self.open_seq(MIXED[:3])
        self.hypr.open("0xcalc", 320, 260)
        self.assertEqual(apw.place_new_window("0xcalc", 1, GAP), "placed")
        assert_composed(self, self.rows())


class TestUsableArea(unittest.TestCase):
    def test_reserved_space_scale_and_rotation(self):
        m = {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1, "transform": 0, "reserved": [0, 52, 0, 68]}
        self.assertEqual(apw.usable_bounds(m), (0, 52, 1920, 1012))
        m = {"x": 1920, "y": 0, "width": 2560, "height": 1440, "scale": 1.25, "transform": 0, "reserved": [0, 40, 0, 0]}
        self.assertEqual(apw.usable_bounds(m), (1920, 40, 1920 + 2048, 1152))
        m = {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1, "transform": 1, "reserved": [0, 0, 0, 0]}
        self.assertEqual(apw.usable_bounds(m), (0, 0, 1080, 1920))
        m = {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1, "reserved": [2000, 0, 0, 0]}
        self.assertEqual(apw.usable_bounds(m), (0, 0, 1920, 1080), "nonsense reservation must not invert the area")


if __name__ == "__main__":
    unittest.main()
