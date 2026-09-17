"""
HEALTH-IMPACT / MORTALITY-RISK INDICATOR — with hard validation boundaries
==========================================================================
This module answers "what could this heat DO to people?" while refusing to
overclaim. Three mutually exclusive model statuses exist and every payload
carries exactly one:

    validated_observed_outcome_model
        A model fitted AND evaluated against named, documented observed
        health-outcome data (mortality or hospitalisation counts). This repo
        ships NO such dataset, so this status is unreachable unless an
        operator supplies real outcome data AND a reproducible evaluation
        report (see ``resolve_model_status``). The code path exists so the
        boundary is explicit, not aspirational.

    parameterised_health_risk_indicator
        A transparent rule-based index (documented weights, no fitting)
        combining thermal stress, climate-normal departure, air quality and
        vulnerability. It indicates pressure and priority; it is NOT a
        forecast of deaths or admissions.

    synthetic_demo
        The same indicator computed on labelled synthetic demo inputs. Shown
        only inside the Heat Risk Demo and marked on every row.

Health-outcome ingestion (for a future validated model) has a documented
schema — see ``HEALTH_OUTCOME_SCHEMA`` and data/health_outcomes/README.md.
Files that do not match the schema are rejected loudly rather than trusted.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from core import config

# --------------------------------------------------------------------------- #
# 1. Status vocabulary — the ONLY allowed labels
# --------------------------------------------------------------------------- #

STATUS_VALIDATED = "validated_observed_outcome_model"
STATUS_PARAMETERISED = "parameterised_health_risk_indicator"
STATUS_SYNTHETIC_DEMO = "synthetic_demo"

MODEL_STATUSES = (STATUS_VALIDATED, STATUS_PARAMETERISED, STATUS_SYNTHETIC_DEMO)

STATUS_MEANING: dict[str, str] = {
    STATUS_VALIDATED: (
        "Fitted and evaluated against named, documented observed health-outcome "
        "data (mortality/hospitalisation). Requires an evaluation report with "
        "the dataset name, coverage window and outcome-linked metrics."
    ),
    STATUS_PARAMETERISED: (
        "Transparent rule-based indicator with documented weights. It ranks "
        "heat-health pressure; it is NOT a validated forecast of deaths or "
        "hospital admissions and must never be presented as one."
    ),
    STATUS_SYNTHETIC_DEMO: (
        "The same rule-based indicator driven by labelled synthetic demo "
        "weather/vulnerability inputs. Illustrative only — not a live forecast, "
        "not an observation, and not a validated mortality model."
    ),
}

# What it would take to legitimately claim STATUS_VALIDATED. Shown in the UI
# and README so the boundary is a documented fact, not a vibe.
VALIDATION_REQUIREMENTS: tuple[str, ...] = (
    "Daily observed outcome counts (all-cause or heat-attributable mortality, "
    "and/or heatstroke hospital admissions, e.g. ICD-10 T67) at ward/zone level "
    "or a documented aggregation to it, from a named authority (municipal vital "
    "registration, hospital HMIS, civil registration).",
    "At least three consecutive hot seasons of coverage, with a documented "
    "data-quality statement (completeness, reporting lag, coverage).",
    "A pre-registered evaluation on out-of-sample seasons reporting outcome-"
    "linked metrics (e.g. CSI/HSS of high-impact days, calibration of excess "
    "counts) — retrospective reanalysis replay alone does NOT qualify as "
    "operational forecast skill.",
    "Ethics/privacy clearance for handling health-outcome data, and the "
    "evaluation report committed at data/validation/health_outcome_model_evaluation.json.",
)

EVALUATION_REPORT_PATH = config.DATA_DIR / "validation" / "health_outcome_model_evaluation.json"
HEALTH_OUTCOME_DIR = config.DATA_DIR / "health_outcomes"

# --------------------------------------------------------------------------- #
# 2. Health-outcome data schema + ingestion path
# --------------------------------------------------------------------------- #

HEALTH_OUTCOME_SCHEMA: dict[str, Any] = {
    "description": (
        "Required schema for REAL historical mortality/hospitalisation data. "
        "Ingest with core.health_impact.load_health_outcomes(path). Files that "
        "fail validation are rejected — a warning system must not learn from "
        "silently malformed outcome data."
    ),
    "required_columns": {
        "date": "ISO date (YYYY-MM-DD) of the outcome day.",
        "location_id": "Zone/ward identifier matching the warning system's locations.",
        "outcome_type": "One of: mortality, hospitalisation.",
        "count": "Non-negative integer outcome count for that day/location.",
        "source": "Named authority or dataset the count came from (free text).",
        "data_quality": "One of: official, provisional, estimated, incomplete.",
    },
    "optional_columns": {
        "coverage": "Share of the population covered by the reporting system (0–1).",
        "icd_codes": "Semicolon-separated ICD-10 codes when hospitalisation is cause-specific.",
        "notes": "Free-text caveats.",
    },
    "example_path": "data/health_outcomes/example.SYNTHETIC-do-not-use-as-truth.csv",
}

OUTCOME_TYPES = ("mortality", "hospitalisation")
QUALITY_FLAGS = ("official", "provisional", "estimated", "incomplete")


def load_health_outcomes(path: Path | str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load and validate real historical outcome data.

    Returns ``(frame, metadata)``. Raises ``ValueError`` with a readable reason
    on any schema violation — never a partially trusted frame.
    """
    source = Path(path)
    if not source.exists():
        raise ValueError(f"health-outcome file not found: {source}")
    df = pd.read_csv(source)
    missing = set(HEALTH_OUTCOME_SCHEMA["required_columns"]) - set(df.columns)
    if missing:
        raise ValueError(
            f"{source.name} is missing required columns: {sorted(missing)}. "
            f"See {HEALTH_OUTCOME_SCHEMA['description']}"
        )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date"].isna().any():
        bad = df.loc[df["date"].isna(), "date"].head(3).tolist()
        raise ValueError(f"{source.name} has unparseable dates (e.g. {bad})")
    bad_type = sorted(set(df["outcome_type"]) - set(OUTCOME_TYPES))
    if bad_type:
        raise ValueError(f"{source.name} has unknown outcome_type values: {bad_type}")
    bad_quality = sorted(set(df["data_quality"]) - set(QUALITY_FLAGS))
    if bad_quality:
        raise ValueError(f"{source.name} has unknown data_quality values: {bad_quality}")
    counts = pd.to_numeric(df["count"], errors="coerce")
    if counts.isna().any() or (counts < 0).any():
        raise ValueError(f"{source.name} has negative or non-numeric counts")
    df["count"] = counts.astype(int)
    if not str(source).lower().endswith(".csv"):
        raise ValueError(f"{source.name}: only CSV ingestion is documented")
    metadata = {
        "path": str(source),
        "rows": int(len(df)),
        "locations": int(df["location_id"].nunique()),
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "sources": sorted({str(s) for s in df["source"].unique()}),
        "quality_flags_present": sorted({str(q) for q in df["data_quality"].unique()}),
    }
    return df, metadata


