"""
ADVANCE HEAT-HEALTH WARNING PIPELINE (lead times 0–5 days)
==========================================================
Turns an hourly zone frame into one operational warning row per zone and
target date, with every field an early-warning product needs:

    forecast issuance time · target date · lead time in days AND hours ·
    heatwave candidate / persistent-episode status (IMD plains rule against
    the FIXED 1991–2020 normals, two-day persistence) · thermal-stress level
    (HTSI, core/htsi.py) · vulnerability level (separately sourced and
    labelled) · health-impact indicator status (never "validated" without
    evidence) · recommended action level with municipal + resident actions ·
    data source and quality state.

This module is deliberately the ONLY place that assembles those rows, so the
demo (``core/demo.py``) and the live NCR route (``/warnings/advance``) can
never drift apart in contract. Provider outages are handled upstream by
``core.coupled._ncr_frame`` — a warning route built on it returns labelled
synthetic data instead of HTTP 500.

Vulnerability profiles below are SYNTHETIC, labelled on every row: the repo
has no observed zone-level demographic feed for the NCR demo zones. They
exist so the full decision chain (stress → vulnerability → impact → action)
can be exercised and reviewed; replacing them with a municipal GIS/Census
feed is a data task, not a code change.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from core import config
from core.coupled import (
    _ncr_frame,
    detect_heatwaves,
    load_climatology,
    ncr_daily,
)
from core.health_impact import (
    STATUS_PARAMETERISED,
    health_impact_band,
    health_impact_index,
    resolve_model_status,
)
from core.htsi import (
    ASSUMPTION_NO_ANOMALY,
    HTSI_METADATA,
    QUALITY_DEFINITIONS,
    compute_htsi_frame,
    daily_htsi,
    htsi_band,
    htsi_score,
)

# --------------------------------------------------------------------------- #
# 1. Alert levels and the operational action matrix
# --------------------------------------------------------------------------- #

ALERT_LEVELS: tuple[str, ...] = ("routine", "watch", "warning", "severe")

# Canonical honesty sentence for every demo surface, message and payload.
# Defined once here so core/demo.py and core/notify.py can never drift apart
# on the exact wording the truthfulness rules require.
DEMO_DISCLAIMER = "Demo / synthetic scenario — not a live forecast or observation."

# Operational recommendations per level. Text labels carry the meaning;
# colour is decoration and never the only channel.
ACTION_MATRIX: dict[str, dict[str, Any]] = {
    "routine": {
        "colour": "#3fb950",
        "summary": "Routine summer monitoring — no impact-based escalation.",
        "municipal_actions": [
            "Keep public water points and shade shelters maintained",
            "Monitor the daily forecast update for trend changes",
        ],
        "resident_advice": [
            "Stay hydrated and use shade during the hottest hours",
        ],
    },
    "watch": {
        "colour": "#e3b341",
        "summary": "Heat is building — prepare, do not activate yet.",
        "municipal_actions": [
            "Review cooling-centre readiness (power, water, staffing)",
            "Brief field staff and municipal health workers on the outlook",
            "Pre-position ORS and drinking water in high-vulnerability zones",
            "Share the 3–5 day outlook with the power utility demand desk",
        ],
        "resident_advice": [
            "Plan outdoor work and play for morning or evening",
            "Keep water with you and check on elderly neighbours",
        ],
    },
    "warning": {
        "colour": "#f0883e",
        "summary": "Dangerous heat expected — municipal heat actions activate.",
        "municipal_actions": [
            "Open or extend cooling-centre hours (at least 11:00–17:00)",
            "Shift outdoor work hours: avoid 12:00–15:00 for municipal labour",
            "Issue hydration and shade advisories through ward offices",
            "Activate community health-worker checks on elderly and outdoor workers",
            "Prepare ambulance and health-facility heat surge capacity",
            "Coordinate with electricity operations on peak-demand response",
        ],
        "resident_advice": [
            "Avoid the sun between 12:00 and 15:00",
            "Wear light clothing, drink water before you feel thirsty",
            "Watch for cramps, dizziness or nausea — move to shade and rehydrate",
            "Check on elderly relatives, pregnant people and outdoor workers",
        ],
    },
    "severe": {
        "colour": "#f85149",
        "summary": "Life-threatening heat — emergency coordination.",
        "municipal_actions": [
            "Run cooling centres on extended or 24-hour schedules",
            "Suspend non-essential outdoor work 11:00–16:00 across municipal projects",
            "Deploy emergency water and shade points at labour gathering spots",
            "Door-to-door wellness checks in high-vulnerability blocks",
            "Pre-position ambulances; activate hospital heat-illness surge plans",
            "Open joint municipal + disaster-management control room",
            "Trigger power emergency protocols for peak demand",
        ],
        "resident_advice": [
            "Stay in the coolest room you can, especially 12:00–16:00",
            "Visit a cooling centre if your home is unbearable",
            "Never leave anyone — or a pet — in a parked vehicle",
            "Confusion, fainting or hot dry skin is an emergency: seek medical help now",
        ],
    },
}

VULNERABILITY_BANDS = ((0.0, "Low"), (33.0, "Moderate"), (66.0, "High"))

# --------------------------------------------------------------------------- #
# 2. Synthetic zone vulnerability profiles (labelled on every payload)
# --------------------------------------------------------------------------- #

ZONE_PROFILE_SOURCE = (
    "synthetic demo profile — illustrative planning placeholders, NOT observed "
    "census or municipal values for these zones"
)

# Values chosen to be plausible and deterministic. Replacing this table with a
# real municipal feed is the documented upgrade path (README, DATA.md).
_ZONE_PROFILE_TABLE: tuple[dict[str, Any], ...] = (
    {"zone_id": "central-delhi", "population": 412_000, "pop_density_km2": 27_500,
     "elderly_pct": 9.8, "outdoor_worker_pct": 38.0, "illiteracy_pct": 21.0,
     "cooling_centre_count": 4, "cooling_access_score": 62.0},
    {"zone_id": "north-delhi", "population": 580_000, "pop_density_km2": 21_800,
     "elderly_pct": 8.9, "outdoor_worker_pct": 41.0, "illiteracy_pct": 24.0,
     "cooling_centre_count": 3, "cooling_access_score": 51.0},
    {"zone_id": "east-delhi", "population": 496_000, "pop_density_km2": 24_200,
     "elderly_pct": 9.2, "outdoor_worker_pct": 40.0, "illiteracy_pct": 23.0,
     "cooling_centre_count": 2, "cooling_access_score": 44.0},
    {"zone_id": "south-delhi", "population": 625_000, "pop_density_km2": 15_900,
     "elderly_pct": 10.6, "outdoor_worker_pct": 31.0, "illiteracy_pct": 16.0,
     "cooling_centre_count": 5, "cooling_access_score": 68.0},
    {"zone_id": "noida", "population": 380_000, "pop_density_km2": 18_700,
     "elderly_pct": 8.4, "outdoor_worker_pct": 36.0, "illiteracy_pct": 19.0,
     "cooling_centre_count": 3, "cooling_access_score": 57.0},
    {"zone_id": "greater-noida", "population": 295_000, "pop_density_km2": 9_800,
     "elderly_pct": 7.6, "outdoor_worker_pct": 33.0, "illiteracy_pct": 18.0,
     "cooling_centre_count": 2, "cooling_access_score": 49.0},
    {"zone_id": "gurugram", "population": 542_000, "pop_density_km2": 20_100,
     "elderly_pct": 8.1, "outdoor_worker_pct": 35.0, "illiteracy_pct": 17.0,
     "cooling_centre_count": 4, "cooling_access_score": 60.0},
    {"zone_id": "faridabad", "population": 468_000, "pop_density_km2": 16_400,
     "elderly_pct": 8.7, "outdoor_worker_pct": 43.0, "illiteracy_pct": 25.0,
     "cooling_centre_count": 2, "cooling_access_score": 41.0},
)

# Deterministic cooling-centre placeholder sites, offsets from the zone point.
_COOLING_OFFSETS: tuple[tuple[float, float], ...] = (
    (0.011, -0.008), (-0.013, 0.010), (0.006, 0.014), (-0.009, -0.012), (0.016, 0.004),
)

VULNERABILITY_WEIGHTS = {
    "pop_density_km2": 0.30,
    "elderly_pct": 0.22,
    "outdoor_worker_pct": 0.20,
    "cooling_access_deficit": 0.16,   # 1 - cooling_access_score/100
    "illiteracy_pct": 0.12,
}

VULNERABILITY_FORMULA = (
    "vulnerability = 100 · (0.30·norm(pop_density) + 0.22·norm(elderly_pct) "
    "+ 0.20·norm(outdoor_worker_pct) + 0.16·(1 − cooling_access/100) "
    "+ 0.12·norm(illiteracy_pct)); norm() is min–max across the demo zone set. "
    "Inputs are a SYNTHETIC labelled profile (see zone_profiles source)."
)


def _minmax(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    span = arr.max() - arr.min()
    return (arr - arr.min()) / span if span else np.zeros_like(arr)


def zone_profiles() -> pd.DataFrame:
    """Synthetic-but-labelled vulnerability profile per demo/NCR zone."""
    from core.coupled import ncr_zones

    df = pd.DataFrame(_ZONE_PROFILE_TABLE)
    df = df.merge(ncr_zones()[["zone_id", "zone_name", "lat", "lon"]], on="zone_id", how="left")
    deficits = 1.0 - df["cooling_access_score"].to_numpy(dtype=float) / 100.0
    parts = {
        "pop_density_km2": _minmax(df["pop_density_km2"]),
        "elderly_pct": _minmax(df["elderly_pct"]),
        "outdoor_worker_pct": _minmax(df["outdoor_worker_pct"]),
        "cooling_access_deficit": deficits,           # already 0–1
        "illiteracy_pct": _minmax(df["illiteracy_pct"]),
    }
    score = sum(VULNERABILITY_WEIGHTS[key] * parts[key] for key in VULNERABILITY_WEIGHTS)
    df["vulnerability_score"] = np.round(score * 100.0, 1)
    df["vulnerability_level"] = [vulnerability_level(v) for v in df["vulnerability_score"]]
    df["vulnerability_source"] = ZONE_PROFILE_SOURCE

    centres: list[list[dict[str, Any]]] = []
    for row in df.itertuples(index=False):
        centres.append([
            {
                "name": f"{row.zone_name} cooling centre {i + 1} (demo placeholder)",
                "lat": round(float(row.lat) + offset[0], 5),
                "lon": round(float(row.lon) + offset[1], 5),
            }
            for i, offset in enumerate(_COOLING_OFFSETS[: int(row.cooling_centre_count)])
        ])
    df["cooling_centres"] = centres
    return df


def zone_profiles_with_geo() -> pd.DataFrame:
    """Alias kept for readability at call sites that emphasise the map layer."""
    return zone_profiles()


def vulnerability_level(score: float | None) -> str:
    if score is None or not math.isfinite(float(score)):
        return "Unavailable"
    value = float(score)
    chosen = VULNERABILITY_BANDS[0][1]
    for lo, name in VULNERABILITY_BANDS:
        if value >= lo:
            chosen = name
    return chosen


# --------------------------------------------------------------------------- #
# 3. Alert-level derivation (thermal + heatwave + air load, documented)
# --------------------------------------------------------------------------- #

_THERMAL_TO_LEVEL = {"Normal": "routine", "Watch": "watch", "Warning": "warning",
                     "Severe": "severe", "Unavailable": "routine"}
_HEATWAVE_TO_LEVEL = {
    "None": "routine",
    "Extreme-temperature watch": "watch",
    "Watch": "watch",
    "Heat Wave": "warning",
    "Severe Heat Wave": "severe",
}
_LOAD_TO_LEVEL = {"Good": "routine", "Satisfactory": "routine", "Moderate": "routine",
                  "Poor": "watch", "Very Poor": "watch", "Severe": "warning", "Unknown": "routine"}


def _max_level(levels: Iterable[str]) -> str:
    best = "routine"
    for level in levels:
        if level in ALERT_LEVELS and ALERT_LEVELS.index(level) > ALERT_LEVELS.index(best):
            best = level
    return best


def derive_alert_level(thermal_band: str, heatwave_label: str, load_band: str) -> tuple[str, list[str]]:
    """Escalation rule, kept explicit so a reviewer can audit any row.

    * thermal stress (HTSI band) and declared heatwave episodes map directly;
    * the joint heat+air load can lift the level one step when severe;
    * if severe air load coincides with thermal >= warning, escalate to severe.
    """
    thermal_level = _THERMAL_TO_LEVEL.get(thermal_band, "routine")
    heatwave_level = _HEATWAVE_TO_LEVEL.get(heatwave_label, "routine")
    load_level = _LOAD_TO_LEVEL.get(load_band, "routine")
    level = _max_level([thermal_level, heatwave_level, load_level])
    if load_band == "Severe" and ALERT_LEVELS.index(thermal_level) >= ALERT_LEVELS.index("warning"):
        level = "severe"
    drivers = [
        f"thermal stress {thermal_band} → {thermal_level}",
        f"heatwave status '{heatwave_label}' → {heatwave_level}",
        f"heat+air load {load_band} → {load_level}",
    ]
    return level, drivers


# --------------------------------------------------------------------------- #
# 4. Row assembly — the ONE contract for demo and live advance warnings
# --------------------------------------------------------------------------- #

LEAD_HOUR_TARGET = 15  # local hour the lead-time clock points at (peak heat)


def _lead_hours(issued_at: pd.Timestamp, target_date: Any) -> int:
    target = pd.Timestamp(target_date).normalize() + pd.Timedelta(hours=LEAD_HOUR_TARGET)
    return int(round((target - issued_at).total_seconds() / 3600.0))


def _reason_text(row: dict[str, Any]) -> str:
    pieces: list[str] = []
    if row.get("tmax_c") is not None:
        normal = row.get("normal_tmax_c")
        dep = row.get("departure_c")
        if normal is not None and dep is not None:
            pieces.append(
                f"Tmax {row['tmax_c']:.1f} °C is {dep:+.1f} °C vs the 1991–2020 normal ({normal:.1f} °C)"
            )
        else:
            pieces.append(f"Tmax {row['tmax_c']:.1f} °C (climate normal unavailable)")
    if row.get("is_heatwave_episode"):
        label = "severe heatwave episode" if row.get("is_severe_episode") else "heatwave episode"
        pieces.append(f"day {row.get('episode_day')} of {row.get('episode_length')} in a declared {label}")
    elif row.get("heatwave_candidate"):
        pieces.append("single-day heatwave candidate (persistence rule not yet met — early watch)")
    if row.get("wbgt_est_peak_c") is not None:
        quality = f", {row.get('wbgt_peak_quality')}" if row.get("wbgt_peak_quality") else ""
        pieces.append(f"estimated WBGT {row['wbgt_est_peak_c']:.1f} °C{quality}")
    if row.get("hi_peak_c") is not None:
        pieces.append(f"heat index {row['hi_peak_c']:.1f} °C")
    if row.get("heat_aqi_load_band") in ("Very Poor", "Severe"):
        pieces.append(f"joint heat+air load {row.get('heat_aqi_load_band')} ({row.get('heat_aqi_load_peak'):.0f})")
    return "; ".join(pieces) or "no significant heat driver detected"


def build_warning_rows(
    hourly_frame: pd.DataFrame,
    *,
    issued_at: pd.Timestamp,
    quality_state: str,
    data_source: str,
    is_demo: bool = False,
    scenario_id: str | None = None,
    climatology: dict[str, Any] | None = None,
    fallback_reason: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble warning rows for every zone and every target date ≥ issue date.

    ``hourly_frame`` must carry zone_id/zone_name/lat/lon/timestamp_local/
    temp_c/rh_pct (+ wind_kmh, solar_wm2 for full-quality WBGT, + pm25/aqi
    columns when air coupling is available).
    """
    if hourly_frame.empty:
        return []
    issued_at = pd.Timestamp(issued_at)
    issue_date = issued_at.normalize().date()

    daily = ncr_daily(hourly_frame)
    daily = detect_heatwaves(daily, climatology)

    thermal_hourly = compute_htsi_frame(hourly_frame)
    thermal_daily = daily_htsi(thermal_hourly)

    # Departure from the FIXED normal feeds the HTSI anomaly term. Recompute
    # the score with the anomaly so it matches the reason text on the row.
    merged = daily.merge(thermal_daily, on=["zone_id", "date"], how="left", suffixes=("", "_thermal"))
    profiles = zone_profiles()[
        ["zone_id", "vulnerability_score", "vulnerability_level", "vulnerability_source",
         "population", "elderly_pct", "outdoor_worker_pct", "cooling_centre_count", "cooling_access_score"]
    ]
    merged = merged.merge(profiles, on="zone_id", how="left")

    health_status, health_meaning = resolve_model_status(demo=is_demo)
    confidence = (
        "illustrative — deterministic synthetic scenario" if is_demo
        else "directional — model forecast without verified lead-time skill"
    )

    rows: list[dict[str, Any]] = []
    for record in merged.to_dict("records"):
        target_date = pd.Timestamp(record["date"]).date()
        if target_date < issue_date:
            continue  # yesterday's row is context, not a warning target

        score_no_anomaly = record.get("htsi_score")
        score = htsi_score(record.get("wbgt_est_peak_c"), record.get("departure_c"))
        anomaly_used = bool(
            score is not None and score_no_anomaly is not None
            and _finite(score) and _finite(score_no_anomaly)
            and abs(float(score) - float(score_no_anomaly)) > 1e-9
        )
        band = htsi_band(score)

        impact = health_impact_index(
            score,
            record.get("vulnerability_score"),
            record.get("departure_c"),
            record.get("aqi_peak"),
        )

        lead_days = (target_date - issue_date).days
        level, level_drivers = derive_alert_level(
            band["band"], str(record.get("heatwave_label", "None")), str(record.get("heat_aqi_load_band", "Unknown"))
        )
        actions = ACTION_MATRIX[level]

        row: dict[str, Any] = {
            "zone_id": record["zone_id"],
            "zone_name": record["zone_name"],
            "lat": round(float(record["lat"]), 4),
            "lon": round(float(record["lon"]), 4),
            "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M"),
            "issued_at_utc": _to_utc_iso(issued_at),
            "target_date": str(target_date),
            "target_day_label": f"Day +{lead_days}",
            "lead_days": int(lead_days),
            "lead_hours": _lead_hours(issued_at, target_date),
            "lead_time_basis": f"hours from issuance to {LEAD_HOUR_TARGET}:00 local on the target day",
            # --- heatwave detection (IMD plains rule, fixed normals, persistence) ---
            "tmax_c": _round_or_none(record.get("tmax_c"), 1),
            "normal_tmax_c": _round_or_none(record.get("normal_tmax_c"), 1),
            "normal_granularity": record.get("normal_granularity", "unavailable"),
            "departure_c": _round_or_none(record.get("departure_c"), 1),
            "heatwave_candidate": bool(record.get("heatwave_candidate", False)),
            "is_heatwave_episode": bool(record.get("is_heatwave_episode", False)),
            "is_severe_episode": bool(record.get("is_severe_episode", False)),
            "episode_day": int(record.get("episode_day", 0) or 0),
            "episode_length": int(record.get("episode_length", 0) or 0),
            "heatwave_label": str(record.get("heatwave_label", "None")),
            "extreme_temperature_watch": bool(record.get("extreme_temperature_watch", False)),
            # --- thermal stress (meteorological, HTSI) ---
            "hi_peak_c": _round_or_none(record.get("hi_peak_c"), 1),
            "wbgt_est_peak_c": _round_or_none(record.get("wbgt_est_peak_c"), 1),
            "wbgt_peak_quality": str(record.get("wbgt_peak_quality", "unavailable")),
            "wbgt_peak_inputs": str(record.get("wbgt_peak_inputs", "")),
            "htsi_score": None if score is None or not _finite(score) else round(float(score), 1),
            "htsi_band": band["band"],
            "thermal_stress_level": band["band"],
            "htsi_anomaly_used": anomaly_used,
            # --- vulnerability (separately sourced, separately labelled) ---
            "vulnerability_score": _round_or_none(record.get("vulnerability_score"), 1),
            "vulnerability_level": str(record.get("vulnerability_level", "Unavailable")),
            "vulnerability_source": str(record.get("vulnerability_source", "unavailable")),
            # --- health impact (status can never be "validated" without evidence) ---
            "health_impact_index": impact,
            "health_impact_band": health_impact_band(impact),
            "health_impact_status": health_status,
            "health_impact_status_meaning": health_meaning,
            # --- air context ---
            "aqi_peak": _round_or_none(record.get("aqi_peak"), 0),
            "aqi_band": str(record.get("aqi_band", "Unknown")),
            "heat_aqi_load_peak": _round_or_none(record.get("heat_aqi_load_peak"), 0),
            "heat_aqi_load_band": str(record.get("heat_aqi_load_band", "Unknown")),
            # --- decision ---
            "alert_level": level,
            "recommended_action_level": level,
            "alert_level_drivers": level_drivers,
            "reason": _reason_text(record | {"htsi_score": score}),
            # The action TEXTS live once per payload in `action_matrix` (keyed by
            # level) instead of being duplicated on all 48 rows — same contract,
            # a third of the bytes on a static host.
            "action_summary": actions["summary"],
            # --- provenance ---
            "data_source": data_source,
            "quality_state": quality_state,
            "is_demo": bool(is_demo),
            "is_synthetic": bool(is_demo or quality_state == "synthetic-fallback"),
            "scenario_id": scenario_id,
            "fallback_reason": fallback_reason,
            "confidence": confidence,
        }
        rows.append(row)

    rows.sort(key=lambda r: (r["target_date"], -ALERT_LEVELS.index(r["alert_level"]), r["zone_id"]))
    return rows


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _round_or_none(value: Any, digits: int) -> float | None:
    return round(float(value), digits) if _finite(value) else None


