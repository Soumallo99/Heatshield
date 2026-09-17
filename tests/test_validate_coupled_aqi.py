"""Observed-PM2.5 validation contract tests (all offline fixtures)."""
from __future__ import annotations

import json

import pandas as pd

from scripts import validate_coupled_aqi as validation


def _observations() -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01", periods=4 * 24, freq="h")
    # Daily means are 80, 100, 120, 140 µg/m³.
    values = [80] * 24 + [100] * 24 + [120] * 24 + [140] * 24
    return pd.DataFrame({"Date Time": timestamps.astype(str), "PM2.5": values})


def _model() -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01", periods=4 * 24, freq="h")
    values = [90] * 24 + [90] * 24 + [130] * 24 + [130] * 24
    return pd.DataFrame({"timestamp_local": timestamps.astype(str), "pm25_ugm3": values})


def test_tidy_cpcb_and_model_frames_to_daily_means():
    observed = validation.tidy_observations(_observations())
    model = validation.tidy_model(_model())

    assert observed["observed_pm25_ugm3"].tolist() == [80.0, 100.0, 120.0, 140.0]
    assert observed["observation_hours"].tolist() == [24, 24, 24, 24]
    assert model["model_pm25_ugm3"].tolist() == [90.0, 90.0, 130.0, 130.0]
    assert model["model_hours"].tolist() == [24, 24, 24, 24]


def test_metrics_use_error_and_csi_hss_not_bare_accuracy():
    paired = validation.tidy_observations(_observations()).merge(validation.tidy_model(_model()), on="date")
    metrics = validation.paired_metrics(paired, event_threshold=90)

    assert metrics["n_days"] == 4
    assert metrics["mae_ugm3"] == 10.0
    assert metrics["rmse_ugm3"] == 10.0
    assert metrics["mean_bias_ugm3"] == 0.0
    assert metrics["event_skill"] == {
        "hits": 3, "misses": 0, "false_alarms": 1, "correct_negatives": 0,
        "csi": 0.75, "hss": 0.0,
    }
    assert "accuracy" not in metrics


def test_report_distinguishes_validated_concentration_from_parameterised_load(tmp_path):
    report = validation.make_report(
        validation.tidy_observations(_observations()), validation.tidy_model(_model()),
        station="Fixture CPCB", source_url="https://example.test/cpcb", min_days_for_validated_claim=4,
    )
    path = validation.write_report(report, tmp_path / "report.json")
    parsed = json.loads(path.read_text())

    assert parsed["status"] == "validated-limited"
    assert "CPCB" in parsed["what_is_validated"]
    assert "not fitted" in parsed["what_is_parameterised"]
    assert "accuracy" in parsed["not_reported"].lower()
    assert parsed["metrics"]["cams_archive_vs_cpcb_observation"]["event_skill"]["csi"] == 0.75


def test_cli_can_replay_saved_observation_and_model_files_without_network(tmp_path):
    observed = tmp_path / "observed.csv"
    model = tmp_path / "model.csv"
    output = tmp_path / "validation.json"
    _observations().to_csv(observed, index=False)
    _model().to_csv(model, index=False)

    status = validation.main([
        "--observations", str(observed), "--model", str(model), "--output", str(output),
        "--min-days", "4", "--station", "Fixture CPCB",
    ])
    assert status == 0
    assert json.loads(output.read_text())["station"] == "Fixture CPCB"
