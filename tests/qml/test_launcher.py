#!/usr/bin/env python3
"""Applications (SUPER+R, the bar's search pill): ranking, keys, launching,
closing and its motion, through the real shell QML offscreen.

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
    {"name": "Firefox", "cmd": "firefox", "icon": "firefox", "uses": 40, "last": 1700000500},
    {"name": "Files", "cmd": "nautilus", "icon": "", "uses": 3, "last": 1700000100},
    {"name": "Visual Studio Code", "cmd": "code", "icon": "", "uses": 12, "last": 1700000900},
    {"name": "Kitty", "cmd": "kitty", "icon": "", "uses": 90, "last": 1700000300},
    {"name": "GNU Image Manipulation Program", "cmd": "gimp", "icon": "", "uses": 0},
    {"name": "Discord", "cmd": "/usr/bin/discord --ozone-platform=wayland", "icon": "", "uses": 20, "last": 1700000700},
    {"name": "Fire Alarm <b>", "cmd": "alarm", "icon": "", "uses": 0},
    {"name": "Steam", "cmd": "steam", "icon": "", "uses": 5, "last": 1700000200},
    {"name": "Settings", "cmd": "gnome-control-center", "icon": "", "uses": 0},
    {"name": "Terminal Emulator", "cmd": "xterm", "icon": "", "uses": 1, "last": 1700000050},
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
    """A click as the compositor would route it."""
    s.click(int(x), int(y))


def centre(s, name):
    return s.ev(f"(function(){{ const b = findNamed('{name}'); const p = b.mapToItem(null, b.width/2, b.height/2); return [p.x, p.y]; }})()").toVariant()


class LauncherTest(unittest.TestCase):
    """SUPER+R and the bar's search pill open Applications, the panel that
    hangs from the bar's left section, with its search field ready. (It
    replaced a separate full-screen launcher overlay; these are that
    launcher's tests, kept to the same intent.)"""

    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.set_command("dxrice_list_desktop_apps.py", json.dumps(APPS))
        self.L = "findNamed('appsPanel')"

    def tearDown(self):
        self.s.close()

    def open(self):
        self.s.ev("panels.toggle('apps')")
        self.s.wait(900)

    def is_open(self):
        return self.s.ev("panels.current") == "apps"

    def type(self, text):
        self.s.ev(f"{self.L}.query = {json.dumps(text)}")
        self.s.wait(120)

    def names(self):
        return json.loads(self.s.ev(f"JSON.stringify({self.L}.results.map(r => r.app.name))"))

    def test_toggle_opens_and_closes_and_nothing_is_built_while_closed(self):
        self.assertIsNone(self.s.ev(self.L))
        self.open()
        self.assertTrue(self.is_open())
        self.assertEqual(self.s.ev("findNamed('activityIsland').morph"), 1)
        self.s.ev("panels.toggle('apps')")
        self.s.wait(900)
        self.assertFalse(self.is_open())
        self.assertIsNone(self.s.ev(self.L), "the closed panel was not torn down")

    def test_the_ipc_keybind_opens_it_with_the_keyboard(self):
        self.s.ev("findNamed('appsSearch')")            # nothing yet
        self.s.ev("panels.toggle('apps')")             # what `ipc call launcher toggle` runs
        self.s.wait(900)
        self.assertTrue(self.s.ev("findNamed('statusIsland').parent.takesKeys"))
        self.assertTrue(self.s.ev("findNamed('appsSearch').activeFocus"))

    def test_it_opens_with_the_most_recent_and_loads_the_list_once_per_open(self):
        self.open()
        # newest launch first, whatever the counts (Kitty is the most used)
        self.assertEqual(self.names(), ["Visual Studio Code", "Discord", "Firefox", "Kitty", "Steam"])
        self.assertEqual(self.s.ev("findNamed('appsPanel').recent.length"), 5)
        self.assertEqual(len([r for r in self.s.bridge.run_log if "dxrice_list_desktop_apps.py" in " ".join(r)]), 1)

    def test_with_no_launch_history_nothing_typed_lists_no_alphabet(self):
        # (live, before any launch from here: "Most used" was the first five
        # installed apps by name -- Advanced Network Configuration, Avahi...)
        self.s.set_command("dxrice_list_desktop_apps.py", json.dumps([dict(a, uses=0, last=0) for a in APPS]))
        self.open()
        self.assertEqual(self.names(), [])
        self.assertEqual(self.s.ev("findNamed('appsEmpty').text"), "Type to search every installed app")
        self.type("firef")
        self.assertEqual(self.names(), ["Firefox"])

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
        self.s.key(Qt.Key_N, Qt.ControlModifier)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0)

    def test_the_highlight_glides_to_the_selected_row(self):
        self.open()
        y0 = self.s.ev("findNamed('appsHighlight').y")
        self.s.key(Qt.Key_Down)
        self.s.key(Qt.Key_Down)
        self.s.wait(15)
        mid = self.s.ev("findNamed('appsHighlight').y")
        self.s.wait(500)
        y1 = self.s.ev("findNamed('appsHighlight').y")
        self.assertAlmostEqual(y1 - y0, 2 * self.s.ev("findNamed('appsList').rowH"), delta=1)
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
        self.assertFalse(self.is_open(), "it should close after launching")

    def test_nothing_matching_says_so_and_enter_does_nothing(self):
        self.open()
        self.type("zzzzqq")
        self.assertTrue(self.s.ev("findNamed('appsEmpty').visible"))
        self.assertIn("Nothing matches", self.s.ev("findNamed('appsEmpty').text"))
        self.s.key(Qt.Key_Return)
        self.s.wait(200)
        self.assertEqual([e for e in self.s.bridge.exec_log if "dxrice_launch.sh" in e[0]], [])
        self.assertTrue(self.is_open())

    def test_escape_closes_and_a_reopen_starts_clean(self):
        self.open()
        self.type("fi")
        self.s.key(Qt.Key_Escape)
        self.s.wait(150)
        self.assertFalse(self.is_open())
        self.open()                                    # quick: the panel may still be alive
        self.assertEqual(self.s.ev(f"{self.L}.query"), "")
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0)

    def test_a_click_outside_closes_and_a_click_inside_does_not(self):
        self.open()
        px, py = centre(self.s, "appsSearch")
        click(self.s, px, py)
        self.s.wait(300)
        self.assertTrue(self.is_open())
        click(self.s, 1500, 700)
        self.s.wait(500)
        self.assertFalse(self.is_open())

    def test_a_resting_pointer_never_takes_the_selection(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        self.open()
        rx, ry = centre(self.s, "appsRow:3")
        QTest.mouseMove(self.s.view, QPoint(int(rx), int(ry)))
        QTest.mouseMove(self.s.view, QPoint(int(rx) + 20, int(ry) + 3))
        self.s.wait(80)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 0, "hovering a row took the selection from the keys")
        self.s.key(Qt.Key_Down)
        self.assertEqual(self.s.ev(f"{self.L}.selected"), 1)

    def test_clicking_a_row_launches_it(self):
        self.open()
        x, y = centre(self.s, "appsRow:1")
        click(self.s, x, y)
        self.s.wait(300)
        self.assertEqual(len([e for e in self.s.bridge.exec_log if "dxrice_launch.sh" in e[0]]), 1)

    def test_rapid_toggling_ends_where_the_last_press_says(self):
        for _ in range(7):
            self.s.ev("panels.toggle('apps')")
            self.s.wait(35)
        self.s.wait(900)
        self.assertTrue(self.is_open())
        self.assertEqual(self.s.ev("findNamed('activityIsland').morph"), 1)
        self.s.ev("panels.toggle('apps')")
        self.s.wait(900)
        self.assertEqual((self.is_open(), self.s.ev("findNamed('activityIsland').morph")), (False, 0))

    def test_html_in_an_app_name_is_shown_as_text(self):
        self.open()
        self.type("fire alarm")
        self.assertEqual(self.names()[0], "Fire Alarm <b>")
        self.assertIn("&lt;b>", self.s.ev("findNamed('appsRow:0').children[2].text"))

    def test_it_drops_out_of_the_bar_while_it_fades_in(self):
        self.s.ev("panels.toggle('apps')")
        self.s.wait(60)
        body = self.s.ev("findNamed('activityIslandBody').height")
        self.s.wait(900)
        self.assertGreater(body, 0)
        self.assertLess(body, self.s.ev("findNamed('activityIslandBody').height"))

    def test_while_closed_no_input_is_taken(self):
        rects = lambda: [r for r in self.s.surface_rects().toVariant() if r["surface"] == "TopBar" and r["w"] > 0 and r["h"] > 0]
        self.open()
        self.assertTrue(any(r["h"] > 400 for r in rects()))
        self.s.ev("panels.closeCurrent()")
        self.s.wait(50)
        self.assertEqual([r for r in rects() if r["h"] > 100], [], "input outlived the close")


if __name__ == "__main__":
    unittest.main(verbosity=1)
