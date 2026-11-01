"""Synthetic but realistic data in Garmin's own JSON shapes.

Used by `manage.py seed_demo` (to preview the dashboard) and by the mock Garmin
server in devtools/ (to test the sync). Nothing here touches the real API.
"""
import math
import random
from datetime import date, datetime, time, timedelta

# A made-up runner who lives in one city, does long runs and rides in the next
# town over, and travels a few times a year.
PLACES = {
    "park": ("Amsterdam", 52.3580, 4.8686, 2),
    "river": ("Amsterdam", 52.3483, 4.9040, 1),
    "track": ("Amsterdam", 52.3433, 4.8550, 1),
    "office": ("Amsterdam", 52.3383, 4.8728, 1),
    "dunes": ("Haarlem", 52.3874, 4.6462, 5),
    "nyc": ("New York", 40.7812, -73.9665, 30),
    "london": ("London", 51.5073, -0.1657, 25),
    "lisbon": ("Lisbon", 38.7139, -9.1394, 50),
}
TRIPS = [(30, 5, "nyc"), (150, 4, "london"), (300, 6, "lisbon"), (520, 5, "nyc"), (700, 4, "london"), (900, 5, "lisbon")]

TE_LABELS = {
    "recovery": "RECOVERY", "easy": "BASE", "long": "BASE", "tempo": "TEMPO",
    "intervals": "VO2MAX", "tt5k": "THRESHOLD", "race": "THRESHOLD",
}

HR_REST, HR_MAX = 50, 186
ZONE_FLOORS = [93, 112, 130, 149, 167]


