"""Start the dashboard: first-run setup, then the local web server.

    uv run manage.py start            your data, on http://127.0.0.1:8000
    uv run manage.py start --demo     made-up demo data in a separate database
    uv run manage.py start --port 8080
    uv run manage.py start --lan      also reachable from your phone on the same Wi-Fi (with a private link)

--demo is read in manage.py before settings load, so the demo database is used from the start."""
import os
import re
import shutil
import threading
import webbrowser

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Set up on first run (database, .env) and open the dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Use made-up demo data (data/demo.sqlite3).")
        parser.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000))
        parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
        parser.add_argument("--lan", action="store_true",
                            help="Also listen on your local network, so a phone on the same Wi-Fi can open it.")

    def handle(self, *args, **opts):
        url = f"http://127.0.0.1:{opts['port']}"
        bind = "127.0.0.1"
        if opts["lan"]:
            from dashboard.lan import enable
            key = enable()  # every other device needs the private link once; this computer never does
            bind = "0.0.0.0"
        # the dev server restarts this command in a child process on every code change: set up only once
        if os.environ.get("RUN_MAIN") != "true":
            self.setup(opts["demo"])
            self.stdout.write(f"Dashboard: {url}  (Ctrl+C to stop)")
            if opts["lan"]:
                from dashboard.lan import local_ip
                ip = local_ip()
                if ip:
                    self.stdout.write(f"On your phone (same Wi-Fi): http://{ip}:{opts['port']}/?key={key}")
                    self.stdout.write("Open that link once on the phone; it remembers the key. Keep the link private.")
                else:
                    self.stdout.write("Could not find this computer's address on the network. Check the Wi-Fi connection.")
            if not opts["no_browser"]:
                threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        call_command("runserver", f"{bind}:{opts['port']}")

    def setup(self, demo):
        call_command("migrate", interactive=False, verbosity=0)
        if demo:
            from dashboard.models import Activity
            if not Activity.objects.exists():
                call_command("seed_demo")
            return
        env, example = settings.BASE_DIR / ".env", settings.BASE_DIR / ".env.example"
        if not env.exists() and example.exists():
            shutil.copy(example, env)
            os.chmod(env, 0o600)
            self.stdout.write("Created .env: paste your Garmin key into it (see the README).")
        text = env.read_text(encoding="utf-8") if env.exists() else ""
        has_key = bool(re.search(r"^GARMIN_PERSONAL_API_KEY=\S+", text, re.M))
        self.stdout.write(f"Garmin key: {'set' if has_key else 'NOT set yet (edit .env, then restart)'}")
