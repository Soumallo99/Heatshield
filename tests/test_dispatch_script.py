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


def test_live_dispatch_is_refused_without_locks_or_for_synthetic_rows(tmp_path):
    log = tmp_path / "live_log.csv"
    result = _run(["--live", "--json"], log)
    assert result.returncode == 2
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is False
    assert "refus" in doc["refused"].lower()
    assert not log.exists()  # a refused dispatch logs nothing


def test_audience_and_channel_filters_produce_valid_plans(tmp_path):
    log = tmp_path / "filtered.csv"
    result = _run(["--json", "--audience", "municipal_administration", "--channel", "whatsapp"], log)
    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["dry_run"] is True
    assert set(doc.get("status_counts", {})) <= {"dry-run"} or doc["dispatched"] == 0
