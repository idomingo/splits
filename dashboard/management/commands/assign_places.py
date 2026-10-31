"""Work out the town or city of every activity from its start point (offline).

    python manage.py assign_places          # activities that do not have one yet
    python manage.py assign_places --all    # all of them again
"""
from django.core.management.base import BaseCommand

from dashboard.places import assign_places


class Command(BaseCommand):
    help = "Set the place (town or city) and map route of activities."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Redo every activity, not only new ones.")

    def handle(self, *args, **opts):
        n = assign_places(force=opts["all"], progress=lambda i, total: self.stdout.write(f"\rPlaces: {i}/{total}", ending=""))
        self.stdout.write(self.style.SUCCESS(f"\n{n} activities checked."))
