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
from core.alerts import (DEFAULT_MIN_LEAD_DAYS, DEFAULT_RISK_THRESHOLD,
                         compose_message, dispatch, filter_already_sent,
                         find_active_now, find_upcoming_events)
from core.config import DRILL_PROFILES
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
        ],
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
def _drill(drill: str | None) -> str | None:
    if drill is not None and drill not in DRILL_PROFILES:
        raise HTTPException(400, f"unknown drill '{drill}'")
    return drill

@app.get("/risk/daily")
def risk_daily(scenario_c: float = 0.0, drill: str | None = None):
    """Ward-day risk: peak risk score, band, exposure, excess-death estimate.

    `scenario_c` stress-tests the model (e.g. +6 for a heatwave what-if).
    """
    drill = _drill(drill)
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c, drill=drill)
    d["date"] = d["date"].astype(str)
    return {"rows": len(d), "scenario_c": scenario_c, "drill": drill, "data": d.to_dict(orient="records")}


@app.get("/risk/ranking")
def risk_ranking(scenario_c: float = 0.0, date: str | None = None, drill: str | None = None):
    """
    League table, worst first, for the peak day in the window.

    Defaults to the worst upcoming day rather than the last one — the map should
    show the coming heatwave, matching what /alerts/plan is warning about.
    Pass ?date=YYYY-MM-DD to pin a specific day.
    """
    drill = _drill(drill)
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c, drill=drill)
    r = ward_ranking(d, date=date)
    chosen = str(r["date"].iloc[0]) if len(r) else None
    counts = r["risk_band"].value_counts().to_dict()
    return {"date": chosen, "scenario_c": scenario_c, "drill": drill,
            "band_counts": counts, "data": r.to_dict(orient="records")}


@app.get("/risk/ward/{ward_id}")
def risk_ward(ward_id: int, scenario_c: float = 0.0, drill: str | None = None):
    """Single-ward risk summary for the detail panel / mobile view."""
    drill = _drill(drill)
    d = daily_risk(get_forecast(), temp_offset_c=scenario_c, drill=drill)
    w = d[d["ward_id"] == ward_id]
    if w.empty:
        raise HTTPException(404, f"ward_id {ward_id} not found")

    row = w.loc[w["risk_score"].idxmax()]
    band, colour = risk_band(row["risk_score"])
    return {
        "ward_id": int(ward_id),
        "drill": drill,
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
         scenario_c: float = 0.0, drill: str | None = None):
    """Hourly ward-level risk scores."""
    drill = _drill(drill)
    df = compute_risk(get_forecast(), temp_offset_c=scenario_c, drill=drill)
    if ward_id is not None and ward_id not in set(df["ward_id"]):
        raise HTTPException(404, f"ward_id {ward_id} not found")
    df = _window(df, hours, ward_id)
    out = df.copy()
    out["timestamp_local"] = out["timestamp_local"].dt.strftime("%Y-%m-%dT%H:%M")
    out["fetched_at"] = out["fetched_at"].astype(str)
    return {"rows": len(out), "scenario_c": scenario_c, "drill": drill, "data": out.to_dict(orient="records")}


# ------------------------------------------------------------------ Phase 5
@app.get("/alerts/plan")
def alerts_plan(
    threshold: float = DEFAULT_RISK_THRESHOLD,
    lead_days: int = DEFAULT_MIN_LEAD_DAYS,
    scenario_c: float = 0.0,
    drill: str | None = None,
    only_unsent: bool = False,
):
    """
    Who WOULD be warned, and with how much lead time. Sends nothing.

    `lead_days=1` means "at least one full day before the event" — crossings that
    are today or in the past are excluded, because the intervention window has
    closed. `only_unsent=True` filters out anything already dispatched recently.
    """
    drill = _drill(drill)
    daily = daily_risk(get_forecast(), temp_offset_c=scenario_c, drill=drill)
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
        "drill": drill,
        "total_events": int(len(events)),
        "pending_after_dedupe": int(len(pending)),
        # wards already inside the event: a nowcast, not a warning
        "active_now": int(len(active)),
        "active_wards": [str(w) for w in active["ward_name"].head(12)] if len(active) else [],
        "data": records,
    }


@app.get("/risk/drill")
def risk_drill(drill: str = "heatwave"):
    """Operator drill summary for the dashboard's simulation readout."""
    drill = _drill(drill)
    base = daily_risk(get_forecast(), drill=drill)
    plus = daily_risk(get_forecast(), temp_offset_c=1.0, drill=drill)
    minus = daily_risk(get_forecast(), temp_offset_c=-1.0, drill=drill)
    threshold = DEFAULT_RISK_THRESHOLD
    events = find_upcoming_events(base, min_lead_days=1, risk_threshold=threshold)
    def decisions(frame):
        return set(zip(frame.loc[frame.risk_score >= threshold, "ward_id"],
                       frame.loc[frame.risk_score >= threshold, "date"]))
    stable = decisions(base)
    compared = decisions(plus) | decisions(minus)
    lead = (pd.to_datetime(events["event_date"]) - pd.Timestamp.now().normalize()).dt.days if len(events) else pd.Series(dtype=float)
    plus_events = find_upcoming_events(plus, 1, threshold)
    minus_events = find_upcoming_events(minus, 1, threshold)
    # A score delta, rather than only a queue count, makes the sensitivity
    # useful even when a one-degree perturbation does not cross the threshold.
    score_delta = (plus["risk_score"] - minus["risk_score"]).abs().mean() / 2
    profile = DRILL_PROFILES[drill]
    lead_stats = {
        "min_days": int(lead.min()) if len(lead) else None,
        "mean_days": round(float(lead.mean()), 1) if len(lead) else None,
        "max_days": int(lead.max()) if len(lead) else None,
        "median_days": round(float(lead.median()), 1) if len(lead) else None,
    }
    return {
        "drill": drill,
        "profile": {
            "label": profile["label"],
            "description": profile["description"],
        },
        "warnings": {"wards_queued": int(len(events)),
                     "events": events[["ward_id", "ward_name", "event_date", "lead_days",
                                       "risk_score"]].to_dict(orient="records") if len(events) else []},
        "accuracy": {
            "decision_stability_pct": round(
                100 * len(stable & decisions(plus) & decisions(minus)) / (len(compared) or 1), 1
            ),
        },
        "lead_time": lead_stats,
        "sensitivity": {
            "minus_1c_events": int(len(minus_events)),
            "base_events": int(len(events)),
            "plus_1c_events": int(len(plus_events)),
            "risk_points_per_degree": round(float(score_delta), 2),
        },
        "peak_anomaly_c": float(max(profile["anomalies_c"])),
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
