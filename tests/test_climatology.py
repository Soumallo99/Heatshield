"""Tests for fixed historical normals used by the advance heatwave detector."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.coupled import NCR_ZONES, climatology_normal
from scripts import build_climatology as builder


def _archive_payload() -> list[dict]:
    """Small deterministic stand-in with the same 30-year archive shape."""
    dates = pd.date_range("1991-01-01", "2020-12-31", freq="D")
    # Seasonal wave gives every month distinct values and includes leap days.
    values = (33 + 8 * np.sin((dates.dayofyear.to_numpy() - 105) * 2 * np.pi / 365)).round(1)
    return [
        {
            "latitude": zone["lat"], "longitude": zone["lon"], "elevation": 200,
            "daily": {"time": dates.strftime("%Y-%m-%d").tolist(), "temperature_2m_max": (values + i * .1).tolist()},
        }
        for i, zone in enumerate(NCR_ZONES)
    ]


def test_builds_complete_daily_and_monthly_1991_2020_normals(tmp_path):
    result = builder.build(_archive_payload())
    builder.validate(result)
    output = builder.write_result(result, tmp_path / "normals.json")

    loaded = json.loads(output.read_text())
    assert loaded["reference_period"] == "1991-01-01 to 2020-12-31"
    assert set(loaded["zones"]) == {zone["zone_id"] for zone in NCR_ZONES}
    central = loaded["zones"]["central-delhi"]
    assert len(central["daily_tmax_c"]) == 366
    assert set(central["monthly_tmax_c"]) == {str(month) for month in range(1, 13)}
    assert central["days_used"] == 10958


def test_daily_normal_is_preferred_then_monthly_then_unavailable():
    climatology = {
        "zones": {
            "x": {
                "daily_tmax_c": {"05-20": 39.5},
                "monthly_tmax_c": {"5": 39.2},
            }
        }
    }
    assert climatology_normal(climatology, "x", "2026-05-20") == (39.5, "daily")
    assert climatology_normal(climatology, "x", "2026-05-21") == (39.2, "monthly")
    assert climatology_normal(climatology, "missing", "2026-05-20") == (None, "unavailable")


def test_validation_rejects_partial_file():
    partial = {
        "reference_period": "1991-01-01 to 2020-12-31",
        "zones": {"central-delhi": {"daily_tmax_c": {}, "monthly_tmax_c": {}}},
    }
    try:
        builder.validate(partial)
    except ValueError as exc:
        assert "zone" in str(exc).lower()
    else:
        raise AssertionError("partial climatology must never be accepted")
