#!/usr/bin/env python3
"""The widget library's newer pieces, through the real shell QML offscreen:
widgets sharing a corner stack instead of overlapping; the shaped meters
(real samples, only while shown); reminders kept on this machine, shared by
the calendar's agenda and the desktop widget; the analog clock's numerals;
the weather tile; stopwatch laps.

    python3 tests/qml/test_widget_library.py
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


def scene(**theme):
    return Scene(width=1920, height=1080, setup=with_theme(**theme))


def rect(s, name):
    return json.loads(s.ev(f"(function(){{ const c = findNamed('widgetCard:{name}'); const p = c.mapToItem(null, 0, 0);"
                           " return JSON.stringify([p.x, p.y, c.width, c.height]); })()"))


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class StackingTest(unittest.TestCase):
    def test_widgets_in_one_corner_stack_instead_of_overlapping(self):
        s = scene(widget_system=True, widget_system_pos="top-right", widget_cpu=True, widget_cpu_pos="top-right",
                  widget_memory=True, widget_memory_pos="top-right")
        try:
            s.wait(900)
            rs = [rect(s, n) for n in ("system", "cpu", "memory")]
            for i in range(3):
                for j in range(i + 1, 3):
                    self.assertFalse(overlap(rs[i], rs[j]), f"{rs[i]} overlaps {rs[j]}")
            # in declaration order, downward from the top corner
            self.assertLess(rs[0][1], rs[1][1])
            self.assertLess(rs[1][1], rs[2][1])
            # one switched off: the next moves up into its place
            s.ev("theme.data = Object.assign({}, theme.data, { widget_system: false })")
            s.wait(900)
            self.assertEqual(rect(s, "cpu")[1], rs[0][1])
        finally:
            s.close()

    def test_bottom_corners_stack_upward_and_sit_by_the_screen_edge(self):
        # (no dock any more: the bottom margin is the screen edge's)
        s = scene(widget_music=True, widget_music_pos="bottom-left", widget_timer=True, widget_timer_pos="bottom-left")
        try:
            s.wait(900)
            music, timer = rect(s, "music"), rect(s, "timer")
            self.assertFalse(overlap(music, timer))
            self.assertEqual(music[1] + music[3], 1080 - 28, "the first is at the bottom edge")
            self.assertLess(timer[1] + timer[3], music[1], "the second sits above it")
        finally:
            s.close()


class MeterTest(unittest.TestCase):
    def test_meters_show_real_samples_and_only_sample_while_shown(self):
        s = scene(widget_cpu=False, widget_memory=False, widget_disk=False, widget_system=False)
        try:
            s.wait(400)
            self.assertEqual(s.ev("perf.widgetUsers"), 0)
            s.ev("theme.data = Object.assign({}, theme.data, { widget_memory: true, widget_disk: true })")
            s.wait(2200)
            self.assertEqual(s.ev("perf.widgetUsers"), 2)
            mem = s.ev("perf.memPercent")
            self.assertEqual(s.ev("findNamed('meterValue:memory').text"), f"{round(mem)}%")
            self.assertAlmostEqual(s.ev("findNamed('memoryWidget').level"), mem / 100, delta=0.02)
            s.ev("theme.data = Object.assign({}, theme.data, { widget_memory: false, widget_disk: false })")
            s.wait(500)
            self.assertEqual(s.ev("perf.widgetUsers"), 0, "still sampling after the meters went away")
        finally:
            s.close()


class RemindersTest(unittest.TestCase):
    def setUp(self):
        self.s = scene(widget_reminders=True)
        self.s.wait(700)

    def tearDown(self):
        self.s.close()

    def stored(self):
        p = Path(self.s.bridge.config_home) / "dxrice" / "reminders.json"
        return json.loads(p.read_text())["items"] if p.exists() else []

    def centre(self, name):
        return json.loads(self.s.ev(f"(function(){{ const b = findNamed('{name}'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))

    def test_the_calendar_agenda_adds_and_removes_and_the_widget_follows(self):
        self.s.ev("panels.open('calendar', 'click')")
        self.s.wait(900)
        self.assertIn("Nothing on this day", self.s.ev("findPanel('viewDate').children[0].children.filter(c => c.text !== undefined && String(c.text).indexOf('Nothing') === 0).map(c => c.text).join('')"))
        self.s.ev("findNamed('agendaInput').text = 'Dentist at 4'")
        self.s.click(*self.centre("agendaAdd"))
        self.s.wait(200)
        items = self.stored()
        self.assertEqual([(i["text"], i["kind"]) for i in items], [("Dentist at 4", "reminder")])
        # the day gets its dot, the agenda its line, the desktop widget its line
        self.assertIsNotNone(self.s.ev(f"findNamed('agendaItem:{items[0]['id']}')"))
        self.assertIsNotNone(self.s.ev(f"findNamed('reminderLine:{items[0]['id']}')"))
        self.s.click(*self.centre(f"agendaRemove:{items[0]['id']}"))
        self.s.wait(200)
        self.assertEqual(self.stored(), [])
        self.assertIsNone(self.s.ev(f"findNamed('reminderLine:{items[0]['id']}')"))

    def test_a_reminder_for_another_day_and_kind(self):
        self.s.ev("panels.open('calendar', 'click')")
        self.s.wait(900)
        self.s.ev("findNamed('calendarPanel').select(new Date(2031, 0, 15))")
        self.s.click(*self.centre("agendaKind:birthday"))
        self.s.ev("findNamed('agendaInput').text = 'Sam'")
        self.s.ev("findNamed('agendaInput').accepted()")
        self.s.wait(200)
        self.assertEqual([(i["date"], i["text"], i["kind"]) for i in self.stored()], [("2031-01-15", "Sam", "birthday")])

    def test_the_widget_adds_one_for_today(self):
        self.s.ev("findNamed('remindersInput').text = 'Water the plants'")
        self.s.ev("findNamed('remindersInput').accepted()")
        self.s.wait(200)
        items = self.stored()
        self.assertEqual(len(items), 1)
        today = self.s.ev("(function(){ const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'); })()")
        self.assertEqual(items[0]["date"], today)

    def test_a_broken_file_reads_as_no_reminders_not_an_error(self):
        p = Path(self.s.bridge.config_home) / "dxrice" / "reminders.json"
        p.write_text("{ not json")
        self.s.ev("panels.open('calendar', 'click')")
        self.s.wait(600)
        self.assertEqual(self.s.ev("findNamed('calendarPanel') !== null"), True)


class SmallerPiecesTest(unittest.TestCase):
    def test_the_analog_face_has_numerals_unless_asked_for_ticks(self):
        s = scene(clock_style="analog")
        try:
            s.wait(600)
            self.assertIsNotNone(s.ev("findNamed('clockNumeral:12')"))
            s.ev("theme.data = Object.assign({}, theme.data, { clock_face: 'ticks' })")
            s.wait(300)
            self.assertIsNone(s.ev("findNamed('clockNumeral:12')"))
        finally:
            s.close()

    def test_the_stacked_clock_puts_hours_over_minutes_with_a_minute_hand(self):
        s = scene(clock_style="stacked")
        try:
            s.wait(600)
            self.assertTrue(s.ev("findNamed('clockStackedFace').visible"))
            self.assertFalse(s.ev("findNamed('clockTypeFace').visible"))
            s.ev("findNamed('clockWidget').now = new Date(2026, 9, 21, 8, 1, 0)")
            s.wait(500)
            self.assertEqual(s.ev("findNamed('clockStackedHours').text"), "08")
            self.assertEqual(s.ev("findNamed('clockStackedMinutes').text"), "01")
            self.assertLess(s.ev("findNamed('clockStackedHours').mapToItem(null, 0, 0).y"),
                            s.ev("findNamed('clockStackedMinutes').mapToItem(null, 0, 0).y"))
            self.assertAlmostEqual(s.ev("findNamed('clockStackedHand').rotation") % 360, 6, delta=0.5)
        finally:
            s.close()

    def test_the_weather_tile_is_compact_and_still_honest(self):
        s = scene(widget_weather=True, weather_style="tile")
        try:
            s.wait(600)
            self.assertTrue(s.ev("findNamed('weatherTile').visible"))
            self.assertLess(rect(s, "weather")[2], 230)
            # no place set: no number is made up
            self.assertEqual(s.ev("findNamed('weatherTileTemp').text"), "—")
        finally:
            s.close()

    def test_the_stopwatch_keeps_laps(self):
        s = scene(widget_timer=True)
        try:
            s.wait(500)
            T = "findNamed('timerWidget')"
            s.ev(f"{T}.start()")
            s.wait(300)
            s.ev(f"{T}.lap()")
            s.wait(300)
            s.ev(f"{T}.lap()")
            self.assertEqual(s.ev(f"{T}.laps.length"), 2)
            self.assertGreater(s.ev(f"{T}.laps[0]"), s.ev(f"{T}.laps[1]"), "newest first")
            self.assertIsNotNone(s.ev("findNamed('timerLapRow:1')"))
            s.ev(f"{T}.pause()")
            s.ev(f"{T}.reset()")
            self.assertEqual(s.ev(f"{T}.laps.length"), 0)
        finally:
            s.close()


class ReadableAccentTest(unittest.TestCase):
    def luma(self, s, expr):
        return s.ev(f"theme.luma({expr})")

    def test_a_dark_accent_is_lifted_for_text_and_a_light_one_kept(self):
        # (seen live: a deep blue accent, #0707ea, made matched letters and
        # small captions all but disappear on the dark panel)
        s = scene(accent="0707ea")
        try:
            s.wait(300)
            self.assertGreaterEqual(self.luma(s, "theme.accentText"), 0.49)
            self.assertLess(self.luma(s, "theme.accent"), 0.2)
            self.assertGreater(s.ev("theme.accentText.b"), s.ev("theme.accentText.r"), "it stays recognisably the accent")
        finally:
            s.close()
        s = scene(accent="f0c060")
        try:
            s.wait(300)
            self.assertEqual(s.ev("theme.accentText.toString()"), s.ev("theme.accent.toString()"))
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
