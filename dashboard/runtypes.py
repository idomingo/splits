"""Sort runs into session types from the run itself, the runs around it and the
runner's own history. Nothing is tuned to one person: every threshold is either
a property of the run (its heart rate zones, its pace trace) or relative to the
runner's own recent runs and best efforts. Every decision keeps a one-line
reason; a type set by hand on the activity page always wins.

Order of the checks:
1. short runs within 40 minutes of another run the same day: warm-up,
   cool-down, strides
2. races and time trials: marked as a race in Garmin Connect, mostly zone 5,
   or a hard continuous effort at a standard race distance close to your best
3. structured work found in the pace trace: threshold, intervals, progression,
   long runs with a fast finish
4. long runs (90 minutes, or one and a half times your usual run and an hour),
   then steady (zones 3 to 5 without structure), recovery, easy
"""
import statistics
from datetime import timedelta

from .ingest import zone_floors

RUN_TYPES = [
    ("race", "Races & time trials"),
    ("threshold", "Threshold"),
    ("intervals", "Intervals"),
    ("progression", "Progression"),
    ("long", "Long runs"),
    ("steady", "Steady"),
    ("easy", "Easy"),
    ("recovery", "Recovery"),
    ("strides", "Strides"),
    ("warmup", "Warm-up & cool-down"),
]
RUN_TYPE_LABEL = dict(RUN_TYPES)
RULES_VERSION = 4   # raise when the rules change: every run is sorted again once
RUN_TYPE_KEYS = [k for k, _ in RUN_TYPES]

# colour groups (four, so charts stay readable): fixed order = fixed colours
GROUPS = [("easy", "Easy & other"), ("workout", "Workouts"), ("long", "Long runs"), ("race", "Races & time trials")]
GROUP_OF = {"race": "race", "threshold": "workout", "intervals": "workout", "progression": "workout",
            "long": "long", "steady": "easy", "easy": "easy", "recovery": "easy", "strides": "easy", "warmup": "easy"}
GROUP_LABEL = dict(GROUPS)

STANDARD = [(3000, "3 km"), (5000, "5 km"), (10000, "10 km"), (15000, "15 km"), (21097, "half marathon"),
            (42195, "marathon")]
FAST_FACTOR = 1.18      # a stretch counts as fast at 18% quicker than your easy pace
LONG_MIN = 90.0         # always a long run
LONG_FACTOR = 1.5       # ... or this many times your usual run, and at least LONG_MIN_RELATIVE minutes
LONG_MIN_RELATIVE = 60.0
SHORT_MIN = 35.0        # warm-ups, cool-downs and recovery runs are shorter than this
RECOVERY_FACTOR = 0.7   # recovery runs are shorter than this share of your usual run


def pace_str(s):
    if not s:
        return "-"
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def _zone_share(act):
    z = act.zone_seconds
    if not z or not sum(z):
        return None
    tot = float(sum(z))
    return [x / tot for x in z]


def _speed_series(t, d, window=20.0):
    """Speed (m/s) over a ~20 s window ending at each point."""
    out = [None] * len(t)
    j = 0
    for i in range(len(t)):
        while j < i and t[i] - t[j] > window:
            j += 1
        dt = t[i] - t[j]
        if dt >= window * 0.5 and d[i] is not None and d[j] is not None:
            out[i] = (d[i] - d[j]) / dt
    return out


