"""Static-host contract tests: every phone/demo API route gets a strict JSON file.

A GitHub Pages deployment has no FastAPI. If a route is missing here, the
browser sees a 404 — so the catalogue is asserted against the live FastAPI
route table, and demo scenarios are asserted individually.
"""
from __future__ import annotations

import json

import core.coupled as coupled
import core.demo as demo_engine
from scripts import export_static


def _offline(*_args, **_kwargs):
    raise OSError("simulated static export outage")


def test_catalogue_covers_every_ncr_and_advance_route():
    assert export_static.check_catalogue() == []
    assert export_static.dynamic_phone_routes() == export_static.exported_route_paths()
    # 9 /ncr/* + /heatwave/advance + /warnings/advance + /notifications/preview
    # + 6 /demo/* route paths (scenario snapshots share the path, differ by query)
    assert len(export_static.exported_route_paths()) == 18


def test_catalogue_covers_every_demo_scenario():
    """Each scenario preset must ship forecast/thermal/warnings/notifications files."""
    filenames = {filename for _path, filename, _fn in export_static.EXPORTS}
    for scenario in demo_engine.scenario_ids():
        for kind in ("forecast", "thermal", "warnings", "notifications"):
            assert f"demo-{kind}-{scenario}.json" in filenames, (kind, scenario)
    assert "demo-scenarios.json" in filenames
    assert "demo-zones.json" in filenames
    assert "warnings-advance.json" in filenames
    assert "notifications-preview.json" in filenames


def test_export_is_strict_json_compact_and_uses_labelled_fallback(tmp_path, monkeypatch):
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)

    manifest = export_static.export(tmp_path)
    # Mapping keys preserve query strings; discovered FastAPI paths do not.
    assert {route.split("?", 1)[0] for route in manifest["routes"]} == export_static.exported_route_paths()
    assert len(manifest["routes"]) == len(export_static.EXPORTS)

    for route, spec in manifest["routes"].items():
        body = json.loads((tmp_path / spec["file"]).read_text())
        assert body["static_snapshot"] is True, route
        assert "NaN" not in (tmp_path / spec["file"]).read_text()
    citizen = json.loads((tmp_path / "citizen.json").read_text())
    assert citizen["static_snapshot"] is True
    assert citizen["summary"]["is_synthetic"] is True
    assert "simulated static export outage" in citizen["summary"]["fallback_reason"]
    assert manifest["citizen"]["bytes"] <= 45 * 1024


def test_demo_snapshots_carry_the_disclaimer_even_offline(tmp_path, monkeypatch):
    """Demo files must be self-labelled: a snapshot detached from this repo
    still has to say it is synthetic."""
    coupled.clear_ncr_cache()
    monkeypatch.setattr(coupled, "get_forecast", _offline)
    monkeypatch.setattr(coupled, "get_air_quality", _offline)
    export_static.export(tmp_path)

    for scenario in demo_engine.scenario_ids():
        for kind in ("forecast", "thermal", "warnings", "notifications"):
            body = json.loads((tmp_path / f"demo-{kind}-{scenario}.json").read_text())
            assert body["is_demo"] is True, (kind, scenario)
            assert body["demo_disclaimer"] == demo_engine.DEMO_DISCLAIMER, (kind, scenario)
            assert "synthetic" in body["data_source"].lower(), (kind, scenario)

    warnings_body = json.loads((tmp_path / "demo-warnings-dry-extreme.json").read_text())
    leads = {row["lead_days"] for row in warnings_body["data"]}
    assert {3, 4, 5}.issubset(leads)

    advance = json.loads((tmp_path / "warnings-advance.json").read_text())
    # The live advance route degraded to the labelled synthetic exercise frame
    # instead of failing — a static host must never ship a 500-shaped hole.
    assert advance["is_synthetic"] is True
    assert "simulated static export outage" in advance["fallback_reason"]
