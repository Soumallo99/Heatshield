"""
HeatShield API — FastAPI skeleton (Phase 1).
Endpoints grow each phase: /thermal (P2), /risk (P3), /alerts (P5).

Run:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

import pandas as pd
from zoneinfo import ZoneInfo
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from core.response_cache import ResponseCache
from core.security import (RateLimiter, client_key, redact_phone, require_admin,
                           sanitise_phone_list)

from core import config
from core import demo as demo_engine
from core.coupled import (
    HEAT_AQI_PARAMETERS,
    _ncr_frame,
    heatwave_advance_payload,
    ncr_daily,
    ncr_zones,
)
from core.alerts import (DEFAULT_MIN_LEAD_DAYS, DEFAULT_RISK_THRESHOLD,
                         compose_message, dispatch, filter_already_sent,
                         find_active_now, find_upcoming_events)
from core.notify import dispatch_previews, plan_notifications
from core.warnings import advance_warning_payload
from core.risk import compute_risk, daily_risk, risk_band, ward_ranking
from core.subscribers import (add_subscriber as reg_add,
                              load_registry, opt_out as reg_opt_out,
                              recipients_for_ward, registry_stats)
from core import live as live_layers
from core.thermal import classify_wbgt, compute_thermal, daily_thermal, heatwave_flags, work_rest
from core.weather import UpstreamError, daily_peak, get_forecast, load_wards

# The interactive schema is a map of every route, including the administrative
# ones. Useful locally, needless exposure on a public deployment — so it is on by
# default in development and off once an admin token exists. HS_ENABLE_DOCS
# forces either way.
_DOCS = "/docs" if config.ENABLE_DOCS else None
_OPENAPI = "/openapi.json" if config.ENABLE_DOCS else None

app = FastAPI(
    title="HeatShield API",
    version="0.1.0",
    description="Extreme Heatwave Early Warning & Human Thermal Stress Index",
    docs_url=_DOCS,
    redoc_url=None,
    openapi_url=_OPENAPI,
)

# Browser origins: only what the operator lists, plus localhost dev ports when
# HS_ALLOW_DEV_ORIGINS is not turned off. `allow_origins=["*"]` used to let any
# website read the subscriber registry from a visitor's browser.
_ORIGINS = list(config.ALLOWED_ORIGINS)
if config.ALLOW_DEV_ORIGINS:
    _ORIGINS += [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ]
if _ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "X-HeatShield-Token", "Authorization"],
        max_age=600,
    )

# Requests per client per minute on the whole API. Enumeration of the registry
# and repeated dispatch attempts are the things this is here to make boring.
# Answers to the public reads, kept for as long as they are allowed to be cached.
# Per-process, like the limiter: see core/response_cache.py for what it does and
# what it deliberately does not.
answer_cache = ResponseCache(config.RESPONSE_CACHE_MAX_AGE)

# Compression. The ranking payload is a few hundred kB of JSON for 141 wards and
# the exports are larger; text compresses about 8:1. Added last so it wraps
# everything else, including the guard's own error responses. Small bodies are
# skipped — gzip on a 200-byte reply costs more than it saves.
app.add_middleware(GZipMiddleware, minimum_size=1024)

limiter = RateLimiter(config.RATE_LIMIT_PER_MIN)

_DOC_PATHS = {"/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}

# One logger, one place to look. Without this an unhandled exception in a route
# reaches the client as a bare "Internal Server Error" with nothing in the
# server log tying it to a request — the worst kind of bug report.
logger = logging.getLogger("heatshield.api")

# Responses that may be cached, in seconds. A public read built from the last
# computed run is the same for every visitor until the next forecast cycle, so
# a repeat request (a phone reopening the tab, a second reader) should not pay
# for the computation again.
#
# Deliberately absent: anything that can contain personal data
# (/subscribers*), anything that sends or mutates, and every administrative
# route. Those keep the `no-store` default.
_CACHEABLE_READS = {
    "/health": 30,
    "/risk": config.RESPONSE_CACHE_MAX_AGE,
    "/risk/": config.RESPONSE_CACHE_MAX_AGE,
    "/thermal": config.RESPONSE_CACHE_MAX_AGE,
    "/thermal/": config.RESPONSE_CACHE_MAX_AGE,
    "/alerts/plan": config.RESPONSE_CACHE_MAX_AGE,
    "/ncr/": config.RESPONSE_CACHE_MAX_AGE,
    # The Kolkata citizen brief is the second-largest public read in the API
    # (~365 kB raw, ~9 kB on the wire, rebuilt from the committed forecast cache
    # on every request). It is the same document for every visitor and carries
    # no personal field — the opt-in registry lives under /subscribers, which
    # stays deliberately uncacheable — so a phone reopening its tab should not
    # pay for the rebuild.
    "/citizen/": config.RESPONSE_CACHE_MAX_AGE,
    "/warnings/advance": config.RESPONSE_CACHE_MAX_AGE,
    "/zones": config.RESPONSE_CACHE_MAX_AGE,
    "/wards": config.RESPONSE_CACHE_MAX_AGE,
    "/demo/": 600,
    # NB: nothing under /subscribers appears here, not even the aggregate stats.
    # A path family that is cacheable in one place and forbidden in another is a
    # rule waiting to be broken by the next field someone adds to it.
}


def _cache_seconds(path: str) -> int:
    """Cache lifetime for a GET path, 0 when it must not be cached."""
    if config.RESPONSE_CACHE_MAX_AGE <= 0:
        return 0
    for prefix, seconds in _CACHEABLE_READS.items():
        if path == prefix or path.startswith(prefix):
            return min(seconds, config.RESPONSE_CACHE_MAX_AGE)
    return 0


@app.exception_handler(UpstreamError)
async def _upstream_unavailable(request: Request, exc: UpstreamError) -> JSONResponse:
    """503, not 500: the weather provider is down, this server is fine.

    The distinction matters on the screen. A 500 sends an operator looking for a
    bug in HeatShield; a 503 that says why sends them to the provider's status
    page, and tells a visitor honestly that the numbers are unavailable rather
    than broken. Cached runs never land here — only a live fetch can.
    """
    logger.warning("upstream weather unavailable on %s: %s", request.url.path, exc)
    return JSONResponse(
        {
            "detail": "the weather provider is unavailable right now",
            "upstream": str(exc)[:500],
            "remedy": (
                "cached runs are unaffected — retry later, or run "
                "scripts/refresh.py once the provider recovers"
            ),
        },
        status_code=503,
    )


def _base_headers(request_id: str) -> dict[str, str]:
    """Headers every response carries, cached or fresh."""
    return {
        "X-Request-ID": request_id,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
    }


def _cacheable_headers(headers) -> dict[str, str]:
    """The response headers worth replaying from cache.

    Content-Type carries the media type, Content-Encoding says whether the bytes
    are gzipped, and Vary tells a shared cache that the encoding matters. The
    rest (length, cache-control, request id) is recomputed per request.
    """
    keep = ("content-type", "content-encoding", "vary", "etag", "last-modified")
    return {key: value for key, value in headers.items() if key.lower() in keep}


async def _store_answer(key: str, response, ttl: int):
    """Keep a copy of a 200 for the next reader, and return it unchanged.

    Reading `body_iterator` consumes it, so the response is rebuilt from the
    bytes we just buffered. Only 200s are stored: an error is not an answer, and
    caching one would turn a transient failure into a two-minute outage.
    """
    if response.status_code != 200:
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])
    headers = dict(response.headers)
    answer_cache.set(key, body, headers.get("content-type", "application/json"),
                     _cacheable_headers(headers), ttl)
    return Response(content=body, status_code=response.status_code, headers=headers)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Rate limit, body-size cap, docs lock, cache, security headers, request ids.

    Order matters: cheap rejections happen before anything touches pandas, and a
    cache hit happens before anything runs at all.
    """
    request_id = uuid4().hex[:12]
    request.state.request_id = request_id
    if not config.ENABLE_DOCS and request.url.path in _DOC_PATHS:
        return JSONResponse({"detail": "API documentation is disabled on this deployment"},
                            status_code=404)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)

    allowed, retry_after = limiter.allow(client_key(request))
    if not allowed:
        return JSONResponse(
            {"detail": "rate limit exceeded — try again shortly"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    # A credentialed request is never cached, in either direction: an operator's
    # view must not be served to the next visitor, and must not be stored under a
    # key a visitor can reach.
    authenticated = any(
        request.headers.get(header) for header in ("X-HeatShield-Token", "X-API-Key", "Authorization")
    )
    # A cross-origin request is answered without the shared cache. The CORS
    # middleware sits *inside* this one, so a body replayed from here would reach
    # the browser without its Access-Control-Allow-Origin header — the request
    # would be blocked on a cache hit and allowed on a miss, which is worse than
    # either. Our own pages are same-origin, so this costs the crowd nothing.
    cross_origin = bool(request.headers.get("origin"))
    ttl = _cache_seconds(request.url.path) if request.method == "GET" else 0
    cache_key = None
    flight = None
    if ttl and not authenticated and not cross_origin:
        cache_key = ResponseCache.key(
            request.url.path, request.url.query, request.headers.get("accept-encoding", ""), ttl
        )
        entry = answer_cache.get(cache_key)
        if entry is not None:
            return Response(
                content=entry.body,
                headers={**entry.headers, **_base_headers(request_id), "X-Cache": "HIT",
                         "Cache-Control": f"public, max-age={ttl}, stale-while-revalidate=60"},
            )

        # Single flight. The same page opened by thirty people at once is the
        # normal pattern during a heat wave; it must not be computed thirty
        # times. Waiters sleep rather than block — this is the event loop — and
        # take over if the owner dies, so one failure cannot strand the rest.
        flight, owner = answer_cache.claim(cache_key)
        if not owner:
            # The waiting bound is generous on purpose. A cold compute of the
            # heaviest public read takes ~9 s on one worker, and a waiter that
            # gives up early does not get its answer faster — it starts a second
            # copy of the same work and makes the whole burst slower, which is
            # exactly what the first version of this did (p95 17.7 s, cold).
            for _ in range(600):                     # ~24 s, then compute it anyway
                if flight.is_set():
                    break
                await asyncio.sleep(0.04)
            entry = answer_cache.get(cache_key)
            if entry is not None:
                return Response(
                    content=entry.body,
                    headers={**entry.headers, **_base_headers(request_id), "X-Cache": "COALESCED",
                             "Cache-Control": f"public, max-age={ttl}, stale-while-revalidate=60"},
                )
            flight = answer_cache.takeover(cache_key, flight)

    try:
        response = await call_next(request)
        if cache_key is not None:
            response = await _store_answer(cache_key, response, ttl)
    except Exception:  # noqa: BLE001 — deliberate catch-all: log, name it, say nothing
        # A traceback in the response body is an information leak; nothing at
        # all is worse. Log the whole thing against the request id and hand the
        # client a JSON error it can quote.
        logger.exception("unhandled error on %s %s (request %s)", request.method, request.url.path, request_id)
        return JSONResponse(
            {"detail": "internal error", "request_id": request_id},
            status_code=500,
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )
    finally:
        if cache_key is not None:
            answer_cache.release(cache_key)

    if response.status_code >= 500:
        logger.error("server error %s on %s %s (request %s)",
                     response.status_code, request.method, request.url.path, request_id)

    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if ttl and response.status_code == 200 and not authenticated:
        response.headers.setdefault("Cache-Control", f"public, max-age={ttl}, stale-while-revalidate=60")
    else:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# Input bounds. Every one of these was unbounded before: `?scenario_c=1e9` burned
# nine seconds of CPU per request, and `ward_id=99999` was cheerfully accepted
# into the subscriber registry. The UI's scenario lever spans 0-8 °C.
SCENARIO_MIN, SCENARIO_MAX = -10.0, 20.0
WARD_MAX = 141            # KMC wards (see DATA.md)
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# Shorthand: the admin gate on the routes that read personal data or can send.
AdminOnly = Depends(require_admin)

def live_fetch_guard(request: Request, use_cache: bool = True) -> None:
    """A forced live fetch is an operator action, not a visitor one.

    `?use_cache=false` skips the cache and calls Open-Meteo directly, with three
    retries and backoff between them. Left open, any anonymous client could drive
    that loop as often as it liked — burning our upstream quota (which is free but
    rate-limited) and holding a worker thread for seconds per call. The operator
    who wants current weather has a token (and `scripts/refresh.py`); everyone
    else gets the cached run, which is what the UI uses anyway.
    """
    if not use_cache:
        require_admin(request)


def _now_local() -> pd.Timestamp:
    """Current time in the configured forecast timezone, tz-naive to match the data."""
    return pd.Timestamp.now(tz=ZoneInfo(config.TIMEZONE)).replace(tzinfo=None).floor("h")


def _window(df: pd.DataFrame, hours: int, ward_id: int | None = None) -> pd.DataFrame:
    """
    Next `hours` hours from now — not from the start of the forecast.

    The ward filter MUST run before head(): rows are ordered ward-by-ward, so
    head(24) on the unfiltered frame would silently return only ward 1.
    """
    if ward_id is not None:
        df = df[df["ward_id"] == ward_id]
    return df[df["timestamp_local"] >= _now_local()].head(hours)


def _records(frame: pd.DataFrame, *, timestamp_columns: tuple[str, ...] = ("timestamp_local",),
             date_columns: tuple[str, ...] = ("date",)) -> list[dict]:
    """JSON-safe records for provider data.

    Open-Meteo can legitimately omit a pollutant.  JSON forbids NaN, and a
    missing optional field must not turn a healthy fallback route into a 500.
    """
    out = frame.copy()
    for column in timestamp_columns:
        if column in out:
            out[column] = pd.to_datetime(out[column], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M")
    for column in date_columns:
        if column in out:
            out[column] = out[column].astype(str)
    # astype(object) is important: otherwise pandas silently coerces None back
    # to NaN in a floating-point column.
    out = out.astype(object).where(pd.notna(out), None)
    return out.to_dict(orient="records")


def _ncr_filtered(zone_id: str | None = None, days: int | None = None) -> tuple[pd.DataFrame, str | None]:
    """Common NCR route path: live if possible, synthetic only when necessary."""
    frame, fallback_reason = _ncr_frame(days=days)
    if zone_id is not None:
        frame = frame[frame["zone_id"] == zone_id].copy()
        if frame.empty:
            raise HTTPException(404, f"NCR zone '{zone_id}' not found")
    return frame, fallback_reason


@app.get("/")
def root():
    """Service banner. Handy when someone opens the API port in a browser."""
    return {
        "service": "HeatShield API",
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/zones", "/forecast", "/forecast/daily",
            "/thermal", "/thermal/daily", "/thermal/ward/{ward_id}",
            "/risk", "/risk/daily", "/risk/ranking", "/risk/ward/{ward_id}",
            "/alerts/plan", "/alerts/dispatch",
            "/ncr/zones", "/ncr/forecast", "/ncr/air-quality", "/ncr/heat-aqi",
            "/ncr/daily", "/ncr/summary", "/ncr/metadata", "/ncr/validation",
            "/ncr/alerts", "/heatwave/advance",
            # Optional live tracking layers for the operations globe. They are
            # additive and off by default in the UI; nothing on this platform is
            # computed from them.
            "/live/aircraft", "/live/earthquakes", "/live/satellites",
            "/warnings/advance", "/notifications/preview", "/notifications/dispatch",
            "/demo/scenarios", "/demo/zones", "/demo/forecast", "/demo/thermal",
            "/demo/warnings", "/demo/notifications",
        ],
        "demo_notice": demo_engine.DEMO_DISCLAIMER + " See /demo/scenarios.",
        "alert_defaults": {
            "risk_threshold": DEFAULT_RISK_THRESHOLD,
            "min_lead_days": DEFAULT_MIN_LEAD_DAYS,
        },
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "HeatShield API",
        "version": app.version,
        "time_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "timezone": config.TIMEZONE,
    }


@app.get("/zones")
def zones():
    """Ward registry + demographics (the map layer + Phase 3 inputs)."""
    df = load_wards()
    return {"count": len(df), "zones": df.to_dict(orient="records")}


@app.get("/forecast")
def forecast(
    hours: int = Query(24, ge=1, le=24 * 16, description="Hours from most recent past hour"),
    ward_id: Annotated[int | None, Query(ge=1, le=WARD_MAX)] = None,
    use_cache: bool = Query(
        True,
        description="Serve the cached run. `false` forces a live upstream fetch and requires the admin token",
    ),
    _live: Annotated[None, Depends(live_fetch_guard)] = None,
):
    """Hourly raw weather for all wards (Phase 1 output)."""
    df = get_forecast(use_cache=use_cache)
    if df.empty:
        raise HTTPException(502, "Upstream weather provider returned no data")

    if ward_id is not None and ward_id not in set(df["ward_id"]):
        raise HTTPException(404, f"ward_id {ward_id} not found")
    df = _window(df, hours, ward_id)

    out = df.copy()
    out["timestamp_local"] = out["timestamp_local"].dt.strftime("%Y-%m-%dT%H:%M")
    out["fetched_at"] = out["fetched_at"].astype(str)
    return {
        "rows": len(out),
        "window": [out["timestamp_local"].min(), out["timestamp_local"].max()],
        "fetched_at": df["fetched_at"].iloc[0].isoformat(),
        "data": out.to_dict(orient="records"),
    }


@app.get("/forecast/daily")
def forecast_daily():
    """Daily Tmax / Tmin / RH per ward — the shape the dashboard + alerts consume."""
    df = get_forecast()
    d = daily_peak(df)
    d["date"] = d["date"].astype(str)
    return {"rows": len(d), "data": d.to_dict(orient="records")}


# ------------------------------------------------------------------ NCR: heat + air quality
# These routes power the installable phone app.  They are deliberately compact,
# stable contracts so scripts/export_static.py can materialise every one for a
# GitHub Pages deployment, where there is no FastAPI proxy.

@app.get("/ncr/zones")
def ncr_zone_list():
    zones = ncr_zones()
    return {"count": int(len(zones)), "data": _records(zones, timestamp_columns=(), date_columns=())}


@app.get("/ncr/forecast")
def ncr_forecast(
    hours: int = Query(120, ge=1, le=24 * 8),
    zone_id: str | None = None,
):
    """NCR hourly weather, with an explicit offline-exercise marker if needed."""
    frame, fallback_reason = _ncr_filtered(zone_id)
    frame = frame.sort_values("timestamp_local").groupby("zone_id", group_keys=False).head(hours)
    weather_cols = [
        "zone_id", "zone_name", "lat", "lon", "timestamp_local", "temp_c", "rh_pct",
        "wind_kmh", "precip_mm", "surface_pressure_hpa", "solar_wm2",
    ]
    return {
        "rows": int(len(frame)), "zone_id": zone_id,
        "data_source": str(frame["data_source"].iloc[0]) if len(frame) else "unavailable",
        "is_synthetic": bool(frame["is_synthetic"].iloc[0]) if len(frame) else True,
        "fallback_reason": fallback_reason,
        "data": _records(frame[[column for column in weather_cols if column in frame]]),
    }


@app.get("/ncr/air-quality")
def ncr_air_quality(
    hours: int = Query(120, ge=1, le=24 * 8),
    zone_id: str | None = None,
):
    """Indicative NCR pollutant forecast and Indian PM2.5 sub-index."""
    frame, fallback_reason = _ncr_filtered(zone_id)
    frame = frame.sort_values("timestamp_local").groupby("zone_id", group_keys=False).head(hours)
    air_cols = [
        "zone_id", "zone_name", "lat", "lon", "timestamp_local", "pm25_ugm3", "pm10_ugm3",
        "no2_ugm3", "o3_ugm3", "so2_ugm3", "provider_us_aqi", "aqi_india", "aqi_band",
    ]
    return {
        "rows": int(len(frame)), "zone_id": zone_id,
        "index_note": "AQI is an indicative Indian PM2.5 sub-index from hourly forecast concentrations, not a certified station AQI.",
        "data_source": str(frame["data_source"].iloc[0]) if len(frame) else "unavailable",
        "is_synthetic": bool(frame["is_synthetic"].iloc[0]) if len(frame) else True,
        "fallback_reason": fallback_reason,
        "data": _records(frame[[column for column in air_cols if column in frame]]),
    }


@app.get("/ncr/heat-aqi")
def ncr_heat_aqi(
    hours: int = Query(120, ge=1, le=24 * 8),
    zone_id: str | None = None,
):
    """Joint heat–air *load*, kept distinct from the pollutant AQI itself."""
    frame, fallback_reason = _ncr_filtered(zone_id)
    frame = frame.sort_values("timestamp_local").groupby("zone_id", group_keys=False).head(hours)
    cols = [
        "zone_id", "zone_name", "timestamp_local", "temp_c", "pm25_ugm3", "aqi_india", "aqi_band",
        "heat_multiplier", "heat_aqi_load", "heat_aqi_load_band", "ventilation_index",
    ]
    return {
        "rows": int(len(frame)), "zone_id": zone_id,
        "parameters": HEAT_AQI_PARAMETERS,
        "parameterised_not_validated": True,
        "data_source": str(frame["data_source"].iloc[0]) if len(frame) else "unavailable",
        "is_synthetic": bool(frame["is_synthetic"].iloc[0]) if len(frame) else True,
        "fallback_reason": fallback_reason,
        "data": _records(frame[[column for column in cols if column in frame]]),
    }


@app.get("/ncr/daily")
def ncr_daily_route(zone_id: str | None = None):
    """Daily Tmax, PM2.5 and joint-load peaks for all NCR phone-app locations."""
    frame, fallback_reason = _ncr_filtered(zone_id)
    daily = ncr_daily(frame)
    return {
        "rows": int(len(daily)), "zone_id": zone_id,
        "data_source": str(frame["data_source"].iloc[0]) if len(frame) else "unavailable",
        "is_synthetic": bool(frame["is_synthetic"].iloc[0]) if len(frame) else True,
        "fallback_reason": fallback_reason,
        "data": _records(daily.drop(columns=["data_source", "is_synthetic", "fetched_at"], errors="ignore")),
    }


@app.get("/ncr/summary")
def ncr_summary(zone_id: str | None = None):
    """Small cold-open payload for the citizen phone app.

    This is intentionally a summary rather than the full 120-hour tables.  It
    keeps an installed app quick to open on constrained networks, while detail
    screens can load the static ``/ncr/*`` exports on demand.
    """
    frame, fallback_reason = _ncr_filtered(zone_id)
    if frame.empty:
        return {"rows": 0, "data": [], "is_synthetic": True, "fallback_reason": fallback_reason}
    now = _now_local()
    upcoming = frame[frame["timestamp_local"] >= now]
    if upcoming.empty:
        upcoming = frame
    current = (
        upcoming.sort_values("timestamp_local")
        .groupby("zone_id", as_index=False)
        .first()
        .sort_values("heat_aqi_load", ascending=False)
    )
    daily = ncr_daily(frame)
    next_day = daily[daily["date"] >= now.date()]
    city = {
        "timestamp_local": str(current["timestamp_local"].min().strftime("%Y-%m-%dT%H:%M")),
        "zones": int(current["zone_id"].nunique()),
        "hottest_temp_c": float(current["temp_c"].max()),
        "highest_aqi": float(current["aqi_india"].max()),
        "highest_heat_aqi_load": float(current["heat_aqi_load"].max()),
        "days": int(next_day["date"].nunique()),
    }
    cols = [
        "zone_id", "zone_name", "lat", "lon", "timestamp_local", "temp_c", "rh_pct", "wind_kmh",
        "pm25_ugm3", "aqi_india", "aqi_band", "heat_multiplier", "heat_aqi_load", "heat_aqi_load_band",
        "data_source", "is_synthetic", "fetched_at",
    ]
    return {
        "rows": int(len(current)), "zone_id": zone_id, "city": city,
        "data_source": str(frame["data_source"].iloc[0]),
        "is_synthetic": bool(frame["is_synthetic"].iloc[0]),
        "fallback_reason": fallback_reason,
        "data": _records(current[[column for column in cols if column in current]]),
    }


@app.get("/ncr/metadata")
def ncr_metadata():
    """Method and provenance card; a UI must not hide model limits."""
    return {
        "zones": int(len(ncr_zones())),
        "weather_source": "Open-Meteo numerical weather forecast when reachable",
        "air_source": "Open-Meteo CAMS atmospheric-composition forecast when reachable",
        "offline_mode": "deterministic synthetic exercise episode, explicitly labelled in each response",
        "aqi_method": "Indian PM2.5 sub-index breakpoint interpolation",
        "joint_load": HEAT_AQI_PARAMETERS,
        "validated": {
            "aqi_concentrations": "See /ncr/validation; requires CPCB/CAAQMS observations.",
            "joint_heat_aqi_load": "Parameterised communication indicator; not calibrated as a health-outcome model.",
        },
    }


@app.get("/ncr/validation")
def ncr_validation():
    """Last reproducible observed-AQI validation report, if one has been built."""
    path = config.DATA_DIR / "validation" / "coupled_aqi_validation.json"
    if not path.exists():
        return {
            "available": False,
            "message": "No CPCB/CAAQMS validation report has been generated yet.",
            "how": "python -m scripts.validate_coupled_aqi --observations <cpcb.csv>",
        }
    try:
        import json
        return {"available": True, **json.loads(path.read_text())}
    except (OSError, ValueError):
        return {
            "available": False,
            "message": "Validation report is unreadable; rebuild it from the observed source file.",
        }


@app.get("/heatwave/advance")
def heatwave_advance(
    days: int = Query(config.FORECAST_DAYS, ge=1, le=8),
    zone_id: str | None = None,
    force_refresh: bool = False,
):
    """IMD-plains heatwave watch with a 3–5 day lead and offline fallback.

    Unlike the original implementation, this route goes through ``_ncr_frame``
    via ``heatwave_advance_payload``.  An Open-Meteo outage therefore produces
    a labelled synthetic exercise episode rather than an HTTP 500.
    """
    try:
        return heatwave_advance_payload(days=days, zone_id=zone_id, force_refresh=force_refresh)
    except KeyError:
        raise HTTPException(404, f"NCR zone '{zone_id}' not found") from None


@app.get("/ncr/alerts")
def ncr_alerts(days: int = Query(config.FORECAST_DAYS, ge=1, le=8)):
    """Compact heatwave-alert queue for the phone app notification surface."""
    payload = heatwave_advance_payload(days=days)
    rows = [row for row in payload["data"] if row.get("is_heatwave_episode")]
    return {
        "rows": len(rows),
        "data_source": payload["data_source"],
        "is_synthetic": payload["is_synthetic"],
        "fallback_reason": payload["fallback_reason"],
        "climatology": payload["climatology"],
        "data": rows,
    }


# ------------------------------------------------------------------ advance warnings
# The operational 3–5 day early-warning product. Unlike /heatwave/advance
# (IMD Tmax rule only), every row here carries the full decision chain:
# issuance + lead time, heatwave persistence, HTSI thermal-stress level,
# vulnerability level, health-impact indicator status, action level, and
# provenance. Built on _ncr_frame, so a provider outage yields a labelled
# synthetic exercise frame instead of HTTP 500.

# ------------------------------------------------------------------ Citizen briefs
@app.get("/citizen/kolkata")
def citizen_kolkata():
    """Citizen phone brief for KOLKATA — same payload contract as citizen.json.

    Honesty rules baked in here (and enforced by tests/test_citizen_kolkata.py):

    * Kolkata has NO bundled air-quality source. AQI/PM2.5/load fields are
      null and their bands read "Unavailable" — the brief leads with WBGT
      thermal stress instead of inventing an air number.
    * No fixed per-ward climate normals ship for Kolkata, so the departure
      rule is NOT claimed (``climatology.available = false``). Heatwave
      labels use the IMD coastal ABSOLUTE-temperature rule (Tmax ≥ 37 °C,
      severe ≥ 40 °C) with the standard two-day persistence; a single hot
      day stays an early "Hot-day watch".
    * Offline-safe: served from the committed forecast cache. With no cache
      and no network it returns an empty, labelled payload — never a 500.
    """
    envelope_notice = (
        "Kolkata citizen brief — thermal-stress (WBGT) based. No air-quality source is "
        "bundled for Kolkata, so AQI fields are honestly unavailable. Heatwave labels use "
        "the IMD coastal absolute-temperature rule with two-day persistence; fixed per-ward "
        "climate normals are not bundled, so no departure-based declaration is made."
    )

    def _empty(reason: str) -> dict:
        return {
            "schema_version": 1,
            "source_notice": f"{envelope_notice} Current state: {reason}",
            "summary": {
                "city_profile": "kolkata",
                "static_snapshot": False,
                "is_synthetic": False,
                "data_source": reason,
                "fallback_reason": reason,
                "city": {
                    "timestamp_local": _now_local().strftime("%Y-%m-%dT%H:%M"),
                    "zones": 0, "hottest_temp_c": None, "highest_aqi": None,
                    "highest_heat_aqi_load": None, "peak_wbgt_c": None, "wards_in_alert": 0,
                },
                "data": [],
            },
            "daily": [],
            "alerts": {
                "rows": 0,
                "climatology": _kolkata_climatology_note(),
                "data": [],
            },
        }

    try:
        forecast = get_forecast()
    except Exception as exc:  # noqa: BLE001 — offline with cold cache must not 500
        return _empty(f"Kolkata forecast unavailable ({str(exc)[:160]}). Run: python -m scripts.refresh")

    if forecast is None or forecast.empty:
        return _empty("Kolkata forecast cache is empty. Run: python -m scripts.refresh")

    fetched_at = str(forecast["fetched_at"].iloc[0])
    try:
        age_min = (datetime.now(tz=ZoneInfo("UTC")) - pd.Timestamp(fetched_at)).total_seconds() / 60.0
    except (ValueError, TypeError):
        age_min = None
    stale = age_min is not None and age_min > config.CACHE_TTL_MIN
    source_label = f"Open-Meteo forecast cache fetched {fetched_at}" + (
        " — stale cache served offline" if stale else ""
    )

    thermal = compute_thermal(forecast)
    daily = daily_thermal(forecast)
    risk = daily_risk(forecast)

    # --- "now" row per ward: the cached hour closest to the current local time
    now = _now_local().replace(tzinfo=None)
    thermal = thermal.copy()
    thermal["_delta"] = (thermal["timestamp_local"] - now).abs()
    latest = thermal.sort_values("_delta").groupby("ward_id", as_index=False).first()

    def _f(value) -> float | None:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if out == out else None  # NaN guard

    summary_rows = [
        {
            "zone_id": f"ward-{int(row.ward_id)}",
            "zone_name": row.ward_name,
            "lat": _f(row.lat),
            "lon": _f(row.lon),
            "timestamp_local": pd.Timestamp(row.timestamp_local).strftime("%Y-%m-%dT%H:%M"),
            "temp_c": _f(row.temp_c),
            "rh_pct": _f(row.rh_pct),
            "wind_kmh": _f(row.wind_kmh),
            "wbgt_c": _f(row.wbgt_c),
            "heat_index_c": _f(row.heat_index_c),
            "stress_band": str(row.stress_band),
            "pm25_ugm3": None,
            "aqi_india": None,
            "aqi_band": "Unavailable",
            "heat_multiplier": None,
            "heat_aqi_load": None,
            "heat_aqi_load_band": "Unavailable",
            "is_synthetic": False,
            "data_source": source_label,
        }
        for row in latest.itertuples()
    ]

    # --- heatwave status: IMD coastal ABSOLUTE rule + two-day persistence
    daily = daily.sort_values(["ward_id", "date"]).copy()
    daily["hot_day"] = daily["tmax_c"] >= 37.0
    daily["severe_day"] = daily["tmax_c"] >= 40.0
    daily["_run"] = daily.groupby("ward_id")["hot_day"].transform(lambda s: s.ne(s.shift()).cumsum())
    run_len = daily.groupby(["ward_id", "_run"])["hot_day"].transform("sum")
    daily["episode"] = daily["hot_day"] & (run_len >= 2)
    daily["heatwave_label"] = "None"
    daily.loc[daily["hot_day"] & ~daily["episode"], "heatwave_label"] = "Hot-day watch"
    daily.loc[daily["episode"], "heatwave_label"] = "Heat Wave"
    daily.loc[daily["episode"] & daily["severe_day"], "heatwave_label"] = "Severe Heat Wave"

    merged = daily.merge(
        risk[["ward_id", "date", "risk_score", "risk_band", "exposed_population"]],
        on=["ward_id", "date"], how="left",
    )
    daily_rows = [
        {
            "zone_id": f"ward-{int(row.ward_id)}",
            "zone_name": row.ward_name,
            "date": str(row.date),
            "tmax_c": _f(row.tmax_c),
            "wbgt_peak_c": _f(row.wbgt_peak_c),
            "stress_band": str(row.stress_band),
            "heatwave_label": str(row.heatwave_label),
            "risk_score": _f(row.risk_score),
            "risk_band": str(row.risk_band) if row.risk_band == row.risk_band else "Unavailable",
            "normal_tmax_c": None,
            "departure_c": None,
            "pm25_mean_ugm3": None,
            "aqi_peak": None,
            "aqi_band": "Unavailable",
            "heat_aqi_load_peak": None,
            "heat_aqi_load_band": "Unavailable",
        }
        for row in merged.itertuples()
    ]

    # Alert rows = absolute-rule heatwave days only. A humid WBGT-"Critical"
    # day is real thermal stress (shown on Now/Outlook) but it is NOT a
    # heatwave watch — conflating them would cry wolf every monsoon day.
    alert_frame = daily[daily["hot_day"]]
    alert_rows = [
        {
            "zone_id": f"ward-{int(row.ward_id)}",
            "zone_name": row.ward_name,
            "date": str(row.date),
            "tmax_c": _f(row.tmax_c),
            "normal_tmax_c": None,
            "departure_c": None,
            "heatwave_label": str(row.heatwave_label),
            "is_heatwave_episode": bool(row.episode),
            "is_severe_episode": bool(row.episode and row.severe_day),
            "extreme_temperature_watch": bool(row.severe_day),
            "wbgt_peak_c": _f(row.wbgt_peak_c),
            "stress_band": str(row.stress_band),
            "aqi_peak": None,
            "heat_aqi_load_peak": None,
        }
        for row in alert_frame.itertuples()
    ][:600]

    hottest = max((_f(r["temp_c"]) for r in summary_rows if _f(r["temp_c"]) is not None), default=None)
    peak_wbgt = max((_f(r["wbgt_c"]) for r in summary_rows if _f(r["wbgt_c"]) is not None), default=None)
    wards_in_alert = len({r["zone_id"] for r in alert_rows})

    return {
        "schema_version": 1,
        "source_notice": envelope_notice,
        "summary": {
            "city_profile": "kolkata",
            "static_snapshot": False,
            "is_synthetic": False,
            "data_source": source_label,
            "fallback_reason": "stale cache served offline" if stale else "",
            "city": {
                "timestamp_local": now.strftime("%Y-%m-%dT%H:%M"),
                "zones": len(summary_rows),
                "hottest_temp_c": hottest,
                "highest_aqi": None,
                "highest_heat_aqi_load": None,
                "peak_wbgt_c": peak_wbgt,
                "wards_in_alert": wards_in_alert,
            },
            "data": summary_rows,
        },
        "daily": daily_rows,
        "alerts": {
            "rows": len(alert_rows),
            "climatology": _kolkata_climatology_note(),
            "data": alert_rows,
        },
    }


def _kolkata_climatology_note() -> dict:
    return {
        "available": False,
        "reference_period": None,
        "method": (
            "IMD coastal absolute-temperature rule (Tmax ≥ 37 °C heatwave day, ≥ 40 °C severe) "
            "with two-day persistence. The departure-from-normal rule is deliberately DISABLED "
            "for Kolkata: no fixed per-ward climate normals are bundled, and a forecast-window "
            "mean must never masquerade as a normal."
        ),
    }


# ------------------------------------------------------------------ live layers
# Three additive layers for the operations globe: aircraft, earthquakes and
# satellites. The browser calls /api/live/* and this process fetches the three
# public upstreams (core/live.py), which is what keeps a third-party host out
# of the browser while the globe can still show something live.
#
# Deliberately absent from _CACHEABLE_READS: the response cache cannot tell a
# successful payload from a degraded one, and an "unavailable" replayed for
# another two minutes would outlive the outage that caused it. Successful
# payloads are held briefly inside core/live.py instead, so a burst of
# operators re-opening the globe is one upstream request, not thirty.

@app.get("/live/aircraft")
def live_aircraft(
    lat: float = Query(22.5726, ge=-90, le=90, description="Centre of the search circle"),
    lon: float = Query(88.3639, ge=-180, le=180, description="Centre of the search circle"),
    radius_nm: int = Query(250, ge=10, le=250,
                           description="Radius in nautical miles; adsb.lol accepts up to 250"),
    limit: int = Query(150, ge=1, le=500, description="Most aircraft to return"),
):
    """Live ADS-B traffic around a point, highest first.

    The globe's opt-in layer, not an input to anything: no number on this
    platform is derived from an aircraft position.
    """
    return live_layers.aircraft(lat=lat, lon=lon, radius_nm=radius_nm, limit=limit)


@app.get("/live/earthquakes")
def live_earthquakes(
    window: Literal["hour", "day", "week"] = Query(
        "day", description="USGS summary feed; `month` is deliberately not offered"),
    min_mag: float = Query(2.5, ge=0, le=10, description="Smallest magnitude to return"),
    limit: int = Query(200, ge=1, le=1000, description="Most events to return"),
):
    """USGS events in the last hour/day/week, strongest first."""
    return live_layers.earthquakes(window=window, min_mag=min_mag, limit=limit)


@app.get("/live/satellites")
def live_satellites(
    group: str = Query("stations", description="CelesTrak GP group, e.g. stations, weather, gps-ops"),
    limit: int = Query(60, ge=1, le=300, description="Most element sets to return"),
):
    """CelesTrak GP element sets for one group — positions are propagated in the browser.

    Sending element sets rather than positions is deliberate: where a satellite
    is depends on when you ask, and the globe asks every frame. One element set
    lasts minutes; one position would be wrong immediately and expensive to keep
    right.
    """
    if group not in live_layers.SATELLITE_GROUPS:
        # Not a free-form query: `group` reaches CelesTrak's query interface,
        # so the whitelist is the check that keeps this server from being used
        # to ask that host for arbitrary things.
        raise HTTPException(422, f"group must be one of {live_layers.SATELLITE_GROUPS}")
    return live_layers.satellites(group=group, limit=limit)


@app.get("/warnings/advance")
def warnings_advance(
    days: int = Query(config.FORECAST_DAYS + 1, ge=2, le=9,
                      description="Provider window; issue day + 5 target days needs 6"),
    zone_id: str | None = None,
    force_refresh: bool = False,
):
    try:
        return advance_warning_payload(days=days, zone_id=zone_id, force_refresh=force_refresh)
    except KeyError:
        raise HTTPException(404, f"NCR zone '{zone_id}' not found") from None


# ------------------------------------------------------------------ notifications
# Planning + preview only. Real sending stays behind the existing double lock
# (HS_ALLOW_LIVE_SEND + Twilio credentials) in core/alerts.py, and demo or
# synthetic-fallback alerts can never be dispatched live at all.

@app.get("/notifications/preview")
def notifications_preview(
    days: int = Query(config.FORECAST_DAYS + 1, ge=2, le=9),
    zone_id: str | None = None,
):
    """Dry-run notification previews built from real generated warning rows."""
    try:
        payload = advance_warning_payload(days=days, zone_id=zone_id)
    except KeyError:
        raise HTTPException(404, f"NCR zone '{zone_id}' not found") from None
    plan = plan_notifications(payload["data"], is_demo=False)
    return {
        "disclaimer": payload["disclaimer"],
        "data_source": payload["data_source"],
        "is_synthetic": payload["is_synthetic"],
        "quality_state": payload["quality_state"],
        "fallback_reason": payload["fallback_reason"],
        **plan,
    }


class NotifyDispatchIn(BaseModel):
    dry_run: bool = True
    days: int = Field(config.FORECAST_DAYS + 1, ge=1, le=9)
    # An explicit recipient list is capped and normalised before it is trusted.
    to_numbers: list[str] | None = Field(None, max_length=50)

    @property
    def recipients(self) -> list[str] | None:
        return sanitise_phone_list(self.to_numbers)


@app.post("/notifications/dispatch", dependencies=[AdminOnly])
def notifications_dispatch(payload: NotifyDispatchIn):
    """Dispatch planned notifications. Dry-run by default; live send is refused
    unless both opt-in locks are open AND no row is demo/synthetic."""
    plan_payload = advance_warning_payload(days=payload.days)
    plan = plan_notifications(plan_payload["data"], is_demo=False)
    try:
        result = dispatch_previews(plan["previews"], dry_run=payload.dry_run,
                                   to_numbers=payload.recipients)
    except PermissionError as exc:
        # An unsafe live send is a refusal with a readable reason, not a crash.
        return {"dispatched": 0, "dry_run": payload.dry_run, "refused": str(exc)}
    return result


# ------------------------------------------------------------------ Heat Risk Demo
# Fully offline, deterministic, labelled synthetic scenarios. Fixed scenario
# clock (2026-05-18 06:00 IST) so lead times never drift with the review date.

def _demo_scenario_or_404(scenario: str) -> str:
    if scenario not in demo_engine.SCENARIOS:
        raise HTTPException(
            404,
            f"unknown demo scenario '{scenario}' — valid: {', '.join(demo_engine.scenario_ids())}",
        )
    return scenario


@app.get("/demo/scenarios")
def demo_scenarios():
    """Catalogue of demo presets with labels, teaching points and expectations."""
    return demo_engine.scenarios_payload()


@app.get("/demo/zones")
def demo_zones():
    """Demo zone registry: geography, synthetic vulnerability profile, cooling centres."""
    return demo_engine.zones_payload()


@app.get("/demo/forecast")
def demo_forecast(scenario: str = "dry-extreme", zone_id: str | None = None):
    """Deterministic 5-day synthetic forecast with explicit lead times."""
    _demo_scenario_or_404(scenario)
    try:
        return demo_engine.forecast_payload(scenario, zone_id=zone_id)
    except KeyError:
        raise HTTPException(404, f"demo zone '{zone_id}' not found") from None


@app.get("/demo/thermal")
def demo_thermal(scenario: str = "dry-extreme", zone_id: str | None = None):
    """HTSI detail for a scenario: Heat Index, estimated WBGT, quality flags."""
    _demo_scenario_or_404(scenario)
    try:
        return demo_engine.thermal_payload(scenario, zone_id=zone_id)
    except KeyError:
        raise HTTPException(404, f"demo zone '{zone_id}' not found") from None


@app.get("/demo/warnings")
def demo_warnings(scenario: str = "dry-extreme", zone_id: str | None = None):
    """Advance-warning rows (lead 0–5) for a scenario — same contract as live."""
    _demo_scenario_or_404(scenario)
    try:
        return demo_engine.warnings_payload(scenario, zone_id=zone_id)
    except KeyError:
        raise HTTPException(404, f"demo zone '{zone_id}' not found") from None


@app.get("/demo/notifications")
def demo_notifications(scenario: str = "dry-extreme"):
    """Dry-run notification previews for a scenario. Nothing is ever sent."""
    _demo_scenario_or_404(scenario)
    return demo_engine.notifications_payload(scenario)


# ------------------------------------------------------------------ Phase 2
def _thermal_frame():
    return compute_thermal(get_forecast())


@app.get("/thermal")
def thermal(
    hours: int = Query(24, ge=1, le=24 * 16),
    ward_id: Annotated[int | None, Query(ge=1, le=WARD_MAX)] = None,
    peak_only: bool = False,
):
    """Hourly WBGT + Heat Index + stress band per ward."""
    df = _thermal_frame()
    cutoff = df["timestamp_local"].min() + pd.Timedelta(hours=hours)
    df = df[df["timestamp_local"] <= cutoff]
    if ward_id is not None:
        df = df[df["ward_id"] == ward_id]
        if df.empty:
            raise HTTPException(404, f"ward_id {ward_id} not found")
    if peak_only:
        df = df.loc[df.groupby("ward_id")["wbgt_c"].idxmax()]

    out = df.copy()
    out["timestamp_local"] = out["timestamp_local"].dt.strftime("%Y-%m-%dT%H:%M")
    out["fetched_at"] = out["fetched_at"].astype(str)
    return {"rows": len(out), "data": out.to_dict(orient="records")}


@app.get("/thermal/daily")
def thermal_daily(region: Literal["coastal", "plains", "hills"] = "coastal"):
    """Daily peak WBGT / HI per ward + IMD heatwave flags. The Phase 3+4 input."""
    d = heatwave_flags(daily_thermal(get_forecast()), region=region)
    d["date"] = d["date"].astype(str)
    return {"rows": len(d), "region": region, "data": d.to_dict(orient="records")}


@app.get("/thermal/ward/{ward_id}")
def thermal_ward(
    ward_id: Annotated[int, Path(ge=1, le=WARD_MAX)],
    intensity: Annotated[str, Query(pattern="^(light|moderate|heavy|very_heavy)$")] = "moderate",
):
    """Single-ward summary: today's peak, band, guidance, work/rest rule."""
    df = _thermal_frame()
    w = df[df["ward_id"] == ward_id]
    if w.empty:
        raise HTTPException(404, f"ward_id {ward_id} not found")

    peak = w.loc[w["wbgt_c"].idxmax()]
    now = w.iloc[0]
    cls = classify_wbgt(peak["wbgt_c"])
    return {
        "ward_id": int(ward_id),
        "ward_name": peak["ward_name"],
        "peak": {
            "timestamp_local": peak["timestamp_local"].strftime("%Y-%m-%dT%H:%M"),
            "temp_c": float(peak["temp_c"]),
            "rh_pct": float(peak["rh_pct"]),
            "wet_bulb_c": float(peak["wet_bulb_c"]),
            "globe_c": float(peak["globe_c"]),
            "wbgt_c": float(peak["wbgt_c"]),
            "heat_index_c": float(peak["heat_index_c"]),
        },
        "latest": {
            "timestamp_local": now["timestamp_local"].strftime("%Y-%m-%dT%H:%M"),
            "temp_c": float(now["temp_c"]),
            "wbgt_c": float(now["wbgt_c"]),
            "heat_index_c": float(now["heat_index_c"]),
        },
        "band": cls["band"],
        "colour": cls["colour"],
        "guidance": cls["guidance"],
        "work_rest": work_rest(peak["wbgt_c"], intensity),
    }


# ------------------------------------------------------------------ Phase 3
@app.get("/risk/daily")
def risk_daily(
    scenario_c: Annotated[float, Query(ge=SCENARIO_MIN, le=SCENARIO_MAX)] = 0.0,
):
    """Ward-day risk: peak risk score, band, exposure, excess-death estimate.

    `scenario_c` stress-tests the model (e.g. +6 for a heatwave what-if).
    """
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c)
    d["date"] = d["date"].astype(str)
    return {"rows": len(d), "scenario_c": scenario_c, "data": d.to_dict(orient="records")}


@app.get("/risk/ranking")
def risk_ranking(
    scenario_c: Annotated[float, Query(ge=SCENARIO_MIN, le=SCENARIO_MAX)] = 0.0,
    date: Annotated[str | None, Query(pattern=DATE_PATTERN)] = None,
):
    """
    League table, worst first, for the peak day in the window.

    Defaults to the worst upcoming day rather than the last one — the map should
    show the coming heatwave, matching what /alerts/plan is warning about.
    Pass ?date=YYYY-MM-DD to pin a specific day.
    """
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c)
    r = ward_ranking(d, date=date)
    chosen = str(r["date"].iloc[0]) if len(r) else None
    counts = r["risk_band"].value_counts().to_dict()
    return {"date": chosen, "scenario_c": scenario_c,
            "band_counts": counts, "data": r.to_dict(orient="records")}


