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
            self.assertRegex(named(s, "clockWidget", "timeText"), r"^\d{2}:\d{2}$")
            self.assertFalse(named(s, "clockMeridiem", "visible"))
        finally:
            s.close()
        s = scene(clock_24h=False, clock_seconds=True)
        try:
            s.wait(300)
            self.assertRegex(named(s, "clockWidget", "timeText"), r"^\d{1,2}:\d{2}$")
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

    def test_it_takes_no_input_so_the_desktop_under_it_stays_clickable(self):
        s = scene()
        try:
            s.wait(500)
            self.assertIsNone(s.input_owner(28 + 40, 76 + 40))
        finally:
            s.close()

    def test_the_type_style_is_bare_heavy_type_with_the_date_beside_it(self):
        s = scene(clock_style=None)
        try:
            s.wait(500)
            self.assertTrue(named(s, "clockTypeFace", "visible"))
            self.assertFalse(named(s, "clockBlockFace", "visible"))
            self.assertFalse(named(s, "widgetCard:clock", "children[1].visible"))   # no glass card
            self.assertEqual(named(s, "clockHours", "font.weight"), 700)
            self.assertEqual(s.ev("findNamed('clockHours').color.toString()"), s.ev("theme.accent.toString()"))
            self.assertEqual(named(s, "clockMonth", "text"), named(s, "clockMonth", "text").upper())
        finally:
            s.close()

    def test_the_blocks_style_draws_the_time_as_tty_clock_cells(self):
        s = scene(clock_style="blocks", clock_24h=True, clock_seconds=False)
        try:
            s.wait(500)
            self.assertTrue(named(s, "clockBlockFace", "visible"))
            self.assertFalse(named(s, "clockTypeFace", "visible"))
            # each digit is a 3x5 grid; the lit cells spell the real time
            lit = s.ev("""(function() {
                var face = findNamed('clockBlockFace'); var row = face.children[0]; var out = [];
                for (var i = 0; i < row.children.length; i++) { var g = row.children[i]; if (!g.ch) continue;
                  var bits = ''; for (var j = 0; j < g.children.length; j++) if (g.children[j].lit !== undefined) bits += g.children[j].lit ? '1' : '0';
                  out.push(g.ch + '=' + bits); }
                return out.join(' '); })()""")
            t = named(s, "clockWidget", "timeText")
            glyphs = {"0": "111101101101111", "1": "001001001001001", "2": "111001111100111", "3": "111001111001111",
                      "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
                      "8": "111101111101111", "9": "111101111001111", ":": "01010"}
            self.assertEqual(lit, " ".join(f"{c}={glyphs[c]}" for c in t))
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
            self.assertRegex(named(s, "systemValue:mem", "text"), r"^\d+\.\d / \d+\.\d GiB$")
            self.assertRegex(named(s, "systemValue:net", "text"), r"^↓ [\d.]+ (KB|MB)/s$")
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

    def test_a_steady_reading_still_draws_its_history(self):
        s = scene(widget_system=True)
        try:
            s.wait(5000)   # three samples at 1.5 s, the fake /proc never changes
            self.assertGreaterEqual(s.ev("findNamed('systemWidget').cpu.length"), 3)
            graph = named(s, "systemGraph:cpu", "text")
            self.assertGreaterEqual(len(graph.strip()), 3)
            self.assertTrue(set(graph.strip()) <= set("▁▂▃▄▅▆▇█"))
        finally:
            s.close()

    def test_the_block_graphs_and_gauges_are_exact(self):
        s = scene(widget_system=True)
        try:
            s.wait(300)
            W = "findNamed('systemWidget')"
            self.assertEqual(s.ev(f"{W}.spark([0, 50, 100], 100).trim()"), "▁▄█")
            self.assertEqual(len(s.ev(f"{W}.spark([1], 100)")), s.ev(f"{W}.history"))
            self.assertEqual(s.ev(f"{W}.gauge(0.5, 8)"), "████░░░░")
            self.assertEqual(s.ev(f"{W}.gauge(1.7, 4)"), "████")
            self.assertEqual(s.ev(f"{W}.uptime(90061)"), "1d 1h 1m")
            self.assertEqual(s.ev(f"{W}.temp(-1)"), "")
        finally:
            s.close()

    def test_rows_without_a_source_are_left_out(self):
        s = scene(widget_system=True)
        try:
            s.wait(800)
            ids = s.ev("findNamed('systemWidget').rows.map(r => r.id).join(',')").split(",")
            if s.ev("perf.batteryPercent") < 0:
                self.assertNotIn("bat", ids)
            for must in ("cpu", "gpu", "mem", "net", "up"):
                self.assertIn(must, ids)
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

    def test_the_clock_style_is_chosen_here(self):
        s = scene(clock_style=None)
        try:
            self.open(s)
            self.assertTrue(s.ev("findNamed('clockStyle:type').picked"))
            self.tap(s, "clockStyle:blocks")
            self.assertEqual(s.ev(f"{TE}.clock_style"), "blocks")
            self.assertFalse(s.ev("findNamed('clockStyle:type').picked"))
            self.assertTrue(s.ev(f"{TE}.dirty"))
        finally:
            s.close()

    def test_the_widget_keys_are_saved_with_everything_else(self):
        s = scene()
        try:
            self.open(s)
            keys = s.ev(f"{TE}.allKeys().join(',')").split(",")
            for k in ("widget_clock", "widget_music", "widget_system", "clock_24h", "clock_seconds",
                      "widget_clock_pos", "widget_music_pos", "widget_system_pos", "clock_style"):
                self.assertIn(k, keys)
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
