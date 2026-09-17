"""Regression tests for NCR heat + air-quality paths.

The important test here deliberately takes the provider down.  A fallback that
only exists in a try/except but never executes is untested code; this suite
exercises the eight-zone case that previously indexed past a four-name list.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient

import core.coupled as coupled
from app.main import app


def _offline(*_args, **_kwargs):
    raise OSError("simulated offline provider")


def test_synthetic_supports_eight_zones_and_marks_every_row():
    frame = coupled._synthetic(zones=8, days=3, now=pd.Timestamp("2026-05-20 09:00"))

    assert frame["zone_id"].nunique() == 8
    assert frame["zone_name"].nunique() == 8
    assert len(frame) == 8 * 3 * 24
    assert frame["is_synthetic"].all()
    assert frame["data_source"].str.contains("synthetic", case=False).all()
    # Eight canonical names now exist; this was previously an IndexError after
    # the fourth name rather than a real fallback frame.
    assert {"Faridabad", "Central Delhi"}.issubset(set(frame["zone_name"]))


def test_ncr_frame_uses_synthetic_episode_when_both_live_sources_fail(monkeypatch):
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)

    frame, reason = coupled._ncr_frame(zones=8, days=4, use_cache=False)

    assert len(frame) == 8 * 4 * 24
    assert frame["is_synthetic"].all()
    assert "simulated offline provider" in (reason or "")


def test_heatwave_advance_is_200_and_labelled_when_network_is_down(monkeypatch):
    """The endpoint used to call a live source directly and return 500 offline."""
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)

    response = TestClient(app).get("/heatwave/advance?days=5")
    body = response.json()

    assert response.status_code == 200
    assert body["is_synthetic"] is True
    assert "simulated offline provider" in body["fallback_reason"]
    # The five 24-hour windows can straddle six local calendar dates; every
    # NCR location must nevertheless be present in the returned daily frame.
    assert body["rows"] >= 8 * 5
    assert len({row["zone_id"] for row in body["data"]}) == 8
    assert body["data"]
    assert all("heatwave_label" in row for row in body["data"])


def test_indian_pm25_breakpoints_and_bands_are_not_us_aqi_labels():
    values = coupled.aqi_from_pm25([0, 30, 31, 60, 61, 90, 121, 250, 800])
    assert values.tolist() == [0.0, 50.0, 51.0, 100.0, 101.0, 200.0, 301.0, 400.0, 500.0]
    assert coupled.aqi_band(100) == "Satisfactory"
    assert coupled.aqi_band(101) == "Moderate"
    assert coupled.aqi_band(401) == "Severe"


def test_coupling_keeps_concentration_aqi_separate_from_parameterised_load():
    frame = coupled._synthetic(zones=1, days=1, now=pd.Timestamp("2026-05-20"))
    assert (frame["heat_aqi_load"] >= frame["aqi_india"]).all()
    assert (frame["heat_multiplier"] >= 1).all()
    assert frame["heat_multiplier"].max() <= coupled.HEAT_AQI_PARAMETERS["max_multiplier"]


def test_heatwave_uses_real_normal_not_forecast_window_mean():
    # Seven hot days centered around the real scenario described in the design
    # notes.  A known 39.5 C normal turns five qualifying days into a declared
    # episode; a window mean would largely subtract the event away.
    start = date(2026, 5, 20)
    # Mean = 43.9 C (the misleading forecast-window pseudo-normal); five
    # consecutive days are >= 44.0 C, i.e. +4.5 C over the real normal.
    tmax = [42.0, 44.0, 44.2, 46.2, 45.0, 44.0, 41.9]
    daily = pd.DataFrame({
        "zone_id": ["central-delhi"] * len(tmax),
        "zone_name": ["Central Delhi"] * len(tmax),
        "lat": [28.61] * len(tmax),
        "lon": [77.21] * len(tmax),
        "date": [start + timedelta(days=i) for i in range(len(tmax))],
        "tmax_c": tmax,
        "tmin_c": [30.0] * len(tmax),
        "rh_mean_pct": [35.0] * len(tmax),
        "wind_mean_kmh": [8.0] * len(tmax),
        "pm25_mean_ugm3": [100.0] * len(tmax),
        "pm25_peak_ugm3": [130.0] * len(tmax),
        "aqi_peak": [320.0] * len(tmax),
        "heat_aqi_load_peak": [340.0] * len(tmax),
        "data_source": ["test"] * len(tmax),
        "is_synthetic": [False] * len(tmax),
        "fetched_at": ["2026-05-18T00:00:00Z"] * len(tmax),
    })
    climatology = {
        "zones": {
            "central-delhi": {
                "daily_tmax_c": {
                    (start + timedelta(days=i)).strftime("%m-%d"): 39.5
                    for i in range(len(tmax))
                }
            }
        }
    }

    flagged = coupled.detect_heatwaves(daily, climatology)
    assert flagged["normal_granularity"].eq("daily").all()
    assert int(flagged["heatwave_candidate"].sum()) == 5
    assert int(flagged["is_heatwave_episode"].sum()) == 5


def test_contingency_scores_report_csi_and_hss_not_bare_accuracy():
    scores = coupled.contingency_scores(
        [False, False, True, True],
        [False, True, True, False],
    )
    assert scores == {
        "hits": 1, "misses": 1, "false_alarms": 1, "correct_negatives": 1,
        "csi": 0.333, "hss": 0.0,
    }
    assert "accuracy" not in scores