@app.get("/risk/ward/{ward_id}")
def risk_ward(
    ward_id: Annotated[int, Path(ge=1, le=WARD_MAX)],
    scenario_c: Annotated[float, Query(ge=SCENARIO_MIN, le=SCENARIO_MAX)] = 0.0,
):
    """Single-ward risk summary for the detail panel / mobile view."""
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c)
    w = d[d["ward_id"] == ward_id]
    if w.empty:
        raise HTTPException(404, f"ward_id {ward_id} not found")

    row = w.loc[w["risk_score"].idxmax()]
    band, colour = risk_band(row["risk_score"])
    return {
        "ward_id": int(ward_id),
        "ward_name": row["ward_name"],
        "date": str(row["date"]),
        "risk_score": float(row["risk_score"]),
        "risk_band": band,
        "risk_colour": colour,
        "drivers": {
            "wbgt_peak_c": float(row["wbgt_peak_c"]),
            "hazard_score": float(row["hazard_score"]),
            "vulnerability": float(row["vulnerability"]),
            "uhi_delta_c": float(row["uhi_delta_c"]),
            "tmax_ward_c": float(row["tmax_adj_c"]),
        },
        "impact": {
            "population": int(row["population"]),
            "exposed_population": int(row["exposed_population"]),
            "relative_risk": float(row["relative_risk"]),
            "excess_deaths_per_day": float(row["excess_deaths_per_day"]),
        },
    }


