"""Sync engine: pulls everything new from Garmin into the database.

First run fetches the full history; later runs fetch only what is new.
Each data set is its own phase, so one failing endpoint does not stop the rest.
"""
import logging
import os
import threading
import time
import traceback
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Max, Min, Q
from django.utils import timezone

from .. import fitparse, ingest
from ..models import (Activity, DailySummary, FitnessAge, HrvDay, KeyValue, SleepNight, SyncRun,
                      Vo2Max, WeightDay)
from . import extract
from .client import GarminAuthError, GarminClient, GarminError, GarminNotAvailable, GarminTooLarge

log = logging.getLogger("dashboard.sync")

ACTIVITY_LIST = "/activitylist-service/activities/search/activities"
ACTIVITY_FILE = "/download-service/files/activity/{id}"
DAILY = "/usersummary-service/v2/dailysummaries"
SLEEP = "/sleep-service/sleep/dailySleepSummariesByDate"
HRV = "/hrv-service/hrv/daily/{a}/{b}"
WEIGHT = "/weight-service/weight/range/{a}/{b}"
VO2 = "/metrics-service/metrics/maxmet/daily/{a}/{b}"
FITNESS_AGE = "/fitnessage-service/fitnessage/v2/{d}"
HR_ZONES = "/biometric-service/heartRateZones/v2"

STALE_AFTER = timedelta(minutes=15)  # a running sync with no heartbeat for this long is dead
_lock = threading.Lock()


def now():
    return timezone.now()


class Context:
    def __init__(self, run: SyncRun, client: GarminClient, full=False, echo=None):
        self.run = run
        self.client = client
        self.full = full
        self.echo = echo
        self._last_save = 0.0
        self.problems = []
        self.capabilities = KeyValue.get("capabilities", {}) or {}

    def progress(self, phase=None, done=None, total=None, message=None, force=False):
        r = self.run
        if phase is not None:
            r.phase = phase
        if done is not None:
            r.done = done
        if total is not None:
            r.total = total
        if message is not None:
            r.message = message[:255]
        if self.echo:
            bar = f"{r.done}/{r.total}" if r.total else (str(r.done) if r.done else "")
            self.echo(f"{r.phase}: {bar} {r.message}".rstrip(), False)
        if force or time.time() - self._last_save > 1.0:
            r.heartbeat_at = now()
            r.save(update_fields=["phase", "done", "total", "message", "heartbeat_at", "new_activities"])
            self._last_save = time.time()

    def note(self, text):
        self.run.log += text.rstrip() + "\n"
        if self.echo:
            self.echo(text, True)
        else:
            log.info(text)

    def unavailable(self, key):
        return self.capabilities.get(key) == "missing"

    def mark_missing(self, key):
        self.capabilities[key] = "missing"
        KeyValue.put("capabilities", self.capabilities)
        self.note(f"{key}: not available through the Personal API, skipping it from now on.")


def history_start():
    first = Activity.objects.aggregate(m=Min("start_local"))["m"]
    if first:
        return first.date()
    return date.today() - timedelta(days=365)


def range_start(model, ctx):
    """Where a date-based data set should resume from."""
    last = None if ctx.full else model.objects.aggregate(m=Max("date"))["m"]
    if last:
        return max(history_start(), last - timedelta(days=3))
    return history_start()


# ---------- phases ----------
def phase_upgrade(ctx):
    from ..rebuild import needs_upgrade, rebuild_all
    if not needs_upgrade():
        return
    ctx.progress("Updating stored data", 0, 0, "reading what is already on disk", force=True)
    files = rebuild_all(lambda i, n: ctx.progress(done=i, total=n))
    ctx.note(f"Stored data updated: {files} activity files re-read.")


def phase_places(ctx):
    from ..places import assign_places
    from ..models import Activity
    from ..places import GEO_VERSION
    n = Activity.objects.filter(geo_version__lt=GEO_VERSION).count()
    if not n:
        return
    ctx.progress("Places", 0, n, "", force=True)
    assign_places(progress=lambda i, total: ctx.progress(done=i, total=total))


def phase_classify(ctx):
    from ..runtypes import classify_runs
    ctx.progress("Run types", 0, 0, "", force=True)
    changed = classify_runs()
    if changed:
        ctx.note(f"Run types: {changed} runs updated.")


