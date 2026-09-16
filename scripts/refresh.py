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

    python scripts/refresh.py
"""
from __future__ import annotations

import time

import pandas as pd

from core.risk import daily_risk
from core.thermal import compute_thermal, daily_thermal, heatwave_flags
from core.weather import get_forecast, load_wards

PROC = "data/processed"


def main() -> None:
    pd.set_option("display.width", 180)
    wards = load_wards()
    print(f"Loaded {len(wards)} wards")

    # 1. Weather -- bypass the cache entirely so we truly hit the network.
    t0 = time.time()
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
    from datetime import date

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
    main()
