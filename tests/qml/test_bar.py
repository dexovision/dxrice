#!/usr/bin/env python3
"""The top bar's right-hand island: one indicator per thing, each opening
its own section of one morphing panel -- on a click, or on hover with
intent: a pause opens it, passing over opens nothing, moving to a
neighbour switches without closing, leaving closes a hover-opened panel,
and hovering never takes the keyboard.

    python3 tests/qml/test_bar.py
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
from test_customization import with_theme  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

INDICATORS = ("network", "bluetooth", "audio", "power", "notifications", "dashboard")


class BarTest(unittest.TestCase):
    def setUp(self, **theme):
        self.s = Scene(width=1920, height=1080, setup=with_theme(**theme) if theme else None)
        self.s.wait(500)

    def tearDown(self):
        self.s.close()

    def centre(self, name):
        return json.loads(self.s.ev(f"(function(){{ const b = findNamed('barIndicator:{name}'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))

    def hover(self, name):
        x, y = self.centre(name)
        QTest.mouseMove(self.s.view, QPoint(x, y))
        self.s.wait(10)

    def away(self):
        QTest.mouseMove(self.s.view, QPoint(900, 700))
        self.s.wait(10)

    def current(self):
        return self.s.ev("panels.current")

    def test_one_indicator_per_thing(self):
        for name in INDICATORS:
            self.assertIsNotNone(self.s.ev(f"findNamed('barIndicator:{name}')"), name)

    def test_a_pause_opens_its_own_section_and_only_after_the_delay(self):
        self.hover("audio")
        self.s.wait(60)
        self.assertEqual(self.current(), "", "opened before the pause")
        self.s.wait(250)
        self.assertEqual(self.current(), "status:audio")
        self.assertEqual(self.s.ev("panels.openedBy"), "hover")
        self.s.wait(900)
        self.assertTrue(self.s.ev("findNamed('statusSection:audio').visible"))
        self.assertFalse(self.s.ev("findNamed('statusSection:network').visible"))

    def test_passing_over_the_bar_opens_nothing(self):
        for name in ("network", "bluetooth", "audio"):
            self.hover(name)
            self.s.wait(40)
        self.away()
        self.s.wait(400)
        self.assertEqual(self.current(), "")

    def test_moving_to_a_neighbour_switches_without_closing(self):
        self.hover("network")
        self.s.wait(400)
        self.assertEqual(self.current(), "status:network")
        seen = set()
        self.hover("bluetooth")
        for _ in range(10):
            self.s.wait(15)
            seen.add(self.current())
        self.assertEqual(self.current(), "status:bluetooth")
        self.assertNotIn("", seen, "the panel closed between neighbours")
        self.s.wait(900)
        self.assertTrue(self.s.ev("findNamed('statusSection:bluetooth').visible"))

    def test_leaving_closes_a_hover_opened_panel(self):
        self.hover("power")
        self.s.wait(400)
        self.assertEqual(self.current(), "status:power")
        self.away()
        self.s.wait(150)
        self.assertEqual(self.current(), "status:power", "closed without a grace period")
        self.s.wait(400)
        self.assertEqual(self.current(), "")

    def test_moving_into_the_panel_keeps_it_open(self):
        self.hover("network")
        self.s.wait(1200)
        x, y = json.loads(self.s.ev("(function(){ const s = findNamed('statusSection:network'); const p = s.mapToItem(null, s.width/2, s.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))
        QTest.mouseMove(self.s.view, QPoint(x, y))
        self.s.wait(700)
        self.assertEqual(self.current(), "status:network")

    def test_hover_never_takes_the_keyboard_but_a_click_may(self):
        self.hover("audio")
        self.s.wait(400)
        self.assertFalse(self.s.ev("findNamed('statusIsland').parent.takesKeys"))
        x, y = self.centre("audio")
        self.s.click(x, y)
        self.s.wait(100)
        self.assertEqual(self.current(), "status:audio", "a click on a hover-opened panel keeps it")
        self.assertEqual(self.s.ev("panels.openedBy"), "click")
        self.assertTrue(self.s.ev("findNamed('statusIsland').parent.takesKeys"))
        self.away()
        self.s.wait(700)
        self.assertEqual(self.current(), "status:audio", "a clicked panel stays when the pointer leaves")

    def test_the_clock_opens_the_calendar_on_a_pause(self):
        x, y = json.loads(self.s.ev("(function(){ const b = findNamed('clockIsland'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))
        QTest.mouseMove(self.s.view, QPoint(x, y))
        self.s.wait(60)
        self.assertEqual(self.current(), "")
        self.s.wait(300)
        self.assertEqual(self.current(), "calendar")
        self.away()
        self.s.wait(700)
        self.assertEqual(self.current(), "")

    def test_a_closed_panel_does_not_reopen_under_a_resting_pointer(self):
        # closed by a keybind (or Escape) with the pointer still resting on
        # the indicator that opened it
        x, y = self.centre("dashboard")
        QTest.mouseMove(self.s.view, QPoint(x, 300))
        self.s.wait(20)
        QTest.mouseMove(self.s.view, QPoint(x, y))
        self.s.wait(1200)
        self.assertEqual(self.current(), "quicksettings")
        self.s.ev("panels.closeCurrent()")
        self.s.wait(1200)
        self.assertEqual(self.current(), "", "reopened without the pointer moving")
        QTest.mouseMove(self.s.view, QPoint(x + 2, y))
        self.s.wait(400)
        self.assertEqual(self.current(), "quicksettings", "moving on the element it rests on opens it")

    def test_the_notifications_switch_is_on_when_notifications_show(self):
        x, y = self.centre("notifications")
        self.s.click(x, y)
        self.s.wait(900)
        sw = "findNamed('statusSection:notifications').children[0].children[2]"
        self.assertTrue(self.s.ev(f"{sw}.checked"), "mako is not in do-not-disturb, so the switch is on")
        self.s.ev(f"{sw}.toggled(false)")
        self.s.wait(50)
        self.assertIn(["makoctl", "mode", "-a", "dnd"], self.s.bridge.exec_log)
        self.assertFalse(self.s.ev(f"{sw}.checked"))

    def test_a_hover_opened_panel_gives_way_to_another_sections(self):
        self.hover("network")
        self.s.wait(400)
        self.assertEqual(self.current(), "status:network")
        x, y = json.loads(self.s.ev("(function(){ const b = findNamed('clockIsland'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))
        QTest.mouseMove(self.s.view, QPoint(x, y))
        self.s.wait(300)
        self.assertEqual(self.current(), "calendar", "the bar should branch from wherever the pointer settles")

    def test_a_clicked_panel_stays_while_the_pointer_visits_other_sections(self):
        x, y = self.centre("network")
        self.s.click(x, y)
        self.s.wait(300)
        cx, cy = json.loads(self.s.ev("(function(){ const b = findNamed('clockIsland'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                      " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))
        QTest.mouseMove(self.s.view, QPoint(cx, cy))
        self.s.wait(400)
        self.assertEqual(self.current(), "status:network")

    def test_the_dashboard_indicator_opens_the_full_dashboard(self):
        x, y = self.centre("dashboard")
        self.s.click(x, y)
        self.s.wait(900)
        self.assertEqual(self.current(), "quicksettings")
        self.assertIsNotNone(self.s.ev("findPanel('currentTab')"))


class BarAppsTest(unittest.TestCase):
    """The left island: the launcher and the saved shortcuts (the dock's
    list), launching through the same scope launcher."""

    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.wait(600)

    def tearDown(self):
        self.s.close()

    def centre(self, name):
        return json.loads(self.s.ev(f"(function(){{ const b = findNamed('{name}'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))

    def test_the_shortcuts_are_the_saved_list_minus_the_launcher_duplicate(self):
        # there is no dock any more: the bar is where the shortcuts live
        self.assertIsNone(self.s.ev("findNamed('dockIsland')"))
        labels = self.s.ev("JSON.stringify((function(){ const r = findNamed('barApps'); const out = [];"
                           " for (let i = 0; i < r.children.length; i++) { const c = r.children[i]; if (c.objectName.indexOf('barShortcut:') === 0) out.push(c.objectName.slice(12)); }"
                           " return out; })())")
        self.assertIn("Firefox", json.loads(labels))
        self.assertNotIn("App Launcher", json.loads(labels))
        self.assertIsNotNone(self.s.ev("findNamed('barLauncher')"))

    def test_a_shortcut_launches_through_the_scope_launcher(self):
        x, y = self.centre("barShortcut:Firefox")
        self.s.bridge.exec_log.clear()
        self.s.click(x, y)
        self.s.wait(50)
        self.assertEqual(self.s.bridge.exec_log, [[f"{self.s.shell}/../scripts/dxrice_launch.sh", "bar", "sh", "-c", "firefox"]])

    def test_the_search_pill_opens_applications_with_the_keyboard(self):
        x, y = self.centre("barLauncher")
        self.s.click(x, y)
        self.s.wait(900)
        self.assertEqual(self.s.ev("panels.current"), "apps")
        self.assertTrue(self.s.ev("findNamed('statusIsland').parent.takesKeys"))
        self.assertTrue(self.s.ev("findNamed('appsSearch').activeFocus"))

    def test_applications_pins_the_saved_shortcuts(self):
        self.s.ev("panels.open('apps', 'click')")
        self.s.wait(900)
        self.assertIsNotNone(self.s.ev("findNamed('appsPin:Firefox')"))
        x, y = self.centre("appsPin:Firefox")
        self.s.bridge.exec_log.clear()
        self.s.click(x, y)
        self.s.wait(100)
        self.assertEqual(self.s.bridge.exec_log, [[f"{self.s.shell}/../scripts/dxrice_launch.sh", "bar", "sh", "-c", "firefox"]])
        self.assertEqual(self.s.ev("panels.current"), "", "launching closes it")

    def test_applications_lists_open_windows_to_focus_or_close(self):
        self.s.ev("hypr.toplevels = ({ values: [{ address: '0xabc', title: 'Docs', lastIpcObject: { address: '0xabc', class: 'firefox', title: 'Docs', workspace: { id: 2 } } },"
                  " { address: '0xdef', lastIpcObject: { address: '0xdef', class: 'scratch', title: 'x', workspace: { id: -98 } } }] })")
        self.s.ev("panels.open('apps', 'click')")
        self.s.wait(900)
        self.assertIsNotNone(self.s.ev("findNamed('appsWindow:0xabc')"))
        self.assertIsNone(self.s.ev("findNamed('appsWindow:0xdef')"), "a special workspace's window is not listed")
        x, y = self.centre("appsWindowClose")
        self.s.click(x, y)
        self.s.wait(50)
        self.assertIn('hl.dsp.window.close({ window = "address:0xabc" })', json.loads(self.s.ev("JSON.stringify(hypr.dispatchLog)")))

    def test_the_shortcuts_tab_is_the_taskbar_editor(self):
        self.s.ev("panels.open('apps', 'click')")
        self.s.wait(900)
        x, y = self.centre("appsTab:taskbar")
        self.s.click(x, y)
        self.s.wait(900)
        self.assertEqual(self.s.ev("panels.current"), "taskbar")
        self.assertIsNotNone(self.s.ev("findNamed('appsPanel').manager"))
        self.assertTrue(self.s.ev("findNamed('statusIsland').parent.takesKeys"))

    def test_hovering_a_shortcut_names_it(self):
        x, y = self.centre("barShortcut:Firefox")
        QTest.mouseMove(self.s.view, QPoint(x - 6, y))     # arrive, as a pointer does
        QTest.mouseMove(self.s.view, QPoint(x, y))
        self.s.wait(80)
        self.assertEqual(self.s.ev("findNamed('barTitle').text"), "Firefox")
        QTest.mouseMove(self.s.view, QPoint(900, 700))
        self.s.wait(80)
        self.assertNotEqual(self.s.ev("findNamed('barTitle').text"), "Firefox")

    def test_an_open_app_is_marked_in_the_bar_too(self):
        mark = ("(function(){ const t = findNamed('barShortcut:Firefox'); for (let i = 0; i < t.children.length; i++)"
                " if (t.children[i].objectName === 'barRunning') return t.children[i]; return null; })()")
        self.assertEqual(self.s.ev(f"{mark}.opacity"), 0)
        self.s.ev("hypr.toplevels = ({ values: [{ address: '0x1', lastIpcObject: { class: 'firefox' } }] })")
        self.s.wait(400)
        self.assertGreater(self.s.ev(f"{mark}.opacity"), 0)


class NarrowBarTest(unittest.TestCase):
    def test_a_narrow_screen_keeps_just_the_launcher(self):
        s = Scene(width=800, height=600)
        try:
            s.wait(500)
            self.assertIsNotNone(s.ev("findNamed('barLauncher')"))
            self.assertIsNone(s.ev("findNamed('barShortcut:Firefox')"))
        finally:
            s.close()


class ClickOnlyTest(BarTest):
    def setUp(self):
        super().setUp(bar_hover_open=False)

    def test_a_pause_opens_its_own_section_and_only_after_the_delay(self):
        self.hover("audio")
        self.s.wait(500)
        self.assertEqual(self.current(), "", "hover opened a panel with bar_hover_open off")

    def test_moving_to_a_neighbour_switches_without_closing(self):
        x, y = self.centre("network")
        self.s.click(x, y)
        self.s.wait(300)
        self.hover("bluetooth")
        self.s.wait(100)
        self.assertEqual(self.current(), "status:bluetooth", "an open panel still follows the pointer along its island")

    def test_leaving_closes_a_hover_opened_panel(self):
        self.skipTest("nothing opens on hover")

    def test_moving_into_the_panel_keeps_it_open(self):
        self.skipTest("nothing opens on hover")

    def test_hover_never_takes_the_keyboard_but_a_click_may(self):
        self.skipTest("covered by the hover case")

    def test_passing_over_the_bar_opens_nothing(self):
        self.skipTest("covered above")

    def test_the_clock_opens_the_calendar_on_a_pause(self):
        self.skipTest("nothing opens on hover")

    def test_a_closed_panel_does_not_reopen_under_a_resting_pointer(self):
        self.skipTest("nothing opens on hover")

    def test_a_hover_opened_panel_gives_way_to_another_sections(self):
        self.skipTest("nothing opens on hover")


if __name__ == "__main__":
    unittest.main()
