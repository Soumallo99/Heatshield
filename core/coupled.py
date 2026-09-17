"""Coupled heat and air-quality support for the National Capital Region.

This module intentionally keeps two concepts separate:

* ``aqi_india`` is an air-quality concentration index.  It is derived from the
  pollutant forecast and must not be silently inflated because it is hot.
* ``heat_aqi_load`` is a *communication / health-load* index which combines
  the AQI with a documented heat multiplier.  It is parameterised, not a
  calibrated pollutant forecast, and is labelled as such in every response.

Open-Meteo is used for weather and atmospheric-composition forecasts when it
is reachable.  A warning system must still render during a network outage, so
``_ncr_frame`` falls back to a deterministic, conspicuously labelled synthetic
heat-and-smog episode.  The fallback is useful for exercising the complete
warning path; it is never presented as a measurement or a forecast.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import requests

from core import config

# Eight locations deliberately span the NCR rather than pretending one grid
# cell is a ward-level observation.  The IDs are stable public API keys.
NCR_ZONES: tuple[dict[str, Any], ...] = (
    {"zone_id": "central-delhi", "zone_name": "Central Delhi", "lat": 28.6139, "lon": 77.2090},
    {"zone_id": "north-delhi", "zone_name": "North Delhi", "lat": 28.7041, "lon": 77.1025},
    {"zone_id": "east-delhi", "zone_name": "East Delhi", "lat": 28.6280, "lon": 77.2950},
    {"zone_id": "south-delhi", "zone_name": "South Delhi", "lat": 28.5244, "lon": 77.1855},
    {"zone_id": "noida", "zone_name": "Noida", "lat": 28.5355, "lon": 77.3910},
    {"zone_id": "greater-noida", "zone_name": "Greater Noida", "lat": 28.4744, "lon": 77.5040},
    {"zone_id": "gurugram", "zone_name": "Gurugram", "lat": 28.4595, "lon": 77.0266},
    {"zone_id": "faridabad", "zone_name": "Faridabad", "lat": 28.4089, "lon": 77.3178},
)

NCR_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NCR_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_HOURLY = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
    "surface_pressure",
)
AIR_HOURLY = (
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "ozone",
    "sulphur_dioxide",
    "us_aqi",
)

# These values are *not fitted*.  They turn an already-forecast AQI into a
# clearly separate combined health-load indicator.  The air-quality forecast
# itself remains the provider value, allowing it to be evaluated honestly.
HEAT_AQI_PARAMETERS = {
    "heat_threshold_c": 35.0,
    "per_c_multiplier": 0.015,
    "max_multiplier": 1.15,
    "description": (
        "A transparent communication multiplier for concurrent heat exposure; "
        "not a calibrated concentration or mortality model."
    ),
}

CLIMATOLOGY_PATH = config.DATA_DIR / "climatology_normals.json"

# A tiny in-process cache avoids each of nine static-export routes retrying a
# known-down provider.  It deliberately expires: recovery should be automatic.
_NCR_CACHE_TTL_SECONDS = 5 * 60
_ncr_cache: tuple[float, pd.DataFrame, str | None] | None = None


# ---------------------------------------------------------------------------
# Zone and provider helpers
# ---------------------------------------------------------------------------

def ncr_zones() -> pd.DataFrame:
    """Return the canonical NCR locations in a stable order."""
    return pd.DataFrame(NCR_ZONES).copy()


def _expanded_zones(zones: int | pd.DataFrame | Sequence[dict[str, Any]] | None) -> pd.DataFrame:
    """Normalise a zone request.

    The synthetic path is intentionally testable with arbitrary ``zones``.
    Earlier code indexed a four-item list of names and crashed at ``zones=8``;
    generated sector labels make that class of fallback bug impossible.
    """
    if zones is None:
        return ncr_zones()
    if isinstance(zones, pd.DataFrame):
        out = zones.copy()
    elif isinstance(zones, int):
        if zones < 1:
            raise ValueError("zones must be at least 1")
        base = ncr_zones()
        if zones <= len(base):
            out = base.iloc[:zones].copy()
        else:
            rows = base.to_dict("records")
            # Spread extra deterministic points around Delhi.  These are only
            # useful in a synthetic test episode and are marked accordingly.
            for number in range(len(rows) + 1, zones + 1):
                angle = 2 * math.pi * (number - len(base) - 1) / max(1, zones - len(base))
                rows.append({
                    "zone_id": f"ncr-sector-{number}",
                    "zone_name": f"NCR Sector {number}",
                    "lat": round(28.62 + 0.16 * math.sin(angle), 5),
                    "lon": round(77.22 + 0.22 * math.cos(angle), 5),
                })
            out = pd.DataFrame(rows)
    else:
        out = pd.DataFrame(list(zones))

    needed = {"zone_id", "zone_name", "lat", "lon"}
    missing = needed - set(out.columns)
    if missing:
        raise ValueError(f"NCR zones missing required columns: {sorted(missing)}")
    if out.empty or not out["zone_id"].is_unique:
        raise ValueError("NCR zones must be non-empty with unique zone_id values")
    return out[["zone_id", "zone_name", "lat", "lon"]].reset_index(drop=True)


def _joined_coordinates(zones: pd.DataFrame) -> tuple[str, str]:
    return (
        ",".join(str(round(float(v), 5)) for v in zones["lat"]),
        ",".join(str(round(float(v), 5)) for v in zones["lon"]),
    )


def _request_payload(url: str, params: dict[str, Any], timeout: int = 8) -> list[dict[str, Any]]:
    """Fetch one Open-Meteo multi-coordinate response, failing loudly.

    Failing here is intentional: ``_ncr_frame`` owns the offline decision and
    can attach a useful fallback reason.  Low-level helpers remain reusable for
    scripts that must distinguish a live result from an outage.
    """
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    values = payload if isinstance(payload, list) else [payload]
    if not values or not all(isinstance(value, dict) for value in values):
        raise RuntimeError("air/weather provider returned an invalid response")
    return values


def get_forecast(
    zones: int | pd.DataFrame | Sequence[dict[str, Any]] | None = None,
    *,
    days: int | None = None,
    past_days: int = 1,
    timeout: int = 8,
) -> pd.DataFrame:
    """Fetch NCR hourly weather from Open-Meteo (no fallback at this layer)."""
    z = _expanded_zones(zones)
    days = int(days or config.FORECAST_DAYS)
    latitudes, longitudes = _joined_coordinates(z)
    payloads = _request_payload(
        NCR_FORECAST_URL,
        {
            "latitude": latitudes,
            "longitude": longitudes,
            "hourly": ",".join(WEATHER_HOURLY),
            "forecast_days": days,
            "past_days": max(0, int(past_days)),
            "timezone": config.TIMEZONE,
            "wind_speed_unit": "kmh",
        },
        timeout=timeout,
    )
    return _weather_frame(payloads, z)


def get_air_quality(
    zones: int | pd.DataFrame | Sequence[dict[str, Any]] | None = None,
    *,
    days: int | None = None,
    past_days: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout: int = 8,
) -> pd.DataFrame:
    """Fetch NCR hourly composition/AQI from Open-Meteo (no fallback here).

    ``start_date`` + ``end_date`` selects the CAMS archive and is used only by
    the observed-CPCB validation script.  Forecast and archive modes are kept
    mutually exclusive so a caller cannot accidentally validate a live horizon
    while believing it fetched historical model values.
    """
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be supplied together")
    z = _expanded_zones(zones)
    days = int(days or config.FORECAST_DAYS)
    latitudes, longitudes = _joined_coordinates(z)
    params: dict[str, Any] = {
        "latitude": latitudes,
        "longitude": longitudes,
        "hourly": ",".join(AIR_HOURLY),
        "timezone": config.TIMEZONE,
    }
    if start_date is not None:
        params.update({"start_date": start_date, "end_date": end_date})
    else:
        params.update({"forecast_days": days, "past_days": max(0, int(past_days))})
    payloads = _request_payload(NCR_AIR_QUALITY_URL, params, timeout=timeout)
    return _air_frame(payloads, z)


def _payloads_for_zones(payloads: list[dict[str, Any]], zones: pd.DataFrame) -> Iterable[tuple[dict[str, Any], pd.Series]]:
    if len(payloads) != len(zones):
        raise RuntimeError(
            f"provider returned {len(payloads)} locations for {len(zones)} requested NCR zones"
        )
    return zip(payloads, (row for _, row in zones.iterrows()))


def _weather_frame(payloads: list[dict[str, Any]], zones: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for payload, zone in _payloads_for_zones(payloads, zones):
        hourly = payload.get("hourly") or {}
        frame = pd.DataFrame(hourly)
        if frame.empty or "time" not in frame:
            raise RuntimeError("weather provider omitted hourly data")
        frame = frame.rename(columns={
            "time": "timestamp_local",
            "temperature_2m": "temp_c",
            "relative_humidity_2m": "rh_pct",
            "wind_speed_10m": "wind_kmh",
            "precipitation": "precip_mm",
            "surface_pressure": "surface_pressure_hpa",
        })
        for source, target, default in (
            ("temp_c", "temp_c", np.nan),
            ("rh_pct", "rh_pct", np.nan),
            ("wind_kmh", "wind_kmh", np.nan),
            ("precip_mm", "precip_mm", 0.0),
            ("surface_pressure_hpa", "surface_pressure_hpa", np.nan),
        ):
            if source not in frame:
                frame[target] = default
        for key in ("zone_id", "zone_name", "lat", "lon"):
            frame[key] = zone[key]
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out["timestamp_local"] = pd.to_datetime(out["timestamp_local"], errors="coerce")
    if out["timestamp_local"].isna().any() or out["temp_c"].isna().all():
        raise RuntimeError("weather provider returned unusable timestamps or temperature")
    return out[[
        "zone_id", "zone_name", "lat", "lon", "timestamp_local", "temp_c", "rh_pct",
        "wind_kmh", "precip_mm", "surface_pressure_hpa",
    ]]


def _air_frame(payloads: list[dict[str, Any]], zones: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for payload, zone in _payloads_for_zones(payloads, zones):
        hourly = payload.get("hourly") or {}
        frame = pd.DataFrame(hourly)
        if frame.empty or "time" not in frame:
            raise RuntimeError("air-quality provider omitted hourly data")
        frame = frame.rename(columns={
            "time": "timestamp_local",
            "pm2_5": "pm25_ugm3",
            "pm10": "pm10_ugm3",
            "nitrogen_dioxide": "no2_ugm3",
            "ozone": "o3_ugm3",
            "sulphur_dioxide": "so2_ugm3",
            "us_aqi": "provider_us_aqi",
        })
        for source, default in (
            ("pm25_ugm3", np.nan), ("pm10_ugm3", np.nan), ("no2_ugm3", np.nan),
            ("o3_ugm3", np.nan), ("so2_ugm3", np.nan), ("provider_us_aqi", np.nan),
        ):
            if source not in frame:
                frame[source] = default
        frame["zone_id"] = zone["zone_id"]
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out["timestamp_local"] = pd.to_datetime(out["timestamp_local"], errors="coerce")
    if out["timestamp_local"].isna().any() or out["pm25_ugm3"].isna().all():
        raise RuntimeError("air-quality provider returned unusable timestamps or PM2.5")
    return out[[
        "zone_id", "timestamp_local", "pm25_ugm3", "pm10_ugm3", "no2_ugm3",
        "o3_ugm3", "so2_ugm3", "provider_us_aqi",
    ]]


# ---------------------------------------------------------------------------
# AQI and joint-load calculation
# ---------------------------------------------------------------------------

# Indian National AQI concentration breakpoints for PM2.5 (24 h ug/m3).  The
# hourly source is a forecast concentration, so the result is labelled an
# indicative hourly sub-index rather than an official certified AQI reading.
PM25_BREAKPOINTS: tuple[tuple[float, float, float, float], ...] = (
    (0, 30, 0, 50),
    (31, 60, 51, 100),
    (61, 90, 101, 200),
    (91, 120, 201, 300),
    (121, 250, 301, 400),
    (251, 500, 401, 500),
)


def aqi_from_pm25(pm25_ugm3: Any) -> np.ndarray | float:
    """Return the Indian PM2.5 sub-index using linear breakpoint interpolation."""
    values = np.asarray(pm25_ugm3, dtype=float)
    output = np.full(values.shape, np.nan, dtype=float)
    for c_lo, c_hi, i_lo, i_hi in PM25_BREAKPOINTS:
        mask = (values >= c_lo) & (values <= c_hi)
        output[mask] = (i_hi - i_lo) / (c_hi - c_lo) * (values[mask] - c_lo) + i_lo
    high = values > PM25_BREAKPOINTS[-1][1]
    # Do not imply a meaningful resolution above the published top band.
    output[high] = 500.0
    low = values < 0
    output[low] = np.nan
    output = np.round(output)
    return float(output) if output.ndim == 0 else output


def aqi_band(aqi: float | int | None) -> str:
    """Human-readable Indian AQI band; no colour-only communication."""
    try:
        value = float(aqi)
    except (TypeError, ValueError):
        return "Unknown"
    if not math.isfinite(value):
        return "Unknown"
    if value <= 50:
        return "Good"
    if value <= 100:
        return "Satisfactory"
    if value <= 200:
        return "Moderate"
    if value <= 300:
        return "Poor"
    if value <= 400:
        return "Very Poor"
    return "Severe"


def _apply_coupling(frame: pd.DataFrame) -> pd.DataFrame:
    """Add AQI and a separate, explicitly parameterised joint exposure load."""
    out = frame.copy()
    out["aqi_india"] = aqi_from_pm25(out["pm25_ugm3"])
    out["aqi_band"] = [aqi_band(value) for value in out["aqi_india"]]

    heat_excess = np.clip(out["temp_c"].astype(float) - HEAT_AQI_PARAMETERS["heat_threshold_c"], 0, None)
    multiplier = 1 + HEAT_AQI_PARAMETERS["per_c_multiplier"] * heat_excess
    out["heat_multiplier"] = np.minimum(multiplier, HEAT_AQI_PARAMETERS["max_multiplier"]).round(3)
    out["heat_aqi_load"] = np.minimum(500, out["aqi_india"] * out["heat_multiplier"]).round(0)
    out["heat_aqi_load_band"] = [aqi_band(value) for value in out["heat_aqi_load"]]
    # Wind and rain are shown as explanatory covariates, not secretly fitted
    # coefficients that change the concentration forecast.
    out["ventilation_index"] = (out["wind_kmh"].clip(lower=0) + 3 * out["precip_mm"].clip(lower=0)).round(2)
    return out


def _combine_live(weather: pd.DataFrame, air: pd.DataFrame) -> pd.DataFrame:
    out = weather.merge(air, on=["zone_id", "timestamp_local"], how="inner", validate="one_to_one")
    if out.empty:
        raise RuntimeError("weather and air-quality responses have no overlapping hours")
    out = _apply_coupling(out)
    out["data_source"] = "open-meteo forecast + CAMS air-quality forecast"
    out["is_synthetic"] = False
    out["fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return out.sort_values(["zone_id", "timestamp_local"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Offline episode and public frame
# ---------------------------------------------------------------------------

def _synthetic(
    zones: int | pd.DataFrame | Sequence[dict[str, Any]] | None = None,
    *,
    days: int | None = None,
    now: pd.Timestamp | datetime | None = None,
) -> pd.DataFrame:
    """Deterministic offline heat-and-smog episode.

    It is intentionally realistic *enough to exercise every screen*, but all
    rows carry ``is_synthetic=True`` and a source string.  Do not use it for
    scientific claims or forecast-skill evaluation.
    """
    z = _expanded_zones(zones)
    days = max(1, int(days or config.FORECAST_DAYS))
    if now is None:
        start = pd.Timestamp.now(tz=config.TIMEZONE).tz_localize(None).floor("h")
    else:
        stamp = pd.Timestamp(now)
        start = stamp.tz_convert(config.TIMEZONE).tz_localize(None).floor("h") if stamp.tzinfo else stamp.floor("h")
    hours = pd.date_range(start=start, periods=days * 24, freq="h")
    rows: list[dict[str, Any]] = []

    for zone_position, zone in enumerate(z.to_dict("records")):
        # Small spatial variation is deterministic and repeatable.  It is
        # never intended to represent real neighbourhood differences.
        zone_heat = (zone_position % 5) * 0.42
        zone_pm = (zone_position % 6) * 11.0
        for ts in hours:
            hour = ts.hour + ts.minute / 60
            # Afternoon maximum around 15:00; a 3-day Gaussian episode gives
            # the advance detector both onset and multi-day continuation.
            diurnal = 7.4 * math.cos((hour - 15) * 2 * math.pi / 24)
            day_index = (ts.normalize() - start.normalize()).days
            event = 5.0 * math.exp(-((day_index - max(1, days // 2)) / 1.35) ** 2)
            temp = 35.0 + diurnal + event + zone_heat
            rh = max(18.0, min(85.0, 54.0 - 1.65 * diurnal - 0.6 * event - zone_heat))
            wind = max(1.2, 7.0 + 3.1 * math.sin((hour - 9) * 2 * math.pi / 24) - zone_position * 0.12)
            precip = 0.0
            # Overnight inversion + a midday ventilation dip.  Again, this is
            # a test episode, not a claim about any observed station.
            pm25 = max(15.0, 132.0 + 30 * math.cos((hour - 7) * 2 * math.pi / 24) + 16 * event + zone_pm)
            pm10 = pm25 * 1.52
            no2 = 34 + 12 * math.cos((hour - 8) * 2 * math.pi / 24) + zone_position * 1.3
            o3 = max(8.0, 24 + 22 * math.cos((hour - 14) * 2 * math.pi / 24))
            rows.append({
                **zone,
                "timestamp_local": ts,
                "temp_c": round(temp, 2),
                "rh_pct": round(rh, 1),
                "wind_kmh": round(wind, 2),
                "precip_mm": precip,
                "surface_pressure_hpa": round(1006 - zone_position * 0.7, 1),
                "pm25_ugm3": round(pm25, 1),
                "pm10_ugm3": round(pm10, 1),
                "no2_ugm3": round(no2, 1),
                "o3_ugm3": round(o3, 1),
                "so2_ugm3": round(8 + zone_position * 0.4, 1),
                "provider_us_aqi": np.nan,
            })
    out = _apply_coupling(pd.DataFrame(rows))
    out["data_source"] = "synthetic offline exercise episode — not observed or forecast data"
    out["is_synthetic"] = True
    out["fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return out.sort_values(["zone_id", "timestamp_local"]).reset_index(drop=True)


def clear_ncr_cache() -> None:
    """Clear the in-process cache (useful to tests and an explicit refresh)."""
    global _ncr_cache
    _ncr_cache = None


def _ncr_frame(
    zones: int | pd.DataFrame | Sequence[dict[str, Any]] | None = None,
    *,
    days: int | None = None,
    use_cache: bool = True,
) -> tuple[pd.DataFrame, str | None]:
    """Return a live NCR frame or a labelled synthetic fallback plus reason.

    This is the only place that degrades a failed provider request.  Returning
    the reason separately lets endpoints say exactly why their data is
    synthetic instead of hiding an outage behind a plausible looking graph.
    """
    global _ncr_cache
    days = int(days or config.FORECAST_DAYS)
    canonical_request = zones is None
    if canonical_request and use_cache and _ncr_cache is not None:
        cached_at, cached, cached_reason = _ncr_cache
        if time.monotonic() - cached_at < _NCR_CACHE_TTL_SECONDS and len(cached["timestamp_local"].unique()) >= 1:
            return cached.copy(), cached_reason

    try:
        weather = get_forecast(zones, days=days)
        air = get_air_quality(zones, days=days)
        frame = _combine_live(weather, air)
        reason = None
    except Exception as exc:  # outage/rate-limit/bad upstream: render anyway
        frame = _synthetic(zones, days=days)
        reason = f"Live NCR provider unavailable: {type(exc).__name__}: {str(exc)[:180]}"

    if canonical_request and use_cache:
        _ncr_cache = (time.monotonic(), frame.copy(), reason)
    return frame, reason


def ncr_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """Daily NCR summary used by heatwave and phone-app payloads."""
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["date"] = pd.to_datetime(out["timestamp_local"]).dt.date
    daily = (
        out.groupby(["zone_id", "zone_name", "lat", "lon", "date"], as_index=False)
        .agg(
            tmax_c=("temp_c", "max"),
            tmin_c=("temp_c", "min"),
            rh_mean_pct=("rh_pct", "mean"),
            wind_mean_kmh=("wind_kmh", "mean"),
            pm25_mean_ugm3=("pm25_ugm3", "mean"),
            pm25_peak_ugm3=("pm25_ugm3", "max"),
            aqi_peak=("aqi_india", "max"),
            heat_aqi_load_peak=("heat_aqi_load", "max"),
            data_source=("data_source", "first"),
            is_synthetic=("is_synthetic", "first"),
            fetched_at=("fetched_at", "first"),
        )
        .sort_values(["zone_id", "date"])
        .reset_index(drop=True)
    )
    daily["aqi_band"] = [aqi_band(value) for value in daily["aqi_peak"]]
    daily["heat_aqi_load_band"] = [aqi_band(value) for value in daily["heat_aqi_load_peak"]]
    return daily.round({"tmax_c": 1, "tmin_c": 1, "rh_mean_pct": 1, "wind_mean_kmh": 1,
                        "pm25_mean_ugm3": 1, "pm25_peak_ugm3": 1})


# ---------------------------------------------------------------------------
# Climatology and heatwave detection
# ---------------------------------------------------------------------------

def load_climatology(path: Path | str = CLIMATOLOGY_PATH) -> dict[str, Any] | None:
    """Load the generated 1991–2020 climatology without manufacturing a normal."""
    source = Path(path)
    if not source.exists():
        return None
    try:
        data = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("zones"), dict):
        return None
    return data


def climatology_normal(
    climatology: dict[str, Any] | None,
    zone_id: str,
    when: date | str | pd.Timestamp,
) -> tuple[float | None, str]:
    """Return (normal Tmax, granularity) for a date, or ``(None, unavailable)``.

    Daily normals are preferred.  A monthly normal is a transparent fallback
    when a source only provides monthly values; a forecast-window mean is never
    substituted because it erases the very anomaly the detector must see.
    """
    if not climatology:
        return None, "unavailable"
    zone = climatology.get("zones", {}).get(str(zone_id))
    if not isinstance(zone, dict):
        return None, "unavailable"
    stamp = pd.Timestamp(when)
    key = stamp.strftime("%m-%d")
    daily = zone.get("daily_tmax_c", {})
    if isinstance(daily, dict) and daily.get(key) is not None:
        return float(daily[key]), "daily"
    monthly = zone.get("monthly_tmax_c", {})
    month_key = str(stamp.month)
    if isinstance(monthly, dict) and monthly.get(month_key) is not None:
        return float(monthly[month_key]), "monthly"
    return None, "unavailable"


def _run_lengths(flags: Sequence[bool]) -> list[int]:
    runs: list[int] = []
    run = 0
    for flag in flags:
        run = run + 1 if bool(flag) else 0
        runs.append(run)
    return runs


def detect_heatwaves(daily: pd.DataFrame, climatology: dict[str, Any] | None = None) -> pd.DataFrame:
    """Apply IMD plains criteria and retain the required two-day episodes.

    A hot day qualifies under the IMD *departure* rule when Tmax is at least
    40 °C and departure from the 1991–2020 normal is at least 4.5 °C.  Severe
    uses a 6.5 °C departure.  An absolute Tmax >= 45 °C is retained separately
    as an ``extreme_temperature_watch``; it must not replace the anomaly rule,
    because doing so makes a forecast-window pseudo-normal look harmless and
    destroys the intended 3–5-day early-warning signal.

    IMD declarations need persistence, so only runs of at least two qualifying
    days receive the ``is_heatwave_episode`` label.  The per-day candidate is
    retained to make borderline lead-time reasoning auditable.
    """
    if daily.empty:
        return daily.copy()
    out = daily.copy()
    normals: list[float | None] = []
    granularity: list[str] = []
    for row in out[["zone_id", "date"]].itertuples(index=False):
        normal, level = climatology_normal(climatology, row.zone_id, row.date)
        normals.append(normal)
        granularity.append(level)
    out["normal_tmax_c"] = normals
    out["normal_granularity"] = granularity
    out["departure_c"] = out["tmax_c"] - out["normal_tmax_c"]
    normal_rule = (out["tmax_c"] >= 40.0) & (out["departure_c"] >= 4.5)
    out["extreme_temperature_watch"] = (out["tmax_c"] >= 45.0).fillna(False)
    out["heatwave_candidate"] = normal_rule.fillna(False)
    out["severe_candidate"] = (
        (out["tmax_c"] >= 40.0) & (out["departure_c"] >= 6.5)
    ).fillna(False)
    out["episode_day"] = 0
    out["episode_length"] = 0
    out["is_heatwave_episode"] = False
    out["is_severe_episode"] = False

    for _zone_id, idx in out.groupby("zone_id", sort=False).groups.items():
        ordered = out.loc[idx].sort_values("date")
        candidate = ordered["heatwave_candidate"].tolist()
        # Build each contiguous block rather than using a trailing run length:
        # every day in a valid two-day block is part of the episode.
        start = 0
        while start < len(candidate):
            if not candidate[start]:
                start += 1
                continue
            stop = start + 1
            while stop < len(candidate) and candidate[stop]:
                stop += 1
            length = stop - start
            positions = ordered.index[start:stop]
            out.loc[positions, "episode_day"] = list(range(1, length + 1))
            out.loc[positions, "episode_length"] = length
            if length >= 2:
                out.loc[positions, "is_heatwave_episode"] = True
                if bool(ordered.iloc[start:stop]["severe_candidate"].any()):
                    out.loc[positions, "is_severe_episode"] = True
            start = stop

    out["heatwave_label"] = np.select(
        [out["is_severe_episode"], out["is_heatwave_episode"], out["heatwave_candidate"],
         out["extreme_temperature_watch"]],
        ["Severe Heat Wave", "Heat Wave", "Watch", "Extreme-temperature watch"],
        default="None",
    )
    out["departure_c"] = out["departure_c"].round(1)
    return out


def heatwave_advance_payload(
    *,
    days: int | None = None,
    zone_id: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Build the serialisable /heatwave/advance response and never 500 offline."""
    frame, fallback_reason = _ncr_frame(days=days, use_cache=not force_refresh)
    daily = detect_heatwaves(ncr_daily(frame), load_climatology())
    if zone_id is not None:
        daily = daily[daily["zone_id"] == zone_id].copy()
        if daily.empty:
            raise KeyError(zone_id)

    # Provenance lives once at response level.  Repeating the long source and
    # fallback reason on every daily row materially hurts a static-host payload.
    records = daily.drop(columns=["data_source", "is_synthetic", "fetched_at"], errors="ignore").copy()
    records["date"] = records["date"].astype(str)
    records = records.astype(object).where(pd.notna(records), None)
    episode_rows = records[records["is_heatwave_episode"]]
    normal_rows = int(records["normal_tmax_c"].notna().sum())
    return {
        "rows": int(len(records)),
        "zone_id": zone_id,
        "data_source": str(frame["data_source"].iloc[0]) if len(frame) else "unavailable",
        "is_synthetic": bool(frame["is_synthetic"].iloc[0]) if len(frame) else True,
        "fallback_reason": fallback_reason,
        "climatology": {
            "available": load_climatology() is not None,
            "reference_period": (load_climatology() or {}).get("reference_period"),
            "normal_rows": normal_rows,
            "method": "IMD plains departure rule plus a two-day episode; absolute Tmax is a separate watch", 
        },
        "episodes": int(episode_rows[["zone_id", "date"]].shape[0]),
        "data": records.to_dict(orient="records"),
    }


