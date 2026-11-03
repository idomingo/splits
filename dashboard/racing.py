"""Race predictions: Jack Daniels' VDOT and Pete Riegel's formula.

VDOT (Daniels and Gilbert, "Oxygen Power", 1979) turns a race result into an effective VO2max from two
equations: the oxygen cost of running at a speed, and the share of VO2max a runner can hold for a duration.
A VDOT then predicts a time for any other distance, and the paces to train at.

Riegel (1977): T2 = T1 x (D2 / D1) ^ 1.06. Simple, and a little optimistic for long races when the result
it starts from is short, which is why both are shown.
"""
import math
from datetime import date, timedelta

RIEGEL_EXP = 1.06
# training intensities as a share of VDOT (Daniels' Running Formula, approximate)
TRAINING = [("Easy", 0.62, 0.70, "most of your running"), ("Marathon", 0.80, 0.80, "marathon race pace"),
            ("Threshold", 0.88, 0.88, "comfortably hard, 20 to 30 minutes in all"),
            ("Interval", 0.98, 0.98, "3 to 5 minute repeats"), ("Repetition", 1.05, 1.05, "short fast repeats, 200 to 400 m")]


def _vo2_cost(v):
    """Oxygen cost (ml/kg/min) of running at v metres per minute."""
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _share(t_min):
    """Share of VO2max that can be held for t minutes."""
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(dist_m, secs):
    if not dist_m or not secs or secs <= 0:
        return None
    t = secs / 60.0
    return _vo2_cost(dist_m / t) / _share(t)


def time_for(vdot_value, dist_m):
    """Seconds to run dist_m at this VDOT (bisection on the time)."""
    if not vdot_value:
        return None
    lo, hi = dist_m / 1000 * 120.0, dist_m / 1000 * 1200.0  # 2:00 to 20:00 per km
    for _ in range(60):
        mid = (lo + hi) / 2
        if vdot(dist_m, mid) > vdot_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def speed_at(vdot_value, share):
    """Metres per minute at which the oxygen cost is this share of VDOT."""
    target = vdot_value * share
    a, b, c = 0.000104, 0.182258, -4.60 - target
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def training_paces(vdot_value):
    out = []
    for name, lo, hi, note in TRAINING:
        fast = 60000.0 / speed_at(vdot_value, hi)
        slow = 60000.0 / speed_at(vdot_value, lo)
        out.append({"name": name, "fast": fast, "slow": slow, "note": note})
    return out


def riegel(secs, dist_from, dist_to, exp=RIEGEL_EXP):
    return secs * (dist_to / dist_from) ** exp


def fitness_source(today=None, days=90):
    """The run that shows the runner's current fitness best: the effort with the highest VDOT over 3 km or
    more in the last 90 days (races first, then best efforts inside any run)."""
    from .analytics import kind_q
    from .models import Activity, BestEffort
    today = today or date.today()
    since = today - timedelta(days=days)
    best = None
    for a in Activity.objects.filter(kind_q("race"), category="run", start_local__date__gte=since,
                                     start_local__date__lte=today, distance_m__gte=2900):
        secs = a.elapsed_s or a.time_s
        v = vdot(a.distance_m, secs)
        if v and (best is None or v > best["vdot"]):
            best = {"vdot": v, "dist": a.distance_m, "secs": secs, "date": a.start_local.date(), "id": a.pk,
                    "what": f"race or time trial of {a.distance_km:.2f} km"}
    races = set(Activity.objects.filter(kind_q("race"), category="run").values_list("activity_id", flat=True))
    for e in BestEffort.objects.filter(category="run", distance_m__gte=3000, date__gte=since, date__lte=today):
        if e.activity_id in races:
            continue  # the race result itself counts, not the fastest stretch inside it
        v = vdot(e.distance_m, e.seconds)
        if v and (best is None or v > best["vdot"]):
            best = {"vdot": v, "dist": e.distance_m, "secs": e.seconds, "date": e.date, "id": e.activity_id,
                    "what": f"best {e.distance_m / 1000:g} km inside a run"}
    return best


def splits(total_secs, dist_m, unit=1000.0):
    """Even splits: [(km mark, split seconds, time at that mark)], the last one partial."""
    out, done = [], 0.0
    pace = total_secs / (dist_m / unit)
    k = 0
    while done < dist_m - 1:
        k += 1
        step = min(unit, dist_m - done)
        done += step
        out.append({"mark": done / 1000.0, "split": pace * step / unit, "at": total_secs * done / dist_m,
                    "partial": step < unit})
    return out


