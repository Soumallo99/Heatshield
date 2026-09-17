"""Contract tests for the Kolkata citizen brief (/citizen/kolkata).

The Kolkata brief shares the phone payload contract with the Delhi-NCR
citizen.json but must stay honest about what the city actually has:
WBGT thermal stress instead of an invented AQI, absolute-rule heatwave
labels (no departure claims without fixed normals), and an offline-safe
empty payload when the cache is cold.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import app.main as main
from app.main import app

client = TestClient(app)


def _payload() -> dict:
    response = client.get("/citizen/kolkata")
    assert response.status_code == 200
    # Strict JSON — a NaN would break an installed phone app.
    return json.loads(json.dumps(response.json(), allow_nan=False))


def test_kolkata_brief_covers_every_ward_with_coordinates():
    doc = _payload()
    zones = doc["summary"]["data"]
    assert len(zones) == 141
    assert doc["summary"]["city"]["zones"] == 141
    for zone in zones:
        assert zone["lat"] is not None and zone["lon"] is not None
        assert zone["temp_c"] is not None
        assert zone["wbgt_c"] is not None
        assert zone["stress_band"] in {"Normal", "Caution", "Danger", "Critical", "Extreme"}
        assert zone["zone_id"].startswith("ward-")


def test_kolkata_brief_never_invents_air_quality():
    doc = _payload()
    for zone in doc["summary"]["data"]:
        assert zone["pm25_ugm3"] is None
        assert zone["aqi_india"] is None
        assert zone["aqi_band"] == "Unavailable"
        assert zone["heat_aqi_load"] is None
        assert zone["heat_aqi_load_band"] == "Unavailable"
    assert doc["summary"]["city"]["highest_aqi"] is None
    for day in doc["daily"]:
        assert day["aqi_peak"] is None and day["aqi_band"] == "Unavailable"
        assert day["heat_aqi_load_peak"] is None
    assert "No air-quality source is bundled" in doc["source_notice"]


def test_kolkata_heatwave_labels_use_absolute_rule_without_fake_normals():
    doc = _payload()
    climatology = doc["alerts"]["climatology"]
    assert climatology["available"] is False
    assert "departure" in climatology["method"].lower()
    assert "never masquerade" in climatology["method"] or "DISABLED" in climatology["method"]

    for day in doc["daily"]:
        # No fixed per-ward normals ship for Kolkata — never claim departures.
        assert day["normal_tmax_c"] is None
        assert day["departure_c"] is None
        label = day["heatwave_label"]
        tmax = day["tmax_c"]
        if label in {"Heat Wave", "Severe Heat Wave"}:
            assert tmax >= 37.0
        if label == "Severe Heat Wave":
            assert tmax >= 40.0
        if label == "None":
            assert tmax < 37.0

    for alert in doc["alerts"]["data"]:
        assert alert["tmax_c"] >= 37.0
        assert alert["normal_tmax_c"] is None


def test_kolkata_daily_covers_wards_times_window():
    doc = _payload()
    days = {day["date"] for day in doc["daily"]}
    assert len(doc["daily"]) == 141 * len(days)
    assert len(days) >= 5
    for day in doc["daily"]:
        assert day["wbgt_peak_c"] is not None
        assert day["risk_band"]


def test_kolkata_brief_degrades_to_labelled_empty_payload_when_cache_is_cold(monkeypatch):
    def _no_cache(*_args, **_kwargs):
        raise RuntimeError("simulated cold cache with no network")

    monkeypatch.setattr(main, "get_forecast", _no_cache)
    response = client.get("/citizen/kolkata")
    assert response.status_code == 200  # never a 500 on a static/offline host
    doc = response.json()
    assert doc["summary"]["data"] == []
    assert doc["daily"] == []
    assert doc["alerts"]["data"] == []
    assert doc["summary"]["city"]["zones"] == 0
    assert "simulated cold cache" in doc["summary"]["data_source"]
    assert "scripts.refresh" in doc["source_notice"]
