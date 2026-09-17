"""Build reproducible 1991–2020 daily Tmax normals for HeatShield's NCR zones.

The advance heatwave detector must compare a forecast with a *fixed historical
normal*.  Taking the mean of the same 3–5 day forecast window subtracts the
heatwave away and is not a climatology.

Source
------
Open-Meteo Historical Weather API / ERA5-family reanalysis, daily
``temperature_2m_max``.  This is gridded reanalysis rather than a certified
IMD station normal; it is spatially consistent across the eight NCR points and
is explicitly described that way in the output metadata.

Run on a machine with outbound access:

    python -m scripts.build_climatology --ncr

The script writes ``data/climatology_normals.json`` only after every location
has a complete annual cycle.  It never writes guessed values if the network is
unavailable.  Save a successful raw response with ``--save-raw`` and rebuild
without network with ``--input <response.json>``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from core.coupled import NCR_ZONES

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REFERENCE_START = "1991-01-01"
REFERENCE_END = "2020-12-31"
DEFAULT_OUTPUT = Path("data/climatology_normals.json")


def _coordinates() -> tuple[str, str]:
    return (
        ",".join(str(item["lat"]) for item in NCR_ZONES),
        ",".join(str(item["lon"]) for item in NCR_ZONES),
    )


def fetch_ncr_archive(timeout: int = 120) -> list[dict[str, Any]]:
    """Fetch all eight locations in one documented archive request."""
    latitudes, longitudes = _coordinates()
    response = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": latitudes,
            "longitude": longitudes,
            "start_date": REFERENCE_START,
            "end_date": REFERENCE_END,
            "daily": "temperature_2m_max",
            "timezone": "Asia/Kolkata",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload if isinstance(payload, list) else [payload]
    if len(rows) != len(NCR_ZONES):
        raise RuntimeError(f"expected {len(NCR_ZONES)} archive locations, received {len(rows)}")
    return rows


def _normalise_payload(payload: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a raw response enough to make aggregation reproducible."""
    if not isinstance(payload, list) or len(payload) != len(NCR_ZONES):
        raise ValueError(f"expected a list of {len(NCR_ZONES)} location responses")
    for item in payload:
        daily = item.get("daily") if isinstance(item, dict) else None
        if not isinstance(daily, dict):
            raise ValueError("archive response is missing a daily object")
        times = daily.get("time", [])
        tmax = daily.get("temperature_2m_max", [])
        if len(times) != len(tmax) or len(times) < 365 * 29:
            raise ValueError("archive response has incomplete daily Tmax data")
    return {"locations": payload}


def build(payload: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute daily and monthly 1991–2020 means, preserving source metadata."""
    _normalise_payload(payload)
    zones: dict[str, dict[str, Any]] = {}
    for zone, response in zip(NCR_ZONES, payload):
        daily = response["daily"]
        frame = pd.DataFrame({
            "date": pd.to_datetime(daily["time"], errors="coerce"),
            "tmax_c": pd.to_numeric(daily["temperature_2m_max"], errors="coerce"),
        }).dropna()
        frame = frame[(frame["date"] >= REFERENCE_START) & (frame["date"] <= REFERENCE_END)].copy()
        frame["month_day"] = frame["date"].dt.strftime("%m-%d")
        frame["month"] = frame["date"].dt.month
        daily_normal = frame.groupby("month_day")["tmax_c"].mean().round(2)
        monthly_normal = frame.groupby("month")["tmax_c"].mean().round(2)
        # Feb 29 is rare in a forecast but keeping it prevents a silent hole.
        if len(daily_normal) < 365 or len(monthly_normal) != 12:
            raise ValueError(f"incomplete climatology for {zone['zone_id']}")
        zones[zone["zone_id"]] = {
            "zone_name": zone["zone_name"],
            "requested_lat": zone["lat"],
            "requested_lon": zone["lon"],
            "resolved_lat": response.get("latitude"),
            "resolved_lon": response.get("longitude"),
            "elevation_m": response.get("elevation"),
            "daily_tmax_c": {key: float(value) for key, value in daily_normal.items()},
            "monthly_tmax_c": {str(int(key)): float(value) for key, value in monthly_normal.items()},
            "days_used": int(len(frame)),
        }
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "reference_period": f"{REFERENCE_START} to {REFERENCE_END}",
        "timezone": "Asia/Kolkata",
        "variable": "daily temperature_2m_max (°C)",
        "source": {
            "provider": "Open-Meteo Historical Weather API",
            "url": ARCHIVE_URL,
            "model": "provider default archive reanalysis",
            "caveat": (
                "Gridded reanalysis normals, not certified IMD station normals. "
                "Use station observations before operational declaration."
            ),
        },
        "method": (
            "Mean daily maximum temperature for each calendar day across 1991–2020; "
            "monthly values are means of all source days in each calendar month."
        ),
        "zones": zones,
    }


def validate(result: dict[str, Any]) -> None:
    """Refuse partial files: a missing normal would silently weaken detection."""
    if result.get("reference_period") != f"{REFERENCE_START} to {REFERENCE_END}":
        raise ValueError("wrong reference period")
    zones = result.get("zones")
    if not isinstance(zones, dict) or set(zones) != {zone["zone_id"] for zone in NCR_ZONES}:
        raise ValueError("climatology does not contain exactly the NCR zone set")
    for zone_id, zone in zones.items():
        daily = zone.get("daily_tmax_c", {})
        monthly = zone.get("monthly_tmax_c", {})
        if len(daily) < 365 or set(monthly) != {str(month) for month in range(1, 13)}:
            raise ValueError(f"{zone_id} has an incomplete annual normal")
        if not all(-10 < float(value) < 60 for value in daily.values()):
            raise ValueError(f"{zone_id} contains an implausible daily Tmax normal")


def write_result(result: dict[str, Any], output: Path) -> Path:
    validate(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build 1991–2020 NCR Tmax climatology")
    parser.add_argument("--ncr", action="store_true", help="build the canonical eight NCR locations")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--input", type=Path, help="previously saved raw Open-Meteo JSON response")
    parser.add_argument("--save-raw", type=Path, help="save the live raw response for reproducibility/offline rebuild")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    if not args.ncr:
        parser.error("--ncr is required; no implicit geography is allowed")

    try:
        if args.input:
            payload = json.loads(args.input.read_text())
        else:
            payload = fetch_ncr_archive(timeout=args.timeout)
            if args.save_raw:
                args.save_raw.parent.mkdir(parents=True, exist_ok=True)
                args.save_raw.write_text(json.dumps(payload, indent=2) + "\n")
        result = build(payload)
        path = write_result(result, args.output)
    except Exception as exc:  # Avoid a half-written or invented climatology.
        print(f"climatology build failed; no output written: {type(exc).__name__}: {exc}")
        return 2

    print(f"wrote {path} — {len(result['zones'])} NCR zones, 1991–2020 daily Tmax normals")
    for zone_id, zone in result["zones"].items():
        may = zone["monthly_tmax_c"]["5"]
        print(f"  {zone_id:16s} May Tmax normal {may:.2f} °C ({zone['days_used']} daily values)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
