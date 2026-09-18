"""Notification planning, preview and dry-run safety tests.

Invariants under test:
  * previews are generated from real warning rows and carry zone, severity,
    target date, lead time, reason, recommended action and data-quality state;
  * nothing sends by default — dry_run is True everywhere;
  * live dispatch stays double-locked (env flag + credentials) AND refuses any
    demo/synthetic row even when both locks are open;
  * no credentials are needed for any of it to work.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import core.coupled as coupled
import core.demo as demo
import core.notify as notify
from app.main import app
from core.notify import (
    AUDIENCES,
    SMS_TARGET_CHARS,
    TEMPLATES,
    build_previews,
    dispatch_previews,
    plan_notifications,
)


def _offline(*_args, **_kwargs):
    raise OSError("simulated provider outage")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)
    monkeypatch.setattr(notify, "DRY_RUN_LOG_PATH", tmp_path / "notification_dry_run_log.csv")
    yield
    coupled.clear_ncr_cache()


# --------------------------------------------------------------------------- #
# previews
# --------------------------------------------------------------------------- #

def test_previews_cover_every_audience_and_both_channels():
    rows = demo.warnings_payload("dry-extreme")["data"]
    plan = plan_notifications(rows, is_demo=True, scenario_id="dry-extreme")
    assert plan["dry_run"] is True
    previews = plan["previews"]
    assert previews
    audiences = {preview["audience"] for preview in previews}
    assert audiences == set(AUDIENCES)
    channels = {preview["channel"] for preview in previews}
    assert channels <= {"sms", "whatsapp"}
    assert plan["templates"] == list(TEMPLATES)


def test_every_preview_carries_the_required_operational_fields():
    rows = demo.warnings_payload("dry-extreme")["data"]
    previews = build_previews(rows, is_demo=True, scenario_id="dry-extreme")
    for preview in previews:
        assert preview["zone_id"] and preview["zone_name"]
        assert preview["severity"] in ("warning", "severe")
        assert preview["target_date"] and preview["lead_days"] >= 0
        assert preview["lead_hours"] is not None
        assert preview["reason"]
        assert preview["recommended_action"]
        assert preview["data_quality_state"] == "demo-synthetic"
        assert preview["dry_run"] is True
        assert preview["status"] == "preview"
        assert "DISABLED" in preview["live_send"].upper()
        assert preview["demo_disclaimer"] == demo.DEMO_DISCLAIMER


def test_early_warning_template_mentions_lead_time_and_target_date():
    rows = demo.warnings_payload("dry-extreme")["data"]
    previews = build_previews(rows, is_demo=True, scenario_id="dry-extreme")
    early = [p for p in previews if p["template"] == "early-warning"]
    assert early
    for preview in early:
        message = preview["message"]
        assert "EARLY WARNING" in message
        assert f"lead {preview['lead_days']} d" in message
        assert preview["target_date"] in message
        assert preview["zone_name"] in message
        assert demo.DEMO_DISCLAIMER in message


def test_same_day_escalation_template_exists_for_severe_day_zero():
    rows = demo.warnings_payload("heat-plus-pollution")["data"]
    previews = build_previews(rows, is_demo=True, scenario_id="heat-plus-pollution")
    escalations = [p for p in previews if p["template"] == "same-day-escalation"]
    assert escalations
    for preview in escalations:
        assert preview["lead_days"] == 0
        assert preview["severity"] == "severe"
        assert "SAME-DAY HEAT ESCALATION" in preview["message"]
        assert "TODAY" in preview["message"]


def test_resident_sms_stays_within_segment_budget():
    for scenario_id in demo.scenario_ids():
        rows = demo.warnings_payload(scenario_id)["data"]
        previews = build_previews(rows, is_demo=True, scenario_id=scenario_id)
        for preview in previews:
            if preview["audience"] == "residents" and preview["channel"] == "sms":
                assert preview["message_chars"] <= SMS_TARGET_CHARS, scenario_id


def test_preview_plan_is_empty_for_a_quiet_scenario():
    rows = demo.warnings_payload("monsoon-break")["data"]
    plan = plan_notifications(rows, is_demo=True, scenario_id="monsoon-break")
    assert plan["rows"] == 0
    assert plan["previews"] == []


# --------------------------------------------------------------------------- #
# dispatch safety
# --------------------------------------------------------------------------- #

def test_dry_run_dispatch_logs_and_sends_nothing():
    rows = demo.warnings_payload("dry-extreme")["data"]
    previews = build_previews(rows, is_demo=True, scenario_id="dry-extreme")
    result = dispatch_previews(previews, dry_run=True)
    assert result["dry_run"] is True
    assert result["dispatched"] == len(previews)
    assert set(result["status_counts"]) == {"dry-run"}
    log = pd.read_csv(notify.DRY_RUN_LOG_PATH)
    assert len(log) == len(previews)
    assert (log["status"] == "dry-run").all()
    assert log["dry_run"].astype(bool).all()


def test_live_dispatch_of_demo_rows_is_refused_even_with_both_locks_open(monkeypatch):
    """The demo guard outranks the credential gate: exercises never message people."""
    monkeypatch.setattr(notify, "live_send_allowed", lambda: (True, "ok"))
    rows = demo.warnings_payload("dry-extreme")["data"]
    previews = build_previews(rows, is_demo=True, scenario_id="dry-extreme")
    with pytest.raises(PermissionError, match="demo/synthetic"):
        dispatch_previews(previews, dry_run=False)


def test_live_dispatch_of_synthetic_fallback_rows_is_refused(monkeypatch):
    monkeypatch.setattr(notify, "live_send_allowed", lambda: (True, "ok"))
    client = TestClient(app)
    body = client.get("/notifications/preview").json()
    assert body["is_synthetic"] is True       # provider is down in this suite
    previews = body["previews"]
    assert previews
    with pytest.raises(PermissionError, match="demo/synthetic"):
        dispatch_previews(previews, dry_run=False)


def test_live_dispatch_still_needs_the_double_lock_for_live_rows(monkeypatch):
    live_row_preview = {
        "preview_id": "x", "template": "early-warning", "audience": "residents",
        "channel": "sms", "zone_id": "central-delhi", "target_date": "2026-05-21",
        "lead_days": 3, "severity": "severe", "is_demo": False,
        "data_quality_state": "live-forecast", "message": "test",
    }
    monkeypatch.setattr(notify, "live_send_allowed", lambda: (False, "HS_ALLOW_LIVE_SEND is not set"))
    with pytest.raises(PermissionError, match="HS_ALLOW_LIVE_SEND"):
        dispatch_previews([live_row_preview], dry_run=False)


def test_dispatch_endpoint_defaults_to_dry_run_and_refuses_unsafe_live():
    client = TestClient(app)
    result = client.post("/notifications/dispatch", json={},
                         headers={"X-API-Key": "test-admin-token"}).json()
    assert result["dry_run"] is True
    assert result["dispatched"] > 0
    assert set(result["status_counts"]) == {"dry-run"}

    refused = client.post("/notifications/dispatch", json={"dry_run": False},
                          headers={"X-API-Key": "test-admin-token"}).json()
    assert refused["dispatched"] == 0
    assert "demo/synthetic" in refused["refused"]


def test_preview_endpoint_needs_no_credentials_or_network():
    client = TestClient(app)
    body = client.get("/notifications/preview").json()
    assert body["dry_run"] is True
    assert body["dispatch_policy"]["demo_guard"]
    assert "HS_ALLOW_LIVE_SEND=1" in body["dispatch_policy"]["live_send_locks"][0]
    demo_body = client.get("/demo/notifications?scenario=humid-dangerous").json()
    assert demo_body["is_demo"] is True
    assert demo_body["dry_run"] is True
