"""Numbers and series behind each page. Plain Python over the database."""
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import Coalesce

from .ingest import zone_floors
from .models import (Activity, BestEffort, DailySummary, FitnessAge, HrvDay, KeyValue, SleepNight,
                     Vo2Max, WeightDay)
from .sports import (BEST_EFFORT_DISTANCES, BEST_EFFORT_LABELS, CATEGORY_KEYS, CATEGORY_LABEL, CATEGORY_TO_SLUG,
                     PACE_CATEGORIES)

FIELDS = ("activity_id", "name", "category", "type_key", "start_local", "distance_m", "duration_s", "moving_s",
          "elev_gain_m", "avg_hr", "max_hr", "training_load", "avg_cadence", "te_label", "event_type", "calories",
          "avg_speed", "run_type", "run_type_manual", "place_id")


def week_start(d):
    if isinstance(d, datetime):
        d = d.date()
    return d - timedelta(days=d.weekday())


def month_start(d):
    if isinstance(d, datetime):
        d = d.date()
    return d.replace(day=1)


def t_of(row):
    return row["moving_s"] or row["duration_s"] or 0


def kind_q(kind):
    """Runs of one kind: your own choice first, then the classifier's."""
    return Q(run_type_manual=kind) | Q(run_type_manual="", run_type=kind)


def rows(qs=None):
    qs = qs if qs is not None else Activity.objects.all()
    out = list(qs.order_by("start_local").values(*FIELDS))
    for r in out:
        r["kind"] = r["run_type_manual"] or r["run_type"] or ""
    return out


def sports_present():
    present = set(Activity.objects.values_list("category", flat=True).distinct())
    return [c for c in CATEGORY_KEYS if c in present]


# ---------- shared ----------
def totals(items):
    dist = sum((r["distance_m"] or 0) for r in items)
    secs = sum(t_of(r) for r in items)
    elev = sum((r["elev_gain_m"] or 0) for r in items)
    return {"count": len(items), "km": dist / 1000.0, "hours": secs / 3600.0, "secs": secs, "elev": elev}


def ewma(values, span_days):
    k = 2.0 / (span_days + 1)
    out, cur = [], 0.0
    for v in values:
        cur = cur + k * (v - cur)
        out.append(round(cur, 1))
    return out


def boxcar(values, days):
    """Average of the last `days` values (a day without training counts as 0)."""
    out, s = [], 0.0
    for i, v in enumerate(values):
        s += v
        if i >= days:
            s -= values[i - days]
        out.append(round(s / min(i + 1, days), 1))
    return out


def rolling_median(points, window_days=42, min_n=3):
    """points: list of (date, value) sorted. Returns list of (date, median of the window ending there)."""
    out = []
    j = 0
    vals = []
    for i, (d, _v) in enumerate(points):
        while points[j][0] < d - timedelta(days=window_days):
            j += 1
        win = [p[1] for p in points[j:i + 1] if p[1] is not None]
        if len(win) >= min_n:
            out.append((d, round(statistics.median(win), 2)))
    return out


def iso(d):
    return d.isoformat() if d else None


