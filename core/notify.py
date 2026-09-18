"""
NOTIFICATION PLANNING + PREVIEW (dry-run first, opt-in dispatch)
================================================================
Turns advance-warning rows (core/warnings.py) into audience-specific message
PREVIEWS for:

    municipal administration · disaster management · healthcare systems · residents
    channels: SMS · WhatsApp

Safety model (enforced by tests/test_notifications.py):

1. **Previews never send.** Everything this module produces by default is a
   preview record with ``dry_run: true`` and ``status: "preview"``.
2. **Dispatch is opt-in and double-locked.** A live send reuses the existing
   ``core.alerts.live_send_allowed()`` gate: real Twilio credentials AND
   ``HS_ALLOW_LIVE_SEND=1``. Either missing ⇒ ``PermissionError``, no send.
3. **Demo/synthetic data can never trigger a live send.** Even with both
   locks open, dispatch refuses rows whose quality state is demo or synthetic
   fallback — an exercise must never message real people.
4. **No credentials in Git, none in chat.** Configuration lives in the
   gitignored ``.env`` (see ``.env.example``).

Templates cover the two operational shapes the brief requires:
    * ``early-warning``      — 3–5 day (and 1–2 day) advance notice
    * ``same-day-escalation``— the event is today; act now
"""
from __future__ import annotations

from datetime import datetime
import math
import os
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import pandas as pd

from core import config
from core.alerts import live_send_allowed, send_twilio
from core.warnings import ACTION_MATRIX, DEMO_DISCLAIMER

# Env override keeps tests and one-off rehearsals away from the real log file.
DRY_RUN_LOG_PATH = Path(os.getenv("HS_DRY_RUN_LOG", "") or config.PROCESSED_DIR / "notification_dry_run_log.csv")

LIVE_SEND_LOCK_NOTE = (
    "live sending is DISABLED by default — it requires HS_ALLOW_LIVE_SEND=1 plus "
    "Twilio credentials in the environment (never in Git)"
)

# --------------------------------------------------------------------------- #
# 1. Audiences and channels
# --------------------------------------------------------------------------- #

AUDIENCES: dict[str, dict[str, Any]] = {
    "municipal_administration": {
        "label": "Municipal administration",
        "channels": ("sms", "whatsapp"),
        "focus": "civic operations: cooling centres, water, work-hour shifts, power coordination",
    },
    "disaster_management": {
        "label": "Disaster management authority",
        "channels": ("sms",),
        "focus": "activation decisions: control rooms, inter-agency coordination, emergency powers",
    },
    "healthcare_systems": {
        "label": "Healthcare systems",
        "channels": ("whatsapp",),
        "focus": "surge readiness: heat-illness staffing, ambulance pre-positioning, ward capacity",
    },
    "residents": {
        "label": "Residents",
        "channels": ("sms",),
        "focus": "personal safety: timing, hydration, shade, checking on vulnerable people",
    },
}

CHANNELS: tuple[str, ...] = ("sms", "whatsapp")
TEMPLATES: tuple[str, ...] = ("early-warning", "same-day-escalation")

# Keep SMS previews inside 3 concatenated segments (459 chars incl. sender overhead).
SMS_TARGET_CHARS = 459

_LEVEL_WORD = {"routine": "ROUTINE", "watch": "WATCH", "warning": "WARNING", "severe": "SEVERE"}
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _weekday(date_iso: str) -> str:
    try:
        return _WEEKDAYS[pd.Timestamp(date_iso).weekday()]
    except (ValueError, TypeError):
        return ""


