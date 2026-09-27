"""
PHASE 8 — UTCI (Universal Thermal Climate Index)
================================================
The SIH problem statement names **two** thermal indices: WBGT and UTCI. Until now
only WBGT was implemented, so the second named metric was a slide, not a number.
This module closes that gap with the operational UTCI.

What UTCI is
------------
UTCI is an **equivalent temperature**: the air temperature of a reference
environment (50 % RH, calm-ish air, Tmrt = Ta) that would provoke the same
physiological strain as the *actual* combination of air temperature, mean
radiant temperature, wind and humidity. It comes out of the Fiala multi-node
thermoregulation model, which is far too slow to run per ward-hour, so the
UTCI project published a **6th-order polynomial approximation** of the model
response (210 coefficients). That polynomial is what this module implements.

    UTCI = Ta + Offset(Ta, Tmrt - Ta, va, e)

where ``Ta`` is air temperature (°C), ``Tmrt`` mean radiant temperature (°C),
``va`` wind speed at 10 m (m/s) and ``e`` water vapour pressure (kPa).

Why it belongs next to WBGT, not instead of it
----------------------------------------------
WBGT is an *occupational* index: it assumes a standard worker, standard
clothing and drives work/rest rules. UTCI is a *public-health* index: it is
derived from a general-population model with adaptive clothing and is the
metric European and Indian heat-health action plans increasingly use for
population warnings. HeatShield keeps both, for different audiences:

    WBGT  -> hazard score, work/rest, labour guidance  (unchanged, still the model driver)
    HI    -> public SMS copy                            (unchanged)
    UTCI  -> public-health heat-stress category, CAP severity, cross-city comparison

Source of the coefficients
--------------------------
Bröde, P.; Fiala, D.; Błażejczyk, K.; Holmér, I.; Jendritzky, G.; Kampmann, B.;
Tinz, B.; Havenith, G. (2012). *Deriving the operational procedure for the
Universal Thermal Climate Index (UTCI).* International Journal of
Biometeorology 56(3):481-494. doi:10.1007/s00484-011-0454-1 — Table of
polynomial coefficients, Electronic Supplementary Material 3.

The coefficient table here is the published one, transcribed from the
Apache-2.0 reference implementation (ECMWF ``thermofeel``, which is itself a
transcription of the ESM above) and **re-verified numerically** against that
implementation across the full validity envelope (see ``python -m core.utci``).
It is vendored rather than imported so that a clone still needs nothing but
``pip install -r requirements.txt`` — the same "no credentials, no extra
dependency" rule the rest of the pipeline follows.

Validity envelope (from the same paper — inputs are CLAMPED to it and the
clamps are reported by ``UTCI_LIMITS``, because extrapolating a 6th-order
polynomial outside its fit is how you get a 90 °C heat index):

    Ta        -50 ... +50 °C
    Tmrt - Ta -30 ... +70 °C
    va (10 m)   0.5 ... 17 m/s
    e           0 ... 5 kPa  (50 hPa)

Run standalone:  python -m core.utci
"""
from __future__ import annotations

import numpy as np

# --------------------------------------------------------------------------- #
# 0. Constants
# --------------------------------------------------------------------------- #

# ISO 7726 black-globe -> mean radiant temperature conversion.
GLOBE_DIAMETER_M = 0.15       # standard 150 mm globe (same as core.thermal)
GLOBE_EMISSIVITY = 0.95
# The ISO 7726 globe formula wants the wind speed *at the globe*, i.e. at
# 1.1 m, not the 10 m wind a forecast model gives us. Log-law scaling between
# the two heights with the 0.01 m roughness length the UTCI reference uses.
GLOBE_HEIGHT_M = 1.1
WIND_REFERENCE_HEIGHT_M = 10.0
ROUGHNESS_LENGTH_M = 0.01

