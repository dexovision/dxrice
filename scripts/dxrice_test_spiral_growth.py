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
        self.assertEqual(sp.anchor_index(rects, _centre(USABLE)), 0, "the first window stopped being the anchor")
        # the sweep turns one way round the anchor
        hub = _centre(rects[0])
        ang = [math.atan2(_centre(r)[1] - hub[1], _centre(r)[0] - hub[0]) for r in rects[1:]]
        steps = [sp._wrap(b - a) for a, b in zip(ang, ang[1:])]
        self.assertGreaterEqual(max(sum(s > 0 for s in steps), sum(s < 0 for s in steps)), len(steps) - 1, steps)

    RING = [(900, 600)] + [(700, 450)] * 11

    def test_4_more_windows_continue_outward(self):
        """Twelve windows round a moderate anchor: the arm turns one way all
        the way round the anchor, then carries on in a wider second turn."""
        addrs = self.open_seq(self.RING)
        rects = [self.rect(a) for a in addrs]
        assert_composed(self, self.rows())
        self.assertEqual(sp.anchor_index(rects, _centre(USABLE)), 0)
        hub = _centre(rects[0])
        ang = [math.atan2(_centre(r)[1] - hub[1], _centre(r)[0] - hub[0]) for r in rects[1:]]
        steps = [sp._wrap(b - a) for a, b in zip(ang, ang[1:])]
        same = max(sum(s > 0 for s in steps), sum(s < 0 for s in steps))
        self.assertGreaterEqual(same, len(steps) - 1, f"the sweep reversed: {[round(math.degrees(a)) for a in ang]}")
        self.assertGreater(abs(sum(steps)), 2 * math.pi, "it never came all the way round")
        rad = [math.hypot(_centre(r)[0] - hub[0], _centre(r)[1] - hub[1]) for r in rects[1:]]
        self.assertGreater(sum(rad[-3:]) / 3, max(rad[:6]), f"the second turn isn't further out: {rad}")

    def test_7_opening_never_moves_existing_windows(self):
        # open_seq asserts it on every open; a longer, mixed run here
        self.open_seq(MIXED + MIXED[:4])

    def test_8_closing_a_window_leaves_the_rest_and_its_hole_can_be_reused(self):
        """Closing moves nothing (nothing listens for it). A window closed
        inside the ring leaves an enclosed hole, and the next window of
        that size takes it rather than extending the arm."""
        addrs = self.open_seq(self.RING)
        gone = addrs[2]
        hole = self.rect(gone)
        del self.hypr.clients[gone]
        before = self.hypr.snapshot()
        new = self.open_seq([(700, 450)], prefix="0xn")[0]
        self.assertEqual(self.hypr.snapshot(but=new), before)
        assert_composed(self, self.rows())
        self.assertLess(math.hypot(*(a - b for a, b in zip(_centre(self.rect(new)), _centre(hole)))), 150,
                        "the enclosed hole wasn't reused")

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
        self.assertLessEqual(cloud._sep(self.rect(new), self.rect(tip)), sp.SPACING_MAX_DEFAULT + 1,
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
        self.open_seq(MIXED[:7])
        self.press()
        self.assertIn("0 moved, 0 resized", self.press())

    def test_10_an_oversized_composition_keeps_its_anchor_on_screen(self):
        """The live test's case: six 826x493 terminals cover more than the
        screen; centring the whole group cut the anchor off at the top."""
        for i in range(6):
            self.hypr.add(f"0xt{i}", 100 + 140 * i, 80 + 60 * i, 826, 493)
        self.press()
        rects = [cloud._rect(c) for c in self.hypr.clients.values()]
        anchor = rects[sp.anchor_index(rects, _centre(USABLE))]
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
