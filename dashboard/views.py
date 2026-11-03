from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import analytics
from .maps import map_config
from .garmin.sync import current_run, start_background_sync
from .models import Activity, Place, SyncRun
from .places import resolve_area
from .sports import CATEGORY_LABEL, CATEGORY_TO_SLUG, PACE_CATEGORIES, SLUG_TO_CATEGORY

FEED_BATCH = 40


def feed_weeks(category=None, before=None, kind=None, area=None):
    """Activities grouped by week, newest first. Only whole weeks per page. A warm-up, cool-down or strides run
    shows inside the card of the run it belongs to; it gets a card of its own only when that run is not in
    this list (on the page of warm-ups, say)."""
    from .runtypes import session_role
    qs = (Activity.objects.select_related("stream", "weather", "place", "session_of")
          .defer("raw", "route", "stream__data", "stream__splits", "weather__hourly", "session_of__raw",
                 "session_of__route"))
    if category:
        qs = qs.filter(category=category)
    if kind:
        qs = qs.filter(analytics.kind_q(kind))
    if area:
        qs = qs.filter(area.q())
    if before:
        qs = qs.filter(start_local__lt=before)
    batch = list(qs.order_by("-start_local")[:FEED_BATCH + 1])
    more = len(batch) > FEED_BATCH
    batch = batch[:FEED_BATCH]
    ids = {a.pk for a in batch}
    extras = {}
    for e in (Activity.objects.filter(session_of_id__in=ids).select_related("place")
              .defer("raw", "route").order_by("start_local")):
        extras.setdefault(e.session_of_id, []).append(e)
    groups = OrderedDict()
    for a in batch:
        groups.setdefault(analytics.week_start(a.start_local), []).append(a)
    if more and len(groups) > 1:
        groups.popitem()  # last week may be cut in half; it comes with the next page
    weeks = []
    for wk, acts in groups.items():
        zones = [0.0] * 5
        for a in acts:
            zs = a.zone_seconds
            if zs:
                zones = [x + (y or 0) for x, y in zip(zones, zs)]
        cards = []
        for a in acts:
            if a.session_of_id and a.session_of_id in ids:
                continue  # shown inside its run's card
            a.extras = [{"role": session_role(e, a), "km": e.distance_km, "secs": e.time_s, "id": e.pk}
                        for e in extras.get(a.pk, [])]
            cards.append(a)
        weeks.append({
            "start": wk, "end": wk + timedelta(days=6), "acts": cards,
            "km": sum(a.distance_km for a in acts), "secs": sum(a.time_s for a in acts),
            "count": len(cards), "zones": zones if any(zones) else None,
        })
    cursor = None
    if more and weeks:
        cursor = datetime.combine(weeks[-1]["start"], datetime.min.time()).isoformat()
    return weeks, cursor


def overview(request):
    data = analytics.overview()
    weeks, cursor = feed_weeks()
    return render(request, "dashboard/overview.html", {
        "page": "overview", "data": data, "json": {k: v for k, v in data.items() if k != "next_race"}, "weeks": weeks, "cursor": cursor, "feed_category": "",
    })


def sport(request, slug, kind=None):
    from .runtypes import RUN_TYPE_LABEL
    category = SLUG_TO_CATEGORY.get(slug)
    if not category or (kind and (category != "run" or kind not in RUN_TYPE_LABEL)):
        raise Http404
    area = resolve_area(request.GET.get("place"))
    data = analytics.sport(category, kind, area)
    weeks, cursor = feed_weeks(category, kind=kind, area=area)
    label = RUN_TYPE_LABEL[kind] if kind else CATEGORY_LABEL[category]
    return render(request, "dashboard/sport.html", {
        "page": slug, "subpage": kind or "", "category": category, "kind": kind or "", "label": label,
        "parent_label": CATEGORY_LABEL[category] if kind else "", "data": data, "area": area,
        "place_qs": f"?place={area.slug}" if area else "",
        "json": dict({k: v for k, v in data.items() if k not in ("longest", "first_date", "last_date", "pbs", "where",
                                                                "where_countries", "kind_rows")},
                     race_vdot=[[r["date"].date().isoformat(), round(r["vdot"], 1), r["id"], r["title"], r["secs"]]
                                for r in reversed(data.get("kind_rows") or []) if r.get("vdot")] if kind == "race" else None),
        "weeks": weeks, "cursor": cursor, "feed_category": category, "feed_kind": kind or "",
        "feed_place": area.slug if area else "",
        "pace_mode": category in PACE_CATEGORIES,
    })


