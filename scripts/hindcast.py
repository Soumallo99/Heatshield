"""
PHASE 7b — Hindcast and forecast-skill evaluation.

Two different questions, and it matters which one you can answer today.

(A) RETROSPECTIVE RUN — works immediately.
    Replay the model over OBSERVED past weather (Open-Meteo archive, keyless)
    instead of forecast weather. This does not measure forecasting skill, but it
    does prove the pipeline behaves sensibly on real weather: how many ward-days
    crossed the alert threshold, which wards, which days, what the band split
    looks like across a real month. If this came back with zero Danger days in
    August, the thresholds would be wrong — so it is a genuine sanity check.

(B) FORECAST SKILL — needs history we have only just started collecting.
    "When the system said Danger on D+4, was it right?" requires knowing what we
    forecast, which we never stored until now. scripts/schedule.py archives every
    run to data/archive/, so this section comes alive after the scheduler has
    been running longer than the archive lag (~5 days). Until then it says so
    plainly rather than inventing a number.

Usage
-----
    python -m scripts.hindcast                 # last 30 days, lag 5
    python -m scripts.hindcast --days 60
    python -m scripts.hindcast --days 90 --lag 7 --threshold 60
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from core.alerts import DEFAULT_RISK_THRESHOLD
from core.config import DATA_DIR
from core.risk import daily_risk
from core.thermal import compute_thermal, daily_thermal, heatwave_flags
from core.weather import get_archive, load_wards

ARCHIVE_DIR = DATA_DIR / "archive"

BAND_ORDER = ["Normal", "Caution", "Danger", "Critical", "Extreme"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def load_forecast_snapshots() -> pd.DataFrame:
    """Every archived run, stacked. Empty frame (with columns) if none yet."""
    cols = ["ward_id", "date", "risk_score", "wbgt_peak_c", "risk_band", "run_at"]
    files = sorted(ARCHIVE_DIR.glob("risk_*.csv")) if ARCHIVE_DIR.exists() else []
    if not files:
        return pd.DataFrame(columns=cols)

    frames = []
    for f in files:
        try:
            d = pd.read_csv(f)
        except Exception:                                   # noqa: BLE001
            continue
        if "run_at" not in d.columns:
            # filename carries it: risk_YYYYMMDDTHHMMSS.csv
            stamp = f.stem.replace("risk_", "")
            try:
                run_at = pd.to_datetime(stamp, format="%Y%m%dT%H%M%S").isoformat()
            except Exception:                               # noqa: BLE001
                continue
            d["run_at"] = run_at
        keep = [c for c in cols if c in d.columns]
        frames.append(d[keep])

    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)


def contingency(fcst: pd.Series, act: pd.Series, threshold: float) -> dict:
    """2x2 skill counts against a threshold, plus the standard ratios."""
    f = fcst >= threshold
    a = act >= threshold
    hits = int((f & a).sum())
    misses = int((~f & a).sum())
    false_alarms = int((f & ~a).sum())
    correct_rejects = int((~f & ~a).sum())
    n = hits + misses + false_alarms + correct_rejects

    pod = hits / (hits + misses) if (hits + misses) else float("nan")
    far = false_alarms / (hits + false_alarms) if (hits + false_alarms) else float("nan")
    csi = hits / (hits + misses + false_alarms) if (hits + misses + false_alarms) else float("nan")
    return {
        "n": n, "hits": hits, "misses": misses,
        "false_alarms": false_alarms, "correct_rejects": correct_rejects,
        "POD": pod, "FAR": far, "CSI": csi,
    }


# --------------------------------------------------------------------------- #
# (A) retrospective run on observed weather
# --------------------------------------------------------------------------- #

def retrospective(days: int, lag: int, threshold: float) -> pd.DataFrame:
    end = date.today() - timedelta(days=lag)
    start = end - timedelta(days=days - 1)

    print("=" * 78)
    print("(A) RETROSPECTIVE RUN — model replayed on OBSERVED weather")
    print("=" * 78)
    print(f"  window      : {start} -> {end}  ({days} days, ending {lag}d before today)")
    print(f"  source      : Open-Meteo archive API (reanalysis), keyless")
    print(f"  threshold   : risk >= {threshold}")
    print("  NOTE: this validates model behaviour on real weather, NOT forecast skill.\n")

    wards = load_wards()
    df = get_archive(wards, start.isoformat(), end.isoformat())
    print(f"  pulled      : {len(df):,} ward-hours across {df['ward_id'].nunique()} wards")

    th = compute_thermal(df)
    daily_th = heatwave_flags(daily_thermal(df))
    daily = daily_risk(df, wards, temp_offset_c=0.0)

    print(f"  scored      : {len(daily):,} ward-days\n")

    # ---- band distribution
    counts = daily["risk_band"].value_counts()
    print("  Band distribution over the window:")
    for b in BAND_ORDER:
        if b in counts:
            pct = 100 * counts[b] / len(daily)
            bar = "#" * max(1, round(pct / 2))
            print(f"    {b:<9} {counts[b]:>6}  {pct:5.1f}%  {bar}")

    # ---- threshold crossings
    over = daily[daily["risk_score"] >= threshold]
    dates_hit = sorted(over["date"].unique())
    wards_hit = sorted(over["ward_id"].unique())
    print(f"\n  Ward-days at or above {threshold}: {len(over):,} "
          f"({100 * len(over) / len(daily):.2f}% of all ward-days)")
    print(f"  Distinct days affected : {len(dates_hit)} of {daily['date'].nunique()}")
    print(f"  Distinct wards affected: {len(wards_hit)} of {daily['ward_id'].nunique()}")

    if len(over):
        per_day = over.groupby("date").agg(
            wards=("ward_id", "nunique"),
            max_risk=("risk_score", "max"),
            max_wbgt=("wbgt_peak_c", "max"),
        ).round(1)
        print("\n  Worst days in the window:")
        print(per_day.sort_values("max_risk", ascending=False).head(8).to_string())

        top_w = over.groupby(["ward_id", "ward_name"]).agg(
            days=("date", "nunique"),
            peak=("risk_score", "max"),
        ).sort_values(["days", "peak"], ascending=False).head(8).round(1)
        print("\n  Wards most often over threshold:")
        print(top_w.to_string())
    else:
        print("\n  No ward-day reached the threshold in this window.")
        print("  That is a real finding: either the window was genuinely cool, or the")
        print("  threshold is set too high for this city. Check the max risk below.")
        print(f"  max risk observed = {daily['risk_score'].max():.1f}")

    print(f"\n  Risk score over the window: "
          f"min {daily['risk_score'].min():.1f} · "
          f"median {daily['risk_score'].median():.1f} · "
          f"max {daily['risk_score'].max():.1f}")
    print(f"  Peak WBGT: min {daily['wbgt_peak_c'].min():.1f} · "
          f"median {daily['wbgt_peak_c'].median():.1f} · "
          f"max {daily['wbgt_peak_c'].max():.1f} °C")

    daily.to_csv(DATA_DIR / "processed" / "hindcast_actual_daily.csv", index=False)
    print(f"\n  saved -> data/processed/hindcast_actual_daily.csv")
    return daily


# --------------------------------------------------------------------------- #
# (B) forecast skill
# --------------------------------------------------------------------------- #

def skill(actual: pd.DataFrame, threshold: float) -> None:
    print("\n" + "=" * 78)
    print("(B) FORECAST SKILL — did yesterday's forecast match what happened?")
    print("=" * 78)

    snaps = load_forecast_snapshots()
    if snaps.empty:
        print("  No archived forecast snapshots yet.")
        print("  scripts/schedule.py writes one per cycle to data/archive/.")
        _explain_skill_timeline()
        return

    snaps["date"] = pd.to_datetime(snaps["date"]).dt.date
    snaps["run_date"] = pd.to_datetime(snaps["run_at"]).dt.date
    snaps["lead_days"] = snaps.apply(lambda r: (r["date"] - r["run_date"]).days, axis=1)

    act = actual.copy()
    act["date"] = pd.to_datetime(act["date"]).dt.date

    merged = snaps.merge(
        act[["ward_id", "date", "risk_score", "wbgt_peak_c"]],
        on=["ward_id", "date"], suffixes=("_fcst", "_act"),
    )

    # only lead times that are verifiable: target date must be in the past
    merged = merged[merged["lead_days"] >= 0]

    print(f"  snapshots loaded : {snaps['run_at'].nunique()} runs, "
          f"{len(snaps):,} forecast ward-days")
    print(f"  verifiable pairs : {len(merged):,} (forecast joined to observed)\n")

    if merged.empty:
        print("  Snapshots exist but none overlap the observed window yet.")
        _explain_skill_timeline()
        return

    print(f"  {'lead':>4}  {'n':>6}  {'MAE WBGT':>9}  {'bias':>7}  "
          f"{'MAE risk':>9}  {'bias':>7}  {'POD':>5}  {'FAR':>5}  {'CSI':>5}")
    print("  " + "-" * 74)
    for lead, g in merged.groupby("lead_days"):
        mae_w = float(np.mean(np.abs(g["wbgt_peak_c_fcst"] - g["wbgt_peak_c_act"])))
        bia_w = float(np.mean(g["wbgt_peak_c_fcst"] - g["wbgt_peak_c_act"]))
        mae_r = float(np.mean(np.abs(g["risk_score_fcst"] - g["risk_score_act"])))
        bia_r = float(np.mean(g["risk_score_fcst"] - g["risk_score_act"]))
        c = contingency(g["risk_score_fcst"], g["risk_score_act"], threshold)
        print(f"  {lead:>4}  {len(g):>6}  {mae_w:>9.2f}  {bia_w:>+7.2f}  "
              f"{mae_r:>9.2f}  {bia_r:>+7.2f}  "
              f"{c['POD']:>5.2f}  {c['FAR']:>5.2f}  {c['CSI']:>5.2f}")

    print("\n  POD = probability of detection (of the events that happened, how many we caught)")
    print("  FAR = false alarm ratio (of the warnings we issued, how many were wrong)")
    print("  CSI = critical success index (overall skill, 1.0 perfect)")
    print("  bias = mean(forecast - observed): + means we over-warn.")


def _explain_skill_timeline() -> None:
    print("\n  Why: forecast skill is measured by comparing a forecast to what")
    print("  actually happened — which means the archived prediction must be older")
    print("  than the event, and the event must be old enough to be in the archive")
    print("  (reanalysis lags the present by a few days).")
    print("\n  Start the scheduler and these numbers fill in on their own:")
    print("      python -m scripts.schedule --interval-minutes 360")
    print("  First skill numbers appear roughly a week later, and improve daily.")


def main() -> None:
    ap = argparse.ArgumentParser(description="HeatShield hindcast / skill evaluation")
    ap.add_argument("--days", type=int, default=30, help="length of the retrospective window")
    ap.add_argument("--lag", type=int, default=5,
                    help="end the window this many days before today (archive lag)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_RISK_THRESHOLD)
    args = ap.parse_args()

    actual = retrospective(args.days, args.lag, args.threshold)
    skill(actual, args.threshold)


if __name__ == "__main__":
    main()
