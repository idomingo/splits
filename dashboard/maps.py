"""Basemap settings for the activity map.

CARTO wants its key on every style, tile, font and sprite request, so the
key travels to the browser too (the page adds it to each CARTO request).
That is normal for map keys; it only ever goes to basemaps.cartocdn.com.
"""
from django.conf import settings

CARTO_VECTOR_DEFAULT = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
CARTO_RASTER_DEFAULT = "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
OSM_RASTER = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
CARTO_ATTRIBUTION = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
                     '&copy; <a href="https://carto.com/attributions">CARTO</a>')
OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

# light style -> matching dark style, when no dark URL is configured
DARK_SWAPS = (("voyager-gl-style", "dark-matter-gl-style"), ("positron-gl-style", "dark-matter-gl-style"))


def _with_key(url, key):
    if not url:
        return ""
    for placeholder in ("{key}", "{api_key}", "YOUR_KEY", "YOUR_API_KEY"):
        url = url.replace(placeholder, key)
    if key and "key=" not in url:
        url += ("&" if "?" in url else "?") + "key=" + key
    return url


def map_config():
    key = settings.CARTO_API_KEY.strip()
    vector = settings.CARTO_VECTOR_STYLE_URL.strip() or (CARTO_VECTOR_DEFAULT if key else "")
    raster = settings.CARTO_RASTER_TILE_URL.strip() or (CARTO_RASTER_DEFAULT if key else "")
    vector = _with_key(vector, key)
    raster = _with_key(raster, key)
    dark = _with_key(settings.CARTO_VECTOR_STYLE_URL_DARK.strip(), key)
    if not dark and vector:
        for light, dark_name in DARK_SWAPS:
            if light in vector:
                dark = vector.replace(light, dark_name)
                break
    return {
        "vector": vector,
        "vector_dark": dark,
        "raster": raster or OSM_RASTER,
        "raster_attribution": CARTO_ATTRIBUTION if raster else OSM_ATTRIBUTION,
        "attribution": CARTO_ATTRIBUTION,
        "key": key,
    }