def prediction(dist_m, source=None):
    """Predicted time for a distance by VDOT and by Riegel, from the runner's fitness source."""
    src = source or fitness_source()
    if not src:
        return None
    v_time = time_for(src["vdot"], dist_m)
    r_time = riegel(src["secs"], src["dist"], dist_m)
    return {"source": src, "vdot": src["vdot"], "vdot_time": v_time, "riegel_time": r_time,
            "vdot_pace": v_time / (dist_m / 1000), "riegel_pace": r_time / (dist_m / 1000)}


STANDARD_DISTANCES = [(5000, "5 km"), (10000, "10 km"), (15000, "15 km"), (21097.5, "Half marathon"),
                      (42195, "Marathon")]


def parse_time(text):
    """'1:52:30', '52:30' or '52' (minutes) -> seconds; None when empty or unreadable."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.replace(".", ":").split(":")] if ":" in text else [float(text) * 60]
    except ValueError:
        return None
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs if secs > 0 else None


def matching_activity(race):
    """The race or time trial run on the race day at about the race distance, once it has happened."""
    from .analytics import kind_q
    from .models import Activity
    acts = Activity.objects.filter(category="run", start_local__date=race.date, distance_m__gte=race.distance_m * 0.9,
                                   distance_m__lte=race.distance_m * 1.1)
    return acts.filter(kind_q("race")).first() or acts.order_by("-distance_m").first()


def readiness(race, today=None):
    """Plain facts about the build-up: longest run lately and weekly running distance."""
    from .models import Activity
    today = today or date.today()
    ref = min(today, race.date - timedelta(days=1))
    runs = list(Activity.objects.filter(category="run", start_local__date__gt=ref - timedelta(days=42),
                                        start_local__date__lte=ref).values_list("distance_m", "start_local"))
    longest = max((d or 0 for d, _ in runs), default=0)
    last4 = sum((d or 0) for d, s in runs if s.date() > ref - timedelta(days=28)) / 1000.0 / 4
    return {"longest_km": longest / 1000.0, "longest_share": round(100 * longest / race.distance_m) if longest else 0,
            "weekly_km": last4, "runs_6w": len(runs)}


def race_view(race, today=None):
    """Everything the race page shows."""
    today = today or date.today()
    past = race.date < today
    src = fitness_source(today=min(today, race.date - timedelta(days=1)))
    pred = prediction(race.distance_m, src) if src else None
    goal = race.goal_s
    out = {"race": race, "past": past, "days": (race.date - today).days, "pred": pred, "goal": goal,
           "goal_pace": goal / race.distance_km if goal else None,
           "goal_vdot": vdot(race.distance_m, goal) if goal else None,
           "paces": training_paces(src["vdot"]) if src else [], "ready": readiness(race, today)}
    plans = []
    if goal:
        plans.append(("Goal", goal))
    if pred:
        plans += [("VDOT", pred["vdot_time"]), ("Riegel", pred["riegel_time"])]
    names = [p[0] for p in plans]
    marks = splits(plans[0][1], race.distance_m) if plans else []
    rows = []
    for i, m in enumerate(marks):
        rows.append({"mark": m["mark"], "partial": m["partial"],
                     "cells": [{"at": t * m["mark"] * 1000 / race.distance_m, "pace": t / race.distance_km} for _n, t in plans]})
    out["split_names"], out["split_rows"] = names, rows
    if past:
        act = matching_activity(race)
        if act:
            secs = act.elapsed_s or act.time_s
            out["result"] = {"id": act.pk, "secs": secs, "pace": secs / act.distance_km, "vdot": vdot(act.distance_m, secs),
                             "vs_vdot": secs - pred["vdot_time"] if pred else None,
                             "vs_riegel": secs - pred["riegel_time"] if pred else None,
                             "vs_goal": secs - goal if goal else None}
            r = out["result"]
            if pred:
                # faster than both predictions, than one, or slower than both
                beat = (r["vs_vdot"] < 0) + (r["vs_riegel"] < 0)
                r["verdict"] = ("better", "mixed", "worse")[2 - beat]
                r["verdict_text"] = ("Faster than both predictions", "Faster than one of the predictions",
                                     "Slower than both predictions")[2 - beat]
                r["verdict_short"] = ("Faster", "Faster than one", "Slower")[2 - beat]
                r["verdict_icon"] = ("\u2714\u2714", "\u2714", "\u2716")[2 - beat]  # two ticks, one tick, a cross
            if goal:
                r["goal_hit"] = secs <= goal
                r["goal_diff"] = abs(secs - goal)
    return out
