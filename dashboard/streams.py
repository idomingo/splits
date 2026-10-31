"""Turn full-resolution samples into what the pages need: down-sampled
series, per-km splits, best efforts, route outline and time in HR zones.

Input: dict of equal-length lists keyed t (s from start), d (m), hr, spd (m/s),
cad, alt (m), lat, lon, pwr, tmp. Missing channels may be absent or contain None.
"""
import math

from .sports import BEST_EFFORT_DISTANCES, MAX_PLAUSIBLE_SPEED

CHANNELS = ("t", "d", "hr", "spd", "cad", "alt", "lat", "lon", "pwr", "tmp")
MAX_POINTS = 1500


def _clean_distance(t, d, max_speed):
    """Make distance monotonic and drop GPS jumps faster than max_speed."""
    out = []
    last_d = None
    last_t = None
    offset = 0.0
    for ti, di in zip(t, d):
        if di is None:
            out.append(out[-1] if out else 0.0)
            continue
        if last_d is None:
            last_d, last_t = di, ti
            offset = max(di, 0.0)
            out.append(offset)
            continue
        step = di - last_d
        dt = max(ti - last_t, 1e-6)
        if step < 0:
            step = 0.0
        if max_speed and step / dt > max_speed * 1.5:
            step = 0.0  # glitch
        offset += step
        out.append(offset)
        last_d, last_t = di, ti
    return out


def downsample(samples, max_points=MAX_POINTS):
    n = len(samples.get("t") or [])
    if n == 0:
        return {}
    stride = max(1, math.ceil(n / max_points))
    out = {}
    for ch in CHANNELS:
        vals = samples.get(ch)
        if not vals or all(v is None for v in vals):
            continue
        picked = vals[::stride]
        if ch in ("lat", "lon"):
            out[ch] = [round(v, 6) if v is not None else None for v in picked]
        elif ch in ("t", "d", "alt"):
            out[ch] = [round(v, 1) if v is not None else None for v in picked]
        elif ch == "spd":
            out[ch] = [round(v, 3) if v is not None else None for v in picked]
        else:
            out[ch] = [round(v) if v is not None else None for v in picked]
    # keep last point so totals line up
    if stride > 1:
        for ch in out:
            last = samples[ch][-1]
            if last is not None:
                if ch in ("lat", "lon"):
                    out[ch].append(round(last, 6))
                elif ch in ("t", "d", "alt"):
                    out[ch].append(round(last, 1))
                elif ch == "spd":
                    out[ch].append(round(last, 3))
                else:
                    out[ch].append(round(last))
            else:
                out[ch].append(None)
    return out


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def compute_splits(t, d, hr=None, alt=None, cad=None, unit=1000.0):
    """Per-km splits. Returns list of dicts."""
    splits = []
    if not t or not d or d[-1] < unit * 0.1:
        return splits
    start_i = 0
    target = unit
    n = len(t)
    for i in range(1, n):
        if d[i] >= target:
            # interpolate crossing time
            d0, d1 = d[i - 1], d[i]
            frac = (target - d0) / (d1 - d0) if d1 > d0 else 0
            t_cross = t[i - 1] + frac * (t[i] - t[i - 1])
            t_start = splits[-1]["t_end"] if splits else t[0]
            splits.append(_split_row(len(splits) + 1, unit, t_start, t_cross, start_i, i, hr, alt, cad))
            start_i = i
            target += unit
    # trailing partial
    rest = d[-1] - (target - unit)
    if rest >= unit * 0.1:
        t_start = splits[-1]["t_end"] if splits else t[0]
        splits.append(_split_row(len(splits) + 1, rest, t_start, t[-1], start_i, n, hr, alt, cad))
    return splits


def _split_row(idx, dist, t_start, t_end, i0, i1, hr, alt, cad):
    secs = max(t_end - t_start, 0.0)
    gain = loss = 0.0
    if alt:
        seg = [a for a in alt[i0:i1] if a is not None]
        for a, b in zip(seg, seg[1:]):
            diff = b - a
            if diff > 0:
                gain += diff
            else:
                loss -= diff
    return {
        "n": idx,
        "dist": round(dist, 1),
        "secs": round(secs, 1),
        "pace": round(secs / (dist / 1000.0), 1) if dist > 0 else None,
        "hr": round(_avg(hr[i0:i1])) if hr and _avg(hr[i0:i1]) is not None else None,
        "cad": round(_avg(cad[i0:i1])) if cad and _avg(cad[i0:i1]) is not None else None,
        "gain": round(gain, 1),
        "loss": round(loss, 1),
        "t_end": t_end,
    }


