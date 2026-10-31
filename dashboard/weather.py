"""Weather for each outdoor activity, from Open-Meteo (free, no key).

Open-Meteo gives model data on a grid (about 2-11 km), not a weather station
reading, so treat it as "the conditions in the area at that hour".
- 2022 onwards: the Historical Forecast API (includes visibility).
- Before 2022: the ERA5 archive (no visibility).
Values at the middle of the activity are interpolated between hours; rain is
summed over the hours the activity covered.
"""
import logging
import math
import time
from datetime import date, datetime, timedelta

import requests
from django.conf import settings

log = logging.getLogger("dashboard.weather")

HOURLY = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature", "precipitation",
          "rain", "weather_code", "cloud_cover", "pressure_msl", "surface_pressure", "wind_speed_10m",
          "wind_direction_10m", "wind_gusts_10m", "visibility"]
OUTDOOR = {"run", "walk", "cycle"}
INDOOR_TYPES = ("treadmill", "indoor", "virtual")

WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers",
    82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def describe(code):
    return WMO.get(code, "") if code is not None else ""


def compass(deg):
    if deg is None:
        return ""
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


class WeatherError(Exception):
    pass


class WeatherClient:
    def __init__(self):
        self.forecast_url = getattr(settings, "WEATHER_FORECAST_URL", "") or "https://historical-forecast-api.open-meteo.com/v1/forecast"
        self.archive_url = getattr(settings, "WEATHER_ARCHIVE_URL", "") or "https://archive-api.open-meteo.com/v1/archive"
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "splits-dashboard/1.0 (personal use)"
        self.calls = 0
        self._last = 0.0

    def hourly(self, lat, lon, start: date, end: date):
        use_archive = start < date(2022, 1, 1)
        url = self.archive_url if use_archive else self.forecast_url
        variables = [v for v in HOURLY if not (use_archive and v == "visibility")]
        for attempt in range(3):
            wait = 0.25 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "start_date": start.isoformat(),
                      "end_date": end.isoformat(), "hourly": ",".join(variables), "timezone": "GMT",
                      "wind_speed_unit": "kmh"}
            try:
                r = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                raise WeatherError(f"Could not reach Open-Meteo ({exc.__class__.__name__})") from None
            self.calls += 1
            if r.status_code == 400 and "visibility" in variables:
                variables.remove("visibility")  # not every model has it
                continue
            if r.status_code == 429:
                raise WeatherError("Open-Meteo daily limit reached; the rest comes with the next sync")
            if r.status_code >= 500 and attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
            if r.status_code != 200:
                raise WeatherError(f"Open-Meteo answered {r.status_code}: {r.text[:120]}")
            data = r.json()
            data["_source"] = "archive" if use_archive else "historical-forecast"
            return data
        raise WeatherError("Open-Meteo did not answer")


def _parse_time(s):
    s = s.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _interp(times, values, at):
    """Linear interpolation of an hourly series at a datetime."""
    pts = [(t, v) for t, v in zip(times, values) if t is not None and v is not None]
    if not pts:
        return None
    if at <= pts[0][0]:
        return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= at <= t1:
            f = (at - t0).total_seconds() / max((t1 - t0).total_seconds(), 1)
            return v0 + (v1 - v0) * f
    return pts[-1][1]


def _interp_dir(times, speeds, dirs, at):
    """Wind direction interpolated as a vector (so 350 and 10 average to 0, not 180)."""
    u = [None if s is None or d is None else -s * math.sin(math.radians(d)) for s, d in zip(speeds, dirs)]
    v = [None if s is None or d is None else -s * math.cos(math.radians(d)) for s, d in zip(speeds, dirs)]
    ui, vi = _interp(times, u, at), _interp(times, v, at)
    if ui is None or vi is None:
        return None
    return (math.degrees(math.atan2(-ui, -vi)) + 360) % 360


def _sum_over(times, values, start, end):
    """Sum hourly totals (each value covers the hour before its timestamp) over [start, end]."""
    total, seen = 0.0, False
    for t, v in zip(times, values):
        if t is None or v is None:
            continue
        h0, h1 = t - timedelta(hours=1), t
        overlap = (min(h1, end) - max(h0, start)).total_seconds()
        if overlap > 0:
            total += v * overlap / 3600.0
            seen = True
    if not seen:  # shorter than an hour inside one bucket
        for t, v in zip(times, values):
            if t is not None and v is not None and t - timedelta(hours=1) <= start <= t:
                return v * max((end - start).total_seconds(), 0) / 3600.0
    return total


def activity_window(act):
    """(start, end) in GMT."""
    start = act.start_gmt
    if start is None:
        start = act.start_local  # best effort
    end = start + timedelta(seconds=act.elapsed_s or act.duration_s or act.time_s or 0)
    return start, end


def activity_coords(act):
    if act.start_lat is not None and act.start_lon is not None:
        return act.start_lat, act.start_lon
    stream = getattr(act, "stream", None)
    data = stream.data if stream else {}
    for la, lo in zip(data.get("lat") or [], data.get("lon") or []):
        if la is not None and lo is not None:
            return la, lo
    return None


def wants_weather(act):
    if act.category not in OUTDOOR:
        return False
    if any(x in (act.type_key or "") for x in INDOOR_TYPES):
        return False
    return activity_coords(act) is not None


