"""Heat Risk Demo scenario tests.

The demo must be deterministic (no clock, no network, no RNG), fully labelled
as synthetic, and must exercise the whole product surface: five-day outlook
with explicit lead times, multiple zones at different risk levels, HTSI,
vulnerability, health-impact status, actions and notification previews.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import core.coupled as coupled
import core.demo as demo
from app.main import app

DISCLAIMER = "Demo / synthetic scenario — not a live forecast or observation."


def test_canonical_disclaimer_is_defined_once():
    """demo + notify + warnings must quote the identical sentence."""
    assert demo.DEMO_DISCLAIMER == DISCLAIMER
    from core import notify, warnings
    assert warnings.DEMO_DISCLAIMER == DISCLAIMER
    assert notify.DEMO_DISCLAIMER == DISCLAIMER


def _offline(*_args, **_kwargs):
    raise OSError("simulated offline provider")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The demo must be identical with or without a provider — take it away."""
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)
    yield
    coupled.clear_ncr_cache()


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #

def test_scenario_frame_is_deterministic_and_clock_independent():
    first = demo.scenario_frame("dry-extreme")
    second = demo.scenario_frame("dry-extreme")
    pd.testing.assert_frame_equal(first, second)
    # The scenario clock is FIXED: it never moves with the review date.
    assert first["timestamp_local"].min() == demo.DEMO_ISSUED_AT_LOCAL.normalize()
    assert str(first["issued_at"].iloc[0]) == "2026-05-18T06:00"
    assert str(first["fetched_at"].iloc[0]) == "2026-05-18T00:30:00+00:00"


def test_warning_payloads_are_byte_identical_between_calls():
    a = json.dumps(demo.warnings_payload("humid-dangerous"), sort_keys=True, default=str)
    b = json.dumps(demo.warnings_payload("humid-dangerous"), sort_keys=True, default=str)
    assert a == b


# --------------------------------------------------------------------------- #
# catalogue + labels
# --------------------------------------------------------------------------- #

def test_catalogue_has_the_required_presets_and_metadata():
    ids = set(demo.scenario_ids())
    assert {"dry-extreme", "humid-dangerous", "heat-plus-pollution"}.issubset(ids)
    assert len(ids) >= 4  # including a near-normal baseline preset
    for scenario_id in ids:
        meta = demo.scenario_meta(scenario_id)
        assert meta["label"] and meta["summary"] and meta["teaching_points"]
        assert meta["is_demo"] is True and meta["is_synthetic"] is True
        assert meta["demo_disclaimer"] == DISCLAIMER
        assert meta["forecast_days"] == 6


def test_every_demo_payload_is_labelled_synthetic():
    payloads = [
        demo.scenarios_payload(),
        demo.zones_payload(),
    ]
    for scenario_id in demo.scenario_ids():
        payloads.extend((
            demo.forecast_payload(scenario_id),
            demo.thermal_payload(scenario_id),
            demo.warnings_payload(scenario_id),
            demo.notifications_payload(scenario_id),
        ))
    for payload in payloads:
        assert payload["is_demo"] is True
        text = json.dumps(payload, default=str, ensure_ascii=False)
        assert DISCLAIMER in text
        assert "NaN" not in text


# --------------------------------------------------------------------------- #
# five-day outlook with explicit lead times
# --------------------------------------------------------------------------- #

def test_every_scenario_shows_day_3_day_4_and_day_5_for_every_zone():
    for scenario_id in demo.scenario_ids():
        rows = demo.warnings_payload(scenario_id)["data"]
        zones = {row["zone_id"] for row in rows}
        assert len(zones) == 8
        for lead in (3, 4, 5):
            lead_rows = [row for row in rows if row["lead_days"] == lead]
            assert len(lead_rows) == 8, (scenario_id, lead)
            for row in lead_rows:
                target = pd.Timestamp(row["target_date"])
                issued = pd.Timestamp(row["issued_at"])
                assert row["target_day_label"] == f"Day +{lead}"
                assert (target.date() - issued.date()).days == lead
                assert row["lead_hours"] == lead * 24 + 9   # 06:00 issue → 15:00 peak
                assert row["issued_at"] == "2026-05-18T06:00"
                assert row["issued_at_utc"] == "2026-05-18T00:30:00Z"


def test_zones_show_different_risk_and_vulnerability_levels():
    rows = demo.warnings_payload("dry-extreme")["data"]
    day3 = [row for row in rows if row["lead_days"] == 3]
    assert len({row["alert_level"] for row in day3}) >= 2
    # Across the scenario, zones/days must span multiple thermal-stress bands.
    assert len({row["htsi_band"] for row in rows}) >= 2
    profiles = demo.zones_payload()["data"]
    assert len({zone["vulnerability_level"] for zone in profiles}) >= 2
    assert len({zone["vulnerability_score"] for zone in profiles}) >= 5


# --------------------------------------------------------------------------- #
# scenario physics and detection behaviour
# --------------------------------------------------------------------------- #

