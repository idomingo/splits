from datetime import date

from django.conf import settings
from django.db.models import Count

from .models import Activity, KeyValue, SyncRun
from .sports import CATEGORIES, CATEGORY_TO_SLUG

NAV_PLACES = 6


def _current_area(request):
    """The place filter of the page being shown: ?place=... or the place page itself."""
    from .places import resolve_area
    match = getattr(request, "resolver_match", None)
    if match and match.url_name == "place":
        return resolve_area(match.kwargs.get("slug"))
    return resolve_area(request.GET.get("place"))


def nav(request):
    running = SyncRun.objects.filter(status=SyncRun.RUNNING).first()
    counts = dict(Activity.objects.values_list("category").annotate(n=Count("pk")))
    sports = [
        {"key": key, "label": label, "slug": CATEGORY_TO_SLUG[key], "count": counts.get(key, 0)}
        for key, label, _ in CATEGORIES if counts.get(key)
    ]
    area = _current_area(request)

    # run types for the Running sub-menu (counted inside the place filter when there is one)
    from .runtypes import RUN_TYPES
    runs = Activity.objects.filter(category="run")
    if area:
        runs = runs.filter(area.q())
    kinds = {}
    for auto, manual in runs.values_list("run_type", "run_type_manual"):
        k = manual or auto
        if k:
            kinds[k] = kinds.get(k, 0) + 1
    run_kinds = [{"key": k, "label": label, "count": kinds[k]} for k, label in RUN_TYPES if kinds.get(k)]

    # places: the most visited ones, and what you did in the one being shown
    place_rows = list(Activity.objects.exclude(place=None)
                      .values("place__slug", "place__name", "place__custom_name")
                      .annotate(n=Count("pk")).order_by("-n", "place__name"))
    nav_places = [{"slug": r["place__slug"], "name": r["place__custom_name"] or r["place__name"], "count": r["n"]}
                  for r in place_rows[:NAV_PLACES]]
    if area and not area.is_country and not any(p["slug"] == area.slug for p in nav_places):
        r = next((r for r in place_rows if r["place__slug"] == area.slug), None)
        if r:
            nav_places.append({"slug": area.slug, "name": area.name, "count": r["n"]})
    area_sports = []
    if area:
        ac = dict(Activity.objects.filter(area.q()).values_list("category").annotate(n=Count("pk")))
        area_sports = [{"key": key, "label": label, "slug": CATEGORY_TO_SLUG[key], "count": ac[key]}
                       for key, label, _ in CATEGORIES if ac.get(key)]

    from .courses import find_courses
    try:
        n_courses = len(find_courses()) if counts.get("run") else 0
    except Exception:  # never break the menu over this
        n_courses = 0

    from .models import Race
    nxt = Race.objects.filter(date__gte=date.today()).order_by("date").first()

    last = SyncRun.objects.exclude(status=SyncRun.RUNNING).first()
    return {
        "APP_NAME": settings.APP_NAME,
        "nav_sports": sports,
        "nav_run_kinds": run_kinds,
        "nav_total": sum(counts.values()),
        "nav_places": nav_places,
        "nav_courses": n_courses,
        "nav_next_race": (nxt.date - date.today()).days if nxt else None,
        "nav_place_count": len(place_rows),
        "nav_area": area,
        "nav_area_sports": area_sports,
        "nav_place_qs": f"?place={area.slug}" if area else "",
        "last_sync": last,
        "sync_running": running,
        "is_demo": bool(KeyValue.get("demo")),
        "key_set": bool(settings.GARMIN_PERSONAL_API_KEY),
        "today_year": date.today().year,
    }
