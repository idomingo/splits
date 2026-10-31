"""Fill a database with demo data so you can preview the dashboard.

Use a separate database so demo data never mixes with yours:
    DB_PATH=data/demo.sqlite3 python manage.py seed_demo
(run.sh demo does this for you)."""
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
        self.stdout.write(self.style.SUCCESS(f"Demo data ready in {db_name}"))
