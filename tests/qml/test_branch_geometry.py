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



# ---- attach(): the Theme editor's colour picker (ColorPopover.qml) --------
# Branches off ONE control -- the swatch clicked -- not off the panel: it
# must start `gap` from the swatch's own edge, sit centred on it where the
# bounds allow, try right / left / below / above in that order, never cover
# the swatch, and stay inside the bounds it is given.
_attach = engine.globalObject().property("attach")
POP = {"w": 288, "h": 348}
POP_GAP, POP_MIN_W = 12, 260
SW = {"w": 32, "h": 24}


def attach(target, bounds, want=POP):
    args = [engine.toScriptValue(v) for v in (target, want, bounds,
                                              {"gap": POP_GAP, "minW": POP_MIN_W, "minH": want["h"]})]
    r = _attach.call(args).toVariant()
    return {k: (v if k in ("side", "fallback") else float(v)) for k, v in r.items()}


def theme_panel(sw, sh):
    """ThemeEditor.qml's own panel geometry: centred under the bar."""
    pw = round(min(920, max(700, sw * 0.46)))
    return rect(round((sw - pw) / 2), 52, pw, min(640, sh - 60))


def theme_bounds(sw, sh, panel):
    """What ThemeEditor passes: screen width minus the edge margin; the
    panel's own vertical span (or the picker's height if the panel is
    shorter), never past the screen."""
    return rect(MARGIN, panel["y"], sw - 2 * MARGIN,
                min(sh - MARGIN - panel["y"], max(panel["h"], POP["h"])))


PALETTE_SCREENS = [(1920, 1080), (2560, 1440), (1366, 768), (1280, 720), (1024, 768), (3840, 2160), (800, 600)]