def _num(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number != number:  # NaN
        return "n/a"
    return f"{number:.{digits}f}{suffix}"


def _actions_for(row: dict[str, Any]) -> list[str]:
    """Municipal action texts for a row's recommended action level."""
    level = str(row.get("recommended_action_level") or row.get("alert_level") or "watch")
    return list(ACTION_MATRIX.get(level, ACTION_MATRIX["watch"])["municipal_actions"])


def _advice_for(row: dict[str, Any]) -> list[str]:
    level = str(row.get("recommended_action_level") or row.get("alert_level") or "watch")
    return list(ACTION_MATRIX.get(level, ACTION_MATRIX["watch"])["resident_advice"])


def _demo_line(row: dict[str, Any]) -> str:
    if row.get("is_demo"):
        return DEMO_DISCLAIMER
    if row.get("quality_state") == "synthetic-fallback":
        return "Practice data (provider outage fallback) — not a live forecast or observation."
    return ""


def _quality_line(row: dict[str, Any]) -> str:
    state = row.get("quality_state", "unknown")
    source = row.get("data_source", "unknown source")
    wbgt_quality = row.get("wbgt_peak_quality", "unknown")
    return f"Data: {state} · source: {source} · WBGT {wbgt_quality}."


# --------------------------------------------------------------------------- #
# 2. Templates
# --------------------------------------------------------------------------- #

def compose_early_warning(row: dict[str, Any], audience_id: str) -> str:
    """Advance (1–5 day) warning copy for one audience."""
    if audience_id not in AUDIENCES:
        raise KeyError(audience_id)
    level = _LEVEL_WORD.get(row.get("alert_level", "watch"), "WATCH")
    day = _weekday(row.get("target_date", ""))
    header = (
        f"HeatShield {level} — HEAT EARLY WARNING ({row.get('target_day_label', '')})\n"
        f"{row.get('zone_name', 'Zone')} · target {day} {row.get('target_date', '')} · "
        f"lead {row.get('lead_days')} d ({row.get('lead_hours')} h to peak)\n"
    )
    conditions = (
        f"Expected: Tmax {_num(row.get('tmax_c'), 1, ' °C')} "
        f"({_num(row.get('departure_c'), 1, ' °C')} vs 1991–2020 normal), "
        f"est. WBGT {_num(row.get('wbgt_est_peak_c'), 1, ' °C')}, "
        f"Heat Index {_num(row.get('hi_peak_c'), 1, ' °C')}, HTSI {_num(row.get('htsi_score'), 0)}/100 "
        f"({row.get('thermal_stress_level', 'Unknown')}).\n"
    )
    heatwave = ""
    if row.get("is_heatwave_episode"):
        kind = "SEVERE heatwave episode" if row.get("is_severe_episode") else "heatwave episode"
        heatwave = f"Status: day {row.get('episode_day')} of {row.get('episode_length')} of a declared {kind}.\n"
    elif row.get("heatwave_candidate"):
        heatwave = "Status: heatwave candidate — early watch, persistence rule not yet met.\n"
    impact = (
        f"Health impact: {row.get('health_impact_band', 'Unavailable')} "
        f"({_num(row.get('health_impact_index'), 0)}/100) — {row.get('health_impact_status', '')}.\n"
    )

    if audience_id == "municipal_administration":
        actions = _actions_for(row)[:3]
        body = "Activate:\n" + "\n".join(f"  • {action}" for action in actions) + "\n"
    elif audience_id == "disaster_management":
        body = (
            f"Recommended activation level: {row.get('recommended_action_level', 'watch').upper()}.\n"
            "Coordinate municipal response, control-room staffing and inter-agency "
            "resource movement for the target window.\n"
        )
    elif audience_id == "healthcare_systems":
        body = (
            f"Prepare for {row.get('health_impact_band', 'elevated')} heat-health pressure: "
            "heat-illness triage readiness, IV/ORC stock, ambulance pre-positioning, "
            "and alert ward duty doctors for the target date.\n"
        )
    else:  # residents — short, actionable, one SMS-friendly block
        advice = _advice_for(row)[:2]
        body = " · ".join(advice) + "\n"

    footer = _quality_line(row)
    demo = _demo_line(row)
    parts = [header, conditions, heatwave, impact, body, footer]
    if demo:
        parts.append(demo)
    message = "\n".join(part for part in parts if part)
    if audience_id == "residents" and len(message) > SMS_TARGET_CHARS:
        # Resident SMS must stay small: drop the impact line first, then status lines.
        parts = [header, conditions, body, demo] if demo else [header, conditions, body]
        message = "\n".join(part for part in parts if part)
    return message


def compose_same_day_escalation(row: dict[str, Any], audience_id: str) -> str:
    """Same-day escalation copy — the event is TODAY; act now."""
    level = _LEVEL_WORD.get(row.get("alert_level", "severe"), "SEVERE")
    header = (
        f"HeatShield {level} — SAME-DAY HEAT ESCALATION\n"
        f"{row.get('zone_name', 'Zone')} · TODAY {row.get('target_date', '')}\n"
    )
    conditions = (
        f"Peak expected {_num(row.get('tmax_c'), 1, ' °C')}, est. WBGT "
        f"{_num(row.get('wbgt_est_peak_c'), 1, ' °C')} ({row.get('thermal_stress_level', 'Unknown')}).\n"
    )
    if audience_id == "residents":
        body = " · ".join(_advice_for(row)[:2]) + "\n"
    elif audience_id == "healthcare_systems":
        body = "Expect heat-illness arrivals through the afternoon; activate surge staffing now.\n"
    elif audience_id == "disaster_management":
        body = "Control room activation recommended for today's peak window (12:00–16:00).\n"
    else:
        body = "Execute severe-level actions now: cooling centres, water points, outdoor-work suspension.\n"
    parts = [header, conditions, body, _quality_line(row)]
    demo = _demo_line(row)
    if demo:
        parts.append(demo)
    return "\n".join(part for part in parts if part)


# --------------------------------------------------------------------------- #
# 3. Planning — which rows deserve a message, and to whom
# --------------------------------------------------------------------------- #

MAX_EARLY_WARNINGS_PER_SCENARIO = 6
MAX_SAME_DAY_ESCALATIONS = 3
_LEVEL_RANK = {"routine": 0, "watch": 1, "warning": 2, "severe": 3}


def select_alert_rows(rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick (early-warning rows, same-day escalation rows) from warning rows.

    Early warnings: alert level ≥ warning with lead ≥ 1 day; per zone keep the
    EARLIEST actionable target (that is the intervention window), then cap the
    scenario at the most severe zones. Same-day: lead 0 at severe level.
    """
    actionable = [row for row in rows if _LEVEL_RANK.get(row.get("alert_level", "routine"), 0) >= 2
                  and int(row.get("lead_days", 0)) >= 1]
    earliest_by_zone: dict[str, dict[str, Any]] = {}
    for row in actionable:
        zone = str(row.get("zone_id"))
        current = earliest_by_zone.get(zone)
        if current is None or (int(row["lead_days"]), -_LEVEL_RANK.get(row["alert_level"], 0)) < (
            int(current["lead_days"]), -_LEVEL_RANK.get(current["alert_level"], 0)
        ):
            earliest_by_zone[zone] = row
    early = sorted(
        earliest_by_zone.values(),
        key=lambda r: (-_LEVEL_RANK.get(r.get("alert_level", "warning"), 2),
                       -(r.get("health_impact_index") or 0.0), r.get("zone_id", "")),
    )[:MAX_EARLY_WARNINGS_PER_SCENARIO]

    same_day = [row for row in rows if int(row.get("lead_days", 0)) == 0
                and row.get("alert_level") == "severe"]
    same_day = sorted(same_day, key=lambda r: (-(r.get("health_impact_index") or 0.0), r.get("zone_id", "")))
    return early, same_day[:MAX_SAME_DAY_ESCALATIONS]


def _reason_short(row: dict[str, Any]) -> str:
    reason = str(row.get("reason", ""))
    return reason if len(reason) <= 240 else reason[:237] + "…"


def build_previews(
    rows: Sequence[dict[str, Any]],
    *,
    is_demo: bool,
    scenario_id: str | None = None,
) -> list[dict[str, Any]]:
    """Preview records for every selected row × audience × channel."""
    early, same_day = select_alert_rows(rows)
    previews: list[dict[str, Any]] = []
    counter = 0
    for template, selected in (("early-warning", early), ("same-day-escalation", same_day)):
        for row in selected:
            for audience_id, audience in AUDIENCES.items():
                composer = compose_early_warning if template == "early-warning" else compose_same_day_escalation
                for channel in audience["channels"]:
                    counter += 1
                    message = composer(row, audience_id)
                    previews.append({
                        "preview_id": f"{template}-{counter:03d}",
                        "template": template,
                        "audience": audience_id,
                        "audience_label": audience["label"],
                        "channel": channel,
                        "zone_id": row.get("zone_id"),
                        "zone_name": row.get("zone_name"),
                        "severity": row.get("alert_level"),
                        "severity_label": _LEVEL_WORD.get(row.get("alert_level", ""), row.get("alert_level", "")),
                        "target_date": row.get("target_date"),
                        "target_day_label": row.get("target_day_label"),
                        "lead_days": row.get("lead_days"),
                        "lead_hours": row.get("lead_hours"),
                        "reason": _reason_short(row),
                        "recommended_action": (
                            (_advice_for(row) if audience_id == "residents" else _actions_for(row))
                            or ["monitor conditions"]
                        )[0],
                        "recommended_action_level": row.get("recommended_action_level"),
                        "health_impact_status": row.get("health_impact_status"),
                        "data_quality_state": row.get("quality_state"),
                        "data_source": row.get("data_source"),
                        "is_demo": bool(is_demo or row.get("is_demo", False)),
                        "scenario_id": scenario_id or row.get("scenario_id"),
                        "message": message,
                        "message_chars": len(message),
                        "sms_segments_estimated": max(1, math.ceil(len(message) / 153)) if channel == "sms" else None,
                        "dry_run": True,
                        "status": "preview",
                        "live_send": LIVE_SEND_LOCK_NOTE,
                        "demo_disclaimer": _demo_line(row) or None,
                    })
    return previews


def plan_notifications(
    rows: Sequence[dict[str, Any]],
    *,
    is_demo: bool,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Full notification-plan payload (previews + policy + counts)."""
    previews = build_previews(rows, is_demo=is_demo, scenario_id=scenario_id)
    audience_counts = {audience_id: 0 for audience_id in AUDIENCES}
    for preview in previews:
        audience_counts[preview["audience"]] += 1
    return {
        "rows": len(previews),
        "dry_run": True,
        "dispatch_policy": {
            "default": "dry_run — nothing is sent; previews are generated from real alert rows",
            "live_send_locks": [
                "HS_ALLOW_LIVE_SEND=1 in the environment",
                "TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_NUMBER configured",
            ],
            "demo_guard": "demo or synthetic-fallback alerts can NEVER be dispatched live, even with both locks open",
            "credentials_note": "credentials live only in the gitignored .env — never in Git, never in chat",
        },
        "audiences": [
            {"id": audience_id, **{key: value for key, value in audience.items()}}
            for audience_id, audience in AUDIENCES.items()
        ],
        "templates": list(TEMPLATES),
        "audience_counts": audience_counts,
        "previews": previews,
    }


# --------------------------------------------------------------------------- #
# 4. Dispatch — dry-run by default, double-locked, demo-proof
# --------------------------------------------------------------------------- #

def dispatch_previews(
    previews: Sequence[dict[str, Any]],
    *,
    dry_run: bool = True,
    to_numbers: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Send (or rehearse) planned notifications.

    ``dry_run=True`` (the default) logs every message and sends nothing.
    ``dry_run=False`` is refused with ``PermissionError`` unless BOTH live-send
    locks are open AND no preview originates from demo/synthetic data.
    """
    selected = list(previews)
    if not dry_run:
        unsafe = [p for p in selected if p.get("is_demo") or p.get("data_quality_state") in
                  ("demo-synthetic", "synthetic-fallback")]
        if unsafe:
            raise PermissionError(
                f"refusing live dispatch of {len(unsafe)} demo/synthetic alert message(s) — "
                "exercises must never message real people"
            )
        allowed, reason = live_send_allowed()
        if not allowed:
            raise PermissionError(reason)

    targets = list(to_numbers or config.ALERT_TO) or ["dry-run-log"]
    records: list[dict[str, Any]] = []
    for preview in selected:
        if dry_run:
            sends = [{"to": target, "status": "dry-run", "sid": None} for target in targets]
        else:
            sends = send_twilio(preview["message"], targets)
        for send in sends:
            records.append({
                "logged_at": datetime.now().isoformat(timespec="seconds"),
                "preview_id": preview.get("preview_id"),
                "template": preview.get("template"),
                "audience": preview.get("audience"),
                "channel": preview.get("channel"),
                "zone_id": preview.get("zone_id"),
                "target_date": preview.get("target_date"),
                "lead_days": preview.get("lead_days"),
                "severity": preview.get("severity"),
                "is_demo": bool(preview.get("is_demo")),
                "dry_run": bool(dry_run),
                "to": send["to"],
                "status": send["status"],
                "sid": send.get("sid"),
                "message": preview.get("message"),
            })

    log = pd.DataFrame(records)
    if not log.empty:
        DRY_RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = not DRY_RUN_LOG_PATH.exists()
        log.to_csv(DRY_RUN_LOG_PATH, mode="a", index=False, header=header)

    status_counts = log["status"].value_counts().to_dict() if not log.empty else {}
    return {
        "dispatched": int(len(selected)),
        "dry_run": bool(dry_run),
        "records": int(len(log)),
        "status_counts": status_counts,
        "log_path": str(DRY_RUN_LOG_PATH),
        "live_send_allowed": live_send_allowed()[0] if not dry_run else False,
    }


__all__ = [
    "AUDIENCES", "CHANNELS", "DRY_RUN_LOG_PATH", "LIVE_SEND_LOCK_NOTE",
    "SMS_TARGET_CHARS", "TEMPLATES", "build_previews", "compose_early_warning",
    "compose_same_day_escalation", "dispatch_previews", "plan_notifications",
    "select_alert_rows",
]
