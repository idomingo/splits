from collections import OrderedDict
from datetime import datetime, timedelta

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
    """Activities grouped by week, newest first. Only whole weeks per page."""
    qs = (Activity.objects.select_related("stream", "weather", "place")
          .defer("raw", "route", "stream__data", "stream__splits", "weather__hourly"))
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
        weeks.append({
            "start": wk, "end": wk + timedelta(days=6), "acts": acts,
            "km": sum(a.distance_km for a in acts), "secs": sum(a.time_s for a in acts),
            "count": len(acts), "zones": zones if any(zones) else None,
        })
    cursor = None
    if more and weeks:
        cursor = datetime.combine(weeks[-1]["start"], datetime.min.time()).isoformat()
    return weeks, cursor


def overview(request):
    data = analytics.overview()
    weeks, cursor = feed_weeks()
    return render(request, "dashboard/overview.html", {
        "page": "overview", "data": data, "weeks": weeks, "cursor": cursor, "feed_category": "",
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
        "json": {k: v for k, v in data.items() if k not in ("longest", "first_date", "last_date", "pbs", "where", "where_countries")},
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
    detail = analytics.activity_detail(act)
    w = detail["weather"]
    from .weather import compass, describe, heat_cost
    return render(request, "dashboard/activity.html", {
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
            "wind_dir": w.wind_dir if w else None, "wind_kmh": w.wind_kmh if w else None,
            "laps": [{"n": l.index, "start": l.start_offset_s, "secs": l.duration_s, "dist": l.distance_m,
                      "hr": l.avg_hr, "pace": l.pace_s_per_km} for l in detail["laps"]],
        },
    })


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
                                                       "json": _json_safe(data, "fitness_age", "records", "year_rows", "pbs",
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