class Demo:
    def __init__(self, days=3 * 365, seed=42, today=None):
        self.rng = random.Random(seed)
        self.today = today or date.today()
        self.start = self.today - timedelta(days=days)
        self.next_id = 17_000_000_000
        self.activities = []   # list of dicts: raw, samples, laps
        self.daily, self.sleep, self.hrv, self.weight, self.vo2 = [], [], [], [], []

    # fitness from 0 (start) to 1 (today), with a 5-week break about 16 months ago
    def fitness(self, d):
        x = (d - self.start).days / max((self.today - self.start).days, 1)
        f = 1 - math.exp(-2.4 * x)
        f = f / (1 - math.exp(-2.4))
        brk = self.today - timedelta(days=480)
        if brk <= d < brk + timedelta(days=35):
            f -= 0.12
        elif brk + timedelta(days=35) <= d < brk + timedelta(days=95):
            f -= 0.12 * (1 - (d - brk - timedelta(days=35)).days / 60)
        return max(0.0, min(1.0, f))

    def in_break(self, d):
        brk = self.today - timedelta(days=480)
        return brk <= d < brk + timedelta(days=35)

    def build(self):
        d = self.start
        races = self.race_calendar()
        self.trips = {}
        for back, length, place in TRIPS:
            for i in range(length):
                self.trips[self.today - timedelta(days=back - i)] = place
        while d <= self.today:
            self.day(d, races.get(d))
            d += timedelta(days=1)
        self.activities.sort(key=lambda a: a["raw"]["startTimeLocal"])
        return self

    def race_calendar(self):
        races = {}
        for back, dist, name in ((8, 10000, "City 10K"), (60, 21097, "Autumn Half Marathon"),
                                 (200, 10000, "Spring 10K"), (420, 21097, "City Half Marathon"),
                                 (620, 10000, "River 10K"), (760, 21097, "Coastal Half Marathon")):
            rd = self.today - timedelta(days=back)
            while rd.weekday() != 6:  # races on Sunday
                rd -= timedelta(days=1)
            if rd >= self.start:
                races[rd] = (dist, name)
        return races

    def day(self, d, race):
        r = self.rng
        wd = d.weekday()
        f = self.fitness(d)
        broke = self.in_break(d)
        trip = self.trips.get(d)
        # runs
        if not broke and trip:
            if r.random() < 0.7:
                if wd >= 5:
                    self.run(d, "long", 12000 + 5000 * f, place=trip, hour=8)
                else:
                    self.run(d, "easy", 6000 + 2000 * f + r.uniform(-800, 800), place=trip, hour=7)
        elif not broke:
            if race:
                start, end = self.run(d, "race", race[0], name=race[1], place="river", hour=9)
                # a warm-up before and a cool-down after: one session on the dashboard
                self.run(d, "easy", 2000 + r.uniform(-300, 300), place="river", start=start - timedelta(minutes=24))
                if r.random() < 0.6:
                    self.run(d, "recovery", 1500 + r.uniform(-300, 300), place="river", start=end + timedelta(minutes=6))
            elif wd == 1 and r.random() < 0.85:
                self.run(d, "intervals", 9000, place="track", hour=19)
            elif wd == 3 and r.random() < 0.8:
                self.run(d, "tempo", 9000 + 2000 * f, place="office", hour=12)
            elif wd == 4 and r.random() < 0.35:
                start, _end = self.run(d, "tt5k", 5000, name="Track 5K time trial", place="track", hour=18)
                self.run(d, "easy", 2000 + r.uniform(-300, 300), place="track", start=start - timedelta(minutes=22))
            elif wd == 6 and r.random() < 0.85:
                self.run(d, "long", 13000 + 8000 * f + r.uniform(-1500, 1500), place="dunes", hour=8)
            elif wd in (0, 4, 5) and r.random() < 0.55:
                self.run(d, "easy", 6000 + 3000 * f + r.uniform(-800, 800), place="park", hour=7)
            elif wd == 2 and r.random() < 0.3:
                self.run(d, "recovery", 5000, place="river", hour=7)
        # walks
        if r.random() < (0.75 if wd < 5 else 0.45):
            self.walk(d, place=trip or ("office" if wd < 5 and wd != 0 else "park"))
        # cycling on summer weekends, strength at home
        if not trip and d.month in (5, 6, 7, 8, 9) and wd == 5 and r.random() < 0.35:
            self.ride(d)
        if not trip and wd == 2 and r.random() < 0.6:
            self.strength(d)
        self.wellness(d, f, broke)

    # ---------- samples ----------
    def pace_targets(self, f):
        return {
            "recovery": 360 - 20 * f, "easy": 342 - 24 * f, "long": 350 - 25 * f,
            "tempo": 292 - 22 * f, "interval": 252 - 20 * f, "tt5k": 266 - 26 * f,
            "race10": 276 - 22 * f, "race21": 291 - 22 * f, "jog": 400,
        }

    def segments(self, kind, dist, f):
        p = self.pace_targets(f)
        if kind == "intervals":
            segs = [(2000, p["easy"], "Warm up")]
            for i in range(8):
                segs += [(600, p["interval"], f"Rep {i + 1}"), (300, p["jog"], "Recover")]
            segs.append((max(1500.0, dist - 2000 - 7200), p["easy"] + 10, "Cool down"))
            return segs
        if kind == "tempo":
            tempo_d = dist - 3500
            return [(2000, p["easy"], "Warm up"), (tempo_d, p["tempo"], "Tempo"), (1500, p["easy"] + 10, "Cool down")]
        if kind == "long":
            return [(dist - 3000, p["long"], None), (3000, p["long"] - 18, None)]
        if kind == "tt5k":
            return [(5000, p["tt5k"], None)]
        if kind == "race":
            key = "race21" if dist > 15000 else "race10"
            return [(dist, p[key], None)]
        return [(dist, p[kind], None)]

    def run(self, d, kind, dist, name=None, place="park", hour=7, start=None):
        """One run; returns its start and end. Time trials, races and recovery runs keep to the same route
        each time (a course), the others wander."""
        r = self.rng
        f = self.fitness(d)
        segs = self.segments(kind, dist, f)
        v_thr = 1000.0 / (self.pace_targets(f)["tempo"] - 4)
        start = start or datetime.combine(d, time(hour, r.randint(0, 40), r.randint(0, 59)))
        course = f"{place}-{kind}-{round(dist / 1000)}" if kind in ("tt5k", "race", "recovery") and dist >= 4000 else None
        samples, laps = self.simulate(segs, start, place, dt=2.0, v_thr=v_thr, kind="run",
                                      auto_lap=kind not in ("intervals", "tempo"), course=course)
        town = PLACES[place][0]
        label = {"race": name, "tt5k": name}.get(kind) or f"{town} Running"
        self.add("running", label, start, samples, laps, kind=kind, race=(kind == "race"))
        return start, start + timedelta(seconds=samples["t"][-1])

    def walk(self, d, place="park"):
        r = self.rng
        hour = r.choice([8, 12, 13, 17, 18])
        start = datetime.combine(d, time(hour, r.randint(0, 59), r.randint(0, 59)))
        dist = r.uniform(1800, 6500)
        samples, laps = self.simulate([(dist, r.uniform(640, 760), None)], start, place, dt=4.0,
                                      v_thr=3.6, kind="walk", auto_lap=True)
        kind = "hiking" if dist > 6000 and d.weekday() >= 5 else "walking"
        self.add(kind, f"{PLACES[place][0]} Walking", start, samples, laps, kind="walk")

    def ride(self, d):
        r = self.rng
        start = datetime.combine(d, time(10, r.randint(0, 50), 0))
        dist = r.uniform(30000, 70000)
        samples, laps = self.simulate([(dist, 3600 / r.uniform(24, 29), None)], start, "dunes", dt=5.0,
                                      v_thr=9.5, kind="cycle", auto_lap=True, lap_every=5000)
        self.add("road_biking", "Haarlem Road Cycling", start, samples, laps, kind="ride")

    def strength(self, d):
        r = self.rng
        start = datetime.combine(d, time(20, r.randint(0, 30), 0))
        n = int(r.uniform(1800, 2700) / 5)
        t, hr, h = [], [], 85.0
        for i in range(n):
            target = 115 + 25 * math.sin(i / 9.0) + r.uniform(-6, 6)
            h += (target - h) * 0.2
            t.append(i * 5.0)
            hr.append(round(h))
        self.add("strength_training", "Strength", start, {"t": t, "hr": hr}, [], kind="strength")

    def simulate(self, segs, start, place, dt, v_thr, kind, auto_lap, lap_every=1000, course=None):
        r = self.rng
        _town, lat, lon, base_alt = PLACES[place]
        total = sum(s[0] for s in segs)
        heading = r.uniform(0, 2 * math.pi)
        turn = 2 * math.pi / max(total, 1) * r.choice([-1, 1]) * r.uniform(0.85, 1.15)
        wobble = 0.03
        if course:  # the same loop every time: fixed start heading and direction, little wobble
            cr = random.Random(course)
            heading = cr.uniform(0, 2 * math.pi)
            turn = 2 * math.pi / max(total, 1) * cr.choice([-1, 1])
            wobble = 0.004
        hill_a, hill_b = r.uniform(4, 14), r.uniform(1, 5)
        ph1, ph2 = r.uniform(0, 6), r.uniform(0, 6)
        t = dist = 0.0
        hr = 78.0 if kind != "walk" else 72.0
        out = {k: [] for k in ("t", "d", "hr", "spd", "cad", "alt", "lat", "lon", "tmp")}
        laps, lap_start = [], (0.0, 0.0, 0)
        seg_bounds, acc = [], 0.0
        for s in segs:
            acc += s[0]
            seg_bounds.append(acc)
        seg_i = 0
        v = 1000.0 / segs[0][1]
        temp = r.uniform(6, 17) if start.month not in (6, 7, 8) else r.uniform(13, 22)
        for k, v0 in (("t", 0.0), ("d", 0.0), ("hr", round(hr)), ("spd", 0.0), ("cad", None), ("alt", base_alt),
                      ("lat", lat), ("lon", lon), ("tmp", round(temp, 1))):
            out[k].append(v0)
        out["cad"][-1] = 0
        while dist < total:
            while seg_i < len(segs) - 1 and dist >= seg_bounds[seg_i]:
                if not auto_lap:
                    laps.append(self._lap(out, lap_start))
                    lap_start = (t, dist, len(out["t"]))
                seg_i += 1
            v_target = 1000.0 / segs[seg_i][1] * (1 + r.uniform(-0.03, 0.03))
            alt = base_alt + hill_a * math.sin(dist / 900 + ph1) + hill_b * math.sin(dist / 230 + ph2)
            grade = (hill_a / 900 * math.cos(dist / 900 + ph1) + hill_b / 230 * math.cos(dist / 230 + ph2))
            v += (v_target * (1 - 2.5 * grade) - v) * 0.15
            v = max(v, 0.6)
            # heart rate follows effort with a lag, plus drift
            if kind == "cycle":
                effort = (v / v_thr) ** 1.3
                target_hr = HR_REST + 40 + (HR_MAX - HR_REST - 40) * min(effort, 1.1) * 0.84 + t / 60 * 0.06
            else:
                # share of heart rate reserve: easy pace ~ zone 2, threshold pace ~ zone 4, faster ~ zone 5
                frac = 0.544 + 1.77 * (v / v_thr - 0.85) + 2.0 * max(grade, 0)
                target_hr = HR_REST + (HR_MAX - HR_REST) * max(0.35, min(frac, 0.97)) + t / 60 * 0.06
            if kind == "walk":
                target_hr = 88 + 30 * (v / 1.6) ** 2
            hr += (target_hr - hr) * (dt / 28.0)
            heading += turn * v * dt + r.gauss(0, wobble)
            step = v * dt
            lat += step * math.cos(heading) / 111320.0
            lon += step * math.sin(heading) / (111320.0 * math.cos(math.radians(lat)))
            t += dt
            dist += step
            cad = (152 + 9 * v + r.uniform(-2, 2)) if kind == "run" else (
                108 + 8 * v + r.uniform(-3, 3) if kind == "walk" else 82 + r.uniform(-6, 6))
            out["t"].append(round(t, 1))
            out["d"].append(round(dist, 2))
            out["hr"].append(round(min(hr + r.uniform(-1.5, 1.5), HR_MAX + 2)))
            out["spd"].append(round(v, 3))
            out["cad"].append(round(cad))
            out["alt"].append(round(alt, 1))
            out["lat"].append(lat)
            out["lon"].append(lon)
            out["tmp"].append(round(temp + t / 3600, 1))
            if auto_lap and dist - lap_start[1] >= lap_every:
                laps.append(self._lap(out, lap_start))
                lap_start = (t, dist, len(out["t"]))
        if len(out["t"]) - lap_start[2] > 1:
            laps.append(self._lap(out, lap_start))
        return out, laps

    @staticmethod
    def _lap(out, lap_start):
        t0, d0, i0 = lap_start
        ts, ds, hr, cad, alt = out["t"][i0:], out["d"][i0:], out["hr"][i0:], out["cad"][i0:], out["alt"][i0:]
        if not ts:
            return {}
        dur = ts[-1] - t0
        dist = ds[-1] - d0
        gain = sum(max(b - a, 0) for a, b in zip(alt, alt[1:]))
        loss = sum(max(a - b, 0) for a, b in zip(alt, alt[1:]))
        return {"start_offset_s": t0, "duration_s": dur, "distance_m": dist,
                "avg_speed": dist / dur if dur else None, "avg_hr": sum(hr) / len(hr),
                "max_hr": max(hr), "avg_cadence": sum(cad) / len(cad), "elev_gain_m": gain,
                "elev_loss_m": loss, "avg_power": None}

    def add(self, type_key, name, start, samples, laps, kind, race=False):
        r = self.rng
        self.next_id += r.randint(3, 40)
        t = samples["t"]
        dur = t[-1] if t else 0
        dist = samples.get("d", [0])[-1] if samples.get("d") else None
        hr = samples.get("hr") or []
        zones = [0.0] * 5
        for i in range(1, len(t)):
            h = hr[i]
            if h >= ZONE_FLOORS[0]:
                z = max(zi for zi in range(5) if h >= ZONE_FLOORS[zi])
                zones[z] += t[i] - t[i - 1]
        alt = samples.get("alt") or []
        gain = sum(max(b - a, 0) for a, b in zip(alt, alt[1:])) if alt else None
        loss = sum(max(a - b, 0) for a, b in zip(alt, alt[1:])) if alt else None
        avg_hr = sum(hr) / len(hr) if hr else None
        intensity = ((avg_hr or 100) - HR_REST) / (HR_MAX - HR_REST)
        aerobic = round(min(5.0, 0.6 + intensity * 3.2 + dur / 3600 * 0.9), 1) if hr else None
        anaerobic = round(min(4.5, max(0.0, (intensity - 0.72) * 9 + (1.6 if kind == "intervals" else 0))), 1) if hr else None
        load = round(dur / 60 * (intensity ** 2) * 2.1) if hr else None
        is_run = type_key == "running"
        cad = samples.get("cad") or []
        f = self.fitness(start.date())
        raw = {
            "activityId": self.next_id,
            "activityName": name,
            "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"),
            "startTimeGMT": (start - timedelta(hours=1 if 3 < start.month < 11 else 0)).strftime("%Y-%m-%d %H:%M:%S"),
            "activityType": {"typeId": 1, "typeKey": type_key, "parentTypeId": 17},
            "eventType": {"typeKey": "race" if race else "uncategorized"},
            "distance": round(dist, 1) if dist else None,
            "duration": round(dur + (r.uniform(5, 90) if dist else 0), 1),
            "movingDuration": round(dur, 1),
            "elapsedDuration": round(dur + r.uniform(5, 120), 1),
            "elevationGain": round(gain, 1) if gain is not None else None,
            "elevationLoss": round(loss, 1) if loss is not None else None,
            "averageSpeed": round(dist / dur, 3) if dist and dur else None,
            "maxSpeed": round(max(samples["spd"]), 3) if samples.get("spd") else None,
            "averageHR": round(avg_hr) if avg_hr else None,
            "maxHR": max(hr) if hr else None,
            "calories": round(dur / 60 * (11 if is_run else 5)),
            "averageRunningCadenceInStepsPerMinute": round(sum(cad) / len(cad), 1) if cad and type_key != "road_biking" else None,
            "maxRunningCadenceInStepsPerMinute": max(cad) if cad and type_key != "road_biking" else None,
            "averageBikingCadenceInRevPerMinute": round(sum(cad) / len(cad), 1) if cad and type_key == "road_biking" else None,
            "steps": round(sum(cad) / len(cad) * dur / 60) if cad and type_key != "road_biking" else None,
            "avgStrideLength": round(dist / (sum(cad) / len(cad) * dur / 60) * 100, 1) if cad and dist and type_key != "road_biking" else None,
            "aerobicTrainingEffect": aerobic,
            "anaerobicTrainingEffect": anaerobic,
            "trainingEffectLabel": TE_LABELS.get(kind, "BASE" if hr else None) if kind in TE_LABELS or kind == "ride" else (
                "RECOVERY" if kind == "walk" else None),
            "activityTrainingLoad": load,
            "vO2MaxValue": round(48.0 + 4.0 * f) if is_run and kind in ("tempo", "long", "tt5k", "race") else None,
            "hrTimeInZone_1": round(zones[0]) if hr else None,
            "hrTimeInZone_2": round(zones[1]) if hr else None,
            "hrTimeInZone_3": round(zones[2]) if hr else None,
            "hrTimeInZone_4": round(zones[3]) if hr else None,
            "hrTimeInZone_5": round(zones[4]) if hr else None,
            "startLatitude": samples["lat"][0] if samples.get("lat") else None,
            "startLongitude": samples["lon"][0] if samples.get("lon") else None,
            "locationName": name.split(" ")[0] if samples.get("lat") else None,
            "lapCount": len(laps) or None,
            "minTemperature": min(samples["tmp"]) if samples.get("tmp") else None,
            "maxTemperature": max(samples["tmp"]) if samples.get("tmp") else None,
            "avgGroundContactTime": round(255 - 20 * f + r.uniform(-4, 4), 1) if is_run else None,
            "avgVerticalOscillation": round(8.9 - 0.4 * f + r.uniform(-0.2, 0.2), 1) if is_run else None,
        }
        raw = {k: v for k, v in raw.items() if v is not None}
        self.activities.append({"raw": raw, "samples": samples, "laps": laps, "start": start})

    # ---------- wellness ----------
    def wellness(self, d, f, broke):
        r = self.rng
        ds = d.isoformat()
        rest = 57 - 6 * f + r.gauss(0, 1.3) + (2 if broke else 0)
        steps = int(r.gauss(11500 if d.weekday() < 5 else 9000, 2500))
        stress = max(12, min(70, r.gauss(31 if d.weekday() < 5 else 24, 6)))
        bb_max = max(30, min(100, r.gauss(78 + 8 * f, 9)))
        bb_min = max(5, min(bb_max - 15, r.gauss(22, 7)))
        self.daily.append({
            "calendarDate": ds,
            "movement": {"steps": {"value": max(steps, 1500)}, "distance": {"value": max(steps, 1500) * 0.78}},
            "heartRate": {"restingValue": round(rest), "minValue": round(rest - 4), "maxValue": round(r.uniform(120, 178))},
            "stress": {"avgLevel": round(stress), "maxLevel": round(min(99, stress + r.uniform(30, 55)))},
            "bodyBattery": {"maxValue": round(bb_max), "minValue": round(bb_min),
                            "chargedValue": round(bb_max - bb_min + r.uniform(-5, 5)), "drainedValue": round(bb_max - bb_min + r.uniform(-5, 10))},
            "intensityMinutes": {"moderate": round(max(0, r.gauss(22, 12))), "vigorous": round(max(0, r.gauss(25, 18)))},
            "respiration": {"avgValue": round(r.gauss(14.2, 0.6), 1)},
            "calories": {"total": round(r.gauss(2650, 250)), "active": round(r.gauss(750, 220))},
            "floors": {"ascended": round(max(0, r.gauss(9, 4)))},
        })
        total = max(4.6, min(9.2, r.gauss(7.2 if d.weekday() in (4, 5) else 6.9, 0.55))) * 3600
        deep = total * r.uniform(0.14, 0.22)
        rem = total * r.uniform(0.18, 0.25)
        awake = r.uniform(300, 1800)
        light = total - deep - rem
        bed = datetime.combine(d - timedelta(days=1), time(23, 0)) + timedelta(minutes=r.gauss(15, 25))
        score = max(35, min(97, 40 + (total / 3600 - 5) * 11 + (deep / total - 0.15) * 120 - awake / 200 + r.gauss(0, 4)))
        self.sleep.append({
            "calendarDate": ds, "sleepTimeSeconds": round(total), "deepSleepSeconds": round(deep),
            "lightSleepSeconds": round(light), "remSleepSeconds": round(rem), "awakeSleepSeconds": round(awake),
            "sleepScores": {"overall": {"value": round(score)}},
            "sleepStartTimestampLocal": int(bed.timestamp() * 1000),
            "sleepEndTimestampLocal": int((bed + timedelta(seconds=total + awake)).timestamp() * 1000),
            "averageRespirationValue": round(r.gauss(13.6, 0.5), 1), "averageSpO2Value": round(r.gauss(95, 1.2)),
        })
        if (self.today - d).days < 900:  # HRV only on the newer watch
            base = 46 + 9 * f
            last = r.gauss(base, 5) - (6 if broke else 0)
            self.hrv.append({
                "calendarDate": ds, "lastNightAvg": round(last), "weeklyAvg": round(base + r.gauss(0, 1.5)),
                "status": "BALANCED" if abs(last - base) < 7 else ("UNBALANCED" if last < base else "BALANCED"),
                "baseline": {"balancedLow": round(base - 6), "balancedUpper": round(base + 7)},
            })
        if d.weekday() == 6 and r.random() < 0.8:
            kg = 71.0 - 2.5 * f + r.gauss(0, 0.4)
            self.weight.append({"summaryDate": ds, "latestWeight": {"weight": round(kg * 1000, 1),
                                "bmi": round(kg / 1.80 ** 2, 1), "bodyFat": round(21 - 3 * f + r.gauss(0, 0.5), 1)}})
        if d.weekday() in (1, 4, 6):
            self.vo2.append({"generic": {"calendarDate": ds, "vo2MaxPreciseValue": round(48.0 + 4.0 * f + r.gauss(0, 0.15), 1),
                                         "vo2MaxValue": round(48.0 + 4.0 * f)}, "cycling": None})

    def hr_zones(self):
        return [{"trainingMethod": "HR_MAX", "sport": "DEFAULT", "maxHeartRateUsed": HR_MAX,
                 "restingHeartRateUsed": HR_REST, **{f"zone{i + 1}Floor": z for i, z in enumerate(ZONE_FLOORS)}}]

    def fitness_age(self):
        return {"chronologicalAge": 41, "fitnessAge": 35.8, "achievableFitnessAge": 33.0}


