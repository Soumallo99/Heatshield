"""
PHASE 3 — Mortality Risk Index (0-100)
======================================
Impact-based risk, not raw weather:

    RISK = HAZARD x VULNERABILITY-AMPLIFIER

  HAZARD        f(WBGT) after urban-heat-island downscaling — the physics (Phase 2)
  VULNERABILITY demographic susceptibility — who is exposed and how fragile they are

THE CENTRAL PROBLEM THIS SOLVES
-------------------------------
All 141 Kolkata wards sit inside ONE Open-Meteo grid cell (~11 km), so raw WBGT is
essentially identical across the city — a map of it would be 14 identical dots.
Two mechanisms create real spatial differentiation:

  1. UHI DOWNSCALING  -- a per-ward dT from population density and green-cover deficit
     (measured Kolkata UHI is ~2-4 C). Absolute humidity is held constant while air
     temperature rises, so RH falls as T rises — physically correct, and it stops the
     model from inventing moisture that isn't there.

  2. VULNERABILITY    -- elderly %, slum %, outdoor workers %, density, green deficit.

Defaults are transparent rule-based weights (defensible, no training data required).
An optional sklearn hook learns the weights if real mortality labels are supplied.

Run:  python -m core.risk                      # current conditions
      python -m core.risk --scenario +6        # +6 C heatwave stress test
      python -m core.risk --fit data/mortality_labels.SYNTHETIC.example.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.config import RISK_BANDS
from core.thermal import (
    globe_temperature,
    heat_index,
    saturation_vapour_pressure,
    wbgt_outdoor,
    wet_bulb_stull,
)
from core.weather import load_wards

# --------------------------------------------------------------------------- #
# Tunable parameters — every one is exposed so judges can interrogate them
# --------------------------------------------------------------------------- #

# UHI components — every input is measured, not assumed.
#   pop_norm      -> anthropogenic heat + crowding       (real: Census 2011 / ward area)
#   green_deficit -> missing evaporative cooling         (real: OSM green polygons)
#   built_norm    -> impervious surface / canyon effect  (real: OSM building centroids)
#   water_deficit -> missing water-body cooling          (real: OSM water polygons)
UHI = {
    "pop_weight": 0.45,
    "green_weight": 0.35,
    "built_weight": 0.15,
    "water_weight": 0.05,
    "max_c": 3.5,           # measured Kolkata UHI is ~2-4 C; 3.5 keeps us inside it
    "clamp": (0.0, 5.0),
}

HAZARD = {
    "w0": 25.0,        # WBGT below which thermal hazard is treated as zero
    "w_max": 36.0,     # WBGT at/above which hazard saturates at 100
    "exponent": 1.4,   # convexity: risk accelerates faster than WBGT
}

# Vulnerability from REAL, MEASURED features only. Must sum to 1.0.
#
# DELIBERATELY ABSENT: age structure, slum households, outdoor-worker share.
# Those live in Census 2011 ward-level PCA tables that are not freely
# machine-readable, and inventing them would make the whole index theatre.
# Until they are sourced, this index measures EXPOSURE + URBAN FORM, not
# physiological frailty — and is labelled that way in the UI.
VULN_WEIGHTS = {
    # --- urban form: how much HOTTER this ward gets (heat amplification) ------
    "pop_density_km2":   0.22,  # crowding: more people per unit of shade/water
    "green_deficit":     0.22,  # no vegetation to cool the neighbourhood
    "built_density_km2": 0.13,  # impervious surface / urban canyon
    "water_deficit":     0.08,  # no water-body cooling
    # --- social: how badly the population COPES (Census 2011 PCA) -------------
    "illiteracy":        0.20,  # socioeconomic deprivation / health literacy
    "crowding":          0.08,  # persons per household -> indoor heat load
    "outdoor_work":      0.07,  # share who work -> daytime outdoor exposure
}                               # (sums to 1.00; urban form 0.65, social 0.35)

# The social block needs these columns in data/wards.csv. They come from the
# official Census 2011 PCA via scripts/build_demographics.py. If they are
# missing the index degrades to urban-form-only rather than crashing, and
# active_social_keys() reports exactly what was used.
SOCIAL_KEYS = ("illiteracy", "crowding", "outdoor_work")

CENSUS_CAVEAT = (
    "illiteracy_pct, hh_size and worker_pct are from the Census of India 2011 "
    "Primary Census Abstract (ward level, official). Population aged 60+ — the "
    "strongest single driver of heat mortality — is NOT available at ward level "
    "in any machine-readable source found, so it is absent rather than modelled."
)


def active_social_keys(wards: pd.DataFrame) -> list[str]:
    """Which social-vulnerability terms are actually backed by data."""
    have = {
        "illiteracy": "illiteracy_pct" in wards.columns,
        "crowding": "hh_size" in wards.columns,
        "outdoor_work": "worker_pct" in wards.columns,
    }
    return [k for k in SOCIAL_KEYS if have[k]]

# OSM mapping completeness varies by ward: a ward with few mapped buildings is
# usually under-mapped, not empty. Flagged in the UI and in every output.
OSM_CAVEAT = (
    "green_cover_pct, water_pct and building_density_km2 are derived from "
    "OpenStreetMap and therefore reflect mapping completeness as well as ground "
    "truth. A production system should use Sentinel-2 NDVI and an impervious-"
    "surface product instead."
)

MORTALITY = {
    "baseline_deaths_per_1000_per_year": 7.2,   # India crude death rate ~7.2/1000/yr
    "wbgt_threshold_c": 27.0,                   # above which excess mortality accrues
    "rr_coeff": 0.025,          # RR = exp(0.025 * (WBGT - 27)); ~+2.5% per C above threshold
}

COMBINE = {
    "hazard_floor": 0.55,     # risk = hazard * (floor + (1-floor) * vuln/100)
}


# --------------------------------------------------------------------------- #
# 1. Urban heat island downscaling
# --------------------------------------------------------------------------- #

def uhi_delta(wards: pd.DataFrame) -> pd.Series:
    """
    Per-ward temperature increment (C), relative to the city's coolest ward.

    Components are min-max normalised across the ward set, so the scale is
    self-calibrating: the coolest ward gets +0.0 C and the hottest +max_c.
    """
    p = np.log10(wards["pop_density_km2"].astype(float).clip(lower=1))
    pop_norm = (p - p.min()) / (p.max() - p.min() or 1)
    green_deficit = 1 - wards["green_cover_pct"].astype(float) / 100.0
    water_deficit = 1 - wards["water_pct"].astype(float) / 100.0
    built = wards["building_density_km2"].astype(float) if "building_density_km2" in wards else 0.0
    b = np.log1p(np.asarray(built, dtype=float))
    built_norm = (b - b.min()) / (b.max() - b.min() or 1)

    raw = (UHI["pop_weight"] * pop_norm
           + UHI["green_weight"] * green_deficit
           + UHI["built_weight"] * built_norm
           + UHI["water_weight"] * water_deficit)
    raw_norm = (raw - raw.min()) / (raw.max() - raw.min() or 1)
    return (raw_norm * UHI["max_c"]).clip(*UHI["clamp"]).round(2)


def apply_uhi(df: pd.DataFrame, wards: pd.DataFrame) -> pd.DataFrame:
    """
    Push the grid forecast down to ward level.

    Holds ABSOLUTE humidity (dew point) constant while air temperature rises by the UHI
    increment, so relative humidity correctly falls instead of inventing extra moisture.
    """
    out = df.copy()
    if "uhi_delta_c" in out.columns:
        out = out.drop(columns=["uhi_delta_c"])

    # uhi_delta() carries wards' positional index, NOT ward_id — re-attach ward_id
    # explicitly or the merge silently shifts every ward by one row.
    uhi = wards[["ward_id"]].copy()
    uhi["uhi_delta_c"] = uhi_delta(wards).to_numpy()
    out = out.merge(uhi, on="ward_id", how="left")
    assert out["uhi_delta_c"].notna().all(), "UHI merge failed — ward_id mismatch"

    out["temp_adj_c"] = out["temp_c"] + out["uhi_delta_c"].fillna(0.0)

    e_actual = saturation_vapour_pressure(out["dewpoint_c"])
    rh_new = 100.0 * e_actual / saturation_vapour_pressure(out["temp_adj_c"])
    out["rh_adj_pct"] = np.clip(rh_new, 1, 100).round(1)

    if "wind_ms" not in out.columns:
        out["wind_ms"] = out["wind_kmh"] / 3.6
    solar = out.get("solar_wm2", pd.Series(0.0, index=out.index)).fillna(0.0)

    out["wet_bulb_adj_c"] = np.round(wet_bulb_stull(out["temp_adj_c"], out["rh_adj_pct"]), 2)
    out["globe_adj_c"] = np.round(globe_temperature(out["temp_adj_c"], out["wind_ms"], solar), 2)
    out["wbgt_adj_c"] = np.round(
        wbgt_outdoor(out["temp_adj_c"], out["rh_adj_pct"], out["wind_ms"], solar), 2)
    out["heat_index_adj_c"] = np.round(heat_index(out["temp_adj_c"], out["rh_adj_pct"]), 2)
    return out


# --------------------------------------------------------------------------- #
# 2. Hazard from thermal stress
# --------------------------------------------------------------------------- #

def hazard_score(wbgt_c) -> np.ndarray:
    """0-100 thermal hazard, convex in WBGT, zero below HAZARD['w0']."""
    w = np.asarray(wbgt_c, dtype=float)
    frac = np.clip((w - HAZARD["w0"]) / (HAZARD["w_max"] - HAZARD["w0"]), 0, 1)
    return np.round(100.0 * frac ** HAZARD["exponent"], 1)


# --------------------------------------------------------------------------- #
# 3. Vulnerability index
# --------------------------------------------------------------------------- #

def _minmax(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    return (s - s.min()) / (s.max() - s.min() or 1)


def vulnerability_index(wards: pd.DataFrame, weights: dict | None = None) -> pd.Series:
    """
    0-100 susceptibility index, built ONLY from measured features.

    Two blocks:
      urban form  - how much hotter this ward actually gets
      social      - how badly its residents cope (Census 2011 PCA)

    Each feature is min-max normalised across the ward set. Weights are
    renormalised over the features that are actually present, so a wards.csv
    without the Census columns still returns a correctly-scaled 0-100 score
    instead of one silently squashed toward zero.
    """
    w = dict(VULN_WEIGHTS if weights is None else weights)

    def _norm(name: str):
        return _minmax(wards[name]) if name in wards.columns else 0.0

    parts = {
        "pop_density_km2":   _minmax(wards["pop_density_km2"]),
        "green_deficit":     1 - wards["green_cover_pct"].astype(float) / 100.0,
        "built_density_km2": _norm("building_density_km2"),
        "water_deficit":     1 - wards["water_pct"].astype(float) / 100.0
                             if "water_pct" in wards.columns else 0.0,
        # --- Census 2011 social block (0.0 if the columns are absent) ---
        "illiteracy":        _norm("illiteracy_pct"),
        "crowding":          _norm("hh_size"),
        "outdoor_work":      _norm("worker_pct"),
    }
    # np.isscalar() is True only for the 0.0 placeholders, i.e. missing columns.
    usable = {k: v for k, v in parts.items()
              if w.get(k, 0) > 0 and not np.isscalar(v)}
    total = sum(w[k] for k in usable) or 1.0
    score = sum(w[k] / total * v for k, v in usable.items())
    return (100.0 * score).round(1)


# --------------------------------------------------------------------------- #
# 4. Combine + mortality translation
# --------------------------------------------------------------------------- #

def risk_score(hazard, vulnerability) -> np.ndarray:
    """RISK = hazard x (floor + (1-floor) * vuln/100). Vulnerability amplifies, never creates."""
    h = np.asarray(hazard, dtype=float)
    v = np.asarray(vulnerability, dtype=float)
    amp = COMBINE["hazard_floor"] + (1 - COMBINE["hazard_floor"]) * (v / 100.0)
    return np.round(np.clip(h * amp, 0, 100), 1)


def risk_band(score) -> tuple[str, str]:
    """-> (band name, colour) using config.RISK_BANDS."""
    s = float(score)
    for lo, hi, colour, name in RISK_BANDS:
        if lo <= s < hi:
            return name, colour
    return RISK_BANDS[-1][3], RISK_BANDS[-1][2]


def relative_risk(wbgt_c) -> np.ndarray:
    """Mortality relative risk vs baseline, from a simple exponential dose-response."""
    w = np.asarray(wbgt_c, dtype=float)
    excess = np.maximum(0.0, w - MORTALITY["wbgt_threshold_c"])
    return np.exp(MORTALITY["rr_coeff"] * excess)


def excess_deaths(population, wbgt_c) -> np.ndarray:
    """ILLUSTRATIVE excess deaths per day. Assumptions are in MORTALITY — show them, don't hide them."""
    baseline_daily = MORTALITY["baseline_deaths_per_1000_per_year"] / 365.0 / 1000.0
    return np.round(
        np.asarray(population, dtype=float) * baseline_daily * (relative_risk(wbgt_c) - 1.0), 2)


