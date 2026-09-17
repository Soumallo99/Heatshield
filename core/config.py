"""Central config. Zero-dependency, hackathon-fast (no pydantic-settings needed)."""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"
WARDS_CSV = DATA_DIR / "wards.csv"

for _d in (RAW_DIR, PROCESSED_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- data source
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = os.getenv("HS_TIMEZONE", "Asia/Kolkata")
FORECAST_DAYS = int(os.getenv("HS_FORECAST_DAYS", "5"))   # 3-5 day MVP window
PAST_DAYS = int(os.getenv("HS_PAST_DAYS", "1"))             # "now" context (use past_days, NOT past_hours:
                                                            # past_hours conflicts with forecast_days and silently
                                                            # stretches the window to 16 days)
CACHE_TTL_MIN = int(os.getenv("HS_CACHE_TTL_MIN", "30"))   # don't hammer the free API
BATCH_SIZE = int(os.getenv("HS_BATCH_SIZE", "40"))         # coords per HTTP request

# Deterministic operator drill profiles. Values are day offsets, anchored to
# the first date returned by the forecast window.
DRILL_PROFILES = {
    "heatwave": {
        "label": "Heatwave drill",
        "description": "A deterministic escalating heatwave anomaly for response rehearsal.",
        "anomalies_c": [0.0, 0.0, 0.0, 1.5, 5.0, 8.5],
    },
}

# Hourly variables we need now (Phase 1) + later (Phase 2 WBGT/Heat Index).
# shortwave_radiation -> globe temperature (outdoor WBGT)
# direct_normal_irradiance -> sun-angle / shade refinements
HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "direct_normal_irradiance",
    "cloud_cover",
    "apparent_temperature",
]

# ---------------------------------------------------------------- risk bands (Phase 3)
RISK_BANDS = [
    (0,  25, "Green",  "Normal"),
    (25, 50, "Yellow", "Caution"),
    (50, 75, "Orange", "Danger"),
    (75, 101, "Red",   "Critical"),
]

# ---------------------------------------------------------------- alerts (Phase 5)
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER", "")       # whatsapp:+14155238886
ALERT_TO = [n.strip() for n in os.getenv("ALERT_TO_NUMBERS", "").split(",") if n.strip()]

# Sending costs money and wakes people up, so live dispatch needs TWO things to
# be true: real credentials AND an explicit opt-in flag. Either one missing and
# dispatch() refuses — you cannot accidentally SMS a city by forgetting an arg.
ALLOW_LIVE_SEND = os.getenv("HS_ALLOW_LIVE_SEND", "").strip().lower() in {"1", "true", "yes"}