def build(act, data):
    """Turn an Open-Meteo answer into Weather fields for the activity."""
    h = data.get("hourly") or {}
    times = [_parse_time(t) for t in h.get("time") or []]
    start, end = activity_window(act)
    mid = start + (end - start) / 2
    g = lambda k: h.get(k) or [None] * len(times)
    fields = {
        "source": data.get("_source", ""),
        "grid_elevation": data.get("elevation"),
        "temp_c": _interp(times, g("temperature_2m"), mid),
        "feels_c": _interp(times, g("apparent_temperature"), mid),
        "humidity": _interp(times, g("relative_humidity_2m"), mid),
        "dew_point_c": _interp(times, g("dew_point_2m"), mid),
        "precip_mm": _sum_over(times, g("precipitation"), start, end),
        "rain_mm": _sum_over(times, g("rain"), start, end),
        "cloud_pct": _interp(times, g("cloud_cover"), mid),
        "pressure_msl": _interp(times, g("pressure_msl"), mid),
        "pressure_surface": _interp(times, g("surface_pressure"), mid),
        "wind_kmh": _interp(times, g("wind_speed_10m"), mid),
        "gust_kmh": max([v for t, v in zip(times, g("wind_gusts_10m")) if t and v is not None
                         and start - timedelta(hours=1) <= t <= end + timedelta(hours=1)] or [None],
                        key=lambda x: -1 if x is None else x),
        "wind_dir": _interp_dir(times, g("wind_speed_10m"), g("wind_direction_10m"), mid),
        "visibility_m": _interp(times, g("visibility"), mid),
        "error": "",
    }
    codes = [v for t, v in zip(times, g("weather_code")) if t and v is not None
             and start < t < end + timedelta(hours=1)]  # hourly codes describe the hour before their time
    fields["weather_code"] = max(codes) if codes else None  # the most significant weather during it
    keep = [i for i, t in enumerate(times) if t and start - timedelta(hours=2) <= t <= end + timedelta(hours=2)]
    fields["hourly"] = {"time": [h["time"][i] for i in keep],
                        **{k: [h[k][i] for i in keep] for k in HOURLY if k in h}}
    for k in ("temp_c", "feels_c", "humidity", "dew_point_c", "cloud_pct", "pressure_msl", "pressure_surface",
              "wind_kmh", "wind_dir", "visibility_m", "precip_mm", "rain_mm"):
        if fields[k] is not None:
            fields[k] = round(fields[k], 2)
    hw = headwind_series(act, fields)
    if hw:
        fields["headwind_kmh"], fields["headwind_share"] = hw["avg"], hw["share"]
    return fields


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def headwind_series(act, w, data=None):
    """Headwind (+) / tailwind (-) in km/h at each sample, from your direction of travel.
    Uses the wind at the middle of the activity (wind is from the model grid, at 10 m).
    data: {"t", "lat", "lon"} lists to use instead of the stored chart copy (the full recording, say)."""
    if data is None:
        stream = getattr(act, "stream", None)
        data = stream.data if stream else {}
    lat, lon, t = data.get("lat"), data.get("lon"), data.get("t")
    speed, wfrom = (w.get("wind_kmh") if isinstance(w, dict) else w.wind_kmh), (
        w.get("wind_dir") if isinstance(w, dict) else w.wind_dir)
    if not lat or not lon or not t or speed is None or wfrom is None:
        return None
    n = len(t)
    out = [None] * n
    j = 0
    for i in range(n):
        while j < i and t[i] - t[j] > 15:
            j += 1
        if lat[i] is None or lat[j] is None or i == j:
            continue
        # ignore standing still (GPS jitter gives random bearings)
        dist = math.hypot((lat[i] - lat[j]) * 111320, (lon[i] - lon[j]) * 111320 * math.cos(math.radians(lat[i])))
        if dist < 10:
            continue
        b = _bearing(lat[j], lon[j], lat[i], lon[i])
        out[i] = round(speed * math.cos(math.radians(b - wfrom)), 1)
    vals, weights = [], []
    for i in range(1, n):
        if out[i] is not None:
            vals.append(out[i])
            weights.append(max(min(t[i] - t[i - 1], 30), 0))
    if not vals or not sum(weights):
        return None
    avg = sum(v * wt for v, wt in zip(vals, weights)) / sum(weights)
    share = sum(wt for v, wt in zip(vals, weights) if v > 5) / sum(weights)
    return {"series": out, "avg": round(avg, 1), "share": round(share, 3)}


def heat_cost(temp_c, dew_c):
    """Runners' rule of thumb on temperature + dew point, in Celsius: returns (sum in °C, expected slowdown
    as text). The guide is usually given in Fahrenheit (no effect up to 100 °F combined, then about every
    10 °F); these are the same bands converted, since the sum of two °F values is 1.8 * sum °C + 64."""
    if temp_c is None or dew_c is None:
        return None, ""
    s = temp_c + dew_c
    bands = [(20.0, "no effect"), (25.6, "0 to 0.5% slower"), (31.1, "0.5 to 1% slower"), (36.7, "1 to 2% slower"),
             (42.2, "2 to 3% slower"), (47.8, "3 to 4.5% slower"), (53.3, "4.5 to 6% slower"),
             (58.9, "6 to 8% slower"), (64.4, "8 to 10% slower")]
    for limit, text in bands:
        if s <= limit:
            return round(s, 1), text
    return round(s, 1), "too hot for hard running"
