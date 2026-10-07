"""BranchGeometry.place() -- where Taskbar Manager's Add Shortcut branch goes.

The dock always puts the taskbar panel bottom-centre, so the live shell can
only ever exercise one parent position per screen size. This drives the
pure placement function directly with synthetic parent rects -- near every
screen edge, on small and large screens -- and checks the invariants that
matter: never off-screen, never overlapping the parent unless it is the
inside-the-parent "sheet" fallback, branches toward the side with room,
sensible minimum size.

    python3 tests/qml/test_branch_geometry.py
"""
import sys
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed (pip install PySide6-Essentials)")
    sys.exit(0)

SRC = (Path(__file__).resolve().parents[2] / "quickshell" / "BranchGeometry.js").read_text()
SRC = SRC.replace(".pragma library", "")

_app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
engine = QJSEngine()
engine.evaluate(SRC)
_place = engine.globalObject().property("place")

MARGIN, GAP, MIN_W, MIN_H = 8, 12, 280, 380
WANT = {"w": 340, "h": 520}


def place(parent, screen, anchor=None, header=48, footer=52):
    if anchor is None:
        anchor = {"x": parent["x"] + parent["w"] - 80, "y": parent["y"] + header / 2}
    args = [engine.toScriptValue(v) for v in (
        parent, anchor, WANT, screen,
        {"margin": MARGIN, "gap": GAP, "minW": MIN_W, "minH": MIN_H, "headerH": header, "footerH": footer})]
    r = _place.call(args).toVariant()
    return {k: (v if k == "side" else float(v)) for k, v in r.items()}


