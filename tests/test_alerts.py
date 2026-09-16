"""
Phase 5 regression tests: the alert engine and its threshold plumbing.

Why these exist
---------------
The risk threshold was recalibrated 65 -> 60 when the Census social block
rebalanced the vulnerability index. It was hard-coded in FOUR places
(core/alerts.py, app/main.py's GET default, app/main.py's POST body, and the
frontend). Only one was updated, so the engine warned 6 wards while the API's
own default reported 0 — a silent, very convincing lie.

These tests pin every copy to the single constant and cover the lead-time rule
that defines "warning" vs "nowcast".
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from core.alerts import (
    DEFAULT_MIN_LEAD_DAYS,
    DEFAULT_RISK_THRESHOLD,
    compose_message,
    find_active_now,
    find_upcoming_events,
)

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 4)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _frame(rows: list[tuple]) -> pd.DataFrame:
    """rows = (ward_id, date_offset_days, risk_score)"""
    return pd.DataFrame(
        [
            {
                "ward_id": w,
                "ward_name": f"Ward {w}",
                "date": (TODAY + timedelta(days=off)).isoformat(),
                "risk_score": score,
                "risk_band": "Danger" if score >= 50 else "Caution",
                "wbgt_peak_c": 33.0,
                "tmax_adj_c": 35.0,
                "uhi_delta_c": 2.0,
                "population": 10_000,
                "exposed_population": 6_000,
            }
            for w, off, score in rows
        ]
    )


# --------------------------------------------------------------------------- #
# 1. Threshold single-source-of-truth
# --------------------------------------------------------------------------- #

def test_threshold_is_recalibrated_to_60():
    """65 left only one ward warned after the vulnerability rebalance."""
    assert DEFAULT_RISK_THRESHOLD == 60.0
    assert DEFAULT_MIN_LEAD_DAYS == 1


def test_no_hard_coded_threshold_copies():
    """Every default must read the constant, never a literal.

    This is the exact bug that shipped: three of four copies still said 65.0.
    """
    for rel in ("app/main.py", "core/alerts.py"):
        src = (ROOT / rel).read_text()
        # strip comments so the explanatory "Was 65.0..." note doesn't trip it
        code = "\n".join(
            line.split("#")[0] for line in src.splitlines()
        )
        hits = re.findall(r"threshold\w*\s*[:=]\s*(6[0-9](?:\.\d+)?)", code)
        assert not hits, f"{rel} hard-codes threshold {hits}"


def test_api_defaults_follow_the_constant():
    """The HTTP layer must not drift from the engine."""
    from app import main as api

    assert api.alerts_plan.__defaults__[0] == DEFAULT_RISK_THRESHOLD
    assert api.alerts_plan.__defaults__[1] == DEFAULT_MIN_LEAD_DAYS
    assert api.DispatchIn.model_fields["threshold"].default == DEFAULT_RISK_THRESHOLD


# --------------------------------------------------------------------------- #
# 2. Lead time — a warning is not a nowcast
# --------------------------------------------------------------------------- #

def test_event_today_is_not_a_warning():
    """D+0 has no intervention window left, so it must not be queued."""
    df = _frame([(1, 0, 90.0)])
    assert find_upcoming_events(df, min_lead_days=1, today=TODAY).empty


def test_event_tomorrow_is_a_warning():
    df = _frame([(1, 1, 90.0)])
    ev = find_upcoming_events(df, min_lead_days=1, today=TODAY)
    assert len(ev) == 1
    assert int(ev.iloc[0]["lead_days"]) == 1


def test_min_lead_days_is_respected():
    """A 2-day lead filter must drop a crossing only 1 day out."""
    df = _frame([(1, 1, 90.0), (2, 4, 90.0)])
    assert len(find_upcoming_events(df, min_lead_days=1, today=TODAY)) == 2
    ev = find_upcoming_events(df, min_lead_days=2, today=TODAY)
    assert len(ev) == 1
    assert int(ev.iloc[0]["ward_id"]) == 2


def test_multi_day_heatwave_still_warns():
    """Regression: a ward hot today AND tomorrow must still be warned for
    tomorrow. An earlier version took the global first crossing (today, zero
    lead) and discarded the ward entirely, suppressing the case that matters."""
    df = _frame([(7, 0, 95.0), (7, 1, 95.0), (7, 2, 95.0)])
    ev = find_upcoming_events(df, min_lead_days=1, today=TODAY)
    assert len(ev) == 1
    assert int(ev.iloc[0]["lead_days"]) == 1


def test_one_row_per_ward_and_sorted_by_urgency():
    df = _frame([(1, 3, 61.0), (2, 1, 62.0), (3, 2, 63.0), (4, 1, 64.0)])
    ev = find_upcoming_events(df, min_lead_days=1, today=TODAY)
    assert len(ev) == 4
    assert ev["ward_id"].nunique() == 4
    # soonest first, then worst-first within a day
    assert list(ev["lead_days"]) == sorted(ev["lead_days"])
    assert int(ev.iloc[0]["ward_id"]) == 4  # lead 1, risk 64


def test_threshold_boundary_is_inclusive():
    df = _frame([(1, 2, DEFAULT_RISK_THRESHOLD)])
    assert len(find_upcoming_events(df, min_lead_days=1, today=TODAY)) == 1
    df = _frame([(1, 2, DEFAULT_RISK_THRESHOLD - 0.1)])
    assert find_upcoming_events(df, min_lead_days=1, today=TODAY).empty


def test_below_threshold_never_warns():
    df = _frame([(w, d, 10.0) for w in range(1, 6) for d in range(0, 5)])
    assert find_upcoming_events(df, min_lead_days=1, today=TODAY).empty


# --------------------------------------------------------------------------- #
# 3. Active-now (nowcast) is tracked separately
# --------------------------------------------------------------------------- #

def test_active_now_counts_today_only():
    """Yesterday's row must not inflate the count (past_days=1 is in the data)."""
    df = _frame([(1, -1, 99.0), (1, 0, 61.0), (2, 0, 20.0)])
    act = find_active_now(df, today=TODAY)
    assert len(act) == 1
    assert int(act.iloc[0]["ward_id"]) == 1


