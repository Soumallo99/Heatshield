"""
PHASE 7a — Unattended scheduler.

Until now the pipeline only ran when somebody typed `python -m scripts.refresh`.
An early-warning system that only warns when a human remembers to run it is a
demo, not a warning system. This is the piece that makes it run by itself.

Each cycle:
    1. pull the forecast          (core.weather, bypassing the cache)
    2. score thermal stress       (core.thermal)
    3. score risk                 (core.risk)
    4. ARCHIVE the snapshot       -> data/archive/risk_<run>.csv (capped at 400)
    5. find crossings with lead   (core.alerts.find_upcoming_events)
    6. dispatch                   (dry-run unless explicitly told otherwise)

Step 4 is the quiet one that matters most: you cannot measure forecast skill
retroactively, because we never kept what we forecast. Archiving every run means
`scripts/hindcast.py` can, from the first cycle onwards, answer "when the system
said Danger four days out, was it right?" — with real numbers.

Usage
-----
    python -m scripts.schedule                       # every 6 h, dry-run
    python -m scripts.schedule --interval-minutes 60
    python -m scripts.schedule --once                # single cycle, then exit
    python -m scripts.schedule --live                # real SMS (needs creds AND
                                                     # HS_ALLOW_LIVE_SEND=1)

Stdlib only — no cron, no APScheduler, no extra dependency. Runs anywhere Python
runs; swap in systemd/cron if you want OS-level supervision.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core.alerts import (DEFAULT_MIN_LEAD_DAYS, DEFAULT_RISK_THRESHOLD,
                         dispatch, filter_already_sent, find_active_now,
                         find_upcoming_events, live_send_allowed)
from core.config import DATA_DIR, PROCESSED_DIR
from core.risk import daily_risk
from core.thermal import compute_thermal, daily_thermal, heatwave_flags
from core.weather import get_forecast, load_wards

ARCHIVE_DIR = DATA_DIR / "archive"
RUN_LOG = PROCESSED_DIR / "scheduler_runs.jsonl"

DEFAULT_INTERVAL_MIN = 6 * 60

_stop = False


def _handle_stop(signum, _frame):
    global _stop
    _stop = True
    print(f"\n[{_ts()}] signal {signum} received — finishing this cycle, then stopping.")


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def prune_archive(keep: int = 400) -> int:
    """
    Cap the snapshot history.

    A daemon that writes a file every cycle and never deletes anything is a
    disk-filling bug waiting to be discovered at 3am. 400 snapshots is ~100 days
    at four cycles a day — far more than enough to compute skill curves, and
    bounded.
    """
    if not ARCHIVE_DIR.exists():
        return 0
    files = sorted(ARCHIVE_DIR.glob("risk_*.csv"))
    if len(files) <= keep:
        return 0
    for f in files[:-keep]:
        try:
            f.unlink()
        except OSError:
            pass
    return len(files) - keep


def archive_snapshot(daily: pd.DataFrame, run_at: datetime) -> Path | None:
    """
    Persist what we forecast, keyed by when we forecast it.

    The filename carries the run time and every row carries its own target date,
    so the hindcast can join forecast(made at T, for date D) against actual(D)
    and derive a lead time of D - T.
    """
    if daily is None or daily.empty:
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    out = daily.copy()
    out["run_at"] = run_at.isoformat(timespec="seconds")
    path = ARCHIVE_DIR / f"risk_{run_at.strftime('%Y%m%dT%H%M%S')}.csv"
    out.to_csv(path, index=False)
    return path


def run_cycle(threshold: float, lead_days: int, live: bool, do_archive: bool) -> dict:
    started = datetime.now()
    rec: dict = {"started_at": started.isoformat(timespec="seconds")}

    wards = load_wards()
    df = get_forecast(wards, use_cache=False)
    rec["ward_hours"] = int(len(df))

    th = compute_thermal(df)
    daily_th = heatwave_flags(daily_thermal(df))
    th.to_csv(PROCESSED_DIR / "thermal_hourly.csv", index=False)
    daily_th.to_csv(PROCESSED_DIR / "thermal_daily.csv", index=False)

    daily = daily_risk(df, wards, temp_offset_c=0.0)
    daily.to_csv(PROCESSED_DIR / "risk_daily.csv", index=False)
    rec["ward_days"] = int(len(daily))
    rec["horizon"] = f"{daily['date'].min()} -> {daily['date'].max()}"

    if do_archive:
        p = archive_snapshot(daily, started)
        rec["archived"] = str(p) if p else None
        rec["pruned"] = prune_archive()

    events = find_upcoming_events(daily, min_lead_days=lead_days, risk_threshold=threshold)
    pending = filter_already_sent(events)
    active = find_active_now(daily, risk_threshold=threshold)

    rec["threshold"] = threshold
    rec["lead_days"] = lead_days
    rec["events"] = int(len(events))
    rec["pending"] = int(len(pending))
    rec["active_now"] = int(len(active))
    rec["live"] = bool(live)

    if pending.empty:
        rec["dispatched"] = 0
        rec["note"] = "no new events with sufficient lead time"
    else:
        try:
            log = dispatch(pending, dry_run=not live, per_ward=True)
            rec["dispatched"] = int(len(log))
            rec["status_counts"] = log["status"].value_counts().to_dict()
        except PermissionError as exc:
            # Refusing an unsafe live send is a normal outcome, not a crash.
            rec["dispatched"] = 0
            rec["refused"] = str(exc)
        except Exception:                                   # noqa: BLE001
            rec["dispatched"] = 0
            rec["error"] = traceback.format_exc(limit=3)

    rec["seconds"] = round((datetime.now() - started).total_seconds(), 1)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description="HeatShield unattended scheduler")
    ap.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MIN)
    ap.add_argument("--threshold", type=float, default=DEFAULT_RISK_THRESHOLD)
    ap.add_argument("--lead-days", type=int, default=DEFAULT_MIN_LEAD_DAYS)
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--live", action="store_true",
                    help="actually send (needs Twilio creds AND HS_ALLOW_LIVE_SEND=1)")
    ap.add_argument("--no-archive", action="store_true", help="skip writing forecast snapshots")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    if args.live:
        allowed, reason = live_send_allowed()
        if not allowed:
            print(f"[{_ts()}] REFUSING to start in live mode: {reason}")
            print("       set HS_ALLOW_LIVE_SEND=1 and fill in the Twilio vars in .env")
            sys.exit(2)
        print(f"[{_ts()}] LIVE MODE — real messages will be sent.")

    mode = "once" if args.once else f"every {args.interval_minutes} min"
    print(f"[{_ts()}] HeatShield scheduler starting ({mode})")
    print(f"         threshold={args.threshold}  lead>={args.lead_days}d  "
          f"dry_run={not args.live}  archive={not args.no_archive}")

    cycle = 0
    while True:
        cycle += 1
        try:
            rec = run_cycle(args.threshold, args.lead_days, args.live, not args.no_archive)
            rec["cycle"] = cycle
            with RUN_LOG.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"[{_ts()}] cycle {cycle}: "
                  f"{rec['ward_hours']:,} ward-hours · "
                  f"{rec['events']} events · {rec.get('dispatched', 0)} dispatched"
                  + (f" · REFUSED: {rec['refused']}" if rec.get("refused") else "")
                  + (f" · {rec['seconds']}s"))
        except Exception:                                   # noqa: BLE001
            # One bad cycle must never kill the daemon — the next one may work.
            print(f"[{_ts()}] cycle {cycle} FAILED:\n{traceback.format_exc(limit=5)}")
            with RUN_LOG.open("a") as f:
                f.write(json.dumps({"cycle": cycle, "error": traceback.format_exc(limit=3)}) + "\n")

        if args.once or _stop:
            break

        next_at = datetime.now() + timedelta(minutes=args.interval_minutes)
        print(f"[{_ts()}] sleeping until {next_at.strftime('%H:%M:%S')}")
        # sleep in small slices so a stop signal is honoured promptly
        deadline = time.time() + args.interval_minutes * 60
        while time.time() < deadline and not _stop:
            time.sleep(min(5, max(0.1, deadline - time.time())))

    print(f"[{_ts()}] scheduler stopped after {cycle} cycle(s).")


if __name__ == "__main__":
    main()
