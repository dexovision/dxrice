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

    def test_every_indicator_opens_its_own_section_on_a_pause(self):
        # (the recording card's branch, laid over the capture mark, once took
        # its hover: capture never opened by hovering)
        for name in ("capture", "performance", "network", "bluetooth", "audio", "power", "notifications"):
            self.s.ev("panels.closeCurrent()")
            self.away()
            self.s.wait(500)
            x, y = self.centre(name)
            QTest.mouseMove(self.s.view, QPoint(x, 70))
            self.s.wait(30)
            self.hover(name)
            self.s.wait(500)
            self.assertEqual(self.current(), "status:" + name, f"hovering {name} opened nothing")

    def test_clicking_the_neighbour_the_panel_just_turned_into_keeps_it(self):
        # (moving onto the Dashboard mark with a section open switched to the
        # Dashboard; the click that followed then closed it)
        x, y = self.centre("audio")
        self.s.click(x, y)
        self.s.wait(400)
        self.hover("dashboard")
        self.s.wait(200)
        self.assertEqual(self.current(), "quicksettings")
        self.s.click(*self.centre("dashboard"))
        self.s.wait(100)
        self.assertEqual(self.current(), "quicksettings", "the click closed the panel it had just switched to")
        # a later click still closes it
        self.s.wait(1600)
        self.s.click(*self.centre("dashboard"))
        self.s.wait(100)
        self.assertEqual(self.current(), "")

    def test_sweeping_along_the_indicators_does_not_flick_through_each(self):
        x, y = self.centre("network")
        self.s.click(x, y)
        self.s.wait(400)
        seen = []
        for name in ("bluetooth", "audio", "power"):
            self.hover(name)
            for _ in range(3):
                self.s.wait(10)
                if self.current() not in seen:
                    seen.append(self.current())
        self.s.wait(300)
        self.assertEqual(self.current(), "status:power")
        self.assertNotIn("status:bluetooth", seen, "it switched to a section the pointer only passed over")
        self.assertNotIn("status:audio", seen)

    def test_leaving_closes_a_hover_opened_panel(self):
        self.hover("power")
        self.s.wait(400)
        self.assertEqual(self.current(), "status:power")
        self.away()
        self.s.wait(150)
        self.assertEqual(self.current(), "status:power", "closed without a grace period")
        self.s.wait(400)
        self.assertEqual(self.current(), "")

    def leave_along_the_bar_across(self, start, section):
        x, y = self.centre(start)
        QTest.mouseMove(self.s.view, QPoint(x, 70))
        self.s.wait(20)
        self.hover(start)
        self.s.wait(450)
        self.assertEqual(self.current(), "status:" + start if start != "clockIsland" else "calendar")
        cx, _ = json.loads(self.s.ev(f"(function(){{ const b = findNamed('{section}'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                     " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))
        for i in range(1, 21):
            QTest.mouseMove(self.s.view, QPoint(int(x + (cx - x) * i / 20), y))
            self.s.wait(8)
        QTest.mouseMove(self.s.view, QPoint(cx, 400))
        self.s.wait(10)
        self.away()

    def test_leaving_along_the_bar_across_another_section_still_closes(self):
        # (seen live: a panel stayed open after the pointer left it. The close
        # timer followed whichever section the pointer left last; crossing
        # the clock on the way out aimed it at the clock, which had nothing open)
        self.leave_along_the_bar_across("network", "clockIsland")
        self.s.wait(900)
        self.assertEqual(self.current(), "", "the panel stayed open after the pointer left across the clock")
        self.leave_along_the_bar_across("audio", "activityIsland")
        self.s.wait(900)
        self.assertEqual(self.current(), "", "the panel stayed open after the pointer left across the left section")

    def test_a_clicked_panel_stays_when_the_pointer_leaves(self):
        x, y = self.centre("network")
        self.s.click(x, y)
        self.s.wait(400)
        self.away()
        self.s.wait(900)
        self.assertEqual(self.current(), "status:network")

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

    def test_leaving_along_the_bar_across_another_section_still_closes(self):
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

    def test_every_indicator_opens_its_own_section_on_a_pause(self):
        self.skipTest("nothing opens on hover")


class PanTest(unittest.TestCase):
    """While the infinite desktop is panned (the pan daemon's flag,
    Viewport.panning) the bar steps aside -- slides up, fades, takes no input,
    closes its panel -- and comes back the moment the pan ends, or when the
    flag goes stale (a daemon killed mid-pan)."""

    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.wait(500)

    def tearDown(self):
        self.s.close()

    def bar(self):
        return json.loads(self.s.ev("(function(){ const b = findNamed('barStrip'); const p = b.mapToItem(null, 0, 0);"
                                    " let o = 1, it = b; while (it) { o *= it.opacity; it = it.parent; }"
                                    " return JSON.stringify([p.y, o]); })()"))

    def pan(self, on, age=0):
        self.s.ev(f"viewport._readPan('{'1' if on else '0'} ' + (Date.now() / 1000 - {age}))")

    def test_the_bar_steps_aside_during_a_pan_and_comes_back(self):
        y0, o0 = self.bar()
        self.s.ev("panels.open('status:network', 'hover')")
        self.s.wait(400)
        self.pan(True)
        self.s.wait(400)
        y1, o1 = self.bar()
        self.assertLess(o1, 0.05, "the bar is still showing during the pan")
        self.assertLess(y1, y0, "it should slide up out of the way")
        self.assertEqual(self.s.ev("panels.current"), "", "a panel stayed open during the pan")
        self.assertIsNone(self.s.input_owner(400, 25), "the hidden bar still takes the pointer")
        self.pan(False)
        self.s.wait(60)
        # sliding back: no input yet (a region built mid-slide would sit too high)
        self.assertIsNone(self.s.input_owner(400, 25))
        self.assertTrue(self.s.ev("findNamed('barStrip').parent.mask === findNamed('barStrip').parent._noInput"))
        self.s.wait(500)
        self.assertTrue(self.s.ev("findNamed('barStrip').parent.mask === findNamed('barStrip').parent._input"),
                        "the input region was not set again once the bar was back")
        y2, o2 = self.bar()
        self.assertAlmostEqual(o2, 1, delta=0.01)
        self.assertAlmostEqual(y2, y0, delta=0.5)
        self.assertEqual(self.s.input_owner(400, 25), "TopBar")

    def test_its_reserved_strip_stays_so_no_window_moves(self):
        zone = "findNamed('barStrip').parent.exclusiveZone"
        zone0 = self.s.ev(zone)
        self.assertGreater(zone0, 0)
        self.pan(True)
        self.s.wait(400)
        self.assertEqual(self.s.ev(zone), zone0)

    def test_a_stale_flag_brings_the_bar_back(self):
        # the daemon refreshes the flag every half second; one 3 s old means it died mid-pan
        self.pan(True, age=3)
        self.s.wait(600)
        self.assertGreater(self.bar()[1], 0.99, "a stale pan flag kept the bar away")
        self.pan(True)
        self.s.wait(400)
        self.assertLess(self.bar()[1], 0.05)
        self.s.wait(2600)          # no refresh comes
        self.assertGreater(self.bar()[1], 0.99, "the bar never came back after the flag went stale")


if __name__ == "__main__":
    unittest.main()
