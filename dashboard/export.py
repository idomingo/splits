"""One run as a Markdown file to hand to an AI tool.

Descriptive parts (what, where, when, totals, weather, why it counts as a
long run) are Markdown; small tables are Markdown tables; the long per-second
recording is a CSV block, which costs far fewer tokens than the same numbers as
a Markdown table. GPS coordinates are left out on purpose: a start point is
often someone's front door, and the file is meant to be uploaded elsewhere.
"""
import io
import math
import re
import statistics
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings

from .sports import KIND_TITLE as KIND_NAME  # noqa: E402  (same words as the titles on the dashboard)
ZONE_NAMES = ["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"]
# Garmin summary fields that identify the person, the device owner or the location: never exported
PRIVATE_KEYS = re.compile(r"^(owner|userProfile|profileImage|deviceId|activityUUID|privacy|summarizedDiveInfo)"
                          r"|(Latitude|Longitude|ImageUrl)", re.I)


# ---------- small formatters ----------
def _n(v, dp=0):
    """Compact number: rounded, no trailing .0, blank when missing."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    v = round(float(v), dp)
    if dp == 0 or v == int(v):
        return str(int(v))
    return f"{v:.{dp}f}".rstrip("0").rstrip(".")


def _dur(s):
    if s is None:
        return ""
    s = int(round(s))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _pace(s_per_km):
    if not s_per_km or s_per_km <= 0 or s_per_km > 3600:
        return ""
    s = int(round(s_per_km))
    return f"{s // 60}:{s % 60:02d}"


def _hm(s):
    if s is None:
        return ""
    m = int(round(s / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def _climb(alts, threshold=1.2):
    """Metres up and down, ignoring wobbles under `threshold` (altimeter noise)."""
    up = down = 0.0
    anchor = None
    for a in alts:
        if a is None:
            continue
        if anchor is None:
            anchor = a
        elif a - anchor >= threshold:
            up += a - anchor
            anchor = a
        elif anchor - a >= threshold:
            down += anchor - a
            anchor = a
    return up, down


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


# ---------- the full recording ----------
def fit_path(act):
    stream = getattr(act, "stream", None) if _has(act, "stream") else None
    names = [stream.source_file] if stream and stream.source_file else []
    names += [f"{act.activity_id}.zip", f"{act.activity_id}.fit"]
    for name in names:
        p = settings.DATA_DIR / "fit" / name
        if p.exists():
            return p
    return None


def full_recording(act):
    """Every point the watch recorded, from the activity file (usually one per second).
    Returns (columns dict of lists, laps list, device name) or None when there is no file."""
    import fitdecode

    from .fitparse import SEMICIRCLE, extract_fit_bytes
    path = fit_path(act)
    if not path:
        return None
    fit = extract_fit_bytes(path.read_bytes())
    if not fit:
        return None
    steps = 2 if act.category in ("run", "walk") else 1
    keys = ("ts", "d", "spd", "hr", "cad", "pwr", "alt", "vo", "gct", "vr", "step", "tmp", "resp", "lat", "lon")
    rec = {k: [] for k in keys}
    laps, device = [], ""

    def val(frame, *names):
        for nm in names:
            if frame.has_field(nm):
                v = frame.get_value(nm, fallback=None)
                if v is not None:
                    return v
        return None

    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    with fitdecode.FitReader(io.BytesIO(fit), check_crc=fitdecode.CrcCheck.DISABLED) as fr:
        for frame in fr:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name == "record":
                ts = val(frame, "timestamp")
                if ts is None:
                    continue
                cad = num(val(frame, "cadence"))
                if cad is not None:
                    cad = (cad + (num(val(frame, "fractional_cadence")) or 0)) * steps
                lat, lon = num(val(frame, "position_lat")), num(val(frame, "position_long"))
                row = {
                    "ts": ts.timestamp(), "d": num(val(frame, "distance")),
                    "spd": num(val(frame, "enhanced_speed", "speed")), "hr": num(val(frame, "heart_rate")),
                    "cad": cad, "pwr": num(val(frame, "power")), "alt": num(val(frame, "enhanced_altitude", "altitude")),
                    "vo": num(val(frame, "vertical_oscillation")), "gct": num(val(frame, "stance_time")),
                    "vr": num(val(frame, "vertical_ratio")), "step": num(val(frame, "step_length")),
                    "tmp": num(val(frame, "temperature")),
                    "resp": num(val(frame, "enhanced_respiration_rate", "respiration_rate")),
                    "lat": lat * SEMICIRCLE if lat is not None else None,
                    "lon": lon * SEMICIRCLE if lon is not None else None,
                }
                for k in keys:
                    rec[k].append(row[k])
            elif frame.name == "lap":
                cad = num(val(frame, "avg_running_cadence", "avg_cadence"))
                if cad is not None:
                    cad = (cad + (num(val(frame, "avg_fractional_cadence")) or 0)) * steps
                start = val(frame, "start_time")
                laps.append({
                    "start_ts": start.timestamp() if start else None,
                    "secs": num(val(frame, "total_timer_time", "total_elapsed_time")),
                    "dist": num(val(frame, "total_distance")),
                    "avg_spd": num(val(frame, "enhanced_avg_speed", "avg_speed")),
                    "max_spd": num(val(frame, "enhanced_max_speed", "max_speed")),
                    "avg_hr": num(val(frame, "avg_heart_rate")), "max_hr": num(val(frame, "max_heart_rate")),
                    "cad": cad, "pwr": num(val(frame, "avg_power")),
                    "up": num(val(frame, "total_ascent")), "down": num(val(frame, "total_descent")),
                    "vo": num(val(frame, "avg_vertical_oscillation")), "gct": num(val(frame, "avg_stance_time")),
                    "step": num(val(frame, "avg_step_length")),
                    "intensity": str(val(frame, "intensity") or ""), "trigger": str(val(frame, "lap_trigger") or ""),
                })
            elif frame.name == "file_id" and not device:
                prod = val(frame, "garmin_product", "product_name", "product")
                if prod is not None:
                    device = str(prod)
    if not rec["ts"]:
        return None
    t0 = rec["ts"][0]
    rec["t"] = [round(x - t0, 1) for x in rec["ts"]]
    for lap in laps:
        lap["start"] = (lap["start_ts"] - t0) if lap.get("start_ts") else None
    return rec, laps, device


def stored_recording(act):
    """The down-sampled copy kept for the charts, used when the activity file is missing (demo data)."""
    stream = act.stream if _has(act, "stream") else None
    data = stream.data if stream else {}
    if not data.get("t"):
        return None
    n = len(data["t"])
    rec = {k: (data.get(k) or [None] * n) for k in ("t", "d", "spd", "hr", "cad", "pwr", "alt", "tmp", "lat", "lon")}
    for k in ("vo", "gct", "vr", "step", "resp"):
        rec[k] = [None] * n
    return rec


def _has(obj, rel):
    try:
        return getattr(obj, rel) is not None
    except Exception:
        return False


# ---------- splits from the full recording ----------
def km_splits(rec, wind=None, mask=None, unit=1000.0):
    """Per-km splits worked out from the recording (boundaries interpolated between samples)."""
    t, d = rec["t"], rec["d"]
    if not t or not d or not any(d):
        return []
    clean, last = [], 0.0
    for v in d:  # distance only ever goes up
        last = max(last, v) if v is not None else last
        clean.append(last)
    rec = dict(rec, d=clean)
    rows, i0, target, n, t_start = [], 0, unit, len(t), t[0]
    for i in range(1, n):
        while clean[i] >= target:
            d0, d1 = clean[i - 1], clean[i]
            frac = (target - d0) / (d1 - d0) if d1 > d0 else 0
            t_cross = t[i - 1] + frac * (t[i] - t[i - 1])
            rows.append(seg_stats(rec, i0, i, wind, mask, t0=t_start, t1=t_cross, dist=unit))
            i0, t_start, target = i, t_cross, target + unit
    rest = clean[-1] - (target - unit)
    if rest >= 50:
        rows.append(seg_stats(rec, i0, n - 1, wind, mask, t0=t_start, t1=t[-1], dist=rest))
    return rows


# ---------- analysis on the full recording ----------
MOVING = 0.8  # m/s: slower than this counts as standing


def _back_avg(xs, t, win):
    """Average of each value with the ones recorded in the `win` seconds before it."""
    out, j, tot, cnt = [], 0, 0.0, 0
    for i in range(len(xs)):
        if xs[i] is not None:
            tot += xs[i]
            cnt += 1
        while t[i] - t[j] > win:
            if xs[j] is not None:
                tot -= xs[j]
                cnt -= 1
            j += 1
        out.append(tot / cnt if cnt else None)
    return out


def marked_hr_ranges(rec, jump=25, window=30, settle=300):
    """Stretches where heart rate does not follow pace: after the first `settle` seconds, heart rate moves
    more than `jump` bpm within `window` seconds while pace stays within 15%. The stretch at the lower level
    is returned, from its start until heart rate is back. No judgement on which reading is right."""
    t, hr, spd = rec["t"], rec["hr"], rec["spd"]
    n = len(t)
    if n < 60 or not any(hr) or not any(spd):
        return []
    h, sp = _back_avg(hr, t, 5), _back_avg(spd, t, 30)
    found, i, j = [], 0, 0
    while i < n:
        while j < i and t[i] - t[j] > window:
            j += 1
        steady = (t[i] >= settle and h[i] and h[j] and sp[i] and sp[j] and sp[j] > 1.0
                  and abs(sp[i] - sp[j]) / sp[j] < 0.15)
        if steady and abs(h[i] - h[j]) > jump:
            if h[i] > h[j]:  # it rose: the low stretch before is the odd one out
                after = statistics.median([x for x in h[i:i + 30] if x] or [h[i]])
                k = j
                while k > 0 and h[k - 1] is not None and h[k - 1] < after - 15:
                    k -= 1
                e = i
                while e < n - 1 and h[e] is not None and h[e] < after - 5:
                    e += 1
                found.append([t[k], t[e]])
            else:  # it dropped: the low stretch after it
                before = h[j]
                e = i
                while e < n - 1 and (h[e] is None or h[e] < before - 8):
                    e += 1
                found.append([t[j], t[e]])
            i = e + 1
            continue
        i += 1
    merged = []
    for a, b in sorted(found):
        if merged and a <= merged[-1][1] + 10:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= 15]


def mask_for(t, ranges):
    out, r = [], 0
    for tt in t:
        while r < len(ranges) and tt > ranges[r][1]:
            r += 1
        out.append(r < len(ranges) and ranges[r][0] <= tt <= ranges[r][1])
    return out


def _wmean(rec, key, i0, i1, keep=None, weight=False):
    """Time-weighted mean of rec[key] over samples i0..i1 (a sample counts for the time to the next one,
    at most 5 s), only where keep(k) is true. With weight=True, (mean, seconds counted)."""
    t, vals = rec["t"], rec[key]
    tot = wsum = 0.0
    for k in range(i0, min(i1, len(t) - 1) + 1):
        v = vals[k]
        if v is None or (keep and not keep(k)):
            continue
        dt = min((t[k + 1] - t[k]) if k + 1 < len(t) else 1.0, 5.0) or 1.0
        tot += v * dt
        wsum += dt
    mean = tot / wsum if wsum else None
    return (mean, wsum) if weight else mean


def hr_without(rec, i0, i1, mask):
    """Average heart rate over i0..i1 leaving out marked samples; None when too little is left to say
    (under a quarter of the stretch or under 30 seconds)."""
    if not mask or not any(mask[i0:i1 + 1]):
        return _wmean(rec, "hr", i0, i1)
    _, every = _wmean(rec, "hr", i0, i1, weight=True)
    mean, kept = _wmean(rec, "hr", i0, i1, keep=lambda k: not mask[k], weight=True)
    return mean if kept >= max(30.0, 0.25 * every) else None


def seg_stats(rec, i0, i1, wind=None, mask=None, t0=None, t1=None, dist=None):
    """Totals and averages for samples i0..i1. Cadence, power and running dynamics count moving time only,
    as Garmin does; heart rate counts all of it, and again without marked stretches when there are some."""
    t, d = rec["t"], rec["d"]
    moving = lambda k: (rec["spd"][k] or 0) >= MOVING
    t0 = t[i0] if t0 is None else t0
    t1 = t[i1] if t1 is None else t1
    if dist is None:
        dist = max((d[i1] or 0) - (d[i0] or 0), 0)
    secs = max(t1 - t0, 0)
    hrs = [h for h in rec["hr"][i0:i1 + 1] if h]
    up, down = _climb(rec["alt"][i0:i1 + 1])
    out = {
        "dist": dist, "secs": secs, "pace": secs / (dist / 1000.0) if dist > 0 else None,
        "hr": _wmean(rec, "hr", i0, i1), "max_hr": max(hrs) if hrs else None,
        "hr_clean": hr_without(rec, i0, i1, mask) if mask else None,
        "marked": bool(mask) and any(mask[i0:i1 + 1]),
        "cad": _wmean(rec, "cad", i0, i1, moving), "pwr": _wmean(rec, "pwr", i0, i1, moving),
        "gct": _wmean(rec, "gct", i0, i1, moving), "step": _wmean(rec, "step", i0, i1, moving),
        "vo": _wmean(rec, "vo", i0, i1, moving), "up": up, "down": down,
        "wind": None,
    }
    if wind:
        vals = [w for w in wind[i0:i1 + 1] if w is not None]
        out["wind"] = sum(vals) / len(vals) if vals else None
    return out


def zone_times(rec, floors, mask=None):
    """Seconds below zone 1 and in zones 1 to 5, from the recorded heart rate."""
    t, hr = rec["t"], rec["hr"]
    out = [0.0] * 6
    for k in range(len(t)):
        h = hr[k]
        if not h or (mask and mask[k]):
            continue
        dt = min((t[k + 1] - t[k]) if k + 1 < len(t) else 1.0, 5.0)
        z = 0
        for i, f in enumerate(floors):
            if h >= f:
                z = i + 1
        out[z] += dt
    return out


def _xy(rec):
    """One point every 10 m along the track, in metres around the start: [(index, x, y, distance)]."""
    lat, lon, d = rec["lat"], rec["lon"], rec["d"]
    idx = [i for i in range(len(rec["t"])) if lat[i] is not None and lon[i] is not None and d[i] is not None]
    if len(idx) < 60:
        return []
    la0, lo0 = lat[idx[0]], lon[idx[0]]
    k = math.cos(math.radians(la0))
    pts, last = [], -1e9
    for i in idx:
        if d[i] - last >= 10:
            pts.append((i, (lon[i] - lo0) * 111320 * k, (lat[i] - la0) * 111320, d[i]))
            last = d[i]
    return pts


def route_shape(rec, near=40.0):
    """Only clear cases: an out-and-back (turns round near half way, comes back the same way, ends near the
    start) or laps of the same circuit (most points are passed again after the same distance).
    Returns None when neither is clear."""
    if not rec or not rec.get("lat") or not any(v is not None for v in rec["lat"]):
        return None
    pts = _xy(rec)
    if len(pts) < 30:
        return None
    total = pts[-1][3] - pts[0][3]
    if total < 1000:
        return None
    grid = {}
    for n, (_i, x, y, _d) in enumerate(pts):
        grid.setdefault((int(x // near), int(y // near)), []).append(n)

    def around(n):
        cx, cy = int(pts[n][1] // near), int(pts[n][2] // near)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                yield from grid.get((gx, gy), ())

    def dist(a, b):
        return math.hypot(pts[a][1] - pts[b][1], pts[a][2] - pts[b][2])

    far = max(range(len(pts)), key=lambda n: math.hypot(pts[n][1], pts[n][2]))
    frac = (pts[far][3] - pts[0][3]) / total
    end_gap = math.hypot(pts[-1][1], pts[-1][2])
    if 0.42 <= frac <= 0.58 and end_gap <= max(250.0, 0.05 * total):
        back = range(far + 1, len(pts))
        out = range(0, far)
        hit_back = sum(1 for b in back if any(m < far and dist(m, b) <= near for m in around(b)))
        hit_out = sum(1 for a in out if any(m > far and dist(m, a) <= near for m in around(a)))
        if back and out and hit_back / len(back) >= 0.8 and hit_out / len(out) >= 0.8:
            return {"shape": "out_and_back", "turn": pts[far][0]}
    returns = []
    for n in range(len(pts)):
        best = None
        for m in around(n):
            gap = pts[m][3] - pts[n][3]
            if gap >= 200 and dist(n, m) <= near * 0.6 and (best is None or gap < best):
                best = gap
        returns.append(best)
    found = [r for r in returns if r]
    if len(found) < 0.5 * len(pts):
        return None
    lap = statistics.median(found)
    if sum(1 for r in found if abs(r - lap) <= 0.08 * lap) < 0.75 * len(found) or total < 2 * lap:
        return None
    ref = next(n for n, r in enumerate(returns) if r and abs(r - lap) <= 0.08 * lap)
    passes, n = [ref], ref + 1
    while n < len(pts):
        if dist(n, ref) <= near * 0.6 and pts[n][3] - pts[passes[-1]][3] >= 0.7 * lap:
            m = n  # the closest point of this pass
            while m + 1 < len(pts) and dist(m + 1, ref) < dist(m, ref):
                m += 1
            passes.append(m)
            n = m + 1
            continue
        n += 1
    if len(passes) < 3:
        return None
    return {"shape": "circuit", "lap_m": lap, "passes": [pts[p][0] for p in passes]}


def decoupling(rec, kind, blocks, mask=None, wind=None):
    """Aerobic decoupling (pace to heart rate) for steady running: the first half against the second,
    after a warm-up and before any fast finish. None when the steady part is under 20 minutes."""
    if kind not in ("easy", "recovery", "long", "steady") or not rec or not any(rec["hr"]):
        return None
    t = rec["t"]
    warm = 600.0 if t[-1] >= 3000 else 300.0
    end = min((b["start"] for b in blocks or [] if b.get("start") is not None), default=t[-1])
    if end - warm < 1200:
        return None
    mid = (warm + end) / 2
    halves = []
    for a, b in ((warm, mid), (mid, end)):
        ks = [k for k in range(len(t)) if a <= t[k] < b and (rec["spd"][k] or 0) >= MOVING and rec["hr"][k]
              and not (mask and mask[k])]
        if len(ks) < 60:
            return None
        keep = set(ks)
        i0, i1 = ks[0], ks[-1]
        spd = _wmean(rec, "spd", i0, i1, lambda k: k in keep)
        hr = _wmean(rec, "hr", i0, i1, lambda k: k in keep)
        pwr = _wmean(rec, "pwr", i0, i1, lambda k: k in keep)
        up, down = _climb(rec["alt"][i0:i1 + 1])
        wv = [wind[k] for k in ks if wind and wind[k] is not None]
        halves.append({"from": a, "to": b, "spd": spd, "hr": hr, "pwr": pwr, "ef": spd * 60 / hr,
                       "up": up, "down": down, "wind": sum(wv) / len(wv) if wv else None})
    h1, h2 = halves
    out = {"halves": halves, "pa_hr": (h1["ef"] - h2["ef"]) / h1["ef"] * 100}
    if h1["pwr"] and h2["pwr"]:
        r1, r2 = h1["pwr"] / h1["hr"], h2["pwr"] / h2["hr"]
        out["pw_hr"] = (r1 - r2) / r1 * 100
    out["cut_at_block"] = end < t[-1]
    return out


# ---------- the file ----------
def filename(act):
    """The same words as the activity's title on the dashboard, with the date and time in front. The file
    always says what kind of run it was, even when the run has a name of its own in Garmin Connect."""
    what = act.make_title(use_name=False)
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", f"{act.start_local:%Y-%m-%d %Hh%M} {what}")
    return re.sub(r"\s+", " ", name).strip() + ".md"


def content_disposition(name):
    ascii_name = name.encode("ascii", "ignore").decode() or "activity.md"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}'


def activity_markdown(act):
    from .analytics import activity_detail
    from .models import Activity, BestEffort, DailySummary, HrvDay, SleepNight, Vo2Max
    from .runtypes import RUN_TYPE_LABEL
    from .sports import BEST_EFFORT_LABELS
    from .weather import compass, describe, headwind_series, heat_cost

    det = activity_detail(act)
    w = det["weather"]
    full = full_recording(act)
    if full:
        rec, fit_laps, device = full
        resolution = "every point the watch recorded, from the original activity file"
    else:
        rec, fit_laps, device = stored_recording(act), [], ""
        resolution = "a thinned copy kept for the charts (the original activity file was not available)"
    wind = None
    if rec and w and rec.get("lat") and any(v is not None for v in rec["lat"]):
        hw = headwind_series(act, w, data={"t": rec["t"], "lat": rec["lat"], "lon": rec["lon"]})
        wind = hw["series"] if hw else None
    intervals = [b - a for a, b in zip(rec["t"], rec["t"][1:])] if rec else []
    step_s = statistics.median(intervals) if intervals else None
    marks = marked_hr_ranges(rec) if rec else []
    mask = mask_for(rec["t"], marks) if marks else None
    shape = route_shape(rec) if rec else None

    place = act.place if _has(act, "place") else None
    where = f"{place.label}, {place.country}" if place else (act.location_name or "")
    kind = act.kind if act.category == "run" else ""
    kind_name = KIND_NAME.get(kind, "Run")
    start = act.start_local
    title = f"{kind_name}{' in ' + where if where else ''}"
    wx_line = ""
    if w:
        bits = [f"{_n(w.temp_c)}°C"]
        if w.weather_code is not None:
            bits.append(describe(w.weather_code).lower())
        if w.wind_kmh is not None:
            bits.append(f"wind {_n(w.wind_kmh)} km/h from the {compass(w.wind_dir)}")
        wx_line = ", ".join(bits)

    L = []
    add = L.append
    # front matter: the facts a tool can pick up without reading further
    add("---")
    add("file: run exported from Splits (Garmin data) for analysis")
    add(f"title: {title}")
    add(f"date: {start:%Y-%m-%d}")
    add(f"weekday: {start:%A}")
    add(f"start_local_time: \"{start:%H:%M}\"")
    if where:
        add(f"place: {where}")
    if kind:
        add(f"kind: {kind_name}")
    add(f"distance_km: {_n(act.distance_km, 2)}")
    race_secs = act.elapsed_s or act.time_s if kind == "race" else None
    if race_secs:  # a race is timed on the clock, stops included
        add(f"elapsed_time: \"{_dur(race_secs)}\"")
        if act.distance_m:
            add(f"average_pace_per_km: \"{_pace(race_secs / act.distance_km)}\"  # on elapsed time")
    else:
        add(f"moving_time: \"{_dur(act.time_s)}\"")
        if act.pace_s_per_km:
            add(f"average_pace_per_km: \"{_pace(act.pace_s_per_km)}\"")
    if act.avg_hr:
        add(f"average_heart_rate_bpm: {_n(act.avg_hr)}")
    if wx_line:
        add(f"weather: {wx_line}")
    if step_s:
        add(f"recording_interval_s: {_n(step_s, 1)}")
    add("---")
    add("")
    add(f"# {title}")
    add("")
    desc = (f"{'A' if not kind_name[0] in 'AEIOU' else 'An'} {kind_name.lower()} of {_n(act.distance_km, 2)} km"
            f"{' in ' + where if where else ''}, starting at {start:%H:%M} on {start:%A %-d %B %Y} (local time). "
            + (f"Time {_dur(race_secs)} (elapsed, clock time)" if race_secs else f"Moving time {_dur(act.time_s)}"))
    if race_secs and act.distance_m:
        desc += f", average pace {_pace(race_secs / act.distance_km)} per km"
    elif act.pace_s_per_km:
        desc += f", average pace {_pace(act.pace_s_per_km)} per km"
    if act.avg_hr:
        desc += f", average heart rate {_n(act.avg_hr)} bpm (max {_n(act.max_hr)})"
    desc += "."
    if wx_line:
        desc += f" Weather at the time: {wx_line}."
    if act.run_type_reason and kind:
        desc += f" Sorted as a {kind_name.lower()} because: {act.run_type_reason}"
    if shape and shape["shape"] == "out_and_back":
        desc += " The route was an out-and-back."
    elif shape and shape["shape"] == "circuit":
        desc += f" The route was {len(shape['passes']) - 1} laps of a circuit of about {_n(shape['lap_m'], -1 if shape['lap_m'] >= 1000 else 0)} m."
    add(desc)
    add("")
    add("## How to read this file")
    add("")
    add("- Units: distance in km (metres in the per-second table), pace in minutes:seconds per km, speed in metres "
        "per second, heart rate in beats per minute, cadence in steps per minute, power in watts, elevation in "
        "metres, temperature in °C, wind in km/h.")
    add("- Wind direction is where the wind comes from. Headwind is positive, tailwind negative, worked out from "
        "the direction of travel at each point and the wind at that hour.")
    add("- Heart rate zones come from the runner's own Garmin settings. 'Kind' was decided by the app from pace, "
        "heart rate and the runner's own history, unless the runner picked it by hand.")
    add("- Splits per km are worked out by this app from the per-second recording (cadence, power and running "
        "dynamics over moving time only). Laps are the watch's own summaries as Garmin calculates them, so the "
        "two can differ slightly for the same stretch.")
    if marks:
        add("- Some stretches are marked where heart rate did not follow pace (see that section). Heart rate "
            "figures are given with and without them; the file does not say which reading is right.")
    add(f"- The per-second table at the end is CSV: {resolution}.")
    add("- GPS coordinates are left out on purpose.")
    add("")

    # totals
    add("## Totals")
    add("")
    rows = [
        ("Distance", f"{_n(act.distance_km, 2)} km"),
        ("Moving time", _dur(act.time_s)),
        ("Elapsed time", _dur(act.elapsed_s) if act.elapsed_s else ""),
        ("Average pace", f"{_pace(act.pace_s_per_km)} /km" if act.pace_s_per_km else ""),
        ("Fastest pace (max speed)", f"{_pace(1000 / act.max_speed)} /km" if act.max_speed else ""),
        ("Average heart rate", f"{_n(act.avg_hr)} bpm" if act.avg_hr else ""),
        ("Average heart rate without the marked stretches",
         f"{_n(hr_without(rec, 0, len(rec['t']) - 1, mask))} bpm" if mask and hr_without(rec, 0, len(rec['t']) - 1, mask) else ""),
        ("Max heart rate", f"{_n(act.max_hr)} bpm" if act.max_hr else ""),
        ("Average cadence", f"{_n(act.avg_cadence)} spm" if act.avg_cadence else ""),
        ("Max cadence", f"{_n(act.max_cadence)} spm" if act.max_cadence else ""),
        ("Average stride", f"{_n(act.avg_stride_cm)} cm" if act.avg_stride_cm else ""),
        ("Steps", _n(act.steps) if act.steps else ""),
        ("Elevation gain / loss", f"{_n(act.elev_gain_m)} m / {_n(act.elev_loss_m)} m" if act.elev_gain_m is not None else ""),
        ("Average / max power", f"{_n(act.avg_power)} W / {_n(act.max_power)} W" if act.avg_power else ""),
        ("Normalised power", f"{_n(act.norm_power)} W" if act.norm_power else ""),
        ("Calories", f"{_n(act.calories)} kcal" if act.calories else ""),
        ("Aerobic / anaerobic training effect", f"{_n(act.aerobic_te, 1)} / {_n(act.anaerobic_te, 1)}" if act.aerobic_te else ""),
        ("Garmin's label for the session", (act.te_label or "").replace("_", " ").lower()),
        ("Training load (Garmin)", _n(act.training_load) if act.training_load else ""),
        ("VO2max estimate after this run", _n(act.vo2max, 1) if act.vo2max else ""),
        ("Average ground contact time", f"{_n(act.avg_gct_ms)} ms" if act.avg_gct_ms else ""),
        ("Average vertical oscillation", f"{_n(act.avg_vert_osc_cm, 1)} cm" if act.avg_vert_osc_cm else ""),
        ("Average vertical ratio", f"{_n(act.avg_vert_ratio, 1)} %" if act.avg_vert_ratio else ""),
        ("Watch sensor temperature (warmed by the wrist)",
         f"{_n(act.min_temp)} to {_n(act.max_temp)} °C" if act.min_temp is not None else ""),
        ("Recorded with", device.replace("_", " ") if device else ""),
    ]
    for k, v in rows:
        if v:
            add(f"- {k}: {v}")
    add("")

    # zones
    zs, floors = det["zones"], det["floors"]
    if marks and floors:
        every, clean = zone_times(rec, floors), zone_times(rec, floors, mask)
        add("## Time in heart rate zones")
        add("")
        add("From the recorded heart rate, with and without the marked stretches (Garmin's own zone times are in "
            "the Garmin fields further down as hrTimeInZone).")
        add("")
        trows = []
        names = ["Below zone 1"] + ZONE_NAMES
        for z in range(6):
            if z == 0 and not every[0]:
                continue
            rng = f"under {_n(floors[0])}" if z == 0 else (f"{_n(floors[z - 1])} to {_n(floors[z] - 1)}" if z < 5 else f"{_n(floors[4])} to max")
            trows.append((names[z], rng, _dur(every[z]), f"{_n(100 * every[z] / (sum(every) or 1))}%",
                          _dur(clean[z]), f"{_n(100 * clean[z] / (sum(clean) or 1))}%"))
        add(_table(["Zone", "bpm", "Time, all", "Share, all", "Time, without marked", "Share, without marked"], trows))
        add("")
    elif zs and floors and sum(zs):
        add("## Time in heart rate zones")
        add("")
        total = sum(zs)
        trows = []
        for i, secs in enumerate(zs):
            top = f"{_n(floors[i + 1] - 1)}" if i < 4 else "max"
            trows.append((ZONE_NAMES[i], f"{_n(floors[i])} to {top}", _dur(secs), f"{_n(100 * secs / total)}%"))
        add(_table(["Zone", "bpm", "Time", "Share"], trows))
        add("")

    if marks:
        add("## Stretches where heart rate did not follow pace")
        add("")
        add("Marked where, after the first 5 minutes, heart rate moved more than 25 bpm within 30 seconds while "
            "pace stayed within 15 %. The stretch at the lower level is marked, from its start until heart rate "
            "came back. They are flagged in the per-second table (hr_marked = 1). In the tables below, 'without "
            "marked' is left blank where less than a quarter of that stretch was left.")
        add("")
        trows = []
        t_, d_ = rec["t"], rec["d"]
        for a, b in marks:
            i0 = next(k for k, tt in enumerate(t_) if tt >= a)
            i1 = max(k for k, tt in enumerate(t_) if tt <= b)
            st = seg_stats(rec, i0, i1)
            after = _wmean(rec, "hr", i1, min(i1 + 60, len(t_) - 1))
            trows.append((_dur(a), _dur(b), _dur(b - a), _n((d_[i0] or 0) / 1000, 2), _n((d_[i1] or 0) / 1000, 2),
                          _pace(st["pace"]), _n(st["hr"]), _n(after)))
        add(_table(["From", "To", "Length", "From km", "To km", "Pace /km", "Avg HR in it", "Avg HR in the minute after"], trows))
        add("")

    # kind
    if kind:
        add(f"## Why it counts as a {kind_name.lower()}")
        add("")
        add(act.run_type_reason or "Picked by hand.")
        if act.run_type_manual:
            add("")
            add(f"The runner set this by hand (the app's own guess was: {KIND_NAME.get(act.run_type, act.run_type)}).")
        info = act.run_type_info or {}
        refs = []
        if info.get("easy_pace"):
            refs.append(f"easy pace {_pace(info['easy_pace'])} /km (from {info.get('easy_source', 'recent runs')})")
        if info.get("fast_pace"):
            refs.append(f"'fast' means quicker than {_pace(info['fast_pace'])} /km")
        if info.get("usual_km"):
            refs.append(f"usual run length {_n(info['usual_km'], 1)} km over the six weeks before")
        if refs:
            add("")
            add("Reference values at the time: " + "; ".join(refs) + ".")
        if det["blocks"]:
            add("")
            add("Fast blocks found in the pace trace:")
            add("")
            add(_table(["#", "Starts at km", "Time", "Distance m", "Pace /km", "Avg HR"],
                       [(i + 1, _n(b.get("at"), 2), _dur(b.get("dur")), _n(b.get("dist")), _pace(b.get("pace")), _n(b.get("hr")))
                        for i, b in enumerate(det["blocks"])]))
        add("")

    dec = decoupling(rec, kind, det["blocks"], mask, wind) if rec else None
    if dec:
        h1, h2 = dec["halves"]
        add("## Aerobic decoupling")
        add("")
        add(f"Pace against heart rate in the first half of the steady running compared with the second half, from "
            f"{_dur(h1['from'])} to {_dur(h2['to'])}"
            f"{' (before the fast finish)' if dec['cut_at_block'] else ''}"
            f"{', leaving out the marked heart rate stretches' if mask else ''}. Moving time only.")
        add("")
        add(_table(["Half", "From", "To", "Pace /km", "Avg HR", "Metres per heartbeat", "Power W", "Up m", "Down m", "Headwind km/h"],
                   [(name, _dur(h["from"]), _dur(h["to"]), _pace(1000 / h["spd"]), _n(h["hr"]), _n(h["ef"], 3),
                     _n(h["pwr"]), _n(h["up"]), _n(h["down"]), _n(h["wind"], 1))
                    for name, h in (("First", h1), ("Second", h2))]))
        add("")
        add(f"- Decoupling, pace to heart rate: {_n(dec['pa_hr'], 1)} % (positive means heart rate rose for the same pace)")
        if dec.get("pw_hr") is not None:
            add(f"- Decoupling, power to heart rate: {_n(dec['pw_hr'], 1)} %")
        add("- Common reading (Joe Friel): under 5 % means the pace was well within the runner's aerobic "
            "endurance. Hills, wind, heat and drinking also move it.")
        add("")

    # weather
    if w:
        add("## Weather")
        add("")
        add("Model data from Open-Meteo for the area at the time (not a weather station on the route), "
            "taken at the middle of the run.")
        add("")
        hs, cost = heat_cost(w.temp_c, w.dew_point_c)
        rows = [
            ("Conditions", describe(w.weather_code) if w.weather_code is not None else ""),
            ("Temperature", f"{_n(w.temp_c, 1)} °C (feels like {_n(w.feels_c, 1)} °C)" if w.temp_c is not None else ""),
            ("Humidity / dew point", f"{_n(w.humidity)} % / {_n(w.dew_point_c, 1)} °C" if w.humidity is not None else ""),
            ("Heat effect (rule of thumb on temperature + dew point)",
             f"{_n(hs, 1)} °C combined: {cost} (slowing starts from about 20 °C combined)" if hs is not None else ""),
            ("Rain during the run", f"{_n(w.precip_mm, 1)} mm" if w.precip_mm else "none"),
            ("Cloud cover", f"{_n(w.cloud_pct)} %" if w.cloud_pct is not None else ""),
            ("Wind", f"{_n(w.wind_kmh)} km/h from {compass(w.wind_dir)} ({_n(w.wind_dir)}°), gusts up to {_n(w.gust_kmh)} km/h"
             if w.wind_kmh is not None else ""),
            ("Headwind along the route", (f"{_n(w.headwind_kmh, 1)} km/h on average (negative is tailwind), into the wind "
                                          f"{_n((w.headwind_share or 0) * 100)} % of the time") if w.headwind_kmh is not None else ""),
            ("Pressure", f"{_n(w.pressure_msl)} hPa at sea level, {_n(w.pressure_surface)} hPa on the ground"
             if w.pressure_msl is not None else ""),
            ("Visibility", f"{_n((w.visibility_m or 0) / 1000, 1)} km" if w.visibility_m else ""),
            ("Ground height of the weather grid", f"{_n(w.grid_elevation)} m" if w.grid_elevation is not None else ""),
        ]
        for k, v in rows:
            if v:
                add(f"- {k}: {v}")
        h = w.hourly or {}
        if h.get("time"):
            cols = [("time", "time_utc"), ("temperature_2m", "temp_c"), ("apparent_temperature", "feels_c"),
                    ("relative_humidity_2m", "humidity_pct"), ("dew_point_2m", "dew_point_c"),
                    ("precipitation", "precip_mm"), ("weather_code", "weather_code"), ("cloud_cover", "cloud_pct"),
                    ("wind_speed_10m", "wind_kmh"), ("wind_gusts_10m", "gust_kmh"), ("wind_direction_10m", "wind_from_deg"),
                    ("pressure_msl", "pressure_hpa"), ("visibility", "visibility_m")]
            cols = [c for c in cols if h.get(c[0])]
            add("")
            add("Hour by hour around the run (each value covers the hour up to that time, UTC):")
            add("")
            add("```csv")
            add(",".join(c[1] for c in cols))
            for i in range(len(h["time"])):
                add(",".join(str(h[c[0]][i]).replace("T", " ") if c[0] == "time" else _n(h[c[0]][i], 1) for c in cols))
            add("```")
        add("")

    # splits
    splits = km_splits(rec, wind, mask) if rec else []
    if splits:
        add("## Splits per km")
        add("")
        add("Worked out by this app from the per-second recording. Heart rate is time-weighted over the whole km; "
            "cadence, power and running dynamics count moving time only.")
        add("")
        has = {k: any(s[k] is not None for s in splits) for k in ("hr", "cad", "pwr", "gct", "step", "vo", "wind")}
        any_marked = any(s["marked"] for s in splits)
        head = ["Km", "Distance m", "Time", "Pace /km", "Avg HR", "Avg HR without marked", "Max HR", "Cadence",
                "Power W", "Up m", "Down m", "GCT ms", "Step mm", "Vert osc mm", "Headwind km/h"]
        keep = [True, True, True, True, has["hr"], any_marked, has["hr"], has["cad"], has["pwr"], True, True,
                has["gct"], has["step"], has["vo"], has["wind"]]
        trows = []
        for i, s in enumerate(splits):
            row = [i + 1, _n(s["dist"]), _dur(s["secs"]), _pace(s["pace"]), _n(s["hr"]),
                   _n(s["hr_clean"]) if s["marked"] else _n(s["hr"]), _n(s["max_hr"]), _n(s["cad"]),
                   _n(s["pwr"]), _n(s["up"]), _n(s["down"]), _n(s["gct"]), _n(s["step"]), _n(s["vo"], 1),
                   _n(s["wind"], 1)]
            trows.append([c for c, k in zip(row, keep) if k])
        add(_table([h_ for h_, k in zip(head, keep) if k], trows))
        add("")

    if shape:
        t_ = rec["t"]

        def row(name, i0, i1):
            st = seg_stats(rec, i0, i1, wind, mask)
            return (name, _dur(t_[i0]), _n(st["dist"]), _dur(st["secs"]), _pace(st["pace"]), _n(st["hr"]),
                    _n(st["hr_clean"]) if st["marked"] else _n(st["hr"]), _n(st["cad"]), _n(st["pwr"]),
                    _n(st["up"]), _n(st["down"]), _n(st["wind"], 1))
        head = ["Part", "Starts at", "Distance m", "Time", "Pace /km", "Avg HR", "Avg HR without marked", "Cadence",
                "Power W", "Up m", "Down m", "Headwind km/h"]
        keep = [True] * 6 + [bool(mask)] + [True] * 5
        sub = lambda rows: [[c for c, k in zip(r_, keep) if k] for r_ in rows]
        head = [h_ for h_, k in zip(head, keep) if k]
        if shape["shape"] == "out_and_back":
            add("## Out and back")
            add("")
            add("Found from the GPS track: the route turns round near half way and comes back the same way. "
                "The two halves, split at the turning point:")
            add("")
            add(_table(head, sub([row("Out", 0, shape["turn"]), row("Back", shape["turn"], len(t_) - 1)])))
        else:
            ps = shape["passes"]
            add("## Laps of the circuit")
            add("")
            add(f"Found from the GPS track: {len(ps) - 1} laps of the same circuit, about "
                f"{_n(shape['lap_m'])} m each, counted each time the route passed the same point. "
                "These are not the watch's laps.")
            add("")
            rows_ = []
            if ps[0] > 0 and t_[ps[0]] >= 30:
                rows_.append(row("Before the first lap", 0, ps[0]))
            rows_ += [row(f"Lap {k + 1}", a, b) for k, (a, b) in enumerate(zip(ps, ps[1:]))]
            if len(t_) - 1 - ps[-1] > 30:
                rows_.append(row("After the last lap", ps[-1], len(t_) - 1))
            add(_table(head, sub(rows_)))
        add("")

    # laps
    if fit_laps and len(fit_laps) > 1:
        add("## Laps (as recorded by the watch)")
        add("")
        add("The watch's own lap summaries, as Garmin calculates them"
            f"{'; heart rate without the marked stretches is worked out from the recording' if mask else ''}.")
        add("")
        t_ = rec["t"]
        clean_hr = []
        for l in fit_laps:
            a = l["start"] or 0
            b = a + (l["secs"] or 0)
            ks = [k for k, tt in enumerate(t_) if a <= tt < b]
            clean_hr.append(hr_without(rec, ks[0], ks[-1], mask) if mask and ks and any(mask[k] for k in ks) else False)
        head = ["Lap", "Starts at", "Time", "Distance m", "Pace /km", "Avg HR", "Avg HR without marked", "Max HR",
                "Cadence", "Power W", "Up m", "Down m", "Type", "Ended by"]
        keep = [True] * 6 + [any(v is not False for v in clean_hr)] + [True] * 7
        trows = []
        for i, l in enumerate(fit_laps):
            r_ = [i + 1, _dur(l["start"]), _dur(l["secs"]), _n(l["dist"]),
                  _pace(l["secs"] / (l["dist"] / 1000)) if l["dist"] and l["secs"] else "",
                  _n(l["avg_hr"]), _n(l["avg_hr"]) if clean_hr[i] is False else _n(clean_hr[i]), _n(l["max_hr"]),
                  _n(l["cad"]), _n(l["pwr"]), _n(l["up"]), _n(l["down"]), l["intensity"], l["trigger"].replace("_", " ")]
            trows.append([c for c, k in zip(r_, keep) if k])
        add(_table([h_ for h_, k in zip(head, keep) if k], trows))
        add("")
    elif det["laps"] and len(det["laps"]) > 1:
        add("## Laps (as recorded by the watch)")
        add("")
        add(_table(["Lap", "Starts at", "Time", "Distance m", "Pace /km", "Avg HR", "Max HR", "Cadence", "Up m", "Down m"],
                   [(l.index, _dur(l.start_offset_s), _dur(l.duration_s), _n(l.distance_m), _pace(l.pace_s_per_km),
                     _n(l.avg_hr), _n(l.max_hr), _n(l.avg_cadence), _n(l.elev_gain_m), _n(l.elev_loss_m))
                    for l in det["laps"]]))
        add("")

    # best efforts
    if det["efforts"]:
        add("## Best efforts inside this run")
        add("")
        add(_table(["Distance", "Time", "Pace /km", "Starts at", "Rank among all the runner's efforts",
                    "Personal best at the time"],
                   [(e["label"], _dur(e["secs"]), _pace(e["secs"] / (e["dist"] / 1000)), _dur(e["start"]),
                     e["rank"], "yes" if e["pb_then"] else "no") for e in det["efforts"]]))
        add("")

    # compared with the 90 days before
    c = det["compare"]
    if c:
        add("## Compared with the runner's 90 days before")
        add("")
        add(f"- {'Runs of the same kind' if c.get('kind') else 'Runs'} in those 90 days: {c['n']}")
        if c.get("dist_avg"):
            add(f"- Their average distance: {_n(c['dist_avg'], 1)} km; this run was longer than {c['longer_than']} % of them")
        if c.get("pace_avg"):
            add(f"- Their median pace: {_pace(c['pace_avg'])} /km")
        if c.get("hr_avg"):
            add(f"- Their average heart rate: {_n(c['hr_avg'])} bpm")
        add("")

    # a race or time trial: the earlier ones on the same course, or else in the same place
    if kind == "race":
        from .analytics import kind_q
        from .courses import find_courses
        course = next((c for c in find_courses() if act.pk in c["runs"]), None)
        if course:
            earlier = Activity.objects.filter(pk__in=course["runs"], start_local__lt=start)
            scope = f"on the same course ({course['name']}, matched from the GPS track)"
        elif place:
            earlier = Activity.objects.filter(kind_q("race"), category="run", place=place, start_local__lt=start)
            scope = f"in {place.label} (any course)"
        else:
            earlier = Activity.objects.none()
        earlier = list(earlier.select_related("weather").order_by("-start_local")[:10])
        if earlier:
            add("## Earlier races and time trials " + scope)
            add("")
            add("Most recent first, up to 10. Time is clock time (elapsed).")
            add("")
            trows = []
            for r in earlier:
                rw = r.wx
                secs = r.elapsed_s or r.time_s
                trows.append((f"{r.start_local:%a %Y-%m-%d %H:%M}", _n(r.distance_km, 2), _dur(secs),
                              _pace(secs / r.distance_km) if r.distance_m else "", _n(r.avg_hr), _n(r.max_hr),
                              _n(rw.temp_c) if rw else "", _n(rw.wind_kmh) if rw else "",
                              _n(rw.headwind_kmh, 1) if rw and rw.headwind_kmh is not None else ""))
            add(_table(["Date", "Km", "Time", "Pace /km", "Avg HR", "Max HR", "Temp °C", "Wind km/h",
                        "Avg headwind km/h"], trows))
            add("")

    # the runner's training plan around this day, when one was imported
    from . import plan as P
    around = P.by_day(start.date() - timedelta(days=6), start.date() + timedelta(days=7))
    if around:
        today_plan = around.get(start.date(), [])
        add("## Training plan")
        add("")
        if today_plan:
            for ps in today_plan:
                bits = [ps.title or P.label(ps.kind), f"kind {P.label(ps.kind).lower()}"]
                if ps.distance_km:
                    bits.append(f"{_n(ps.distance_km, 1)} km")
                if ps.duration_min:
                    bits.append(f"{_n(ps.duration_min)} min")
                if ps.pace:
                    bits.append(f"pace {ps.pace} /km")
                add(f"- Planned for this day: {', '.join(bits)}" + (f". {ps.description}" if ps.description else ""))
        else:
            add("- Nothing was planned for this day.")
        add("")
        add("The plan for the week before and the week after (from the runner's imported plan):")
        add("")
        trows = []
        for d in sorted(around):
            for ps in around[d]:
                trows.append((f"{d:%a %Y-%m-%d}", P.label(ps.kind), ps.title, _n(ps.distance_km, 1) if ps.distance_km else "",
                              ps.pace, (ps.description or "").replace("|", "/")[:140]))
        add(_table(["Date", "Kind", "Title", "Km", "Pace", "Details"], trows))
        add("")

    # the races the runner has entered, from this day on
    from .models import Race
    ahead = list(Race.objects.filter(date__gte=start.date(), date__lte=start.date() + timedelta(days=180)).order_by("date")[:3])
    if ahead:
        add("## Races ahead (entered by the runner)")
        add("")
        for r in ahead:
            gap = (r.date - start.date()).days
            when = "the same day as this run" if gap == 0 else f"{gap} day{'s' if gap != 1 else ''} after this run"
            add(f"- {r.name}: {r.date:%a %Y-%m-%d}, {when}, "
                f"{_n(r.distance_km, 2)} km{', ' + r.location if r.location else ''}"
                f"{', goal ' + _dur(r.goal_s) if r.goal_s else ''}")
        add("")

    # training context
    add("## Training context")
    add("")
    runs = Activity.objects.filter(category="run", start_local__lt=start).order_by("-start_local")
    weeks = []
    for k in range(4):
        a, b = start - timedelta(days=7 * (k + 1)), start - timedelta(days=7 * k)
        sel = [r for r in runs if a <= r.start_local < b]
        weeks.append((f"{k * 7 + 1} to {k * 7 + 7} days before", len(sel), _n(sum(r.distance_km for r in sel), 1),
                      _dur(sum(r.time_s for r in sel)), _n(max((r.distance_km for r in sel), default=0), 1)))
    add("Running in the four weeks before:")
    add("")
    add(_table(["Window", "Runs", "Km", "Time", "Longest km"], weeks))
    add("")
    recent = [r for r in runs if r.start_local >= start - timedelta(days=14)]
    if recent:
        add("Every run in the 14 days before:")
        add("")
        add(_table(["Date", "Kind", "Km", "Time", "Pace /km", "Avg HR"],
                   [(f"{r.start_local:%a %Y-%m-%d %H:%M}", KIND_NAME.get(r.kind, ""), _n(r.distance_km, 2),
                     _dur(r.time_s), _pace(r.pace_s_per_km), _n(r.avg_hr)) for r in reversed(recent)]))
        add("")
    pbs = []
    for dist in (1000, 1609, 5000, 10000, 21097, 42195):
        e = (BestEffort.objects.filter(category="run", distance_m=dist, date__lt=start.date())
             .order_by("seconds").first())
        if e:
            pbs.append((BEST_EFFORT_LABELS.get(dist, f"{dist} m"), _dur(e.seconds), _pace(e.seconds / (dist / 1000)),
                        f"{e.date:%Y-%m-%d}"))
    if pbs:
        add("Personal bests before this run (fastest stretch inside any run):")
        add("")
        add(_table(["Distance", "Time", "Pace /km", "Date"], pbs))
        add("")
    day = start.date()
    body = []
    sl = SleepNight.objects.filter(date=day).first()
    if sl and sl.total_s:
        bits = [f"{_hm(sl.total_s)} asleep"]
        if sl.score:
            bits.append(f"score {_n(sl.score)}")
        if sl.deep_s is not None:
            bits.append(f"deep {_hm(sl.deep_s)}, REM {_hm(sl.rem_s)}, awake {_hm(sl.awake_s)}")
        if sl.need_min:
            bits.append(f"Garmin's sleep need {_hm(sl.need_min * 60)}")
        body.append(("Sleep the night before", ", ".join(bits)))
    hv = HrvDay.objects.filter(date=day).first()
    if hv and hv.last_night:
        rng = f", normal range {_n(hv.baseline_low)} to {_n(hv.baseline_high)} ms" if hv.baseline_low else ""
        body.append(("HRV that night", f"{_n(hv.last_night)} ms (7-day average {_n(hv.weekly_avg)}{rng}"
                                       f"{', status ' + hv.status.lower() if hv.status else ''})"))
    ds = DailySummary.objects.filter(date=day).first()
    if ds:
        if ds.resting_hr:
            body.append(("Resting heart rate that day", f"{_n(ds.resting_hr)} bpm"))
        if ds.bb_max is not None:
            body.append(("Body battery that day", f"high {_n(ds.bb_max)}, low {_n(ds.bb_min)}"))
        if ds.avg_stress is not None:
            body.append(("Average stress that day", _n(ds.avg_stress)))
    vo = Vo2Max.objects.filter(sport="running", date__lt=day).order_by("-date").first()
    if vo:
        body.append(("VO2max before this run", f"{_n(vo.value, 1)} ({vo.date:%Y-%m-%d})"))
    if body:
        add("The runner's body around that day (Garmin estimates):")
        add("")
        for k, v in body:
            add(f"- {k}: {v}")
        add("")

    # every Garmin summary field, as Garmin names it
    flat = []

    def walk(d, prefix=""):
        for k, v in d.items():
            key = prefix + k
            if PRIVATE_KEYS.search(k):
                continue
            if isinstance(v, dict):
                walk(v, key + ".")
            elif isinstance(v, (list, tuple)) or v is None or v is False or v == "":
                continue
            else:
                flat.append((key, _n(v, 3) if isinstance(v, float) else v))
    walk(act.raw or {})
    if flat:
        add("## Every summary field from Garmin")
        add("")
        add("As Garmin reports them (speeds in m/s, times in seconds, distances in metres).")
        add("")
        for k, v in flat:
            add(f"- {k}: {v}")
        add("")

    # every second
    if rec and rec.get("t"):
        cols = [("t", "t_s", 1), ("d", "dist_m", 1), ("spd", "speed_ms", 2), ("hr", "hr", 0), ("cad", "cadence_spm", 0),
                ("pwr", "power_w", 0), ("alt", "alt_m", 1), ("vo", "vert_osc_mm", 1), ("gct", "gct_ms", 0),
                ("vr", "vert_ratio_pct", 1), ("step", "step_mm", 0), ("resp", "breaths_min", 0), ("tmp", "watch_temp_c", 0)]
        cols = [c for c in cols if rec.get(c[0]) and any(v is not None for v in rec[c[0]])]
        series = [rec[c[0]] for c in cols]
        names = [c[1] for c in cols]
        dps = [c[2] for c in cols]
        if wind:
            series.append(wind)
            names.append("headwind_kmh")
            dps.append(1)
        if mask:
            series.append([1 if m else None for m in mask])
            names.append("hr_marked")
            dps.append(0)
        lap_of = None
        if fit_laps:
            starts = [l["start"] or 0 for l in fit_laps]
            lap_of, j = [], 0
            for tt in rec["t"]:
                while j + 1 < len(starts) and tt >= starts[j + 1]:
                    j += 1
                lap_of.append(j + 1)
            series.append(lap_of)
            names.append("lap")
            dps.append(0)
        add(f"## Every recorded point ({len(rec['t'])} rows)")
        add("")
        add(f"Resolution: {resolution}"
            f"{', about one row every ' + _n(step_s, 1) + ' s' if step_s else ''}. "
            "t_s is seconds from the start; empty cells mean the watch recorded no value.")
        add("")
        add("```csv")
        add(",".join(names))
        for i in range(len(rec["t"])):
            add(",".join(_n(s[i], dp) if i < len(s) else "" for s, dp in zip(series, dps)))
        add("```")
        add("")
    return "\n".join(L)


# ---------- the same analysis for the activity page (worked out once, kept with the stream) ----------
ANALYSIS_VERSION = 1


def _nearest_index(src_t, dst_t):
    """For every time in dst_t, the index of the closest time in src_t (both sorted)."""
    out, j = [], 0
    for tt in dst_t:
        while j + 1 < len(src_t) and abs(src_t[j + 1] - tt) <= abs(src_t[j] - tt):
            j += 1
        out.append(j)
    return out


def page_analysis(act):
    """Running dynamics as chart channels, marked heart rate stretches, the out-and-back halves or circuit
    laps and aerobic decoupling, for the activity page. Worked out from the activity file the first time the
    page is opened and stored with the chart data."""
    from .weather import headwind_series
    stream = act.stream if _has(act, "stream") else None
    if not stream or not (stream.data or {}).get("t") or act.category != "run":
        return None
    data = stream.data
    cached = data.get("_analysis")
    if cached and cached.get("v") == ANALYSIS_VERSION:
        return cached
    full = full_recording(act)
    rec = full[0] if full else stored_recording(act)
    if not rec or not rec.get("t"):
        return None
    w = act.wx
    wind = None
    if w and rec.get("lat") and any(v is not None for v in rec["lat"]):
        hw = headwind_series(act, w, data={"t": rec["t"], "lat": rec["lat"], "lon": rec["lon"]})
        wind = hw["series"] if hw else None
    marks = marked_hr_ranges(rec)
    mask = mask_for(rec["t"], marks) if marks else None
    out = {"v": ANALYSIS_VERSION, "marks": [[a, b] for a, b in marks]}

    def row(name, i0, i1):
        st = seg_stats(rec, i0, i1, wind, mask)
        return {"name": name, "start": rec["t"][i0], "dist": st["dist"], "secs": st["secs"], "pace": st["pace"],
                "hr": st["hr"], "hr_clean": st["hr_clean"] if st["marked"] else None, "cad": st["cad"],
                "pwr": st["pwr"], "up": st["up"], "down": st["down"], "wind": st["wind"]}
    shape = route_shape(rec)
    if shape and shape["shape"] == "out_and_back":
        out["shape"] = {"kind": "out_and_back", "rows": [row("Out", 0, shape["turn"]),
                                                         row("Back", shape["turn"], len(rec["t"]) - 1)]}
    elif shape:
        ps, t = shape["passes"], rec["t"]
        rows = [row(f"Lap {k + 1}", a, b) for k, (a, b) in enumerate(zip(ps, ps[1:]))]
        if ps[0] > 0 and t[ps[0]] >= 30:
            rows.insert(0, row("Before the first lap", 0, ps[0]))
        if len(t) - 1 - ps[-1] > 30:
            rows.append(row("After the last lap", ps[-1], len(t) - 1))
        out["shape"] = {"kind": "circuit", "lap_m": shape["lap_m"], "laps": len(ps) - 1, "rows": rows}
    dec = decoupling(rec, act.kind, (act.run_type_info or {}).get("blocks") or [], mask, wind)
    if dec:
        out["decoupling"] = dec
    # running dynamics, thinned to the chart's own points
    if full:
        idx = _nearest_index(rec["t"], data["t"])
        for key in ("gct", "vo", "vr", "step"):
            vals = rec.get(key) or []
            if any(v for v in vals):
                data[key] = [round(vals[i], 1) if vals[i] else None for i in idx]
    data["_analysis"] = out
    stream.data = data
    stream.save(update_fields=["data"])
    return out