# --------------------------------------------------------------------------- #
# 5. Pipelines
# --------------------------------------------------------------------------- #

def compute_risk(df: pd.DataFrame, wards: pd.DataFrame | None = None,
                 temp_offset_c: float = 0.0) -> pd.DataFrame:
    """Hourly ward-level risk. `temp_offset_c` is for scenario/stress testing."""
    wards = load_wards() if wards is None else wards
    out = df.copy()
    if temp_offset_c:
        out["temp_c"] = out["temp_c"] + temp_offset_c
        out["dewpoint_c"] = out["dewpoint_c"] + temp_offset_c

    out = apply_uhi(out, wards)

    vuln = wards.assign(vulnerability=vulnerability_index(wards))[["ward_id", "vulnerability"]]
    out = out.merge(vuln, on="ward_id", how="left")

    out["hazard_score"] = hazard_score(out["wbgt_adj_c"])
    out["risk_score"] = risk_score(out["hazard_score"], out["vulnerability"])
    bands = [risk_band(v) for v in out["risk_score"]]
    out["risk_band"] = [b[0] for b in bands]
    out["risk_colour"] = [b[1] for b in bands]
    return out


def daily_risk(df: pd.DataFrame, wards: pd.DataFrame | None = None,
               temp_offset_c: float = 0.0) -> pd.DataFrame:
    """One row per ward-day: peak risk, band, exposure, illustrative excess deaths."""
    wards = load_wards() if wards is None else wards
    r = compute_risk(df, wards, temp_offset_c=temp_offset_c)
    r["date"] = r["timestamp_local"].dt.date

    g = (r.groupby(["ward_id", "ward_name", "date"], as_index=False)
           .agg(tmax_adj_c=("temp_adj_c", "max"),
                rh_mean_pct=("rh_adj_pct", "mean"),
                wbgt_peak_c=("wbgt_adj_c", "max"),
                hi_peak_c=("heat_index_adj_c", "max"),
                hazard_score=("hazard_score", "max"),
                risk_score=("risk_score", "max"),
                uhi_delta_c=("uhi_delta_c", "first")))

    g = g.merge(wards.assign(vulnerability=vulnerability_index(wards))
                     [["ward_id", "vulnerability"]], on="ward_id", how="left")
    g = g.merge(wards[["ward_id", "population"]], on="ward_id", how="left")

    bands = [risk_band(v) for v in g["risk_score"]]
    g["risk_band"] = [b[0] for b in bands]
    g["risk_colour"] = [b[1] for b in bands]

    g["exposed_population"] = (g["population"] * g["risk_score"] / 100.0).round(0)
    g["relative_risk"] = relative_risk(g["wbgt_peak_c"]).round(3)
    g["excess_deaths_per_day"] = excess_deaths(g["population"], g["wbgt_peak_c"])

    return g.round(2).sort_values(["date", "risk_score"], ascending=[True, False]).reset_index(drop=True)


