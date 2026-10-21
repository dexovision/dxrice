#!/usr/bin/env python3
"""The weather widget's data: current conditions and the next three days
for the place written in theme.json ("weather_location", e.g. "Lisbon" or
"Austin, Texas"), from Open-Meteo (no account or key needed).

Prints one JSON object:
  {"place", "temp", "feels", "humidity", "wind", "code", "is_day",
   "units", "days": [{"date", "max", "min", "code"}, ...], "fetched", "stale"}
or {"error": "..."} -- with no location set, an unknown place, or no network
and nothing cached. Nothing is ever guessed: no location means no weather,
and the place is never worked out from the network.

Answers are cached in the state dir for 10 minutes; when the network fails
the last answer for the same place is returned with "stale": true.

    python3 dxrice_weather.py [--location PLACE] [--units metric|imperial]
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_xdg  # noqa: E402

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
FRESH_S = 600
TIMEOUT_S = 8


def _get(url, params, opener=None):
    full = url + "?" + urllib.parse.urlencode(params)
    with (opener or urllib.request.urlopen)(full, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def settings(path=None):
    path = path or os.path.join(dxrice_xdg.config_dir(), "theme.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    place = str(data.get("weather_location") or "").strip()
    units = "imperial" if data.get("weather_units") == "imperial" else "metric"
    return place, units


def cache_path():
    return os.path.join(dxrice_xdg.state_dir(), "weather.json")


def _read_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_cache(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


def fetch(place, units, opener=None):
    """The answer for `place` straight from Open-Meteo (raises on network
    trouble; returns {"error"} for a place it doesn't know)."""
    # "Austin, Texas": the geocoder matches on the name; the rest picks among matches
    name, _, qualifier = place.partition(",")
    found = _get(GEOCODE, {"name": name.strip(), "count": 10, "format": "json"}, opener).get("results") or []
    if qualifier.strip():
        q = qualifier.strip().lower()
        found = [r for r in found if q in " ".join(str(r.get(k, "")) for k in ("admin1", "country", "country_code")).lower()] or found
    if not found:
        return {"error": f"Open-Meteo doesn't know a place called {place!r}."}
    p = found[0]
    imperial = units == "imperial"
    w = _get(FORECAST, {
        "latitude": p["latitude"], "longitude": p["longitude"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
        "timezone": "auto", "forecast_days": 3,
    }, opener)
    cur, daily = w.get("current") or {}, w.get("daily") or {}
    days = [{"date": d, "max": hi, "min": lo, "code": c}
            for d, hi, lo, c in zip(daily.get("time", []), daily.get("temperature_2m_max", []),
                                    daily.get("temperature_2m_min", []), daily.get("weather_code", []))]
    return {
        "place": ", ".join(x for x in (p.get("name"), p.get("country_code")) if x),
        "temp": cur.get("temperature_2m"), "feels": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"), "wind": cur.get("wind_speed_10m"),
        "code": cur.get("weather_code"), "is_day": bool(cur.get("is_day", 1)),
        "units": units, "days": days,
    }


def weather(place, units, cache=None, now=None, opener=None):
    if not place:
        return {"error": "No location set. Add one in Settings > Experience > Desktop widgets."}
    cache = cache or cache_path()
    now = time.time() if now is None else now
    key = f"{place.lower()}|{units}"
    cached = _read_cache(cache)
    if cached and cached.get("key") == key and now - cached.get("fetched", 0) < FRESH_S:
        return dict(cached["data"], fetched=cached["fetched"], stale=False)
    try:
        data = fetch(place, units, opener)
    except (OSError, ValueError, KeyError) as e:
        if cached and cached.get("key") == key:
            return dict(cached["data"], fetched=cached["fetched"], stale=True)
        return {"error": f"No weather right now ({type(e).__name__}); will try again."}
    if "error" not in data:
        _write_cache(cache, {"key": key, "fetched": now, "data": data})
        return dict(data, fetched=now, stale=False)
    return data


def main(argv):
    place, units = settings()
    if "--location" in argv:
        place = argv[argv.index("--location") + 1]
    if "--units" in argv:
        units = "imperial" if argv[argv.index("--units") + 1] == "imperial" else "metric"
    print(json.dumps(weather(place, units)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
