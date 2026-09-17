"""
Force-refresh the whole pipeline from the live Open-Meteo API.

Why this exists
---------------
The forecast cache is a file whose freshness is judged by mtime and
CACHE_TTL_MIN. When the workspace is restored from a snapshot, every file's
mtime is reset to "now", so a three-day-old forecast looks brand new and
`get_forecast(use_cache=True)` happily serves stale data forever. That quietly
starves Phase 5: with only one future day in the table, no alert can ever show
more than one day of lead time -- which is exactly the requirement.

Run this after restoring a snapshot, or whenever you want current numbers:

    python scripts/refresh.py             # live: forces a new Open-Meteo fetch
    python scripts/refresh.py --offline   # no network: re-scores the cached fetch

`--offline` exists for network-restricted environments (air-gapped CI, a demo
laptop with no signal). It replays the *real* forecast already on disk in
`data/cache/` and says so loudly, including when that fetch was made -- it never
synthesises weather. Physics, scoring and CSV writes are identical either way,
so it is also a regression harness: same inputs must give the same 846 rows.
"""
from __future__ import annotations

import argparse
import time

import pandas as pd

from core.risk import daily_risk
from core.thermal import compute_thermal, daily_thermal, heatwave_flags
from core.weather import get_forecast, load_cache, load_wards

PROC = "data/processed"


def _cached_forecast() -> pd.DataFrame:
    """The last real Open-Meteo fetch on disk, TTL ignored on purpose."""
    df = load_cache(max_age_min=10**9)
    if df is None or df.empty:
        raise SystemExit(
            "--offline needs a cached forecast in data/cache/, and there is none.\n"
            "Run `python -m scripts.refresh` once on a machine with network access."
        )
    return df


def main(offline: bool = False) -> None:
    pd.set_option("display.width", 180)
    wards = load_wards()
    print(f"Loaded {len(wards)} wards")

    # 1. Weather -- live mode bypasses the cache entirely so we truly hit the
    #    network; --offline replays the cached fetch instead.
    t0 = time.time()
    if offline:
        df = _cached_forecast()
        fetched = df["fetched_at"].iloc[0]
        print("OFFLINE : no network call -- replaying the cached Open-Meteo fetch")
        print(f"          cached at {fetched} (NOT a live pull; re-run without "
              f"--offline for current weather)")
        # Keep data/processed in step with the rows scored below, exactly as
        # get_forecast(save=True) would in live mode.
        df.to_csv(f"{PROC}/forecast_hourly.csv", index=False)
    else:
        df = get_forecast(wards, use_cache=False)
    print(f"Weather : {len(df):,} ward-hours in {time.time() - t0:.1f}s")
    print(f"Window  : {df.timestamp_local.min()}  ->  {df.timestamp_local.max()}")

    # 2. Thermal stress (Phase 2).
    th = compute_thermal(df)
    daily_th = heatwave_flags(daily_thermal(df))
    th.to_csv(f"{PROC}/thermal_hourly.csv", index=False)
    daily_th.to_csv(f"{PROC}/thermal_daily.csv", index=False)
    print(f"Thermal : {len(th):,} ward-hours, {len(daily_th):,} ward-days")

    # 3. Risk index (Phase 3).
    daily = daily_risk(df, wards, temp_offset_c=0.0)
    daily.to_csv(f"{PROC}/risk_daily.csv", index=False)
    print(f"Risk    : {len(daily):,} ward-days")
    print(f"Dates   : {daily['date'].min()} -> {daily['date'].max()}")

    # 4. What the alert engine will actually see.
    from core.alerts import (
        DEFAULT_MIN_LEAD_DAYS,
        DEFAULT_RISK_THRESHOLD,
        find_active_now,
        find_upcoming_events,
    )

    # Use the engine's own defaults, never a hard-coded copy. The threshold was
    # recalibrated 65 -> 60 when the Census social block rebalanced the
    # vulnerability index; a stale literal here silently reported
    # "0 wards queued" while /alerts/plan was correctly warning 6 wards.
    print(f"  alert engine defaults: threshold={DEFAULT_RISK_THRESHOLD}, "
          f"lead>={DEFAULT_MIN_LEAD_DAYS}d")
    for lead in (1, 2, 3):
        up = find_upcoming_events(
            daily, min_lead_days=lead, risk_threshold=DEFAULT_RISK_THRESHOLD
        )
        print(f"  min_lead_days={lead}: {len(up):3d} wards queued"
              + (f", lead times {sorted(int(x) for x in up['lead_days'].unique())}"
                 if len(up) else ""))
    act = find_active_now(daily, risk_threshold=DEFAULT_RISK_THRESHOLD)
    print(f"  active today        : {len(act):3d} wards (nowcasts, not warnings)")
    print("\nDone. Restart the API if it is running so it re-reads the CSVs.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Re-fetch the forecast and re-score every ward.")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="skip the network and replay the cached Open-Meteo fetch from data/cache/",
    )
    args = ap.parse_args()
    main(offline=args.offline)
