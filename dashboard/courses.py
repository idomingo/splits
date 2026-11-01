"""Courses: races and time trials that went the same way, found from the GPS track.

Two runs are on the same course when they start and finish within 250 m of each other, their distance is
within 6%, and at least 80% of each track lies within 60 m of the other. Every run of a course can then be
compared with the others: the cleanest answer to "am I getting fitter", since the route is the same.

Nothing is stored: courses are worked out from the simplified routes the app already keeps, and cached until
runs are added or changed. A course is named after its place and distance, and keeps the id of its first run.
"""
import math
import statistics
from collections import Counter, defaultdict

CACHE_KEY = "courses"
VERSION = 3
NEAR_END = 250.0      # start and finish within this many metres
NEAR_TRACK = 60.0     # a point of one track counts as on the other within this distance
SHARE = 0.8           # ... for this share of each track
DIST_TOL = 0.06       # distance within 6%
MIN_KM = 1.0
STEP = 25.0           # resample the tracks every 25 m


def _xy(lon, lat):
    return lon * 111320.0 * math.cos(math.radians(lat)), lat * 110540.0


def _resample(route):
    """Points every STEP metres along the track (pieces joined), in metres."""
    pts = [_xy(lo, la) for piece in route or [] for lo, la in piece]
    if len(pts) < 2:
        return []
    out, carry = [pts[0]], 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg > 1500:  # a gap in the signal: no points across it
            out.append((x1, y1))
            carry = 0.0
            continue
        pos = STEP - carry
        while pos <= seg:
            f = pos / seg
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
            pos += STEP
        carry = seg - (pos - STEP)
    out.append(pts[-1])
    return out