def test_active_and_upcoming_are_disjoint():
    df = _frame([(1, 0, 80.0), (1, 3, 80.0), (2, 3, 80.0)])
    act = find_active_now(df, today=TODAY)
    up = find_upcoming_events(df, min_lead_days=1, today=TODAY)
    assert set(act["ward_id"]) == {1}
    assert set(up["ward_id"]) == {1, 2}  # warned for D+3, also hot today


# --------------------------------------------------------------------------- #
# 4. Message content
# --------------------------------------------------------------------------- #

def test_message_has_ward_date_and_guidance():
    df = _frame([(24, 4, 63.9)])
    ev = find_upcoming_events(df, min_lead_days=1, today=TODAY)
    msg = compose_message(ev.iloc[0].to_dict())
    assert "Ward 24" in msg
    # human-readable date, not ISO — this is SMS copy going to residents
    assert "08 Sep" in msg
    assert "4 day" in msg          # lead time is the whole point of the message
    assert "WBGT" in msg
    assert len(msg) <= 320         # single SMS segment


# --------------------------------------------------------------------------- #
# 5. Empty input must not explode
# --------------------------------------------------------------------------- #

def test_empty_frame_returns_empty():
    """A day with no crossings must yield an empty queue, not a crash."""
    empty = pd.DataFrame(
        columns=["ward_id", "ward_name", "date", "risk_score", "risk_band"]
    )
    assert find_upcoming_events(empty, today=TODAY).empty
    assert find_active_now(empty, today=TODAY).empty


def test_empty_result_has_expected_columns():
    """Callers index these columns unconditionally, so they must always exist."""
    df = _frame([(1, 0, 90.0)])  # today only -> nothing upcoming
    ev = find_upcoming_events(df, min_lead_days=1, today=TODAY)
    for col in ("ward_id", "ward_name", "event_date", "lead_days", "risk_score"):
        assert col in ev.columns
