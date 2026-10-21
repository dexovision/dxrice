#!/usr/bin/env python3
"""dxrice_weather.py: the place comes only from the setting, answers are
cached, a failing network falls back to the last answer, and nothing is
ever made up. No real network: a fake opener answers."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_weather as w  # noqa: E402

GEO = {"results": [
    {"name": "Austin", "latitude": 30.27, "longitude": -97.74, "country_code": "US", "admin1": "Texas", "country": "United States"},
    {"name": "Austin", "latitude": 43.67, "longitude": -92.97, "country_code": "US", "admin1": "Minnesota", "country": "United States"},
]}
FORECAST = {"current": {"temperature_2m": 21.5, "apparent_temperature": 20.1, "relative_humidity_2m": 40,
                        "weather_code": 2, "wind_speed_10m": 11.0, "is_day": 1},
            "daily": {"time": ["2026-10-21", "2026-10-22", "2026-10-23"], "temperature_2m_max": [24, 25, 19],
                      "temperature_2m_min": [12, 14, 9], "weather_code": [2, 3, 61]}}


class FakeNet:
    def __init__(self, geo=GEO, forecast=FORECAST, fail=False):
        self.geo, self.forecast, self.fail, self.urls = geo, forecast, fail, []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if self.fail:
            raise OSError("network is unreachable")
        body = self.geo if url.startswith(w.GEOCODE) else self.forecast
        return _Resp(json.dumps(body).encode())


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestWeather(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "weather.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_location_means_no_weather_and_no_request(self):
        net = FakeNet()
        got = w.weather("", "metric", cache=self.cache, opener=net)
        self.assertIn("error", got)
        self.assertIn("No location set", got["error"])
        self.assertEqual(net.urls, [])

    def test_a_place_is_geocoded_then_forecast(self):
        net = FakeNet()
        got = w.weather("Austin", "metric", cache=self.cache, now=1000, opener=net)
        self.assertEqual(got["place"], "Austin, US")
        self.assertEqual((got["temp"], got["feels"], got["humidity"], got["wind"], got["code"]), (21.5, 20.1, 40, 11.0, 2))
        self.assertEqual([d["max"] for d in got["days"]], [24, 25, 19])
        self.assertFalse(got["stale"])
        q = urllib.parse.parse_qs(urllib.parse.urlparse(net.urls[1]).query)
        self.assertEqual((q["latitude"], q["temperature_unit"]), (["30.27"], ["celsius"]))

    def test_a_qualifier_picks_among_places_with_the_same_name(self):
        net = FakeNet()
        w.weather("Austin, Minnesota", "metric", cache=self.cache, opener=net)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(net.urls[1]).query)
        self.assertEqual(q["latitude"], ["43.67"])
        g = urllib.parse.parse_qs(urllib.parse.urlparse(net.urls[0]).query)
        self.assertEqual(g["name"], ["Austin"])

    def test_imperial_asks_for_fahrenheit_and_mph(self):
        net = FakeNet()
        w.weather("Austin", "imperial", cache=self.cache, opener=net)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(net.urls[1]).query)
        self.assertEqual((q["temperature_unit"], q["wind_speed_unit"]), (["fahrenheit"], ["mph"]))

    def test_an_unknown_place_says_so(self):
        got = w.weather("Nowhereville", "metric", cache=self.cache, opener=FakeNet(geo={"results": []}))
        self.assertIn("doesn't know", got["error"])

    def test_a_fresh_answer_is_served_from_the_cache(self):
        w.weather("Austin", "metric", cache=self.cache, now=1000, opener=FakeNet())
        net = FakeNet()
        got = w.weather("Austin", "metric", cache=self.cache, now=1000 + w.FRESH_S - 1, opener=net)
        self.assertEqual(net.urls, [])
        self.assertEqual(got["temp"], 21.5)

    def test_a_failing_network_returns_the_last_answer_marked_stale(self):
        w.weather("Austin", "metric", cache=self.cache, now=1000, opener=FakeNet())
        got = w.weather("Austin", "metric", cache=self.cache, now=1000 + w.FRESH_S + 5, opener=FakeNet(fail=True))
        self.assertTrue(got["stale"])
        self.assertEqual(got["temp"], 21.5)

    def test_a_failing_network_with_nothing_cached_is_an_error_not_a_guess(self):
        got = w.weather("Austin", "metric", cache=self.cache, opener=FakeNet(fail=True))
        self.assertEqual(set(got), {"error"})

    def test_a_cached_answer_for_another_place_is_never_used(self):
        w.weather("Austin", "metric", cache=self.cache, now=1000, opener=FakeNet())
        got = w.weather("Lisbon", "metric", cache=self.cache, now=1001, opener=FakeNet(fail=True))
        self.assertIn("error", got)

    def test_settings_read_the_place_and_units(self):
        path = os.path.join(self.tmp.name, "theme.json")
        with open(path, "w") as f:
            json.dump({"weather_location": "  Lisbon ", "weather_units": "imperial", "accent": "x"}, f)
        self.assertEqual(w.settings(path), ("Lisbon", "imperial"))
        with open(path, "w") as f:
            f.write("{broken")
        self.assertEqual(w.settings(path), ("", "metric"))


if __name__ == "__main__":
    unittest.main()
