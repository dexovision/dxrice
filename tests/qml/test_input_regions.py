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
from test_customization import with_theme  # noqa: E402

SETTLE_MS = 1100        # > ShellIsland's durationEnter + keep-alive at default anim speed
SCREENS = [(1920, 1080), (2560, 1440), (1366, 768), (1024, 768)]


class InputRegionTest(unittest.TestCase):
    scene: Scene = None
    size = (1920, 1080)

    @classmethod
    def setUpClass(cls):
        # The panels' input only: the music widget now stays on the desktop
        # with no player (its own input is tested in test_widgets.py).
        cls.scene = Scene(width=cls.size[0], height=cls.size[1], setup=with_theme(widget_music=False))

    @classmethod
    def tearDownClass(cls):
        cls.scene.close()

    # ---- helpers ----
    def rects(self):
        return [dict(r) for r in self.scene.surface_rects().toVariant()]

    def assert_idle(self, context):
        s = self.scene
        rs = self.rects()
        # (zero-size regions are panels' bodies while closed: no input)
        top = [r for r in rs if r["surface"] == "TopBar" and r["w"] > 0 and r["h"] > 0]
        other = [r for r in rs if r["surface"] != "TopBar" and r["w"] > 0 and r["h"] > 0]
        # one bar: its whole strip takes input (a bar that looks solid must
        # not pass clicks through its gaps), and nothing below it does
        self.assertEqual(len(top), 1, f"{context}: the top bar should expose exactly its strip, got {top}")
        b = top[0]
        self.assertLessEqual(b["h"], 40, f"{context}: top-bar input taller than the bar: {b}")
        self.assertLessEqual(b["y"], 10, f"{context}: top-bar input not at the top edge: {b}")
        self.assertGreaterEqual(b["w"], s.width - 20, f"{context}: the bar's input doesn't span the bar: {b}")
        # the clock (the one widget on by default) is only to look at: it
        # takes no input, so nothing but the bar does at idle (there is no
        # dock any more)
        self.assertEqual(other, [], f"{context}: unexpected input surfaces {other}")
        # Click-through probes across the whole application area, away from
        # the bar: every one must reach the app underneath.
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
            self.assertEqual(s.input_owner(px, py), "TopBar", f"open branch point {(px, py)} not in the input mask")
        # The branch's own close button is clickable and closes it.
        cx = s.ev("(function(){ const b = findNamed('addShortcutBranchClose'); const p = b.mapToItem(null, b.width/2, b.height/2); return p.x; })()")
        cy = s.ev("(function(){ const b = findNamed('addShortcutBranchClose'); const p = b.mapToItem(null, b.width/2, b.height/2); return p.y; })()")
        self.assertEqual(s.click(cx, cy), "TopBar", "close button is outside the input mask")
        self.settle(700)
        self.assertFalse(s.ev("findPanel('addPanelOpen').addPanelOpen"), "clicking the branch's X did not close it")
        # Closed branch contributes nothing, even though the taskbar is open.
        self.assertFalse(any(r["surface"] == "TopBar" and r["w"] > 0 and abs(r["x"] - bx) < 1 and abs(r["y"] - by) < 1 for r in self.rects()),
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
        self.assertEqual(names, ["TopBar"], f"unexpected surfaces while Add Shortcut is open: {names}")
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
        s = self.scene
        s.ev("panels.open('taskbar')"); self.settle(700)
        s.ev("findPanel('addPanelOpen').addPanelOpen = true"); self.settle(700)
        # The bar's single handler, called directly (in this harness every
        # surface shares one QQuickView).
        s.ev("findNamed('topBarEscape').activated()")
        self.settle(500)
        self.assertFalse(s.ev("findPanel('addPanelOpen').addPanelOpen"), "Escape did not close the branch first")
        self.assertEqual(s.ev("panels.current"), "taskbar", "Escape closed the taskbar instead of just the branch")
        s.ev("findNamed('topBarEscape').activated()")
        self.settle()
        self.assertEqual(s.ev("panels.current"), "", "second Escape did not close the taskbar")
        self.assert_idle("after Escape x2")

    def _center_of_text(self, panel_prop, text):
        v = self.scene.ev(f"""(function(){{ const st=[findPanel('{panel_prop}')]; while (st.length) {{ const it=st.pop();
            if (String(it).startsWith('QQuickText') && String(it.text) === '{text}') {{ const p = it.mapToItem(null, it.width/2, it.height/2); return [p.x, p.y]; }}
            for (let i=0;i<it.children.length;i++) st.push(it.children[i]); }} }})()""").toVariant()
        return v[0], v[1]

    def test_09_closing_panel_releases_input_immediately(self):
        """A panel that is visually closing must stop taking input at once,
        not when its close animation finishes. The Theme editor's window
        lives on for its reverse-reveal (~440ms) and kept an unconditional
        full-screen dismiss region the whole time: every click anywhere on
        the desktop in that window was swallowed by an invisible catcher.
        Probes the app well away from every island mid-close."""
        s = self.scene
        # (a panel's body lets go of input the moment its close begins, so
        # these probes may cross where it is still visibly retracting)
        x_max = int(s.width * 0.30)
        probes = [(x, y) for x in range(int(s.width * 0.05), x_max, max(30, s.width // 32))
                  for y in range(int(s.height * 0.55), int(s.height * 0.80), max(40, s.height // 14))]
        for name in ["quicksettings", "calendar", "taskbar", "theme"]:
            s.ev(f"panels.open('{name}')")
            self.settle()
            s.ev("panels.closeCurrent()")
            s.wait(60)  # mid close animation
            blocked = [(x, y) for (x, y) in probes if s.input_owner(x, y) is not None]
            self.assertEqual(blocked, [], f"{name} closing: {len(blocked)} points over the app intercepted, "
                                          f"e.g. {blocked[:3]} by {s.input_owner(*blocked[0]) if blocked else None}")
            before = s.ev("appClicks")
            s.click(*probes[0])
            self.assertEqual(s.ev("appClicks"), before + 1, f"{name} closing: a click over the app did not reach it")
            if name == "theme":
                focusable = s.ev("surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0).map(w => w.focusable)")
                self.assertEqual(list(focusable.toVariant()) if hasattr(focusable, "toVariant") else list(focusable),
                                 [False], "closing Theme editor still holds keyboard focus")
            self.settle()
            self.assert_idle(f"after {name} finished closing")

    def test_10_closing_overview_releases_input_immediately(self):
        """The overview is a full-monitor overlay that stays mapped through
        its closing zoom and the release frames. It used to have no input
        mask at all, so for that whole time (up to the compositor's window
        move after a panning click) every click on the desktop landed on its
        stage instead of the application underneath."""
        import json
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from test_overview import MIXED, clients_for, monitor
        import dxrice_spiral as sp
        s = self.scene
        mon = monitor()
        mon["width"], mon["height"] = s.width, s.height
        rects = sp.arrange(MIXED, [], (0, 52, s.width, s.height - 68), (32, 56))
        s.set_command("hyprctl -j clients", json.dumps(clients_for(rects)))
        s.set_command("hyprctl -j monitors", json.dumps([mon]))
        ov = "findNamed('overview')"
        x, y = int(s.width * 0.6), int(s.height * 0.6)
        for close in [f"{ov}.hide()", "pan"]:
            s.ev(f"{ov}.show()"); self.settle(900)
            self.assertTrue(s.ev(f"{ov}.open"))
            self.assertEqual(s.input_owner(x, y), "overview", "an open overview must take the click")
            if close == "pan":
                # click the window farthest off screen: the close then runs as
                # long as the compositor's move
                tiles = json.loads(s.ev("JSON.stringify(" + ov + ".layout.windows)"))
                far = max(tiles, key=lambda w: abs(w["x"]) + abs(w["y"]))
                s.ev(f"{ov}.activate(findNamed('overviewTile:{far['address']}'))")
            else:
                s.ev(close)
            for wait in (30, 60, 90):  # cumulative 180ms, inside the 300ms zoom
                s.wait(wait)
                self.assertTrue(s.ev(f"{ov}.showing"), "test needs the overview still on screen")
                self.assertIsNone(s.input_owner(x, y), f"closing overview ({close}) still takes input after {wait}ms")
            before = s.ev("appClicks")
            s.click(x, y)
            self.assertEqual(s.ev("appClicks"), before + 1, "a click right after closing the overview was swallowed")
            self.settle()
        self.assert_idle("after the overview closed")

    def test_08_clicks_inside_a_panel_never_dismiss_it(self):
        """The other half of the invariant: inside an open surface, bare
        (non-control) areas must not fall through to the click-outside
        catcher underneath and close it."""
        s = self.scene
        s.ev("panels.open('calendar')"); self.settle(900)
        x, y = self._center_of_text("viewDate", "15")
        self.assertEqual(s.click(x, y), "TopBar")
        s.wait(500)
        self.assertEqual(s.ev("panels.current"), "calendar", "clicking a calendar day closed the calendar")
        s.ev("panels.open('taskbar')"); self.settle(900)
        x, y = self._center_of_text("addPanelOpen", "Taskbar")
        s.click(x, y); s.wait(500)
        self.assertEqual(s.ev("panels.current"), "taskbar", "clicking the taskbar header closed the taskbar")
        s.ev("findPanel('addPanelOpen').addPanelOpen = true"); self.settle(800)
        s.click(x, y); s.wait(500)
        self.assertTrue(s.ev("findPanel('addPanelOpen').addPanelOpen"), "clicking the parent panel closed the branch")
        s.ev("panels.closeCurrent()"); self.settle()
        self.assert_idle("after inside-panel clicks")


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