#: Documented validity envelope. Inputs are clamped to these bounds before the
#: polynomial is evaluated; every clamp is listed here so it can be shown in a
#: payload rather than buried in the arithmetic.
UTCI_LIMITS: dict[str, tuple[float, float]] = {
    "ta_c": (-50.0, 50.0),
    "tmrt_minus_ta_c": (-30.0, 70.0),
    "wind_10m_ms": (0.5, 17.0),
    "vapour_pressure_kpa": (0.0, 5.0),
}

# --------------------------------------------------------------------------- #
# 1. The published polynomial
# --------------------------------------------------------------------------- #

# (coefficient, Ta power, va power, (Tmrt - Ta) power, e power)
# 210 terms, total degree <= 6. Units: coefficient multiplies °C / (m/s) / kPa
# raised to the listed powers and the result is an offset in °C.
#
# Copyright 1996- ECMWF.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# The coefficient values below originate from the table published by Bröde et
# al. (2012) and were extracted from the Apache-2.0 reference implementation
# ECMWF thermofeel (https://github.com/ecmwf-projects/thermofeel). In applying
# this licence, ECMWF does not waive the privileges and immunities granted to it
# by virtue of its status as an intergovernmental organisation nor does it
# submit to any jurisdiction. Full provenance: THIRD-PARTY.md.
UTCI_POLYNOMIAL: tuple[tuple[float, int, int, int, int], ...] = (
    (+6.0756205200e-01, 0, 0, 0, 0),
    (+5.1273349700e+00, 0, 0, 0, 1),
    (-2.8062640600e+00, 0, 0, 0, 2),
    (-3.5387412300e-02, 0, 0, 0, 3),
    (+6.1415534500e-01, 0, 0, 0, 4),
    (+8.8277310800e-02, 0, 0, 0, 5),
    (+1.4834806500e-03, 0, 0, 0, 6),
    (+3.9837402900e-01, 0, 0, 1, 0),
    (-3.6947634800e-02, 0, 0, 1, 1),
    (+5.1450742400e-02, 0, 0, 1, 2),
    (-2.2692161500e-03, 0, 0, 1, 3),
    (-1.4852642100e-03, 0, 0, 1, 4),
    (+2.4709053900e-04, 0, 0, 1, 5),
    (+7.5504309000e-04, 0, 0, 2, 0),
    (-7.3246918000e-04, 0, 0, 2, 1),
    (+3.0478889300e-04, 0, 0, 2, 2),
    (+3.0212203500e-04, 0, 0, 2, 3),
    (-9.7767590600e-06, 0, 0, 2, 4),
    (-1.2120667300e-05, 0, 0, 3, 0),
    (-3.5941317300e-07, 0, 0, 3, 1),
    (-4.3649772500e-06, 0, 0, 3, 2),
    (-4.0908789800e-07, 0, 0, 3, 3),
    (-1.3036902500e-09, 0, 0, 4, 0),
    (+3.9436767400e-08, 0, 0, 4, 1),
    (+3.2392689700e-09, 0, 0, 4, 2),
    (+6.6215487900e-10, 0, 0, 5, 0),
    (-1.1560644700e-10, 0, 0, 5, 1),
    (-4.7360246900e-12, 0, 0, 6, 0),
    (-2.2583652000e+00, 0, 1, 0, 0),
    (+5.4805061200e-01, 0, 1, 0, 1),
    (-3.0880636500e-01, 0, 1, 0, 2),
    (+4.5343345500e-02, 0, 1, 0, 3),
    (+3.5537538700e-03, 0, 1, 0, 4),
    (+1.0445298900e-03, 0, 1, 0, 5),
    (-2.0051826900e-02, 0, 1, 1, 0),
    (+8.6420339000e-03, 0, 1, 1, 1),
    (-2.6601630500e-04, 0, 1, 1, 2),
    (-7.9635544800e-04, 0, 1, 1, 3),
    (-6.8043441500e-06, 0, 1, 1, 4),
    (+1.5454725000e-04, 0, 1, 2, 0),
    (+2.7786293000e-05, 0, 1, 2, 1),
    (+7.6802338400e-06, 0, 1, 2, 2),
    (+1.7382571500e-06, 0, 1, 2, 3),
    (+1.2500673400e-06, 0, 1, 3, 0),
    (-4.7976873100e-07, 0, 1, 3, 1),
    (+2.6748927100e-08, 0, 1, 3, 2),
    (-5.0822038400e-09, 0, 1, 4, 0),
    (+3.3467804100e-10, 0, 1, 4, 1),
    (+1.9508720300e-12, 0, 1, 5, 0),
    (-7.5126950500e-01, 0, 2, 0, 0),
    (-4.2922362200e-02, 0, 2, 0, 1),
    (+2.1078775600e-03, 0, 2, 0, 2),
    (+2.1750861000e-04, 0, 2, 0, 3),
    (+1.0244975700e-04, 0, 2, 0, 4),
    (+1.6999241500e-04, 0, 2, 1, 0),
    (-3.5921747600e-05, 0, 2, 1, 1),
    (-1.0682330600e-04, 0, 2, 1, 2),
    (-6.3122365800e-06, 0, 2, 1, 3),
    (-1.5623630700e-05, 0, 2, 2, 0),
    (+2.5301672300e-06, 0, 2, 2, 1),
    (-3.5993791000e-08, 0, 2, 2, 2),
    (-3.3651463000e-08, 0, 2, 3, 0),
    (+1.6289705800e-09, 0, 2, 3, 1),
    (+1.1713913300e-10, 0, 2, 4, 0),
    (+1.5813725600e-01, 0, 3, 0, 0),
    (-1.2581350200e-03, 0, 3, 0, 1),
    (+4.1785659000e-04, 0, 3, 0, 2),
    (+3.3321714000e-05, 0, 3, 0, 3),
    (+8.4924293200e-05, 0, 3, 1, 0),
    (-1.2438230000e-05, 0, 3, 1, 1),
    (+2.2974896700e-07, 0, 3, 1, 2),
    (+6.5171172100e-07, 0, 3, 2, 0),
    (-3.9507939800e-08, 0, 3, 2, 1),
    (+4.1703262000e-10, 0, 3, 3, 0),
    (-1.2776275300e-02, 0, 4, 0, 0),
    (+1.2973580800e-04, 0, 4, 0, 1),
    (-3.0462047200e-06, 0, 4, 0, 2),
    (-4.9941030100e-06, 0, 4, 1, 0),
    (+2.2060929600e-07, 0, 4, 1, 1),
    (-1.0036111300e-08, 0, 4, 2, 0),
    (+4.5630667200e-04, 0, 5, 0, 0),
    (-2.2855868600e-06, 0, 5, 0, 1),
    (+8.1530011400e-08, 0, 5, 1, 0),
    (-5.9149126900e-06, 0, 6, 0, 0),
    (-2.2771234300e-02, 1, 0, 0, 0),
    (-3.1278856100e-01, 1, 0, 0, 1),
    (+5.4871248400e-01, 1, 0, 0, 2),
    (-2.2120119000e-01, 1, 0, 0, 3),
    (-6.1675593100e-02, 1, 0, 0, 4),
    (-3.0185930600e-03, 1, 0, 0, 5),
    (+1.8394531400e-04, 1, 0, 1, 0),
    (+1.6232532200e-03, 1, 0, 1, 1),
    (-4.3251099700e-03, 1, 0, 1, 2),
    (+3.8026198200e-04, 1, 0, 1, 3),
    (-4.1146918300e-05, 1, 0, 1, 4),
    (-5.6509521500e-05, 1, 0, 2, 0),
    (-1.8738196400e-05, 1, 0, 2, 1),
    (-6.4207083600e-05, 1, 0, 2, 2),
    (-4.7740354700e-06, 1, 0, 2, 3),
    (-2.1820366000e-07, 1, 0, 3, 0),
    (+7.0438804600e-07, 1, 0, 3, 1),
    (+1.6873796900e-07, 1, 0, 3, 2),
    (+4.1390846100e-10, 1, 0, 4, 0),
    (-1.1856624700e-09, 1, 0, 4, 1),
    (+4.0386326000e-13, 1, 0, 5, 0),
    (+8.8032603500e-02, 1, 1, 0, 0),
    (-3.3055282300e-03, 1, 1, 0, 1),
    (+1.1695236400e-02, 1, 1, 0, 2),
    (-4.3294386200e-03, 1, 1, 0, 3),
    (-5.1302785100e-04, 1, 1, 0, 4),
    (+8.9285983700e-04, 1, 1, 1, 0),
    (-6.8740518100e-04, 1, 1, 1, 1),
    (+2.6378958600e-04, 1, 1, 1, 2),
    (+2.5345803400e-05, 1, 1, 1, 3),
    (+5.2411097000e-06, 1, 1, 2, 0),
    (-5.0600459200e-06, 1, 1, 2, 1),
    (-5.4744689600e-07, 1, 1, 2, 2),
    (-1.8158473600e-09, 1, 1, 3, 0),
    (+7.9607997800e-09, 1, 1, 3, 1),
    (-2.2473096100e-11, 1, 1, 4, 0),
    (-4.0835027100e-03, 1, 2, 0, 0),
    (+5.0084566700e-03, 1, 2, 0, 1),
    (-6.9844573800e-04, 1, 2, 0, 2),
    (-6.6672470200e-05, 1, 2, 0, 3),
    (-4.9920431400e-05, 1, 2, 1, 0),
    (+3.2869651100e-05, 1, 2, 1, 1),
    (+3.6134113600e-06, 1, 2, 1, 2),
    (-1.3389561400e-07, 1, 2, 2, 0),
    (-1.7285703500e-08, 1, 2, 2, 1),
    (+1.3590835900e-10, 1, 2, 3, 0),
    (-6.5726314300e-05, 1, 3, 0, 0),
    (-1.7933039100e-04, 1, 3, 0, 1),
    (-1.2704387100e-05, 1, 3, 0, 2),
    (+1.3519132800e-06, 1, 3, 1, 0),
    (-7.3858440000e-09, 1, 3, 1, 1),
    (+1.9496005300e-09, 1, 3, 2, 0),
    (+9.6689187500e-06, 1, 4, 0, 0),
    (+1.2906487000e-06, 1, 4, 0, 1),
    (-1.8948925800e-08, 1, 4, 1, 0),
    (-1.7420254600e-07, 1, 5, 0, 0),
    (+8.0647024900e-04, 2, 0, 0, 0),
    (-1.9670186100e-02, 2, 0, 0, 1),
    (-3.9942841000e-03, 2, 0, 0, 2),
    (+1.5512603800e-02, 2, 0, 0, 3),
    (+1.3337484600e-03, 2, 0, 0, 4),
    (-1.7375451000e-04, 2, 0, 1, 0),
    (-3.1427968000e-05, 2, 0, 1, 1),
    (+8.9928115600e-05, 2, 0, 1, 2),
    (-5.4531431400e-09, 2, 0, 1, 3),
    (-4.5216656400e-07, 2, 0, 2, 0),
    (+4.8092523900e-06, 2, 0, 2, 1),
    (+1.1625797100e-06, 2, 0, 2, 2),
    (+7.5126948200e-09, 2, 0, 3, 0),
    (-1.8930916700e-08, 2, 0, 3, 1),
    (+9.2265225400e-12, 2, 0, 4, 0),
    (+2.1684445400e-03, 2, 1, 0, 0),
    (-1.6411944000e-03, 2, 1, 0, 1),
    (+4.9527190300e-04, 2, 1, 0, 2),
    (+1.4538982600e-04, 2, 1, 0, 3),
    (+3.4543304800e-06, 2, 1, 1, 0),
    (-9.1386387200e-06, 2, 1, 1, 1),
    (-7.0119900300e-06, 2, 1, 1, 2),
    (-8.7587498200e-08, 2, 1, 2, 0),
    (+1.1432536700e-07, 2, 1, 2, 1),
    (-3.5219767100e-10, 2, 1, 3, 0),
    (-5.2167067500e-05, 2, 2, 0, 0),
    (+1.0060125700e-06, 2, 2, 0, 1),
    (+2.3010907300e-05, 2, 2, 0, 2),
    (+2.4741717800e-07, 2, 2, 1, 0),
    (-7.1054245400e-07, 2, 2, 1, 1),
    (+2.4970982400e-09, 2, 2, 2, 0),
    (+2.2269752400e-07, 2, 3, 0, 0),
    (+2.3499444100e-06, 2, 3, 0, 1),
    (-6.2153125400e-09, 2, 3, 1, 0),
    (+2.5278585200e-09, 2, 4, 0, 0),
    (-1.5427137200e-04, 3, 0, 0, 0),
    (+9.9969087000e-04, 3, 0, 0, 1),
    (-9.5400919100e-04, 3, 0, 0, 2),
    (-2.6391727900e-04, 3, 0, 0, 3),
    (-7.6078115900e-07, 3, 0, 1, 0),
    (+2.5983555900e-06, 3, 0, 1, 1),
    (-7.1466394300e-07, 3, 0, 1, 2),
    (+2.4668887800e-08, 3, 0, 2, 0),
    (-8.7549204000e-08, 3, 0, 2, 1),
    (+9.7906384800e-11, 3, 0, 3, 0),
    (-1.5334708700e-05, 3, 1, 0, 0),
    (-5.1667069400e-06, 3, 1, 0, 1),
    (-1.9071088200e-05, 3, 1, 0, 2),
    (-3.7792577400e-07, 3, 1, 1, 0),
    (+5.1591680600e-07, 3, 1, 1, 1),
    (-1.5074306400e-09, 3, 1, 2, 0),
    (+1.9454466700e-06, 3, 2, 0, 0),
    (-1.8174864400e-06, 3, 2, 0, 1),
    (+1.0759646600e-08, 3, 2, 1, 0),
    (-4.1611703100e-08, 3, 3, 0, 0),
    (-3.2465173500e-06, 4, 0, 0, 0),
    (+9.5173851200e-06, 4, 0, 0, 1),
    (+1.9309097800e-05, 4, 0, 0, 2),
    (+3.7783028700e-08, 4, 0, 1, 0),
    (-4.7713652300e-08, 4, 0, 1, 1),
    (+2.4267434800e-10, 4, 0, 2, 0),
    (-5.7298370400e-07, 4, 1, 0, 0),
    (+9.5269243200e-07, 4, 1, 0, 1),
    (-1.6969937700e-09, 4, 1, 1, 0),
    (+1.1409953100e-08, 4, 2, 0, 0),
    (+7.3260285200e-08, 5, 0, 0, 0),
    (-4.6642634100e-07, 5, 0, 0, 1),
    (+5.4307967300e-10, 5, 0, 1, 0),
    (-2.5509014500e-09, 5, 1, 0, 0),
    (+1.3595907300e-09, 6, 0, 0, 0),
)