# ---------- overview ----------
def overview():
    today = date.today()
    all_rows = rows()
    if not all_rows:
        return {"empty": True}
    sports = sports_present()
    this_week = week_start(today)

    # this week vs the 4 weeks before
    week_items = [r for r in all_rows if r["start_local"].date() >= this_week]
    prev_items = [r for r in all_rows if this_week - timedelta(days=28) <= r["start_local"].date() < this_week]
    tw = totals(week_items)
    prev = totals(prev_items)
    days = []
    for i in range(7):
        d = this_week + timedelta(days=i)
        acts = [{"cat": r["category"], "min": round(t_of(r) / 60), "km": round((r["distance_m"] or 0) / 1000, 1),
                 "id": r["activity_id"], "name": r["name"]}
                for r in week_items if r["start_local"].date() == d]
        days.append({"date": d.isoformat(), "label": d.strftime("%a"), "acts": acts, "future": d > today})
    by_sport_week = []
    for c in sports:
        items = [r for r in week_items if r["category"] == c]
        if items:
            t = totals(items)
            by_sport_week.append({"cat": c, "label": CATEGORY_LABEL[c], **t})

    # weekly volume for 26 weeks, by sport
    n_weeks = 26
    weeks = [this_week - timedelta(weeks=n_weeks - 1 - i) for i in range(n_weeks)]
    idx = {w: i for i, w in enumerate(weeks)}
    hours = {c: [0.0] * n_weeks for c in sports}
    km = {c: [0.0] * n_weeks for c in sports}
    for r in all_rows:
        w = week_start(r["start_local"])
        if w in idx:
            hours[r["category"]][idx[w]] += t_of(r) / 3600
            km[r["category"]][idx[w]] += (r["distance_m"] or 0) / 1000
    weekly = {"weeks": [w.isoformat() for w in weeks],
              "hours": {c: [round(v, 2) for v in hours[c]] for c in sports},
              "km": {c: [round(v, 1) for v in km[c]] for c in sports if any(km[c])}}

    # training load: acute (7 d) vs chronic (42 d)
    load_start = today - timedelta(days=180 + 42)
    daily_load = defaultdict(float)
    for r in all_rows:
        if r["start_local"].date() >= load_start:
            daily_load[r["start_local"].date()] += r["training_load"] or (t_of(r) / 60 * 0.8 if r["avg_hr"] else 0)
    span = [load_start + timedelta(days=i) for i in range((today - load_start).days + 1)]
    vals = [daily_load.get(d, 0.0) for d in span]
    acute, chronic = boxcar(vals, 7), boxcar(vals, 42)
    cut = 42
    load = {"dates": [d.isoformat() for d in span[cut:]], "acute": acute[cut:], "chronic": chronic[cut:]}

    # calendar: minutes per day for a year
    cal_start = today - timedelta(days=364)
    per_day = defaultdict(float)
    for r in all_rows:
        if r["start_local"].date() >= cal_start:
            per_day[r["start_local"].date()] += t_of(r) / 60
    calendar = {"start": cal_start.isoformat(), "end": today.isoformat(),
                "days": [[d.isoformat(), round(v)] for d, v in sorted(per_day.items())]}

    return {
        "empty": False,
        "week": {"start": this_week.isoformat(), "totals": tw, "by_sport": by_sport_week, "days": days,
                 "avg_prev_hours": prev["hours"] / 4, "avg_prev_km": prev["km"] / 4,
                 "avg_prev_count": prev["count"] / 4},
        "weekly": weekly,
        "load": load,
        "calendar": calendar,
        "tiles": health_tiles(),
        "sports": sports,
    }


# ---------- sport pages ----------
def _days(first, last):
    out, d = [], first
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def _months(first, last):
    out, m = [], month_start(first)
    while m <= last:
        out.append(m)
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def where(qs):
    """Places for these activities, most visited first, and the countries they are in."""
    agg = (qs.exclude(place=None)
           .values("place__slug", "place__name", "place__custom_name", "place__country", "place__country_code")
           .annotate(n=Count("pk"), dist=Sum("distance_m")).order_by("-n", "place__name"))
    places, countries = [], {}
    for r in agg:
        km = (r["dist"] or 0) / 1000.0
        places.append({"slug": r["place__slug"], "name": r["place__custom_name"] or r["place__name"],
                       "country": r["place__country"], "cc": r["place__country_code"], "count": r["n"], "km": km})
        c = countries.setdefault(r["place__country_code"], {"slug": r["place__country_code"].lower(),
                                                            "name": r["place__country"], "count": 0, "km": 0.0})
        c["count"] += r["n"]
        c["km"] += km
    return places, sorted(countries.values(), key=lambda c: -c["count"])


