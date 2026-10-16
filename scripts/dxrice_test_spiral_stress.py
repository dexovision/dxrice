#!/usr/bin/env python3
"""Randomised stress test of the Galaxy Spiral: many seeded sequences of
windows opening (ordinary, very wide, very tall, larger than the screen),
closing, pinned and fullscreen windows appearing, and SUPER+G presses,
through the real placement and the real SUPER+G entry point against the
in-memory Hyprland of dxrice_test_auto_place_cloud.py.

Invariants checked after every step:
  - opening a window never moves or resizes another one;
  - a placed window overlaps no other window except a fullscreen one;
  - SUPER+G never resizes anything, never moves a pinned or fullscreen
    window, and leaves no two arranged windows overlapping;
  - a second SUPER+G press moves nothing.

  python3 scripts/dxrice_test_spiral_stress.py [SEEDS]
"""
import contextlib
import io
import os
import random
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_auto_arrange as arr  # noqa: E402
import dxrice_auto_place_window as apw  # noqa: E402
import dxrice_test_auto_place_cloud as cloud  # noqa: E402

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 40
SIZES = [(1100, 700), (860, 560), (640, 400), (900, 620), (550, 300), (480, 320), (1300, 850),
         (2400, 260),    # very wide
         (300, 1600),    # very tall
         (2200, 1300),   # larger than the screen
         (160, 120)]     # tiny


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class SpiralStress(cloud._Base):
    def press(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            arr.main()
        return buf.getvalue()

    def check_no_overlap(self, what, among):
        rects = {a: cloud._rect(self.hypr.clients[a]) for a in among}
        names = sorted(rects)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                self.assertFalse(overlap(rects[a], rects[b]), f"{what}: {a} {rects[a]} overlaps {b} {rects[b]}")

    def run_seed(self, seed):
        rng = random.Random(seed)
        h = self.hypr
        n = 0
        for step in range(28):
            op = rng.random()
            live = [a for a, c in h.clients.items() if not c["pinned"] and not c["fullscreen"]]
            if op < 0.55 or not live:
                n += 1
                addr = f"0xs{seed}w{n}"
                w, ht = rng.choice(SIZES)
                before = h.snapshot()
                h.open(addr, w, ht, cls=f"app{n}")
                res = apw.place_new_window(addr, 1, cloud.GAP)
                self.assertEqual(res, "placed", (seed, step, addr))
                self.assertEqual(h.snapshot(but=addr), before, f"seed {seed} step {step}: opening {addr} moved another window")
                others = [a for a, c in h.clients.items() if a != addr and not c["fullscreen"]]
                for o in others:
                    self.assertFalse(overlap(cloud._rect(h.clients[addr]), cloud._rect(h.clients[o])),
                                     f"seed {seed} step {step}: {addr} placed over {o}")
            elif op < 0.72:
                del h.clients[rng.choice(live)]
            elif op < 0.78 and not any(c["pinned"] for c in h.clients.values()):
                n += 1
                h.add(f"0xs{seed}pin{n}", 1500, 70, 380, 220, pinned=True)
            elif op < 0.82 and not any(c["fullscreen"] for c in h.clients.values()):
                n += 1
                h.add(f"0xs{seed}fs{n}", 0, 0, 1920, 1080, fullscreen=2)
            else:
                fixed = {a: (tuple(c["at"]), tuple(c["size"])) for a, c in h.clients.items()
                         if c["pinned"] or c["fullscreen"]}
                sizes = {a: tuple(c["size"]) for a, c in h.clients.items()}
                self.press()
                self.assertEqual({a: tuple(c["size"]) for a, c in h.clients.items()}, sizes,
                                 f"seed {seed} step {step}: SUPER+G resized a window")
                self.assertEqual({a: (tuple(h.clients[a]["at"]), tuple(h.clients[a]["size"])) for a in fixed}, fixed,
                                 f"seed {seed} step {step}: SUPER+G moved a pinned or fullscreen window")
                arranged = [a for a, c in h.clients.items() if not c["pinned"] and not c["fullscreen"]]
                self.check_no_overlap(f"seed {seed} step {step} after SUPER+G", arranged)
                h.dispatched.clear()
                out = self.press()
                moves = [d for d in h.dispatched if "window.move(" in d]
                self.assertEqual(moves, [], f"seed {seed} step {step}: a second SUPER+G moved windows ({out.strip()})")

    def test_seeds(self):
        failures = []
        for seed in range(SEEDS):
            self.hypr.clients.clear()
            with self.subTest(seed=seed):
                self.run_seed(seed)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
