"""Materialise the phone-app API contract for a static host such as GitHub Pages.

A Vite dev server can proxy ``/api`` to FastAPI; a static host cannot.  This
exporter calls the same endpoint functions and writes strict JSON snapshots to
``frontend/web/public/static-api``.  The client tries live ``/api`` first and
falls back to these labelled snapshots only when a static host or offline
connection has no API.

Run after a forecast refresh, or use the built-in offline fallback deliberately:

    HS_FORECAST_DAYS=5 python -m scripts.export_static
    HS_FORECAST_DAYS=5 python -m scripts.export_static --check

``--check`` also fails if a new GET route under ``/ncr/*``, ``/demo/*``,
``/warnings/*``, ``/heatwave/advance`` or ``/notifications/preview`` has not
been added here.  That guard exists because a previous static release shipped
nine live routes as GitHub Pages 404s.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from app import main as api
from core import config
from core import demo as demo_engine

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "frontend" / "web" / "public" / "static-api"


def _demo_exports() -> tuple[tuple[str, str, Callable[[], dict[str, Any]]], ...]:
    """One snapshot per demo route × scenario, so the Heat Risk Demo works on
    GitHub Pages with no API, no network and no credentials."""
    entries: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
        ("/demo/scenarios", "demo-scenarios.json", api.demo_scenarios),
        ("/demo/zones", "demo-zones.json", api.demo_zones),
    ]
    for scenario in demo_engine.scenario_ids():
        entries.extend((
            (f"/demo/forecast?scenario={scenario}", f"demo-forecast-{scenario}.json",
             lambda s=scenario: api.demo_forecast(scenario=s)),
            (f"/demo/thermal?scenario={scenario}", f"demo-thermal-{scenario}.json",
             lambda s=scenario: api.demo_thermal(scenario=s)),
            (f"/demo/warnings?scenario={scenario}", f"demo-warnings-{scenario}.json",
             lambda s=scenario: api.demo_warnings(scenario=s)),
            (f"/demo/notifications?scenario={scenario}", f"demo-notifications-{scenario}.json",
             lambda s=scenario: api.demo_notifications(scenario=s)),
        ))
    return tuple(entries)


# (live API path, file name, endpoint function).  Keep this list explicit:
# output filenames are part of the versioned static-client contract.
EXPORTS: tuple[tuple[str, str, Callable[[], dict[str, Any]]], ...] = (
    ("/ncr/zones", "ncr-zones.json", api.ncr_zone_list),
    ("/ncr/forecast?hours=120", "ncr-forecast.json", lambda: api.ncr_forecast(hours=120)),
    ("/ncr/air-quality?hours=120", "ncr-air-quality.json", lambda: api.ncr_air_quality(hours=120)),
    ("/ncr/heat-aqi?hours=120", "ncr-heat-aqi.json", lambda: api.ncr_heat_aqi(hours=120)),
    ("/ncr/daily", "ncr-daily.json", api.ncr_daily_route),
    ("/ncr/summary", "ncr-summary.json", api.ncr_summary),
    ("/ncr/metadata", "ncr-metadata.json", api.ncr_metadata),
    ("/ncr/validation", "ncr-validation.json", api.ncr_validation),
    ("/ncr/alerts", "ncr-alerts.json", lambda: api.ncr_alerts(days=config.FORECAST_DAYS)),
    ("/heatwave/advance", "heatwave-advance.json", lambda: api.heatwave_advance(days=config.FORECAST_DAYS)),
    # Operational advance-warning + notification-preview routes (offline-safe:
    # they render the labelled synthetic exercise frame when no provider answers).
    ("/warnings/advance", "warnings-advance.json",
     lambda: api.warnings_advance(days=config.FORECAST_DAYS + 1)),
    ("/notifications/preview", "notifications-preview.json",
     lambda: api.notifications_preview(days=config.FORECAST_DAYS + 1)),
    # Kolkata citizen brief (phone contract). Offline-safe: built from the
    # committed forecast cache; empty+labelled when the cache is cold.
    ("/citizen/kolkata", "citizen-kolkata.json", api.citizen_kolkata),
) + _demo_exports()


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _strict_json(value: Any) -> str:
    """Serialise strict JSON — NaN would make an installed app fail to parse."""
    # Whitespace has no value over a slow cellular connection.  The API schema
    # and a readable manifest live in source; shipped snapshots stay compact.
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False, default=_json_default) + "\n"


def exported_route_paths() -> set[str]:
    """The paths this exporter promises to serve, stripped of query strings."""
    return {path.split("?", 1)[0] for path, _filename, _fn in EXPORTS}


STATIC_ROUTE_PREFIXES = ("/ncr/", "/demo/", "/warnings/")
STATIC_ROUTE_EXACT = ("/heatwave/advance", "/notifications/preview", "/citizen/kolkata")


def dynamic_phone_routes() -> set[str]:
    """GET routes that must have a static counterpart, discovered from FastAPI.

    POST-only routes (dispatch endpoints) are excluded on purpose: a static
    host cannot execute them, and the demo must never need them.
    """
    discovered: set[str] = set()
    for route in api.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if "GET" not in methods:
            continue
        if path.startswith(STATIC_ROUTE_PREFIXES) or path in STATIC_ROUTE_EXACT:
            discovered.add(path)
    return discovered


def check_catalogue() -> list[str]:
    missing = sorted(dynamic_phone_routes() - exported_route_paths())
    filenames = [filename for _path, filename, _fn in EXPORTS]
    duplicate_files = sorted({name for name in filenames if filenames.count(name) > 1})
    problems = [f"static export missing route {path}" for path in missing]
    problems.extend(f"duplicate static export filename {name}" for name in duplicate_files)
    return problems


def _compact_citizen_payload(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Keep the initial phone payload small; detail tables stay lazy-loaded."""
    summary = results["ncr-summary.json"]
    alerts = results["ncr-alerts.json"]
    daily = results["ncr-daily.json"]
    advance = results["heatwave-advance.json"]
    compact_days = [
        {
            key: row.get(key)
            for key in (
                "zone_id", "zone_name", "date", "tmax_c", "pm25_mean_ugm3", "aqi_peak",
                "aqi_band", "heat_aqi_load_peak", "heat_aqi_load_band",
            )
        }
        for row in daily.get("data", [])
    ]
    compact_alerts = [
        {
            key: row.get(key)
            for key in (
                "zone_id", "zone_name", "date", "tmax_c", "normal_tmax_c", "departure_c",
                "heatwave_label", "is_heatwave_episode", "is_severe_episode",
                "extreme_temperature_watch", "aqi_peak", "heat_aqi_load_peak",
            )
        }
        for row in advance.get("data", [])
        if row.get("is_heatwave_episode") or row.get("extreme_temperature_watch")
    ]
    return {
        "schema_version": 1,
        "static_snapshot": True,
        "exported_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "summary": summary,
        "alerts": {
            "rows": alerts.get("rows", 0),
            "climatology": alerts.get("climatology", {}),
            "data": compact_alerts,
        },
        "daily": compact_days,
        "source_notice": (
            "This is a generated snapshot for a static host. Inspect is_synthetic and "
            "data_source in summary before treating it as live information."
        ),
    }


