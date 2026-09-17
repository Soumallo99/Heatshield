"""Validate the NCR air-quality source against *observed* CPCB/CAAQMS PM2.5.

The coupled heat + air load is deliberately not tuned until it "looks right".
This command pairs an observed station daily mean with the corresponding
Open-Meteo CAMS archive daily mean, writes reproducible error and event-skill
metrics, and labels exactly what it does **not** validate.

Example (a tidy CPCB export with a timestamp and PM2.5 column)::

    python -m scripts.validate_coupled_aqi \
      --observations data/raw/anand-vihar-cpcb.csv \
      --lat 28.6469 --lon 77.3160 --station "Anand Vihar" \
      --source-url "https://airquality.cpcb.gov.in/..."

For an offline/reproducible rerun, save an Open-Meteo archive response as a
CSV with ``timestamp_local,pm25_ugm3`` and pass ``--model``.  The output is a
small JSON report suitable for ``/ncr/validation``; the potentially large raw
CAAQMS export remains outside Git.

Metrics intentionally include MAE, RMSE, bias, correlation, CSI and HSS. They
never report bare accuracy: AQ episodes are rare enough that a never-alert
model can score impressively while providing no warning value.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from core.coupled import contingency_scores, get_air_quality

DEFAULT_OUTPUT = Path("data/validation/coupled_aqi_validation.json")
DEFAULT_CPCB_SOURCE = "https://airquality.cpcb.gov.in/ccr/#/caaqm-dashboard-all/caaqm-landing/caaqm-data-repository"


def _normalise_name(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _find_column(frame: pd.DataFrame, aliases: tuple[str, ...], label: str) -> str:
    lookup = {_normalise_name(column): str(column) for column in frame.columns}
    for alias in aliases:
        if alias in lookup:
            return lookup[alias]
    raise ValueError(f"could not find a {label} column; accepted aliases: {', '.join(aliases)}")


def _numeric(series: pd.Series) -> pd.Series:
    """Read CAAQMS cells such as '<10', ' 54.2 ', '--' without inventing data."""
    clean = series.astype(str).str.replace(r"[^0-9.\-]+", "", regex=True)
    return pd.to_numeric(clean, errors="coerce")


def tidy_observations(frame: pd.DataFrame, timezone_name: str = "Asia/Kolkata") -> pd.DataFrame:
    """Normalise a tidy CPCB/CAAQMS export to local daily observed PM2.5 means.

    In addition to conventional ``PM2.5`` headers, this accepts the common
    stream shape ``parameter,value,timestamp``.  A mixed-pollutant stream is
    filtered to its PM2.5 parameter before aggregation; a bare ``value`` field
    is never assumed to mean PM2.5 when its parameter says otherwise.
    """
    timestamp_column = _find_column(
        frame,
        ("timestamplocal", "timestamp", "datetime", "datetimeist", "datetimeutc", "dateandtime", "date"),
        "timestamp",
    )
    pm25_column = _find_column(
        frame,
        ("pm25", "pm25ugm3", "pm25value", "pm2point5", "pm2_5", "pm2.5", "value"),
        "PM2.5",
    )
    source = frame.copy()
    if _normalise_name(pm25_column) == "value":
        columns = {_normalise_name(column): str(column) for column in source.columns}
        parameter_column = next((columns[name] for name in ("parameter", "param", "pollutant") if name in columns), None)
        if parameter_column is not None:
            pm25_rows = source[parameter_column].map(_normalise_name).eq("pm25")
            source = source.loc[pm25_rows].copy()
            if source.empty:
                raise ValueError("a generic value column was supplied but no PM2.5 parameter rows were found")
    stamp = pd.to_datetime(source[timestamp_column], errors="coerce", format="mixed")
    # A CAAQMS export is normally local IST. If it explicitly carries an offset,
    # normalise it before extracting the local calendar day.
    try:
        if getattr(stamp.dt, "tz", None) is not None:
            stamp = stamp.dt.tz_convert(timezone_name).dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    out = pd.DataFrame({"timestamp_local": stamp, "observed_pm25_ugm3": _numeric(source[pm25_column])}).dropna()
    out = out[out["observed_pm25_ugm3"] >= 0]
    if out.empty:
        raise ValueError("no non-negative timestamped PM2.5 observations found")
    out["date"] = out["timestamp_local"].dt.date
    return (
        out.groupby("date", as_index=False)
        .agg(observed_pm25_ugm3=("observed_pm25_ugm3", "mean"), observation_hours=("timestamp_local", "count"))
        .sort_values("date")
        .reset_index(drop=True)
    )


def quality_screen_observations(observations: pd.DataFrame, minimum_hours: int = 18) -> pd.DataFrame:
    """Keep daily means with enough valid hourly values for a limited comparison.

    ``18`` is a transparent 75% coverage screen, not a claim that this alone
    confers regulatory validity. The caller records the screen in its report.
    """
    if minimum_hours < 1 or int(minimum_hours) != minimum_hours:
        raise ValueError("minimum observation hours must be a positive integer")
    needed = {"date", "observed_pm25_ugm3", "observation_hours"}
    missing = needed - set(observations)
    if missing:
        raise ValueError(f"observation frame missing {sorted(missing)}")
    screened = observations[observations["observation_hours"] >= int(minimum_hours)].copy()
    if screened.empty:
        raise ValueError(f"no daily observations meet the {minimum_hours}-hour coverage screen")
    return screened.reset_index(drop=True)


def tidy_model(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise a CAMS archive CSV/frame to local daily model PM2.5 means."""
    timestamp_column = _find_column(frame, ("timestamplocal", "timestamp", "datetime", "date"), "model timestamp")
    pm25_column = _find_column(frame, ("pm25ugm3", "pm25", "pm2_5", "pm2.5"), "model PM2.5")
    out = pd.DataFrame({
        "timestamp_local": pd.to_datetime(frame[timestamp_column], errors="coerce", format="mixed"),
        "model_pm25_ugm3": _numeric(frame[pm25_column]),
    }).dropna()
    out = out[out["model_pm25_ugm3"] >= 0]
    if out.empty:
        raise ValueError("no non-negative timestamped model PM2.5 values found")
    out["date"] = out["timestamp_local"].dt.date
    return (
        out.groupby("date", as_index=False)
        .agg(model_pm25_ugm3=("model_pm25_ugm3", "mean"), model_hours=("timestamp_local", "count"))
        .sort_values("date")
        .reset_index(drop=True)
    )


