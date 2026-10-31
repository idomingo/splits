"""Which town or city each activity happened in, worked out offline.

Every activity with GPS gets the place of its start point, looked up in the
GeoNames list of towns with 1,000 people or more (bundled in dashboard/geodata,
CC BY 4.0). Nothing is sent anywhere.

A city counts for its whole area. Each town reaches out a distance that grows
with its population: about 4 km for a town of 8,000, 16 km for a city of a
million, 30 km for New York. When several reach a point, the biggest one wins,
so a run in a suburb counts for the city (a run in Brooklyn counts for New York).
A point that no town reaches gets the nearest town within 100 km.
"""
import gzip
import math
import os
from functools import lru_cache

from django.db import transaction
from django.utils.text import slugify

GEO_VERSION = 2   # raise when places or routes are worked out differently: every activity is redone once
DATA = os.path.join(os.path.dirname(__file__), "geodata")
ROUTE_POINTS = 160
NEAREST_MAX_KM = 100.0
GAP_KM = 1.0


def reach_km(population):
    return max(2.0, min(40.0, 0.26 * max(population, 1000) ** 0.3))


@lru_cache(maxsize=1)
def _grid():
    """Places in 1 x 1 degree cells: {(lat_cell, lon_cell): [(lat, lon, pop, geonameid, name, cc), ...]}."""
    grid = {}
    with gzip.open(os.path.join(DATA, "places.tsv.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            gid, name, lat, lon, cc, pop = line.rstrip("\n").split("\t")
            lat, lon = float(lat), float(lon)
            grid.setdefault((math.floor(lat), math.floor(lon)), []).append((lat, lon, int(pop), int(gid), name, cc))
    return grid


@lru_cache(maxsize=1)
def countries():
    out = {}
    with open(os.path.join(DATA, "countries.tsv"), encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#") and "\t" in line:
                code, name = line.rstrip("\n").split("\t", 1)
                out[code] = name
    return out


def country_name(code):
    return countries().get((code or "").upper(), code or "")


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def locate(lat, lon):
    """The place for a point: dict(geonameid, name, country_code, lat, lon, population, km) or None."""
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    grid = _grid()
    cy, cx = math.floor(lat), math.floor(lon)
    # enough cells to cover 100 km in every direction (longitude cells shrink towards the poles)
    ny = 1
    nx = min(180, int(math.ceil(NEAREST_MAX_KM / max(111.32 * math.cos(math.radians(min(abs(lat), 89))), 1.0))))
    best = nearest = None
    best_pop, near_km = -1, float("inf")
    for dy in range(-ny, ny + 1):
        for dx in range(-nx, nx + 1):
            x = ((cx + dx + 180) % 360) - 180
            for c in grid.get((cy + dy, x), ()):
                d = _km(lat, lon, c[0], c[1])
                if d <= reach_km(c[2]) and c[2] > best_pop:
                    best, best_pop = (c, d), c[2]
                if d < near_km:
                    nearest, near_km = (c, d), d
    hit = best or (nearest if near_km <= NEAREST_MAX_KM else None)
    if not hit:
        return None
    (plat, plon, pop, gid, name, cc), d = hit
    return {"geonameid": gid, "name": name, "country_code": cc, "lat": plat, "lon": plon,
            "population": pop, "km": round(d, 1)}


def simplify_route(data, max_points=ROUTE_POINTS):
    """A light copy of the GPS track for maps that show many activities: [[[lon, lat], ...], ...].

    The track is cut where the signal jumps more than GAP_KM between two recorded
    points (a tunnel, or the watch left running on a train), so maps do not draw a
    straight line across the gap."""
    pts = [(lo, la) for la, lo in zip(data.get("lat") or [], data.get("lon") or []) if la is not None and lo is not None]
    if len(pts) < 2:
        return None
    pieces, cur = [], [pts[0]]
    for a, b in zip(pts, pts[1:]):
        if _km(a[1], a[0], b[1], b[0]) > GAP_KM:
            pieces.append(cur)
            cur = []
        cur.append(b)
    pieces.append(cur)
    pieces = [p for p in pieces if len(p) >= 2]
    if not pieces:
        return None
    step = max(1, len(pts) // max_points)
    out = []
    for piece in pieces:
        thin = piece[::step]
        if thin[-1] != piece[-1]:
            thin.append(piece[-1])
        if len(thin) >= 2:
            out.append([[round(lo, 5), round(la, 5)] for lo, la in thin])
    return out or None


def place_for(info):
    """The Place row for a locate() result, created on first use."""
    from .models import Place
    p = Place.objects.filter(geonameid=info["geonameid"]).first()
    if p:
        return p
    base = slugify(f"{info['name']}-{info['country_code']}") or f"place-{info['geonameid']}"
    slug = base if not Place.objects.filter(slug=base).exists() else f"{base}-{info['geonameid']}"
    return Place.objects.create(geonameid=info["geonameid"], slug=slug, name=info["name"],
                                country_code=info["country_code"], country=country_name(info["country_code"]),
                                lat=info["lat"], lon=info["lon"], population=info["population"])


def assign_places(qs=None, force=False, progress=None):
    """Set place and route on activities that do not have them yet (or all, with force).
    Returns how many activities were looked at."""
    from .models import Activity
    from .weather import activity_coords
    qs = qs if qs is not None else Activity.objects.all()
    if not force:
        qs = qs.filter(geo_version__lt=GEO_VERSION)
    ids = list(qs.values_list("pk", flat=True))
    done = 0
    for i in range(0, len(ids), 200):
        with transaction.atomic():
            for act in Activity.objects.filter(pk__in=ids[i:i + 200]).select_related("stream"):
                stream = _stream(act)
                coords = activity_coords(act)
                info = locate(*coords) if coords else None
                act.place = place_for(info) if info else None
                act.route = simplify_route(stream.data) if stream else None
                act.geo_version = GEO_VERSION
                act.save(update_fields=["place", "route", "geo_version"])
                done += 1
        if progress:
            progress(min(done, len(ids)), len(ids))
    return done


def _stream(act):
    try:
        return act.stream
    except Exception:
        return None


# ---------- areas: a place or a whole country ----------
class Area:
    """What a place filter points at: one town or city, or a country (by its two-letter code)."""

    def __init__(self, slug, name, country="", country_code="", place=None):
        self.slug, self.name, self.country, self.country_code, self.place = slug, name, country, country_code, place

    @property
    def is_country(self):
        return self.place is None

    def q(self, prefix=""):
        from django.db.models import Q
        if self.place is not None:
            return Q(**{f"{prefix}place": self.place})
        return Q(**{f"{prefix}place__country_code": self.country_code})

    def __str__(self):
        return self.name


def resolve_area(slug):
    """'lisbon-pt' -> that place; 'pt' -> Portugal; anything else -> None."""
    from .models import Place
    if not slug:
        return None
    slug = slug.strip().lower()
    if len(slug) == 2 and slug.isalpha():
        cc = slug.upper()
        if not Place.objects.filter(country_code=cc).exists():
            return None
        return Area(slug, country_name(cc), country_name(cc), cc)
    p = Place.objects.filter(slug=slug).first()
    if not p:
        return None
    return Area(p.slug, p.label, p.country, p.country_code, place=p)
