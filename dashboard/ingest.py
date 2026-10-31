"""Store Garmin records in the database. Shared by sync, demo data and rebuilds."""
from django.db import transaction

from . import streams
from .garmin import extract
from .models import (Activity, ActivityLap, ActivityStream, BestEffort, DailySummary, FitnessAge,
                     HrvDay, KeyValue, SleepNight, Vo2Max, WeightDay)

DEFAULT_ZONE_PCTS = (0.50, 0.60, 0.70, 0.80, 0.90)


def zone_floors():
    """Floors (bpm) for zones 1-5: Garmin's settings if we have them, else % of max HR."""
    z = KeyValue.get("hr_zones")
    if z and z.get("floors"):
        return z["floors"]
    max_hr = KeyValue.get("max_hr_seen")
    if not max_hr:
        from django.db.models import Max
        max_hr = Activity.objects.aggregate(m=Max("max_hr"))["m"]
    if not max_hr:
        return None
    return [round(max_hr * p) for p in DEFAULT_ZONE_PCTS]


def upsert_activity(raw: dict):
    """Returns (activity, created)."""
    act_id = raw.get("activityId")
    if act_id is None:
        return None, False
    fields = extract.activity_fields(raw)
    if fields["start_local"] is None:
        return None, False
    if fields.get("vo2max") is None:
        fields.pop("vo2max", None)  # keep the value read from the activity file
    obj = Activity.objects.filter(pk=act_id).first()
    if obj is None:
        obj = Activity(activity_id=act_id, raw=raw, **fields)
        obj.save()
        _activity_vo2(obj)
        return obj, True
    for k, v in fields.items():
        setattr(obj, k, v)
    obj.raw = raw
    obj.save()
    _activity_vo2(obj)
    return obj, False


def _activity_vo2(act):
    """One VO2max per day and sport: the value from that day's latest activity."""
    if act.vo2max and act.category in ("run", "cycle"):
        sport = "cycling" if act.category == "cycle" else "running"
        d = act.start_local.date()
        latest = (Activity.objects.filter(category=act.category, start_local__date=d, vo2max__isnull=False)
                  .order_by("-start_local").first())
        value = latest.vo2max if latest else act.vo2max
        existing = Vo2Max.objects.filter(date=d, sport=sport).first()
        if existing is None:
            Vo2Max.objects.create(date=d, sport=sport, value=value, source=Vo2Max.SOURCE_ACTIVITY)
        elif existing.source == Vo2Max.SOURCE_ACTIVITY and existing.value != value:
            existing.value = value
            existing.save(update_fields=["value"])


@transaction.atomic
def store_activity_samples(act: Activity, parsed: dict, source_file: str = ""):
    """parsed = {"samples": {...}, "laps": [...]} from fitparse or demo data."""
    samples = parsed.get("samples") or {}
    result = streams.process(samples, act.category, zone_floors()) if samples else None
    if parsed.get("vo2max") and act.category in ("run", "cycle"):
        act.vo2max = parsed["vo2max"]
        act.save(update_fields=["vo2max"])
        _activity_vo2(act)

    ActivityLap.objects.filter(activity=act).delete()
    ActivityLap.objects.bulk_create([
        ActivityLap(activity=act, index=i + 1, **{k: lap.get(k) for k in (
            "start_offset_s", "duration_s", "distance_m", "avg_speed", "avg_hr", "max_hr",
            "avg_cadence", "elev_gain_m", "elev_loss_m", "avg_power")})
        for i, lap in enumerate(parsed.get("laps") or [])
    ])

    BestEffort.objects.filter(activity=act).delete()
    if not result:
        ActivityStream.objects.filter(activity=act).delete()
        act.route_svg = ""
        act.detail_status = Activity.DETAIL_NONE if not parsed.get("laps") else Activity.DETAIL_OK
        act.save(update_fields=["route_svg", "detail_status"])
        return act

    ActivityStream.objects.update_or_create(activity=act, defaults={
        "data": result["stream"], "splits": result["splits"], "zone_s": result["zone_s"],
        "source_file": source_file, "sample_count": result["count"],
    })
    BestEffort.objects.bulk_create([
        BestEffort(activity=act, category=act.category, distance_m=dist, seconds=secs,
                   start_offset_s=start, date=act.start_local.date())
        for dist, (secs, start) in result["efforts"].items()
    ])
    act.route_svg = result["route"]
    act.geo_version = 0  # place and map route are worked out again from the new track
    act.detail_status = Activity.DETAIL_OK
    act.detail_error = ""
    act.save(update_fields=["route_svg", "detail_status", "detail_error", "geo_version"])
    return act


def upsert_daily(raw):
    d = extract.daily_date(raw)
    if not d:
        return False
    fields = extract.daily_fields(raw)
    if not any(v is not None for v in fields.values()):
        return False
    DailySummary.objects.update_or_create(date=d, defaults=dict(fields, raw=raw))
    return True


def upsert_sleep(raw):
    d = extract.sleep_date(raw)
    if not d:
        return False
    fields = extract.sleep_fields(raw)
    if not fields.get("total_s"):
        return False
    SleepNight.objects.update_or_create(date=d, defaults=dict(fields, raw=raw))
    return True


def upsert_hrv(raw):
    d = extract.parse_date(extract.dig(raw, "calendarDate", "date"))
    if not d:
        return False
    fields = extract.hrv_fields(raw)
    if not (fields["last_night"] or fields["weekly_avg"]):
        return False
    HrvDay.objects.update_or_create(date=d, defaults=dict(fields, raw=raw))
    return True


def upsert_weight(raw):
    d = extract.weight_date(raw)
    if not d:
        return False
    fields = extract.weight_fields(raw)
    if not fields["weight_kg"]:
        return False
    WeightDay.objects.update_or_create(date=d, defaults=dict(fields, raw=raw))
    return True


def upsert_vo2(d, sport, value):
    Vo2Max.objects.update_or_create(date=d, sport=sport, defaults={"value": value, "source": Vo2Max.SOURCE_DAILY})


def upsert_fitness_age(d, raw):
    fields = extract.fitness_age_fields(raw or {})
    if not fields["fitness_age"]:
        return False
    FitnessAge.objects.update_or_create(date=d, defaults=dict(fields, raw=raw))
    return True