def fast_blocks(stream, fast_speed, merge_gap=30.0, min_len=8.0, hold=0.93):
    """Continuous stretches at or above fast_speed. Once fast, a stretch stays fast
    until the speed drops below hold x fast_speed (so small dips do not split it)."""
    t, d = stream.get("t") or [], stream.get("d") or []
    if len(t) < 10 or not d or not fast_speed:
        return []
    hr = stream.get("hr") or [None] * len(t)
    spd = _speed_series(t, d)
    blocks, cur = [], None
    in_block = False
    for i, v in enumerate(spd):
        fast = v is not None and (v >= fast_speed or (in_block and v >= fast_speed * hold))
        in_block = fast
        if fast:
            if cur and t[i] - cur["t1"] <= merge_gap:
                cur["t1"], cur["i1"] = t[i], i
            else:
                cur = {"t0": t[i] - 20.0 if i else t[i], "t1": t[i], "i0": i, "i1": i}
                blocks.append(cur)
    out = []
    for b in blocks:
        i0, i1 = b["i0"], b["i1"]
        # the 20 s window lags: start the block where the window started
        j0 = i0
        while j0 > 0 and t[j0] > b["t0"]:
            j0 -= 1
        dur = t[i1] - t[j0]
        if dur < min_len:
            continue
        dist = (d[i1] or 0) - (d[j0] or 0)
        hrs = [h for h in hr[j0:i1 + 1] if h]
        out.append({"start": round(t[j0]), "dur": round(dur), "dist": round(dist),
                    "pace": round(dur / (dist / 1000.0), 1) if dist > 0 else None,
                    "hr": round(sum(hrs) / len(hrs)) if hrs else None,
                    "at": round((d[j0] or 0) / 1000.0, 2)})
    return out


class References:
    """Your easy pace and best paces as of a given date, from earlier runs."""

    def __init__(self, runs):
        self.runs = sorted(runs, key=lambda a: a.start_local)

    def easy_pace(self, act):
        since = act.start_local - timedelta(days=60)
        paces = []
        for r in self.runs:
            if r.start_local >= act.start_local:
                break
            if r.start_local < since or not r.pace_s_per_km or (r.distance_m or 0) < 4000:
                continue
            zs = _zone_share(r)
            if zs and zs[0] + zs[1] >= 0.65:
                paces.append(r.pace_s_per_km)
        if len(paces) >= 3:
            return statistics.median(paces), "your easy runs of the last 60 days"
        others = [r.pace_s_per_km for r in self.runs if r.start_local < act.start_local and r.pace_s_per_km
                  and (r.distance_m or 0) >= 4000 and r.start_local >= since]
        if len(others) >= 3:
            return statistics.quantiles(others, n=4)[2], "your usual runs of the last 60 days"
        return (act.pace_s_per_km or 400) * 1.05, "this run"

    def usual_km(self, act):
        """Median distance of your runs over the six weeks before this one (warm-ups and strides left out)."""
        since = act.start_local - timedelta(days=42)
        kms = [r.distance_km for r in self.runs if since <= r.start_local < act.start_local
               and r.distance_km >= 2.0 and (r.kind or "") not in ("warmup", "strides")]
        if len(kms) >= 4:
            return statistics.median(kms)
        kms = [r.distance_km for r in self.runs if r.pk != act.pk and r.distance_km >= 2.0]
        return statistics.median(kms) if len(kms) >= 4 else None

    def race_pace(self, act, dist):
        """Fastest average pace of your earlier races at about this distance (s/km)."""
        paces = [r.pace_s_per_km for r in self.runs if r.start_local < act.start_local and (r.kind or "") == "race"
                 and r.pace_s_per_km and abs((r.distance_m or 0) - dist) <= dist * 0.06]
        return min(paces) if paces else None

    def best_pace(self, act, dist):
        """Best pace (s/km) for a distance from best efforts before this run."""
        from .models import BestEffort
        e = (BestEffort.objects.filter(category="run", distance_m=dist, date__lte=act.start_local.date())
             .exclude(activity=act).order_by("seconds").first())
        return e.seconds / (dist / 1000.0) if e else None


def _neighbours(act, runs):
    start = act.start_local
    end = start + timedelta(seconds=act.elapsed_s or act.duration_s or act.time_s or 0)
    before = after = None
    for r in runs:
        if r.pk == act.pk or r.start_local.date() != start.date():
            continue
        r_end = r.start_local + timedelta(seconds=r.elapsed_s or r.duration_s or r.time_s or 0)
        if r_end <= start + timedelta(minutes=2) and start - r_end <= timedelta(minutes=40):
            before = r
        if r.start_local >= end - timedelta(minutes=2) and r.start_local - end <= timedelta(minutes=40):
            after = after or r
    return before, after