def feed_more(request):
    category = request.GET.get("category") or None
    kind = request.GET.get("kind") or None
    area = resolve_area(request.GET.get("place"))
    before = request.GET.get("before")
    try:
        before_dt = datetime.fromisoformat(before) if before else None
    except ValueError:
        before_dt = None
    weeks, cursor = feed_weeks(category, before_dt, kind, area)
    return render(request, "dashboard/partials/feed_weeks.html", {
        "weeks": weeks, "cursor": cursor, "feed_category": category or "", "feed_kind": kind or "",
        "feed_place": area.slug if area else "",
    })


@require_POST
def set_run_type(request, activity_id):
    from django.shortcuts import redirect
    from .runtypes import RUN_TYPE_LABEL
    act = get_object_or_404(Activity, pk=activity_id, category="run")
    value = request.POST.get("run_type", "")
    act.run_type_manual = value if value in RUN_TYPE_LABEL else ""
    act.save(update_fields=["run_type_manual"])
    from .runtypes import group_sessions
    group_sessions()
    return redirect("activity", activity_id=act.pk)


def export_activity(request, activity_id):
    """The run as a Markdown file for AI tools (descriptive Markdown plus CSV for the per-second data)."""
    from django.http import HttpResponse
    from .export import activity_markdown, content_disposition, filename
    act = get_object_or_404(Activity.objects.select_related("stream", "place"), pk=activity_id, category="run")
    resp = HttpResponse(activity_markdown(act), content_type="text/markdown; charset=utf-8")
    resp["Content-Disposition"] = content_disposition(filename(act))
    return resp


def activity(request, activity_id):
    from .runtypes import RUN_TYPES, RUN_TYPE_LABEL
    act = get_object_or_404(Activity.objects.select_related("stream", "place"), pk=activity_id)
    from .export import page_analysis
    try:
        analysis = page_analysis(act)
    except Exception:  # an unreadable file must not take the page down
        analysis = None
    detail = analytics.activity_detail(act)
    w = detail["weather"]
    from .weather import compass, describe, heat_cost
    from .courses import course_of
    return render(request, "dashboard/activity.html", {
        "session": _session(act), "analysis": analysis, "course": course_of(act) if act.category == "run" else None,
        "run_types": RUN_TYPES, "kind_label": RUN_TYPE_LABEL.get(act.kind, ""),
        "w_desc": describe(w.weather_code) if w else "", "w_compass": compass(w.wind_dir) if w else "",
        "w_heat": heat_cost(w.temp_c, w.dew_point_c) if w else (None, ""),
        "page": analytics_slug(act.category), "subpage": act.kind if act.category == "run" else "", "a": act, "d": detail,
        "pace_mode": act.category in PACE_CATEGORIES, "label": CATEGORY_LABEL.get(act.category, "Other"),
        "map_config": map_config() if detail["has_map"] else None,
        "chart_data": {
            "stream": detail["stream"], "splits": detail["splits"], "floors": detail["floors"],
            "zones": detail["zones"], "category": act.category, "pace_mode": act.category in PACE_CATEGORIES,
            "efforts": detail["efforts"], "wind": detail["wind"], "blocks": detail["blocks"],
            "marks": (analysis or {}).get("marks") or [],
            "wind_dir": w.wind_dir if w else None, "wind_kmh": w.wind_kmh if w else None,
            "laps": [{"n": l.index, "start": l.start_offset_s, "secs": l.duration_s, "dist": l.distance_m,
                      "hr": l.avg_hr, "pace": l.pace_s_per_km} for l in detail["laps"]],
        },
    })


def _session(act):
    """The runs of the session this one belongs to (warm-up, run, cool-down, strides), in order."""
    from .runtypes import session_role
    main = act.session_of if act.session_of_id else act
    extras = list(Activity.objects.filter(session_of=main).select_related("place").order_by("start_local"))
    if not extras:
        return None
    parts = sorted([main] + extras, key=lambda x: x.start_local)
    return {"main": main, "km": sum(p.distance_km for p in parts),
            "parts": [{"act": p, "role": "Run" if p.pk == main.pk else session_role(p, main)} for p in parts]}


