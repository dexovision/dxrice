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
        self.assertFalse(self.s.ev("findNamed('statusIsland').parent.focusable"))
        x, y = self.centre("audio")
        self.s.click(x, y)
        self.s.wait(100)
        self.assertEqual(self.current(), "status:audio", "a click on a hover-opened panel keeps it")
        self.assertEqual(self.s.ev("panels.openedBy"), "click")
        self.assertTrue(self.s.ev("findNamed('statusIsland').parent.focusable"))
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

    def test_the_dashboard_indicator_opens_the_full_dashboard(self):
        x, y = self.centre("dashboard")
        self.s.click(x, y)
        self.s.wait(900)
        self.assertEqual(self.current(), "quicksettings")
        self.assertIsNotNone(self.s.ev("findPanel('currentTab')"))


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


if __name__ == "__main__":
    unittest.main()
