"""
PHASE 5 — Alerting with lead time
=================================
The point of a forecast is warning BEFORE the event. This module scans the ward-day
risk table for the first day each ward crosses a threshold and raises an alert only
when there is at least `min_lead_days` of warning (default 1 day).

    today is D+0. An event on D+0 or earlier is a nowcast, not a warning —
    the intervention window has closed, so we deliberately stay quiet
    rather than send an alert nobody can act on.

Dispatch is DRY-RUN by default: it prints and logs every message it would send,
and only touches Twilio when credentials are present and dry_run=False. That way
you cannot spam real numbers by accident during development.

Run:  python -m core.alerts                # plan only, sends nothing
      python -m core.alerts --send         # actually dispatch (needs Twilio creds)
      python -m core.alerts --threshold 75 --lead 2
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from core.config import (ALERT_TO, ALLOW_LIVE_SEND, TWILIO_FROM, TWILIO_SID,
                        TWILIO_TOKEN)

LOG_PATH = Path("data/processed/alert_log.csv")

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEFAULT_MIN_LEAD_DAYS = 1      # warn at least 1 day ahead
# Alert threshold, upper "Danger" band (bands: Caution 25-50, Danger 50-75).
# Was 65.0, but adding the Census social block rebalanced the vulnerability
# index (urban form 0.65 / social 0.35) and pulled peak risk down, so 65 left
# only a single ward warned. 60 keeps the queue actionable without spamming
# every ward in Danger. Tunable per-call and via ?threshold= on /alerts/plan.
DEFAULT_RISK_THRESHOLD = 60.0
DEDUP_HOURS = 12               # don't re-alert the same ward+event within this window
WEB_BASE = os.getenv("HS_WEB_BASE", "https://heatshield.app")

DAYNAME = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

GUIDANCE = {
    "Caution": "Increase fluids. Schedule heavy work before 11:00.",
    "Danger": "Hourly shaded breaks. Watch for cramps and dizziness.",
    "Critical": "Suspend non-essential outdoor labour 12:00–15:00.",
    "Extreme": "Stop all outdoor work. Activate cooling centres.",
}


# --------------------------------------------------------------------------- #
# 1. Detection
# --------------------------------------------------------------------------- #

def find_upcoming_events(
    daily: pd.DataFrame,
    min_lead_days: int = DEFAULT_MIN_LEAD_DAYS,
    risk_threshold: float = DEFAULT_RISK_THRESHOLD,
    today: date | None = None,
) -> pd.DataFrame:
    """
    First threshold crossing per ward that still has actionable lead time.

    Returns one row per ward: event date, lead time in days, peak values,
    severity, and the guidance text. Wards whose crossing is today or in the
    past are excluded — there is nothing to warn about any more.
    """
    today = today or date.today()
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date

    # Restrict the search to days that still leave enough warning, then take the
    # FIRST crossing inside that window. Taking the global first crossing instead
    # would suppress exactly the case that matters most: a ward that is hot TODAY
    # and hot again TOMORROW got no warning for tomorrow, because its first
    # crossing (today) had zero lead time and the ward was discarded outright.
    cutoff = today + timedelta(days=min_lead_days)
    events = []
    for ward_id, g in d.groupby("ward_id"):
        g = g.sort_values("date")
        hit = g[(g["risk_score"] >= risk_threshold) & (g["date"] >= cutoff)]
        if hit.empty:
            continue
        ev = hit.iloc[0]
        lead = (ev["date"] - today).days
        if lead < min_lead_days:
            continue  # too late to act — a nowcast, not a warning

        # severity = worst band anywhere in the remaining horizon
        band_order = ["Normal", "Caution", "Danger", "Critical", "Extreme"]
        worst = max(g["risk_band"], key=lambda b: band_order.index(b) if b in band_order else 0)

        events.append({
            "ward_id": int(ward_id),
            "ward_name": ev["ward_name"],
            "event_date": ev["date"],
            "lead_days": int(lead),
            "risk_score": float(ev["risk_score"]),
            "risk_band": ev["risk_band"],
            "worst_band": worst,
            "wbgt_peak_c": float(ev.get("wbgt_peak_c", float("nan"))),
            "tmax_ward_c": float(ev.get("tmax_adj_c", float("nan"))),
            "uhi_delta_c": float(ev.get("uhi_delta_c", float("nan"))),
            "population": int(ev.get("population", 0)),
            "exposed_population": int(ev.get("exposed_population", 0)),
            "guidance": GUIDANCE.get(ev["risk_band"], "Stay hydrated, avoid midday sun."),
        })

    if not events:
        return pd.DataFrame(columns=["ward_id", "ward_name", "event_date", "lead_days", "risk_score"])
    return (pd.DataFrame(events)
            .sort_values(["lead_days", "risk_score"], ascending=[True, False])
            .reset_index(drop=True))


def find_active_now(daily: pd.DataFrame, risk_threshold: float = DEFAULT_RISK_THRESHOLD,
                    today: date | None = None) -> pd.DataFrame:
    """
    Wards already at or above the threshold TODAY (lead time 0 or negative).

    These are deliberately NOT sent as warnings — the intervention window has
    closed. They get a different message: shelter now, don't wait for a warning.
    """
    today = today or date.today()
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    # TODAY only. The forecast also contains yesterday (past_days=1); counting it
    # would double-count every ward and inflate this number past 141.
    today_rows = d[(d["date"] == today) & (d["risk_score"] >= risk_threshold)]
    if today_rows.empty:
        return today_rows
    return today_rows.sort_values("risk_score", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 2. Message
# --------------------------------------------------------------------------- #

def _num(ev: dict, key: str, default=float("nan")) -> float:
    """Read a numeric field defensively — round-trips through JSON/CSV can turn
    these into None or strings, and an alert must never fail to compose."""
    try:
        v = float(ev.get(key, default))
    except (TypeError, ValueError):
        return float("nan")
    return v


def compose_message(ev: dict) -> str:
    """WhatsApp/SMS body. Short enough for one SMS segment where possible."""
    d = ev["event_date"]
    day = DAYNAME[d.weekday()] if isinstance(d, date) else ""
    uhi = ev.get("uhi_delta_c")
    try:
        uhi = float(uhi)
    except (TypeError, ValueError):
        uhi = float("nan")
    # `uhi == uhi` is False only for NaN; the float() cast above makes None and
    # stray strings safe too (None == None is True, so the NaN trick alone
    # would fall through to `None > 0.05` and raise).
    uhi_txt = f" (city +{uhi:.1f}°C heat island)" if uhi == uhi and uhi > 0.05 else ""

    lines = [
        f"HeatShield {ev['risk_band'].upper()} HEAT WARNING",
        f"{ev['ward_name']} — {day} {d.strftime('%d %b')}, in {ev['lead_days']} day(s)",
        "",
        f"Risk {_num(ev, 'risk_score'):.0f}/100 · peak WBGT {_num(ev, 'wbgt_peak_c'):.1f}°C",
        f"Ward peak temp {_num(ev, 'tmax_ward_c'):.1f}°C{uhi_txt}",
        "",
        f"Action: {ev.get('guidance', 'Stay hydrated, avoid midday sun.')}",
        f"About {_num(ev, 'exposed_population', 0):,.0f} residents exposed.",
        "",
        f"Details: {WEB_BASE}/ward/{ev['ward_id']}",
        "Reply STOP to opt out.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 3. Dedupe
# --------------------------------------------------------------------------- #

def _load_log() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame(columns=["sent_at", "ward_id", "event_date", "risk_band", "status"])
    try:
        return pd.read_csv(LOG_PATH)
    except Exception:
        return pd.DataFrame(columns=["sent_at", "ward_id", "event_date", "risk_band", "status"])


def filter_already_sent(events: pd.DataFrame, dedup_hours: int = DEDUP_HOURS) -> pd.DataFrame:
    log = _load_log()
    if log.empty or events.empty:
        return events
    log["sent_at"] = pd.to_datetime(log["sent_at"], errors="coerce")
    cutoff = datetime.now() - pd.Timedelta(hours=dedup_hours)
    recent = log[log["sent_at"] >= cutoff]

    # Only a SUCCESSFUL send suppresses a re-alert. A dry run is a rehearsal and
    # a failure is a retry candidate — treating either as "already warned" would
    # silently swallow the real warning, which is the worst failure mode this
    # system has. (Found in testing: dispatch() logs every row, so a single dry
    # run used to suppress the live send 12 hours later.)
    if "status" in recent.columns:
        recent = recent[recent["status"].astype(str) == "sent"]
    if recent.empty:
        return events
    key_recent = set(zip(recent["ward_id"].astype(int), recent["event_date"].astype(str)))
    keep = [i for i, r in events.iterrows()
            if (int(r["ward_id"]), str(r["event_date"])) not in key_recent]
    return events.loc[keep].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 4. Dispatch
# --------------------------------------------------------------------------- #

def send_twilio(body: str, to_numbers: list[str]) -> list[dict]:
    """Returns a result dict per recipient. Never raises — callers log the outcome."""
    results = []
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        return [{"to": n, "status": "no-credentials", "sid": None} for n in to_numbers]

    try:
        from twilio.rest import Client
    except ImportError:
        return [{"to": n, "status": "twilio-not-installed", "sid": None} for n in to_numbers]

    client = Client(TWILIO_SID, TWILIO_TOKEN)
    for n in to_numbers:
        try:
            msg = client.messages.create(from_=TWILIO_FROM, to=n, body=body)
            results.append({"to": n, "status": "sent", "sid": msg.sid})
        except Exception as exc:                       # noqa: BLE001
            results.append({"to": n, "status": f"failed: {str(exc)[:120]}", "sid": None})
    return results


def live_send_allowed() -> tuple[bool, str]:
    """
    Gate for real dispatch. Returns (allowed, reason).

    Two independent locks, because the failure modes differ: missing credentials
    is a config problem, a missing HS_ALLOW_LIVE_SEND is the operator not having
    decided to send yet. Both must be open.
    """
    if not ALLOW_LIVE_SEND:
        return False, "HS_ALLOW_LIVE_SEND is not set — live dispatch refused"
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        return False, "Twilio credentials incomplete — live dispatch refused"
    return True, "ok"


def dispatch(events: pd.DataFrame, dry_run: bool = True, to_numbers: list[str] | None = None,
             per_ward: bool = False) -> pd.DataFrame:
    """
    Compose, optionally send, and log every alert.

    per_ward=True resolves recipients from the ward registry (locals + citywide
    duty officers) instead of blasting one flat list. Falls back to the flat list
    for wards with no subscribers, so a ward is never silently skipped.
    """
    if not dry_run:
        allowed, reason = live_send_allowed()
        if not allowed:
            raise PermissionError(reason)

        from core.subscribers import recipients_for_ward  # local import: keeps the module importable standalone

    flat = to_numbers or ALERT_TO or ["dry-run"]
    records = []

    for ev in events.to_dict("records"):
        body = compose_message(ev)
        if dry_run:
            if per_ward:
                from core.subscribers import recipients_for_ward
                targets = recipients_for_ward(ev["ward_id"]) or flat
            else:
                targets = flat
            sends = [{"to": t, "status": "dry-run", "sid": None} for t in targets]
        else:
            targets = recipients_for_ward(ev["ward_id"]) or flat if per_ward else flat
            sends = send_twilio(body, targets)

        for s in sends:
            records.append({
                "sent_at": datetime.now().isoformat(timespec="seconds"),
                "ward_id": ev["ward_id"],
                "ward_name": ev["ward_name"],
                "event_date": str(ev["event_date"]),
                "lead_days": ev["lead_days"],
                "risk_score": ev["risk_score"],
                "risk_band": ev["risk_band"],
                "to": s["to"],
                "status": s["status"],
                "sid": s["sid"],
                "body": body,
            })

    out = pd.DataFrame(records)
    if not out.empty:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = not LOG_PATH.exists()
        out.to_csv(LOG_PATH, mode="a", index=False, header=header)
    return out


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually dispatch via Twilio")
    ap.add_argument("--threshold", type=float, default=DEFAULT_RISK_THRESHOLD)
    ap.add_argument("--lead", type=int, default=DEFAULT_MIN_LEAD_DAYS)
    ap.add_argument("--scenario", default="0", help="temperature offset, e.g. +6")
    args = ap.parse_args()

    from core.risk import daily_risk
    from core.weather import get_forecast

    pd.set_option("display.width", 200)
    print("=" * 88)
    print(f"ALERT PLAN   threshold={args.threshold}   min lead={args.lead}d   "
          f"scenario={args.scenario}   mode={'SEND' if args.send else 'DRY RUN'}")
    print("=" * 88)

    daily = daily_risk(get_forecast(), temp_offset_c=float(args.scenario))
    events = find_upcoming_events(daily, min_lead_days=args.lead, risk_threshold=args.threshold)
    print(f"\n{len(events)} ward(s) cross the threshold with >= {args.lead} day(s) of lead time.\n")

    if events.empty:
        print("Nothing to warn about yet — every crossing is inside the lead-time window.")
        print("(Try --scenario +6 to see what a real heatwave looks like.)")
        raise SystemExit(0)

    pending = filter_already_sent(events)
    print(f"After dedupe ({DEDUP_HOURS}h): {len(pending)} to dispatch\n")

    print(events[["ward_name", "event_date", "lead_days", "risk_score", "risk_band", "wbgt_peak_c"]]
          .head(15).to_string(index=False))

    print("\n" + "-" * 88)
    print("SAMPLE MESSAGE")
    print("-" * 88)
    print(compose_message(pending.iloc[0].to_dict() if not pending.empty else events.iloc[0].to_dict()))

    if not pending.empty:
        log = dispatch(pending, dry_run=not args.send)
        print("\n" + "-" * 88)
        print(f"{len(log)} message record(s) -> {LOG_PATH}")
        print(log["status"].value_counts().to_dict())