def export(output: Path = OUT_DIR) -> dict[str, Any]:
    problems = check_catalogue()
    if problems:
        raise RuntimeError("\n".join(problems))
    output.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    manifest_routes: dict[str, dict[str, Any]] = {}
    for route, filename, fn in EXPORTS:
        body = fn()
        # A snapshot is not an API response.  The marker is deliberately added
        # here rather than mutating FastAPI's live response contract.
        body = {"static_snapshot": True, **body}
        serialised = _strict_json(body)
        (output / filename).write_text(serialised)
        results[filename] = body
        manifest_routes[route] = {
            "file": filename,
            "bytes": len(serialised.encode("utf-8")),
            "is_synthetic": body.get("is_synthetic"),
        }

    citizen = _compact_citizen_payload(results)
    citizen_serialised = _strict_json(citizen)
    (output / "citizen.json").write_text(citizen_serialised)
    manifest = {
        "schema_version": 1,
        "exported_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "routes": manifest_routes,
        "citizen": {"file": "citizen.json", "bytes": len(citizen_serialised.encode("utf-8"))},
    }
    (output / "manifest.json").write_text(_strict_json(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export NCR/heatwave API snapshots for static hosting")
    parser.add_argument("--output", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true", help="validate the route catalogue before exporting")
    args = parser.parse_args(argv)
    problems = check_catalogue()
    if problems:
        print("static export catalogue failed:")
        print("\n".join(f"  - {problem}" for problem in problems))
        return 2
    if args.check:
        print(f"static export catalogue OK — {len(EXPORTS)} routes, all phone API paths covered")
        return 0
    manifest = export(args.output)
    print(f"exported {len(manifest['routes'])} routes + citizen payload -> {args.output}")
    print(f"cold-open citizen payload: {manifest['citizen']['bytes']:,} bytes (uncompressed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