def resolve_model_status(
    *,
    demo: bool = False,
    outcomes_path: Path | str | None = None,
    evaluation_path: Path | str = EVALUATION_REPORT_PATH,
) -> tuple[str, str]:
    """Pick the model status — and make ``validated`` genuinely hard to reach.

    Rules (enforced by tests/test_health_impact.py):
      * demo inputs  -> always ``synthetic_demo``, whatever else exists.
      * validated    -> ONLY when a committed evaluation report names an
                        observed dataset AND the outcome file loads cleanly
                        against the documented schema AND the report contains
                        outcome-linked metrics.
      * otherwise    -> ``parameterised_health_risk_indicator``.
    """
    if demo:
        return STATUS_SYNTHETIC_DEMO, STATUS_MEANING[STATUS_SYNTHETIC_DEMO]

    evaluation: dict[str, Any] | None = None
    eval_path = Path(evaluation_path)
    if eval_path.exists():
        try:
            evaluation = json.loads(eval_path.read_text())
        except (OSError, json.JSONDecodeError):
            evaluation = None

    if isinstance(evaluation, dict):
        names_dataset = bool(str(evaluation.get("observed_data_source", "")).strip())
        has_metrics = bool(evaluation.get("metrics"))
        outcomes_ok = False
        if outcomes_path is not None:
            try:
                load_health_outcomes(outcomes_path)
                outcomes_ok = True
            except (ValueError, OSError):
                outcomes_ok = False
        if names_dataset and has_metrics and outcomes_ok:
            return STATUS_VALIDATED, STATUS_MEANING[STATUS_VALIDATED]

    return STATUS_PARAMETERISED, STATUS_MEANING[STATUS_PARAMETERISED]


