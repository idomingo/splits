"""Read Garmin activity files (FIT, or a ZIP holding a FIT) into plain lists."""
import io
import zipfile
from datetime import datetime, timezone

import fitdecode

SEMICIRCLE = 180.0 / 2 ** 31


def extract_fit_bytes(blob: bytes) -> bytes | None:
    """Return the FIT payload from a download (ZIP or raw FIT)."""
    if not blob:
        return None
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not names:
                return None
            # largest FIT member is the activity recording
            names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
            return zf.read(names[0])
    if len(blob) > 12 and blob[8:12] == b".FIT":
        return blob
    return None


def _val(frame, *names):
    for n in names:
        if frame.has_field(n):
            v = frame.get_value(n, fallback=None)
            if v is not None:
                return v
    return None


def _ts(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.timestamp()
    return None


def parse_fit(fit_bytes: bytes, steps_per_cycle: int = 1) -> dict:
    """Parse records, laps and session. steps_per_cycle=2 for run/walk cadence."""
    rec = {k: [] for k in ("ts", "d", "hr", "spd", "cad", "alt", "lat", "lon", "pwr", "tmp")}
    laps = []
    session = {}
    vo2max = None
    with fitdecode.FitReader(io.BytesIO(fit_bytes), check_crc=fitdecode.CrcCheck.DISABLED) as fr:
        for frame in fr:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name == "record":
                ts = _ts(_val(frame, "timestamp"))
                if ts is None:
                    continue
                lat = _val(frame, "position_lat")
                lon = _val(frame, "position_long")
                cad = _val(frame, "cadence")
                if cad is not None:
                    frac = _val(frame, "fractional_cadence") or 0
                    cad = (cad + frac) * steps_per_cycle
                rec["ts"].append(ts)
                rec["d"].append(_num(_val(frame, "distance")))
                rec["hr"].append(_num(_val(frame, "heart_rate")))
                rec["spd"].append(_num(_val(frame, "enhanced_speed", "speed")))
                rec["cad"].append(_num(cad))
                rec["alt"].append(_num(_val(frame, "enhanced_altitude", "altitude")))
                rec["lat"].append(lat * SEMICIRCLE if isinstance(lat, (int, float)) else None)
                rec["lon"].append(lon * SEMICIRCLE if isinstance(lon, (int, float)) else None)
                rec["pwr"].append(_num(_val(frame, "power")))
                rec["tmp"].append(_num(_val(frame, "temperature")))
            elif frame.name == "lap":
                cad = _val(frame, "avg_running_cadence", "avg_cadence")
                if cad is not None:
                    frac = _val(frame, "avg_fractional_cadence") or 0
                    cad = (cad + frac) * steps_per_cycle
                laps.append({
                    "start_ts": _ts(_val(frame, "start_time")),
                    "duration_s": _num(_val(frame, "total_timer_time", "total_elapsed_time")),
                    "distance_m": _num(_val(frame, "total_distance")),
                    "avg_speed": _num(_val(frame, "enhanced_avg_speed", "avg_speed")),
                    "avg_hr": _num(_val(frame, "avg_heart_rate")),
                    "max_hr": _num(_val(frame, "max_heart_rate")),
                    "avg_cadence": _num(cad),
                    "elev_gain_m": _num(_val(frame, "total_ascent")),
                    "elev_loss_m": _num(_val(frame, "total_descent")),
                    "avg_power": _num(_val(frame, "avg_power")),
                })
            elif frame.name == "unknown_140" or getattr(frame, "global_mesg_num", None) == 140:
                # Garmin writes the VO2max estimate here (not in the public FIT profile)
                raw = None
                for fld in frame.fields:
                    if fld.def_num == 7:
                        raw = fld.raw_value if hasattr(fld, "raw_value") else fld.value
                if isinstance(raw, (int, float)) and raw > 0:
                    v = raw * 3.5 / 65536.0
                    if 15 <= v <= 95:
                        vo2max = round(v, 2)
            elif frame.name == "session":
                session = {
                    "sport": str(_val(frame, "sport") or ""),
                    "start_ts": _ts(_val(frame, "start_time")),
                    "total_distance": _num(_val(frame, "total_distance")),
                    "total_timer_time": _num(_val(frame, "total_timer_time")),
                }
    if not rec["ts"]:
        return {"samples": {}, "laps": laps, "session": session, "vo2max": vo2max}
    t0 = rec["ts"][0]
    samples = {"t": [round(x - t0, 1) for x in rec["ts"]]}
    for k in ("d", "hr", "spd", "cad", "alt", "lat", "lon", "pwr", "tmp"):
        if any(v is not None for v in rec[k]):
            samples[k] = rec[k]
    for lap in laps:
        lap["start_offset_s"] = (lap["start_ts"] - t0) if lap.get("start_ts") else None
    return {"samples": samples, "laps": laps, "session": session, "t0": t0, "vo2max": vo2max}


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    return None
