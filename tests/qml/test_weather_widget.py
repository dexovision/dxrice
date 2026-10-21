#!/usr/bin/env python3
"""The weather widget: off until switched on, asks the script only while
shown, shows a real answer, says plainly when there is none, and marks an
old one. The script itself (and the network) is a fixture here.

    python3 tests/qml/test_weather_widget.py
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

ANSWER = {"place": "Austin, US", "temp": 21.5, "feels": 20.1, "humidity": 40, "wind": 11.0, "code": 2, "is_day": True,
          "units": "metric", "fetched": 1792540000, "stale": False,
          "days": [{"date": "2026-10-21", "max": 24, "min": 12, "code": 2},
                   {"date": "2026-10-22", "max": 25, "min": 14, "code": 3},
                   {"date": "2026-10-23", "max": 19, "min": 9, "code": 61}]}


def fetches(s):
    return [r for r in s.bridge.run_log if any("dxrice_weather.py" in a for a in r)]


class WeatherWidgetTest(unittest.TestCase):
    def scene(self, answer=ANSWER, **theme):
        themed = with_theme(**theme)
        out = answer if isinstance(answer, str) else json.dumps(answer)

        def setup(bridge):
            themed(bridge)
            # before the shell loads: the widget asks as soon as it appears
            bridge.commands.insert(0, ("dxrice_weather.py", out))
        s = Scene(width=1920, height=1080, setup=setup)
        s.wait(700)
        return s

    def text(self, s, name):
        return s.ev(f"findNamed('{name}').text")

    def test_off_by_default_and_then_it_asks_for_nothing(self):
        s = self.scene(widget_weather=None)
        try:
            self.assertFalse(s.ev("findNamed('weatherWidget').visible"))
            self.assertEqual(fetches(s), [])
        finally:
            s.close()

    def test_a_real_answer_is_shown(self):
        s = self.scene(widget_weather=True, weather_location="Austin")
        try:
            self.assertEqual(len(fetches(s)), 1)
            self.assertEqual(self.text(s, "weatherTemp"), "22°")
            self.assertEqual(self.text(s, "weatherCondition"), "Partly cloudy  ·  Austin, US")
            self.assertIn("feels 20°", self.text(s, "weatherDetails"))
            self.assertIn("11 km/h", self.text(s, "weatherDetails"))
            self.assertEqual(s.ev("findNamed('weatherDays').children.length"), 4)   # 3 days + the Repeater
            self.assertFalse(s.ev("findNamed('weatherStale').visible"))
            self.assertFalse(s.ev("findNamed('weatherMessage').visible"))
        finally:
            s.close()

    def test_no_location_says_so_instead_of_a_forecast(self):
        s = self.scene(answer={"error": "No location set. Add one in Settings > Experience > Desktop widgets."},
                       widget_weather=True, weather_location=None)
        try:
            self.assertTrue(s.ev("findNamed('weatherMessage').visible"))
            self.assertIn("No location set", self.text(s, "weatherMessage"))
            self.assertFalse(s.ev("findNamed('weatherTemp').visible"))
        finally:
            s.close()

    def test_an_old_answer_is_marked_offline(self):
        s = self.scene(answer=dict(ANSWER, stale=True), widget_weather=True, weather_location="Austin")
        try:
            self.assertTrue(s.ev("findNamed('weatherStale').visible"))
            self.assertTrue(self.text(s, "weatherStale").startswith("offline"))
        finally:
            s.close()

    def test_broken_output_is_an_honest_message(self):
        s = self.scene(answer="not json", widget_weather=True, weather_location="Austin")
        try:
            self.assertTrue(s.ev("findNamed('weatherMessage').visible"))
            self.assertFalse(s.ev("findNamed('weatherTemp').visible"))
        finally:
            s.close()

    def test_changing_the_place_asks_again(self):
        s = self.scene(widget_weather=True, weather_location="Austin")
        try:
            n = len(fetches(s))
            s.ev("theme.data = Object.assign({}, theme.data, {weather_location: 'Lisbon'})")
            s.wait(300)
            self.assertEqual(len(fetches(s)), n + 1)
        finally:
            s.close()

    def test_imperial_units_show_mph(self):
        s = self.scene(answer=dict(ANSWER, units="imperial", wind=7), widget_weather=True, weather_location="Austin")
        try:
            self.assertIn("7 mph", self.text(s, "weatherDetails"))
        finally:
            s.close()

    def test_the_location_is_typed_in_settings(self):
        s = self.scene(widget_weather=True, weather_location=None)
        try:
            s.ev("panels.open('theme')")
            s.wait(700)
            s.ev(f"{TE}.currentCategory = 'experience'")
            s.wait(600)
            s.ev("(function(){ var i = findNamed('weatherLocationInput'); i.text = 'Lisbon'; i.editingFinished(); })()")
            self.assertEqual(s.ev(f"{TE}.weather_location"), "Lisbon")
            self.assertTrue(s.ev(f"{TE}.dirty"))
            keys = s.ev(f"{TE}.allKeys().join(',')").split(",")
            for k in ("widget_weather", "weather_location", "weather_units", "widget_weather_pos"):
                self.assertIn(k, keys)
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