def sport(category, kind=None, area=None):
    from .runtypes import GROUP_OF, GROUPS, RUN_TYPE_LABEL
    from .models import Weather
    today = date.today()
    base_qs = Activity.objects.filter(category=category)
    if kind:
        base_qs = base_qs.filter(kind_q(kind))
    where_places, where_countries = where(base_qs)
    qs = base_qs.filter(area.q()) if area else base_qs
    items = rows(qs)
    if not items:
        return {"empty": True, "where": where_places, "where_countries": where_countries}
    is_run = category == "run"
    year0 = date(today.year, 1, 1)
    m0 = today.replace(day=1)
    t_all = totals(items)
    t_year = totals([r for r in items if r["start_local"].date() >= year0])
    t_month = totals([r for r in items if r["start_local"].date() >= m0])
    last12 = [r for r in items if r["start_local"].date() >= week_start(today) - timedelta(weeks=12)]
    t12 = totals(last12)
    longest = max(items, key=lambda r: r["distance_m"] or 0)
    has_km = any((r["distance_m"] or 0) > 0 for r in items)
    groups = [g for g, _ in GROUPS] if (is_run and not kind) else ["all"]
    group_of = (lambda r: GROUP_OF.get(r["kind"], "easy")) if (is_run and not kind) else (lambda r: "all")
    group_labels = dict(GROUPS) if (is_run and not kind) else {"all": RUN_TYPE_LABEL.get(kind, "") if kind else ""}

    # month by month and day by day, split by group (runs) so the colours tell the story
    first_day = items[0]["start_local"].date()
    # in one place (a trip, say) the charts run from the first to the last day there, not to today
    end_day = items[-1]["start_local"].date() if area else today
    months = _months(first_day, end_day)
    days = _days(first_day, end_day)
    midx = {m: i for i, m in enumerate(months)}
    didx = {d: i for i, d in enumerate(days)}
    m_val = {g: [0.0] * len(months) for g in groups}
    d_val = {g: [0.0] * len(days) for g in groups}
    m_count = [0] * len(months)
    d_names = [[] for _ in days]
    for r in items:
        g = group_of(r)
        v = (r["distance_m"] or 0) / 1000 if has_km else t_of(r) / 3600
        m_val[g][midx[month_start(r["start_local"])]] += v
        di = didx[r["start_local"].date()]
        d_val[g][di] += v
        m_count[midx[month_start(r["start_local"])]] += 1
        d_names[di].append({"id": r["activity_id"], "kind": RUN_TYPE_LABEL.get(r["kind"], "") if is_run else "",
                            "km": round((r["distance_m"] or 0) / 1000, 2), "min": round(t_of(r) / 60)})
    used = [g for g in groups if any(m_val[g])]
    monthly = {"months": [m.isoformat() for m in months], "unit": "km" if has_km else "h", "groups": used,
               "labels": {g: group_labels[g] for g in used},
               "values": {g: [round(v, 1) for v in m_val[g]] for g in used},
               "count": m_count}
    daily = {"days": [d.isoformat() for d in days], "unit": "km" if has_km else "h", "groups": used,
             "labels": {g: group_labels[g] for g in used}, "values": {g: [round(v, 2) for v in d_val[g]] for g in used},
             "acts": d_names}

    # each activity: pace, HR, distance, efficiency (warm-ups and strides left out)
    pts, eff = [], []
    for r in items:
        if is_run and r["kind"] in ("warmup", "strides"):
            continue
        secs = t_of(r)
        dist = r["distance_m"] or 0
        if dist < 500 or secs <= 0:
            continue
        pace = secs / (dist / 1000)
        if category in PACE_CATEGORIES and not (150 < pace < 1500):
            continue
        d = r["start_local"].date()
        grp = GROUP_OF.get(r["kind"], "easy") if is_run else "all"
        pts.append({"date": d.isoformat(), "pace": round(pace, 1), "kmh": round(dist / 1000 / (secs / 3600), 2),
                    "km": round(dist / 1000, 2), "hr": r["avg_hr"], "id": r["activity_id"], "name": r["name"],
                    "group": grp, "kind": RUN_TYPE_LABEL.get(r["kind"], "") if is_run else ""})
        if r["avg_hr"] and dist >= 3000:
            eff.append((d, round((dist / secs * 60) / r["avg_hr"], 3)))
    eff_line = rolling_median(eff, 42, 4)
    pace_points = [(date.fromisoformat(p["date"]), p["pace"]) for p in pts if p["group"] != "race"]
    pace_line = rolling_median(pace_points, 42, 4)

    # best efforts: every distance, best per month and per quarter
    ids = {r["activity_id"] for r in items}
    progress, pb_table = {}, []
    for dist in BEST_EFFORT_DISTANCES.get(category, []):
        efforts = [e for e in BestEffort.objects.filter(category=category, distance_m=dist).order_by("date")
        .values("date", "seconds", "activity_id") if e["activity_id"] in ids]
        if not efforts:
            continue
        by_m, by_q = {}, {}
        for e in efforts:
            m = e["date"].replace(day=1)
            q = date(e["date"].year, 3 * ((e["date"].month - 1) // 3) + 1, 1)
            if m not in by_m or e["seconds"] < by_m[m]["seconds"]:
                by_m[m] = e
            if q not in by_q or e["seconds"] < by_q[q]["seconds"]:
                by_q[q] = e
        progress[str(dist)] = {
            "label": BEST_EFFORT_LABELS.get(dist, f"{dist} m"), "dist": dist,
            "month": [{"p": k.isoformat(), "secs": v["seconds"], "id": v["activity_id"]} for k, v in
                      sorted(by_m.items())],
            "quarter": [{"p": k.isoformat(), "secs": v["seconds"], "id": v["activity_id"]} for k, v in
                        sorted(by_q.items())],
        }
        best = min(efforts, key=lambda e: e["seconds"])
        recent = [e for e in efforts if e["date"] >= today - timedelta(days=90)]
        best90 = min(recent, key=lambda e: e["seconds"]) if recent else None
        pb_table.append({"dist": dist, "label": BEST_EFFORT_LABELS.get(dist, f"{dist} m"), "secs": best["seconds"],
                         "date": best["date"], "id": best["activity_id"],
                         "secs90": best90["seconds"] if best90 else None,
                         "id90": best90["activity_id"] if best90 else None,
                         "count": len(efforts)})

    heat = defaultdict(int)
    for r in items:
        heat[(r["start_local"].weekday(), r["start_local"].hour)] += 1
    heatmap = [[h, wd, n] for (wd, h), n in heat.items()]

    edges = _hist_edges(category)
    hist = [0] * (len(edges) - 1)
    for r in items:
        km_ = (r["distance_m"] or 0) / 1000
        for i in range(len(edges) - 1):
            if edges[i] <= km_ < edges[i + 1]:
                hist[i] += 1
                break
    hist_labels = [f"{edges[i]:g}-{edges[i + 1]:g}" if i < len(edges) - 2 else f"{edges[i]:g}+" for i in
                   range(len(edges) - 1)]

    cad = defaultdict(list)
    for r in items:
        if r["avg_cadence"] and not (is_run and r["kind"] in ("warmup", "strides")):
            cad[month_start(r["start_local"])].append(r["avg_cadence"])
    cadence = [[k.isoformat(), round(sum(v) / len(v), 1)] for k, v in sorted(cad.items())]

    # type mix (all running only)
    mix = _run_mix(items) if is_run and not kind else []

    return {
        "empty": False, "category": category, "kind": kind, "pace_mode": category in PACE_CATEGORIES,
        "kind_group": GROUP_OF.get(kind, "easy") if kind else "",
        "totals": {"all": t_all, "year": t_year, "month": t_month, "weekly_avg_km": t12["km"] / 12,
                   "weekly_avg_count": t12["count"] / 12},
        "longest": {"km": (longest["distance_m"] or 0) / 1000, "id": longest["activity_id"],
                    "date": longest["start_local"]},
        "first_date": items[0]["start_local"],
        "last_date": items[-1]["start_local"],
        "days_count": len({r["start_local"].date() for r in items}),
        "has_km": has_km,
        "monthly": monthly, "daily": daily,
        "points": pts,
        "pace_line": [[d.isoformat(), v] for d, v in pace_line],
        "efficiency": {"points": [[d.isoformat(), v] for d, v in eff],
                       "line": [[d.isoformat(), v] for d, v in eff_line]},
        "progress": progress, "pbs": pb_table, "heatmap": heatmap,
        "hist": {"labels": hist_labels, "counts": hist}, "cadence": cadence, "mix": mix,
        "weather": weather_analysis(items, is_run, same_kind=bool(kind)),
        "where": where_places, "where_countries": where_countries,
    }


def weather_analysis(items, is_run, same_kind=False):
    """How conditions relate to your pace and heart rate (outdoor sessions with weather).

    Efficiency only compares like with like, so on all running the charts use the easy kinds; on the page
    of one kind of run every session of that kind counts."""
    from .models import Weather
    from .weather import heat_cost
    by_id = {w.activity_id: w for w in
             Weather.objects.filter(activity_id__in=[r["activity_id"] for r in items], error="")}
    pts = []
    for r in items:
        w = by_id.get(r["activity_id"])
        if not w or w.temp_c is None:
            continue
        secs, dist = t_of(r), r["distance_m"] or 0
        if dist < 2000 or secs <= 0 or (is_run and r["kind"] in ("warmup", "strides")):
            continue
        hs, cost = heat_cost(w.temp_c, w.dew_point_c)
        pts.append({"id": r["activity_id"], "date": r["start_local"].date().isoformat(), "name": r["name"],
                    "temp": w.temp_c, "feels": w.feels_c, "dew": w.dew_point_c, "wind": w.wind_kmh,
                    "gust": w.gust_kmh, "head": w.headwind_kmh, "rain": w.precip_mm, "hum": w.humidity,
                    "pace": round(secs / (dist / 1000), 1), "hr": r["avg_hr"],
                    "eff": round((dist / secs * 60) / r["avg_hr"], 3) if r["avg_hr"] else None,
                    "easy": same_kind or (not is_run) or r["kind"] in ("easy", "long", "steady", "recovery"),
                    "heat_sum": hs, "heat_cost": cost})
    if not pts:
        return None

    def binned(key, edges, value="eff"):
        out = []
        for a, b in zip(edges, edges[1:]):
            sel = [p for p in pts if p["easy"] and p[value] is not None and p[key] is not None and a <= p[key] < b]
            vals = [p[value] for p in sel]
            out.append({"label": f"{a:g} to {b:g}", "lo": a, "hi": b, "n": len(vals),
                        "x": round(statistics.median([p[key] for p in sel]), 1) if sel else None,
                        "median": round(statistics.median(vals), 3) if vals else None})
        return out

    wet = [p for p in pts if (p["rain"] or 0) >= 0.2]
    windy = [p for p in pts if (p["wind"] or 0) >= 25]
    return {
        "points": pts,
        "by_temp": binned("temp", [-10, 0, 5, 10, 15, 20, 25, 40]),
        "by_wind": binned("wind", [0, 10, 15, 20, 25, 30, 40, 100]),
        "n": len(pts), "wet": len(wet), "windy": len(windy),
        "n_cmp": sum(1 for p in pts if p["easy"] and p["eff"] is not None),
        "warmest": max(pts, key=lambda p: p["temp"]), "coldest": min(pts, key=lambda p: p["temp"]),
        "windiest": max(pts, key=lambda p: p["wind"] or 0),
        "wettest": max(pts, key=lambda p: p["rain"] or 0) if wet else None,
    }


def _hist_edges(category):
    if category == "cycle":
        return [0, 20, 40, 60, 80, 100, 150]
    if category == "walk":
        return [0, 2, 4, 6, 8, 10, 15, 20]
    return [0, 3, 5, 8, 10, 13, 16, 19, 22, 30]


# ---------- personal ----------
def personal():
    today = date.today()
    items = rows()
    if not items:
        return {"empty": True}
    sports = sports_present()
    life = totals(items)
    first = items[0]["start_local"]
    years = list(range(first.year, today.year + 1))
    yidx = {y: i for i, y in enumerate(years)}
    y_hours = {c: [0.0] * len(years) for c in sports}
    y_km = {c: [0.0] * len(years) for c in sports}
    y_count = {c: [0] * len(years) for c in sports}
    for r in items:
        i = yidx[r["start_local"].year]
        y_hours[r["category"]][i] += t_of(r) / 3600
        y_km[r["category"]][i] += (r["distance_m"] or 0) / 1000
        y_count[r["category"]][i] += 1
    year_rows = []
    for y in reversed(years):
        i = yidx[y]
        year_rows.append({"year": y,
                          "cells": [{"cat": c, "km": y_km[c][i], "hours": y_hours[c][i], "count": y_count[c][i]} for c
                                    in sports],
                          "hours": sum(y_hours[c][i] for c in sports), "count": sum(y_count[c][i] for c in sports)})

    # records
    records = []
    for c in sports:
        cat_items = [r for r in items if r["category"] == c]
        if not cat_items:
            continue
        far = max(cat_items, key=lambda r: r["distance_m"] or 0)
        long_ = max(cat_items, key=t_of)
        climb = max(cat_items, key=lambda r: r["elev_gain_m"] or 0)
        rec = {"cat": c, "label": CATEGORY_LABEL[c], "count": len(cat_items),
               "far": far if far["distance_m"] else None, "long": long_,
               "climb": climb if climb["elev_gain_m"] else None}
        # biggest week
        wk = defaultdict(float)
        for r in cat_items:
            wk[week_start(r["start_local"])] += (r["distance_m"] or 0) / 1000
        if wk and max(wk.values()) > 0:
            bw = max(wk.items(), key=lambda kv: kv[1])
            rec["big_week"] = {"start": bw[0], "km": bw[1]}
        records.append(rec)

    pbs = []
    for c in ("run", "cycle", "walk"):
        if c not in sports:
            continue
        for dist in BEST_EFFORT_DISTANCES.get(c, []):
            e = BestEffort.objects.filter(category=c, distance_m=dist).order_by("seconds").select_related(
                "activity").first()
            if e:
                pbs.append({"cat": c, "label": BEST_EFFORT_LABELS.get(dist, str(dist)), "dist": dist, "secs": e.seconds,
                            "date": e.date, "id": e.activity_id, "name": e.activity.name})

    # streaks (days with any activity)
    active_days = sorted({r["start_local"].date() for r in items})
    best_streak = cur = 1
    best_end = active_days[0]
    for a, b in zip(active_days, active_days[1:]):
        cur = cur + 1 if (b - a).days == 1 else 1
        if cur > best_streak:
            best_streak, best_end = cur, b
    s = set(active_days)
    d = today if today in s else today - timedelta(days=1)  # today may still be to come
    cur_streak = 0
    while d in s:
        cur_streak += 1
        d -= timedelta(days=1)
    weeks_active = {week_start(x) for x in active_days}
    w = week_start(today)
    week_streak = 0
    while w in weeks_active:
        week_streak += 1
        w -= timedelta(weeks=1)

    zones = KeyValue.get("hr_zones")
    floors = zone_floors()
    fa = FitnessAge.objects.order_by("-date").first()
    weights = list(WeightDay.objects.order_by("date").values_list("date", "weight_kg", "body_fat"))

    # month by month and day by day, every month and day since the first activity
    monthly, daily = by_sport_series(items, sports, first.date(), today)

    # time of year: hours per month, all years stacked into calendar months
    month_hours = [0.0] * 12
    for r in items:
        month_hours[r["start_local"].month - 1] += t_of(r) / 3600

    return {
        "empty": False,
        "sports": sports,
        "life": life,
        "first": first,
        "days_active": len(active_days),
        "years": [str(y) for y in years],
        "yearly": {"hours": {c: [round(v, 1) for v in y_hours[c]] for c in sports},
                   "km": {c: [round(v, 1) for v in y_km[c]] for c in sports if any(y_km[c])}},
        "year_rows": year_rows,
        "records": records,
        "pbs": pbs,
        "streak": {"best": best_streak, "best_end": best_end, "current": cur_streak, "weeks": week_streak},
        "zones": zones,
        "floors": floors,
        "fitness_age": fa,
        "weights": [[d.isoformat(), round(kg, 2), bf] for d, kg, bf in weights if kg],
        "month_hours": [round(v, 1) for v in month_hours],
        "monthly": monthly,
        "daily": daily,
    }


def by_sport_series(items, sports, first_day, last_day):
    """Hours and kilometres per sport for every month and every day from first_day to last_day."""
    months = _months(first_day, last_day)
    days = _days(first_day, last_day)
    midx = {m: i for i, m in enumerate(months)}
    didx = {d: i for i, d in enumerate(days)}
    mh = {c: [0.0] * len(months) for c in sports}
    mk = {c: [0.0] * len(months) for c in sports}
    dh = {c: [0.0] * len(days) for c in sports}
    dk = {c: [0.0] * len(days) for c in sports}
    for r in items:
        d = r["start_local"].date()
        if d not in didx or r["category"] not in mh:
            continue
        mi, di = midx[month_start(d)], didx[d]
        mh[r["category"]][mi] += t_of(r) / 3600
        mk[r["category"]][mi] += (r["distance_m"] or 0) / 1000
        dh[r["category"]][di] += t_of(r) / 3600
        dk[r["category"]][di] += (r["distance_m"] or 0) / 1000
    monthly = {"months": [m.isoformat() for m in months],
               "hours": {c: [round(v, 2) for v in mh[c]] for c in sports},
               "km": {c: [round(v, 1) for v in mk[c]] for c in sports if any(mk[c])}}
    daily = {"days": [d.isoformat() for d in days],
             "hours": {c: [round(v, 2) for v in dh[c]] for c in sports},
             "km": {c: [round(v, 2) for v in dk[c]] for c in sports if any(dk[c])}}
    return monthly, daily


# ---------- places ----------
def _sport_rows(items, sports):
    out = []
    for c in sports:
        sel = [r for r in items if r["category"] == c]
        if sel:
            t = totals(sel)
            out.append({"cat": c, "label": CATEGORY_LABEL[c], "slug": CATEGORY_TO_SLUG.get(c, "other"),
                        "count": t["count"], "km": t["km"], "hours": t["hours"]})
    return out


def _run_mix(items):
    from .runtypes import GROUP_OF, RUN_TYPES
    runs = [r for r in items if r["category"] == "run"]
    mix = []
    for k, label in RUN_TYPES:
        sel = [r for r in runs if r["kind"] == k]
        if sel:
            t = totals(sel)
            mix.append(
                {"key": k, "label": label, "group": GROUP_OF[k], "count": len(sel), "km": t["km"], "hours": t["hours"]})
    return mix


def places_index():
    """Every place with activities, grouped by country, for the Places page and its map."""
    from .models import Place
    secs = Coalesce("moving_s", "duration_s")
    agg = {r["place_id"]: r for r in Activity.objects.exclude(place=None).values("place_id").annotate(
        n=Count("pk"), dist=Sum("distance_m"), secs=Sum(secs), first=Min("start_local"), last=Max("start_local"))}
    per_sport = defaultdict(dict)
    for r in Activity.objects.exclude(place=None).values("place_id", "category").annotate(n=Count("pk")):
        per_sport[r["place_id"]][r["category"]] = r["n"]
    places = []
    for p in Place.objects.filter(pk__in=agg.keys()):
        a = agg[p.pk]
        places.append({"slug": p.slug, "name": p.label, "country": p.country, "cc": p.country_code, "lat": p.lat,
                       "lon": p.lon, "count": a["n"], "km": (a["dist"] or 0) / 1000.0,
                       "hours": (a["secs"] or 0) / 3600.0,
                       "first": a["first"], "last": a["last"],
                       "sports": [{"cat": c, "n": per_sport[p.pk][c]} for c in CATEGORY_KEYS if
                                  per_sport[p.pk].get(c)]})
    places.sort(key=lambda x: (-x["count"], x["name"]))
    countries = {}
    for p in places:
        c = countries.setdefault(p["cc"], {"slug": p["cc"].lower(), "name": p["country"], "count": 0, "km": 0.0,
                                           "hours": 0.0, "places": []})
        c["count"] += p["count"]
        c["km"] += p["km"]
        c["hours"] += p["hours"]
        c["places"].append(p)
    return {
        "empty": not places,
        "places": places,
        "countries": sorted(countries.values(), key=lambda c: -c["count"]),
        "unplaced": Activity.objects.filter(place=None).count(),
        "placed": Activity.objects.exclude(place=None).count(),
        "total": Activity.objects.count(),
    }


def place_page(area):
    """One town or city, or a whole country: what you did there and where."""
    qs = Activity.objects.filter(area.q())
    items = rows(qs)
    if not items:
        return {"empty": True}
    sports = [c for c in CATEGORY_KEYS if any(r["category"] == c for r in items)]
    first, last = items[0]["start_local"], items[-1]["start_local"]
    monthly, daily = by_sport_series(items, sports, first.date(), last.date())
    route_rows = (qs.exclude(route=None).order_by("-start_local")
                  .values("activity_id", "category", "name", "start_local", "distance_m", "route",
                          "run_type", "run_type_manual")[:400])
    from .runtypes import RUN_TYPE_LABEL
    routes = [
        {"id": r["activity_id"], "cat": r["category"], "name": r["name"], "date": r["start_local"].date().isoformat(),
         "km": round((r["distance_m"] or 0) / 1000.0, 2),
         "kind": RUN_TYPE_LABEL.get(r["run_type_manual"] or r["run_type"], "") if r["category"] == "run" else "",
         "c": r["route"]} for r in route_rows]
    places, _countries = where(qs) if area.is_country else ([], [])
    return {
        "empty": False,
        "totals": totals(items),
        "days": len({r["start_local"].date() for r in items}),
        "first": first, "last": last,
        "sports": sports,
        "by_sport": _sport_rows(items, sports),
        "mix": _run_mix(items),
        "monthly": monthly, "daily": daily,
        "routes": routes,
        "places": places,
    }


# ---------- health ----------
def _series(model, *fields):
    out = {f: [] for f in fields}
    dates = []
    for row in model.objects.order_by("date").values("date", *fields):
        dates.append(row["date"].isoformat())
        for f in fields:
            out[f].append(row[f])
    out["dates"] = dates
    return out


def health():
    daily = _series(DailySummary, "resting_hr", "min_hr", "max_hr", "steps", "steps_goal", "avg_stress", "bb_max",
                    "bb_min", "bb_charged", "bb_drained", "resp_avg", "resp_min", "resp_max", "spo2_avg", "spo2_min",
                    "im_moderate", "im_vigorous", "kcal_total", "kcal_active", "kcal_resting", "floors_up",
                    "floors_down",
                    "stress_rest_s", "stress_low_s", "stress_med_s", "stress_high_s")
    sleep = _series(SleepNight, "total_s", "deep_s", "light_s", "rem_s", "awake_s", "score", "avg_hr", "resp_avg",
                    "resp_low", "resp_high", "spo2_avg", "spo2_low", "sleep_stress", "need_min")
    hrv = _series(HrvDay, "last_night", "weekly_avg", "baseline_low", "baseline_high")
    vo2 = {"dates": [], "running": [], "cycling": []}
    rowsv = list(Vo2Max.objects.order_by("date").values("date", "sport", "value"))
    for sport in ("running", "cycling"):
        vals = [(r["date"].isoformat(), r["value"]) for r in rowsv if r["sport"] == sport]
        vo2[sport] = vals
    weight = [[d.isoformat(), kg] for d, kg in WeightDay.objects.order_by("date").values_list("date", "weight_kg") if
              kg]
    empty = not (daily["dates"] or sleep["dates"] or hrv["dates"] or vo2["running"])
    return {"empty": empty, "daily": daily, "sleep": sleep, "hrv": hrv, "vo2": vo2, "weight": weight,
            "tiles": health_tiles(), "hrv_last": HrvDay.objects.order_by("-date").first()}


def _tile(values, dates, label, unit, better="up", digits=0, fmt=None):
    pairs = [(d, v) for d, v in zip(dates, values) if v is not None]
    if not pairs:
        return None
    last_d, last_v = pairs[-1]
    last_date = date.fromisoformat(last_d) if isinstance(last_d, str) else last_d
    recent = [v for d, v in pairs if
              (date.fromisoformat(d) if isinstance(d, str) else d) > last_date - timedelta(days=7)]
    before = [v for d, v in pairs if last_date - timedelta(days=37) < (
        date.fromisoformat(d) if isinstance(d, str) else d) <= last_date - timedelta(days=7)]
    avg7 = sum(recent) / len(recent) if recent else None
    avg30 = sum(before) / len(before) if before else None
    delta = (avg7 - avg30) if (avg7 is not None and avg30 is not None) else None
    spark = [v for _d, v in pairs[-30:]]
    good = None
    if better and delta is not None and abs(delta) > (0.5 if digits == 0 else 0.05):
        good = (delta > 0) == (better == "up")
    return {"label": label, "unit": unit, "value": last_v, "date": last_date, "avg7": avg7, "avg30": avg30,
            "delta": delta, "good": good, "spark": spark, "digits": digits, "fmt": fmt}


def health_tiles():
    tiles = []
    d = list(DailySummary.objects.order_by("date").values("date", "resting_hr", "steps", "avg_stress", "bb_max",
                                                          "floors_up", "spo2_avg", "resp_avg"))
    s = list(SleepNight.objects.order_by("date").values("date", "total_s", "score"))
    h = list(HrvDay.objects.order_by("date").values("date", "last_night"))
    v = list(Vo2Max.objects.filter(sport="running").order_by("date").values("date", "value"))
    for t in (
            _tile([r["resting_hr"] for r in d], [r["date"].isoformat() for r in d], "Resting heart rate", "bpm",
                  "down"),
            _tile([r["last_night"] for r in h], [r["date"].isoformat() for r in h], "HRV last night", "ms", "up"),
            _tile([r["value"] for r in v], [r["date"].isoformat() for r in v], "VO2max", "", "up", 1),
            _tile([r["score"] for r in s], [r["date"].isoformat() for r in s], "Sleep score", "", "up"),
            _tile([(r["total_s"] or 0) / 3600 or None for r in s], [r["date"].isoformat() for r in s], "Sleep", "",
                  "up", 1, "hours"),
            _tile([r["avg_stress"] for r in d], [r["date"].isoformat() for r in d], "Stress", "", "down"),
            _tile([r["bb_max"] for r in d], [r["date"].isoformat() for r in d], "Body battery high", "", "up"),
            _tile([r["steps"] for r in d], [r["date"].isoformat() for r in d], "Steps", "", "up"),
            _tile([r["floors_up"] for r in d], [r["date"].isoformat() for r in d], "Floors climbed", "", "up"),
            _tile([r["spo2_avg"] for r in d], [r["date"].isoformat() for r in d], "Pulse ox", "%", "up"),
            _tile([r["resp_avg"] for r in d], [r["date"].isoformat() for r in d], "Breathing rate", "brpm", None),
    ):
        if t:
            tiles.append(t)
    return tiles


# ---------- one activity ----------
def activity_detail(act):
    stream = getattr(act, "stream", None)
    data = stream.data if stream else {}
    splits = stream.splits if stream else []
    laps = list(act.laps.all())
    efforts = list(act.best_efforts.all())
    floors = zone_floors()
    zs = act.zone_seconds

    # compare with the same sport over the 90 days before
    since = act.start_local - timedelta(days=90)
    peers = rows(
        Activity.objects.filter(category=act.category, start_local__gte=since, start_local__lt=act.start_local))
    compare = None
    if len(peers) >= 3:
        p_dist = [r["distance_m"] / 1000 for r in peers if r["distance_m"]]
        p_pace = [t_of(r) / (r["distance_m"] / 1000) for r in peers if
                  r["distance_m"] and r["distance_m"] > 500 and t_of(r)]
        p_hr = [r["avg_hr"] for r in peers if r["avg_hr"]]
        compare = {
            "n": len(peers),
            "dist_avg": sum(p_dist) / len(p_dist) if p_dist else None,
            "pace_avg": statistics.median(p_pace) if p_pace else None,
            "hr_avg": sum(p_hr) / len(p_hr) if p_hr else None,
            "longer_than": round(100 * sum(1 for x in p_dist if x < act.distance_km) / len(p_dist)) if p_dist else None,
        }
    # PB flags: is any effort here an all-time best (so far, at that date)?
    pb_flags = []
    for e in efforts:
        better = BestEffort.objects.filter(category=act.category, distance_m=e.distance_m, seconds__lt=e.seconds,
                                           date__lte=e.date).exists()
        rank = BestEffort.objects.filter(category=act.category, distance_m=e.distance_m,
                                         seconds__lt=e.seconds).count() + 1
        pb_flags.append({"label": BEST_EFFORT_LABELS.get(e.distance_m, str(e.distance_m)), "dist": e.distance_m,
                         "secs": e.seconds, "pb_then": not better, "rank": rank, "start": e.start_offset_s})
    weather = getattr(act, "weather", None) if _has(act, "weather") else None
    wind = None
    split_wind = []
    if weather and not weather.error:
        from .weather import headwind_series
        hw = headwind_series(act, weather)
        if hw:
            wind = hw["series"]
            t = data.get("t") or []
            start_t = 0.0
            for sp in splits:
                vals = [w for tt, w in zip(t, wind) if w is not None and start_t <= tt <= sp.get("t_end", 0)]
                split_wind.append(round(sum(vals) / len(vals)) if vals else None)
                start_t = sp.get("t_end", 0)
    prev_act = Activity.objects.filter(start_local__lt=act.start_local).order_by("-start_local").first()
    next_act = Activity.objects.filter(start_local__gt=act.start_local).order_by("start_local").first()
    return {
        "stream": data,
        "splits": splits,
        "laps": laps,
        "efforts": pb_flags,
        "zones": zs,
        "floors": floors,
        "compare": compare,
        "prev": prev_act,
        "next": next_act,
        "has_map": bool(data.get("lat")),
        "weather": weather if weather and not weather.error else None,
        "weather_error": weather.error if weather and weather.error else "",
        "wind": wind,
        "split_wind": split_wind,
        "blocks": (act.run_type_info or {}).get("blocks") or [],
    }


def _has(obj, rel):
    try:
        return getattr(obj, rel) is not None
    except Exception:
        return False