def phase_weather(ctx):
    from ..models import Weather
    from ..weather import OUTDOOR, WeatherClient, WeatherError, activity_coords, activity_window, build, wants_weather
    qs = (Activity.objects.filter(category__in=OUTDOOR).select_related("stream")
          .filter(Q(weather__isnull=True) | ~Q(weather__error="")).order_by("-start_local"))
    todo = [a for a in qs if wants_weather(a)]
    if not todo:
        return
    client = WeatherClient()
    ctx.progress("Weather", 0, len(todo), "from Open-Meteo", force=True)
    ok = failed = unreachable = 0
    for i, act in enumerate(todo, 1):
        lat, lon = activity_coords(act)
        start, end = activity_window(act)
        try:
            data = client.hourly(lat, lon, start.date(), end.date())
            fields = build(act, data)
            Weather.objects.update_or_create(activity=act, defaults=dict(fields, lat=lat, lon=lon))
            ok += 1
            unreachable = 0
        except WeatherError as exc:
            failed += 1
            Weather.objects.update_or_create(activity=act, defaults={"lat": lat, "lon": lon, "error": str(exc)[:255]})
            if "limit" in str(exc):
                ctx.note(str(exc))
                break
            if "reach" in str(exc):
                unreachable += 1
                if unreachable >= 3:
                    ctx.note("Weather: Open-Meteo cannot be reached right now; trying again next sync.")
                    break
        except Exception as exc:  # bad data for one activity must not stop the rest
            failed += 1
            Weather.objects.update_or_create(activity=act, defaults={"lat": lat, "lon": lon, "error": f"{exc}"[:255]})
        ctx.progress(done=i)
    ctx.note(f"Weather: {ok} activities, {failed} failed ({client.calls} calls).")

def phase_hr_zones(ctx):
    if ctx.unavailable("hr_zones"):
        return
    ctx.progress("Heart rate zones", 0, 0, "", force=True)
    try:
        raw = ctx.client.get_json(HR_ZONES)
    except GarminNotAvailable:
        ctx.mark_missing("hr_zones")
        return
    KeyValue.put("hr_zones_raw", raw)
    parsed = extract.hr_zone_floors(raw)
    if parsed:
        KeyValue.put("hr_zones", parsed)


def phase_activities(ctx):
    full = ctx.full or not Activity.objects.exists()
    ctx.progress("Activities", 0, 0, "reading your activity list", force=True)
    start, limit, seen, new = 0, 20, 0, 0
    while True:
        try:
            items = ctx.client.get_json(ACTIVITY_LIST, {"start": start, "limit": limit})
        except GarminTooLarge:
            if limit > 5:
                limit //= 2
                continue
            raise
        if isinstance(items, dict):
            items = items.get("activities") or items.get("activityList") or []
        items = items or []
        page_new = 0
        for raw in items:
            act, created = ingest.upsert_activity(raw)
            if act and created:
                new += 1
                page_new += 1
        seen += len(items)
        ctx.run.new_activities = new
        ctx.progress(done=seen, message=f"{new} new")
        if len(items) < limit:
            break
        if not full and page_new == 0:
            break
        start += len(items)
    if new:
        mx = Activity.objects.aggregate(m=Max("max_hr"))["m"]
        if mx:
            KeyValue.put("max_hr_seen", mx)
    ctx.note(f"Activities: {seen} checked, {new} new.")