def paired_metrics(paired: pd.DataFrame, event_threshold: float = 90.0) -> dict[str, Any]:
    """Error and event-skill metrics for a paired daily observed/model frame."""
    needed = {"observed_pm25_ugm3", "model_pm25_ugm3"}
    missing = needed - set(paired)
    if missing:
        raise ValueError(f"paired frame missing {sorted(missing)}")
    clean = paired.dropna(subset=sorted(needed)).copy()
    if clean.empty:
        raise ValueError("no overlapping daily observed/model PM2.5 values")
    error = clean["model_pm25_ugm3"] - clean["observed_pm25_ugm3"]
    correlation = clean["model_pm25_ugm3"].corr(clean["observed_pm25_ugm3"])
    skill = contingency_scores(clean["model_pm25_ugm3"] >= event_threshold,
                               clean["observed_pm25_ugm3"] >= event_threshold)
    return {
        "n_days": int(len(clean)),
        "mae_ugm3": round(float(error.abs().mean()), 2),
        "rmse_ugm3": round(float(np.sqrt(np.mean(np.square(error)))), 2),
        "mean_bias_ugm3": round(float(error.mean()), 2),
        "pearson_r": round(float(correlation), 3) if pd.notna(correlation) else None,
        "event_threshold_pm25_ugm3": float(event_threshold),
        "event_skill": skill,
    }


def persistence_metrics(paired: pd.DataFrame, event_threshold: float = 90.0) -> dict[str, Any] | None:
    """Yesterday-observed persistence baseline on genuinely adjacent dates.

    A coverage-screened station record can have gaps. Reusing the last available
    value over a multi-day gap would not be a ``yesterday`` baseline, so those
    rows are excluded rather than flattering or penalising persistence.
    """
    ordered = paired.sort_values("date").copy()
    dates = pd.to_datetime(ordered["date"])
    adjacent = dates.diff().eq(pd.Timedelta(days=1))
    ordered["model_pm25_ugm3"] = ordered["observed_pm25_ugm3"].shift(1).where(adjacent)
    if ordered.dropna(subset=["model_pm25_ugm3"]).empty:
        return None
    return paired_metrics(ordered, event_threshold)