def test_dry_extreme_declares_severe_episode_with_3_to_5_day_lead():
    rows = demo.warnings_payload("dry-extreme")["data"]
    core_rows = [row for row in rows if row["zone_id"] == "central-delhi"]
    for lead in (3, 4, 5):
        row = next(r for r in core_rows if r["lead_days"] == lead)
        assert row["is_heatwave_episode"] is True
        assert row["heatwave_label"] == "Severe Heat Wave"
        assert row["alert_level"] == "severe"
        assert row["tmax_c"] >= 45.0
    # The persistence rule is visible: the episode is a multi-day block.
    episode_rows = [row for row in core_rows if row["is_heatwave_episode"]]
    assert max(row["episode_length"] for row in episode_rows) >= 2


def test_humid_scenario_is_dangerous_while_imd_tmax_rule_stays_quiet():
    rows = demo.warnings_payload("humid-dangerous")["data"]
    severe = [row for row in rows if row["alert_level"] == "severe"]
    assert severe, "humid dangerous heat must reach the severe level"
    quiet = [row for row in severe if row["heatwave_label"] == "None"]
    assert quiet, "the teaching point is severe WBGT stress WITHOUT an IMD Tmax declaration"
    for row in quiet:
        assert row["wbgt_est_peak_c"] >= 33.0
        assert row["tmax_c"] < 40.0
    frame = demo.scenario_frame("humid-dangerous")
    peak = frame[frame["temp_c"] == frame["temp_c"].max()].iloc[0]
    assert peak["rh_pct"] >= 60.0


def test_pollution_scenario_keeps_concentration_aqi_separate_from_joint_load():
    rows = demo.warnings_payload("heat-plus-pollution")["data"]
    worst = max(rows, key=lambda row: row.get("heat_aqi_load_peak") or 0)
    assert worst["aqi_band"] in ("Very Poor", "Severe")
    assert worst["heat_aqi_load_peak"] > worst["aqi_peak"]   # load = AQI × heat multiplier
    assert worst["heat_aqi_load_band"] == "Severe"
    assert worst["alert_level"] == "severe"


def test_baseline_scenario_shows_normal_and_watch_without_episodes():
    payload = demo.warnings_payload("monsoon-break")
    levels = {row["alert_level"] for row in payload["data"]}
    assert levels <= {"routine", "watch"}
    assert not any(row["is_heatwave_episode"] for row in payload["data"])
    assert not any(row["heatwave_candidate"] for row in payload["data"])


def test_demo_anomaly_logic_uses_the_fixed_1991_2020_normals():
    climatology = coupled.load_climatology()
    assert climatology is not None
    rows = demo.warnings_payload("dry-extreme")["data"]
    for row in rows[:24]:
        normal, granularity = coupled.climatology_normal(climatology, row["zone_id"], row["target_date"])
        assert row["normal_tmax_c"] == pytest.approx(round(normal, 1))
        assert row["normal_granularity"] == granularity == "daily"
        # A forecast-window mean would differ from the fixed normal — assert the
        # row uses the fixed one, never a window statistic.
        assert row["departure_c"] == pytest.approx(round(row["tmax_c"] - normal, 1), abs=0.15)


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #

def test_demo_routes_reject_unknown_scenarios_and_zones_with_404():
    client = TestClient(app)
    assert client.get("/demo/forecast?scenario=nope").status_code == 404
    assert client.get("/demo/warnings?zone_id=nowhere").status_code == 404
    assert client.get("/demo/thermal?zone_id=nowhere").status_code == 404


def test_demo_routes_answer_200_with_no_provider_reachable():
    client = TestClient(app)
    for path in ("/demo/scenarios", "/demo/zones", "/demo/forecast", "/demo/thermal",
                 "/demo/warnings", "/demo/notifications"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json()["is_demo"] is True or "scenarios" in response.json()


def test_forecast_payload_provides_current_conditions_and_outlook_rows():
    payload = demo.forecast_payload("dry-extreme")
    assert payload["rows_daily"] == 8 * 6
    # Issue-day hourly detail drives the "current thermal conditions" panel.
    assert payload["rows_hourly"] == 8 * 24
    hourly = payload["hourly"]
    assert {"temp_c", "rh_pct", "wind_kmh", "solar_wm2"} <= set(hourly[0])
    daily = payload["daily"]
    leads = sorted({row["lead_days"] for row in daily})
    assert leads == [0, 1, 2, 3, 4, 5]


def test_thermal_payload_documents_every_metric_and_quality_flag():
    payload = demo.thermal_payload("dry-extreme")
    method = payload["method"]
    assert method["metrics"]["heat_index_c"]["valid_range"]
    assert method["metrics"]["heat_index_c"]["limitations"]
    assert "ESTIMATED WBGT" in payload["wbgt_statement"]
    assert method["metrics"]["utci_c"]["quality_best_case"] == "unavailable"
    for row in payload["daily"]:
        assert row["wbgt_peak_quality"] == "estimated"      # demo provides all inputs
        assert row["wbgt_peak_inputs"] == "temperature+humidity+wind+radiation"
        assert row["htsi_band"] in ("Normal", "Watch", "Warning", "Severe", "Unavailable")