def training_log(request):
    before = request.GET.get("before")
    try:
        before_d = date.fromisoformat(before) if before else None
    except ValueError:
        before_d = None
    data = analytics.training_log(before_d)
    from .models import PlanSession
    return render(request, "dashboard/log.html", {"page": "log", "data": data, "has_plan": PlanSession.objects.exists()})


def courses(request):
    from .courses import course_page, find_courses
    items = []
    for c in find_courses():
        page = course_page(c)
        items.append({**c, "count": len(c["runs"]), "best": page["best"], "last": page["last"], "first": page["first"],
                      "route": page["route"], "latest": page["rows"][-1] if page["rows"] else None})
    return render(request, "dashboard/courses.html", {"page": "courses", "courses": items,
                                                      "once": sum(1 for c in items if c["count"] == 1)})


def course(request, course_id):
    from .courses import course_by_id, course_page
    from .runtypes import GROUP_OF
    c = course_by_id(course_id)
    if not c:
        raise Http404
    page = course_page(c)
    json_rows = [{"id": r["id"], "date": r["date"].date().isoformat(), "secs": r["secs"], "pace": r["pace"],
                  "hr": r["hr"], "ef": r["ef"], "kind": r["kind"], "group": GROUP_OF.get(r["kind_key"], "easy"),
                  "title": r["title"],
                  "temp": r["temp"], "wind": r["wind"]} for r in page["rows"]]
    return render(request, "dashboard/course.html", {"page": "courses", "course": c, "data": page,
                                                     "json": {"rows": json_rows, "km": c["km"]}})


# ---------- races you have entered ----------
def _race_from_post(post, race=None):
    from .models import Race
    from .racing import parse_time
    race = race or Race()
    race.name = (post.get("name") or "").strip()[:200] or "Race"
    race.location = (post.get("location") or "").strip()[:200]
    try:
        race.date = date.fromisoformat(post.get("date") or "")
    except ValueError:
        return None, "Give the race a date."
    dist = post.get("distance")
    try:
        km = float(post.get("distance_km") or 0) if dist == "other" else float(dist or 0) / 1000.0
    except ValueError:
        km = 0
    if not 0.4 <= km <= 400:
        return None, "Give the race a distance."
    race.distance_m = km * 1000.0
    race.goal_s = parse_time(post.get("goal"))
    race.notes = (post.get("notes") or "").strip()
    return race, ""


def _race_fields(race=None, post=None):
    """Values for the race form: what was posted (after an error), the race being edited, or a blank form."""
    from .racing import STANDARD_DISTANCES
    from .templatetags.fmt import dur
    if post is not None:
        return {k: post.get(k, "") for k in ("name", "location", "date", "distance", "distance_km", "goal", "notes")}
    if race is None:
        return {"distance": str(STANDARD_DISTANCES[0][0])}
    std = next((d for d, _ in STANDARD_DISTANCES if abs(d - race.distance_m) < 1), None)
    return {"name": race.name, "location": race.location, "date": race.date.isoformat(),
            "distance": str(std) if std else "other", "distance_km": "" if std else f"{race.distance_km:g}",
            "goal": dur(race.goal_s) if race.goal_s else "", "notes": race.notes}


def races(request):
    from django.shortcuts import redirect
    from .models import Race
    from .racing import STANDARD_DISTANCES, prediction
    error = ""
    if request.method == "POST":
        race, error = _race_from_post(request.POST)
        if race:
            race.save()
            return redirect("race", race_id=race.pk)
    today = date.today()
    upcoming = list(Race.objects.filter(date__gte=today))
    for r in upcoming:
        r.days = (r.date - today).days
        r.pred = prediction(r.distance_m)
    from .racing import race_view
    past = list(Race.objects.filter(date__lt=today).order_by("-date"))
    for r in past:
        r.view = race_view(r, today)
    return render(request, "dashboard/races.html", {"page": "races", "upcoming": upcoming, "past": past,
                                                    "distances": STANDARD_DISTANCES, "error": error,
                                                    "f": _race_fields(post=request.POST if error else None)})


