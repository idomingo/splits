"""Data worked out from what is already stored: run kinds and places.

The sync fills them in. After an update, or when a page is opened before the
next sync, anything missing is filled in on the spot, so menus and filters never
wait for a sync.
"""
import threading

_lock = threading.Lock()


def missing():
    """(runs to sort, activities without a place). Runs: "all" after a change to the rules, True for new ones."""
    from .models import Activity, KeyValue
    from .places import GEO_VERSION
    from .runtypes import RULES_VERSION
    runs = Activity.objects.filter(category="run")
    if runs.exists() and KeyValue.get("run_rules_version") != RULES_VERSION:
        sort = "all"
    else:
        sort = runs.filter(run_type="").exists()
    geo = Activity.objects.filter(geo_version__lt=GEO_VERSION).exists()
    return sort, geo


def fill_missing():
    """Fill in missing run kinds and places. Skips quietly if another request is already doing it."""
    if not _lock.acquire(blocking=False):
        return False
    try:
        runs, geo = missing()
        if geo:
            from .places import assign_places
            assign_places()
        if runs:
            from .runtypes import classify_runs
            classify_runs(only_missing=runs != "all")
        return runs or geo
    finally:
        _lock.release()
