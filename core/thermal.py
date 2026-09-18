"""
PHASE 2 — Thermal Stress Engine
===============================
Turns raw weather (Phase 1) into human-relevant heat stress:

  * Heat Index (HI)      -- Rothfusz/NWS regression. The number for PUBLIC MESSAGING.
  * WBGT (outdoor)       -- 0.7*Tw + 0.2*Tg + 0.1*Ta. The number for the RISK MODEL
                            (it accounts for sun + wind, which HI ignores).
  * Natural wet-bulb Tw  -- Stull (2011) empirical, validated here against a
                            psychrometric inversion (max dev ~0.3 C).
  * Globe temperature Tg -- energy balance on a 150 mm black globe, Ranz-Marshall
                            forced convection + linearised radiation.
  * Heatwave detection   -- IMD criteria (coastal/plain presets), feeds Phase 3.

Run standalone:  python -m core.thermal      (validation table + live demo)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# 0. Unit helpers
# --------------------------------------------------------------------------- #

SIGMA = 5.670374419e-8   # Stefan-Boltzmann, W/m^2/K^4
GLOBE_D = 0.15           # standard 150 mm black globe, m
GLOBE_ABS = 0.95         # shortwave absorptivity of the black globe
K_AIR = 0.026            # thermal conductivity of air, W/m/K
NU_AIR = 1.6e-5          # kinematic viscosity of air, m^2/s
PR_AIR = 0.71            # Prandtl number


def c2f(c):
    return np.asarray(c, dtype=float) * 9.0 / 5.0 + 32.0


def f2c(f):
    return (np.asarray(f, dtype=float) - 32.0) * 5.0 / 9.0


def kmh_to_ms(v):
    return np.asarray(v, dtype=float) / 3.6


def saturation_vapour_pressure(t_c) -> np.ndarray:
    """Tetens equation, kPa."""
    t = np.asarray(t_c, dtype=float)
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


# --------------------------------------------------------------------------- #
# 1. Heat Index (Rothfusz regression, NWS) — PUBLIC-FACING NUMBER
# --------------------------------------------------------------------------- #

def heat_index(t_c, rh_pct):
    """
    NWS Heat Index in °C.
    Works in °F internally (the regression is defined there), returns °C.
    Valid for T >= ~27 °C; below that it converges to air temperature.
    """
    t = np.asarray(t_c, dtype=float)
    r = np.clip(np.asarray(rh_pct, dtype=float), 0, 100)
    tf, rf = c2f(t), r

    hi = (
        -42.379 + 2.04901523 * tf + 10.14333127 * rf
        - 0.22475541 * tf * rf - 6.83783e-3 * tf**2
        - 5.481717e-2 * rf**2 + 1.22874e-3 * tf**2 * rf
        + 8.5282e-4 * tf * rf**2 - 1.99e-6 * tf**2 * rf**2
    )

    # NWS adjustments
    hot_dry = (rf < 13) & (tf >= 80) & (tf <= 112)
    adj1 = ((13 - rf) / 4) * np.sqrt(np.clip((17 - np.abs(tf - 95)) / 17, 0, None))
    hi = np.where(hot_dry, hi - adj1, hi)

    hot_humid = (rf > 85) & (tf >= 80) & (tf <= 87)
    adj2 = ((rf - 85) / 10) * ((87 - tf) / 5)
    hi = np.where(hot_humid, hi + adj2, hi)

    # Simple formula is more accurate below 80 °F
    simple = 0.5 * (tf + 61.0 + (tf - 68.0) * 1.2 + rf * 0.094)
    hi = np.where(hi < 80, simple, hi)

    return np.where(t < 20, t, f2c(hi))     # cold-season degeneracy guard


# --------------------------------------------------------------------------- #
# 2. Natural wet-bulb temperature
# --------------------------------------------------------------------------- #

def wet_bulb_stull(t_c, rh_pct):
    """Stull (2011) empirical natural wet-bulb, °C. Fast + vectorised (the model path)."""
    t = np.asarray(t_c, dtype=float)
    r = np.clip(np.asarray(rh_pct, dtype=float), 1, 100)
    return (
        t * np.arctan(0.151977 * np.sqrt(r + 8.313659))
        + np.arctan(t + r)
        - np.arctan(r - 1.676331)
        + 0.00391838 * r**1.5 * np.arctan(0.023101 * r)
        - 4.686035
    )


def wet_bulb_psychrometric(t_c, rh_pct, pressure_kpa: float = 101.325, iters: int = 45):
    """
    Reference Tw by bisecting the psychrometric relation (slower, used for VALIDATION):
        e = es(Tw) - A*P*(T - Tw),  A = 0.00066*(1 + 0.00115*Tw)
    """
    t = np.asarray(t_c, dtype=float)
    r = np.clip(np.asarray(rh_pct, dtype=float), 1, 100)
    e_actual = saturation_vapour_pressure(t) * r / 100.0

    lo, hi = t - 40.0, t + 5.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        a = 0.00066 * (1 + 0.00115 * mid)
        e_mid = saturation_vapour_pressure(mid) - a * pressure_kpa * (t - mid)
        need_higher = e_mid < e_actual
        lo = np.where(need_higher, mid, lo)
        hi = np.where(need_higher, hi, mid)
    return (lo + hi) / 2


# --------------------------------------------------------------------------- #
# 3. Globe temperature
# --------------------------------------------------------------------------- #

def globe_temperature(t_c, wind_ms, solar_wm2):
    """
    Black-globe temperature from a steady-state energy balance.

        alpha*S/4 = (h_conv + h_rad) * (Tg - Ta)

    The /4 is the sphere's projected-to-surface area ratio -- forgetting it is the
    classic error that puts Tg ~50 °C above air temperature instead of ~10-15 °C.
    """
    t = np.asarray(t_c, dtype=float)
    v = np.maximum(np.asarray(wind_ms, dtype=float), 0.13)   # floor: free convection
    s = np.maximum(np.asarray(solar_wm2, dtype=float), 0.0)

    re = v * GLOBE_D / NU_AIR                                 # Reynolds
    nusselt = 2.0 + 0.6 * np.sqrt(re) * PR_AIR ** (1 / 3)     # Ranz-Marshall
    h_conv = nusselt * K_AIR / GLOBE_D
    h_rad = 4 * SIGMA * GLOBE_ABS * (t + 273.15) ** 3         # linearised radiation

    return t + (GLOBE_ABS * s) / (4.0 * (h_conv + h_rad))


# --------------------------------------------------------------------------- #
# 4. WBGT
# --------------------------------------------------------------------------- #

def wbgt_outdoor(t_c, rh_pct, wind_ms, solar_wm2):
    """
    Wet-Bulb Globe Temperature, full sun (ISO 7243):
        WBGT = 0.7*Tw + 0.2*Tg + 0.1*Ta
    At night (no sun) Tg -> Ta and this collapses to the shade/indoor form
    0.7*Tw + 0.3*Ta, which is handled automatically.
    """
    t = np.asarray(t_c, dtype=float)
    tw = wet_bulb_stull(t, rh_pct)
    tg = globe_temperature(t, wind_ms, solar_wm2)
    day = np.asarray(solar_wm2, dtype=float) > 20.0
    return np.where(day, 0.7 * tw + 0.2 * tg + 0.1 * t, 0.7 * tw + 0.3 * t)


def wbgt_shade(t_c, rh_pct):
    """Shade / indoor WBGT: 0.7*Tw + 0.3*Ta."""
    t = np.asarray(t_c, dtype=float)
    return 0.7 * wet_bulb_stull(t, rh_pct) + 0.3 * t


# --------------------------------------------------------------------------- #
# 5. Classification + work/rest guidance
# --------------------------------------------------------------------------- #

# (lower, colour, label, public guidance)
WBGT_BANDS = [
    (0.0,  "#22c55e", "Normal",  "No restriction. Maintain hydration."),
    (26.0, "#eab308", "Caution", "Increase fluids. Schedule heavy work before 11:00."),
    (29.0, "#f97316", "Danger",  "Hourly 10-min shaded breaks. Watch for cramps, dizziness."),
    (31.0, "#ef4444", "Critical", "Suspend outdoor labour 12:00-15:00. Activate cooling centres."),
    (32.0, "#a21caf", "Extreme", "Stop all non-essential outdoor work. Door-to-door wellness checks."),
]

HI_BANDS = [
    (0.0,  "#22c55e", "Normal",         "Comfortable."),
    (27.0, "#eab308", "Caution",        "Fatigue possible with prolonged exposure."),
    (32.0, "#f97316", "Extreme Caution","Heat cramps and exhaustion likely."),
    (39.0, "#ef4444", "Danger",         "Heat stroke probable with continued activity."),
    (51.0, "#a21caf", "Extreme Danger", "Heat stroke imminent. Medical emergency."),
]

# ACGIH-style work/rest per hour, by metabolic intensity (WBGT lower bounds)
WORK_REST = {
    "light":    [29.0, 30.0, 31.0, 31.5],   # -> 100%, 75%, 50%, 25%, 0%
    "moderate": [28.0, 29.0, 30.0, 31.0],
    "heavy":    [26.5, 28.0, 29.0, 30.0],
}


def _classify(value, bands):
    v = float(value)
    out = bands[0]
    for lo, *rest in bands:
        if v >= lo:
            out = (lo, *rest)
    return {"colour": out[1], "band": out[2], "guidance": out[3]}


def classify_wbgt(wbgt_c) -> dict:
    return _classify(wbgt_c, WBGT_BANDS)


def classify_heat_index(hi_c) -> dict:
    return _classify(hi_c, HI_BANDS)


def work_rest(wbgt_c, intensity: str = "moderate") -> str:
    """ACGIH-style work:rest allocation per hour at a given WBGT."""
    thr = WORK_REST.get(intensity, WORK_REST["moderate"])
    w = float(wbgt_c)
    if w < thr[0]:
        mins = 60
    elif w < thr[1]:
        mins = 45
    elif w < thr[2]:
        mins = 30
    elif w < thr[3]:
        mins = 15
    else:
        return "No work — suspend all physical activity"
    return f"{mins} min work : {60 - mins} min rest per hour ({intensity})"


# --------------------------------------------------------------------------- #
# 6. Vectorised pipeline over the Phase 1 DataFrame
# --------------------------------------------------------------------------- #

def compute_thermal(df: pd.DataFrame) -> pd.DataFrame:
    """Add thermal-stress columns to a Phase 1 hourly forecast frame."""
    out = df.copy()
    out["wind_ms"] = kmh_to_ms(out["wind_kmh"])
    solar = out.get("solar_wm2", pd.Series(0.0, index=out.index)).fillna(0.0)

    out["wet_bulb_c"] = np.round(wet_bulb_stull(out["temp_c"], out["rh_pct"]), 2)
    out["globe_c"] = np.round(globe_temperature(out["temp_c"], out["wind_ms"], solar), 2)
    out["wbgt_c"] = np.round(wbgt_outdoor(out["temp_c"], out["rh_pct"], out["wind_ms"], solar), 2)
    out["heat_index_c"] = np.round(heat_index(out["temp_c"], out["rh_pct"]), 2)

    cls = [classify_wbgt(v) for v in out["wbgt_c"]]
    out["stress_band"] = [c["band"] for c in cls]
    out["stress_colour"] = [c["colour"] for c in cls]
    out["is_daytime"] = (solar > 20).astype(int)
    return out


def daily_thermal(df: pd.DataFrame) -> pd.DataFrame:
    """Daily worst-case thermal stress per ward — the shape Phases 3-5 consume."""
    d = compute_thermal(df) if "wbgt_c" not in df.columns else df.copy()
    d["date"] = d["timestamp_local"].dt.date
    g = (
        d.groupby(["ward_id", "ward_name", "date"], as_index=False)
        .agg(
            tmax_c=("temp_c", "max"),
            tmin_c=("temp_c", "min"),
            rh_mean_pct=("rh_pct", "mean"),
            wbgt_peak_c=("wbgt_c", "max"),
            wbgt_mean_c=("wbgt_c", "mean"),
            hi_peak_c=("heat_index_c", "max"),
            solar_max_wm2=("solar_wm2", "max"),
            wind_mean_kmh=("wind_kmh", "mean"),
        )
    )
    cls = [classify_wbgt(v) for v in g["wbgt_peak_c"]]
    g["stress_band"] = [c["band"] for c in cls]
    g["stress_colour"] = [c["colour"] for c in cls]
    g["work_rest"] = [work_rest(v) for v in g["wbgt_peak_c"]]
    return g.round(2).sort_values(["date", "ward_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 7. Heatwave detection (IMD criteria)
# --------------------------------------------------------------------------- #

IMD_PRESETS = {
    "coastal": {"abs_c": 37.0, "departure_c": 4.5, "severe_c": 40.0, "severe_departure_c": 6.4},
    "plains":  {"abs_c": 40.0, "departure_c": 4.5, "severe_c": 47.0, "severe_departure_c": 6.4},
    "hills":   {"abs_c": 30.0, "departure_c": 4.5, "severe_c": 35.0, "severe_departure_c": 6.4},
}


def heatwave_flags(daily: pd.DataFrame, normals: pd.DataFrame | None = None,
                   region: str = "coastal") -> pd.DataFrame:
    """
    Flag heatwave days per IMD criteria.

    Heat wave      : Tmax >= abs_c  OR  Tmax - normal >= departure_c
    Severe         : Tmax >= severe_c  OR  departure >= severe_departure_c

    `normals` (ward_id, month, normal_tmax_c) gives a real climatology. If omitted,
    the ward's own mean over the supplied window is used as a pseudo-normal
    (fine for a 5-day demo, NOT for production -- say so in your presentation).
    """
    p = IMD_PRESETS[region]
    d = daily.copy()

    if normals is not None:
        d["month"] = pd.to_datetime(d["date"]).dt.month
        d = d.merge(normals[["ward_id", "month", "normal_tmax_c"]], on=["ward_id", "month"], how="left")
    else:
        base = d.groupby("ward_id")["tmax_c"].transform("mean")
        d["normal_tmax_c"] = base.round(1)

    d["departure_c"] = (d["tmax_c"] - d["normal_tmax_c"]).round(2)
    d["is_heatwave"] = (d["tmax_c"] >= p["abs_c"]) | (d["departure_c"] >= p["departure_c"])
    d["is_severe"] = (d["tmax_c"] >= p["severe_c"]) | (d["departure_c"] >= p["severe_departure_c"])
    d["heatwave_label"] = np.select(
        [d["is_severe"], d["is_heatwave"]], ["Severe Heat Wave", "Heat Wave"], default="None"
    )
    return d.drop(columns=["month"], errors="ignore")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    pd.set_option("display.width", 170)
    from core.weather import get_forecast

    print("=" * 74)
    print("A) Wet-bulb validation: Stull(2011) vs psychrometric inversion")
    print("=" * 74)
    grid = [(t, rh) for t in (20, 25, 30, 35, 40, 45) for rh in (10, 30, 50, 70, 90)]
    tw_s = wet_bulb_stull([g[0] for g in grid], [g[1] for g in grid])
    tw_p = wet_bulb_psychrometric([g[0] for g in grid], [g[1] for g in grid])
    dev = np.abs(tw_s - tw_p)
    print(pd.DataFrame({"t_c": [g[0] for g in grid], "rh_pct": [g[1] for g in grid],
                        "tw_stull": tw_s.round(2), "tw_psychro": tw_p.round(2),
                        "dev": dev.round(3)}).to_string(index=False))
    humid = np.array([g[1] for g in grid]) >= 50
    print(f"\nfull grid   : mean {dev.mean():.3f} C, max {dev.max():.3f} C")
    print(f"RH >= 50%   : mean {dev[humid].mean():.3f} C, max {dev[humid].max():.3f} C   <- the regime that matters")
    print("note: worst deviation sits at RH <= 10%, outside Stull's validated envelope.")

    print("\n" + "=" * 74)
    print("B) Heat Index validation vs NWS published chart")
    print("=" * 74)
    # (T_C, RH%, NWS chart value in C)  -- 80F/80%=84F, 90F/60%=100F, 90F/70%=105F, 100F/40%=109F
    cases = [(26.7, 80, 28.9), (32.2, 60, 37.8), (32.2, 70, 40.6), (37.8, 40, 42.8), (37.8, 55, 51.1)]
    rows = []
    for t, rh, expect in cases:
        got = float(heat_index(t, rh))
        rows.append({"t_c": t, "rh_pct": rh, "nws_expected_c": expect,
                     "our_hi_c": round(got, 2), "dev": round(got - expect, 2)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n" + "=" * 74)
    print("C) Globe temperature sanity (should sit ~8-15 C above air in full sun)")
    print("=" * 74)
    print(pd.DataFrame([
        {"t_c": 33, "wind_ms": 0.5, "solar_wm2": s,
         "globe_c": round(float(globe_temperature(33, 0.5, s)), 2),
         "delta": round(float(globe_temperature(33, 0.5, s)) - 33, 2)}
        for s in (0, 200, 400, 700, 900)
    ]).to_string(index=False))

    print("\n" + "=" * 74)
    print("D) Live run over real Open-Meteo data (all 141 wards)")
    print("=" * 74)
    df = get_forecast()
    th = compute_thermal(df)
    print(f"{len(th):,} ward-hours scored.")
    worst = th.nlargest(8, "wbgt_c")[
        ["ward_name", "timestamp_local", "temp_c", "rh_pct", "wind_kmh",
         "solar_wm2", "wet_bulb_c", "globe_c", "wbgt_c", "heat_index_c", "stress_band"]
    ]
    print("\nWorst 8 ward-hours:")
    print(worst.to_string(index=False))

    daily = heatwave_flags(daily_thermal(df))
    print("\nHighest-risk ward-days:")
    print(daily.nlargest(8, "wbgt_peak_c")[
        ["ward_name", "date", "tmax_c", "wbgt_peak_c", "hi_peak_c", "stress_band", "work_rest"]
    ].to_string(index=False))

    th.to_csv("data/processed/thermal_hourly.csv", index=False)
    daily.to_csv("data/processed/thermal_daily.csv", index=False)
    print("\nSaved -> data/processed/thermal_hourly.csv, thermal_daily.csv")
