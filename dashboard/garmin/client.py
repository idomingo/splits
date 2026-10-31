"""Garmin Connect Personal API client (read-only).

Auth: the personal API key is exchanged for an access token (valid 24 h, no
refresh). The token is cached in data/token.json and renewed after 20 h.
The key and the token are never printed or logged.
"""
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from django.conf import settings

log = logging.getLogger("dashboard.garmin")

TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
TOKEN_MAX_AGE = 20 * 3600


class GarminError(Exception):
    pass


class GarminAuthError(GarminError):
    """Key missing, wrong or expired."""


class GarminNotAvailable(GarminError):
    """404: this endpoint is not part of the Personal API (or no data)."""


class GarminTooLarge(GarminError):
    """Response over Garmin's size limit (500 with empty body) or range too long (400)."""


class GarminClient:
    def __init__(self, api_key=None, base_url=None, token_file=None, pause=None, timeout=60):
        self.api_key = (api_key if api_key is not None else settings.GARMIN_PERSONAL_API_KEY or "").strip()
        self.base = (base_url or settings.GARMIN_API_BASE).rstrip("/")
        self.token_file = Path(token_file or (settings.DATA_DIR / "token.json"))
        self.pause = settings.GARMIN_PAUSE_SECONDS if pause is None else pause
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "splits-dashboard/1.0 (personal use)"
        self._token = None
        self._last_call = 0.0
        self.calls = 0

    # ---------- token ----------
    def key_is_set(self):
        return bool(self.api_key)

    def _read_cached_token(self):
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("base") != self.base:
            return None
        if time.time() - float(data.get("obtained_at", 0)) > TOKEN_MAX_AGE:
            return None
        return data.get("token") or None

    def _save_token(self, token):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({"token": token, "obtained_at": time.time(), "base": self.base}), encoding="utf-8")
        try:
            self.token_file.chmod(0o600)
        except OSError:
            pass

    def forget_token(self):
        self._token = None
        try:
            self.token_file.unlink()
        except OSError:
            pass

    def token(self, force=False):
        if not self.api_key:
            raise GarminAuthError("No Garmin key found. Put GARMIN_PERSONAL_API_KEY=... in the .env file.")
        if self._token and not force:
            return self._token
        if not force:
            cached = self._read_cached_token()
            if cached:
                self._token = cached
                return cached
        self._throttle()
        try:
            r = self.session.post(self.base + TOKEN_PATH, headers={"Authorization": f"ApiKey {self.api_key}"}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GarminError(f"Could not reach Garmin for a token: {exc.__class__.__name__}") from None
        self.calls += 1
        if r.status_code in (400, 401, 403):
            raise GarminAuthError(f"Garmin rejected the key (HTTP {r.status_code}). Check it in .env, or create a new key if it expired.")
        if r.status_code >= 300:
            raise GarminError(f"Token request failed with HTTP {r.status_code}.")
        token = self._parse_token(r)
        if not token:
            raise GarminError("Token response was empty.")
        self._token = token
        self._save_token(token)
        return token

    @staticmethod
    def _parse_token(r):
        text = (r.text or "").strip()
        if text.startswith("{"):
            try:
                data = r.json()
            except ValueError:
                data = {}
            for k in ("access_token", "accessToken", "token", "personalApiToken"):
                if data.get(k):
                    return str(data[k]).strip()
            return None
        return text.strip('"')

    # ---------- requests ----------
    def _throttle(self):
        wait = self.pause - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _get(self, path, params=None, accept="application/json"):
        url = self.base + path
        refreshed = False
        attempt = 0
        while True:
            attempt += 1
            token = self.token()
            self._throttle()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout,
                                     headers={"Authorization": f"Bearer {token}", "Accept": accept})
            except requests.RequestException as exc:
                if attempt <= 3:
                    time.sleep(2 * attempt)
                    continue
                raise GarminError(f"Network error on {path}: {exc.__class__.__name__}") from None
            self.calls += 1
            sc = r.status_code
            if sc == 401 and not refreshed:
                refreshed = True
                self.forget_token()
                self.token(force=True)
                continue
            if sc in (401, 403):
                raise GarminAuthError(f"Garmin refused {path} (HTTP {sc}).")
            if sc == 404:
                raise GarminNotAvailable(f"{path} returned 404")
            if sc in (429, 502, 503, 504) and attempt <= 5:
                retry_after = r.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 3 * attempt)
                log.info("Garmin %s on %s, waiting %.0fs", sc, path, delay)
                time.sleep(delay)
                continue
            if sc == 500 and not r.content:
                raise GarminTooLarge(f"{path} too large (500, empty body)")
            if sc == 400:
                raise GarminTooLarge(f"{path} rejected the range (400)")
            if sc >= 500 and attempt <= 3:
                time.sleep(3 * attempt)
                continue
            if sc >= 300:
                raise GarminError(f"{path} failed with HTTP {sc}")
            return r

    def get_json(self, path, params=None):
        r = self._get(path, params)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            raise GarminError(f"{path} did not return JSON") from None

    def get_bytes(self, path, params=None):
        return self._get(path, params, accept="*/*").content

    # ---------- date ranges ----------
    def fetch_range(self, start: date, end: date, chunk_days: int, fetch):
        """Call fetch(a, b) over [start, end] in chunks, newest chunk last.
        When Garmin says a chunk is too big, split it in half and retry.
        Yields (a, b, payload)."""
        cur = start
        while cur <= end:
            b = min(end, cur + timedelta(days=chunk_days - 1))
            yield from self._fetch_window(cur, b, fetch)
            cur = b + timedelta(days=1)

    def _fetch_window(self, a, b, fetch):
        try:
            yield a, b, fetch(a, b)
        except GarminTooLarge:
            if a == b:
                log.warning("Skipping %s: too large even for one day", a)
                return
            mid = a + (b - a) // 2
            yield from self._fetch_window(a, mid, fetch)
            yield from self._fetch_window(mid + timedelta(days=1), b, fetch)