def ward_ranking(daily: pd.DataFrame, wards: pd.DataFrame | None = None,
                 date: str | None = None) -> pd.DataFrame:
    """
    League table for a single day — the thing the dashboard reads.

    The default day is the WORST day in the forecast window, not the last one.
    This is an early-warning product, so the actionable view is the peak of the
    coming heatwave. Ranking on the final horizon day instead showed the
    furthest-out (and in practice often the coolest) day, which made the map
    contradict the alerts panel — the panel scans the whole window, the map did
    not. Pass `date="YYYY-MM-DD"` to pin a specific day.

    Carries lat/lon so the map can position wards without a second request.
    """
    wards = load_wards() if wards is None else wards
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date

    if date is not None:
        date = pd.to_datetime(date).date()
    elif not d.empty:
        # Peak day: the day whose worst-scoring ward is worst overall.
        date = d.groupby("date")["risk_score"].max().idxmax()

    d = d[d["date"] == date].copy()
    d = d.merge(wards[["ward_id", "lat", "lon"]], on="ward_id", how="left")
    return (d.sort_values("risk_score", ascending=False)
             .assign(rank=lambda x: range(1, len(x) + 1))
             [["rank", "ward_id", "ward_name", "lat", "lon", "risk_score", "risk_band",
               "risk_colour", "wbgt_peak_c", "hi_peak_c", "tmax_adj_c", "uhi_delta_c",
               "vulnerability", "population", "exposed_population",
               "excess_deaths_per_day", "date"]]
             .reset_index(drop=True))