_MAX_DEGREE = 6


def utci_offset(ta_c, tmrt_c, wind_10m_ms, vapour_kpa):
    """
    UTCI offset from air temperature, in °C — the ``Offset(...)`` term of

        UTCI = Ta + Offset(Ta, Tmrt - Ta, va, e)

    Vectorised over numpy arrays or scalars. Inputs are clamped to
    :data:`UTCI_LIMITS` first, because a 6th-order polynomial evaluated outside
    its fit runs away fast.
    """
    raw_ta = np.asarray(ta_c, dtype=float)
    ta = _clamp(raw_ta, *UTCI_LIMITS["ta_c"])
    va = _clamp(np.asarray(wind_10m_ms, dtype=float), *UTCI_LIMITS["wind_10m_ms"])
    e = _clamp(np.asarray(vapour_kpa, dtype=float), *UTCI_LIMITS["vapour_pressure_kpa"])
    # The radiant excess is a difference of the *inputs*, taken before Ta is
    # clamped: clamping Ta first would turn "Tmrt = Ta = 90 °C" into a 40 °C
    # radiant excess and report heat stress that is not in the input.
    d_mrt = _clamp(np.asarray(tmrt_c, dtype=float) - raw_ta, *UTCI_LIMITS["tmrt_minus_ta_c"])

    ta_p = _powers(ta)
    va_p = _powers(va)
    d_p = _powers(d_mrt)
    e_p = _powers(e)

    total = np.zeros(np.broadcast(ta, va, d_mrt, e).shape, dtype=float)
    for coefficient, i, j, k, l in UTCI_POLYNOMIAL:
        term = ta_p[i] * va_p[j] * d_p[k] * e_p[l]
        if coefficient != 1.0:
            term = term * coefficient
        total += term
    return total


