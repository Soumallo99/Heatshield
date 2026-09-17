"""Human Thermal Stress Index tests — formulas, edge cases, quality flags.

The truthfulness rule under test: an estimated WBGT is never presented as a
measurement, a missing input always degrades to a labelled assumption, and
vulnerability can never leak into the meteorological stress score.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core import htsi
from core.htsi import (
    ASSUMPTION_NO_RADIATION,
    ASSUMPTION_NO_WIND,
    HTSI_METADATA,
    QUALITY_ESTIMATED,
    QUALITY_PARTIAL,
    QUALITY_UNAVAILABLE,
    compute_htsi_frame,
    htsi_band,
    htsi_score,
    thermal_metrics,
)
from core.thermal import heat_index


# --------------------------------------------------------------------------- #
# Heat Index documented range and limits
# --------------------------------------------------------------------------- #

def test_heat_index_below_20c_returns_air_temperature():
    assert thermal_metrics(15.0, 80.0)["heat_index_c"] == pytest.approx(15.0, abs=0.2)


def test_heat_index_is_monotonic_in_humidity_when_hot():
    values = [thermal_metrics(36.0, rh)["heat_index_c"] for rh in (30.0, 50.0, 70.0, 90.0)]
    assert values == sorted(values)
    assert values[-1] > values[0] + 5.0


def test_heat_index_metadata_documents_range_and_limits():
    hi_meta = HTSI_METADATA["metrics"]["heat_index_c"]
    assert "26.7" in hi_meta["valid_range"]
    assert "shade" in hi_meta["limitations"].lower()
    assert hi_meta["quality_best_case"] == QUALITY_ESTIMATED
    assert "Rothfusz" in hi_meta["formula"]


# --------------------------------------------------------------------------- #
# Quality flags for missing radiation / wind / humidity
# --------------------------------------------------------------------------- #

def test_full_inputs_produce_an_estimated_not_measured_wbgt():
    metrics = thermal_metrics(40.0, 30.0, wind_kmh=10.0, solar_wm2=900.0)
    assert metrics["wbgt_quality"] == QUALITY_ESTIMATED
    assert metrics["assumptions"] == []
    assert metrics["missing_inputs"] == []
    assert metrics["inputs_available"] == {
        "temperature": True, "humidity": True, "wind": True, "radiation": True,
    }
    # "estimated" is the ceiling — this module never claims "measured".
    assert metrics["wbgt_quality"] != "measured"


def test_missing_radiation_degrades_to_labelled_shade_form():
    metrics = thermal_metrics(40.0, 30.0, wind_kmh=10.0)
    assert metrics["wbgt_quality"] == QUALITY_PARTIAL
    assert ASSUMPTION_NO_RADIATION in metrics["assumptions"]
    assert metrics["missing_inputs"] == ["radiation"]
    full = thermal_metrics(40.0, 30.0, wind_kmh=10.0, solar_wm2=900.0)
    # The shade form must UNDERSTATE stress relative to full sun — the
    # assumption text says so, and the numbers must agree.
    assert metrics["wbgt_est_c"] < full["wbgt_est_c"]
    assert metrics["globe_c"] is None


def test_missing_wind_degrades_to_labelled_free_convection_floor():
    metrics = thermal_metrics(40.0, 30.0, solar_wm2=900.0)
    assert metrics["wbgt_quality"] == QUALITY_PARTIAL
    assert ASSUMPTION_NO_WIND in metrics["assumptions"]
    windy = thermal_metrics(40.0, 30.0, wind_kmh=20.0, solar_wm2=900.0)
    assert metrics["wbgt_est_c"] > windy["wbgt_est_c"]   # still air = hotter globe


def test_missing_humidity_or_temperature_is_unavailable_never_invented():
    dry = thermal_metrics(40.0, None, wind_kmh=10.0, solar_wm2=900.0)
    assert dry["wbgt_quality"] == QUALITY_UNAVAILABLE
    assert dry["wbgt_est_c"] is None and dry["heat_index_c"] is None
    assert "humidity" in dry["missing_inputs"]

    cold = thermal_metrics(None, 40.0)
    assert cold["wbgt_quality"] == QUALITY_UNAVAILABLE
    assert cold["wbgt_est_c"] is None


def test_frame_flags_partial_input_when_the_radiation_column_is_absent():
    frame = pd.DataFrame({
        "timestamp_local": pd.date_range("2026-05-18", periods=4, freq="h"),
        "temp_c": [38.0, 39.0, 40.0, 39.5],
        "rh_pct": [30.0, 28.0, 25.0, 27.0],
        "wind_kmh": [9.0, 8.0, 7.0, 8.5],
    })
    scored = compute_htsi_frame(frame)
    assert (scored["wbgt_quality"] == QUALITY_PARTIAL).all()
    assert (scored["wbgt_inputs"] == "temperature+humidity+wind").all()
    assert scored["wbgt_est_c"].notna().all()


# --------------------------------------------------------------------------- #
# Score behaviour
# --------------------------------------------------------------------------- #

def test_score_is_monotonic_in_wbgt_and_bounded():
    scores = [htsi_score(w) for w in (24.0, 26.0, 28.0, 30.0, 32.0, 34.0, 40.0)]
    assert scores == sorted(scores)
    assert scores[0] == 0.0
    assert all(0.0 <= s <= 100.0 for s in scores)


def test_anomaly_bonus_uses_fixed_normal_and_caps_at_eight_points():
    base = htsi_score(31.0, departure_c=None)
    plus_four = htsi_score(31.0, departure_c=4.0)
    plus_twenty = htsi_score(31.0, departure_c=20.0)
    assert plus_four == pytest.approx(base + 6.4, abs=0.15)
    assert plus_twenty == pytest.approx(min(100.0, base + 8.0), abs=0.15)
    # Negative departures never subtract: a cool anomaly is not a hazard credit.
    assert htsi_score(31.0, departure_c=-5.0) == base


def test_invalid_scores_never_become_numbers():
    assert htsi_score(None) is None
    assert htsi_score(float("nan")) is None
    assert htsi_score("hot") is None


def test_band_thresholds_are_documented_and_text_carrying():
    assert htsi_band(10.0)["band"] == "Normal"
    assert htsi_band(30.0)["band"] == "Watch"       # boundary is inclusive
    assert htsi_band(54.9)["band"] == "Watch"
    assert htsi_band(55.0)["band"] == "Warning"
    assert htsi_band(75.0)["band"] == "Severe"
    assert htsi_band(None)["band"] == "Unavailable"
    # Every band carries words, not just a colour — no colour-only channels.
    for entry in HTSI_METADATA["bands"]:
        assert entry["band"] and entry["meaning"] and entry["colour"]


def test_vulnerability_cannot_leak_into_the_meteorological_score():
    signature = inspect_signature(htsi_score)
    assert "vulnerability" not in signature
    assert "separate" in HTSI_METADATA["separation_rule"].lower()


def inspect_signature(function) -> str:
    import inspect
    return str(inspect.signature(function))


def test_utci_is_explicitly_unavailable_rather_than_faked():
    utci_meta = HTSI_METADATA["metrics"]["utci_c"]
    assert utci_meta["formula"] is None
    assert "NOT COMPUTED" in utci_meta["limitations"]


def test_wbgt_estimate_consistency_with_core_physics():
    """The single-observation path must agree with the vectorised frame path."""
    frame = pd.DataFrame({
        "timestamp_local": pd.date_range("2026-05-18 12:00", periods=1, freq="h"),
        "temp_c": [42.0], "rh_pct": [22.0], "wind_kmh": [8.0], "solar_wm2": [980.0],
    })
    scored = compute_htsi_frame(frame).iloc[0]
    metrics = thermal_metrics(42.0, 22.0, wind_kmh=8.0, solar_wm2=980.0)
    assert scored["wbgt_est_c"] == pytest.approx(metrics["wbgt_est_c"], abs=0.02)
    assert scored["heat_index_c"] == pytest.approx(metrics["heat_index_c"], abs=0.11)
    assert scored["wet_bulb_c"] == pytest.approx(metrics["wet_bulb_c"], abs=0.02)
    assert math.isfinite(scored["htsi_score"])