# --------------------------------------------------------------------------- #
# 6. Optional ML: learn the weights from real mortality labels
# --------------------------------------------------------------------------- #

FEATURE_COLS = ["wbgt_peak_c", "hi_peak_c", "tmax_adj_c", "uhi_delta_c", "vulnerability"]


def fit_ml_model(labels: pd.DataFrame, target_col: str = "excess_deaths") -> dict:
    """
    Fit a gradient-boosted model on labelled outcomes and report what it learned.
    Falls back gracefully if scikit-learn isn't installed.

    `labels` needs: ward_id, date + the target column. Features are joined from the model.
    Returns {"model", "importances", "r2", "n"} — compare importances against VULN_WEIGHTS
    to sanity-check the hand-set weights.
    """
    try:
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.metrics import r2_score
    except ImportError:
        return {"error": "scikit-learn not installed (pip install scikit-learn)"}

    df = labels.copy()
    if target_col not in df.columns:
        return {"error": f"labels missing target column '{target_col}'"}

    X = df[FEATURE_COLS].astype(float)
    y = df[target_col].astype(float)
    model = GradientBoostingRegressor(n_estimators=200, max_depth=2, random_state=0)
    model.fit(X, y)

    return {
        "model": model,
        "importances": dict(zip(FEATURE_COLS, np.round(model.feature_importances_, 3))),
        "r2": round(float(r2_score(y, model.predict(X))), 3),
        "n": int(len(df)),
    }


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from core.weather import get_forecast

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="0",
                    help="temperature offset in C, e.g. +6 to stress-test a heatwave")
    ap.add_argument("--fit", default="", help="CSV of mortality labels for the ML hook")
    args = ap.parse_args()
    offset = float(args.scenario)

    pd.set_option("display.width", 200)
    wards = load_wards()

    print("=" * 96)
    print("PHASE 3 — Mortality Risk Index" + (f"   [scenario: {offset:+.0f} C]" if offset else ""))
    print("=" * 96)

    uhi = wards.assign(uhi_delta_c=uhi_delta(wards), vuln=vulnerability_index(wards))
    print("\nUHI downscaling + vulnerability (the two differentiators):")
    print(uhi[["ward_id", "ward_name", "pop_density_km2", "green_cover_pct",
               "uhi_delta_c", "vuln"]].to_string(index=False))
    print(f"\nUHI spread: {uhi.uhi_delta_c.min():+.1f} to {uhi.uhi_delta_c.max():+.1f} C "
          f"(measured Kolkata UHI is ~2-4 C)")
    print(f"Vulnerability spread: {uhi.vuln.min():.0f} to {uhi.vuln.max():.0f}")

    df = get_forecast()
    daily = daily_risk(df, wards, temp_offset_c=offset)

    print("\n" + "=" * 96)
    print("Ward ranking — latest day")
    print("=" * 96)
    print(ward_ranking(daily).to_string(index=False))

    print("\nFull ward-day table (worst 10):")
    print(daily.nlargest(10, "risk_score")[
        ["ward_name", "date", "tmax_adj_c", "wbgt_peak_c", "hazard_score",
         "vulnerability", "risk_score", "risk_band", "exposed_population",
         "relative_risk", "excess_deaths_per_day"]
    ].to_string(index=False))

    band_counts = daily[daily["date"] == daily["date"].max()]["risk_band"].value_counts()
    print("\nBand distribution on latest day:")
    for b in ["Normal", "Caution", "Danger", "Critical"]:
        if b in band_counts:
            print(f"  {b:<9} {band_counts[b]} wards")

    if args.fit:
        labels = pd.read_csv(args.fit)
        res = fit_ml_model(labels)
        print("\nML weight check:")
        print("  " + ("error: " + res["error"] if "error" in res
                      else f"n={res['n']}  R2={res['r2']}  importances={res['importances']}"))

        # --fit is DIAGNOSTIC: it must never overwrite the live pipeline output.
        # (It used to, which quietly replaced the real risk table with whatever
        # this run happened to produce — indistinguishable from a bug in the
        # model.) Diagnostics get their own file; the live table is only written
        # by the pipeline itself (scripts.refresh / scripts.schedule).
        Path("data/processed").mkdir(parents=True, exist_ok=True)
        out = Path("data/processed/risk_daily.fit-diagnostics.csv")
        daily.to_csv(out, index=False)
        if "importances" in res:
            pd.DataFrame(
                [{"feature": k, "importance": float(v)} for k, v in res["importances"].items()]
            ).sort_values("importance", ascending=False).to_csv(
                "data/processed/risk_feature_importances.csv", index=False
            )
            print("  importances -> data/processed/risk_feature_importances.csv")
        print(f"\nSaved (diagnostic only) -> {out}")
        print("  data/processed/risk_daily.csv was NOT modified.")
    else:
        daily.to_csv("data/processed/risk_daily.csv", index=False)
        print("\nSaved -> data/processed/risk_daily.csv")
