"""
data.gov.in adapter tests.

The property that matters is not that the HTTP call works — it is that the
adapter is *inert* without a key. HeatShield's whole "clone it and run it"
guarantee rests on no credential ever becoming mandatory, so these tests
assert the no-key path as loudly as the wired one.
"""
from __future__ import annotations

import json

import pytest

from core import datagov


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    """Every test starts unconfigured unless it opts in."""
    monkeypatch.delenv("HS_DATAGOV_API_KEY", raising=False)
    monkeypatch.delenv("DATAGOV_API_KEY", raising=False)


FAKE_BODY = json.dumps({
    "records": [
        {"state": "WEST BENGAL", "district": "KOLKATA", "temp_max": 38.4},
        {"state": "WEST BENGAL", "district": "KOLKATA", "temp_max": 37.1},
    ],
    "total": 2,
    "count": 2,
})


# --------------------------------------------------------------- keyless path
def test_without_a_key_the_adapter_refuses_loudly():
    assert datagov.configured() is False
    with pytest.raises(datagov.NotConfiguredError, match="HS_DATAGOV_API_KEY"):
        datagov.fetch_resource("abc-123")
    with pytest.raises(datagov.NotConfiguredError):
        datagov.fetch_dataset("imd-daily-station-observations")


def test_the_refusal_says_the_pipeline_is_unaffected():
    """The error has to reassure, not just fail — an operator reading a stack
    trace should not go looking for a broken pipeline."""
    with pytest.raises(datagov.NotConfiguredError) as excinfo:
        datagov.fetch_resource("abc-123")
    assert "unaffected" in str(excinfo.value).lower()


def test_status_reports_unconfigured_without_raising():
    state = datagov.status()
    assert state["configured"] is False
    assert state["datasets_wired"] == 0
    assert state["datasets_catalogued"] == len(datagov.CATALOGUE)
    assert "optional" in state["note"].lower()


# --------------------------------------------------------------- wired path
def test_fetch_resource_parses_records_and_metadata(monkeypatch):
    monkeypatch.setenv("HS_DATAGOV_API_KEY", "test-key")
    seen = {}

    def getter(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return FAKE_BODY

    result = datagov.fetch_resource("abc-123", limit=10, getter=getter)
    assert len(result["records"]) == 2
    assert result["total"] == 2
    assert result["records"][0]["district"] == "KOLKATA"
    # the key is in the URL, so the URL must never be logged verbatim elsewhere
    assert "api-key=test-key" in seen["url"]
    assert "format=json" in seen["url"] and "limit=10" in seen["url"]


def test_filters_and_pagination_are_encoded_the_way_the_api_expects(monkeypatch):
    monkeypatch.setenv("HS_DATAGOV_API_KEY", "test-key")
    captured = {}

    def getter(url, timeout):
        captured["url"] = url
        return FAKE_BODY

    datagov.fetch_resource("abc-123", offset=50, limit=5000,
                           filters={"district": "Kolkata"}, getter=getter)
    assert "offset=50" in captured["url"]
    assert "limit=5000" in captured["url"]
    assert "filters%5Bdistrict%5D=Kolkata" in captured["url"]


def test_a_response_without_records_is_an_error_not_an_empty_success(monkeypatch):
    """An empty result is a fact about the source, not a licence to invent one."""
    monkeypatch.setenv("HS_DATAGOV_API_KEY", "test-key")
    with pytest.raises(datagov.UpstreamError, match="no 'records' key"):
        datagov.fetch_resource("abc", getter=lambda url, timeout: '{"error": "bad key"}')


def test_a_transport_failure_becomes_an_upstream_error(monkeypatch):
    monkeypatch.setenv("HS_DATAGOV_API_KEY", "test-key")

    def boom(url, timeout):
        raise OSError("connection reset")

    with pytest.raises(datagov.UpstreamError, match="connection reset"):
        datagov.fetch_resource("abc", getter=boom)


def test_a_non_json_body_becomes_an_upstream_error(monkeypatch):
    monkeypatch.setenv("HS_DATAGOV_API_KEY", "test-key")
    with pytest.raises(datagov.UpstreamError, match="non-JSON"):
        datagov.fetch_resource("abc", getter=lambda url, timeout: "<html>502</html>")


def test_fetching_an_unwired_dataset_says_so(monkeypatch):
    """A dataset with no resource id must fail with the reason, not 404."""
    monkeypatch.setenv("HS_DATAGOV_API_KEY", "test-key")
    with pytest.raises(ValueError, match="no resource id"):
        datagov.fetch_dataset("imd-daily-station-observations")


def test_build_url_requires_a_resource_id():
    with pytest.raises(ValueError, match="resource_id is required"):
        datagov.build_url("")


# --------------------------------------------------------------- catalogue
def test_every_catalogue_entry_is_complete():
    slugs = set()
    for entry in datagov.CATALOGUE:
        for field in datagov.REQUIRED_FIELDS:
            assert field in entry, (entry.get("slug"), field)
        assert entry["slug"] not in slugs, f"duplicate slug {entry['slug']}"
        slugs.add(entry["slug"])
        assert entry["closes_gap"] and entry["publisher"] and entry["status"]


def test_no_catalogue_entry_ships_a_fabricated_resource_id():
    """A guessed resource id would turn 'not configured' into a 404 that looks
    like a data outage. Empty is honest."""
    for entry in datagov.CATALOGUE:
        assert entry["resource_id"] is None, entry["slug"]


def test_the_catalogue_names_the_gaps_data_md_documents():
    """The whole reason this adapter exists."""
    gaps = " ".join(entry["closes_gap"] for entry in datagov.CATALOGUE).lower()
    assert "60+" in gaps, "the strongest heat-mortality modifier must be here"
    assert "bias correction" in gaps or "verification" in gaps


def test_dataset_lookup_and_resolve():
    assert datagov.dataset("imd-daily-station-observations")["publisher"].startswith("India Met")
    assert datagov.dataset("no-such-dataset") is None
    assert datagov.resolve("no-such-dataset") is None
    assert datagov.resolve("imd-daily-station-observations") is None   # not wired yet


def test_the_api_route_reports_state_without_a_key(client):
    body = client.get("/integrations/datagov").json()
    assert body["configured"] is False
    assert body["datasets_catalogued"] == len(datagov.CATALOGUE)
