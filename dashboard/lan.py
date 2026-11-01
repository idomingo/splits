"""Opening the dashboard from a phone on the same Wi-Fi (`manage.py start --lan`).

The server then listens on the local network as well as on this computer. Anyone on the same network could
reach it, so every device other than this computer needs a private key once: the link the start command
prints has it (?key=...), the phone keeps it in a cookie, and requests without it get a short page saying
so. The key is made once and kept in the data folder, so the phone stays signed in across restarts; delete
data/lan_key.txt to make a new one (and sign every phone out).
"""
import os
import secrets
import socket

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect

COOKIE = "splits_key"
ENV = "SPLITS_LAN_KEY"


def key_file():
    return settings.DATA_DIR / "lan_key.txt"


def enable():
    """Turn on network access for this process (and the dev server's child process). Returns the key."""
    key = os.environ.get(ENV)
    if not key:
        f = key_file()
        if f.exists():
            key = f.read_text().strip()
        if not key:
            key = secrets.token_urlsafe(12)
            f.write_text(key)
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
        os.environ[ENV] = key
    settings.ALLOWED_HOSTS = ["*"]  # the phone uses this computer's network address as the host name
    return key


def local_ip():
    """This computer's address on the local network (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


LOCKED = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Splits</title><body style="font:16px/1.5 system-ui,sans-serif;max-width:32em;margin:3em auto;padding:0 16px;color:#13212e">
<h1 style="font-size:22px">Open the private link</h1>
<p>This dashboard is running on a computer on your network. To open it here, use the link the start command
printed in the terminal on that computer (it ends in <code>?key=...</code>). You only need it once on this device.</p>"""


class LanGuard:
    """Lets this computer in as always; other devices need the key once."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = os.environ.get(ENV)
        if not key:
            return self.get_response(request)
        addr = request.META.get("REMOTE_ADDR", "")
        if addr in ("127.0.0.1", "::1"):
            return self.get_response(request)
        given = request.GET.get("key")
        if given and secrets.compare_digest(given, key):
            # keep it in a cookie and drop it from the address bar
            q = request.GET.copy()
            q.pop("key", None)
            resp = HttpResponseRedirect(request.path + (f"?{q.urlencode()}" if q else ""))
            resp.set_cookie(COOKIE, key, max_age=400 * 86400, httponly=True, samesite="Lax")
            return resp
        if secrets.compare_digest(request.COOKIES.get(COOKIE, ""), key):
            return self.get_response(request)
        return HttpResponse(LOCKED, status=403)
