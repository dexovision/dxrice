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


if __name__ == "__main__":
    unittest.main(verbosity=2)
