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

# --------------------------------------------------------------------------- #
# 6. API security
# --------------------------------------------------------------------------- #
# Bearer token for the administrative routes (subscriber registry, dispatch).
# Unset ⇒ those routes answer 503 instead of trusting an anonymous caller.
ADMIN_TOKEN = os.getenv("HS_ADMIN_TOKEN", "")

# Browser origins allowed to call this API. Empty default is deliberate: the web
# app talks to the API same-origin (Vite proxies /api in dev; a static host has
# no API at all), so no deployment *needs* CORS. Add origins explicitly, e.g.
# HS_ALLOWED_ORIGINS=https://heatshield.example
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("HS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
# Local development origins are added automatically unless the operator opts out.
ALLOW_DEV_ORIGINS = os.getenv("HS_ALLOW_DEV_ORIGINS", "1").strip().lower() in {"1", "true", "yes"}

# OpenAPI/docs UI. Default: on for local dev, off once an admin token exists
# (i.e. a real deployment), unless explicitly forced on.
_ENABLE_DOCS = os.getenv("HS_ENABLE_DOCS", "").strip().lower()
ENABLE_DOCS = (_ENABLE_DOCS in {"1", "true", "yes"}) if _ENABLE_DOCS else not ADMIN_TOKEN

# Requests per client per minute on the public API. 0 disables the limiter
# (the test suite does this); raise it for a busy deployment.
RATE_LIMIT_PER_MIN = int(os.getenv("HS_RATE_LIMIT_PER_MIN", "120"))
# Largest accepted request body, in bytes. Bodies are small JSON documents.
MAX_BODY_BYTES = int(os.getenv("HS_MAX_BODY_BYTES", str(256 * 1024)))
# How long a public read endpoint may be cached by a browser or proxy, in
# seconds. The data behind them changes at most once per forecast cycle, so a
# repeat visitor should not wait for pandas twice. 0 turns the header off and
# every response goes back to `no-store`.
RESPONSE_CACHE_MAX_AGE = int(os.getenv("HS_RESPONSE_CACHE_MAX_AGE", "120"))
# Set when the app runs behind a trusted reverse proxy, so X-Forwarded-For can be
# believed for rate-limiting purposes.
TRUST_PROXY = os.getenv("HS_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}
