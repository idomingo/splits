"""Fill a database with demo data so you can preview the dashboard.

Use a separate database so demo data never mixes with yours:
    DB_PATH=data/demo.sqlite3 python manage.py seed_demo
(uv run manage.py start --demo does this for you)."""
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from dashboard import ingest
from dashboard.demo import Demo
from dashboard.models import Activity, KeyValue


class Command(BaseCommand):
    help = "Fill the database with demo data (use a separate DB_PATH)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3 * 365)
        parser.add_argument("--force", action="store_true", help="Allow seeding a database that has real data.")

    def handle(self, *args, **opts):
        db_name = str(settings.DATABASES["default"]["NAME"])
        has_real = Activity.objects.exists() and not KeyValue.get("demo")
        if has_real and not opts["force"]:
            self.stderr.write(f"{db_name} already holds your real data. Use DB_PATH=data/demo.sqlite3 for demo data.")
            sys.exit(1)
        self.stdout.write("Generating demo data ...")
        demo = Demo(days=opts["days"]).build()
        with transaction.atomic():
            KeyValue.put("demo", True)
            KeyValue.put("hr_zones", {"floors": [93, 112, 130, 149, 167], "max": 186, "resting": 50,
                                      "method": "HR_MAX", "sport": "DEFAULT"})
            KeyValue.put("hr_zones_raw", demo.hr_zones())
            for raw in demo.daily:
                ingest.upsert_daily(raw)
            for raw in demo.sleep:
                ingest.upsert_sleep(raw)
            for raw in demo.hrv:
                ingest.upsert_hrv(raw)
            for raw in demo.weight:
                ingest.upsert_weight(raw)
        from dashboard.garmin import extract
        from datetime import date
        with transaction.atomic():
            for d, sport, v in extract.vo2_rows(demo.vo2):
                ingest.upsert_vo2(d, sport, v)
            ingest.upsert_fitness_age(date.today(), demo.fitness_age())
        n = len(demo.activities)
        for i, item in enumerate(demo.activities, 1):
            act, _ = ingest.upsert_activity(item["raw"])
            ingest.store_activity_samples(act, {"samples": item["samples"], "laps": item["laps"]}, "demo")
            if i % 50 == 0 or i == n:
                sys.stdout.write(f"\rActivities: {i}/{n}")
                sys.stdout.flush()
        self.stdout.write("\nFinding places, sorting runs and adding made-up weather ...")
        from dashboard.demo import fake_weather
        from dashboard.models import Weather
        from dashboard.runtypes import classify_runs
        from dashboard.weather import HOURLY, activity_coords, activity_window, build, wants_weather
        from dashboard.places import assign_places
        assign_places()
        classify_runs()
        for act in Activity.objects.select_related("stream"):
            if not wants_weather(act):
                continue
            lat, lon = activity_coords(act)
            start, end = activity_window(act)
            data = fake_weather({"start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
                                 "hourly": ",".join(HOURLY),
                                 "latitude": lat, "longitude": lon})
            data["_source"] = "demo"
            Weather.objects.update_or_create(activity=act, defaults=dict(build(act, data), lat=lat, lon=lon))
        self.add_race_and_plan()
        self.stdout.write(self.style.SUCCESS(f"Demo data ready in {db_name}"))

    def add_race_and_plan(self):
        """A half marathon coming up and the plan towards it: four weeks done, three to go."""
        from datetime import date, timedelta
        from dashboard.models import Race
        from dashboard.plan import import_plan
        today = date.today()
        race_day = today + timedelta(days=(6 - today.weekday()) % 7 + 21)
        Race.objects.create(name="Winter Half Marathon", location="Amsterdam", date=race_day, distance_m=21097.5,
                            goal_s=1 * 3600 + 39 * 60)
        week = [(0, "easy", "Easy run", 8, "5:35-5:50", ""), (1, "intervals", "8 x 600 m", 9, "4:10",
                 "2 km warm-up; 8 x 600 m, 300 m jog; cool-down"), (2, "strength", "Strength", None, "", ""),
                (3, "threshold", "Tempo", 11, "4:45", "2 km warm-up; tempo; 1.5 km cool-down"),
                (4, "easy", "Easy run", 7, "5:40", ""), (5, "rest", "Rest", None, "", ""),
                (6, "long", "Long run", 18, "5:40-5:55", "Last 3 km at half marathon pace")]
        rows = ["date,kind,title,distance_km,duration_min,pace,description"]
        start = race_day - timedelta(days=race_day.weekday()) - timedelta(weeks=6)
        for w in range(7):
            for day, kind, title, km, pace, desc in week:
                d = start + timedelta(weeks=w, days=day)
                if d > race_day:
                    continue
                if d == race_day:
                    kind, title, km, pace, desc = "race", "Winter Half Marathon", 21.1, "4:42", ""
                elif w == 6:
                    km = round(km * 0.6, 1) if km else km  # race week: lighter
                rows.append(f'{d},{kind},{title},{km if km else ""},,{pace},"{desc}"')
        import_plan("\n".join(rows), replace_all=True)