def _to_utc_iso(local_naive: pd.Timestamp) -> str:
    """Local (config.TIMEZONE) naive timestamp → UTC ISO string."""
    aware = pd.Timestamp(local_naive).tz_localize(ZoneInfo(config.TIMEZONE))
    return aware.tz_convert(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def warnings_meta(*, issued_at: pd.Timestamp, climatology: dict[str, Any] | None,
                  is_demo: bool, scenario_id: str | None) -> dict[str, Any]:
    """Method/provenance block shared by demo and live warning payloads."""
    return {
        "issued_at": pd.Timestamp(issued_at).strftime("%Y-%m-%dT%H:%M"),
        "issued_at_utc": _to_utc_iso(issued_at),
        "timezone": config.TIMEZONE,
        "lead_hour_target_local": LEAD_HOUR_TARGET,
        "persistence_rule": (
            "IMD plains departure rule (Tmax ≥ 40 °C AND departure ≥ 4.5 °C from the fixed "
            "1991–2020 normal) marks a daily candidate; only runs of ≥ 2 consecutive candidate "
            "days are declared heatwave episodes. Single candidates stay labelled as early watches."
        ),
        "climatology": {
            "available": climatology is not None,
            "reference_period": (climatology or {}).get("reference_period"),
            "source": (climatology or {}).get("source"),
            "note": "Fixed historical normals — never a forecast-window average.",
        },
        "thermal_method": {
            "htsi_version": HTSI_METADATA["version"],
            "score_formula": HTSI_METADATA["score_formula"],
            "quality_flags": QUALITY_DEFINITIONS,
            "assumption_no_anomaly": ASSUMPTION_NO_ANOMALY,
        },
        "alert_levels": [
            {"level": level, "colour": ACTION_MATRIX[level]["colour"],
             "summary": ACTION_MATRIX[level]["summary"]}
            for level in ALERT_LEVELS
        ],
        "action_matrix": ACTION_MATRIX,
        "vulnerability": {
            "formula": VULNERABILITY_FORMULA,
            "source": ZONE_PROFILE_SOURCE,
        },
        "granularity_note": (
            "Zones are ~10 km model grid points, not ward-level observations. "
            "Do not read a single zone value as a street-level measurement."
        ),
        "is_demo": bool(is_demo),
        "scenario_id": scenario_id,
    }


# --------------------------------------------------------------------------- #
# 5. Live advance-warning payload (never HTTP 500 on provider outage)
# --------------------------------------------------------------------------- #

def now_local() -> pd.Timestamp:
    return pd.Timestamp.now(tz=ZoneInfo(config.TIMEZONE)).replace(tzinfo=None).floor("h")


def advance_warning_payload(
    *,
    days: int | None = None,
    zone_id: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Live route payload: forecast when reachable, labelled fallback otherwise.

    ``days`` is the provider window; with past_days=1 the frame spans
    yesterday→today+(days−1), so the default FORECAST_DAYS+1 guarantees
    lead times up to Day +5.
    """
    window = int(days or config.FORECAST_DAYS + 1)
    frame, fallback_reason = _ncr_frame(days=window, use_cache=not force_refresh)
    is_synthetic = bool(frame["is_synthetic"].iloc[0]) if len(frame) else True
    quality_state = "synthetic-fallback" if is_synthetic else "live-forecast"
    data_source = str(frame["data_source"].iloc[0]) if len(frame) else "unavailable"
    issued_at = now_local()
    climatology = load_climatology()

    rows = build_warning_rows(
        frame,
        issued_at=issued_at,
        quality_state=quality_state,
        data_source=data_source,
        is_demo=False,
        climatology=climatology,
        fallback_reason=fallback_reason,
    )
    if zone_id is not None:
        rows = [row for row in rows if row["zone_id"] == zone_id]
        if not rows and zone_id not in set(frame["zone_id"]):
            raise KeyError(zone_id)

    by_lead: dict[str, int] = {}
    for row in rows:
        by_lead[str(row["lead_days"])] = by_lead.get(str(row["lead_days"]), 0) + 1
    level_counts: dict[str, int] = {}
    for row in rows:
        level_counts[row["alert_level"]] = level_counts.get(row["alert_level"], 0) + 1

    return {
        "rows": len(rows),
        "zone_id": zone_id,
        "days": window,
        "lead_day_counts": by_lead,
        "alert_level_counts": level_counts,
        "disclaimer": (
            "Operational-style advance warning built on model forecast data. It is not an "
            "official IMD declaration, and the health-impact indicator is parameterised — "
            "not a validated mortality forecast."
        ),
        "data_source": data_source,
        "is_synthetic": is_synthetic,
        "fallback_reason": fallback_reason,
        "quality_state": quality_state,
        **warnings_meta(issued_at=issued_at, climatology=climatology, is_demo=False, scenario_id=None),
        "data": rows,
    }


__all__ = [
    "ACTION_MATRIX", "ALERT_LEVELS", "LEAD_HOUR_TARGET", "VULNERABILITY_FORMULA",
    "VULNERABILITY_WEIGHTS", "ZONE_PROFILE_SOURCE", "advance_warning_payload",
    "build_warning_rows", "derive_alert_level", "now_local", "vulnerability_level",
    "warnings_meta", "zone_profiles", "zone_profiles_with_geo",
]