@app.get("/risk")
def risk(
    hours: Annotated[int, Query(ge=1, le=24 * 16)] = 24,
    ward_id: Annotated[int | None, Query(ge=1, le=WARD_MAX)] = None,
    scenario_c: Annotated[float, Query(ge=SCENARIO_MIN, le=SCENARIO_MAX)] = 0.0,
):
    """Hourly ward-level risk scores."""
    df = compute_risk(get_forecast(), temp_offset_c=scenario_c)
    if ward_id is not None and ward_id not in set(df["ward_id"]):
        raise HTTPException(404, f"ward_id {ward_id} not found")
    df = _window(df, hours, ward_id)
    out = df.copy()
    out["timestamp_local"] = out["timestamp_local"].dt.strftime("%Y-%m-%dT%H:%M")
    out["fetched_at"] = out["fetched_at"].astype(str)
    return {"rows": len(out), "scenario_c": scenario_c, "data": out.to_dict(orient="records")}


# ------------------------------------------------------------------ Phase 5
@app.get("/alerts/plan")
def alerts_plan(
    threshold: Annotated[float, Query(ge=0, le=100)] = DEFAULT_RISK_THRESHOLD,
    lead_days: Annotated[int, Query(ge=0, le=7)] = DEFAULT_MIN_LEAD_DAYS,
    scenario_c: Annotated[float, Query(ge=SCENARIO_MIN, le=SCENARIO_MAX)] = 0.0,
    only_unsent: bool = False,
):
    """
    Who WOULD be warned, and with how much lead time. Sends nothing.

    `lead_days=1` means "at least one full day before the event" — crossings that
    are today or in the past are excluded, because the intervention window has
    closed. `only_unsent=True` filters out anything already dispatched recently.
    """
    daily = daily_risk(get_forecast(), temp_offset_c=scenario_c)
    events = find_upcoming_events(daily, min_lead_days=lead_days, risk_threshold=threshold)
    pending = filter_already_sent(events)
    active = find_active_now(daily, risk_threshold=threshold)

    shown = pending if only_unsent else events
    records = []
    for r in shown.to_dict("records"):
        r = dict(r)
        # compose BEFORE stringifying: compose_message formats the date object
        r["message"] = compose_message(r)
        r["event_date"] = str(r["event_date"])
        r["already_sent"] = r["ward_id"] not in set(pending["ward_id"]) if not pending.empty else True
        records.append(r)

    return {
        "threshold": threshold,
        "min_lead_days": lead_days,
        "scenario_c": scenario_c,
        "total_events": int(len(events)),
        "pending_after_dedupe": int(len(pending)),
        # wards already inside the event: a nowcast, not a warning
        "active_now": int(len(active)),
        "active_wards": [str(w) for w in active["ward_name"].head(12)] if len(active) else [],
        "data": records,
    }


