"""
HUMAN THERMAL STRESS INDEX (HTSI)
=================================
A documented, quality-flagged thermal-stress layer that answers "what will the
weather DO to people?" instead of reporting dry-bulb temperature alone.

Design rules enforced here (see README "Metric definitions"):

1. **Meteorological stress only.** The HTSI score is a function of air
   temperature, relative humidity, wind speed, shortwave radiation and — when a
   fixed historical normal is available — the departure from that normal.
   Vulnerability and demographics are deliberately NOT inputs; they live in
   ``core/health_impact.py`` so that "how hot it is" and "who is exposed" can
   never be silently conflated.

2. **Every metric carries explicit source/quality metadata.** Nothing produced
   here is a physical measurement: values are computed from forecast or
   scenario input, so the best attainable flag is ``estimated``.

       measured        a physical instrument observed this (never produced by
                       this module — reserved for ingested station data)
       estimated       all required inputs were available; value computed with
                       the documented formula
       partial-input   a required input was missing; a documented assumption
                       replaced it (the assumption is always listed)
       unavailable     a mandatory input (temperature or humidity) was missing;
                       no value is produced rather than inventing one

3. **Heat Index keeps its documented valid range.** The NWS Rothfusz
   regression is defined for shade, no wind, T >= 80 °F (26.7 °C) and RH
   20-100 %. Below 20 °C we return air temperature (cold-season degeneracy
   guard already implemented in ``core.thermal``). Those limits travel with
   the value in ``HTSI_METADATA``.

Run standalone:  python -m core.htsi        (worked examples incl. missing inputs)
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from core.thermal import (
    globe_temperature,
    heat_index,
    kmh_to_ms,
    wet_bulb_stull,
    wbgt_outdoor,
    wbgt_shade,
)

# --------------------------------------------------------------------------- #
# 1. Quality vocabulary — the same flags everywhere, never per-route wording
# --------------------------------------------------------------------------- #

QUALITY_MEASURED = "measured"
QUALITY_ESTIMATED = "estimated"
QUALITY_PARTIAL = "partial-input"
QUALITY_UNAVAILABLE = "unavailable"

# Which inputs each metric needs, and what we assume when one is missing.
# The keys are the ONLY accepted assumption set — a new assumption must be
# written down here before it can appear in a payload.
QUALITY_DEFINITIONS: dict[str, dict[str, Any]] = {
    QUALITY_MEASURED: {
        "meaning": "Observed by a physical instrument at the location.",
        "produced_by_htsi": False,
    },
    QUALITY_ESTIMATED: {
        "meaning": (
            "Computed from model/forecast inputs (temperature, humidity, wind, "
            "shortwave radiation) with the documented formula. All required "
            "inputs were present. This is NOT a globe-thermometer measurement."
        ),
        "produced_by_htsi": True,
    },
    QUALITY_PARTIAL: {
        "meaning": (
            "Computed with at least one required input missing and replaced by "
            "the documented assumption listed in `assumptions`. Treat as "
            "lower-confidence than `estimated`."
        ),
        "produced_by_htsi": True,
    },
    QUALITY_UNAVAILABLE: {
        "meaning": (
            "A mandatory input (air temperature or relative humidity) is "
            "missing. No value is produced — we never invent one."
        ),
        "produced_by_htsi": True,
    },
}

ASSUMPTION_NO_RADIATION = (
    "shortwave radiation unavailable — shade-form WBGT (0.7·Tw + 0.3·Ta) used; "
    "this UNDERSTATES stress in direct sun"
)
ASSUMPTION_NO_WIND = (
    "wind speed unavailable — free-convection floor of 0.13 m/s used for the "
    "globe energy balance; this OVERSTATES globe temperature in breezy shade"
)
ASSUMPTION_NO_ANOMALY = (
    "climate-normal departure unavailable — HTSI score computed from "
    "meteorological stress only, without the acclimatisation anomaly term"
)

# --------------------------------------------------------------------------- #
# 2. Method documentation — formulas and versions, shipped with every payload
# --------------------------------------------------------------------------- #

HTSI_METADATA: dict[str, Any] = {
    "index_name": "Human Thermal Stress Index (HTSI)",
    "version": "1.0.0",
    "score_range": [0, 100],
    "score_formula": (
        "HTSI = 100 · clip((WBGT_est − 25) / (36 − 25), 0, 1)^1.4 "
        "+ min(8, 1.6 · max(0, Tmax − Tmax_normal(1991–2020))) when a fixed "
        "climate normal is available; clipped to 0–100. The anomaly term "
        "represents acclimatisation stress: heat further above the local "
        "normal harms more at the same absolute WBGT."
    ),
    "separation_rule": (
        "Meteorological stress only. Vulnerability and demographics are NOT "
        "inputs to this index; they are combined separately and transparently "
        "in the health-impact indicator (core/health_impact.py)."
    ),
    "metrics": {
        "heat_index_c": {
            "formula": "NWS Rothfusz regression evaluated in °F with the three "
                       "standard NWS adjustments (low-RH, high-RH, simple-formula "
                       "switch below 80 °F); implementation core.thermal.heat_index.",
            "valid_range": "Designed for air temperature ≥ 26.7 °C (80 °F) and RH 20–100 %. "
                           "Below 20 °C air temperature is returned unchanged.",
            "limitations": "Assumes shade and no wind; ignores solar radiation and "
                           "individual physiology. Public-messaging number, not a "
                           "risk-model driver.",
            "quality_best_case": QUALITY_ESTIMATED,
        },
        "wet_bulb_c": {
            "formula": "Stull (2011) empirical natural wet-bulb from T and RH at "
                       "standard pressure; validated in-repo against a psychrometric "
                       "inversion (max deviation ≈ 0.55 °C, RH ≥ 50 % regime).",
            "valid_range": "−20 °C to 50 °C, RH 5–99 % (Stull's stated envelope).",
            "limitations": "Empirical fit, not a psychrometric measurement.",
            "quality_best_case": QUALITY_ESTIMATED,
        },
        "wbgt_est_c": {
            "formula": "ISO 7243 outdoor WBGT = 0.7·Tw + 0.2·Tg + 0.1·Ta when "
                       "shortwave > 20 W/m², else shade form 0.7·Tw + 0.3·Ta. "
                       "Tg from a 150 mm black-globe energy balance with "
                       "Ranz–Marshall convection (Nu = 2 + 0.6·Re^0.5·Pr^⅓) and "
                       "linearised radiation; absorptivity 0.95.",
            "valid_range": "Outdoor conditions representable by forecast T/RH/wind/"
                           "radiation; Tw via Stull's envelope.",
            "limitations": "ESTIMATED WBGT — no physical globe thermometer is "
                           "involved. Assumes standard globe geometry and "
                           "pressure; cloud/radiation come from the same forecast "
                           "as temperature, so errors are correlated.",
            "quality_best_case": QUALITY_ESTIMATED,
        },
        "utci_c": {
            "formula": None,
            "limitations": "NOT COMPUTED. Full UTCI needs mean radiant "
                           "temperature and its 6th-order polynomial; rather "
                           "than ship a mislabelled approximation, estimated "
                           "WBGT is the radiation-aware metric of record.",
            "quality_best_case": QUALITY_UNAVAILABLE,
        },
    },
    "quality_flags": QUALITY_DEFINITIONS,
    "bands": None,  # filled below once HTSI_BANDS exists
}

# --------------------------------------------------------------------------- #
# 3. Bands — documented thresholds, human-readable labels, text + colour
# --------------------------------------------------------------------------- #

# (lower_bound, band, colour, plain-language meaning)
# Colour is never the only channel: every band ships with its text label.
HTSI_BANDS: tuple[tuple[float, str, str, str], ...] = (
    (0.0,  "Normal",  "#3fb950", "Thermal stress is within the range most healthy adults tolerate."),
    (30.0, "Watch",   "#e3b341", "Rising thermal stress; heat-sensitive groups should start adapting schedules."),
    (55.0, "Warning", "#f0883e", "Dangerous thermal stress for outdoor exposure; municipal heat actions should activate."),
    (75.0, "Severe",  "#f85149", "Life-threatening thermal stress possible; emergency heat-health response."),
)

HTSI_METADATA["bands"] = [
    {"band": band, "colour": colour, "htsi_min": lo, "meaning": meaning}
    for lo, band, colour, meaning in HTSI_BANDS
]


def htsi_band(score: float | None) -> dict[str, Any]:
    """Band lookup that survives None/NaN — an unknown score is 'Unavailable',
    never silently mapped to the lowest band."""
    if score is None:
        return {"band": "Unavailable", "colour": "#8b949e", "htsi_min": None,
                "meaning": "No thermal-stress score could be computed from the available inputs."}
    try:
        value = float(score)
    except (TypeError, ValueError):
        return {"band": "Unavailable", "colour": "#8b949e", "htsi_min": None,
                "meaning": "No thermal-stress score could be computed from the available inputs."}
    if not math.isfinite(value):
        return {"band": "Unavailable", "colour": "#8b949e", "htsi_min": None,
                "meaning": "No thermal-stress score could be computed from the available inputs."}
    chosen = HTSI_BANDS[0]
    for entry in HTSI_BANDS:
        if value >= entry[0]:
            chosen = entry
    lo, band, colour, meaning = chosen
    return {"band": band, "colour": colour, "htsi_min": lo, "meaning": meaning}


def htsi_score(wbgt_est_c: float | None, departure_c: float | None = None) -> float | None:
    """0–100 meteorological thermal-stress score (documented in HTSI_METADATA).

    ``departure_c`` is Tmax minus a FIXED historical climate normal (e.g. the
    1991–2020 normals in data/climatology_normals.json). A forecast-window mean
    is never accepted here — passing one would erase the anomaly the score is
    supposed to express. Callers that lack a real normal pass None and receive
    the score without the anomaly term (flagged by ``htsi_anomaly_used``).
    """
    if wbgt_est_c is None:
        return None
    try:
        w = float(wbgt_est_c)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(w):
        return None
    base = 100.0 * float(np.clip((w - 25.0) / 11.0, 0.0, 1.0)) ** 1.4
    bonus = 0.0
    if departure_c is not None:
        try:
            dep = float(departure_c)
        except (TypeError, ValueError):
            dep = None
        if dep is not None and math.isfinite(dep):
            bonus = min(8.0, 1.6 * max(0.0, dep))
    return round(min(100.0, base + bonus), 1)


# --------------------------------------------------------------------------- #
# 4. Per-row metric computation with explicit quality flags
# --------------------------------------------------------------------------- #

def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def thermal_metrics(
    temp_c: Any,
    rh_pct: Any = None,
    wind_kmh: Any = None,
    solar_wm2: Any = None,
) -> dict[str, Any]:
    """Single-observation thermal metrics + quality metadata.

    Mandatory inputs: temperature, relative humidity.
    Optional inputs: wind (globe convection), shortwave radiation (globe load).
    Missing optional inputs degrade the WBGT to ``partial-input`` with the
    exact documented assumption; missing mandatory inputs yield
    ``unavailable`` rather than a fabricated number.
    """
    has_t = _finite(temp_c)
    has_rh = _finite(rh_pct)
    has_wind = _finite(wind_kmh)
    has_solar = _finite(solar_wm2)

    missing: list[str] = []
    if not has_t:
        missing.append("temperature")
    if not has_rh:
        missing.append("humidity")
    if not has_wind:
        missing.append("wind")
    if not has_solar:
        missing.append("radiation")

    out: dict[str, Any] = {
        "inputs_available": {
            "temperature": has_t, "humidity": has_rh,
            "wind": has_wind, "radiation": has_solar,
        },
        "missing_inputs": missing,
        "assumptions": [],
    }

    if not (has_t and has_rh):
        out.update({
            "heat_index_c": None, "hi_quality": QUALITY_UNAVAILABLE,
            "wet_bulb_c": None, "wet_bulb_quality": QUALITY_UNAVAILABLE,
            "globe_c": None, "globe_quality": QUALITY_UNAVAILABLE,
            "wbgt_est_c": None, "wbgt_quality": QUALITY_UNAVAILABLE,
        })
        return out

    t = float(temp_c)
    rh = float(rh_pct)
    hi = float(heat_index(t, rh))
    tw = float(wet_bulb_stull(t, rh))

    # Heat Index needs only T + RH; both are present whenever we get here.
    hi_quality = QUALITY_ESTIMATED

    # WBGT: degrade honestly when optional inputs are missing.
    assumptions: list[str] = []
    wind_ms = kmh_to_ms(float(wind_kmh)) if has_wind else 0.13  # free-convection floor
    if not has_wind:
        assumptions.append(ASSUMPTION_NO_WIND)
    if has_solar:
        solar = max(0.0, float(solar_wm2))
        tg = float(globe_temperature(t, wind_ms, solar))
        wbgt = float(wbgt_outdoor(t, rh, wind_ms, solar))
    else:
        assumptions.append(ASSUMPTION_NO_RADIATION)
        tg = None
        wbgt = float(wbgt_shade(t, rh))

    wbgt_quality = QUALITY_PARTIAL if assumptions else QUALITY_ESTIMATED

    out.update({
        "heat_index_c": round(hi, 1), "hi_quality": hi_quality,
        "wet_bulb_c": round(tw, 2), "wet_bulb_quality": QUALITY_ESTIMATED,
        "globe_c": round(tg, 2) if tg is not None else None,
        "globe_quality": QUALITY_ESTIMATED if tg is not None else QUALITY_UNAVAILABLE,
        "wbgt_est_c": round(wbgt, 2), "wbgt_quality": wbgt_quality,
        "assumptions": assumptions,
    })
    return out


def compute_htsi_frame(df: pd.DataFrame, departure_c: pd.Series | None = None) -> pd.DataFrame:
    """Vectorised HTSI columns over an hourly frame.

    Requires columns ``temp_c`` and ``rh_pct``; uses ``wind_kmh`` and
    ``solar_wm2`` when present (missing column == missing input for every row,
    which is reflected in the per-row quality flags). An optional
    ``departure_c`` series (aligned to df) feeds the anomaly term of the score.
    """
    out = df.copy()
    t = pd.to_numeric(out.get("temp_c", pd.Series(np.nan, index=out.index)), errors="coerce")
    rh = pd.to_numeric(out.get("rh_pct", pd.Series(np.nan, index=out.index)), errors="coerce")
    wind = pd.to_numeric(out.get("wind_kmh", pd.Series(np.nan, index=out.index)), errors="coerce") if "wind_kmh" in out else pd.Series(np.nan, index=out.index)
    solar = pd.to_numeric(out.get("solar_wm2", pd.Series(np.nan, index=out.index)), errors="coerce") if "solar_wm2" in out else pd.Series(np.nan, index=out.index)

    wind_ms = np.where(np.isfinite(wind.to_numpy(dtype=float)), wind.to_numpy(dtype=float), 0.0) / 3.6
    wind_ms = np.maximum(wind_ms, 0.13)
    solar_arr = solar.to_numpy(dtype=float)

    out["wet_bulb_c"] = np.round(wet_bulb_stull(t, rh), 2)
    out["heat_index_c"] = np.round(heat_index(t, rh), 1)

    has_solar = np.isfinite(solar_arr)
    tg = np.where(has_solar, globe_temperature(t, wind_ms, np.nan_to_num(solar_arr)), np.nan)
    wbgt_sun = wbgt_outdoor(t, rh, wind_ms, np.nan_to_num(solar_arr))
    wbgt_shade_v = wbgt_shade(t, rh)
    out["globe_c"] = np.round(tg, 2)
    out["wbgt_est_c"] = np.round(np.where(has_solar, wbgt_sun, wbgt_shade_v), 2)

    has_mandatory = np.isfinite(t.to_numpy(dtype=float)) & np.isfinite(rh.to_numpy(dtype=float))
    has_wind = np.isfinite(wind.to_numpy(dtype=float))

    quality = np.where(has_mandatory, QUALITY_ESTIMATED, QUALITY_UNAVAILABLE)
    quality = np.where(has_mandatory & (~has_solar | ~has_wind), QUALITY_PARTIAL, quality)
    out["wbgt_quality"] = quality
    out["wbgt_inputs"] = np.where(
        has_mandatory,
        np.where(has_solar,
                 np.where(has_wind, "temperature+humidity+wind+radiation",
                          "temperature+humidity+radiation"),
                 np.where(has_wind, "temperature+humidity+wind", "temperature+humidity")),
        "",
    )

    dep = None
    if departure_c is not None:
        dep = pd.to_numeric(departure_c, errors="coerce").reindex(out.index).to_numpy(dtype=float)
    scores = [
        htsi_score(w, None if dep is None or not np.isfinite(d) else d)
        for w, d in zip(out["wbgt_est_c"].to_numpy(dtype=float),
                        dep if dep is not None else np.full(len(out), np.nan))
    ]
    out["htsi_score"] = scores
    out["htsi_band"] = [htsi_band(s)["band"] for s in scores]
    return out


def daily_htsi(df: pd.DataFrame, group_cols: Sequence[str] = ("zone_id",)) -> pd.DataFrame:
    """Per-location-per-day thermal peaks with the quality of the peak hour.

    The daily row reports the WORST hour (peak estimated WBGT) and the input
    quality at that hour, so a day can never look better than its most
    dangerous moment.
    """
    d = df.copy()
    d["date"] = pd.to_datetime(d["timestamp_local"]).dt.date
    keys = list(group_cols) + ["date"]
    rows: list[dict[str, Any]] = []
    for key_values, group in d.groupby(keys, sort=True):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        valid = group[np.isfinite(group["wbgt_est_c"].to_numpy(dtype=float))] if "wbgt_est_c" in group else group.iloc[0:0]
        peak = valid.loc[valid["wbgt_est_c"].idxmax()] if len(valid) else None
        row = dict(zip(keys, key_values))
        if peak is None:
            row.update({
                "tmax_c": float(group["temp_c"].max()) if "temp_c" in group and group["temp_c"].notna().any() else None,
                "wbgt_est_peak_c": None, "wbgt_peak_quality": QUALITY_UNAVAILABLE,
                "hi_peak_c": None, "htsi_score": None, "htsi_band": "Unavailable",
                "wbgt_peak_inputs": "", "htsi_anomaly_used": False,
            })
        else:
            raw_score = peak.get("htsi_score")
            score = float(raw_score) if _finite(raw_score) else None
            row.update({
                "tmax_c": round(float(group["temp_c"].max()), 1),
                "wbgt_est_peak_c": round(float(peak["wbgt_est_c"]), 1),
                "wbgt_peak_quality": str(peak["wbgt_quality"]),
                "wbgt_peak_inputs": str(peak.get("wbgt_inputs", "")),
                "hi_peak_c": round(float(peak["heat_index_c"]), 1) if _finite(peak.get("heat_index_c")) else None,
                "htsi_score": score,
                "htsi_band": htsi_band(score)["band"],
                # An anomaly term counts as "used" only when it changed the score.
                "htsi_anomaly_used": bool(
                    score is not None
                    and (base := htsi_score(float(peak["wbgt_est_c"]), None)) is not None
                    and abs(score - base) > 1e-9
                ),
            })
        rows.append(row)
    return pd.DataFrame(rows)


__all__ = [
    "ASSUMPTION_NO_ANOMALY", "ASSUMPTION_NO_RADIATION", "ASSUMPTION_NO_WIND",
    "HTSI_BANDS", "HTSI_METADATA", "QUALITY_DEFINITIONS", "QUALITY_ESTIMATED",
    "QUALITY_MEASURED", "QUALITY_PARTIAL", "QUALITY_UNAVAILABLE",
    "compute_htsi_frame", "daily_htsi", "htsi_band", "htsi_score", "thermal_metrics",
]


# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover — worked examples
    print("HTSI worked examples (quality flags under missing inputs)")
    print("=" * 72)
    cases = [
        ("full inputs, hot dry",      dict(temp_c=46.0, rh_pct=15.0, wind_kmh=9.0, solar_wm2=1020.0)),
        ("full inputs, humid",        dict(temp_c=37.0, rh_pct=78.0, wind_kmh=11.0, solar_wm2=700.0)),
        ("no radiation",              dict(temp_c=42.0, rh_pct=25.0, wind_kmh=8.0)),
        ("no wind, no radiation",     dict(temp_c=42.0, rh_pct=25.0)),
        ("no humidity (mandatory)",   dict(temp_c=42.0, wind_kmh=8.0, solar_wm2=900.0)),
        ("mild",                      dict(temp_c=29.0, rh_pct=55.0, wind_kmh=14.0, solar_wm2=420.0)),
    ]
    for label, kwargs in cases:
        m = thermal_metrics(**kwargs)
        score = htsi_score(m["wbgt_est_c"], departure_c=4.0 if m["wbgt_est_c"] else None)
        band = htsi_band(score)
        print(f"{label:28s} WBGT={m['wbgt_est_c']} [{m['wbgt_quality']}] "
              f"HI={m['heat_index_c']} HTSI={score} ({band['band']})")
        for assumption in m["assumptions"]:
            print(f"{'':30s}  assumption: {assumption}")
