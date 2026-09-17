"""
HeatShield API — FastAPI skeleton (Phase 1).
Endpoints grow each phase: /thermal (P2), /risk (P3), /alerts (P5).

Run:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

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
from core.thermal import classify_wbgt, compute_thermal, daily_thermal, heatwave_flags, work_rest
from core.weather import daily_peak, get_forecast, load_wards

app = FastAPI(
    title="HeatShield API",
    version="0.1.0",
    description="Extreme Heatwave Early Warning & Human Thermal Stress Index",
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


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
    ward_id: int | None = None,
    use_cache: bool = True,
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
    days: int = config.FORECAST_DAYS + 1
    to_numbers: list[str] | None = None


@app.post("/notifications/dispatch")
def notifications_dispatch(payload: NotifyDispatchIn):
    """Dispatch planned notifications. Dry-run by default; live send is refused
    unless both opt-in locks are open AND no row is demo/synthetic."""
    plan_payload = advance_warning_payload(days=payload.days)
    plan = plan_notifications(plan_payload["data"], is_demo=False)
    try:
        result = dispatch_previews(plan["previews"], dry_run=payload.dry_run,
                                   to_numbers=payload.to_numbers)
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
    ward_id: int | None = None,
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
def thermal_daily(region: str = "coastal"):
    """Daily peak WBGT / HI per ward + IMD heatwave flags. The Phase 3+4 input."""
    d = heatwave_flags(daily_thermal(get_forecast()), region=region)
    d["date"] = d["date"].astype(str)
    return {"rows": len(d), "region": region, "data": d.to_dict(orient="records")}


@app.get("/thermal/ward/{ward_id}")
def thermal_ward(ward_id: int, intensity: str = "moderate"):
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
def risk_daily(scenario_c: float = 0.0):
    """Ward-day risk: peak risk score, band, exposure, excess-death estimate.

    `scenario_c` stress-tests the model (e.g. +6 for a heatwave what-if).
    """
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c)
    d["date"] = d["date"].astype(str)
    return {"rows": len(d), "scenario_c": scenario_c, "data": d.to_dict(orient="records")}


@app.get("/risk/ranking")
def risk_ranking(scenario_c: float = 0.0, date: str | None = None):
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
def risk_ward(ward_id: int, scenario_c: float = 0.0):
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
def risk(hours: int = Query(24, ge=1, le=24 * 16), ward_id: int | None = None,
         scenario_c: float = 0.0):
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
    threshold: float = DEFAULT_RISK_THRESHOLD,
    lead_days: int = DEFAULT_MIN_LEAD_DAYS,
    scenario_c: float = 0.0,
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
    threshold: float = DEFAULT_RISK_THRESHOLD
    lead_days: int = DEFAULT_MIN_LEAD_DAYS
    dry_run: bool = True
    to_numbers: list[str] | None = None
    # resolve recipients per ward from the subscriber registry
    per_ward: bool = True

class SubscriberIn(BaseModel):
    phone: str
    ward_id: int = 0            # 0 = citywide
    name: str = ""
    role: str = "resident"

class StopIn(BaseModel):
    phone: str


@app.post("/alerts/dispatch")
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
                       to_numbers=payload.to_numbers, per_ward=payload.per_ward)
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
@app.get("/subscribers")
def subscribers_list(ward_id: int | None = None):
    """Registry contents. `?ward_id=N` filters to that ward (+ citywide)."""
    df = load_registry()
    if df.empty:
        return {"count": 0, "stats": registry_stats(), "data": []}
    if ward_id is not None:
        df = df[(df["ward_id"] == ward_id) | (df["ward_id"] == 0)]
    out = df.copy()
    out["opted_out"] = out["opted_out"].astype(bool)
    return {"count": int(len(out)), "stats": registry_stats(), "data": out.to_dict(orient="records")}


@app.get("/subscribers/stats")
def subscribers_stats():
    return registry_stats()


@app.post("/subscribers")
def subscribers_add(payload: SubscriberIn):
    result = reg_add(payload.phone, payload.ward_id, payload.name, payload.role)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    result["stats"] = registry_stats()
    return result


@app.post("/subscribers/stop")
def subscribers_stop(payload: StopIn):
    """STOP. Never fails loudly — silence is the requested outcome."""
    result = reg_opt_out(payload.phone)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    result["stats"] = registry_stats()
    return result


@app.get("/subscribers/for-ward/{ward_id}")
def subscribers_for_ward(ward_id: int):
    return {"ward_id": ward_id, "recipients": recipients_for_ward(ward_id)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