def phase_details(ctx):
    if ctx.unavailable("activity_file"):
        return
    qs = Activity.objects.filter(Q(detail_status=Activity.DETAIL_PENDING) |
                                 Q(detail_status=Activity.DETAIL_ERROR, detail_attempts__lt=3)).order_by("-start_local")
    ids = list(qs.values_list("activity_id", flat=True))
    total = len(ids)
    ctx.progress("Activity details", 0, total, "downloading activity files", force=True)
    ok = none = errors = misses_in_a_row = 0
    fit_dir = settings.DATA_DIR / "fit"
    for i, act_id in enumerate(ids, 1):
        act = Activity.objects.get(pk=act_id)
        act.detail_attempts += 1
        try:
            blob = ctx.client.get_bytes(ACTIVITY_FILE.format(id=act_id))
            misses_in_a_row = 0
        except GarminNotAvailable:
            misses_in_a_row += 1
            act.detail_status = Activity.DETAIL_NONE
            act.detail_error = "No file on Garmin"
            act.save(update_fields=["detail_status", "detail_error", "detail_attempts"])
            none += 1
            if misses_in_a_row >= 8 and ok == 0:
                # every download fails: the endpoint itself is not available
                Activity.objects.filter(detail_status=Activity.DETAIL_NONE, detail_error="No file on Garmin").update(
                    detail_status=Activity.DETAIL_PENDING, detail_attempts=0, detail_error="")
                ctx.mark_missing("activity_file")
                return
            ctx.progress(done=i)
            continue
        except GarminAuthError:
            raise
        except GarminError as exc:
            act.detail_status = Activity.DETAIL_ERROR
            act.detail_error = str(exc)[:500]
            act.save(update_fields=["detail_status", "detail_error", "detail_attempts"])
            errors += 1
            ctx.progress(done=i)
            continue
        try:
            fit_bytes = fitparse.extract_fit_bytes(blob)
            ext = ".zip" if blob[:2] == b"PK" else ".fit"
            path = fit_dir / f"{act_id}{ext}"
            path.write_bytes(blob)
            if not fit_bytes:
                act.detail_status = Activity.DETAIL_NONE
                act.detail_error = "Download had no FIT recording"
                act.save(update_fields=["detail_status", "detail_error", "detail_attempts"])
                none += 1
            else:
                steps = 2 if act.category in ("run", "walk") else 1
                parsed = fitparse.parse_fit(fit_bytes, steps_per_cycle=steps)
                act.save(update_fields=["detail_attempts"])
                ingest.store_activity_samples(act, parsed, source_file=path.name)
                ok += 1
        except Exception as exc:  # a broken file must not stop the sync
            act.detail_status = Activity.DETAIL_ERROR
            act.detail_error = f"Could not read file: {exc}"[:500]
            act.save(update_fields=["detail_status", "detail_error", "detail_attempts"])
            errors += 1
        ctx.progress(done=i, message=f"{act.start_local:%d %b %Y} {act.name}"[:120])
    ctx.note(f"Activity details: {ok} read, {none} without file, {errors} errors.")


def _range_phase(ctx, key, label, model, chunk_days, fetch, store):
    if ctx.unavailable(key):
        return
    start = range_start(model, ctx)
    end = date.today()
    days = (end - start).days + 1
    ctx.progress(label, 0, days, f"from {start:%d %b %Y}", force=True)
    stored = 0
    try:
        for a, b, payload in ctx.client.fetch_range(start, end, chunk_days, fetch):
            stored += store(payload)
            ctx.progress(done=(b - start).days + 1)
    except GarminNotAvailable:
        ctx.mark_missing(key)
        return
    ctx.note(f"{label}: {stored} days stored.")


def _items(payload, *keys):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, list):
                return v
    return []


def phase_daily(ctx):
    def fetch(a, b):
        return ctx.client.get_json(DAILY, {"startDate": a.isoformat(), "endDate": b.isoformat()})

    def store(p):
        return sum(1 for raw in _items(p, "data", "dailySummaries") if ingest.upsert_daily(raw))
    _range_phase(ctx, "daily", "Daily summaries", DailySummary, 28, fetch, store)


def phase_sleep(ctx):
    def fetch(a, b):
        return ctx.client.get_json(SLEEP, {"startDate": a.isoformat(), "endDate": b.isoformat()})

    def store(p):
        return sum(1 for raw in _items(p, "data", "dailySleepSummaries", "sleepSummaries") if ingest.upsert_sleep(raw))
    _range_phase(ctx, "sleep", "Sleep", SleepNight, 28, fetch, store)


def phase_hrv(ctx):
    def fetch(a, b):
        return ctx.client.get_json(HRV.format(a=a.isoformat(), b=b.isoformat()))

    def store(p):
        return sum(1 for raw in _items(p, "hrvSummaries", "data") if ingest.upsert_hrv(raw))
    _range_phase(ctx, "hrv", "HRV", HrvDay, 28, fetch, store)


def phase_weight(ctx):
    def fetch(a, b):
        return ctx.client.get_json(WEIGHT.format(a=a.isoformat(), b=b.isoformat()))

    def store(p):
        return sum(1 for raw in _items(p, "dailyWeightSummaries", "data") if ingest.upsert_weight(raw))
    _range_phase(ctx, "weight", "Weight", WeightDay, 90, fetch, store)


