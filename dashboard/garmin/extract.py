"""Map raw Garmin JSON to model fields. Field names follow what Garmin returns
today; each lookup tries a few spellings so small API changes do not break it.
If Garmin renames something, fix it here and run: manage.py rebuild_from_raw
"""
from datetime import date, datetime, timezone

from ..sports import categorize


def dig(obj, *paths, default=None):
    """dig(raw, "a.b.c", "x.y") -> first non-None value found."""
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def parse_dt(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # epoch millis
        try:
            secs = v / 1000.0 if v > 1e11 else v
            return datetime.fromtimestamp(secs, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip().replace("T", " ").rstrip("Z")
        if "+" in s[10:]:
            s = s[: 10 + s[10:].index("+")]
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def parse_date(v):
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    dt = parse_dt(v)
    return dt.date() if dt else None


def activity_fields(raw: dict) -> dict:
    type_key = dig(raw, "activityType.typeKey", "activityTypeDTO.typeKey", default="other")
    category = categorize(type_key)
    start_local = parse_dt(dig(raw, "startTimeLocal", "summaryDTO.startTimeLocal"))
    start_gmt = parse_dt(dig(raw, "startTimeGMT", "summaryDTO.startTimeGMT", "beginTimestamp"))
    if start_local is None:
        start_local = start_gmt
    is_bike = category == "cycle"
    cadence = num(dig(raw, "averageBikingCadenceInRevPerMinute") if is_bike else
                  dig(raw, "averageRunningCadenceInStepsPerMinute", "averageSwimCadenceInStrokesPerMinute"))
    max_cadence = num(dig(raw, "maxBikingCadenceInRevPerMinute") if is_bike else
                      dig(raw, "maxRunningCadenceInStepsPerMinute"))
    return {
        "name": (dig(raw, "activityName", default="") or "")[:255],
        "type_key": type_key or "",
        "category": category,
        "event_type": dig(raw, "eventType.typeKey", "eventTypeDTO.typeKey", default="") or "",
        "start_local": start_local,
        "start_gmt": start_gmt,
        "distance_m": num(dig(raw, "distance")),
        "duration_s": num(dig(raw, "duration")),
        "moving_s": num(dig(raw, "movingDuration")),
        "elapsed_s": num(dig(raw, "elapsedDuration")),
        "elev_gain_m": num(dig(raw, "elevationGain")),
        "elev_loss_m": num(dig(raw, "elevationLoss")),
        "avg_speed": num(dig(raw, "averageSpeed")),
        "max_speed": num(dig(raw, "maxSpeed")),
        "avg_hr": num(dig(raw, "averageHR", "averageHr")),
        "max_hr": num(dig(raw, "maxHR", "maxHr")),
        "calories": num(dig(raw, "calories")),
        "avg_cadence": cadence,
        "max_cadence": max_cadence,
        "avg_stride_cm": num(dig(raw, "avgStrideLength")),
        "steps": int(num(dig(raw, "steps")) or 0) or None,
        "avg_power": num(dig(raw, "avgPower")),
        "max_power": num(dig(raw, "maxPower")),
        "norm_power": num(dig(raw, "normPower")),
        "aerobic_te": num(dig(raw, "aerobicTrainingEffect")),
        "anaerobic_te": num(dig(raw, "anaerobicTrainingEffect")),
        "te_label": str(dig(raw, "trainingEffectLabel", default="") or "")[:48],
        "training_load": num(dig(raw, "activityTrainingLoad")),
        "vo2max": num(dig(raw, "vO2MaxValue", "vo2MaxValue")),
        "hr_z1": num(dig(raw, "hrTimeInZone_1")),
        "hr_z2": num(dig(raw, "hrTimeInZone_2")),
        "hr_z3": num(dig(raw, "hrTimeInZone_3")),
        "hr_z4": num(dig(raw, "hrTimeInZone_4")),
        "hr_z5": num(dig(raw, "hrTimeInZone_5")),
        "min_temp": num(dig(raw, "minTemperature")),
        "max_temp": num(dig(raw, "maxTemperature")),
        "start_lat": num(dig(raw, "startLatitude")),
        "start_lon": num(dig(raw, "startLongitude")),
        "location_name": (dig(raw, "locationName", default="") or "")[:128],
        "lap_count": int(num(dig(raw, "lapCount")) or 0) or None,
        "avg_gct_ms": num(dig(raw, "avgGroundContactTime")),
        "avg_vert_osc_cm": num(dig(raw, "avgVerticalOscillation")),
        "avg_vert_ratio": num(dig(raw, "avgVerticalRatio")),
    }


def daily_date(raw):
    return parse_date(dig(raw, "calendarDate", "date", "summaryDate"))


def daily_fields(raw: dict) -> dict:
    return {
        "steps": int(num(dig(raw, "movement.steps.value", "steps.value", "totalSteps", "steps")) or 0) or None,
        "distance_m": num(dig(raw, "movement.distance.value", "movement.distanceInMeters", "totalDistanceMeters")),
        "resting_hr": num(dig(raw, "heartRate.restingValue", "heartRate.resting", "restingHeartRate")),
        "min_hr": num(dig(raw, "heartRate.minValue", "minHeartRate")),
        "max_hr": num(dig(raw, "heartRate.maxValue", "maxHeartRate")),
        "avg_stress": num(dig(raw, "stress.avgLevel", "stress.averageLevel", "averageStressLevel")),
        "max_stress": num(dig(raw, "stress.maxLevel", "maxStressLevel")),
        "bb_max": num(dig(raw, "bodyBattery.maxValue", "bodyBatteryHighestValue")),
        "bb_min": num(dig(raw, "bodyBattery.minValue", "bodyBatteryLowestValue")),
        "bb_charged": num(dig(raw, "bodyBattery.chargedValue", "bodyBatteryChargedValue")),
        "bb_drained": num(dig(raw, "bodyBattery.drainedValue", "bodyBatteryDrainedValue")),
        "im_moderate": num(dig(raw, "intensityMinutes.moderate", "intensityMinutes.moderateValue", "moderateIntensityMinutes")),
        "im_vigorous": num(dig(raw, "intensityMinutes.vigorous", "intensityMinutes.vigorousValue", "vigorousIntensityMinutes")),
        "resp_avg": num(dig(raw, "respiration.avgValue", "respiration.avgWakingValue", "avgWakingRespirationValue")),
        "spo2_avg": num(dig(raw, "pulseOx.avgValue", "spo2.avgValue", "averageSpo2")),
        "kcal_total": num(dig(raw, "calories.burnedTotal", "calories.total", "calories.totalValue", "totalKilocalories")),
        "kcal_active": num(dig(raw, "calories.burnedActive", "calories.active", "calories.activeValue", "activeKilocalories")),
        "kcal_resting": num(dig(raw, "calories.burnedResting", "calories.resting", "bmrKilocalories")),
        "floors_up": num(dig(raw, "movement.floorsAscended.value", "floors.ascended", "floorsAscended")),
        "floors_down": num(dig(raw, "movement.floorsDescended.value", "floors.descended", "floorsDescended")),
        "steps_goal": int(num(dig(raw, "movement.steps.goal", "dailyStepGoal")) or 0) or None,
        "spo2_min": num(dig(raw, "pulseOx.minValue", "lowestSpo2")),
        "resp_min": num(dig(raw, "respiration.minValue", "lowestRespirationValue")),
        "resp_max": num(dig(raw, "respiration.maxValue", "highestRespirationValue")),
        "stress_rest_s": _ms(dig(raw, "stress.restDurationInMillis")),
        "stress_low_s": _ms(dig(raw, "stress.lowStressDurationInMillis")),
        "stress_med_s": _ms(dig(raw, "stress.mediumStressDurationInMillis")),
        "stress_high_s": _ms(dig(raw, "stress.highStressDurationInMillis")),
        "hydration_ml": num(dig(raw, "hydration.consumedInMl")) or None,
    }


def _ms(v):
    v = num(v)
    return v / 1000.0 if v is not None else None


def sleep_date(raw):
    return parse_date(dig(raw, "calendarDate", "dailySleepDTO.calendarDate", "date"))


def sleep_fields(raw: dict) -> dict:
    base = raw.get("dailySleepDTO") if isinstance(raw.get("dailySleepDTO"), dict) else raw
    return {
        "total_s": num(dig(base, "sleepTimeSeconds", "totalSleepSeconds")),
        "deep_s": num(dig(base, "deepSleepSeconds")),
        "light_s": num(dig(base, "lightSleepSeconds")),
        "rem_s": num(dig(base, "remSleepSeconds")),
        "awake_s": num(dig(base, "awakeSleepSeconds")),
        "score": num(dig(base, "sleepScores.overall.value", "sleepScore.value", "overallSleepScore", "sleepScore")),
        "start_local": parse_dt(dig(base, "sleepStartTimestampLocal", "sleepStartLocal")),
        "end_local": parse_dt(dig(base, "sleepEndTimestampLocal", "sleepEndLocal")),
        "resp_avg": num(dig(base, "averageRespirationValue", "avgSleepRespiration")),
        "spo2_avg": num(dig(base, "averageSpO2Value", "avgSleepSpo2")),
        "avg_hr": num(dig(base, "avgHeartRate")),
        "resp_low": num(dig(base, "lowestRespirationValue")),
        "resp_high": num(dig(base, "highestRespirationValue")),
        "spo2_low": num(dig(base, "lowestSpO2Value")),
        "sleep_stress": num(dig(base, "avgSleepStress")),
        "awake_count": int(num(dig(base, "awakeCount")) or 0) if dig(base, "awakeCount") is not None else None,
        "need_min": num(dig(base, "sleepNeed.actual")),
        "nap_s": num(dig(base, "napTimeSeconds")),
    }


def hrv_fields(raw: dict) -> dict:
    return {
        "last_night": num(dig(raw, "lastNightAvg", "lastNight")),
        "weekly_avg": num(dig(raw, "weeklyAvg")),
        "status": str(dig(raw, "status", default="") or "")[:24],
        "baseline_low": num(dig(raw, "baseline.balancedLow", "baseline.lowUpper")),
        "baseline_high": num(dig(raw, "baseline.balancedUpper")),
    }


def weight_fields(raw: dict) -> dict:
    w = num(dig(raw, "latestWeight.weight", "weight"))
    if w and w > 1000:  # grams
        w = w / 1000.0
    return {
        "weight_kg": w,
        "bmi": num(dig(raw, "latestWeight.bmi", "bmi")),
        "body_fat": num(dig(raw, "latestWeight.bodyFat", "bodyFat")),
    }


def weight_date(raw):
    return parse_date(dig(raw, "summaryDate", "calendarDate", "latestWeight.calendarDate", "date"))


def vo2_rows(raw):
    """maxmet responses: list of {generic: {calendarDate, vo2MaxPreciseValue}, cycling: {...}}."""
    rows = []
    items = raw if isinstance(raw, list) else (raw or {}).get("maxMetrics") or []
    for it in items:
        for sport_key, sport in (("generic", "running"), ("running", "running"), ("cycling", "cycling")):
            part = it.get(sport_key) if isinstance(it, dict) else None
            if isinstance(part, dict):
                d = parse_date(part.get("calendarDate"))
                v = num(part.get("vo2MaxPreciseValue")) or num(part.get("vo2MaxValue"))
                if d and v:
                    rows.append((d, sport, v))
    return rows


def hr_zone_floors(raw):
    """Pick the zone floors to use (running if present, else default)."""
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    chosen = None
    for it in items:
        if not isinstance(it, dict):
            continue
        sport = str(it.get("sport", "")).upper()
        if chosen is None or sport == "RUNNING":
            chosen = it
    if not chosen:
        return None
    floors = [num(chosen.get(f"zone{i}Floor")) for i in range(1, 6)]
    if all(floors):
        return {"floors": floors, "max": num(chosen.get("maxHeartRateUsed")),
                "resting": num(chosen.get("restingHeartRateUsed")),
                "method": chosen.get("trainingMethod", ""), "sport": chosen.get("sport", "")}
    return None


def fitness_age_fields(raw: dict) -> dict:
    return {
        "fitness_age": num(dig(raw, "fitnessAge")),
        "chrono_age": num(dig(raw, "chronologicalAge")),
        "achievable": num(dig(raw, "achievableFitnessAge")),
    }
