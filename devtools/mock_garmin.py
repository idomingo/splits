"""A fake Garmin Personal API for testing the sync without a real key.

    pip install fit-tool        (dev only)
    python devtools/mock_garmin.py --port 8765 --days 200
    GARMIN_API_BASE=http://127.0.0.1:8765 GARMIN_PERSONAL_API_KEY=test-key \\
        DB_PATH=data/mock.sqlite3 python manage.py sync_garmin

It mimics the limits seen on the real API: 500 with an empty body when a page
is too large, 400 on ranges that are too long, an occasional 429, and 404 on
endpoints that are not part of the Personal API.
"""
import argparse
import io
import json
import os
import sys
import threading
import zipfile
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dashboard.demo import Demo, fake_weather  # noqa: E402

API_KEY = "test-key"
STATE = {"token_requests": 0, "requests": 0, "hidden": 0, "fit_cache": {}}
LOCK = threading.Lock()


def build_fit(item):
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.profile_type import FileType, Manufacturer

    start = item["start"]
    gmt = datetime.strptime(item["raw"]["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    t0 = int(gmt.timestamp() * 1000)
    s = item["samples"]
    run_like = item["raw"]["activityType"]["typeKey"] in ("running", "walking", "hiking")
    b = FitFileBuilder(auto_define=True, min_string_size=50)
    m = FileIdMessage()
    m.type = FileType.ACTIVITY
    m.manufacturer = Manufacturer.GARMIN.value
    m.product = 0
    m.time_created = t0
    m.serial_number = 0x1234
    b.add(m)
    recs = []
    for i, t in enumerate(s["t"]):
        r = RecordMessage()
        r.timestamp = t0 + int(t * 1000)
        if s.get("lat"):
            r.position_lat = s["lat"][i]
            r.position_long = s["lon"][i]
        if s.get("d"):
            r.distance = s["d"][i]
        if s.get("spd"):
            r.enhanced_speed = s["spd"][i]
        if s.get("hr"):
            r.heart_rate = int(s["hr"][i])
        if s.get("cad"):
            c = s["cad"][i] / 2 if run_like else s["cad"][i]
            r.cadence = int(c)
        if s.get("alt"):
            r.enhanced_altitude = s["alt"][i]
        if s.get("tmp"):
            r.temperature = int(s["tmp"][i])
        recs.append(r)
    b.add_all(recs)
    for i, lap in enumerate(item["laps"]):
        if not lap:
            continue
        lm = LapMessage()
        lm.message_index = i
        lm.start_time = t0 + int((lap["start_offset_s"] or 0) * 1000)
        lm.timestamp = lm.start_time + int((lap["duration_s"] or 0) * 1000)
        lm.total_timer_time = lap["duration_s"]
        lm.total_elapsed_time = lap["duration_s"]
        lm.total_distance = lap["distance_m"]
        if lap.get("avg_speed"):
            lm.enhanced_avg_speed = lap["avg_speed"]
        lm.avg_heart_rate = int(lap["avg_hr"])
        lm.max_heart_rate = int(lap["max_hr"])
        lm.total_ascent = int(lap["elev_gain_m"])
        lm.total_descent = int(lap["elev_loss_m"])
        if lap.get("avg_cadence"):
            lm.avg_cadence = int(lap["avg_cadence"] / 2 if run_like else lap["avg_cadence"])
        b.add(lm)
    fit = b.build().to_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{item['raw']['activityId']}_ACTIVITY.fit", fit)
    return buf.getvalue()


def make_handler(demo):
    acts_desc = sorted(demo.activities, key=lambda a: a["raw"]["startTimeLocal"], reverse=True)
    by_id = {a["raw"]["activityId"]: a for a in demo.activities}

    def in_range(rows, a, b, key):
        return [r for r in rows if a <= r.get(key, "") <= b]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body=b"", ctype="application/json", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path.startswith("/personalapitoken-service/personal-api/personal-api-key/token"):
                if self.headers.get("Authorization") != f"ApiKey {API_KEY}":
                    return self.send(401, {"error": "bad key"})
                with LOCK:
                    STATE["token_requests"] += 1
                    n = STATE["token_requests"]
                return self.send(200, f"mock-token-{n}", "text/plain")
            self.send(404)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = u.path
            if p == "/__mock/release":
                STATE["hidden"] = 0
                return self.send(200, {"ok": True})
            if p == "/__mock/stats":
                return self.send(200, {k: v for k, v in STATE.items() if k != "fit_cache"})
            if p in ("/v1/forecast", "/v1/archive"):  # Open-Meteo stand-in
                data = fake_weather(q, archive=p.endswith("archive"))
                if data is None:
                    return self.send(400, {"error": True, "reason": "Cannot initialize WeatherVariable from invalid String value visibility"})
                return self.send(200, data)
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer mock-token-"):
                return self.send(401, {"error": "no token"})
            with LOCK:
                STATE["requests"] += 1
                n = STATE["requests"]
            if n == 7:  # one rate-limit response early on
                return self.send(429, {"error": "slow down"}, headers={"Retry-After": "1"})
            parts = p.strip("/").split("/")

            if p == "/activitylist-service/activities/search/activities":
                start, limit = int(q.get("start", 0)), int(q.get("limit", 20))
                if limit > 20:
                    return self.send(500, b"")
                visible = acts_desc[STATE["hidden"]:]
                return self.send(200, [a["raw"] for a in visible[start:start + limit]])
            if p.startswith("/download-service/files/activity/"):
                act_id = int(parts[-1])
                item = by_id.get(act_id)
                if not item:
                    return self.send(404)
                if act_id % 23 == 0:
                    return self.send(404)  # some activities have no file
                with LOCK:
                    blob = STATE["fit_cache"].get(act_id)
                if blob is None:
                    blob = build_fit(item)
                    with LOCK:
                        STATE["fit_cache"][act_id] = blob
                return self.send(200, blob, "application/zip")
            if p == "/usersummary-service/v2/dailysummaries":
                a, b = q["startDate"], q["endDate"]
                if (date.fromisoformat(b) - date.fromisoformat(a)).days > 31:
                    return self.send(400, {"error": "range"})
                return self.send(200, {"data": in_range(demo.daily, a, b, "calendarDate")})
            if p == "/sleep-service/sleep/dailySleepSummariesByDate":
                a, b = q["startDate"], q["endDate"]
                if (date.fromisoformat(b) - date.fromisoformat(a)).days > 20:
                    return self.send(400, {"error": "range"})  # forces the client to halve
                return self.send(200, in_range(demo.sleep, a, b, "calendarDate"))
            if p.startswith("/hrv-service/hrv/daily/"):
                a, b = parts[-2], parts[-1]
                return self.send(200, {"hrvSummaries": in_range(demo.hrv, a, b, "calendarDate")})
            if p.startswith("/weight-service/weight/range/"):
                a, b = parts[-2], parts[-1]
                return self.send(200, {"dailyWeightSummaries": in_range(demo.weight, a, b, "summaryDate")})
            if p.startswith("/metrics-service/metrics/maxmet/daily/"):
                return self.send(404)  # not in the Personal API (probably)
            if p.startswith("/fitnessage-service/fitnessage/v2/"):
                return self.send(200, demo.fitness_age())
            if p == "/biometric-service/heartRateZones/v2":
                return self.send(200, demo.hr_zones())
            return self.send(404, {"error": "not found"})

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--days", type=int, default=200)
    ap.add_argument("--hide", type=int, default=0, help="Hide the newest N activities until /__mock/release")
    args = ap.parse_args()
    demo = Demo(days=args.days, seed=7).build()
    STATE["hidden"] = args.hide
    print(f"Mock Garmin on http://127.0.0.1:{args.port} with {len(demo.activities)} activities", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(demo)).serve_forever()


if __name__ == "__main__":
    main()
