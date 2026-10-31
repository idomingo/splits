"""Sport categories. The order here is the fixed colour order (CSS --c-<key>)."""

CATEGORIES = [
    # key, label, Garmin typeKey fragments that map here
    ("run", "Running", ("run", "track", "treadmill")),
    ("walk", "Walking", ("walk", "hik", "mountaineering")),
    ("cycle", "Cycling", ("cycl", "bik", "ride", "gravel")),
    ("swim", "Swimming", ("swim",)),
    ("strength", "Strength", ("strength", "hiit", "yoga", "pilates", "cardio", "fitness_equipment", "indoor_rowing", "elliptical", "stair")),
    ("other", "Other", ()),
]

CATEGORY_CHOICES = [(k, label) for k, label, _ in CATEGORIES]
CATEGORY_LABEL = {k: label for k, label, _ in CATEGORIES}
CATEGORY_KEYS = [k for k, _, _ in CATEGORIES]

# URL slugs for sport pages
SLUG_TO_CATEGORY = {
    "running": "run", "walking": "walk", "cycling": "cycle",
    "swimming": "swim", "strength": "strength", "other": "other",
}
CATEGORY_TO_SLUG = {v: k for k, v in SLUG_TO_CATEGORY.items()}

# Distances (metres) for best efforts, per category
BEST_EFFORT_DISTANCES = {
    "run": [400, 1000, 1609, 3000, 5000, 10000, 15000, 21097, 42195],
    "walk": [1000, 5000, 10000, 21097],
    "cycle": [5000, 10000, 20000, 40000, 50000, 100000],
}

BEST_EFFORT_LABELS = {
    400: "400 m", 1000: "1 km", 1609: "1 mile", 3000: "3 km", 5000: "5 km",
    10000: "10 km", 15000: "15 km", 20000: "20 km", 21097: "Half marathon",
    40000: "40 km", 42195: "Marathon", 50000: "50 km", 100000: "100 km",
}

# Fastest plausible average speed (m/s) per category; faster GPS segments are noise.
MAX_PLAUSIBLE_SPEED = {"run": 8.0, "walk": 4.0, "cycle": 25.0}

# Categories where pace (min/km) reads better than speed (km/h)
PACE_CATEGORIES = {"run", "walk"}


def categorize(type_key: str) -> str:
    t = (type_key or "").lower()
    if t in ("multi_sport", "triathlon"):
        return "other"
    for key, _label, fragments in CATEGORIES:
        if any(f in t for f in fragments):
            return key
    return "other"


def pretty_type(type_key: str) -> str:
    return (type_key or "activity").replace("_", " ").capitalize()
