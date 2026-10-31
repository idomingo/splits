from datetime import date, datetime

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..sports import BEST_EFFORT_LABELS, CATEGORY_LABEL, pretty_type

register = template.Library()


@register.filter
def km(m, digits=2):
    if m is None:
        return "-"
    return f"{m / 1000:.{int(digits)}f}"


@register.filter
def kmv(value, digits=1):
    """Already in km."""
    if value is None:
        return "-"
    return f"{value:,.{int(digits)}f}"


@register.filter
def dur(s):
    """1:02:03 or 48:31"""
    if not s:
        return "-"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


@register.filter
def hm(s):
    """5 h 12 min"""
    if not s:
        return "0 min"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m = rem // 60
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min"


@register.filter
def hours(h, digits=0):
    if h is None:
        return "-"
    return f"{h:,.{int(digits)}f}"


@register.filter
def pace(s_per_km):
    if not s_per_km:
        return "-"
    s = int(round(s_per_km))
    return f"{s // 60}:{s % 60:02d}"


@register.filter
def speed(kmh):
    if not kmh:
        return "-"
    return f"{kmh:.1f}"


@register.filter
def dur_hours(h):
    """7.25 -> 7 h 15 min"""
    if not h:
        return "-"
    return hm(h * 3600)


@register.filter
def signed_hm(h):
    if h is None:
        return ""
    mins = round(h * 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"{sign}{mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"{sign}{mins} min"


@register.filter
def uses_pace(category):
    from ..sports import PACE_CATEGORIES
    return category in PACE_CATEGORIES


@register.filter
def num(v, digits=0):
    if v is None or v == "":
        return "-"
    try:
        return f"{float(v):,.{int(digits)}f}"
    except (TypeError, ValueError):
        return v


@register.filter
def signed(v, digits=0):
    if v is None:
        return ""
    return f"{v:+,.{int(digits)}f}"


@register.filter
def catlabel(c):
    return CATEGORY_LABEL.get(c, "Other")


@register.filter
def typelabel(t):
    return pretty_type(t)


TE_NAMES = {
    "RECOVERY": "Recovery", "BASE": "Base", "TEMPO": "Tempo", "THRESHOLD": "Threshold",
    "VO2MAX": "VO2 max", "ANAEROBIC_CAPACITY": "Anaerobic", "SPRINT": "Sprint",
    "LACTATE_THRESHOLD": "Threshold", "AEROBIC_BASE": "Base", "NO_BENEFIT": "", "UNKNOWN": "",
}


@register.filter
def telabel(v):
    if not v:
        return ""
    return TE_NAMES.get(str(v).upper(), str(v).replace("_", " ").capitalize())


@register.filter
def effortlabel(d):
    return BEST_EFFORT_LABELS.get(int(d), f"{d} m")


@register.filter
def ago(dt):
    if not dt:
        return "never"
    now = timezone.now()
    secs = (now - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    days = int(secs // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


@register.filter
def nicedate(d):
    if not d:
        return ""
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    if isinstance(d, datetime):
        d = d.date()
    today = date.today()
    if d == today:
        return "Today"
    if (today - d).days == 1:
        return "Yesterday"
    if d.year == today.year:
        return d.strftime("%a %-d %b")
    return d.strftime("%-d %b %Y")


@register.filter
def pct(part, whole):
    try:
        return 100.0 * float(part) / float(whole) if whole else 0
    except (TypeError, ValueError):
        return 0


@register.simple_tag
def zone_ribbon(zones, size="sm"):
    """Horizontal bar split by time in HR zones 1-5."""
    if not zones or not any(zones):
        return format_html('<div class="ribbon ribbon-{} ribbon-empty" aria-hidden="true"></div>', size)
    total = sum(z or 0 for z in zones)
    parts = []
    label = []
    for i, z in enumerate(zones):
        if not z:
            continue
        p = 100.0 * z / total
        label.append(f"zone {i + 1} {round(p)}%")
        parts.append(f'<span class="z{i + 1}" style="flex-grow:{p:.2f}"></span>')
    return mark_safe(f'<div class="ribbon ribbon-{size}" role="img" aria-label="Heart rate: {", ".join(label)}">{"".join(parts)}</div>')


@register.simple_tag
def sport_icon(cat, cls="icon"):
    return mark_safe(f'<svg class="{cls}" aria-hidden="true"><use href="#i-{cat}"></use></svg>')


@register.filter
def get(d, key):
    if isinstance(d, dict):
        return d.get(key)
    return None


@register.filter
def get_index(seq, i):
    try:
        return seq[int(i)]
    except (IndexError, TypeError, ValueError, KeyError):
        return None


@register.filter
def mul36(v):
    """m/s -> km/h"""
    return v * 3.6 if v else None


@register.filter
def per_km(secs, dist_m):
    try:
        return secs / (float(dist_m) / 1000.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


@register.filter
def kmh(dist_m, secs):
    try:
        return (float(dist_m) / 1000.0) / (float(secs) / 3600.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


@register.filter
def ordinal_suffix(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


@register.filter
def div(v, by):
    try:
        return float(v) / float(by)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


@register.filter
def kindgroup(kind):
    from ..runtypes import GROUP_OF
    return GROUP_OF.get(kind, "easy")


@register.filter
def wmo(code):
    from ..weather import describe
    return describe(code)


@register.filter
def compass(deg):
    from ..weather import compass as c
    return c(deg)


@register.filter
def vis_km(m):
    if m is None:
        return "-"
    return f"{m / 1000:.0f}" if m >= 10000 else f"{m / 1000:.1f}"


@register.filter
def neg(v):
    return -v if v is not None else None


@register.filter
def mul100(v):
    return v * 100 if v is not None else None
