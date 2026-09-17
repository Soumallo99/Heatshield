"""Static-host contract tests: every phone API route gets a strict JSON file."""
from __future__ import annotations

import json

import core.coupled as coupled
from scripts import export_static


def _offline(*_args, **_kwargs):
    raise OSError("simulated static export outage")


def test_catalogue_covers_every_ncr_and_advance_route():
    assert export_static.check_catalogue() == []
    assert export_static.dynamic_phone_routes() == export_static.exported_route_paths()
    assert len(export_static.exported_route_paths()) == 10


def test_export_is_strict_json_compact_and_uses_labelled_fallback(tmp_path, monkeypatch):
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)

    manifest = export_static.export(tmp_path)
    # Mapping keys preserve query strings; discovered FastAPI paths do not.
    assert {route.split("?", 1)[0] for route in manifest["routes"]} == export_static.exported_route_paths()
    assert len(manifest["routes"]) == 10

    for route, spec in manifest["routes"].items():
        body = json.loads((tmp_path / spec["file"]).read_text())
        assert body["static_snapshot"] is True, route
        assert "NaN" not in (tmp_path / spec["file"]).read_text()
    citizen = json.loads((tmp_path / "citizen.json").read_text())
    assert citizen["static_snapshot"] is True
    assert citizen["summary"]["is_synthetic"] is True
    assert "simulated static export outage" in citizen["summary"]["fallback_reason"]
    assert manifest["citizen"]["bytes"] <= 45 * 1024
