"""
Phase 2 physics tests.  Run:  python -m pytest tests -q
(Or without pytest:  python tests/test_thermal.py)
"""
from __future__ import annotations

import numpy as np

from core.thermal import (
    classify_wbgt,
    globe_temperature,
    heat_index,
    wbgt_outdoor,
    wbgt_shade,
    wet_bulb_psychrometric,
    wet_bulb_stull,
    work_rest,
)

TOL_HI = 0.6      # °C vs published NWS chart
TOL_TW = 0.6      # °C vs psychrometric inversion, humid regime


# --------------------------------------------------------------- Heat Index
def test_heat_index_matches_nws_chart():
    """NWS published cells: 80F/80%=84F, 90F/60%=100F, 90F/70%=105F, 100F/40%=109F."""
    cases = [(26.7, 80, 28.9), (32.2, 60, 37.8), (32.2, 70, 40.6), (37.8, 40, 42.8)]
    for t, rh, expect in cases:
        got = float(heat_index(t, rh))
        assert abs(got - expect) < TOL_HI, f"HI({t}C,{rh}%) = {got:.2f}, expected ~{expect}"


def test_heat_index_monotonic_in_temp_and_humidity():
    assert heat_index(30, 50) < heat_index(35, 50)
    assert heat_index(35, 40) < heat_index(35, 80)


def test_heat_index_degenerate_cold():
    assert abs(float(heat_index(5, 50)) - 5.0) < 0.5     # HI converges to T when cold


# --------------------------------------------------------------- Wet bulb
def test_stull_matches_psychrometric_in_humid_regime():
    t = np.array([25.0, 30.0, 35.0, 40.0])
    rh = np.array([50.0, 70.0, 90.0, 60.0])
    dev = np.abs(wet_bulb_stull(t, rh) - wet_bulb_psychrometric(t, rh))
    assert dev.max() < TOL_TW, f"max deviation {dev.max():.3f} C too large"


def test_wet_bulb_bounded_by_dewpoint_and_airtemp():
    t, rh = np.array([20.0, 30.0, 40.0]), np.array([30.0, 60.0, 95.0])
    tw = wet_bulb_stull(t, rh)
    assert np.all(tw <= t + 1e-6), "wet bulb cannot exceed air temperature"
    assert np.all(tw >= t - 40), "wet bulb implausibly low"


# --------------------------------------------------------------- Globe
def test_globe_equals_airtemp_at_night():
    tg = globe_temperature(30.0, 1.0, 0.0)
    assert abs(float(tg) - 30.0) < 1e-6


def test_globe_rises_with_solar_and_falls_with_wind():
    low_sun, high_sun = globe_temperature(33, 1.0, 200), globe_temperature(33, 1.0, 900)
    still, breezy = globe_temperature(33, 0.3, 900), globe_temperature(33, 5.0, 900)
    assert high_sun > low_sun
    assert still > breezy
    assert 5 < float(high_sun) - 33 < 25, "globe-to-air delta should be ~5-25 C in full sun"


# --------------------------------------------------------------- WBGT
def test_wbgt_between_wetbulb_and_globe():
    tw = wet_bulb_stull(33, 70)
    tg = globe_temperature(33, 1.0, 800)
    w = float(wbgt_outdoor(33, 70, 1.0, 800))
    assert tw <= w <= tg + 0.5


def test_wbgt_shade_below_wbgt_sun():
    shade = float(wbgt_shade(35, 50))
    sun = float(wbgt_outdoor(35, 50, 1.0, 900))
    assert sun > shade


def test_wbgt_night_collapses_to_shade_formula():
    night = float(wbgt_outdoor(28, 80, 0.5, 0.0))
    assert abs(night - float(wbgt_shade(28, 80))) < 1e-6


# --------------------------------------------------------------- Classification
def test_bands_and_work_rest():
    assert classify_wbgt(20)["band"] == "Normal"
    assert classify_wbgt(27)["band"] == "Caution"
    assert classify_wbgt(30)["band"] == "Danger"
    assert classify_wbgt(31.5)["band"] == "Critical"
    assert classify_wbgt(33)["band"] == "Extreme"
    assert work_rest(20) == "60 min work : 0 min rest per hour (moderate)"
    assert work_rest(35).startswith("No work")
    assert work_rest(29, "heavy") != work_rest(29, "light")


if __name__ == "__main__":
    import sys

    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