def best_efforts(t, d, distances):
    """Fastest time for each distance (two-pointer, interpolated end)."""
    results = {}
    n = len(t)
    if n < 2 or not d:
        return results
    total = d[-1]
    for target in distances:
        if total < target:
            continue
        best = None
        best_start = 0.0
        j = 1
        for i in range(n - 1):
            goal = d[i] + target
            if goal > total:
                break
            if j <= i:
                j = i + 1
            while j < n and d[j] < goal:
                j += 1
            if j >= n:
                break
            d0, d1 = d[j - 1], d[j]
            frac = (goal - d0) / (d1 - d0) if d1 > d0 else 0
            t_end = t[j - 1] + frac * (t[j] - t[j - 1])
            secs = t_end - t[i]
            if secs > 0 and (best is None or secs < best):
                best = secs
                best_start = t[i]
        if best:
            results[target] = (round(best, 1), round(best_start, 1))
    return results


def route_svg_path(lat, lon, size=100.0, pad=6.0, max_pts=260):
    pts = [(a, b) for a, b in zip(lat or [], lon or []) if a is not None and b is not None]
    if len(pts) < 2:
        return ""
    stride = max(1, math.ceil(len(pts) / max_pts))
    pts = pts[::stride] + [pts[-1]]
    lat0 = sum(p[0] for p in pts) / len(pts)
    k = math.cos(math.radians(lat0))
    xs = [p[1] * k for p in pts]
    ys = [-p[0] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = maxx - minx, maxy - miny
    span = max(w, h)
    if span <= 0:
        return ""
    scale = (size - 2 * pad) / span
    offx = pad + ((size - 2 * pad) - w * scale) / 2
    offy = pad + ((size - 2 * pad) - h * scale) / 2
    parts = []
    for i, (x, y) in enumerate(zip(xs, ys)):
        px = offx + (x - minx) * scale
        py = offy + (y - miny) * scale
        parts.append(("M" if i == 0 else "L") + f"{px:.1f} {py:.1f}")
    return "".join(parts)


def zone_seconds(t, hr, floors):
    """Seconds in each of 5 zones. floors = [z1_floor, z2_floor, ..., z5_floor]."""
    if not t or not hr or not floors or len(floors) < 5:
        return []
    out = [0.0] * 5
    for i in range(1, len(t)):
        h = hr[i]
        if h is None:
            continue
        dt = t[i] - t[i - 1]
        if dt <= 0 or dt > 30:
            continue  # pauses
        if h < floors[0]:
            continue
        z = 0
        for zi in range(5):
            if h >= floors[zi]:
                z = zi
        out[z] += dt
    return [round(x) for x in out]


def process(samples, category, zone_floors=None):
    """Full pipeline. Returns dict with stream, splits, efforts, route, zone_s, summary."""
    t = samples.get("t") or []
    if len(t) < 2:
        return None
    d_raw = samples.get("d")
    has_distance = bool(d_raw) and any(v for v in d_raw if v)
    if has_distance:
        d = _clean_distance(t, d_raw, MAX_PLAUSIBLE_SPEED.get(category))
        samples = dict(samples, d=d)
    else:
        d = None
    if samples.get("cad"):
        # 0 cadence = standing still; treat as a gap, not a value
        samples = dict(samples, cad=[c if c else None for c in samples["cad"]])
    hr = samples.get("hr")
    alt = samples.get("alt")
    cad = samples.get("cad")

    splits = []
    efforts = {}
    if has_distance and d[-1] > 100:
        unit = 5000.0 if category == "cycle" else 1000.0
        splits = compute_splits(t, d, hr, alt, cad, unit=unit)
        dists = BEST_EFFORT_DISTANCES.get(category)
        if dists:
            efforts = best_efforts(t, d, dists)
            vmax = MAX_PLAUSIBLE_SPEED.get(category)
            if vmax:
                efforts = {k: v for k, v in efforts.items() if k / v[0] <= vmax}

    zone_s = zone_seconds(t, hr, zone_floors) if zone_floors else []
    return {
        "stream": downsample(samples),
        "splits": splits,
        "efforts": efforts,
        "route": route_svg_path(samples.get("lat"), samples.get("lon")),
        "zone_s": zone_s,
        "count": len(t),
    }