def utci(ta_c, tmrt_c, wind_10m_ms, vapour_kpa):
    """UTCI equivalent temperature in °C. ``Ta + Offset(Ta, Tmrt-Ta, va, e)``."""
    ta = _clamp(np.asarray(ta_c, dtype=float), *UTCI_LIMITS["ta_c"])
    return ta + utci_offset(ta_c, tmrt_c, wind_10m_ms, vapour_kpa)


# --------------------------------------------------------------------------- #
# 2. Inputs the forecast does not hand us directly
# --------------------------------------------------------------------------- #

def mean_radiant_temperature(ta_c, globe_c, wind_10m_ms):
    """
    Mean radiant temperature (°C) from a 150 mm black globe, ISO 7726:

        Tmrt = [ Tg^4 + (1.1e8 * v^0.6) / (eps * D^0.4) * (Tg - Ta) ]^(1/4)

    with ``v`` in m/s at globe height and temperatures in Kelvin. The 10 m wind
    is scaled down to the globe height with the log law before it is used.

    This is the standard bridge from the globe temperature ``core.thermal``
    already computes to the radiant input UTCI needs — no new measurement, no
    new assumption beyond the ISO conversion itself.
    """
    ta = np.asarray(ta_c, dtype=float)
    tg = np.asarray(globe_c, dtype=float)
    va = np.maximum(np.asarray(wind_10m_ms, dtype=float), 0.0)

    v_globe = va * _wind_scale_to_globe()
    factor = (1.1e8 * np.power(v_globe, 0.6)) / (GLOBE_EMISSIVITY * GLOBE_DIAMETER_M ** 0.4)

    ta_k, tg_k = ta + 273.15, tg + 273.15
    inner = np.power(tg_k, 4) + factor * (tg_k - ta_k)
    # The fourth root of a negative number is not a temperature. Can only happen
    # for an unphysical globe colder than its surroundings by a wide margin.
    return np.power(np.clip(inner, 0.0, None), 0.25) - 273.15