class DispatchIn(BaseModel):
    threshold: float = Field(DEFAULT_RISK_THRESHOLD, ge=0, le=100)
    lead_days: int = Field(DEFAULT_MIN_LEAD_DAYS, ge=0, le=7)
    dry_run: bool = True
    to_numbers: list[str] | None = Field(None, max_length=50)
    # resolve recipients per ward from the subscriber registry
    per_ward: bool = True

    @property
    def recipients(self) -> list[str] | None:
        return sanitise_phone_list(self.to_numbers)

class SubscriberIn(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    ward_id: int = Field(0, ge=0, le=WARD_MAX)   # 0 = citywide
    name: str = Field("", max_length=200)
    role: str = "resident"

class StopIn(BaseModel):
    phone: str = Field(min_length=8, max_length=20)


@app.post("/alerts/dispatch", dependencies=[AdminOnly])
def alerts_dispatch(payload: DispatchIn):
    """Dispatch alerts. Defaults to dry-run; set dry_run=false to actually send."""
    daily = daily_risk(get_forecast())
    events = find_upcoming_events(daily, min_lead_days=payload.lead_days,
                                 risk_threshold=payload.threshold)
    pending = filter_already_sent(events)
    if pending.empty:
        return {"dispatched": 0, "message": "no new events with sufficient lead time"}
    try:
        log = dispatch(pending, dry_run=payload.dry_run,
                       to_numbers=payload.recipients, per_ward=payload.per_ward)
    except PermissionError as exc:
        # Refusing an unsafe live send is a 403, not a crash.
        return {"dispatched": 0, "dry_run": payload.dry_run, "refused": str(exc)}
    return {
        "dispatched": int(len(log)),
        "dry_run": payload.dry_run,
        "per_ward": payload.per_ward,
        "status_counts": log["status"].value_counts().to_dict(),
        "records": log[["ward_id", "ward_name", "event_date", "lead_days",
                        "risk_score", "risk_band", "status"]].to_dict(orient="records"),
    }


# --------------------------------------------------------- Phase 5b: registry
@app.get("/subscribers", dependencies=[AdminOnly])
def subscribers_list(
    ward_id: Annotated[int | None, Query(ge=0, le=WARD_MAX)] = None,
):
    """Registry contents for operators. `?ward_id=N` filters to that ward (+ citywide).

    Phone numbers are **redacted** here (`+91••••••3210`): dispatch resolves the
    real numbers server-side, so no browser ever needs them, and a list of every
    resident's number is the single most valuable thing on this API. The
    administrative gate in front of the route is the second layer, not the first.
    """
    df = load_registry()
    stats = registry_stats()
    if df.empty:
        return {"count": 0, "stats": stats, "data": []}
    if ward_id is not None:
        df = df[(df["ward_id"] == ward_id) | (df["ward_id"] == 0)]
    out = df.copy()
    out["phone"] = out["phone"].map(redact_phone)
    out["opted_out"] = out["opted_out"].astype(bool)
    out = out.astype(object).where(pd.notna(out), None)
    return {"count": int(len(out)), "stats": stats, "data": out.to_dict(orient="records")}


@app.get("/subscribers/stats")
def subscribers_stats():
    """Aggregate counts only — no personal data, so this one stays public."""
    return registry_stats()


@app.post("/subscribers", dependencies=[AdminOnly])
def subscribers_add(payload: SubscriberIn):
    result = reg_add(payload.phone, payload.ward_id, payload.name, payload.role)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    result["stats"] = registry_stats()
    return result


@app.post("/subscribers/stop", dependencies=[AdminOnly])
def subscribers_stop(payload: StopIn):
    """STOP. Never fails loudly — silence is the requested outcome.

    Gated because without it anybody could silence anybody's heat warnings by
    posting their number: a denial-of-warnings attack against a life-safety
    system. Real STOP handling arrives as an inbound SMS webhook, which is the
    only place a phone number proves it belongs to the sender.
    """
    result = reg_opt_out(payload.phone)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    result["stats"] = registry_stats()
    return result


@app.get("/subscribers/for-ward/{ward_id}", dependencies=[AdminOnly])
def subscribers_for_ward(ward_id: Annotated[int, Path(ge=0, le=WARD_MAX)]):
    """Recipient numbers for one ward — redacted, for operator auditing."""
    return {"ward_id": ward_id,
            "recipients": [redact_phone(n) for n in recipients_for_ward(ward_id)]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