def fake_weather(q, archive=False):
    """Open-Meteo shaped hourly data: mild, breezy, often damp."""
    a, b = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
    variables = q["hourly"].split(",")
    if archive and "visibility" in variables:
        return None
    times, cols = [], {v: [] for v in variables}
    d = a
    while d <= b:
        rnd = random.Random(d.toordinal())
        base_t = 11 + 6 * math.sin((d.timetuple().tm_yday - 110) / 365 * 2 * math.pi)
        wind0, dir0, wet = rnd.uniform(8, 32), rnd.uniform(190, 290), rnd.random() < 0.45
        for h in range(24):
            times.append(f"{d.isoformat()}T{h:02d}:00")
            t = base_t + 4 * math.sin((h - 9) / 24 * 2 * math.pi) + rnd.gauss(0, 0.4)
            rh = min(99, max(55, 85 - 2.5 * (t - base_t) + rnd.gauss(0, 3)))
            dew = t - (100 - rh) / 5
            ws = max(0, wind0 + rnd.gauss(0, 3))
            pr = max(0, rnd.gauss(0.6, 0.6)) if wet and rnd.random() < 0.5 else 0.0
            vals = {"temperature_2m": t, "relative_humidity_2m": rh, "dew_point_2m": dew,
                    "apparent_temperature": t - ws / 8, "precipitation": pr, "rain": pr,
                    "weather_code": (61 if pr > 0.5 else 51) if pr > 0 else rnd.choice([0, 1, 2, 3, 3]),
                    "cloud_cover": 90 if pr else rnd.uniform(10, 95), "pressure_msl": 1012 + 10 * math.sin(d.toordinal() / 5),
                    "surface_pressure": 1000 + 10 * math.sin(d.toordinal() / 5), "wind_speed_10m": ws,
                    "wind_direction_10m": (dir0 + rnd.gauss(0, 10)) % 360, "wind_gusts_10m": ws * 1.6,
                    "visibility": 8000 if pr else rnd.uniform(15000, 40000)}
            for v in variables:
                x = vals.get(v)
                cols[v].append(round(x, 1) if isinstance(x, float) else x)
        d += timedelta(days=1)
    return {"latitude": float(q["latitude"]), "longitude": float(q["longitude"]), "elevation": 90.0,
            "hourly_units": {}, "hourly": {"time": times, **cols}}