def utci_from_weather(ta_c, rh_pct, wind_ms, solar_wm2):
    """
    UTCI from the same four inputs :func:`core.thermal.wbgt_outdoor` takes.

        air temperature °C · relative humidity % · 10 m wind m/s · shortwave W/m²

    The chain is the one the paper specifies: globe temperature from
    ``core.thermal.globe_temperature`` -> ISO 7726 mean radiant temperature ->
    vapour pressure from Tetens -> UTCI polynomial. Kept in one call so the
    thermal pipeline cannot accidentally feed UTCI a radiant temperature built
    on different assumptions than the WBGT sitting next to it.
    """
    from core.thermal import globe_temperature, saturation_vapour_pressure

    ta = np.asarray(ta_c, dtype=float)
    globe = globe_temperature(ta, wind_ms, solar_wm2)
    tmrt = mean_radiant_temperature(ta, globe, wind_ms)
    vapour = saturation_vapour_pressure(ta) * np.clip(np.asarray(rh_pct, dtype=float), 0, 100) / 100.0
    return utci(ta, tmrt, wind_ms, vapour)


# --------------------------------------------------------------------------- #
# 3. Classification — the 10-category UTCI scale
# --------------------------------------------------------------------------- #

# The published UTCI assessment scale (Bröde et al. 2012, Table 1 / ESM 2).
# (lower bound °C, colour, label, public-health guidance)
UTCI_BANDS: tuple[tuple[float, str, str, str], ...] = (
    (-1e9,   "#3b4cca", "Extreme cold stress",     "Extreme cold. Open warm shelters."),
    (-40.0,  "#2f6fd0", "Very strong cold stress", "Very strong cold stress. Protect people sleeping rough."),
    (-27.0,  "#4fa3d1", "Strong cold stress",      "Strong cold stress. Wear warm clothing outdoors."),
    (-13.0,  "#7fd1c1", "Moderate cold stress",    "Moderate cold stress. Dress warmly, limit exposure."),
    (0.0,    "#a3e635", "Slight cold stress",      "Slight cold stress. No action required."),
    (9.0,    "#22c55e", "No thermal stress",       "Comfortable. No action required."),
    (26.0,   "#eab308", "Moderate heat stress",    "Stay hydrated. Avoid the midday sun."),
    (32.0,   "#f97316", "Strong heat stress",      "Rest in shade. Check on elderly neighbours."),
    (38.0,   "#ef4444", "Very strong heat stress", "Suspend outdoor work 12:00-15:00. Open cooling centres."),
    (46.0,   "#a21caf", "Extreme heat stress",     "Stop non-essential outdoor activity. Door-to-door checks."),
)


