"""Re-read everything already on disk (raw Garmin JSON and activity files)
without calling Garmin. Used after the app learns new fields."""
from django.conf import settings

from . import fitparse, ingest
from .models import Activity, DailySummary, HrvDay, KeyValue, SleepNight, WeightDay

DATA_VERSION = 2  # bump when extraction or file parsing learns something new


def needs_upgrade():
    return (KeyValue.get("data_version") or 1) < DATA_VERSION


def rebuild_all(progress=None, reparse_files=True):
    acts = list(Activity.objects.all())
    for a in acts:
        ingest.upsert_activity(a.raw)
    for model, fn in ((DailySummary, ingest.upsert_daily), (SleepNight, ingest.upsert_sleep),
                      (HrvDay, ingest.upsert_hrv), (WeightDay, ingest.upsert_weight)):
        for row in model.objects.all().iterator():
            fn(row.raw)
    files = 0
    if reparse_files:
        fit_dir = settings.DATA_DIR / "fit"
        acts = list(Activity.objects.all().order_by("-start_local"))
        for i, act in enumerate(acts, 1):
            for ext in (".zip", ".fit"):
                p = fit_dir / f"{act.activity_id}{ext}"
                if p.exists():
                    fit = fitparse.extract_fit_bytes(p.read_bytes())
                    if fit:
                        steps = 2 if act.category in ("run", "walk") else 1
                        try:
                            ingest.store_activity_samples(act, fitparse.parse_fit(fit, steps), p.name)
                            files += 1
                        except Exception:  # one bad file must not stop the rest
                            pass
                    break
            if progress:
                progress(i, len(acts))
    KeyValue.put("data_version", DATA_VERSION)
    return files
