#!/usr/bin/env python3
"""The application launcher (SUPER+R): ranking, keys, launching, closing and
its motion, through the real shell QML offscreen.

    python3 tests/qml/test_launcher.py
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
from PySide6.QtCore import Qt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
APPS = [
    {"name": "Firefox", "cmd": "firefox", "icon": "firefox", "uses": 40},
    {"name": "Files", "cmd": "nautilus", "icon": "", "uses": 3},
    {"name": "Visual Studio Code", "cmd": "code", "icon": "", "uses": 12},
    {"name": "Kitty", "cmd": "kitty", "icon": "", "uses": 90},
    {"name": "GNU Image Manipulation Program", "cmd": "gimp", "icon": "", "uses": 0},
    {"name": "Discord", "cmd": "/usr/bin/discord --ozone-platform=wayland", "icon": "", "uses": 20},
    {"name": "Fire Alarm <b>", "cmd": "alarm", "icon": "", "uses": 0},
    {"name": "Steam", "cmd": "steam", "icon": "", "uses": 5},
    {"name": "Settings", "cmd": "gnome-control-center", "icon": "", "uses": 0},
    {"name": "Terminal Emulator", "cmd": "xterm", "icon": "", "uses": 1},
]


def js():
    from PySide6.QtQml import QJSEngine
    eng = QJSEngine()
    eng.evaluate((REPO / "quickshell" / "LauncherSearch.js").read_text().replace(".pragma library", ""))
    return lambda q, apps=APPS, limit=8: eng.evaluate(
        f"JSON.stringify(rank({json.dumps(apps)}, {json.dumps(q)}, {limit}).map(function(r) {{ return [r.app.name, r.start, r.len]; }}))"
    ).toString()


class RankingTest(unittest.TestCase):
    def names(self, q, **kw):
        return [r[0] for r in json.loads(js()(q, **kw))]

    def test_an_empty_query_lists_the_most_used_first(self):
        got = self.names("")
        self.assertEqual(got[:3], ["Kitty", "Firefox", "Discord"])
        self.assertEqual(len(got), 8)

    def test_a_prefix_beats_a_word_start_beats_a_substring(self):
        self.assertEqual(self.names("fi")[0], "Firefox")                  # prefix, and used most
        self.assertEqual(self.names("code")[0], "Visual Studio Code")      # word start
        self.assertEqual(self.names("studio")[0], "Visual Studio Code")
        got = self.names("ile")
        self.assertEqual(got[0], "Files")                                  # substring

    def test_usage_breaks_ties_but_never_beats_a_better_match(self):
        apps = [{"name": "Alpha Notes", "cmd": "a", "uses": 0}, {"name": "Notes", "cmd": "n", "uses": 0},
                {"name": "My notes", "cmd": "m", "uses": 500}]
        self.assertEqual(self.names("notes", apps=apps)[0], "Notes")       # exact beats a heavily used word match

    def test_scattered_letters_and_the_command_match_last(self):
        self.assertIn("Firefox", self.names("ffx"))
        self.assertEqual(self.names("nautilus")[0], "Files")               # matched by its command only
        self.assertEqual(self.names("zzzzqq"), [])

    def test_the_match_is_marked_for_highlighting(self):
        row = [r for r in json.loads(js()("code")) if r[0] == "Visual Studio Code"][0]
        self.assertEqual(row[1:], [14, 4])

    def test_the_limit_and_case(self):
        self.assertEqual(len(self.names("", limit=3)), 3)
        self.assertEqual(self.names("FIREFOX")[0], "Firefox")


def click(s, x, y):
    """A click straight into the scene (the launcher covers the monitor)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    QTest.mouseClick(s.view, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(y)))