def classify_utci(value) -> dict:
    """Band, colour and guidance for a UTCI value in °C."""
    v = float(value)
    band = UTCI_BANDS[0]
    for entry in UTCI_BANDS:
        if v >= entry[0]:
            band = entry
    return {"colour": band[1], "band": band[2], "guidance": band[3].strip()}


#: Provenance shipped with every payload that carries a UTCI value.
UTCI_METADATA: dict[str, object] = {
    "index_name": "Universal Thermal Climate Index (UTCI)",
    "version": "1.0.0",
    "reference": (
        "Bröde et al. (2012), Int J Biometeorol 56(3):481-494, "
        "doi:10.1007/s00484-011-0454-1 (6th-order polynomial approximation of "
        "the Fiala multi-node model, 210 coefficients)."
    ),
    "formula": "UTCI = Ta + Offset(Ta, Tmrt - Ta, va_10m, e)",
    "mean_radiant_temperature": (
        "ISO 7726 black-globe conversion of the globe temperature computed in "
        "core.thermal.globe_temperature; 10 m wind scaled to 1.1 m with the "
        "log law (z0 = 0.01 m) before use."
    ),
    "vapour_pressure": "Tetens saturation vapour pressure x RH/100 (kPa) — core.thermal.saturation_vapour_pressure",
    "validity_envelope": {
        "ta_c": [-50.0, 50.0],
        "tmrt_minus_ta_c": [-30.0, 70.0],
        "wind_10m_ms": [0.5, 17.0],
        "vapour_pressure_kpa": [0.0, 5.0],
    },
    "clamping": "Inputs outside the validity envelope are clamped to it, never extrapolated.",
    "relationship_to_wbgt": (
        "Complementary, not interchangeable. WBGT is the occupational index that "
        "drives the hazard score and work/rest rules; UTCI is the population "
        "index used for public-health categorisation and CAP severity."
    ),
    "coefficient_source": (
        "Vendored from the published table (Apache-2.0 reference implementation: "
        "ECMWF thermofeel). See THIRD-PARTY.md."
    ),
}