# --------------------------------------------------------------------------- #
# 3. The indicator itself — every weight documented, nothing fitted
# --------------------------------------------------------------------------- #

HEALTH_IMPACT_PARAMETERS: dict[str, Any] = {
    "weights": {
        "thermal_stress": 0.62,   # HTSI score (meteorological, core/htsi.py)
        "vulnerability": 0.28,    # zone vulnerability profile (0–100)
    },
    "anomaly_bonus": {
        "per_c_above_2": 1.6,     # departure from the fixed climate normal
        "cap": 6.0,               # bonus caps at +6 points above +2 °C departure
    },
    "air_quality_bonus": {
        "aqi_threshold": 200.0,   # concurrent pollution adds physiological load
        "per_aqi_above": 1 / 25.0,
        "cap": 6.0,
    },
    "bands": (
        (0.0, "Low", "Routine monitoring; no impact-based escalation from health pressure."),
        (25.0, "Moderate", "Heat-sensitive groups feel pressure; prepare municipal heat actions."),
        (45.0, "High", "Expect elevated heat-health pressure; activate health-system readiness."),
        (65.0, "Very High", "Severe heat-health pressure likely; emergency coordination."),
    ),
    "formula": (
        "impact = clip(0.62·HTSI + 0.28·vulnerability "
        "+ min(6, 1.6·max(0, Tmax−normal−2)) + min(6, max(0, AQI−200)/25), 0, 100)"
    ),
    "not_a_forecast_of": (
        "This indicator does NOT predict a number of deaths or admissions. Any "
        "such count derived downstream is illustrative arithmetic on stated "
        "assumptions, not an epidemiological forecast."
    ),
}


def health_impact_band(index: float | None) -> str:
    if index is None or not math.isfinite(float(index)):
        return "Unavailable"
    value = float(index)
    chosen = HEALTH_IMPACT_PARAMETERS["bands"][0][1]
    for lo, name, _advice in HEALTH_IMPACT_PARAMETERS["bands"]:
        if value >= lo:
            chosen = name
    return chosen


def health_impact_index(
    htsi_score_value: float | None,
    vulnerability: float | None,
    departure_c: float | None = None,
    aqi: float | None = None,
) -> float | None:
    """0–100 parameterised health-impact indicator (documented above).

    Missing terms degrade transparently: a missing vulnerability term falls
    back to the city-mean placeholder 50 and the payload must say so via
    ``health_impact_inputs``; a missing HTSI yields None (never a fake 0).
    """
    if htsi_score_value is None or not math.isfinite(float(htsi_score_value)):
        return None
    w = HEALTH_IMPACT_PARAMETERS["weights"]
    vuln = float(vulnerability) if vulnerability is not None and math.isfinite(float(vulnerability)) else 50.0
    index = w["thermal_stress"] * float(htsi_score_value) + w["vulnerability"] * vuln

    bonus = HEALTH_IMPACT_PARAMETERS["anomaly_bonus"]
    if departure_c is not None and math.isfinite(float(departure_c)):
        index += min(bonus["cap"], bonus["per_c_above_2"] * max(0.0, float(departure_c) - 2.0))

    aq = HEALTH_IMPACT_PARAMETERS["air_quality_bonus"]
    if aqi is not None and math.isfinite(float(aqi)):
        index += min(aq["cap"], max(0.0, float(aqi) - aq["aqi_threshold"]) * aq["per_aqi_above"])

    return round(min(100.0, max(0.0, index)), 1)


