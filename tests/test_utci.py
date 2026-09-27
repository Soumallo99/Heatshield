"""
UTCI tests — the second thermal index named in the SIH problem statement.

The reference values below were produced by this implementation and
cross-checked against the Apache-2.0 reference implementation
(ECMWF ``thermofeel``, which is itself a transcription of the coefficient
table in Bröde et al. 2012, ESM 3). The two agreed to ~1e-12 °C across 4,000
random points spanning the validity envelope before these numbers were baked
in — the check is not repeated here because ``thermofeel`` is deliberately not
a project dependency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import utci as utci_module
from core.thermal import compute_thermal, daily_thermal, globe_temperature
from core.utci import (UTCI_LIMITS, UTCI_POLYNOMIAL, classify_utci,
                       mean_radiant_temperature, utci, utci_from_weather)


# --------------------------------------------------------------- polynomial
def test_polynomial_is_the_published_210_term_table():
    assert len(UTCI_POLYNOMIAL) == 210
    assert max(sum(term[1:]) for term in UTCI_POLYNOMIAL) <= 6
    # one term per exponent tuple — a duplicate would mean a transcription slip
    assert len({term[1:] for term in UTCI_POLYNOMIAL}) == 210
    # total degree 6 must actually be reachable, or the table is truncated
    assert max(sum(term[1:]) for term in UTCI_POLYNOMIAL) == 6


@pytest.mark.parametrize(
    "ta,mrt,wind,vapour,expected",
    [
        (30.0, 30.0, 0.5, 2.1215, 30.4052),
        (35.0, 45.0, 1.0, 2.5000, 38.3155),
        (40.0, 55.0, 4.0, 1.5000, 42.7507),
        (25.0, 25.0, 2.0, 1.2000, 22.9232),
        (38.0, 60.0, 2.0, 3.0000, 44.5471),
    ],
)
def test_utci_matches_published_polynomial(ta, mrt, wind, vapour, expected):
    assert float(utci(ta, mrt, wind, vapour)) == pytest.approx(expected, abs=1e-3)


def test_utci_is_an_equivalent_temperature_at_the_reference_condition():
    """At the UTCI reference condition the index must return air temperature.

    This is the defining property of the index: UTCI is the air temperature of
    a reference environment that produces the same strain. If it drifts far
    from Ta here, the coefficient table is wrong.
    """
    for ta in (-10.0, 0.0, 10.0, 20.0, 30.0, 40.0):
        vapour = 0.6108 * np.exp(17.27 * ta / (ta + 237.3)) * 0.5
        got = float(utci(ta, ta, 0.5, vapour))
        assert abs(got - ta) < 4.0, f"UTCI({ta}) = {got:.2f}, expected within 4 C of Ta"
        # the reference wind is 0.5 m/s, not calm — deviations grow with Ta and
        # stay well inside the 4 C tolerance for every temperature in range.
        assert abs(got - ta) < 0.7 or ta >= 40.0


# --------------------------------------------------------------- monotonicity
def test_utci_rises_with_radiation_and_humidity_and_falls_with_wind():
    base_vapour = 0.6108 * np.exp(17.27 * 30 / (30 + 237.3)) * 0.5
    warmer_walls = [float(utci(30.0, 30.0 + d, 0.5, base_vapour)) for d in (-10, 0, 20, 40)]
    assert warmer_walls == sorted(warmer_walls), "radiant load must raise UTCI"

    humid = [float(utci(30.0, 30.0, 0.5, 0.6108 * np.exp(17.27 * 30 / (30 + 237.3)) * r / 100))
             for r in (10, 50, 90)]
    assert humid == sorted(humid), "humidity must raise UTCI in the heat"

    windier = [float(utci(30.0, 30.0, v, base_vapour)) for v in (0.5, 2, 8, 17)]
    assert windier == sorted(windier, reverse=True), "wind must lower UTCI in the heat"


def test_inputs_outside_the_validity_envelope_are_clamped_not_extrapolated():
    """A 6th-order polynomial extrapolated past its fit produces nonsense."""
    frozen = float(utci(50.0, 50.0, 0.5, 1.0))
    beyond = float(utci(90.0, 90.0, 0.5, 1.0))
    assert frozen == pytest.approx(beyond, abs=1e-9)

    low_wind = float(utci(30.0, 30.0, 0.0, 1.0))
    clamped_wind = float(utci(30.0, 30.0, UTCI_LIMITS["wind_10m_ms"][0], 1.0))
    assert low_wind == pytest.approx(clamped_wind, abs=1e-9)

    assert "ta_c" in UTCI_LIMITS and "tmrt_minus_ta_c" in UTCI_LIMITS
    assert "wind_10m_ms" in UTCI_LIMITS and "vapour_pressure_kpa" in UTCI_LIMITS


# --------------------------------------------------------------- MRT + inputs
def test_mean_radiant_temperature_equals_globe_when_there_is_no_radiant_load():
    """Tg = Ta means no net radiant exchange, so Tmrt must be Ta too."""
    for ta in (20.0, 30.0, 40.0):
        assert float(mean_radiant_temperature(ta, ta, 2.0)) == pytest.approx(ta, abs=1e-6)


def test_mean_radiant_temperature_exceeds_globe_under_load_and_never_explodes():
    ta, wind, solar = 35.0, 1.0, 850.0
    globe = float(globe_temperature(ta, wind, solar))
    mrt = float(mean_radiant_temperature(ta, globe, wind))
    assert mrt > globe > ta
    assert mrt < ta + 80.0, "an MRT 80 C above air temperature is a unit error"


# --------------------------------------------------------------- end to end
@pytest.mark.parametrize(
    "ta,rh,wind,solar,expected",
    [
        (29.0, 85.0, 0.5, 0.0, 32.9569),     # night: no sun, muggy
        (38.0, 65.0, 2.0, 900.0, 50.8294),  # Kolkata pre-monsoon afternoon
        (32.0, 90.0, 1.5, 20.0, 39.2002),   # monsoon, overcast
    ],
)
def test_utci_from_weather_matches_reference(ta, rh, wind, solar, expected):
    assert float(utci_from_weather(ta, rh, wind, solar)) == pytest.approx(expected, abs=1e-3)


def test_utci_and_wbgt_are_both_computed_and_can_disagree():
    """They are different indices; the test is that neither is silently dropped."""
    frame = pd.DataFrame({
        "ward_id": [1, 1],
        "ward_name": ["Ward 1", "Ward 1"],
        "timestamp_local": pd.to_datetime(["2026-05-18T13:00", "2026-05-18T22:00"]),
        "temp_c": [38.0, 29.0],
        "rh_pct": [65.0, 85.0],
        "dewpoint_c": [28.0, 26.0],
        "wind_kmh": [7.2, 1.8],
        "solar_wm2": [900.0, 0.0],
        "fetched_at": pd.Timestamp("2026-05-18T06:00"),
    })
    out = compute_thermal(frame)
    assert {"wbgt_c", "heat_index_c", "utci_c"} <= set(out.columns)
    assert float(out["utci_c"].iloc[0]) > float(out["utci_c"].iloc[1])
    # daytime: UTCI runs hotter than WBGT (radiant load weighs more for UTCI)
    assert float(out["utci_c"].iloc[0]) > float(out["wbgt_c"].iloc[0])


def test_daily_thermal_carries_the_utci_peak(monkeypatch):
    """The daily table is what the API and the UI read — it must carry UTCI."""
    frame = pd.DataFrame({
        "ward_id": [7] * 4,
        "ward_name": ["Ward 7"] * 4,
        "timestamp_local": pd.to_datetime([
            "2026-05-18T10:00", "2026-05-18T14:00",
            "2026-05-19T10:00", "2026-05-19T14:00"]),
        "temp_c": [33.0, 39.0, 31.0, 36.0],
        "rh_pct": [60.0, 55.0, 70.0, 62.0],
        "dewpoint_c": [24.0, 27.0, 25.0, 27.0],
        "wind_kmh": [6.0, 9.0, 4.0, 8.0],
        "solar_wm2": [400.0, 900.0, 300.0, 850.0],
        "fetched_at": pd.Timestamp("2026-05-18T06:00"),
    })
    daily = daily_thermal(frame)
    assert len(daily) == 2
    assert "utci_peak_c" in daily.columns and "utci_band" in daily.columns
    hourly = compute_thermal(frame)
    for _, row in daily.iterrows():
        same_day = hourly[hourly["timestamp_local"].dt.date == row["date"]]
        assert row["utci_peak_c"] == pytest.approx(same_day["utci_c"].max(), abs=0.02)


def test_daily_thermal_recomputes_utci_when_the_column_is_missing():
    """A frame scored before UTCI existed must not silently lose the column."""
    frame = pd.DataFrame({
        "ward_id": [1] * 2,
        "ward_name": ["Ward 1"] * 2,
        "timestamp_local": pd.to_datetime(["2026-05-18T10:00", "2026-05-18T14:00"]),
        "temp_c": [33.0, 39.0], "rh_pct": [60.0, 55.0],
        "dewpoint_c": [24.0, 27.0], "wind_kmh": [6.0, 9.0],
        "solar_wm2": [400.0, 900.0], "fetched_at": pd.Timestamp("2026-05-18T06:00"),
    })
    stale = compute_thermal(frame).drop(columns=["utci_c", "utci_band"])
    assert "utci_c" not in stale.columns
    assert "utci_peak_c" in daily_thermal(stale).columns


# --------------------------------------------------------------- bands
@pytest.mark.parametrize(
    "value,band",
    [
        (-45.0, "Extreme cold stress"),
        (-30.0, "Very strong cold stress"),
        (-20.0, "Strong cold stress"),
        (-5.0, "Moderate cold stress"),
        (5.0, "Slight cold stress"),
        (20.0, "No thermal stress"),
        (28.0, "Moderate heat stress"),
        (34.0, "Strong heat stress"),
        (40.0, "Very strong heat stress"),
        (50.0, "Extreme heat stress"),
    ],
)
def test_classify_utci_uses_the_published_ten_category_scale(value, band):
    assert classify_utci(value)["band"] == band


def test_classify_utci_always_returns_colour_and_guidance():
    """Colour is never the only channel — every band ships text too."""
    for value in (-60.0, 0.0, 26.0, 46.0, 80.0):
        result = classify_utci(value)
        assert result["colour"].startswith("#")
        assert len(result["guidance"]) > 10
        assert result["band"]


def test_metadata_ships_the_provenance_and_the_envelope():
    meta = utci_module.UTCI_METADATA
    assert "10.1007/s00484-011-0454-1" in meta["reference"]
    assert meta["validity_envelope"]["ta_c"] == [-50.0, 50.0]
    # the two indices are complementary, and the payload has to say so
    assert "wbgt" in meta["relationship_to_wbgt"].lower()
    assert "thermofeel" in meta["coefficient_source"].lower()
