"""Regression test: closed/invisible DXrice surfaces must not intercept
pointer input outside their intended interaction region.

Runs the REAL shell QML offscreen (see harness.py) and checks the input
mask each shell surface hands the compositor -- modelled on Quickshell's
own Region semantics -- after every open/close/interrupt sequence.

    python3 tests/qml/test_input_regions.py

Skips (exit 0, with a message) when PySide6 isn't installed: this is a
developer test, not part of install.sh's verification step.
"""
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed (pip install PySide6-Essentials)")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402

SETTLE_MS = 1100        # > ShellIsland's durationEnter + keep-alive at default anim speed
SCREENS = [(1920, 1080), (2560, 1440), (1366, 768), (1024, 768)]


class InputRegionTest(unittest.TestCase):
    scene: Scene = None
    size = (1920, 1080)

    @classmethod
    def setUpClass(cls):
        cls.scene = Scene(width=cls.size[0], height=cls.size[1])

    @classmethod
    def tearDownClass(cls):
        cls.scene.close()

    # ---- helpers ----
    def rects(self):
        return [dict(r) for r in self.scene.surface_rects().toVariant()]

    def assert_idle(self, context):
        s = self.scene
        rs = self.rects()
        top = [r for r in rs if r["surface"] == "TopBar"]
        dock = [r for r in rs if r["surface"] == "Dock"]
        other = [r for r in rs if r["surface"] not in ("TopBar", "Dock")]
        self.assertEqual(len(top), 3, f"{context}: top bar should expose exactly its 3 capsules, got {top}")
        self.assertEqual(len(dock), 1, f"{context}: dock should expose exactly its own slab, got {dock}")
        self.assertEqual(other, [], f"{context}: unexpected input surfaces {other}")
        for r in top:
            self.assertLessEqual(r["h"], 40, f"{context}: top-bar input taller than a capsule: {r}")
        d = dock[0]
        self.assertLessEqual(d["h"], 60, f"{context}: dock input taller than the dock slab: {d}")
        self.assertGreaterEqual(d["y"], s.height - 70, f"{context}: dock input not at the bottom edge: {d}")
        # Click-through probes across the whole application area, away from
        # the capsules/dock: every one must reach the app underneath.
        before = s.ev("appClicks")
        probes = [(x, y) for x in range(int(s.width * 0.15), int(s.width * 0.85), max(40, s.width // 24))
                  for y in range(int(s.height * 0.30), int(s.height - 80), max(40, s.height // 14))]
        blocked = [(x, y) for (x, y) in probes if s.input_owner(x, y) is not None]
        self.assertEqual(blocked, [], f"{context}: {len(blocked)} points over the app are intercepted by the shell, e.g. {blocked[:5]}")
        # And one real routed click lands on the app.
        s.click(int(s.width * 0.7), int(s.height * 0.75))
        self.assertEqual(s.ev("appClicks"), before + 1, f"{context}: a click over the app did not reach it")

    def settle(self, ms=SETTLE_MS):
        self.scene.wait(ms)

    def taskbar(self):
        return self.scene.ev("findPanel('addPanelOpen')")

    # ---- tests ----
    def test_00_idle(self):
        self.assert_idle("idle at startup")

    def test_01_each_panel_open_close(self):
        for name in ["quicksettings", "calendar", "taskbar", "theme"]:
            self.scene.ev(f"panels.open('{name}')")
            self.settle()
            self.scene.ev("panels.closeCurrent()")
            self.settle()
            self.assert_idle(f"after open/close of {name}")

    def test_02_interrupted_close_and_reopen(self):
        for name in ["quicksettings", "calendar", "taskbar", "theme"]:
            s = self.scene
            s.ev(f"panels.open('{name}')"); s.wait(150)
            s.ev("panels.closeCurrent()"); s.wait(80)
            s.ev(f"panels.open('{name}')"); s.wait(200)
            s.ev("panels.closeCurrent()"); s.wait(60)
            s.ev(f"panels.open('{name}')"); s.wait(500)
            s.ev("panels.closeCurrent()")
            self.settle()
            self.assert_idle(f"after interrupted open/close of {name}")

    def test_03_rapid_switching(self):
        s = self.scene
        for _ in range(3):
            for name in ["quicksettings", "calendar", "taskbar", "theme", "quicksettings"]:
                s.ev(f"panels.open('{name}')"); s.wait(70)
        s.ev("panels.closeCurrent()")
        self.settle()
        self.assert_idle("after rapid panel switching")

    def test_04_add_shortcut_branch_input(self):
        s = self.scene
        s.ev("panels.open('taskbar')"); self.settle(700)
        s.ev("findPanel('addPanelOpen').addPanelOpen = true"); self.settle(800)
        branch = s.ev("findNamed('addShortcutBranch')")
        self.assertIsNotNone(branch, "branch item not found (objectName addShortcutBranch)")
        bx, by = s.ev("findNamed('addShortcutBranch').mapToItem(null, 0, 0).x"), s.ev("findNamed('addShortcutBranch').mapToItem(null, 0, 0).y")
        bw, bh = s.ev("findNamed('addShortcutBranch').width"), s.ev("findNamed('addShortcutBranch').height")
        # Every point of the branch (including its top strip, where the
        # close button lives) must be inside the input mask while open.
        for fx, fy in [(0.02, 0.02), (0.98, 0.02), (0.5, 0.5), (0.02, 0.98), (0.98, 0.98)]:
            px, py = bx + bw * fx, by + bh * fy
            self.assertEqual(s.input_owner(px, py), "Dock", f"open branch point {(px, py)} not in the input mask")
        # The branch's own close button is clickable and closes it.
        cx = s.ev("(function(){ const b = findNamed('addShortcutBranchClose'); const p = b.mapToItem(null, b.width/2, b.height/2); return p.x; })()")
        cy = s.ev("(function(){ const b = findNamed('addShortcutBranchClose'); const p = b.mapToItem(null, b.width/2, b.height/2); return p.y; })()")
        self.assertEqual(s.click(cx, cy), "Dock", "close button is outside the input mask")
        self.settle(700)
        self.assertFalse(s.ev("findPanel('addPanelOpen').addPanelOpen"), "clicking the branch's X did not close it")
        # Closed branch contributes nothing, even though the taskbar is open.
        self.assertFalse(any(r["surface"] == "Dock" and abs(r["x"] - bx) < 1 and abs(r["y"] - by) < 1 for r in self.rects()),
                         "closed branch still in the input mask")
        # Branch open -> taskbar closed: everything goes away together, and
        # a quick reopen does NOT resurrect the branch.
        s.ev("findPanel('addPanelOpen').addPanelOpen = true"); self.settle(600)
        s.ev("panels.closeCurrent()"); s.wait(150)
        s.ev("panels.open('taskbar')"); self.settle(700)
        self.assertFalse(s.ev("findPanel('addPanelOpen').addPanelOpen"), "branch reopened on its own with the taskbar")
        s.ev("panels.closeCurrent()"); self.settle()
        self.assert_idle("after branch open + taskbar closed")

    def test_05_no_separate_window_for_add_shortcut(self):
        s = self.scene
        s.ev("panels.open('taskbar')"); self.settle(700)
        s.ev("findPanel('addPanelOpen').addPanelOpen = true"); self.settle(700)
        tops = s.ev("surfaces().filter(function(x){ return x.isToplevelWindow && x.visible; }).length")
        self.assertEqual(tops, 0, "Add Shortcut opened a separate toplevel window")
        names = sorted(set(r["surface"] for r in self.rects()))
        self.assertEqual(names, ["Dock", "TopBar"], f"unexpected surfaces while Add Shortcut is open: {names}")
        s.ev("panels.closeCurrent()"); self.settle()

    def test_06_single_escape_claim_per_window(self):
        s = self.scene
        for setup in ["", "panels.open('taskbar')", "findPanel('addPanelOpen').addPanelOpen = true",
                      "panels.open('quicksettings')", "panels.open('theme')"]:
            if setup:
                s.ev(setup); self.settle(700)
            claims = s.ev("escapeClaims()").toVariant()
            for surface, n in claims.items():
                self.assertLessEqual(n, 1, f"{surface} has {n} enabled Escape shortcuts after `{setup or 'startup'}` -- Qt makes them all ambiguous")
        s.ev("panels.closeCurrent()"); self.settle()

    def test_07_escape_peels_branch_then_taskbar(self):
        from PySide6.QtCore import Qt
        s = self.scene
        s.ev("panels.open('taskbar')"); self.settle(700)
        s.ev("findPanel('addPanelOpen').addPanelOpen = true"); self.settle(700)
        # Call the Dock's single handler directly: in this harness every
        # surface shares one QQuickView, so TopBar's own (separate-window in
        # reality) Escape would collide with Dock's here and nowhere else.
        s.ev("findNamed('dockEscape').activated()")
        self.settle(500)
        self.assertFalse(s.ev("findPanel('addPanelOpen').addPanelOpen"), "Escape did not close the branch first")
        self.assertEqual(s.ev("panels.current"), "taskbar", "Escape closed the taskbar instead of just the branch")
        s.ev("findNamed('dockEscape').activated()")
        self.settle()
        self.assertEqual(s.ev("panels.current"), "", "second Escape did not close the taskbar")
        self.assert_idle("after Escape x2")


def main():
    # One process per screen size: a QML engine binds the harness singleton
    # instance for its lifetime, so each size gets a fresh interpreter.
    import os
    import subprocess
    size = os.environ.get("DXRICE_TEST_SIZE")
    if size:
        w, h = (int(v) for v in size.split("x"))
        InputRegionTest.size = (w, h)
        InputRegionTest.__name__ = f"InputRegion_{w}x{h}"
        unittest.main(argv=[sys.argv[0], "-v"] + sys.argv[1:])
        return
    failed = []
    for w, h in SCREENS:
        print(f"===== {w}x{h} =====", flush=True)
        rc = subprocess.call([sys.executable, __file__] + sys.argv[1:], env={**os.environ, "DXRICE_TEST_SIZE": f"{w}x{h}"})
        if rc:
            failed.append(f"{w}x{h}")
    print("FAILED sizes: " + ", ".join(failed) if failed else "ALL SIZES PASSED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