def race(request, race_id):
    from django.shortcuts import redirect
    from .models import Race
    from .racing import STANDARD_DISTANCES, race_view
    r = get_object_or_404(Race, pk=race_id)
    error = ""
    if request.method == "POST":
        if request.POST.get("delete"):
            r.delete()
            return redirect("races")
        updated, error = _race_from_post(request.POST, r)
        if updated:
            updated.save()
            return redirect("race", race_id=r.pk)
    data = race_view(r)
    return render(request, "dashboard/race.html", {"page": "races", "d": data, "r": r, "error": error,
                                                   "f": _race_fields(post=request.POST) if error else _race_fields(r),
                                                   "distances": STANDARD_DISTANCES, "editing": True})


# ---------- training plan ----------
def plan(request):
    from django.shortcuts import redirect
    from . import plan as P
    result = None
    if request.method == "POST":
        if request.POST.get("clear"):
            from .models import PlanSession
            PlanSession.objects.all().delete()
            return redirect("plan")
        f = request.FILES.get("file")
        raw = f.read() if f else (request.POST.get("text") or "").encode()
        if raw.strip():
            count, errors = P.import_plan(raw, replace_all=request.POST.get("replace") == "all")
            result = {"count": count, "errors": errors}
        else:
            result = {"count": 0, "errors": ["Choose a CSV file, or paste the plan into the box."]}
    return render(request, "dashboard/plan.html", {"page": "plan", "data": P.overview(), "result": result,
                                                   "prompt": P.AI_PROMPT, "kinds": P.KINDS})


def plan_template(request):
    from django.http import HttpResponse
    from .plan import TEMPLATE
    resp = HttpResponse(TEMPLATE, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="training-plan-template.csv"'
    return resp


def places(request):
    data = analytics.places_index()
    return render(request, "dashboard/places.html", {
        "page": "places", "data": data, "map_config": map_config() if not data["empty"] else None,
        "json": {"places": [{k: p[k] for k in ("slug", "name", "country", "lat", "lon", "count", "km", "hours")}
                            for p in data["places"]]},
    })


def place(request, slug):
    area = resolve_area(slug)
    if not area:
        raise Http404
    data = analytics.place_page(area)
    weeks, cursor = feed_weeks(area=area)
    return render(request, "dashboard/place.html", {
        "page": "place", "area": area, "data": data, "map_config": map_config() if data.get("routes") else None,
        "json": {k: data[k] for k in ("sports", "monthly", "daily", "routes")} if not data["empty"] else {},
        "weeks": weeks, "cursor": cursor, "feed_category": "", "feed_kind": "", "feed_place": area.slug,
        "categories": CATEGORY_TO_SLUG,
    })


@require_POST
def rename_place(request, slug):
    from django.shortcuts import redirect
    p = get_object_or_404(Place, slug=slug)
    p.custom_name = (request.POST.get("name") or "").strip()[:200]
    if p.custom_name == p.name:
        p.custom_name = ""
    p.save(update_fields=["custom_name"])
    return redirect("place", slug=p.slug)


def analytics_slug(category):
    from .sports import CATEGORY_TO_SLUG
    return CATEGORY_TO_SLUG.get(category, "other")


def _json_safe(data, *drop):
    return {k: v for k, v in data.items() if k not in drop}


def personal(request):
    data = analytics.personal()
    return render(request, "dashboard/personal.html", {"page": "personal", "data": data,
                                                       "json": _json_safe(data, "fitness_age", "records", "pbs",
                                                                          "first", "streak", "zones", "life")})


def health(request):
    data = analytics.health()
    return render(request, "dashboard/health.html", {"page": "health", "data": data,
                                                     "json": _json_safe(data, "hrv_last")})


# ---------- sync ----------
def _run_json(run):
    if not run:
        return {"status": "idle"}
    return {
        "id": run.pk, "status": run.status, "phase": run.phase, "done": run.done, "total": run.total,
        "message": run.message, "new": run.new_activities, "error": run.error,
        "started": run.started_at.isoformat() if run.started_at else None,
        "finished": run.finished_at.isoformat() if run.finished_at else None,
    }


@require_POST
def sync_start(request):
    full = request.POST.get("full") == "1"
    run = start_background_sync(full=full)
    return JsonResponse(_run_json(run))


def sync_status(request):
    run_id = request.GET.get("id")
    run = SyncRun.objects.filter(pk=run_id).first() if run_id else (current_run() or SyncRun.objects.first())
    return JsonResponse(_run_json(run))
