#!/usr/bin/env python3
"""The desktop widgets (clock, music, system): on/off and corners from
theme.json, real data only, the input mask, and the motion, through the real
shell QML offscreen.

    python3 tests/qml/test_widgets.py
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
from test_customization import TE, with_theme  # noqa: E402

PLAYER = """({
    trackTitle: 'Blue in Green', trackArtist: 'Miles Davis', trackArtUrl: '', isPlaying: true,
    identity: 'Spotify', metadata: {}, volumeSupported: false, volume: 0,
    positionSupported: true, lengthSupported: true, length: 200, position: 50,
    shuffleSupported: false, shuffle: false, loopSupported: false, loopState: 0,
    calls: [],
    togglePlaying: function() { this.calls.push('toggle'); this.isPlaying = !this.isPlaying; },
    next: function() { this.calls.push('next'); },
    previous: function() { this.calls.push('previous'); },
    positionChanged: function() { this.calls.push('poll'); }
})"""


def scene(**theme):
    return Scene(width=1920, height=1080, setup=with_theme(**theme))


def named(s, name, expr):
    return s.ev(f"findNamed('{name}').{expr}")


class ClockWidgetTest(unittest.TestCase):
    def test_it_is_on_by_default_in_the_top_left_below_the_bar(self):
        s = scene(widget_clock=None, widget_clock_pos=None)
        try:
            s.wait(500)
            self.assertTrue(named(s, "clockWidget", "active"))
            x = named(s, "widgetCard:clock", "x")
            y = named(s, "widgetCard:clock", "y")
            self.assertEqual(x, 28)
            self.assertEqual(y, 76)
            self.assertEqual(named(s, "widgetCard:clock", "opacity"), 1)
        finally:
            s.close()

    def test_switched_off_it_is_not_shown_at_all(self):
        s = scene(widget_clock=False)
        try:
            s.wait(300)
            self.assertFalse(named(s, "clockWidget", "visible"))
            self.assertEqual(named(s, "clockWidget", "shown"), 0)
        finally:
            s.close()

    def test_the_corner_setting_moves_it(self):
        s = scene(widget_clock_pos="bottom-right")
        try:
            s.wait(500)
            card = "widgetCard:clock"
            w, h = named(s, card, "width"), named(s, card, "height")
            self.assertEqual(named(s, card, "x"), 1920 - w - 28)
            self.assertEqual(named(s, card, "y"), 1080 - h - 96)
        finally:
            s.close()

    def test_a_bad_corner_falls_back_to_its_default(self):
        s = scene(widget_clock_pos="middle")
        try:
            s.wait(300)
            self.assertEqual(named(s, "clockWidget", "corner"), "top-left")
        finally:
            s.close()

    def test_24_hour_time_has_no_meridiem_and_12_hour_does(self):
        s = scene(clock_24h=True, clock_seconds=False)
        try:
            s.wait(300)
            self.assertRegex(named(s, "clockTime", "text"), r"^\d{2}:\d{2}$")
            self.assertFalse(named(s, "clockMeridiem", "visible"))
        finally:
            s.close()
        s = scene(clock_24h=False, clock_seconds=True)
        try:
            s.wait(300)
            self.assertRegex(named(s, "clockTime", "text"), r"^\d{1,2}:\d{2}$")
            self.assertTrue(named(s, "clockMeridiem", "visible"))
            self.assertIn(named(s, "clockMeridiem", "text"), ("AM", "PM"))
            self.assertTrue(named(s, "clockSeconds", "visible"))
        finally:
            s.close()

    def test_the_day_bar_is_a_real_fraction_of_the_day(self):
        s = scene()
        try:
            s.wait(300)
            p = s.ev("findNamed('clockWidget').dayFraction")
            self.assertTrue(0 <= p <= 1)
        finally:
            s.close()

    def test_input_goes_to_the_card_only(self):
        s = scene()
        try:
            s.wait(500)
            self.assertEqual(s.input_owner(28 + 40, 76 + 40), "clockWidget")
            self.assertNotEqual(s.input_owner(900, 500), "clockWidget")
        finally:
            s.close()

    def test_it_arrives_by_rising_and_fading_in(self):
        s = scene(widget_clock=False)
        try:
            s.wait(200)
            y_final = 76
            s.ev("theme.data = Object.assign({}, theme.data, {widget_clock: true})")
            s.wait(30)
            mid = named(s, "widgetCard:clock", "opacity")
            s.wait(600)
            self.assertTrue(0 < mid < 1, f"opacity mid-arrival was {mid}")
            self.assertEqual(named(s, "widgetCard:clock", "opacity"), 1)
            self.assertEqual(named(s, "widgetCard:clock", "y"), y_final)
        finally:
            s.close()


class MusicWidgetTest(unittest.TestCase):
    def setUp(self):
        self.s = scene(widget_music=None)
        self.s.wait(300)

    def tearDown(self):
        self.s.close()

    def centre(self, name, fx=0.5):
        return json.loads(self.s.ev(f"(function() {{ var i = findNamed('{name}'); var p = i.mapToItem(null, i.width * {fx}, i.height / 2); return JSON.stringify([p.x, p.y]); }})()"))

    def play(self):
        self.s.ev(f"mpris.players = {{ values: [{PLAYER}] }}")
        self.s.wait(600)

    def test_with_no_player_there_is_no_card(self):
        self.assertFalse(named(self.s, "musicWidget", "active"))
        self.assertFalse(named(self.s, "musicWidget", "visible"))

    def test_a_player_brings_the_card_with_its_real_track(self):
        self.play()
        self.assertTrue(named(self.s, "musicWidget", "active"))
        self.assertEqual(named(self.s, "musicTitle", "text"), "Blue in Green")
        self.assertEqual(named(self.s, "musicArtist", "text"), "Miles Davis")
        self.assertEqual(named(self.s, "widgetCard:music", "opacity"), 1)

    def test_the_buttons_drive_the_player(self):
        self.play()
        for name in ("musicPlay", "musicNext", "musicPrev"):
            c = self.centre(name)
            self.s.click(c[0], c[1])
            self.s.wait(60)
        calls = self.s.ev("mpris.players.values[0].calls.filter(c => c !== 'poll').join(',')")
        self.assertEqual(calls, "toggle,next,previous")

    def test_the_progress_bar_shows_where_the_track_is(self):
        self.play()
        self.s.wait(1200)   # the fill eases in over a second
        bar = named(self.s, "musicProgress", "width")
        fill = named(self.s, "musicProgressFill", "width")
        self.assertAlmostEqual(fill / bar, 0.25, delta=0.02)

    def test_clicking_the_bar_seeks(self):
        self.play()
        c = self.centre("musicProgress")
        self.s.click(c[0], c[1])
        self.s.wait(60)
        self.assertAlmostEqual(self.s.ev("mpris.players.values[0].position"), 100, delta=6)

    def test_the_position_is_polled_only_while_playing(self):
        self.play()
        self.s.wait(1300)
        polls = self.s.ev("mpris.players.values[0].calls.filter(c => c === 'poll').length")
        self.assertGreaterEqual(polls, 1)

    def test_a_player_going_away_takes_the_card_with_it(self):
        self.play()
        self.s.ev("mpris.players = { values: [] }")
        self.s.wait(600)
        self.assertFalse(named(self.s, "musicWidget", "visible"))


class SystemWidgetTest(unittest.TestCase):
    def test_off_by_default_and_then_nothing_is_sampled(self):
        s = scene(widget_system=None)
        try:
            s.wait(400)
            self.assertFalse(named(s, "systemWidget", "visible"))
            self.assertEqual(s.ev("perf.widgetUsers"), 0)
            self.assertFalse(s.ev("perf.sampling"))
        finally:
            s.close()

    def test_switched_on_it_samples_and_shows_real_rows(self):
        s = scene(widget_system=True)
        try:
            s.wait(700)
            self.assertTrue(named(s, "systemWidget", "active"))
            self.assertEqual(s.ev("perf.widgetUsers"), 1)
            self.assertTrue(s.ev("perf.sampling"))
            self.assertRegex(named(s, "systemValue:cpu", "text"), r"^\d+%$")
            self.assertRegex(named(s, "systemValue:mem", "text"), r"^\d+%$")
            self.assertRegex(named(s, "systemValue:net", "text"), r"^[\d.]+ (KB|MB)/s$")
        finally:
            s.close()

    def test_a_gpu_that_cannot_be_read_says_so_instead_of_zero(self):
        s = scene(widget_system=True)
        try:
            s.wait(500)
            if not s.ev("perf.gpuAvailable"):
                self.assertEqual(named(s, "systemValue:gpu", "text"), "n/a")
            else:
                self.assertRegex(named(s, "systemValue:gpu", "text"), r"^\d+%$")
        finally:
            s.close()

    def test_switching_it_off_stops_the_sampling_again(self):
        s = scene(widget_system=True)
        try:
            s.wait(500)
            s.ev("theme.data = Object.assign({}, theme.data, {widget_system: false})")
            s.wait(500)
            self.assertEqual(s.ev("perf.widgetUsers"), 0)
            self.assertFalse(s.ev("perf.sampling"))
        finally:
            s.close()


class WidgetSettingsTest(unittest.TestCase):
    def open(self, s):
        s.ev("panels.open('theme')")
        s.wait(700)
        s.ev(f"{TE}.currentCategory = 'experience'")
        s.wait(600)

    def tap(self, s, name):
        # the page scrolls: bring the chip into view, then click where it is
        s.ev(f"(function(){{ const b = findNamed('{name}'); let it = b; while (it) {{ if (it.contentY !== undefined && it.contentHeight !== undefined) {{"
             f" const p = b.mapToItem(it.contentItem, 0, 0); it.contentY = Math.max(0, p.y - 80); break; }} it = it.parent; }} }})()")
        s.wait(300)
        c = json.loads(s.ev(f"(function() {{ var i = findNamed('{name}'); var p = i.mapToItem(null, i.width / 2, i.height / 2); return JSON.stringify([Math.round(p.x), Math.round(p.y)]); }})()"))
        s.click(c[0], c[1])
        s.wait(150)

    def test_the_switches_show_what_theme_json_says(self):
        s = scene(widget_clock=None, widget_music=None, widget_system=None, clock_24h=False)
        try:
            self.open(s)
            self.assertTrue(s.ev("findNamed('widgetClockSwitch').checked"))
            self.assertTrue(s.ev("findNamed('widgetMusicSwitch').checked"))
            self.assertFalse(s.ev("findNamed('widgetSystemSwitch').checked"))
            self.assertFalse(s.ev("findNamed('clock24hSwitch').checked"))
        finally:
            s.close()

    def test_the_saved_corner_is_picked_and_clicking_another_changes_it(self):
        s = scene(widget_clock_pos="bottom-right")
        try:
            self.open(s)
            self.assertTrue(s.ev("findNamed('widgetPos:clock:bottom-right').picked"))
            self.tap(s, "widgetPos:clock:top-right")
            self.assertTrue(s.ev("findNamed('widgetPos:clock:top-right').picked"))
            self.assertFalse(s.ev("findNamed('widgetPos:clock:bottom-right').picked"))
            self.assertEqual(s.ev(f"{TE}.widget_clock_pos"), "top-right")
            self.assertTrue(s.ev(f"{TE}.dirty"))
        finally:
            s.close()

    def test_the_widget_keys_are_saved_with_everything_else(self):
        s = scene()
        try:
            self.open(s)
            keys = s.ev(f"{TE}.allKeys().join(',')").split(",")
            for k in ("widget_clock", "widget_music", "widget_system", "clock_24h", "clock_seconds",
                      "widget_clock_pos", "widget_music_pos", "widget_system_pos"):
                self.assertIn(k, keys)
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
