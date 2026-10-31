"""Settings for the Splits training dashboard (local, single user)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE per line, existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_env_file(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "fit").mkdir(exist_ok=True)


def _secret_key() -> str:
    if os.environ.get("DJANGO_SECRET_KEY"):
        return os.environ["DJANGO_SECRET_KEY"]
    path = DATA_DIR / "secret_key.txt"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"] + [
    h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "dashboard.middleware.FillMissing",
]

# Map tile servers (OpenStreetMap, and CARTO keys with domain restrictions) need a Referer.
# Django's default ("same-origin") sends none to other sites, so send just the origin.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "dashboard.context.nav",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DB_PATH", str(DATA_DIR / "garmin.sqlite3")),
        "OPTIONS": {
            # WAL lets the page read while a background sync writes.
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 30,
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en"
def _system_time_zone():
    """The computer's own time zone (macOS and Linux keep it as a link to the zoneinfo file)."""
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


TIME_ZONE = os.environ.get("TIME_ZONE") or _system_time_zone()
USE_I18N = False
USE_TZ = False  # Garmin gives local start times; we store them as local wall time.

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Garmin Personal API
GARMIN_PERSONAL_API_KEY = os.environ.get("GARMIN_PERSONAL_API_KEY", "")
GARMIN_API_BASE = os.environ.get("GARMIN_API_BASE", "https://personal.connectapi.garmin.com")
GARMIN_PAUSE_SECONDS = float(os.environ.get("GARMIN_PAUSE_SECONDS", "0.4"))
APP_NAME = os.environ.get("APP_NAME", "Splits")

# Maps. CARTO basemaps need a free key (https://carto.com/basemaps/apikey/).
# Without one, the activity map falls back to OpenStreetMap's own raster tiles.
CARTO_API_KEY = os.environ.get("CARTO_API_KEY", "")
CARTO_VECTOR_STYLE_URL = os.environ.get("CARTO_VECTOR_STYLE_URL", "")
CARTO_VECTOR_STYLE_URL_DARK = os.environ.get("CARTO_VECTOR_STYLE_URL_DARK", "")
CARTO_RASTER_TILE_URL = os.environ.get("CARTO_RASTER_TILE_URL", "")

# Weather (Open-Meteo, free, no key). Override only for testing.
WEATHER_FORECAST_URL = os.environ.get("WEATHER_FORECAST_URL", "")
WEATHER_ARCHIVE_URL = os.environ.get("WEATHER_ARCHIVE_URL", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"dashboard": {"handlers": ["console"], "level": "INFO"}},
}
