import sys

from django.core.management.base import BaseCommand

from dashboard.garmin.sync import current_run, run_sync
from dashboard.models import SyncRun


class Command(BaseCommand):
    help = "Fetch new data from Garmin (the first run fetches your full history)."

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Re-read the full history, not only what is new.")
        parser.add_argument("--recheck", action="store_true",
                            help="Retry endpoints that were marked as not available.")

    def handle(self, *args, **opts):
        if current_run():
            self.stderr.write("A sync is already running (started from the page). Wait for it to finish.")
            sys.exit(1)
        last = {"line": ""}

        def echo(text, is_note):
            # one updating line for progress, new lines for notes
            if not is_note:
                sys.stdout.write("\r" + text[:110].ljust(110))
                sys.stdout.flush()
                last["line"] = text
            else:
                sys.stdout.write("\r" + " " * 110 + "\r" + text + "\n")
                sys.stdout.flush()

        run = run_sync(full=opts["full"], recheck=opts["recheck"], echo=echo)
        sys.stdout.write("\n")
        if run.status == SyncRun.FAILED:
            self.stderr.write(self.style.ERROR(f"Sync failed: {run.error}"))
            sys.exit(1)
        style = self.style.SUCCESS if run.status == SyncRun.OK else self.style.WARNING
        self.stdout.write(style(f"Sync finished: {run.message}"))
