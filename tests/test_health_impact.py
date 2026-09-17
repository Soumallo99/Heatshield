"""Mortality / hospitalisation labelling-boundary tests.

The non-negotiable rule: nothing produced by this repo may call itself a
validated mortality forecast unless it is evaluated against named, documented
observed health-outcome data. No such data ships here, so every payload must
resolve to `parameterised_health_risk_indicator` or `synthetic_demo` — and the
path to `validated_observed_outcome_model` must require real evidence.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import core.coupled as coupled
from core import health_impact as hi
from app.main import app

VALID_COLUMNS = "date,location_id,outcome_type,count,source,data_quality\n"


def _offline(*_args, **_kwargs):
    raise OSError("simulated offline provider")


def _write_outcomes(path, rows=("2024-05-20,central-delhi,mortality,42,Municipal vital registration,official\n",)):
    path.write_text(VALID_COLUMNS + "".join(rows))
    return path


# --------------------------------------------------------------------------- #
# status resolution boundaries
# --------------------------------------------------------------------------- #

def test_demo_status_always_synthetic_even_with_evidence_present(tmp_path):
    outcomes = _write_outcomes(tmp_path / "outcomes.csv")
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({
        "observed_data_source": "Municipal vital registration 2019-2024",
        "metrics": {"csi": 0.61, "hss": 0.55},
    }))
    status, meaning = hi.resolve_model_status(demo=True, outcomes_path=outcomes, evaluation_path=evaluation)
    assert status == hi.STATUS_SYNTHETIC_DEMO
    assert "not a live forecast" in meaning


def test_parameterised_by_default_because_no_outcome_data_ships(tmp_path):
    status, meaning = hi.resolve_model_status(outcomes_path=None, evaluation_path=tmp_path / "absent.json")
    assert status == hi.STATUS_PARAMETERISED
    assert "NOT a validated forecast" in meaning


def test_validated_requires_named_dataset_metrics_and_loadable_outcomes(tmp_path):
    outcomes = _write_outcomes(tmp_path / "outcomes.csv")
    evaluation = tmp_path / "evaluation.json"

    # 1. no report at all
    assert hi.resolve_model_status(outcomes_path=outcomes, evaluation_path=tmp_path / "absent.json")[0] \
        == hi.STATUS_PARAMETERISED

    # 2. report without a named dataset
    evaluation.write_text(json.dumps({"metrics": {"csi": 0.6}}))
    assert hi.resolve_model_status(outcomes_path=outcomes, evaluation_path=evaluation)[0] \
        == hi.STATUS_PARAMETERISED

    # 3. report without outcome-linked metrics
    evaluation.write_text(json.dumps({"observed_data_source": "Named registry"}))
    assert hi.resolve_model_status(outcomes_path=outcomes, evaluation_path=evaluation)[0] \
        == hi.STATUS_PARAMETERISED

    # 4. report complete but outcome file missing/broken
    evaluation.write_text(json.dumps({"observed_data_source": "Named registry", "metrics": {"csi": 0.6}}))
    assert hi.resolve_model_status(outcomes_path=tmp_path / "missing.csv", evaluation_path=evaluation)[0] \
        == hi.STATUS_PARAMETERISED

    # 5. all evidence present — only NOW may the status be validated
    assert hi.resolve_model_status(outcomes_path=outcomes, evaluation_path=evaluation)[0] \
        == hi.STATUS_VALIDATED


def test_committed_repo_state_can_never_resolve_to_validated():
    """With the paths as committed (no evaluation report), the live route's
    status is parameterised. This is the guard against a future commit
    quietly flipping the claim on."""
    status, _ = hi.resolve_model_status(outcomes_path=None)
    assert status == hi.STATUS_PARAMETERISED
    assert not hi.EVALUATION_REPORT_PATH.exists()


# --------------------------------------------------------------------------- #
# outcome ingestion schema
# --------------------------------------------------------------------------- #

def test_schema_documents_required_columns():
    required = hi.HEALTH_OUTCOME_SCHEMA["required_columns"]
    assert {"date", "location_id", "outcome_type", "count", "source", "data_quality"} <= set(required)


def test_loader_accepts_a_conforming_file(tmp_path):
    path = _write_outcomes(tmp_path / "outcomes.csv", rows=(
        "2024-05-20,central-delhi,mortality,42,Municipal vital registration,official\n"
        "2024-05-21,central-delhi,hospitalisation,17,Hospital HMIS extract,provisional\n"
    ))
    frame, metadata = hi.load_health_outcomes(path)
    assert len(frame) == 2
    assert metadata["rows"] == 2
    assert metadata["sources"] == ["Hospital HMIS extract", "Municipal vital registration"]
    assert set(metadata["quality_flags_present"]) == {"official", "provisional"}


def test_loader_rejects_malformed_outcome_files(tmp_path):
    with pytest.raises(ValueError, match="missing required columns"):
        path = tmp_path / "bad.csv"
        path.write_text("date,location_id\n2024-05-20,x\n")
        hi.load_health_outcomes(path)

    with pytest.raises(ValueError, match="unknown outcome_type"):
        _write_outcomes(tmp_path / "bad2.csv", rows=("2024-05-20,x,deaths,3,src,official\n"))
        hi.load_health_outcomes(tmp_path / "bad2.csv")

    with pytest.raises(ValueError, match="negative or non-numeric"):
        _write_outcomes(tmp_path / "bad3.csv", rows=("2024-05-20,x,mortality,-3,src,official\n"))
        hi.load_health_outcomes(tmp_path / "bad3.csv")

    with pytest.raises(ValueError, match="unknown data_quality"):
        _write_outcomes(tmp_path / "bad4.csv", rows=("2024-05-20,x,mortality,3,src,guessed\n"))
        hi.load_health_outcomes(tmp_path / "bad4.csv")

    with pytest.raises(ValueError, match="not found"):
        hi.load_health_outcomes(tmp_path / "absent.csv")


# --------------------------------------------------------------------------- #
# indicator arithmetic
# --------------------------------------------------------------------------- #

def test_indicator_is_bounded_monotonic_and_degrades_transparently():
    assert hi.health_impact_index(None, 50.0) is None          # no HTSI, no fake zero
    low = hi.health_impact_index(30.0, 40.0)
    high = hi.health_impact_index(80.0, 40.0)
    assert high > low
    vuln_high = hi.health_impact_index(60.0, 90.0)
    vuln_low = hi.health_impact_index(60.0, 10.0)
    assert vuln_high > vuln_low
    assert 0.0 <= hi.health_impact_index(100.0, 100.0, departure_c=10.0, aqi=500.0) <= 100.0
    # Missing vulnerability falls back to a documented 50.0 placeholder.
    fallback = hi.health_impact_index(60.0, None)
    explicit = hi.health_impact_index(60.0, 50.0)
    assert fallback == explicit


def test_band_labels_are_words_not_just_numbers():
    assert hi.health_impact_band(10.0) == "Low"
    assert hi.health_impact_band(30.0) == "Moderate"
    assert hi.health_impact_band(50.0) == "High"
    assert hi.health_impact_band(70.0) == "Very High"
    assert hi.health_impact_band(None) == "Unavailable"


# --------------------------------------------------------------------------- #
# API payloads cannot mislabel demo/parameterised output as validated
# --------------------------------------------------------------------------- #

def test_demo_and_live_payloads_never_claim_a_validated_mortality_model(monkeypatch):
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)
    client = TestClient(app)

    demo_rows = client.get("/demo/warnings?scenario=dry-extreme").json()["data"]
    assert demo_rows
    for row in demo_rows:
        assert row["health_impact_status"] == hi.STATUS_SYNTHETIC_DEMO
        assert row["health_impact_status"] != hi.STATUS_VALIDATED

    live = client.get("/warnings/advance").json()
    assert live["data"]
    for row in live["data"]:
        assert row["health_impact_status"] == hi.STATUS_PARAMETERISED
        assert "NOT a validated forecast" in row["health_impact_status_meaning"]
        # Vulnerability inputs are synthetic placeholders and say so on the row.
        assert "synthetic" in row["vulnerability_source"].lower()

    # The full serialized payloads must not contain the validated status string
    # anywhere — not in a stray field, not in metadata.
    assert hi.STATUS_VALIDATED not in json.dumps(demo_rows)
    assert hi.STATUS_VALIDATED not in json.dumps(live["data"])

    notifications = client.get("/demo/notifications?scenario=dry-extreme").json()
    for preview in notifications["previews"]:
        assert preview["health_impact_status"] == hi.STATUS_SYNTHETIC_DEMO


def test_health_impact_block_lists_what_validation_would_require():
    block = hi.health_impact_block(
        htsi_score_value=72.0, vulnerability=55.0, departure_c=4.0, aqi=180.0, demo=True,
        vulnerability_source="synthetic demo profile",
    )
    assert block["model_status"] == hi.STATUS_SYNTHETIC_DEMO
    assert block["validation_requirements"]
    assert any("observed outcome counts" in requirement.lower() or "outcome counts" in requirement.lower()
               for requirement in block["validation_requirements"])
    assert block["parameters"]["not_a_forecast_of"]
    assert block["inputs"]["missing_terms"] == []