def classify(act, refs, runs, floors=None):
    """Returns (run_type, reason, info)."""
    info = {}
    km = act.distance_km
    mins = (act.time_s or 0) / 60.0
    pace = act.pace_s_per_km
    zs = _zone_share(act)
    z5 = zs[4] if zs else 0.0
    z45 = (zs[3] + zs[4]) if zs else 0.0
    z12 = (zs[0] + zs[1]) if zs else None
    floors = floors or zone_floors()
    stream = act.stream.data if hasattr(act, "stream") and act.stream_id_safe else {}

    # 1. short runs around another run
    before, after = _neighbours(act, runs)
    if km < 0.3:
        return "warmup", f"Very short run ({km * 1000:.0f} m), counted with warm-ups and cool-downs.", info
    if mins < SHORT_MIN and z5 < 0.4:
        if after and (after.distance_m or 0) > (act.distance_m or 0):
            return "warmup", f"Warm-up: {km:.1f} km just before your {after.distance_km:.1f} km run at {after.start_local:%H:%M}.", info
        if before:
            faster = pace and before.pace_s_per_km and pace < before.pace_s_per_km * 0.92
            if km < 1.5 and (faster or "ANAEROBIC" in (act.te_label or "")):
                return "strides", (f"Strides: {km * 1000:.0f} m at {pace_str(pace)}/km right after your "
                                   f"{before.distance_km:.1f} km run."), info
            if not faster and (before.distance_m or 0) > (act.distance_m or 0):
                return "warmup", f"Cool-down: {km:.1f} km straight after your {before.distance_km:.1f} km run.", info

    # 2. races and time trials
    if act.event_type == "race":
        return "race", "Marked as a race in Garmin Connect.", info
    if zs and z5 >= 0.45 and mins >= 12 and km >= 2.5:
        return "race", f"Full effort: {z5 * 100:.0f}% of the time in zone 5 over {km:.1f} km.", info
    standard = next(((dist, label) for dist, label in STANDARD if abs((act.distance_m or 0) - dist) <= dist * 0.06), None)
    if standard and pace:
        dist, label = standard
        best = refs.best_pace(act, dist)
        hard = bool(zs and floors and act.avg_hr and act.avg_hr >= floors[3] and z45 >= 0.75)
        if hard and (best is None or pace <= best * 1.03):
            vs = f"within 3% of your best ({pace_str(best)}/km)" if best else "your first at this distance"
            return "race", (f"Full effort over {label}: {pace_str(pace)}/km, {vs}, "
                            f"{z45 * 100:.0f}% in zones 4 and 5."), info
        raced = refs.race_pace(act, dist)
        if raced and pace <= raced * 1.015:
            return "race", (f"Time trial over {label}: {pace_str(pace)}/km, as fast as your earlier races at this "
                            f"distance ({pace_str(raced)}/km)."), info

    # 3. structure in the pace trace
    easy_pace, easy_src = refs.easy_pace(act)
    fast_pace = easy_pace / FAST_FACTOR
    info.update({"easy_pace": round(easy_pace, 1), "fast_pace": round(fast_pace, 1), "easy_source": easy_src})
    blocks = fast_blocks(stream, 1000.0 / fast_pace) if stream else []
    work = [b for b in blocks if b["dur"] >= 60]
    short = [b for b in blocks if 8 <= b["dur"] <= 45]
    info["blocks"] = work
    total_work = sum(b["dur"] for b in work)
    usual = refs.usual_km(act)
    info["usual_km"] = round(usual, 1) if usual else None
    is_long = mins >= LONG_MIN or (usual is not None and mins >= LONG_MIN_RELATIVE and km >= LONG_FACTOR * usual)
    run_t = (stream.get("t") or [0])[-1] if stream else act.time_s

    if is_long and work and total_work >= 240 and all(b["start"] >= 0.55 * max(run_t, 1) for b in work):
        dist_fast = sum(b["dist"] for b in work)
        return "long", (f"Long run with a fast finish: {km:.1f} km, the last {dist_fast / 1000:.1f} km "
                        f"at {pace_str(_avg_pace(work))}/km."), info
    if len(work) >= 2 and total_work >= 360:
        mean_rep = total_work / len(work)
        reps = f"{len(work)} fast blocks averaging {mean_rep / 60:.1f} min at {pace_str(_avg_pace(work))}/km"
        if mean_rep >= 180:
            return "threshold", f"Threshold: {reps}.", info
        return "intervals", f"Intervals: {reps}.", info
    if len(work) == 1 and work[0]["dur"] >= 8 * 60:
        b = work[0]
        end_frac = (b["start"] + b["dur"]) / max(run_t, 1)
        start_frac = b["start"] / max(run_t, 1)
        if end_frac >= 0.85 and start_frac >= 0.45:
            finish = f"last {b['dist'] / 1000:.1f} km at {pace_str(b['pace'])}/km"
            if is_long:
                return "long", f"Long run with a fast finish: {km:.1f} km, {finish}.", info
            return "progression", f"Progression: {finish} after an easy start.", info
        return "threshold", f"Tempo: {b['dur'] / 60:.0f} min continuous at {pace_str(b['pace'])}/km.", info
    split_prog = _progression(act, easy_pace)
    if split_prog and not is_long:
        return "progression", split_prog, info

    # 4. by length and effort
    if is_long:
        why = (f"{km / usual:.1f} times your usual {usual:.1f} km" if usual and mins < LONG_MIN else f"{LONG_MIN:.0f} minutes or more")
        return "long", f"Long run: {km:.1f} km in {mins:.0f} min ({why}).", info
    if floors and act.avg_hr and zs and act.avg_hr >= floors[2] and (zs[2] + z45) >= 0.6:
        return "steady", (f"Steady: average {act.avg_hr:.0f} bpm, {(zs[2] + z45) * 100:.0f}% of the time in zones 3 to 5 "
                          f"(between easy and threshold)."), info
    strides = f" plus {len(short)} strides" if len(short) >= 3 else ""
    short_run = mins < SHORT_MIN and (usual is None or km <= RECOVERY_FACTOR * usual)
    if short_run and (z12 is None or z12 >= 0.7):
        return "recovery", f"Recovery: short and easy, {km:.1f} km at {pace_str(pace)}/km{strides}.", info
    if z12 is not None:
        return "easy", f"Easy: {z12 * 100:.0f}% of the time in zones 1 and 2{strides}.", info
    return "easy", f"Easy: {km:.1f} km at {pace_str(pace)}/km{strides}.", info


