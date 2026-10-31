"""Re-read every stored Garmin record and activity file without calling Garmin.
Use after a fix to the field mapping in dashboard/garmin/extract.py."""
import sys

from django.core.management.base import BaseCommand

from dashboard.rebuild import rebuild_all
from dashboard.runtypes import classify_runs


class Command(BaseCommand):
    help = "Rebuild all fields, charts and run types from the raw data already on disk."

    def handle(self, *args, **opts):
        def progress(i, n):
            sys.stdout.write(f"\rActivity files: {i}/{n}")
            sys.stdout.flush()
        files = rebuild_all(progress)
        self.stdout.write(f"\nActivity files re-read: {files}")
        self.stdout.write(f"Run types updated: {classify_runs()}")
