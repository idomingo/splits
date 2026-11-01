import os
import sys
import warnings

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"

    def ready(self):
        # The dev server reloads itself when the code changes (new files from an update), but `start` only
        # migrates once at start. Apply any new migrations in the serving process so a reload never meets
        # an old database.
        if "runserver" not in sys.argv and "start" not in sys.argv:
            return
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
            return
        try:
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                executor = MigrationExecutor(connection)
                plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
                if plan:
                    from django.core.management import call_command
                    print(f"Updating the database ({len(plan)} change{'s' if len(plan) != 1 else ''})", flush=True)
                    call_command("migrate", interactive=False, verbosity=0)
        except Exception as exc:  # never block the server from starting
            print(f"Could not update the database automatically: {exc}. Run: python manage.py migrate", flush=True)
