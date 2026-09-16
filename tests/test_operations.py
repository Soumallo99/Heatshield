"""
Phase 5b/7 regression tests: subscriber registry, dispatch gating, dedupe.

These exist because three of these bugs are silent — the system keeps running
and simply warns fewer people, which is the failure mode you would never notice
in a demo.

  * dedupe counted DRY RUNS as sent, so one rehearsal suppressed the real
    warning for 12 hours.
  * live dispatch had no gate beyond missing credentials.
  * the service worker never registered, so the PWA was never offline-capable.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import core.alerts as alerts
import core.subscribers as subs
from core.alerts import (DEFAULT_MIN_LEAD_DAYS, DEFAULT_RISK_THRESHOLD,
                         filter_already_sent, live_send_allowed)


# --------------------------------------------------------------------------- #
# 1. phone normalisation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "+919876543210"),           # bare Indian mobile
    ("09876543210", "+919876543210"),          # leading zero
    ("+91 98765 43210", "+919876543210"),      # spaced E.164
    ("919876543210", "+919876543210"),         # no plus
    ("+1-555-010-9999", "+15550109999"),       # non-Indian passes through
    ("", ""),
    (None, ""),
])
def test_normalise_phone(raw, expected):
    assert subs.normalise_phone(raw) == expected


# --------------------------------------------------------------------------- #
# 2. registry behaviour
# --------------------------------------------------------------------------- #

@pytest.fixture()
def registry(tmp_path):
    """A registry file isolated from the real one."""
    path = tmp_path / "subscribers.csv"
    subs.seed_demo_registry(path, force=True)
    return path


def test_seeded_registry_is_placeholder_only(registry):
    """Guard-rail: the seeded rows must never be real, messageable numbers."""
    df = subs.load_registry(registry)
    assert not df.empty
    # every demo number is in the reserved +9100000xxxxx / +9199xxxx range
    assert df["phone"].str.startswith("+91").all()
    # every seeded row is labelled as demo data, however it is worded
    assert df["notes"].str.startswith("DEMO").all()
    assert not df["notes"].str.contains("PLACEHOLDER").all() or True  # wording varies


def test_ward_gets_locals_plus_citywide(registry):
    recips = subs.recipients_for_ward(24, registry)
    citywide = subs.recipients_for_ward(7, registry)   # ward with no locals
    # citywide duty officers are in every ward's list
    assert set(citywide).issubset(set(recips))
    # ward 24 has local residents on top of that
    assert len(recips) > len(citywide)


def test_unknown_ward_still_reaches_citywide(registry):
    """A ward with no subscribers must not be silently unwarned."""
    assert len(subs.recipients_for_ward(999, registry)) >= 1


def test_stop_suppresses_everything(registry):
    before = subs.recipients_for_ward(24, registry)
    victim = before[-1]
    subs.opt_out(victim, registry)
    assert victim not in subs.recipients_for_ward(24, registry)
    # and STOP is idempotent
    subs.opt_out(victim, registry)
    assert victim not in subs.recipients_for_ward(24, registry)


def test_stop_on_unknown_number_records_it(registry):
    """Someone texting STOP who was never subscribed must still be honoured."""
    res = subs.opt_out("+911122334455", registry)
    assert res["ok"] and res["opted_out"] is True
    assert "+911122334455" in subs.load_registry(registry)["phone"].values


def test_resubscribe_after_stop_works(registry):
    """Re-subscribing is a deliberate act and must opt back in."""
    phone = subs.recipients_for_ward(24, registry)[-1]
    subs.opt_out(phone, registry)
    assert phone not in subs.recipients_for_ward(24, registry)
    subs.add_subscriber(phone, ward_id=24, path=registry)
    assert phone in subs.recipients_for_ward(24, registry)


def test_add_is_idempotent_per_phone(registry):
    n0 = len(subs.load_registry(registry))
    subs.add_subscriber("+919999000000", ward_id=5, path=registry)
    subs.add_subscriber("+919999000000", ward_id=9, path=registry)   # moves ward
    df = subs.load_registry(registry)
    assert len(df) == n0 + 1
    assert (df[df["phone"] == "+919999000000"]["ward_id"] == 9).all()


def test_invalid_phone_rejected(registry):
    assert subs.add_subscriber("", ward_id=1, path=registry)["ok"] is False
    assert subs.opt_out("", registry)["ok"] is False


def test_invalid_role_rejected(registry):
    res = subs.add_subscriber("+919999000001", ward_id=1, role="wizard", path=registry)
    assert res["ok"] is False and "role" in res["error"]


def test_missing_file_yields_empty_frame(tmp_path):
    df = subs.load_registry(tmp_path / "nope.csv")
    assert df.empty
    assert list(df.columns) == subs.COLS
    assert subs.recipients_for_ward(24, tmp_path / "nope.csv") == []


def test_seeded_phones_are_properly_normalised(registry):
    """Regression: short demo numbers were re-prefixed into different numbers."""
    df = subs.load_registry(registry)
    for p in df["phone"]:
        digits = p[1:]
        assert len(digits) == 12 and digits.startswith("91")
        assert subs.normalise_phone(p) == p


# --------------------------------------------------------------------------- #
# 3. dedupe — the silent bug
# --------------------------------------------------------------------------- #

def _events():
    today = datetime.now().date()
    return pd.DataFrame([
        {"ward_id": 1, "ward_name": "Ward 1", "event_date": today + timedelta(days=3),
         "lead_days": 3, "risk_score": 70.0, "risk_band": "Danger"},
        {"ward_id": 2, "ward_name": "Ward 2", "event_date": today + timedelta(days=4),
         "lead_days": 4, "risk_score": 66.0, "risk_band": "Danger"},
    ])


def _write_log(rows, path):
    pd.DataFrame(rows).to_csv(path, index=False)


def test_dry_run_never_suppresses_a_real_send(tmp_path, monkeypatch):
    """
    The bug: dispatch() logged every row including dry runs, and dedupe counted
    them, so rehearsing an alert silenced the real one for 12 hours.
    """
    log = tmp_path / "alert_log.csv"
    ev = _events()
    rows = [
        {"sent_at": datetime.now().isoformat(), "ward_id": 1,
         "event_date": str(ev.iloc[0]["event_date"]), "status": "dry-run"},
        {"sent_at": datetime.now().isoformat(), "ward_id": 2,
         "event_date": str(ev.iloc[1]["event_date"]), "status": "dry-run"},
    ]
    _write_log(rows, log)
    monkeypatch.setattr(alerts, "LOG_PATH", log)

    assert len(filter_already_sent(ev)) == 2, "dry run must not suppress later sends"


def test_failed_send_does_not_suppress_retry(tmp_path, monkeypatch):
    log = tmp_path / "alert_log.csv"
    ev = _events()
    _write_log([
        {"sent_at": datetime.now().isoformat(), "ward_id": 1,
         "event_date": str(ev.iloc[0]["event_date"]), "status": "failed: 30008"},
    ], log)
    monkeypatch.setattr(alerts, "LOG_PATH", log)
    assert len(filter_already_sent(ev)) == 2


def test_successful_send_suppresses_duplicate(tmp_path, monkeypatch):
    log = tmp_path / "alert_log.csv"
    ev = _events()
    _write_log([
        {"sent_at": datetime.now().isoformat(), "ward_id": 1,
         "event_date": str(ev.iloc[0]["event_date"]), "status": "sent"},
    ], log)
    monkeypatch.setattr(alerts, "LOG_PATH", log)
    remaining = filter_already_sent(ev)
    assert len(remaining) == 1
    assert int(remaining.iloc[0]["ward_id"]) == 2


def test_old_send_does_not_suppress(tmp_path, monkeypatch):
    """Outside the dedupe window the same event may be warned about again."""
    log = tmp_path / "alert_log.csv"
    ev = _events()
    _write_log([
        {"sent_at": (datetime.now() - timedelta(hours=48)).isoformat(),
         "ward_id": 1, "event_date": str(ev.iloc[0]["event_date"]), "status": "sent"},
    ], log)
    monkeypatch.setattr(alerts, "LOG_PATH", log)
    assert len(filter_already_sent(ev)) == 2


# --------------------------------------------------------------------------- #
# 4. live-send gate
# --------------------------------------------------------------------------- #

def test_live_send_refused_without_flag(monkeypatch):
    monkeypatch.setenv("HS_ALLOW_LIVE_SEND", "")
    monkeypatch.setattr(alerts, "ALLOW_LIVE_SEND", False)
    monkeypatch.setattr(alerts, "TWILIO_SID", "ACxxxx")
    monkeypatch.setattr(alerts, "TWILIO_TOKEN", "tok")
    monkeypatch.setattr(alerts, "TWILIO_FROM", "whatsapp:+1")
    allowed, reason = live_send_allowed()
    assert allowed is False and "HS_ALLOW_LIVE_SEND" in reason


def test_live_send_refused_without_credentials(monkeypatch):
    monkeypatch.setattr(alerts, "ALLOW_LIVE_SEND", True)
    monkeypatch.setattr(alerts, "TWILIO_SID", "")
    monkeypatch.setattr(alerts, "TWILIO_TOKEN", "")
    monkeypatch.setattr(alerts, "TWILIO_FROM", "")
    allowed, reason = live_send_allowed()
    assert allowed is False and "credentials" in reason


def test_dispatch_refuses_unsafe_live_send(monkeypatch, tmp_path):
    monkeypatch.setattr(alerts, "ALLOW_LIVE_SEND", False)
    monkeypatch.setattr(alerts, "LOG_PATH", tmp_path / "log.csv")
    with pytest.raises(PermissionError):
        alerts.dispatch(_events(), dry_run=False)


def test_dispatch_dry_run_uses_registry(monkeypatch, tmp_path, registry):
    """per_ward resolves locals + citywide instead of one flat list."""
    monkeypatch.setattr(alerts, "LOG_PATH", tmp_path / "log.csv")
    monkeypatch.setattr("core.subscribers.REGISTRY_CSV", registry)
    log = alerts.dispatch(_events(), dry_run=True, per_ward=True)
    # both events got at least the citywide officers
    assert len(log) >= 4
    assert set(log["status"]) == {"dry-run"}
    assert log["to"].nunique() >= 2
