"""Safety tests for the WhatsApp/SMS automation entry point.

`scripts/dispatch_notifications.py` is what an operator (or cron) runs. The
defaults must be a rehearsal, and `--live` must stay refused while the payload
is synthetic or the double lock is closed — no credentials are involved in
these tests, by design.
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], log_path: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HS_FORECAST_DAYS": "5",
        "HS_DRY_RUN_LOG": str(log_path),
        # Guarantee the locks are closed for this test regardless of the host.
        "HS_ALLOW_LIVE_SEND": "0",
        "TWILIO_ACCOUNT_SID": "",
        "TWILIO_AUTH_TOKEN": "",
        "TWILIO_FROM_NUMBER": "",
    }
    return subprocess.run(
        [sys.executable, "-m", "scripts.dispatch_notifications", *args],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False, timeout=180,
    )


def test_default_run_is_a_dry_run_and_never_sends(tmp_path):
    log = tmp_path / "dry_run_log.csv"
    result = _run(["--json"], log)
    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is True
    if "reason" in doc:
        # A calm window plans zero notifications — silence is a valid outcome.
        assert doc["dispatched"] == 0
    else:
        assert doc["log_path"] == str(log)
        # Every logged record (if any alert met the bar) is a dry-run record.
        assert set(doc.get("status_counts", {})) <= {"dry-run"}
        assert "sent" not in doc.get("status_counts", {})


def test_live_dispatch_is_refused_for_synthetic_rows_in_any_weather(tmp_path):
    """The safety lock, rehearsed deterministically.

    This assertion used to run against the *real* forecast and require exit 2 —
    so it passed on a laptop with no internet (where the payload degrades to
    synthetic rows) and failed on CI, where the live forecast was mild enough
    that nothing crossed the notification bar and the script correctly exited 0
    with "nothing to send". A safety test that depends on the weather is not a
    test; `--rehearse-demo` plans a synthetic scenario on demand, and every
    preview from it is refused for a live send whatever the sky is doing.
    """
    log = tmp_path / "live_log.csv"
    result = _run(["--live", "--rehearse-demo", "--json"], log)
    assert result.returncode == 2, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is False
    assert "refus" in doc["refused"].lower()
    assert "demo/synthetic" in doc["refused"]
    assert not log.exists()  # a refused dispatch logs nothing


def test_a_rehearsal_without_live_is_a_dry_run_that_really_plans(tmp_path):
    """The same scenario, without --live: planned, rehearsed, nothing sent."""
    log = tmp_path / "rehearsal.csv"
    result = _run(["--rehearse-demo", "--json"], log)
    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is True
    assert doc["dispatched"] > 0, "the rehearsal scenario must have something to say"
    assert set(doc.get("status_counts", {})) <= {"dry-run"}


def test_live_dispatch_never_sends_from_the_real_plan(tmp_path):
    """Against the real forecast there are two honest outcomes, and no third.

    Either the window is calm and the script says so (exit 0, nothing planned),
    or there is something to send and the closed locks refuse it (exit 2). What
    must never happen is a send — and, since a masked CI pipeline was reporting
    this test green while it failed, what must also never happen is a silent
    success that hides the difference.
    """
    log = tmp_path / "live_log.csv"
    result = _run(["--live", "--json"], log)
    assert result.returncode in (0, 2), result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is False
    if result.returncode == 2:
        assert "refus" in doc["refused"].lower()
    else:
        assert doc["dispatched"] == 0
        assert "reason" in doc, "a zero-send live run must say why it sent nothing"
    assert not log.exists()


def test_the_guard_refuses_synthetic_rows_and_a_closed_lock(monkeypatch):
    """The gate itself, with the sender stubbed: no weather, no credentials.

    `dispatch_previews(dry_run=False)` is the only code in the project that can
    message a real person, so it is tested directly rather than only through the
    CLI — and `send_twilio` is replaced with a recorder first, so a bug in the
    guard cannot turn this test into an incident.
    """
    import pytest

    from core import notify

    sent: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(notify, "send_twilio", lambda body, numbers: sent.append((body, list(numbers))) or [])

    synthetic = {"message": "…", "is_demo": True, "audience": "public", "channel": "sms"}
    with pytest.raises(PermissionError, match="demo/synthetic"):
        notify.dispatch_previews([synthetic], dry_run=False)

    fallback = {"message": "…", "is_demo": False, "data_quality_state": "synthetic-fallback"}
    with pytest.raises(PermissionError, match="demo/synthetic"):
        notify.dispatch_previews([fallback], dry_run=False)

    real = {"message": "…", "is_demo": False, "data_quality_state": "live-forecast"}
    monkeypatch.setattr(notify, "live_send_allowed", lambda: (False, "the second lock is closed"))
    with pytest.raises(PermissionError, match="second lock"):
        notify.dispatch_previews([real], dry_run=False)

    # …and with both locks open it does reach the sender — the gate is a gate,
    # not a wall. The stub is what keeps this safe to assert.
    monkeypatch.setattr(notify, "live_send_allowed", lambda: (True, ""))
    notify.dispatch_previews([real], dry_run=False, to_numbers=["+910000000000"])
    assert sent == [("…", ["+910000000000"])]


def test_audience_and_channel_filters_produce_valid_plans(tmp_path):
    log = tmp_path / "filtered.csv"
    result = _run(["--json", "--audience", "municipal_administration", "--channel", "whatsapp"], log)
    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is True
    assert set(doc.get("status_counts", {})) <= {"dry-run"} or doc["dispatched"] == 0
