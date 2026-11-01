"""Training plan: imported from a CSV file, then compared day by day with what you actually did.

The file has one row per session:

    date,kind,title,distance_km,duration_min,pace,description
    2026-11-03,easy,Easy run,8,,6:10-6:30,Relaxed. Strides at the end.
    2026-11-05,threshold,3 x 10 min,10,,5:05,2 km warm-up; 3 x 10 min at threshold, 2 min jog; cool-down

Only date and kind are needed. Importing a file replaces the sessions between its first and last date
(or the whole plan, when asked), so a revised plan can be imported again.
"""
import csv
import io
from datetime import date, timedelta

KINDS = {
    "easy": "Easy", "long": "Long run", "threshold": "Threshold", "tempo": "Threshold", "intervals": "Intervals",
    "progression": "Progression", "steady": "Steady", "recovery": "Recovery", "race": "Race", "strides": "Strides",
    "rest": "Rest", "strength": "Strength", "cross": "Cross-training",
}
RUN_KINDS = {"easy", "long", "threshold", "intervals", "progression", "steady", "recovery", "race", "strides"}
COLUMNS = ["date", "kind", "title", "distance_km", "duration_min", "pace", "description"]

TEMPLATE = """date,kind,title,distance_km,duration_min,pace,description
2026-11-02,easy,Easy run,8,,6:10-6:30,Relaxed. 6 x 20 s strides at the end.
2026-11-03,rest,Rest,,,,
2026-11-04,threshold,3 x 10 min threshold,10,,5:05,2 km warm-up; 3 x 10 min at threshold with 2 min jog; 2 km cool-down
2026-11-05,strength,Strength and mobility,,30,,
2026-11-06,easy,Easy run,6,,6:15-6:35,
2026-11-07,rest,Rest,,,,
2026-11-08,long,Long run,18,,6:20-6:40,Last 3 km at half marathon pace
"""

AI_PROMPT = """Write my training plan as a CSV file I can import into my training dashboard. Use exactly these columns, in this order, with a header row:

date,kind,title,distance_km,duration_min,pace,description

Rules:
- One row per session, one session per day where possible (two rows on the same date are fine for a double).
- date: YYYY-MM-DD.
- kind: one of easy, long, threshold, intervals, progression, steady, recovery, race, strides, rest, strength, cross.
- title: a short name, for example "Long run" or "6 x 800 m".
- distance_km: total kilometres for the session as a number with a dot for decimals (for example 10.5), warm-up and cool-down included. Leave empty for rest, strength and cross.
- duration_min: minutes, only for sessions planned by time instead of distance.
- pace: target pace per km as text, for example 5:05 or 6:10-6:30. Leave empty if there is none.
- description: the details (warm-up, repeats, recoveries). If it contains a comma, put the whole description in double quotes.
- Include rest days as rows with kind rest.
- No other text before or after the CSV."""


def _num(text):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return "bad"


def parse(raw):
    """(sessions, errors). sessions: list of dicts ready for PlanSession; errors: 'line 4: ...' strings."""
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    text = text.strip().strip("`")
    if text.lower().startswith("csv\n"):  # pasted from a code block
        text = text[4:]
    try:
        dialect = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return [], ["The file is empty."]
    head = [h.strip().lower().replace(" ", "_") for h in rows[0]]
    if "date" not in head or "kind" not in head:
        return [], ["The first row must name the columns, with at least date and kind: " + ",".join(COLUMNS)]
    col = {name: head.index(name) for name in COLUMNS if name in head}
    out, errors = [], []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        get = lambda name: row[col[name]].strip() if name in col and col[name] < len(row) else ""
        try:
            d = date.fromisoformat(get("date"))
        except ValueError:
            errors.append(f"line {n}: the date '{get('date')}' is not YYYY-MM-DD")
            continue
        kind = get("kind").lower()
        if kind not in KINDS:
            errors.append(f"line {n}: the kind '{kind}' is not one of {', '.join(sorted(KINDS))}")
            continue
        dist, dur = _num(get("distance_km")), _num(get("duration_min"))
        if dist == "bad" or dur == "bad":
            errors.append(f"line {n}: distance_km and duration_min must be numbers")
            continue
        out.append({"date": d, "kind": "threshold" if kind == "tempo" else kind, "title": get("title")[:200],
                    "distance_km": dist, "duration_min": dur, "pace": get("pace")[:60],
                    "description": get("description")})
    if not out and not errors:
        errors.append("No sessions found under the header row.")
    return out, errors