def _avg_pace(blocks):
    dist = sum(b["dist"] for b in blocks)
    dur = sum(b["dur"] for b in blocks)
    return dur / (dist / 1000.0) if dist else None


def _progression(act, easy_pace=None):
    """Steadily faster: last third at least 7% quicker than the first and quicker
    than your easy pace, km by km."""
    stream = getattr(act, "stream", None)
    splits = [s for s in (stream.splits if stream else []) if s.get("pace") and s.get("dist", 0) >= 900]
    if len(splits) < 5:
        return None
    k = len(splits) // 3
    first = statistics.mean(s["pace"] for s in splits[:k])
    last = statistics.mean(s["pace"] for s in splits[-k:])
    middle = statistics.mean(s["pace"] for s in splits[k:-k]) if len(splits) > 2 * k else (first + last) / 2
    if last <= first * 0.93 and middle <= first * 1.01 and (not easy_pace or last <= easy_pace * 0.95):
        return f"Progression: from {pace_str(first)}/km in the first third to {pace_str(last)}/km in the last."
    return None


# heart rate bands for "pace at the same effort": easy running sits in zone 2, tempo and threshold work in
# zones 3 to 4, races in zones 4 to 5 (from the runner's own zones, so the same chart works for anyone)
ZONE_BANDS = [("z2", "Zone 2", 1, 2, 300), ("z34", "Zones 3 to 4", 2, 4, 300), ("z45", "Zones 4 to 5", 3, 5, 180)]