def centre(s, name):
    return s.ev(f"(function(){{ const b = findNamed('{name}'); const p = b.mapToItem(null, b.width/2, b.height/2); return [p.x, p.y]; }})()").toVariant()


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.set_command("dxrice_list_desktop_apps.py", json.dumps(APPS))
        self.L = "findNamed('launcher')"

    def tearDown(self):
        self.s.close()

    def open(self):
        self.s.ev(f"{self.L}.show()")
        self.s.wait(700)

    def type(self, text):
        self.s.ev(f"{self.L}.query = {json.dumps(text)}")
        self.s.wait(120)

    def names(self):
        return json.loads(self.s.ev(f"JSON.stringify({self.L}.results.map(r => r.app.name))"))

    def test_toggle_opens_and_closes_and_nothing_runs_while_closed(self):
        self.assertFalse(self.s.ev(f"{self.L}.visible"))
        self.open()
        self.assertTrue(self.s.ev(f"{self.L}.open"))
        self.assertEqual(self.s.ev(f"{self.L}.progress"), 1)
        self.s.ev(f"{self.L}.toggle()")
        self.s.wait(500)
        self.assertFalse(self.s.ev(f"{self.L}.visible"))
        self.assertEqual(self.s.ev(f"{self.L}.progress"), 0)

    def test_the_panel_opens_with_the_best_eight_and_loads_the_list_once_per_open(self):
        self.open()
        self.assertEqual(self.names()[:2], ["Kitty", "Firefox"])
        self.assertEqual(len(self.names()), 8)
        self.assertEqual(len([r for r in self.s.bridge.run_log if "dxrice_list_desktop_apps.py" in " ".join(r)]), 1)

    def test_typing_narrows_and_the_selection_resets_to_the_top(self):
        self.open()
        self.s.ev(f"{self.L}.selected = 3")
        self.type("fi")
        self.assertEqual(self.names()[0], "Firefox")
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0)

    def test_arrows_and_ctrl_keys_move_and_wrap(self):
        self.open()
        n = len(self.names())
        self.s.key(Qt.Key_Down)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 1)
        self.s.key(Qt.Key_Up)
        self.s.key(Qt.Key_Up)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), n - 1, "up from the first should wrap to the last")
        self.s.key(Qt.Key_Down)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0)

    def test_the_highlight_glides_to_the_selected_row(self):
        self.open()
        y0 = self.s.ev("findNamed('launcherHighlight').y")
        self.s.key(Qt.Key_Down)
        self.s.key(Qt.Key_Down)
        self.s.wait(15)
        mid = self.s.ev("findNamed('launcherHighlight').y")
        self.s.wait(500)
        y1 = self.s.ev("findNamed('launcherHighlight').y")
        self.assertAlmostEqual(y1 - y0, 2 * self.s.ev(f"{self.L}.rowHeight"), delta=1)
        self.assertTrue(y0 <= mid <= y1)

    def test_enter_launches_the_selected_app_through_the_scope_script_and_records_it(self):
        self.open()
        self.type("disc")
        self.s.key(Qt.Key_Return)
        self.s.wait(400)
        ex = self.s.bridge.exec_log
        launch = [e for e in ex if "dxrice_launch.sh" in e[0]]
        self.assertEqual(len(launch), 1, ex)
        self.assertEqual(launch[0][1:], ["launcher", "sh", "-c", "/usr/bin/discord --ozone-platform=wayland"])
        hist = [r for r in self.s.bridge.run_log if "dxrice_launcher_history.py" in " ".join(r)]
        self.assertEqual(hist[-1][-2:], ["bump", "Discord"])
        self.assertFalse(self.s.ev(f"{self.L}.open"), "it should close after launching")

    def test_nothing_matching_says_so_and_enter_does_nothing(self):
        self.open()
        self.type("zzzzqq")
        self.assertTrue(self.s.ev("findNamed('launcherEmpty').visible"))
        self.assertIn("Nothing matches", self.s.ev("findNamed('launcherEmpty').text"))
        self.s.key(Qt.Key_Return)
        self.s.wait(200)
        self.assertEqual([e for e in self.s.bridge.exec_log if "dxrice_launch.sh" in e[0]], [])
        self.assertTrue(self.s.ev(f"{self.L}.open"))

    def test_escape_closes_and_a_reopen_starts_clean(self):
        self.open()
        self.type("fi")
        self.s.key(Qt.Key_Escape)
        self.s.wait(500)
        self.assertFalse(self.s.ev(f"{self.L}.open"))
        self.open()
        self.assertEqual(self.s.ev(f"{self.L}.query"), "")
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0)

    def test_a_click_outside_closes_and_a_click_inside_does_not(self):
        self.open()
        px, py = centre(self.s, "launcherPanel")
        click(self.s, px + 200, py - self.s.ev("findNamed('launcherPanel').height") / 2 + 30)   # the search bar
        self.s.wait(300)
        self.assertTrue(self.s.ev(f"{self.L}.open"))
        click(self.s, 60, 540)
        self.s.wait(500)
        self.assertFalse(self.s.ev(f"{self.L}.open"))

    def test_a_resting_pointer_does_not_take_the_selection_but_a_moving_one_does(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        self.open()
        rx, ry = centre(self.s, "launcherRow:3")
        QTest.mouseMove(self.s.view, QPoint(int(rx), int(ry)))
        self.s.wait(80)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0, "a first event under the pointer took the selection")
        QTest.mouseMove(self.s.view, QPoint(int(rx) + 20, int(ry) + 3))
        self.s.wait(80)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 3)
        self.s.key(Qt.Key_Up)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 2, "the keys didn't take over again")

    def test_clicking_a_row_launches_it(self):
        self.open()
        x, y = centre(self.s, "launcherRow:1")
        click(self.s, x, y)
        self.s.wait(300)
        self.assertEqual(len([e for e in self.s.bridge.exec_log if "dxrice_launch.sh" in e[0]]), 1)

    def test_rapid_toggling_ends_where_the_last_press_says(self):
        for _ in range(7):
            self.s.ev(f"{self.L}.toggle()")
            self.s.wait(35)
        self.s.wait(900)
        self.assertTrue(self.s.ev(f"{self.L}.open"))
        self.assertEqual(self.s.ev(f"{self.L}.progress"), 1)
        self.s.ev(f"{self.L}.toggle()")
        self.s.wait(600)
        self.assertEqual((self.s.ev(f"{self.L}.open"), self.s.ev(f"{self.L}.progress")), (False, 0))

    def test_html_in_an_app_name_is_shown_as_text(self):
        self.open()
        self.type("fire alarm")
        self.assertEqual(self.names()[0], "Fire Alarm <b>")
        self.assertIn("&lt;b>", self.s.ev("findNamed('launcherRow:0').children[1].children[0].text"))

    def test_the_panel_rises_while_it_fades_in(self):
        self.s.ev(f"{self.L}.show()")
        self.s.wait(40)
        mid = self.s.ev(f"{self.L}.progress")
        o_mid = self.s.ev("findNamed('launcherPanel').opacity")
        self.s.wait(700)
        self.assertTrue(0 < mid < 1, mid)
        self.assertAlmostEqual(o_mid, mid, delta=0.01)
        self.assertEqual(self.s.ev("findNamed('launcherPanel').opacity"), 1)

    def test_while_closed_no_input_is_taken(self):
        self.open()
        self.assertGreater(self.s.ev(f"{self.L}.mask.width"), 0)
        self.s.ev(f"{self.L}.hide()")
        self.assertEqual(self.s.ev(f"{self.L}.mask.width"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