def import_plan(raw, replace_all=False):
    """Replace the plan for the dates in the file (or all of it). Returns (count, errors); nothing is changed
    when there are errors."""
    from django.db import transaction
    from .models import PlanSession
    sessions, errors = parse(raw)
    if errors:
        return 0, errors
    first, last = min(s["date"] for s in sessions), max(s["date"] for s in sessions)
    with transaction.atomic():
        old = PlanSession.objects.all() if replace_all else PlanSession.objects.filter(date__gte=first, date__lte=last)
        old.delete()
        PlanSession.objects.bulk_create([PlanSession(**s) for s in sessions])
    return len(sessions), []


def label(kind):
    return KINDS.get(kind, kind.capitalize())


def status(session, done, today=None):
    """How a planned session went. done: activities of that day (dicts with category, km, kind, id).

    'done' (distance within 20% or no distance planned), 'short', 'long', 'missed', 'extra' (ran on a rest day),
    'rest' (rested as planned), 'today' or 'planned' (still to come)."""
    today = today or date.today()
    runs = [a for a in done if a["category"] == "run"]
    if session.kind == "rest":
        if session.date > today:
            return "planned"
        return "extra" if runs else "rest"
    if session.kind in ("strength", "cross"):
        other = [a for a in done if a["category"] != "run"]
        if other:
            return "done"
        return "planned" if session.date > today else ("today" if session.date == today else "missed")
    if not runs:
        return "planned" if session.date > today else ("today" if session.date == today else "missed")
    km = sum(a["km"] for a in runs)
    if session.distance_km:
        ratio = km / session.distance_km
        if ratio < 0.8:
            return "short"
        if ratio > 1.2:
            return "long"
    return "done"


STATUS_LABEL = {"done": "Done", "short": "Shorter", "long": "Longer", "missed": "Missed", "extra": "Ran on a rest day",
                "rest": "Rested", "today": "Today", "planned": "Planned"}


def by_day(first, last):
    """{date: [PlanSession, ...]} between two dates."""
    from .models import PlanSession
    out = {}
    for s in PlanSession.objects.filter(date__gte=first, date__lte=last):
        out.setdefault(s.date, []).append(s)
    return out


def overview(today=None):
    """What the plan page shows: the next two weeks, and how the last four went."""
    from .models import Activity, PlanSession
    today = today or date.today()
    if not PlanSession.objects.exists():
        return {"empty": True}
    first = PlanSession.objects.order_by("date").first().date
    last = PlanSession.objects.order_by("-date").first().date
    lo = max(first, today - timedelta(days=28))
    hi = min(last, today + timedelta(days=14))
    acts = {}
    for a in Activity.objects.filter(start_local__date__gte=lo, start_local__date__lte=hi, session_of=None):
        km = a.distance_km + sum(x.distance_km for x in a.session_extras.all())
        acts.setdefault(a.start_local.date(), []).append(
            {"category": a.category, "km": km, "kind": a.kind, "id": a.pk, "title": a.title})
    days = []
    plan = by_day(lo, hi)
    d = lo
    while d <= hi:
        for s in plan.get(d, []):
            st = status(s, acts.get(d, []), today)
            run_day = s.kind in RUN_KINDS or s.kind == "rest"
            shown = [a for a in acts.get(d, []) if (a["category"] == "run") == run_day]
            days.append({"s": s, "label": label(s.kind), "status": st, "status_label": STATUS_LABEL[st],
                         "done": shown, "past": d < today, "today": d == today})
        d += timedelta(days=1)
    past = [x for x in days if x["past"] and x["s"].kind != "rest"]
    hit = sum(1 for x in past if x["status"] == "done")
    planned_km = sum(x["s"].distance_km or 0 for x in past)
    done_km = sum(sum(a["km"] for a in x["done"] if a["category"] == "run") for x in past)
    return {"empty": False, "first": first, "last": last, "days": days, "count": PlanSession.objects.count(),
            "past_n": len(past), "past_done": hit, "planned_km": planned_km, "done_km": done_km}