def _grid(points, cell=NEAR_TRACK):
    g = defaultdict(list)
    for x, y in points:
        g[(int(x // cell), int(y // cell))].append((x, y))
    return g


def _share_on(a, grid_b, near=NEAR_TRACK):
    if not a:
        return 0.0
    hit = 0
    for x, y in a:
        cx, cy = int(x // near), int(y // near)
        found = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for bx, by in grid_b.get((cx + dx, cy + dy), ()):
                    if (bx - x) ** 2 + (by - y) ** 2 <= near * near:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        hit += found
    return hit / len(a)


def _candidates():
    from .models import Activity
    # only races and time trials: comparing an easy run with a race on the same roads says little
    from .analytics import kind_q
    qs = (Activity.objects.filter(kind_q("race"), category="run", distance_m__gte=MIN_KM * 1000)
          .exclude(route=None)
          .values_list("activity_id", "start_local", "distance_m", "place_id", "name"))
    return list(qs)


def _fingerprint(cands):
    return [VERSION, len(cands), sum(c[0] % 1000003 for c in cands), sum(round(c[2]) for c in cands)]


def find_courses():
    """[{id, name, km, runs: [activity ids, oldest first]}] for every course, including those run once."""
    from .models import KeyValue, Place
    cands = _candidates()
    fp = _fingerprint(cands)
    cached = KeyValue.get(CACHE_KEY)
    if cached and cached.get("fp") == fp:
        return cached["courses"]
    from .models import Activity
    routes = dict(Activity.objects.filter(pk__in=[c[0] for c in cands]).values_list("activity_id", "route"))
    info = {}
    for aid, start, dist, place_id, name in cands:
        pts = _resample(routes.get(aid))
        if len(pts) < 8:
            continue
        info[aid] = {"start": start, "dist": dist, "pts": pts, "a": pts[0], "b": pts[-1], "place": place_id,
                     "name": name}
    ids = sorted(info, key=lambda i: info[i]["start"])
    by_start = defaultdict(list)
    for i in ids:
        x, y = info[i]["a"]
        by_start[(int(x // NEAR_END), int(y // NEAR_END))].append(i)
    parent = {i: i for i in ids}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grids = {}
    for i in ids:
        A = info[i]
        x, y = A["a"]
        cx, cy = int(x // NEAR_END), int(y // NEAR_END)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in by_start.get((cx + dx, cy + dy), ()):
                    if j <= i or root(i) == root(j):
                        continue
                    B = info[j]
                    if abs(A["dist"] - B["dist"]) > DIST_TOL * max(A["dist"], B["dist"]):
                        continue
                    if math.dist(A["a"], B["a"]) > NEAR_END or math.dist(A["b"], B["b"]) > NEAR_END:
                        continue
                    ga = grids.setdefault(i, _grid(A["pts"]))
                    gb = grids.setdefault(j, _grid(B["pts"]))
                    if _share_on(A["pts"], gb) >= SHARE and _share_on(B["pts"], ga) >= SHARE:
                        parent[root(j)] = root(i)
    groups = defaultdict(list)
    for i in ids:
        groups[root(i)].append(i)
    labels = {p.pk: p.label for p in Place.objects.filter(pk__in={v["place"] for v in info.values() if v["place"]})}
    courses = []
    for members in groups.values():
        members.sort(key=lambda i: info[i]["start"])
        km = statistics.median(info[i]["dist"] for i in members) / 1000.0
        place = labels.get(info[members[0]]["place"], "")
        # a name the runner gave most of these runs in Garmin ("Track 5K time trial") names the course
        from .sports import is_generic_name
        own = Counter(info[i]["name"] for i in members if not is_generic_name(info[i]["name"] or "")).most_common(1)
        name = own[0][0] if own and own[0][1] * 2 > len(members) else (f"{place} {km:.1f} km" if place else f"{km:.1f} km course")
        courses.append({"id": members[0], "km": round(km, 2), "runs": members, "name": name})
    # the same place and distance twice: tell them apart
    seen = defaultdict(int)
    for c in sorted(courses, key=lambda c: (-len(c["runs"]), c["id"])):
        seen[c["name"]] += 1
        if seen[c["name"]] > 1:
            c["name"] += f" ({chr(64 + seen[c['name']])})"
    courses.sort(key=lambda c: (-len(c["runs"]), c["name"]))
    KeyValue.put(CACHE_KEY, {"fp": fp, "courses": courses})
    return courses


def course_by_id(course_id):
    return next((c for c in find_courses() if c["id"] == course_id), None)


def course_of(act):
    """The course this run is on, with its rank by time among the runs of that course."""
    from .models import Activity
    c = next((c for c in find_courses() if act.pk in c["runs"]), None)
    if not c:
        return None
    times = {k: e or m for k, e, m in
             Activity.objects.filter(pk__in=c["runs"]).values_list("activity_id", "elapsed_s", "moving_s")}
    mine = times.get(act.pk) or act.elapsed_s or act.time_s
    ordered = sorted(v for v in times.values() if v)
    return {"id": c["id"], "name": c["name"], "count": len(c["runs"]),
            "rank": 1 + sum(1 for v in ordered if v < mine), "best": ordered[0] if ordered else None}


def course_page(course):
    """Every run of a course, oldest first, with time, heart rate and conditions."""
    from .models import Activity
    from .runtypes import RUN_TYPE_LABEL
    acts = list(Activity.objects.filter(pk__in=course["runs"]).select_related("weather", "place")
                .defer("raw", "route").order_by("start_local"))
    rows, best = [], None
    for a in acts:
        w = a.wx
        secs = a.elapsed_s or a.time_s  # races are timed on the clock
        ef = round((a.distance_m / a.time_s * 60) / a.avg_hr, 3) if a.avg_hr and a.time_s and a.distance_m else None
        rows.append({"id": a.pk, "date": a.start_local, "kind": RUN_TYPE_LABEL.get(a.kind, ""), "kind_key": a.kind,
                     "secs": secs, "km": a.distance_km, "pace": secs / a.distance_km if a.distance_m else None, "hr": a.avg_hr, "ef": ef,
                     "temp": w.temp_c if w else None, "wind": w.wind_kmh if w else None,
                     "head": w.headwind_kmh if w else None, "title": a.title})
        if secs and (best is None or secs < best["secs"]):
            best = rows[-1]
    for r in rows:
        r["best"] = r is best
        r["behind"] = (r["secs"] - best["secs"]) if best and r["secs"] else None
    return {"rows": rows, "best": best, "first": acts[0].start_local if acts else None,
            "last": acts[-1].start_local if acts else None,
            "route": next((a.route_svg for a in reversed(acts) if a.route_svg), "")}
