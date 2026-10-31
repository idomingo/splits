"""Check which Garmin endpoints work for your key.

Prints status codes, sizes and field NAMES only: never the key, the token or
any of your values, so the output is safe to share when something needs fixing.
"""
import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from dashboard import fitparse
from dashboard.garmin import sync as S
from dashboard.garmin.client import GarminAuthError, GarminClient, GarminError, GarminNotAvailable, GarminTooLarge


def shape(obj, depth=0):
    if isinstance(obj, list):
        inner = shape(obj[0], depth + 1) if obj else "empty"
        return f"list[{len(obj)}] of {inner}"
    if isinstance(obj, dict):
        keys = sorted(obj.keys())
        if depth >= 1:
            return "{" + ", ".join(keys[:60]) + (", ..." if len(keys) > 60 else "") + "}"
        parts = []
        for k in keys[:40]:
            v = obj[k]
            if isinstance(v, (dict, list)):
                parts.append(f"{k}: {shape(v, depth + 1)}")
            else:
                parts.append(k)
        return "{" + ", ".join(parts) + "}"
    return type(obj).__name__


class Command(BaseCommand):
    help = "Test the Garmin key and every endpoint the app uses (safe to share the output)."

    def handle(self, *args, **opts):
        c = GarminClient()
        out = self.stdout.write
        out(f"Key in .env: {'set' if c.key_is_set() else 'NOT SET'}")
        if not c.key_is_set():
            return
        try:
            c.token(force=True)
            out(self.style.SUCCESS("Token: OK"))
        except GarminAuthError as exc:
            out(self.style.ERROR(f"Token: FAILED - {exc}"))
            return
        except GarminError as exc:
            out(self.style.ERROR(f"Token: FAILED - {exc}"))
            return

        today = date.today()
        week = today - timedelta(days=6)
        month = today - timedelta(days=29)
        checks = [
            ("Activity list", S.ACTIVITY_LIST, {"start": 0, "limit": 2}),
            ("Daily summaries (7 days)", S.DAILY, {"startDate": week.isoformat(), "endDate": today.isoformat()}),
            ("Sleep (7 days)", S.SLEEP, {"startDate": week.isoformat(), "endDate": today.isoformat()}),
            ("HRV (7 days)", S.HRV.format(a=week.isoformat(), b=today.isoformat()), None),
            ("Weight (30 days)", S.WEIGHT.format(a=month.isoformat(), b=today.isoformat()), None),
            ("VO2max (30 days)", S.VO2.format(a=month.isoformat(), b=today.isoformat()), None),
            ("Fitness age", S.FITNESS_AGE.format(d=today.isoformat()), None),
            ("Heart rate zones", S.HR_ZONES, None),
        ]
        first_activity_id = None
        for label, path, params in checks:
            try:
                data = c.get_json(path, params)
                size = len(json.dumps(data)) if data is not None else 0
                out(self.style.SUCCESS(f"\n[OK] {label}") + f"  ({size} bytes)")
                out("     " + shape(data))
                if label == "Activity list":
                    items = data if isinstance(data, list) else (data or {}).get("activities") or []
                    if items:
                        first_activity_id = items[0].get("activityId")
            except GarminNotAvailable:
                out(self.style.WARNING(f"\n[404] {label}: not available"))
            except GarminTooLarge as exc:
                out(self.style.WARNING(f"\n[TOO LARGE] {label}: {exc}"))
            except GarminError as exc:
                out(self.style.ERROR(f"\n[ERROR] {label}: {exc}"))

        if first_activity_id:
            label = "Activity file (latest activity)"
            try:
                blob = c.get_bytes(S.ACTIVITY_FILE.format(id=first_activity_id))
                kind = "zip" if blob[:2] == b"PK" else ("fit" if blob[8:12] == b".FIT" else "unknown")
                out(self.style.SUCCESS(f"\n[OK] {label}") + f"  ({len(blob)} bytes, {kind})")
                fit = fitparse.extract_fit_bytes(blob)
                if fit:
                    parsed = fitparse.parse_fit(fit)
                    samples = parsed["samples"]
                    out(f"     samples: {len(samples.get('t', []))}, channels: {', '.join(k for k in samples if k != 't')}")
                    out(f"     laps: {len(parsed['laps'])}")
                else:
                    out(self.style.WARNING("     no FIT recording inside"))
            except GarminNotAvailable:
                out(self.style.WARNING(f"\n[404] {label}: not available"))
            except GarminError as exc:
                out(self.style.ERROR(f"\n[ERROR] {label}: {exc}"))
        out(f"\nCalls made: {c.calls}")