# --------------------------------------------------------------------------- #
# 4. Internals
# --------------------------------------------------------------------------- #

def _clamp(values, low: float, high: float):
    return np.clip(np.asarray(values, dtype=float), low, high)


def _powers(values):
    """``[v^0, v^1, ... v^6]`` — one pass, then every term is a lookup."""
    out = [np.ones_like(values)]
    for _ in range(_MAX_DEGREE):
        out.append(out[-1] * values)
    return out


def _wind_scale_to_globe() -> float:
    """Log-law factor from 10 m wind to wind at the 1.1 m globe height."""
    return (np.log10(GLOBE_HEIGHT_M / ROUGHNESS_LENGTH_M)
            / np.log10(WIND_REFERENCE_HEIGHT_M / ROUGHNESS_LENGTH_M))


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import pandas as pd

    from core.thermal import globe_temperature

    print("=" * 78)
    print("A) UTCI at the reference condition must equal air temperature")
    print("=" * 78)
    # By definition UTCI is the air temperature that produces the same strain at
    # the reference environment: 50% RH, Tmrt = Ta, wind 0.5 m/s at 10 m.
    rows = []
    for ta in (-10.0, 0.0, 10.0, 20.0, 30.0, 40.0):
        e = 0.6108 * np.exp(17.27 * ta / (ta + 237.3)) * 0.5
        got = float(utci(ta, ta, 0.5, e))
        rows.append({"ta_c": ta, "utci_c": round(got, 2), "deviation": round(got - ta, 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    print("note: the reference wind is 0.5 m/s, not calm, so a small offset at")
    print("      high temperature is the wind term, not an error.")

    print("\n" + "=" * 78)
    print("B) Response to each input (all else at the reference condition)")
    print("=" * 78)
    base_t, base_e = 30.0, 0.6108 * np.exp(17.27 * 30 / (30 + 237.3)) * 0.5
    print(pd.DataFrame([
        {"case": f"Tmrt - Ta = {d:+.0f} C", "utci_c": round(float(utci(base_t, base_t + d, 0.5, base_e)), 2)}
        for d in (-10, -5, 0, 10, 20, 30, 40)
    ]).to_string(index=False))
    print(pd.DataFrame([
        {"case": f"wind {v:.1f} m/s", "utci_c": round(float(utci(base_t, base_t, v, base_e)), 2)}
        for v in (0.5, 1, 2, 4, 8, 17)
    ]).to_string(index=False))
    print(pd.DataFrame([
        {"case": f"RH {r:.0f}%", "utci_c": round(float(utci(base_t, base_t, 0.5,
                                                            0.6108 * np.exp(17.27 * base_t / (base_t + 237.3)) * r / 100)), 2)}
        for r in (10, 30, 50, 70, 90)
    ]).to_string(index=False))

    print("\n" + "=" * 78)
    print("C) End-to-end from forecast inputs, against WBGT and Heat Index")
    print("=" * 78)
    cases = [
        ("cool, dry, still",      24.0, 45.0, 1.0, 100.0),
        ("warm, humid, calm",     31.0, 80.0, 1.0, 300.0),
        ("hot, dry, windy",       40.0, 20.0, 6.0, 850.0),
        ("Kolkata pre-monsoon",   38.0, 65.0, 2.0, 900.0),
        ("monsoon, no sun",       32.0, 90.0, 1.5, 20.0),
        ("night",                 29.0, 85.0, 0.5, 0.0),
    ]
    from core.thermal import wbgt_outdoor, heat_index
    rows = []
    for label, t, rh, v, s in cases:
        globe = float(globe_temperature(t, v, s))
        rows.append({
            "case": label, "ta_c": t, "rh_%": rh, "wind_ms": v, "solar": s,
            "globe_c": round(globe, 1),
            "mrt_c": round(float(mean_radiant_temperature(t, globe, v)), 1),
            "utci_c": round(float(utci_from_weather(t, rh, v, s)), 2),
            "utci_band": classify_utci(utci_from_weather(t, rh, v, s))["band"],
            "wbgt_c": round(float(wbgt_outdoor(t, rh, v, s)), 2),
            "hi_c": round(float(heat_index(t, rh)), 2),
        })
    print(pd.DataFrame(rows).to_string(index=False))
