#!/usr/bin/env python3
"""SUPER+D (dxrice_floating_tile_toggle.py): tiling a floating workspace and
toggling back puts every window exactly where it was, at its size.

The fake Hyprland resizes a floating window around its centre, as Hyprland
does, so a restore that moves before it resizes lands off by half the size
change.

  python3 scripts/dxrice_test_floating_toggle.py
"""
import os
import re
import sys
import tempfile
import unittest

_tmp = tempfile.TemporaryDirectory()
os.environ["XDG_RUNTIME_DIR"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_floating_tile_toggle as ft  # noqa: E402


class FakeHyprland:
    def __init__(self, rects):
        self.clients = {a: {"address": a, "at": [x, y], "size": [w, h], "floating": True,
                            "workspace": {"id": 1}, "class": a} for a, (x, y, w, h) in rects.items()}

    def hyprctl_json(self, args, **kw):
        if args[0] == "activeworkspace":
            return {"id": 1}
        if args[0] == "clients":
            return [{**c, "at": list(c["at"]), "size": list(c["size"])} for c in self.clients.values()]
        return None

    def batch(self, exprs, timeout=5):
        for e in exprs:
            addr = re.search(r'address:([^"]+)"', e).group(1)
            c = self.clients[addr]
            if "window.float(" in e:
                c["floating"] = not c["floating"]
                # tiling puts it in a grid cell; floating again keeps that
                # cell's geometry until something moves it
                c["at"], c["size"] = [10, 10], [940, 1040]
            else:
                x, y = (int(v) for v in re.search(r"x = (-?\d+), y = (-?\d+)", e).groups())
                if "window.move(" in e:
                    c["at"] = [x, y]
                else:  # centre-anchored resize
                    cx, cy = c["at"][0] + c["size"][0] / 2, c["at"][1] + c["size"][1] / 2
                    c["size"] = [x, y]
                    c["at"] = [round(cx - x / 2), round(cy - y / 2)]
        return b""


class TestToggleRoundTrip(unittest.TestCase):
    def test_restoring_puts_every_window_back_exactly(self):
        rects = {"0xa": (100, 120, 800, 500), "0xb": (1000, 300, 600, 700)}
        hypr = FakeHyprland(rects)
        ft.hyprctl_json, ft.batch = hypr.hyprctl_json, hypr.batch
        ft.main()                      # tile
        self.assertFalse(any(c["floating"] for c in hypr.clients.values()))
        ft.main()                      # and back
        for addr, (x, y, w, h) in rects.items():
            c = hypr.clients[addr]
            self.assertTrue(c["floating"])
            self.assertEqual((tuple(c["at"]), tuple(c["size"])), ((x, y), (w, h)), addr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
