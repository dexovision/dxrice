"""The top bar's focused-window label follows Hyprland's events instead of
polling `hyprctl activewindow -j` every 1.5 s.

    python3 tests/qml/test_topbar_events.py
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

BAR = "(function(){ let it = findNamed('activityIsland'); while (it && it.activeAppId === undefined) it = it.parent; return it; })()"


class TopBarFocusedWindow(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def bar(self, prop):
        return self.s.ev(f"{BAR}.{prop}")

    def event(self, name, data):
        self.s.ev(f"hypr.rawEvent({{ name: '{name}', data: {data!r} }})")
        self.s.wait(50)

    def queries(self):
        return sum(1 for argv in self.s.bridge.run_log if argv[:2] == ["hyprctl", "activewindow"])

    def test_read_once_at_startup(self):
        # the harness fixture answers with Discord
        self.assertEqual(self.bar("activeAppId"), "discord")
        self.assertEqual(self.bar("activeTitle"), "#general | Discord")

    def test_no_polling(self):
        before = self.queries()
        self.s.wait(5000)
        self.assertEqual(self.queries(), before, "the bar queried hyprctl while nothing happened")

    def test_follows_focus_changes(self):
        self.event("activewindowv2", "55aa")
        self.event("activewindow", "firefox,Some page, with a comma - Mozilla Firefox")
        self.assertEqual(self.bar("activeAppId"), "firefox")
        self.assertEqual(self.bar("activeTitle"), "Some page, with a comma - Mozilla Firefox")

    def test_title_changes_of_the_focused_window_only(self):
        self.event("activewindowv2", "55aa")
        self.event("activewindow", "firefox,First tab")
        self.event("windowtitlev2", "77bb,Another window's title")
        self.assertEqual(self.bar("activeTitle"), "First tab")
        self.event("windowtitlev2", "55aa,Second tab")
        self.assertEqual(self.bar("activeTitle"), "Second tab")
        self.assertEqual(self.bar("activeAppId"), "firefox")

    def test_empty_workspace_clears_it(self):
        self.event("activewindow", ",")
        self.assertEqual(self.bar("activeAppId"), "")
        self.assertEqual(self.bar("activeTitle"), "")

    def test_config_reload_reads_again(self):
        before = self.queries()
        self.event("configreloaded", "")
        self.s.wait(100)
        self.assertEqual(self.queries(), before + 1)


class WorkspacePills(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.s.ev("hypr.workspaces = ({ values: ["
                  "{ id: -98, name: 'special:scratch', focused: false, activated: false, activate: function() { this.activated = true; } },"
                  "{ id: 1, focused: true, activated: false, activate: function() { this.activated = true; } },"
                  "{ id: 2, focused: false, activated: false, activate: function() { this.activated = true; } }] })")
        self.s.wait(100)

    def tearDown(self):
        self.s.close()

    def test_special_workspaces_get_no_pill(self):
        self.assertIsNone(self.s.ev("findNamed('workspacePill:-98')"))
        self.assertIsNotNone(self.s.ev("findNamed('workspacePill:2')"))

    def test_clicking_a_pill_switches_in_lua_syntax(self):
        import json
        pos = json.loads(self.s.ev("(function(){ const p = findNamed('workspacePill:2');"
                                   " const q = p.mapToItem(null, p.width / 2, p.height / 2);"
                                   " return JSON.stringify([q.x, q.y]); })()"))
        self.s.ev("hypr.dispatchLog = []")
        self.s.click(int(pos[0]), int(pos[1]))
        self.s.wait(50)
        self.assertEqual(json.loads(self.s.ev("JSON.stringify(hypr.dispatchLog)")),
                         ["hl.dsp.focus({ workspace = 2 })"])
        self.assertFalse(self.s.ev("hypr.workspaces.values[2].activated"),
                         "went through Quickshell's activate(), whose syntax may be classic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
