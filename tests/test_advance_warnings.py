"""Advance-warning pipeline tests: lead times, persistence, provenance, no 500s.

Covers the live route (/warnings/advance) and the shared row builder used by
the demo. The headline guarantee: a provider outage degrades to labelled
synthetic data — it never becomes an HTTP 500 on a warning route.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import core.coupled as coupled
import core.demo as demo
from app.main import app
from core.warnings import (
    ALERT_LEVELS,
    build_warning_rows,
    derive_alert_level,
    zone_profiles,
)

REQUIRED_ROW_FIELDS = {
    "zone_id", "zone_name", "issued_at", "issued_at_utc", "target_date",
    "target_day_label", "lead_days", "lead_hours", "lead_time_basis",
    "tmax_c", "normal_tmax_c", "normal_granularity", "departure_c",
    "heatwave_candidate", "is_heatwave_episode", "is_severe_episode",
    "episode_day", "episode_length", "heatwave_label", "extreme_temperature_watch",
    "hi_peak_c", "wbgt_est_peak_c", "wbgt_peak_quality", "htsi_score",
    "htsi_band", "thermal_stress_level", "htsi_anomaly_used",
    "vulnerability_score", "vulnerability_level", "vulnerability_source",
    "health_impact_index", "health_impact_band", "health_impact_status",
    "aqi_peak", "aqi_band", "heat_aqi_load_peak", "heat_aqi_load_band",
    "alert_level", "recommended_action_level", "alert_level_drivers", "reason",
    "action_summary", "data_source", "quality_state", "is_demo", "is_synthetic",
    "confidence",
}


def _offline(*_args, **_kwargs):
    raise OSError("simulated provider outage")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)
    yield
    coupled.clear_ncr_cache()


# --------------------------------------------------------------------------- #
# live route resilience
# --------------------------------------------------------------------------- #

def test_live_route_returns_200_with_labelled_fallback_when_provider_is_down():
    response = TestClient(app).get("/warnings/advance")
    assert response.status_code == 200
    body = response.json()
    assert body["is_synthetic"] is True
    assert body["quality_state"] == "synthetic-fallback"
    assert "simulated provider outage" in body["fallback_reason"]
    assert body["is_demo"] is False   # fallback ≠ demo: different label, same honesty
    assert "NaN" not in response.text


def test_live_route_produces_lead_times_3_4_and_5():
    body = TestClient(app).get("/warnings/advance").json()
    leads = {row["lead_days"] for row in body["data"]}
    assert {0, 1, 2, 3, 4, 5}.issubset(leads)
    for lead in (3, 4, 5):
        rows = [row for row in body["data"] if row["lead_days"] == lead]
        assert len(rows) == 8
        for row in rows:
            # lead_hours = issuance → 15:00 local on the target day, whatever
            # the (live) issuance hour happens to be.
            issued = pd.Timestamp(row["issued_at"])
            target_peak = pd.Timestamp(row["target_date"]) + pd.Timedelta(hours=15)
            expected_hours = int((target_peak - issued).total_seconds() // 3600)
            assert row["lead_hours"] == expected_hours
            assert row["target_day_label"] == f"Day +{lead}"


def test_every_row_carries_the_full_decision_chain():
    body = TestClient(app).get("/warnings/advance").json()
    assert body["data"]
    for row in body["data"]:
        missing = REQUIRED_ROW_FIELDS - set(row)
        assert not missing, f"row missing {missing}"
        assert row["alert_level"] in ALERT_LEVELS
        assert row["thermal_stress_level"] in ("Normal", "Watch", "Warning", "Severe", "Unavailable")
        assert row["vulnerability_level"] in ("Low", "Moderate", "High", "Unavailable")
        assert row["health_impact_status"] in (
            "parameterised_health_risk_indicator", "synthetic_demo")
        assert row["wbgt_peak_quality"] in ("estimated", "partial-input", "unavailable")
        assert row["lead_time_basis"]


def test_unknown_zone_is_a_404_not_a_500():
    assert TestClient(app).get("/warnings/advance?zone_id=atlantis").status_code == 404


def test_payload_ships_the_action_matrix_and_climatology_provenance():
    body = TestClient(app).get("/warnings/advance").json()
    matrix = body["action_matrix"]
    assert set(matrix) == set(ALERT_LEVELS)
    for level in ("warning", "severe"):
        actions = " ".join(matrix[level]["municipal_actions"]).lower()
        assert "cooling" in actions
        assert "outdoor work" in actions
    assert body["climatology"]["available"] is True
    assert "1991" in str(body["climatology"]["reference_period"])
    assert "never a forecast-window average" in body["climatology"]["note"]
    assert "two-day" in body["persistence_rule"].lower() or "≥ 2" in body["persistence_rule"]


# --------------------------------------------------------------------------- #
# persistence + normals behaviour through the builder
# --------------------------------------------------------------------------- #

def _hourly_from_daily(tmax_by_day: list[float], zone_id: str = "central-delhi") -> pd.DataFrame:
    """Minimal hourly frame with a single hot hour per day at 15:00."""
    start = demo.DEMO_ISSUED_AT_LOCAL.normalize()
    rows = []
    for day_index, tmax in enumerate(tmax_by_day):
        for hour in range(24):
            ts = start + pd.Timedelta(days=day_index, hours=hour)
            temp = tmax if hour == 15 else tmax - 7.0
            rows.append({
                "zone_id": zone_id, "zone_name": "Central Delhi", "lat": 28.6139, "lon": 77.209,
                "timestamp_local": ts, "temp_c": temp, "rh_pct": 30.0, "wind_kmh": 8.0,
                "solar_wm2": 950.0 if 8 <= hour <= 17 else 0.0, "precip_mm": 0.0,
                "pm25_ugm3": 60.0, "pm10_ugm3": 95.0, "no2_ugm3": 30.0, "o3_ugm3": 30.0,
                "so2_ugm3": 8.0, "provider_us_aqi": None,
            })
    frame = coupled._apply_coupling(pd.DataFrame(rows))
    frame["data_source"] = "test"
    frame["is_synthetic"] = True
    frame["fetched_at"] = "2026-05-18T00:30:00+00:00"
    return frame


def test_single_candidate_day_stays_an_early_watch_not_an_episode():
    # Only Day +3 breaches the IMD departure rule; persistence requires two.
    frame = _hourly_from_daily([40.0, 40.5, 40.2, 46.5, 40.8, 40.4])
    rows = build_warning_rows(
        frame, issued_at=demo.DEMO_ISSUED_AT_LOCAL, quality_state="test",
        data_source="test frame", climatology=coupled.load_climatology(),
    )
    by_lead = {row["lead_days"]: row for row in rows}
    assert by_lead[3]["heatwave_candidate"] is True
    assert by_lead[3]["is_heatwave_episode"] is False
    assert by_lead[3]["heatwave_label"] == "Watch"
    assert by_lead[2]["heatwave_candidate"] is False
    assert all(row["is_heatwave_episode"] is False for row in rows)


def test_two_consecutive_candidates_declare_an_episode_and_every_day_knows_it():
    frame = _hourly_from_daily([40.0, 40.5, 45.6, 46.8, 47.4, 40.4])
    rows = build_warning_rows(
        frame, issued_at=demo.DEMO_ISSUED_AT_LOCAL, quality_state="test",
        data_source="test frame", climatology=coupled.load_climatology(),
    )
    by_lead = {row["lead_days"]: row for row in rows}
    for lead in (2, 3, 4):
        assert by_lead[lead]["is_heatwave_episode"] is True
        assert by_lead[lead]["episode_length"] == 3
        assert by_lead[lead]["episode_day"] == lead - 1
    assert by_lead[3]["is_severe_episode"] is True      # departure ≥ 6.5 °C inside block
    assert by_lead[5]["is_heatwave_episode"] is False   # episode ended


def test_normals_are_the_fixed_climatology_not_a_window_mean():
    climatology = coupled.load_climatology()
    frame = _hourly_from_daily([40.0, 40.5, 45.6, 46.8, 47.4, 46.9])
    rows = build_warning_rows(
        frame, issued_at=demo.DEMO_ISSUED_AT_LOCAL, quality_state="test",
        data_source="test frame", climatology=climatology,
    )
    window_mean = sum(r["tmax_c"] for r in rows) / len(rows)
    for row in rows:
        normal, granularity = coupled.climatology_normal(climatology, row["zone_id"], row["target_date"])
        assert row["normal_tmax_c"] == pytest.approx(round(normal, 1))
        assert row["normal_granularity"] == "daily"
        assert abs(row["normal_tmax_c"] - window_mean) > 1.0   # not a window statistic
        assert row["departure_c"] == pytest.approx(row["tmax_c"] - row["normal_tmax_c"], abs=0.15)


# --------------------------------------------------------------------------- #
# alert-level escalation rule
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("thermal,heatwave,load,expected", [
    ("Normal", "None", "Good", "routine"),
    ("Watch", "None", "Moderate", "watch"),
    ("Normal", "Watch", "Good", "watch"),
    ("Warning", "None", "Good", "warning"),
    ("Normal", "Heat Wave", "Good", "warning"),
    ("Severe", "None", "Good", "severe"),
    ("Normal", "Severe Heat Wave", "Good", "severe"),
    ("Watch", "None", "Severe", "warning"),        # air load lifts one step
    ("Warning", "None", "Severe", "severe"),        # severe load + warning thermal
])
def test_escalation_rule_is_explicit(thermal, heatwave, load, expected):
    level, drivers = derive_alert_level(thermal, heatwave, load)
    assert level == expected
    assert len(drivers) == 3


def test_partial_input_wbgt_still_flags_the_row():
    frame = _hourly_from_daily([40.0, 41.0, 42.0, 43.0, 44.0, 45.0]).drop(columns=["solar_wm2"])
    rows = build_warning_rows(
        frame, issued_at=demo.DEMO_ISSUED_AT_LOCAL, quality_state="test",
        data_source="test frame without radiation", climatology=coupled.load_climatology(),
    )
    assert rows
    for row in rows:
        assert row["wbgt_peak_quality"] == "partial-input"
        assert row["wbgt_peak_inputs"] == "temperature+humidity+wind"


def test_zone_profiles_are_labelled_synthetic_and_cover_every_zone():
    profiles = zone_profiles()
    assert set(profiles["zone_id"]) == {zone["zone_id"] for zone in coupled.NCR_ZONES}
    assert (profiles["vulnerability_source"].str.contains("synthetic", case=False)).all()
    assert profiles["vulnerability_score"].between(0, 100).all()
    assert len({round(v) for v in profiles["vulnerability_score"]}) >= 5
