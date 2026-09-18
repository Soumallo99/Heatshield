"""Backup and restore — tested, because an untested backup is a hope.

The scenario this protects: `data/subscribers.csv` is the one file in the
repository that cannot be regenerated. Lose it and people stop getting heat
warnings; lose the opt-outs and people who asked to be left alone get texted.

The test that matters is not "could a backup be written" — it is "would a
restore put the right bytes back, and would it refuse to put the wrong ones
back". Both are covered below.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import backup as backup_tool  # noqa: E402


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A miniature repository: the same relative paths, in a temp directory."""
    root = tmp_path / "repo"
    (root / "data" / "processed").mkdir(parents=True)
    (root / "data" / "cache").mkdir(parents=True)
    (root / "data" / "subscribers.csv").write_text(
        "phone,name,ward_id,role,opted_out\n+919876543210,A,7,resident,False\n", encoding="utf-8"
    )
    (root / "data" / "processed" / "risk_daily.csv").write_text("ward_id,date,risk_score\n7,2026-09-18,71.2\n", encoding="utf-8")
    (root / "data" / "processed" / "thermal_daily.csv").write_text("ward_id,date,wbgt_peak_c\n7,2026-09-18,34.9\n", encoding="utf-8")
    (root / "data" / "processed" / "alert_log.csv").write_text("phone,sent_at\n+919876543210,2026-09-17T09:00\n", encoding="utf-8")
    (root / "data" / "cache" / "forecast_5d.parquet").write_bytes(b"PAR1fake")
    monkeypatch.setattr(backup_tool, "ROOT", root)
    monkeypatch.setattr(backup_tool, "DATA", root / "data")
    return root


def test_backup_writes_a_manifest_that_verifies(workspace, tmp_path, capsys):
    target = backup_tool.backup(tmp_path / "backups")
    assert (target / "MANIFEST.json").exists()

    manifest = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) >= {"data/subscribers.csv", "data/processed/alert_log.csv"}
    for relative, meta in manifest["files"].items():
        assert meta["present"] is True
        assert meta["bytes"] > 0, relative
        assert len(meta["sha256"]) == 64, relative

    ok, missing, corrupt = backup_tool.verify(target)
    assert (missing, corrupt) == ([], [])
    assert len(ok) == len(backup_tool.INCLUDE), "every state file the tool lists must round-trip"


def test_verify_detects_a_corrupted_snapshot(workspace, tmp_path):
    target = backup_tool.backup(tmp_path / "backups")
    victim = target / "data" / "subscribers.csv"
    victim.write_text("phone,name\n+919000000000,Someone else\n", encoding="utf-8")

    ok, missing, corrupt = backup_tool.verify(target)
    assert corrupt == ["data/subscribers.csv"]
    assert "data/processed/alert_log.csv" in ok


def test_verify_detects_a_deleted_snapshot_file(workspace, tmp_path):
    target = backup_tool.backup(tmp_path / "backups")
    (target / "data" / "processed" / "alert_log.csv").unlink()
    ok, missing, corrupt = backup_tool.verify(target)
    assert missing == ["data/processed/alert_log.csv"]


def test_restore_refuses_a_corrupt_snapshot_and_changes_nothing(workspace, tmp_path):
    """A failed restore must not be a half-applied one."""
    target = backup_tool.backup(tmp_path / "backups")
    (target / "data" / "subscribers.csv").write_text("garbage\n", encoding="utf-8")

    before = (workspace / "data" / "subscribers.csv").read_bytes()
    assert backup_tool.restore(target, assume_yes=True) == 2
    assert (workspace / "data" / "subscribers.csv").read_bytes() == before


def test_restore_round_trips_the_exact_bytes(workspace, tmp_path):
    """The whole point: delete the registry, restore it, get the same file."""
    target = backup_tool.backup(tmp_path / "backups")
    original = (workspace / "data" / "subscribers.csv").read_bytes()

    for relative in ("data/subscribers.csv", "data/processed/risk_daily.csv"):
        (workspace / relative).unlink()
    assert not (workspace / "data" / "subscribers.csv").exists()

    assert backup_tool.restore(target, assume_yes=True) == 0
    assert (workspace / "data" / "subscribers.csv").read_bytes() == original
    assert (workspace / "data" / "processed" / "risk_daily.csv").exists()


def test_restore_is_a_no_op_without_the_confirmation_flag(workspace, tmp_path, capsys):
    target = backup_tool.backup(tmp_path / "backups")
    (workspace / "data" / "subscribers.csv").unlink()

    assert backup_tool.restore(target, assume_yes=False) == 0
    assert not (workspace / "data" / "subscribers.csv").exists(), "without --yes nothing may be written"
    assert "--yes" in capsys.readouterr().out


def test_a_missing_file_is_recorded_as_missing_not_invented(workspace, tmp_path):
    """A restore that silently drops a file is how people lose data."""
    (workspace / "data" / "processed" / "alert_log.csv").unlink()
    target = backup_tool.backup(tmp_path / "backups")

    manifest = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["files"]["data/processed/alert_log.csv"] == {"present": False}
    ok, missing, corrupt = backup_tool.verify(target)
    assert missing == [] and corrupt == [], "an absent file is not a corrupt snapshot"
    assert "data/processed/alert_log.csv" not in ok


def test_the_real_repository_has_the_files_the_manifest_expects():
    """Guards the INCLUDE list against a rename in the data layer."""
    from scripts.backup import INCLUDE, ROOT

    present = [relative for relative in INCLUDE if (ROOT / relative).exists()]
    assert "data/subscribers.csv" in present, (
        "the opt-in registry is the one file that cannot be regenerated — if it "
        "moved, scripts/backup.py must move with it"
    )