def zone_paces(stream, floors, skip=180.0):
    """Average pace while heart rate was inside each band, leaving out the first 3 minutes (heart rate lags
    behind pace at the start) and stops. Only bands with enough time in them (5 minutes, 3 for zones 4 to 5)."""
    t, d, hr = (stream or {}).get("t"), (stream or {}).get("d"), (stream or {}).get("hr")
    if not t or not d or not hr or not floors or len(floors) < 5:
        return {}
    edges = list(floors) + [10 ** 6]
    acc = {k: [0.0, 0.0, 0.0] for k, *_ in ZONE_BANDS}  # seconds, metres, heartbeats
    for i in range(1, len(t)):
        h, dt = hr[i], (t[i] - t[i - 1])
        if h is None or t[i] < skip or dt <= 0 or dt > 30 or d[i] is None or d[i - 1] is None:
            continue
        dist = d[i] - d[i - 1]
        if dist / dt < 1.6:  # walking or standing
            continue
        for key, _label, lo, hi, _min in ZONE_BANDS:
            if edges[lo] <= h < edges[hi]:
                a = acc[key]
                a[0] += dt
                a[1] += dist
                a[2] += h * dt
    out = {}
    for key, _label, _lo, _hi, min_s in ZONE_BANDS:
        secs, dist, beats = acc[key]
        if secs >= min_s and dist > 0:
            out[key] = {"pace": round(secs / (dist / 1000.0), 1), "secs": round(secs), "hr": round(beats / secs)}
    return out


FRAGMENTS = ("warmup", "strides")
SESSION_GAP = timedelta(minutes=40)


def _end(r):
    return r.start_local + timedelta(seconds=r.elapsed_s or r.duration_s or r.time_s or 0)


def group_sessions(runs=None):
    """Attach warm-ups, cool-downs and strides to the run they belong to: runs on the same day that follow each
    other with at most 40 minutes between one ending and the next starting form one session, and every
    fragment in it points to the nearest main run. Returns how many links changed."""
    from .models import Activity
    if runs is None:
        runs = list(Activity.objects.filter(category="run").order_by("start_local"))
    runs = sorted(runs, key=lambda r: r.start_local)
    clusters, cur = [], []
    for r in runs:
        if cur and (r.start_local.date() != cur[-1].start_local.date() or r.start_local - _end(cur[-1]) > SESSION_GAP):
            clusters.append(cur)
            cur = []
        cur.append(r)
    if cur:
        clusters.append(cur)
    changed = 0
    for cl in clusters:
        mains = [r for r in cl if (r.kind or "") not in FRAGMENTS]
        for r in cl:
            parent = None
            if mains and (r.kind or "") in FRAGMENTS:
                def gap(m):
                    if _end(m) <= r.start_local:
                        return (r.start_local - _end(m)).total_seconds()
                    return max((m.start_local - _end(r)).total_seconds(), 0)
                parent = min(mains, key=gap)
            pid = parent.pk if parent else None
            if r.session_of_id != pid:
                r.session_of_id = pid
                Activity.objects.filter(pk=r.pk).update(session_of=pid)
                changed += 1
    return changed


def session_role(extra, main):
    """'Warm-up', 'Cool-down' or 'Strides' for a fragment of a session."""
    if (extra.kind or "") == "strides":
        return "Strides"
    return "Warm-up" if extra.start_local < main.start_local else "Cool-down"


def classify_runs(qs=None, only_missing=False):
    """Classify running activities in date order. Returns how many changed."""
    from .models import Activity, KeyValue
    if qs is None and not only_missing:
        KeyValue.put("run_rules_version", RULES_VERSION)
    runs = list((qs or Activity.objects.filter(category="run")).select_related("stream").order_by("start_local"))
    for r in runs:
        r.stream_id_safe = _has_stream(r)
    refs = References(runs)
    floors = zone_floors()
    changed = 0
    for act in runs:
        if only_missing and act.run_type:
            continue
        kind, reason, info = classify(act, refs, runs, floors)
        if act.stream_id_safe:
            zp = zone_paces(act.stream.data, floors)
            if zp:
                info["zone_pace"] = zp
            if kind in ("easy", "long", "steady", "recovery"):
                from .export import decoupling, stored_recording
                rec = stored_recording(act)
                dec = decoupling(rec, kind, info.get("blocks") or []) if rec else None
                if dec:
                    info["decoupling"] = round(dec["pa_hr"], 1)
        if (kind, reason) != (act.run_type, act.run_type_reason) or info != act.run_type_info:
            act.run_type, act.run_type_reason, act.run_type_info = kind, reason[:255], info
            act.save(update_fields=["run_type", "run_type_reason", "run_type_info"])
            changed += 1
    if qs is None:
        group_sessions(runs)
    return changed


def _has_stream(act):
    try:
        return act.stream is not None
    except Exception:
        return False
