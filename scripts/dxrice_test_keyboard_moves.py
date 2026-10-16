#!/usr/bin/env python3
"""SUPER+arrows (dxrice_navigate_windows.py) and SUPER+SHIFT+arrows
(dxrice_move_window.py) against a fake Hyprland.

  - the infinite desktop's camera centres the target in the usable area of a
    scaled monitor, in layout coordinates, not at the mode-pixel centre;
  - pinned and fullscreen windows are never panned;
  - moving a window stops at the real (logical) screen edge, then pushes the
    others.

  python3 scripts/dxrice_test_keyboard_moves.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_move_window as mv  # noqa: E402
import dxrice_navigate_windows as nav  # noqa: E402

# 2880x1620 at scale 1.5 = 1920x1080 in the layout; a 52 px bar on top and a
# 68 px dock below, so the usable area's centre is (960, 532).
SCALED = {"id": 0, "x": 0, "y": 0, "width": 2880, "height": 1620, "scale": 1.5, "transform": 0,
          "focused": True, "reserved": [0, 52, 0, 68]}


def win(addr, x, y, w=400, h=300, **extra):
    return {"address": addr, "at": [x, y], "size": [w, h], "floating": True, "workspace": {"id": 1},
            "class": "app", "monitor": 0, **extra}


class Fake:
    def __init__(self, clients, active):
        self.clients, self.active = clients, active
        self.moves = {}
        self.focused = []

    def hyprctl_json(self, args, **kw):
        return {"activeworkspace": {"id": 1}, "clients": self.clients, "monitors": [SCALED],
                "activewindow": self.active}.get(args[0])

    def record(self, exprs):
        for e in exprs:
            m = re.search(r'address:([^"]+)", x = (-?\d+), y = (-?\d+)', e)
            self.moves[m.group(1)] = (int(m.group(2)), int(m.group(3)))

    def install(self, module):
        module.hyprctl_json = self.hyprctl_json
        module.batch_async = self.record
        if hasattr(module, "dispatch"):
            module.dispatch = lambda e, **kw: self.record([e])
        if hasattr(module, "focus_window"):
            module.focus_window = self.focused.append
            module.move_focus = lambda d: None


def run(module, *argv):
    saved = sys.argv
    sys.argv = ["x", *argv]
    try:
        module.main()
    finally:
        sys.argv = saved


class Navigate(unittest.TestCase):
    def test_centres_in_the_usable_area_of_a_scaled_monitor(self):
        a, b = win("0xa", 760, 382), win("0xb", 1500, 382)
        fake = Fake([a, b], active=a)
        fake.install(nav)
        run(nav, "right")
        x, y = fake.moves["0xb"]
        self.assertEqual((x + 200, y + 150), (960, 532))
        self.assertEqual(fake.focused, ["0xb"])

    def test_pinned_and_fullscreen_windows_are_not_panned(self):
        a, b = win("0xa", 760, 382), win("0xb", 1500, 382)
        pip = win("0xpip", 1400, 700, pinned=True)
        game = win("0xfs", 0, 0, 1920, 1080, fullscreen=2)
        fake = Fake([a, b, pip, game], active=a)
        fake.install(nav)
        run(nav, "right")
        self.assertEqual(set(fake.moves), {"0xa", "0xb"})


class MoveWindow(unittest.TestCase):
    def test_stops_at_the_logical_edge_then_pushes_the_others(self):
        # 40 px from the logical right edge (1920), which in mode pixels
        # would have been 1000 px away
        a = win("0xa", 1920 - 400 - 40, 300)
        b = win("0xb", 200, 300)
        pip = win("0xpip", 100, 100, pinned=True)
        fake = Fake([a, b, pip], active=a)
        fake.install(mv)
        run(mv, "right")
        self.assertEqual(fake.moves["0xa"], (1920 - 400, 300))
        self.assertEqual(fake.moves["0xb"], (200 - 90, 300))
        self.assertNotIn("0xpip", fake.moves)

    def test_away_from_edges_it_just_moves(self):
        a = win("0xa", 700, 400)
        fake = Fake([a], active=a)
        fake.install(mv)
        run(mv, "up")
        self.assertEqual(fake.moves, {"0xa": (700, 310)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