# ---------------------------------------------------------------------------
# Skill scores: report CSI/HSS, never misleading bare accuracy
# ---------------------------------------------------------------------------

def contingency_scores(predicted: Iterable[bool], observed: Iterable[bool]) -> dict[str, float | int | None]:
    """Return the heat-event contingency table, CSI and Heidke Skill Score.

    Accuracy is deliberately absent.  In rare-event heatwave data, a model that
    predicts no events can look excellent by accuracy while having CSI = 0.
    """
    p = np.asarray(list(predicted), dtype=bool)
    o = np.asarray(list(observed), dtype=bool)
    if p.shape != o.shape:
        raise ValueError("predicted and observed must have the same shape")
    hits = int(np.sum(p & o))
    misses = int(np.sum(~p & o))
    false_alarms = int(np.sum(p & ~o))
    correct_negatives = int(np.sum(~p & ~o))
    csi_denom = hits + misses + false_alarms
    csi = hits / csi_denom if csi_denom else None
    hss_denom = ((hits + misses) * (misses + correct_negatives)
                 + (hits + false_alarms) * (false_alarms + correct_negatives))
    hss = (2 * (hits * correct_negatives - misses * false_alarms) / hss_denom) if hss_denom else None
    return {
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "correct_negatives": correct_negatives,
        "csi": round(float(csi), 3) if csi is not None else None,
        "hss": round(float(hss), 3) if hss is not None else None,
    }


__all__ = [
    "AIR_HOURLY", "CLIMATOLOGY_PATH", "HEAT_AQI_PARAMETERS", "NCR_ZONES",
    "_ncr_frame", "_synthetic", "aqi_band", "aqi_from_pm25", "clear_ncr_cache",
    "climatology_normal", "contingency_scores", "detect_heatwaves", "get_air_quality",
    "get_forecast", "heatwave_advance_payload", "load_climatology", "ncr_daily", "ncr_zones",
]