def make_report(
    observations: pd.DataFrame,
    model: pd.DataFrame,
    *,
    station: str,
    source_url: str,
    event_threshold: float = 90.0,
    min_days_for_validated_claim: int = 30,
    source_provider: str = "CPCB / CAAQMS station observation export",
    source_note: str | None = None,
    input_sha256: str | None = None,
    observation_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pair daily data and make the validation boundary explicit in JSON."""
    paired = observations.merge(model, on="date", how="inner").sort_values("date").reset_index(drop=True)
    model_metrics = paired_metrics(paired, event_threshold)
    report_status = "validated-limited" if model_metrics["n_days"] >= min_days_for_validated_claim else "insufficient-sample"
    # Keep enough rows to audit a report but not a whole government export.
    audit_rows = paired.tail(90).copy()
    audit_rows["date"] = audit_rows["date"].astype(str)
    paired_period = {
        "first_paired_date": str(paired["date"].min()),
        "last_paired_date": str(paired["date"].max()),
        "paired_days": model_metrics["n_days"],
    }
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": report_status,
        "station": station,
        "paired_period": paired_period,
        "observed_source": {
            "provider": source_provider,
            "url": source_url,
            "variable": "daily mean PM2.5 (µg/m³)",
            "note": source_note,
            "input_sha256": input_sha256,
        },
        "observation_quality": observation_quality or {
            "minimum_valid_hourly_values_per_day": None,
            "note": "No CLI coverage screen metadata was supplied.",
        },
        "model_source": {
            "provider": "Open-Meteo Air Quality API / CAMS global archive",
            "variable": "daily mean PM2.5 (µg/m³)",
            "caveat": "Retrospective archive comparison, not an archived operational forecast issued before the observation.",
        },
        "metrics": {
            "cams_archive_vs_cpcb_observation": model_metrics,
            "yesterday_observed_persistence_baseline": persistence_metrics(paired, event_threshold),
        },
        "what_is_validated": (
            "The source PM2.5 concentration series only, against the named CPCB/CAAQMS station and period."
        ),
        "what_is_parameterised": (
            "The heat_aqi_load multiplier is a transparent communication indicator. It is not fitted to PM2.5 "
            "or health outcomes and is not validated by this concentration comparison."
        ),
        "not_reported": "Bare accuracy is intentionally omitted; CSI and HSS are the event-skill measures.",
        "paired_daily_sample": audit_rows.to_dict(orient="records"),
    }


def fetch_model_archive(lat: float, lon: float, start_date: str, end_date: str) -> pd.DataFrame:
    """Retrieve historical CAMS model data for the same station coordinate."""
    zone = [{"zone_id": "validation-station", "zone_name": "Validation station", "lat": lat, "lon": lon}]
    return get_air_quality(zone, start_date=start_date, end_date=end_date, timeout=60)


def write_report(report: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate CAMS PM2.5 against CPCB/CAAQMS observations")
    parser.add_argument("--observations", type=Path, required=True, help="tidy CPCB/CAAQMS CSV with timestamp and PM2.5")
    parser.add_argument("--model", type=Path, help="optional saved CAMS CSV; avoids network")
    parser.add_argument("--lat", type=float, help="station latitude (required without --model)")
    parser.add_argument("--lon", type=float, help="station longitude (required without --model)")
    parser.add_argument("--station", default="NCR validation station")
    parser.add_argument("--source-url", default=DEFAULT_CPCB_SOURCE)
    parser.add_argument("--source-provider", default="CPCB / CAAQMS station observation export")
    parser.add_argument("--source-note", help="provenance note retained verbatim in the report")
    parser.add_argument("--event-threshold", type=float, default=90.0)
    parser.add_argument("--min-days", type=int, default=30)
    parser.add_argument(
        "--min-observation-hours", type=int, default=18,
        help="minimum valid hourly PM2.5 values for a retained daily mean (default: 18)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        source_bytes = args.observations.read_bytes()
        raw_observations = pd.read_csv(args.observations)
        observed_before_screen = tidy_observations(raw_observations)
        observed = quality_screen_observations(observed_before_screen, args.min_observation_hours)
        observation_quality = {
            "minimum_valid_hourly_values_per_day": args.min_observation_hours,
            "daily_rows_with_any_valid_value": int(len(observed_before_screen)),
            "daily_rows_retained": int(len(observed)),
            "daily_rows_excluded_for_coverage": int(len(observed_before_screen) - len(observed)),
            "raw_input_rows": int(len(raw_observations)),
            "note": (
                "Coverage screen is a transparent quality filter for this limited comparison; "
                "it is not a regulatory data-validation certificate."
            ),
        }
        if args.model:
            model = tidy_model(pd.read_csv(args.model))
        else:
            if args.lat is None or args.lon is None:
                parser.error("--lat and --lon are required when --model is not supplied")
            start = str(observed["date"].min())
            end = str(observed["date"].max())
            model = tidy_model(fetch_model_archive(args.lat, args.lon, start, end))
        report = make_report(
            observed, model, station=args.station, source_url=args.source_url,
            event_threshold=args.event_threshold, min_days_for_validated_claim=args.min_days,
            source_provider=args.source_provider, source_note=args.source_note,
            input_sha256=hashlib.sha256(source_bytes).hexdigest(),
            observation_quality=observation_quality,
        )
        path = write_report(report, args.output)
    except Exception as exc:
        print(f"AQI validation failed; no report written: {type(exc).__name__}: {exc}")
        return 2

    metrics = report["metrics"]["cams_archive_vs_cpcb_observation"]
    skill = metrics["event_skill"]
    print(f"wrote {path} — {report['status']} with {metrics['n_days']} paired days")
    print(f"CAMS vs CPCB: MAE {metrics['mae_ugm3']:.2f} µg/m³ · bias {metrics['mean_bias_ugm3']:+.2f} · "
          f"r {metrics['pearson_r']} · CSI {skill['csi']} · HSS {skill['hss']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