class PaletteAttachGeometryTest(unittest.TestCase):
    def check(self, target, bounds, ctx, want=POP):
        r = attach(target, bounds, want)
        b = {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
        ctx = f"{ctx} target={target} bounds={bounds} -> {r}"
        self.assertGreaterEqual(b["x"], bounds["x"] - 0.01, "outside bounds: " + ctx)
        self.assertGreaterEqual(b["y"], bounds["y"] - 0.01, "outside bounds: " + ctx)
        self.assertLessEqual(b["x"] + b["w"], bounds["x"] + bounds["w"] + 0.01, "outside bounds: " + ctx)
        self.assertLessEqual(b["y"] + b["h"], bounds["y"] + bounds["h"] + 0.01, "outside bounds: " + ctx)
        self.assertFalse(overlaps(b, target), "covers the swatch it grows out of: " + ctx)
        side = r["side"]
        cx, cy = target["x"] + target["w"] / 2, target["y"] + target["h"] / 2
        if side == "right":
            self.assertAlmostEqual(b["x"], target["x"] + target["w"] + POP_GAP, delta=0.01, msg="not attached to the swatch's right edge: " + ctx)
        elif side == "left":
            self.assertAlmostEqual(b["x"] + b["w"], target["x"] - POP_GAP, delta=0.01, msg="not attached to the swatch's left edge: " + ctx)
        elif side == "below":
            self.assertAlmostEqual(b["y"], target["y"] + target["h"] + POP_GAP, delta=0.01, msg="not attached below the swatch: " + ctx)
        else:
            self.assertEqual(side, "above", ctx)
            self.assertAlmostEqual(b["y"] + b["h"], target["y"] - POP_GAP, delta=0.01, msg="not attached above the swatch: " + ctx)
        # Level with / centred on the swatch, unless the bounds clamp it --
        # and even then the swatch stays within the picker's span on that axis.
        if side in ("right", "left"):
            if bounds["y"] + b["h"] / 2 <= cy <= bounds["y"] + bounds["h"] - b["h"] / 2:
                self.assertAlmostEqual(b["y"] + b["h"] / 2, cy, delta=0.01, msg="not centred on the swatch: " + ctx)
            if not r["fallback"] and b["h"] >= target["h"]:
                self.assertTrue(b["y"] - 0.01 <= cy <= b["y"] + b["h"] + 0.01, "swatch not level with the picker: " + ctx)
        else:
            if bounds["x"] + b["w"] / 2 <= cx <= bounds["x"] + bounds["w"] - b["w"] / 2:
                self.assertAlmostEqual(b["x"] + b["w"] / 2, cx, delta=0.01, msg="not centred on the swatch: " + ctx)
        return r

    def test_theme_panel_at_every_screen_size(self):
        # The swatch sits at the right of each colour row, ~40px in from the
        # panel's right edge.
        expect = {(1920, 1080): "right", (2560, 1440): "right", (3840, 2160): "right",
                  (1366, 768): "right", (1280, 720): "right", (1024, 768): "left", (800, 600): "left"}
        for sw, sh in PALETTE_SCREENS:
            panel = theme_panel(sw, sh)
            bounds = theme_bounds(sw, sh, panel)
            for frac in (0.1, 0.5, 0.9):
                target = rect(panel["x"] + panel["w"] - 72, panel["y"] + (panel["h"] - SW["h"]) * frac, SW["w"], SW["h"])
                r = self.check(target, bounds, f"{sw}x{sh} swatch@{frac}")
                self.assertEqual(r["side"], expect[(sw, sh)], f"{sw}x{sh}: {r}")
                self.assertFalse(r["fallback"], f"{sw}x{sh}: {r}")

    def test_right_then_left_then_below_then_above(self):
        screen = rect(0, 0, 1920, 1080)
        r = self.check(rect(900, 500, 32, 24), screen, "open space")
        self.assertEqual(r["side"], "right")
        r = self.check(rect(1920 - 100, 500, 32, 24), screen, "swatch near the right edge")
        self.assertEqual(r["side"], "left")
        # A tall, narrow column of space: neither side has 260px, below does.
        narrow = rect(0, 0, 300, 1080)
        r = self.check(rect(134, 100, 32, 24), narrow, "narrow bounds, swatch high")
        self.assertEqual(r["side"], "below")
        r = self.check(rect(134, 900, 32, 24), narrow, "narrow bounds, swatch low")
        self.assertEqual(r["side"], "above")

    def test_swatch_near_every_edge(self):
        for sw, sh in PALETTE_SCREENS:
            bounds = rect(MARGIN, MARGIN, sw - 2 * MARGIN, sh - 2 * MARGIN)
            for name, (tx, ty) in {"left": (MARGIN + 4, sh / 2), "right": (sw - MARGIN - 36, sh / 2),
                                   "top": (sw / 2, MARGIN + 4), "bottom": (sw / 2, sh - MARGIN - 28),
                                   "top-left": (MARGIN + 4, MARGIN + 4), "bottom-right": (sw - MARGIN - 36, sh - MARGIN - 28)}.items():
                r = self.check(rect(tx, ty, SW["w"], SW["h"]), bounds, f"{sw}x{sh} {name}")
                if name in ("right", "bottom-right") and sw - 2 * MARGIN - 36 - POP_GAP >= POP_MIN_W:
                    self.assertEqual(r["side"], "left", f"swatch at the right edge must branch left: {r}")
                if name in ("left", "top-left"):
                    self.assertEqual(r["side"], "right", f"swatch at the left edge must branch right: {r}")

    def test_nowhere_fits_squeezes_beside_it_not_over_it(self):
        bounds = rect(0, 0, 400, 300)
        r = self.check(rect(184, 138, 32, 24), bounds, "tiny bounds")
        self.assertTrue(r["fallback"], r)

    def test_follows_the_swatch(self):
        bounds = rect(MARGIN, 52, 1920 - 2 * MARGIN, 640)
        a = attach(rect(1330, 300, 32, 24), bounds)
        b = attach(rect(1330, 260, 32, 24), bounds)
        self.assertEqual(a["side"], b["side"])
        self.assertAlmostEqual(b["y"] - a["y"], -40, delta=0.01, msg=f"picker did not move with the swatch: {a} {b}")

if __name__ == "__main__":
    unittest.main(verbosity=2)
