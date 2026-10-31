"""Fetch weather for activities that do not have it yet (also part of every sync)."""
from django.core.management.base import BaseCommand

from dashboard.garmin import sync as S
from dashboard.models import SyncRun, Weather


class Command(BaseCommand):
    help = "Fetch Open-Meteo weather for outdoor activities without it. --all re-fetches everything."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        if opts["all"]:
            Weather.objects.all().delete()
        run = SyncRun.objects.create(mode="weather", phase="Weather")

        class Ctx(S.Context):
            def __init__(self, run, echo):
                self.run, self.echo, self._last_save, self.problems, self.capabilities = run, echo, 0, [], {}

        def echo(text, is_note):
            if is_note:
                self.stdout.write(text)
        S.phase_weather(Ctx(run, echo))
        run.status, run.phase = SyncRun.OK, "Done"
        run.save()