def rect(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def overlaps(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


SCREENS = [(3840, 2160), (2560, 1440), (1920, 1080), (1366, 768), (1280, 720), (1024, 768), (800, 600)]


class BranchGeometryTest(unittest.TestCase):
    def check(self, parent, sw, sh, ctx):
        r = place(parent, {"w": sw, "h": sh})
        b = {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
        ctx = f"{ctx} screen={sw}x{sh} parent={parent} -> {r}"
        # on-screen with margins
        self.assertGreaterEqual(b["x"], MARGIN - 0.01, ctx)
        self.assertGreaterEqual(b["y"], MARGIN - 0.01, ctx)
        self.assertLessEqual(b["x"] + b["w"], sw - MARGIN + 0.01, ctx)
        self.assertLessEqual(b["y"] + b["h"], sh - MARGIN + 0.01, ctx)
        self.assertGreater(b["w"], 0, ctx)
        self.assertGreater(b["h"], 0, ctx)
        if r["side"] == "sheet":
            # inside the parent's body, below its header, above its footer
            self.assertGreaterEqual(b["x"], parent["x"] - 0.01, ctx)
            self.assertLessEqual(b["x"] + b["w"], parent["x"] + parent["w"] + 0.01, ctx)
            self.assertGreaterEqual(b["y"], parent["y"] + 48 - 0.01, ctx)
            self.assertLessEqual(b["y"] + b["h"], parent["y"] + parent["h"] - 52 + 0.01, ctx)
        else:
            self.assertFalse(overlaps(b, parent), "branch overlaps its parent: " + ctx)
            self.assertGreaterEqual(b["w"], min(MIN_W, sw - 2 * MARGIN) - 0.01, ctx)
        return r

    def test_bottom_centre_dock_all_screens(self):
        for sw, sh in SCREENS:
            ph = min(470, sh - 16)
            parent = rect((sw - 640) / 2, sh - 8 - ph, 640, ph)
            r = self.check(parent, sw, sh, "dock")
            if sw >= 1366:
                self.assertIn(r["side"], ("right", "left"), f"{sw}x{sh}: expected a side branch, got {r}")
                # side branches line up with the parent's top and bottom
                self.assertAlmostEqual(r["y"], parent["y"], delta=0.5)
                self.assertAlmostEqual(r["h"], parent["h"], delta=0.5)

    def test_parent_near_each_edge(self):
        for sw, sh in SCREENS:
            pw, ph = min(640, sw - 16), min(470, sh - 16)
            cases = {
                "left": rect(MARGIN, (sh - ph) / 2, pw, ph),
                "right": rect(sw - MARGIN - pw, (sh - ph) / 2, pw, ph),
                "top": rect((sw - pw) / 2, MARGIN, pw, ph),
                "bottom": rect((sw - pw) / 2, sh - MARGIN - ph, pw, ph),
                "top-left": rect(MARGIN, MARGIN, pw, ph),
                "bottom-right": rect(sw - MARGIN - pw, sh - MARGIN - ph, pw, ph),
            }
            for name, parent in cases.items():
                r = self.check(parent, sw, sh, name)
                if name in ("left", "top-left") and r["side"] in ("left", "right"):
                    self.assertEqual(r["side"], "right", f"parent at left edge must branch right: {r}")
                if name in ("right", "bottom-right") and r["side"] in ("left", "right"):
                    self.assertEqual(r["side"], "left", f"parent at right edge must branch left: {r}")

    def test_small_parent_keeps_usable_branch(self):
        # A short parent must not squash the branch below its usable minimum.
        parent = rect(400, 900, 640, 160)
        r = self.check(parent, 1920, 1080, "short parent")
        self.assertGreaterEqual(r["h"], MIN_H - 0.01)

    def test_sheet_fallback_on_tiny_screen(self):
        parent = rect(80, 120, 640, 472)
        r = self.check(parent, 800, 600, "tiny")
        self.assertEqual(r["side"], "sheet")



# ---- the Theme editor's colour picker (ColorPopover.qml) -------------------
# Same function, with the two opt-in options the picker passes: prefer the
# RIGHT side whenever it fits, and sit level with the swatch that opened it
# (kept within the panel's own vertical span) rather than match its height.
POP = {"w": 288, "h": 348}
POP_MIN_W = 260
POP_OPTS = {"margin": MARGIN, "gap": GAP, "minW": POP_MIN_W, "minH": POP["h"], "headerH": 56, "footerH": 0,
            "preferSide": "right", "alignToAnchor": True}


def place_popover(parent, anchor, screen):
    args = [engine.toScriptValue(v) for v in (parent, anchor, POP, screen, POP_OPTS)]
    r = _place.call(args).toVariant()
    return {k: (v if k == "side" else float(v)) for k, v in r.items()}


def theme_panel(sw, sh):
    """ThemeEditor.qml's own panel geometry: centred under the bar."""
    pw = round(min(920, max(700, sw * 0.46)))
    return rect(round((sw - pw) / 2), 52, pw, min(640, sh - 60))


PALETTE_SCREENS = [(1920, 1080), (2560, 1440), (1366, 768), (1280, 720), (1024, 768), (3840, 2160), (800, 600)]


class PalettePopoverGeometryTest(unittest.TestCase):
    def check(self, parent, anchor, sw, sh, ctx):
        r = place_popover(parent, anchor, {"w": sw, "h": sh})
        b = {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
        ctx = f"{ctx} screen={sw}x{sh} parent={parent} anchor={anchor} -> {r}"
        for k in ("x", "y"):
            self.assertGreaterEqual(b[k], MARGIN - 0.01, "off-screen / negative: " + ctx)
        self.assertLessEqual(b["x"] + b["w"], sw - MARGIN + 0.01, ctx)
        self.assertLessEqual(b["y"] + b["h"], sh - MARGIN + 0.01, ctx)
        self.assertGreater(b["w"], 0, ctx)
        self.assertGreater(b["h"], 0, ctx)
        room_r = sw - MARGIN - (parent["x"] + parent["w"] + GAP)
        room_l = parent["x"] - GAP - MARGIN
        if room_r >= POP_MIN_W:
            self.assertEqual(r["side"], "right", "right side fits but was not used: " + ctx)
        elif room_l >= POP_MIN_W:
            self.assertEqual(r["side"], "left", "left side fits but was not used: " + ctx)
        if r["side"] in ("right", "left"):
            self.assertFalse(overlaps(b, parent), "popover overlaps the panel: " + ctx)
            gap = b["x"] - (parent["x"] + parent["w"]) if r["side"] == "right" else parent["x"] - (b["x"] + b["w"])
            self.assertAlmostEqual(gap, GAP, delta=0.01, msg="not attached at the gap: " + ctx)
            if parent["h"] >= b["h"]:
                # Level with the swatch, inside the panel's own span.
                self.assertGreaterEqual(b["y"], parent["y"] - 0.01, ctx)
                self.assertLessEqual(b["y"] + b["h"], parent["y"] + parent["h"] + 0.01, ctx)
                if parent["y"] + b["h"] / 2 <= anchor["y"] <= parent["y"] + parent["h"] - b["h"] / 2:
                    self.assertAlmostEqual(b["y"] + b["h"] / 2, anchor["y"], delta=0.51, msg="not centred on the swatch: " + ctx)
                self.assertTrue(b["y"] - 0.01 <= anchor["y"] <= b["y"] + b["h"] + 0.01, "swatch not beside the popover: " + ctx)
        elif r["side"] in ("above", "below"):
            self.assertFalse(overlaps(b, parent), "popover overlaps the panel: " + ctx)
        else:
            self.assertEqual(r["side"], "sheet", ctx)
            self.assertGreaterEqual(b["x"], parent["x"] - 0.01, ctx)
            self.assertLessEqual(b["x"] + b["w"], parent["x"] + parent["w"] + 0.01, ctx)
        return r

    def test_theme_panel_at_every_screen_size(self):
        expect = {(1920, 1080): "right", (2560, 1440): "right", (3840, 2160): "right",
                  (1366, 768): "right", (1280, 720): "right", (1024, 768): "sheet", (800, 600): "sheet"}
        for sw, sh in PALETTE_SCREENS:
            parent = theme_panel(sw, sh)
            for frac in (0.15, 0.5, 0.85):
                anchor = {"x": parent["x"] + parent["w"] - 56, "y": parent["y"] + parent["h"] * frac}
                r = self.check(parent, anchor, sw, sh, f"theme panel swatch@{frac}")
                self.assertEqual(r["side"], expect[(sw, sh)], f"{sw}x{sh}: {r}")

    def test_parent_near_each_edge(self):
        for sw, sh in PALETTE_SCREENS:
            pw, ph = min(700, sw - 16), min(520, sh - 16)
            cases = {
                "left": rect(MARGIN, (sh - ph) / 2, pw, ph),
                "right": rect(sw - MARGIN - pw, (sh - ph) / 2, pw, ph),
                "top": rect((sw - pw) / 2, MARGIN, pw, ph),
                "bottom": rect((sw - pw) / 2, sh - MARGIN - ph, pw, ph),
            }
            for name, parent in cases.items():
                for frac in (0.1, 0.5, 0.9):
                    anchor = {"x": parent["x"] + parent["w"] - 56, "y": parent["y"] + parent["h"] * frac}
                    r = self.check(parent, anchor, sw, sh, name)
                    if name == "right" and sw - pw - 16 >= POP_MIN_W + GAP:
                        self.assertEqual(r["side"], "left", f"parent at the right edge must branch left: {r}")

    def test_above_below_fallback_when_neither_side_fits(self):
        # A wide, short panel: no room either side, room below.
        sw, sh = 1366, 768
        parent = rect(40, 52, sw - 80, 200)
        r = self.check(parent, {"x": 1200, "y": 150}, sw, sh, "wide short panel")
        self.assertEqual(r["side"], "below", r)
        # The same panel hugging the bottom: room only above.
        parent = rect(40, sh - 8 - 200, sw - 80, 200)
        r = self.check(parent, {"x": 1200, "y": sh - 100}, sw, sh, "wide short bottom panel")
        self.assertEqual(r["side"], "above", r)

    def test_follows_the_parent_when_it_moves(self):
        sw, sh = 1920, 1080
        a = theme_panel(sw, sh)
        b = dict(a, x=a["x"] - 140, y=a["y"] + 30)
        ra = place_popover(a, {"x": a["x"] + a["w"] - 56, "y": a["y"] + 300}, {"w": sw, "h": sh})
        rb = place_popover(b, {"x": b["x"] + b["w"] - 56, "y": b["y"] + 300}, {"w": sw, "h": sh})
        self.assertAlmostEqual(rb["x"] - ra["x"], -140, delta=0.01)
        self.assertAlmostEqual(rb["y"] - ra["y"], 30, delta=0.01)

if __name__ == "__main__":
    unittest.main(verbosity=2)
