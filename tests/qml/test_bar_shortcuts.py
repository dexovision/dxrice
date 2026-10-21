#!/usr/bin/env python3
"""The saved shortcuts in the bar (they were the dock's): which apps are
open (from Hyprland's own window list), which one is focused, and the hop a
launch gives.

    python3 tests/qml/test_bar_shortcuts.py
"""
import json
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402

def child(s, tile, name):
    return f"(function(){{ const t = findNamed('barShortcut:{tile}'); for (let i = 0; i < t.children.length; i++) if (t.children[i].objectName === '{name}') return t.children[i]; return null; }})()"


TOPBAR = "findNamed('statusIsland').parent"


class BarShortcutsTest(unittest.TestCase):
    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.wait(300)

    def tearDown(self):
        self.s.close()

    def key(self, cmd):
        return self.s.ev(f"shortcuts.appKeyOf({json.dumps(cmd)})")

    def test_a_shortcut_names_its_program(self):
        self.assertEqual(self.key("sh -c 'firefox >/dev/null 2>&1 &'"), "firefox")
        self.assertEqual(self.key("/usr/bin/discord --ozone-platform=wayland"), "discord")
        self.assertEqual(self.key("env GDK_BACKEND=wayland code ."), "code")
        self.assertEqual(self.key("sh -c 'it'\\''s >/dev/null 2>&1 &'"), "it's")
        self.assertEqual(self.key(""), "")

    def test_window_classes_match_their_program(self):
        m = lambda c, k: self.s.ev(f"shortcuts.matches({json.dumps(c)}, {json.dumps(k)})")  # noqa: E731
        self.assertTrue(m("firefox", "firefox"))
        self.assertTrue(m("org.gnome.Nautilus", "nautilus"))
        self.assertTrue(m("brave-browser", "brave"))
        self.assertFalse(m("firefoxdeveloperedition", "firefox"))
        self.assertFalse(m("", "firefox"))

    def test_an_open_app_gets_a_mark_and_the_focused_one_a_wider_accent_one(self):
        mark = child(self.s, "Firefox", "barRunning")
        self.assertEqual(self.s.ev(f"{mark}.opacity"), 0)
        self.s.ev("hypr.toplevels = ({ values: [{ address: '0x1', lastIpcObject: { class: 'firefox' } }] })")
        self.s.wait(400)
        self.assertGreater(self.s.ev(f"{mark}.opacity"), 0)
        narrow = self.s.ev(f"{mark}.width")
        self.s.ev(f"{TOPBAR}.setActive('firefox', 'Mozilla Firefox')")   # a focus event
        self.s.wait(500)
        self.assertGreater(self.s.ev(f"{mark}.width"), narrow)
        self.assertEqual(self.s.ev(f"{mark}.color.toString()"), self.s.ev("theme.accent.toString()"))

    def test_the_focused_mark_works_before_any_focus_change(self):
        # Hyprland.activeToplevel is null until the first focus change; the
        # bar reads the focused class from its own startup read
        mark = child(self.s, "Firefox", "barRunning")
        self.s.ev("hypr.activeToplevel = null")
        self.s.ev("hypr.toplevels = ({ values: [{ address: '0x1', wayland: { appId: 'firefox' } }] })")
        self.s.ev(f"{TOPBAR}.setActive('firefox', '')")
        self.s.wait(500)
        self.assertGreater(self.s.ev(f"{mark}.opacity"), 0.9, "running, from the Wayland app id")
        self.assertEqual(self.s.ev(f"{mark}.width"), 10)

    def test_there_is_no_second_launcher_or_dock(self):
        self.assertIsNone(self.s.ev("findNamed('dockIsland')"))
        self.assertIsNone(self.s.ev("findNamed('launcher')"))
        src = (Path(__file__).resolve().parents[2] / "quickshell" / "shell.qml").read_text()
        self.assertNotIn("Dock {", src)
        self.assertNotIn("AppLauncher {", src)

    def test_launching_hops_the_icon_and_it_lands_back(self):
        pos = json.loads(self.s.ev('(function(){ const t = findNamed("barShortcut:Firefox");'
                                   ' const p = t.mapToItem(null, t.width / 2, t.height / 2);'
                                   ' return JSON.stringify([p.x, p.y]); })()'))
        self.s.click(int(pos[0]), int(pos[1]))
        lowest = 0
        for _ in range(30):
            self.s.wait(15)
            lowest = min(lowest, self.s.ev("findNamed('barShortcut:Firefox').lift"))
        self.assertLess(lowest, -3, "no hop")
        self.s.wait(800)
        self.assertEqual(self.s.ev("findNamed('barShortcut:Firefox').lift"), 0)


if __name__ == "__main__":
    unittest.main()