def health_impact_block(
    *,
    htsi_score_value: float | None,
    vulnerability: float | None,
    departure_c: float | None = None,
    aqi: float | None = None,
    demo: bool = False,
    vulnerability_source: str = "unavailable",
    outcomes_path: Path | str | None = None,
) -> dict[str, Any]:
    """Serialisable indicator + status + honesty metadata for API payloads.

    The returned dict ALWAYS contains ``model_status``; the only route to
    ``validated_observed_outcome_model`` passes through
    ``resolve_model_status`` and its evidence requirements.
    """
    index = health_impact_index(htsi_score_value, vulnerability, departure_c, aqi)
    status, meaning = resolve_model_status(demo=demo, outcomes_path=outcomes_path)
    inputs = {
        "htsi_score": None if htsi_score_value is None or not math.isfinite(float(htsi_score_value)) else round(float(htsi_score_value), 1),
        "vulnerability": None if vulnerability is None or not math.isfinite(float(vulnerability)) else round(float(vulnerability), 1),
        "vulnerability_source": vulnerability_source,
        "departure_from_normal_c": None if departure_c is None or not math.isfinite(float(departure_c)) else round(float(departure_c), 1),
        "aqi_indicative": None if aqi is None or not math.isfinite(float(aqi)) else round(float(aqi), 1),
        "missing_terms": [
            name for name, value in (
                ("htsi_score", htsi_score_value), ("vulnerability", vulnerability),
                ("departure_from_normal_c", departure_c), ("aqi_indicative", aqi),
            ) if value is None or not math.isfinite(float(value))
        ],
    }
    return {
        "health_impact_index": index,
        "health_impact_band": health_impact_band(index),
        "model_status": status,
        "model_status_meaning": meaning,
        "parameters": HEALTH_IMPACT_PARAMETERS,
        "inputs": inputs,
        "validation_requirements": list(VALIDATION_REQUIREMENTS),
        "evaluation_report_expected_at": str(EVALUATION_REPORT_PATH),
    }


__all__ = [
    "EVALUATION_REPORT_PATH", "HEALTH_IMPACT_PARAMETERS", "HEALTH_OUTCOME_DIR",
    "HEALTH_OUTCOME_SCHEMA", "MODEL_STATUSES", "OUTCOME_TYPES", "QUALITY_FLAGS",
    "STATUS_PARAMETERISED", "STATUS_SYNTHETIC_DEMO", "STATUS_VALIDATED",
    "STATUS_MEANING", "VALIDATION_REQUIREMENTS", "health_impact_band",
    "health_impact_block", "health_impact_index", "load_health_outcomes",
    "resolve_model_status",
]


# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover — worked example
    print("health-impact indicator worked examples")
    print("=" * 68)
    for label, kwargs in (
        ("demo, severe heat", dict(htsi_score_value=92.0, vulnerability=71.0, departure_c=6.8, aqi=120.0, demo=True)),
        ("live, warning", dict(htsi_score_value=64.0, vulnerability=55.0, departure_c=4.2, aqi=230.0)),
        ("missing HTSI", dict(htsi_score_value=None, vulnerability=55.0)),
    ):
        block = health_impact_block(vulnerability_source="synthetic demo profile" if kwargs.get("demo") else "unavailable", **kwargs)
        print(f"{label:22s} index={block['health_impact_index']} band={block['health_impact_band']} status={block['model_status']}")