def phase_vo2(ctx):
    def fetch(a, b):
        return ctx.client.get_json(VO2.format(a=a.isoformat(), b=b.isoformat()))

    def store(p):
        rows = extract.vo2_rows(p)
        for d, sport, v in rows:
            ingest.upsert_vo2(d, sport, v)
        return len(rows)

    class _Vo2Model:  # resume from the last daily (not activity-derived) value
        objects = Vo2Max.objects.filter(source=Vo2Max.SOURCE_DAILY)
    _range_phase(ctx, "vo2max", "VO2max", _Vo2Model, 28, fetch, store)


def phase_fitness_age(ctx):
    if ctx.unavailable("fitness_age"):
        return
    today = date.today()
    if not ctx.full and FitnessAge.objects.filter(date=today).exists():
        return
    ctx.progress("Fitness age", 0, 0, "", force=True)
    try:
        raw = ctx.client.get_json(FITNESS_AGE.format(d=today.isoformat()))
    except GarminNotAvailable:
        ctx.mark_missing("fitness_age")
        return
    ingest.upsert_fitness_age(today, raw)


PHASES = [
    ("upgrade", phase_upgrade),
    ("hr_zones", phase_hr_zones),
    ("activities", phase_activities),
    ("details", phase_details),
    ("places", phase_places),
    ("classify", phase_classify),
    ("weather", phase_weather),
    ("daily", phase_daily),
    ("sleep", phase_sleep),
    ("hrv", phase_hrv),
    ("vo2max", phase_vo2),
    ("weight", phase_weight),
    ("fitness_age", phase_fitness_age),
]


# ---------- runner ----------
def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def current_run():
    run = SyncRun.objects.filter(status=SyncRun.RUNNING).first()
    if not run:
        return None
    dead = run.pid is not None and not _alive(run.pid)
    stale = run.heartbeat_at and now() - run.heartbeat_at > STALE_AFTER
    if dead or stale:
        run.status = SyncRun.FAILED
        run.error = "Stopped: the app was closed or restarted while syncing. Sync again to continue."
        run.message = run.error[:255]
        run.finished_at = now()
        run.save()
        return None
    return run


def run_sync(full=False, recheck=False, echo=None, run=None):
    """Run a sync in the current thread. Returns the SyncRun."""
    if run is None:
        run = SyncRun.objects.create(mode="full" if full else "incremental", heartbeat_at=now(), pid=os.getpid())
    if recheck:
        KeyValue.put("capabilities", {})
    ctx = Context(run, GarminClient(), full=full, echo=echo)
    try:
        if not ctx.client.key_is_set():
            raise GarminAuthError("No Garmin key found. Put GARMIN_PERSONAL_API_KEY=... in the .env file.")
        ctx.client.token()
        for key, fn in PHASES:
            try:
                fn(ctx)
            except GarminAuthError:
                raise
            except Exception as exc:
                ctx.problems.append(key)
                ctx.note(f"{key}: failed ({exc.__class__.__name__}: {exc})")
                log.debug(traceback.format_exc())
        run.status = SyncRun.PARTIAL if ctx.problems else SyncRun.OK
        run.message = f"{run.new_activities} new activities" + (f"; problems with {', '.join(ctx.problems)}" if ctx.problems else "")
    except GarminAuthError as exc:
        run.status = SyncRun.FAILED
        run.error = str(exc)
        run.message = str(exc)[:255]
    except Exception as exc:
        run.status = SyncRun.FAILED
        run.error = f"{exc.__class__.__name__}: {exc}"
        run.message = run.error[:255]
        log.exception("Sync failed")
    run.phase = "Done" if run.status != SyncRun.FAILED else "Failed"
    run.finished_at = now()
    run.heartbeat_at = now()
    run.save()
    KeyValue.put("last_sync", {"at": run.finished_at.isoformat(), "status": run.status, "calls": ctx.client.calls})
    return run


def start_background_sync(full=False):
    """Start a sync thread unless one is running. Returns the SyncRun."""
    with _lock:
        existing = current_run()
        if existing:
            return existing
        run = SyncRun.objects.create(mode="full" if full else "incremental", heartbeat_at=now(),
                                     pid=os.getpid(), phase="Starting")

    def target():
        close_old_connections()
        try:
            run_sync(full=full, run=run)
        finally:
            close_old_connections()

    threading.Thread(target=target, name="garmin-sync", daemon=True).start()
    return run
