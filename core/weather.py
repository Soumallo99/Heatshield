"""
PHASE 1 — Weather Data Pipeline
===============================
Fetches 3-5 day hourly forecasts (Temp, RH, Dewpoint, Wind, Solar Radiation, Cloud)
from Open-Meteo for ALL wards in one batched request, returns a tidy DataFrame,
and caches to disk so we don't hammer the free API during the hackathon.

Run standalone:        python -m core.weather
Use in code:           from core.weather import get_forecast
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable, Sequence

import pandas as pd
import requests

from core import config

# --------------------------------------------------------------------------- #
# 0. Ward registry
# --------------------------------------------------------------------------- #

DEMOGRAPHIC_COLS = [
    "population",
    "pop_density_km2",
    "elderly_pct",
    "slum_pct",
    "green_cover_pct",
    "outdoor_worker_pct",
]


def load_wards(path: Path | str = config.WARDS_CSV) -> pd.DataFrame:
    """Ward centroids + mock demographics (feeds Phase 3 risk model)."""
    df = pd.read_csv(path)
    missing = {"ward_id", "ward_name", "lat", "lon"} - set(df.columns)
    if missing:
        raise ValueError(f"wards.csv missing required columns: {missing}")
    return df


# --------------------------------------------------------------------------- #
# 1. Fetch (batched, retrying)
# --------------------------------------------------------------------------- #

def _chunks(seq: Sequence, n: int) -> Iterable[Sequence]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class UpstreamError(RuntimeError):
    """Open-Meteo could not be reached, or refused to answer.

    A distinct type so the API can answer 503 ("the weather service is
    unavailable right now") rather than 500 ("this server has a bug"). Those two
    mean very different things to whoever is reading the screen, and only one of
    them is our fault. `app/main.py` registers the handler.
    """


def fetch_raw(
    lats: Sequence[float],
    lons: Sequence[float],
    forecast_days: int = config.FORECAST_DAYS,
    past_days: int = config.PAST_DAYS,
    timeout: int = 30,
    retries: int = 3,
) -> list[dict]:
    """
    One HTTP call per batch of <= BATCH_SIZE coordinates.
    Open-Meteo returns a list (one dict per coordinate) when >1 coord is passed.
    No API key required for non-commercial use.
    """
    if len(lats) != len(lons):
        raise ValueError("lats and lons must be the same length")

    out: list[dict] = []
    for lat_chunk, lon_chunk in zip(_chunks(lats, config.BATCH_SIZE), _chunks(lons, config.BATCH_SIZE)):
        params = {
            "latitude": ",".join(str(round(float(x), 5)) for x in lat_chunk),
            "longitude": ",".join(str(round(float(x), 5)) for x in lon_chunk),
            "hourly": ",".join(config.HOURLY_VARS),
            "past_days": past_days,
            "forecast_days": forecast_days,
            "timezone": config.TIMEZONE,
            "wind_speed_unit": "kmh",
        }
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                r = requests.get(config.OPEN_METEO_URL, params=params, timeout=timeout)
                r.raise_for_status()
                payload = r.json()
                out.extend(payload if isinstance(payload, list) else [payload])
                break
            except Exception as exc:  # network blip / rate limit -> back off
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise UpstreamError(
                f"Open-Meteo fetch failed after {retries} attempts: {last_err}"
            ) from last_err
    return out


# --------------------------------------------------------------------------- #
# 2. Normalise -> tidy DataFrame
# --------------------------------------------------------------------------- #

RENAME = {
    "temperature_2m": "temp_c",
    "relative_humidity_2m": "rh_pct",
    "dew_point_2m": "dewpoint_c",
    "wind_speed_10m": "wind_kmh",
    "shortwave_radiation": "solar_wm2",
    "direct_normal_irradiance": "dni_wm2",
    "cloud_cover": "cloud_pct",
    "apparent_temperature": "apparent_temp_c",
}


def to_dataframe(raw: list[dict], wards: pd.DataFrame) -> pd.DataFrame:
    """Explode batched JSON -> long/tidy frame, one row per (ward, hour)."""
    frames = []
    for res, (_, ward) in zip(raw, wards.iterrows()):
        hourly = res.get("hourly", {})
        df = pd.DataFrame(hourly).rename(columns=RENAME)
        df["ward_id"] = ward["ward_id"]
        df["ward_name"] = ward["ward_name"]
        df["lat"] = res["latitude"]
        df["lon"] = res["longitude"]
        df["elevation_m"] = res.get("elevation")
        frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    out = out.rename(columns={"time": "timestamp_local"})
    out["timestamp_local"] = pd.to_datetime(out["timestamp_local"])
    out["fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0)

    ordered = [
        "ward_id", "ward_name", "lat", "lon", "elevation_m", "timestamp_local",
        "temp_c", "rh_pct", "dewpoint_c", "wind_kmh",
        "solar_wm2", "dni_wm2", "cloud_pct", "apparent_temp_c", "fetched_at",
    ]
    return out[[c for c in ordered if c in out.columns]]


# --------------------------------------------------------------------------- #
# 3. Cache layer (TTL)
# --------------------------------------------------------------------------- #

def _cache_path() -> Path:
    # parquet if pyarrow is installed, else pickle (zero extra deps, still fast)
    try:
        import pyarrow  # noqa: F401
        return config.CACHE_DIR / f"forecast_{config.FORECAST_DAYS}d.parquet"
    except ImportError:
        return config.CACHE_DIR / f"forecast_{config.FORECAST_DAYS}d.pkl"


def save_cache(df: pd.DataFrame, raw: list[dict] | None = None) -> None:
    p = _cache_path()
    if p.suffix == ".parquet":
        df.to_parquet(p, index=False)
    else:
        df.to_pickle(p)
    if raw is not None:  # keep raw JSON for debugging / reproducibility
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        (config.RAW_DIR / f"open_meteo_{stamp}.json").write_text(json.dumps(raw))


# How old a cached fetch may be when we fall back to it after a FAILED live
# pull. A week: beyond that a "forecast" is a history lesson, and serving it
# silently would mislead. A failed fetch + no cache still raises.
STALE_FALLBACK_MIN = 60 * 24 * 7

# After a failed live pull, don't re-attempt the network on every request for
# this long (the retry/backoff in fetch_raw costs ~10 s; a dashboard refresh
# fires several endpoints at once). The stale cache serves instantly meanwhile,
# and we still re-probe the network every couple of minutes so recovery is
# automatic when connectivity returns.
FETCH_FAIL_COOLDOWN_S = 120.0
_fetch_fail_until = 0.0


def load_cache(max_age_min: int = config.CACHE_TTL_MIN) -> pd.DataFrame | None:
    p = _cache_path()
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > max_age_min * 60:
        return None
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_pickle(p)


# --------------------------------------------------------------------------- #
# 4. Public entry point
# --------------------------------------------------------------------------- #

def get_forecast(
    wards: pd.DataFrame | None = None,
    forecast_days: int = config.FORECAST_DAYS,
    use_cache: bool = True,
    save: bool = True,
) -> pd.DataFrame:
    """
    The ONE function the rest of the app calls.

    Returns tidy DataFrame:
        ward_id, ward_name, lat, lon, elevation_m, timestamp_local,
        temp_c, rh_pct, dewpoint_c, wind_kmh, solar_wm2, dni_wm2,
        cloud_pct, apparent_temp_c, fetched_at
    """
    global _fetch_fail_until

    if use_cache:
        cached = load_cache()
        if cached is not None:
            return cached
        # Inside the failure cooldown, skip the slow doomed fetch entirely.
        if time.time() < _fetch_fail_until:
            stale = load_cache(max_age_min=STALE_FALLBACK_MIN)
            if stale is not None and not stale.empty:
                return stale

    wards = load_wards() if wards is None else wards
    try:
        raw = fetch_raw(
            wards["lat"].tolist(),
            wards["lon"].tolist(),
            forecast_days=forecast_days,
        )
    except Exception:
        if not use_cache:
            raise  # scripts.refresh (live) must fail loudly, never serve stale
        _fetch_fail_until = time.time() + FETCH_FAIL_COOLDOWN_S
        # Offline-first: a warning system that 500s the moment the network
        # drops is useless exactly when it is needed. Serve the last REAL
        # fetch, however old, instead of an error. `fetched_at` rides along
        # in the frame, so the UI can still say how old the data is — and
        # scripts.refresh (live mode) remains the way to get current weather.
        stale = load_cache(max_age_min=STALE_FALLBACK_MIN)
        if stale is None or stale.empty:
            raise
        return stale

    df = to_dataframe(raw, wards)
    df = df.dropna(subset=["temp_c", "rh_pct"]).reset_index(drop=True)

    if save:
        save_cache(df, raw)
        df.to_csv(config.PROCESSED_DIR / "forecast_hourly.csv", index=False)
    return df


# --------------------------------------------------------------------------- #
# 5. Handy helpers for Phases 2-4
# --------------------------------------------------------------------------- #

def daily_peak(df: pd.DataFrame) -> pd.DataFrame:
    """Daily per-ward peaks: Tmax, Tmin, max solar, mean RH. Feeds the map + alerts."""
    d = df.copy()
    d["date"] = d["timestamp_local"].dt.date
    return (
        d.groupby(["ward_id", "ward_name", "date"], as_index=False)
        .agg(
            tmax_c=("temp_c", "max"),
            tmin_c=("temp_c", "min"),
            rh_mean_pct=("rh_pct", "mean"),
            rh_max_pct=("rh_pct", "max"),
            wind_mean_kmh=("wind_kmh", "mean"),
            solar_max_wm2=("solar_wm2", "max"),
        )
        .sort_values(["date", "ward_id"])
        .reset_index(drop=True)
    )


def hottest_hours(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    return df.nlargest(top_n, "temp_c")[
        ["ward_name", "timestamp_local", "temp_c", "rh_pct", "wind_kmh", "solar_wm2"]
    ]


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    pd.set_option("display.width", 160)
    wards = load_wards()
    print(f"Fetching {config.FORECAST_DAYS}-day forecast for {len(wards)} wards...")

    t0 = time.time()
    df = get_forecast(wards, use_cache=False)
    print(f"OK  {len(df):,} rows x {df.shape[1]} cols in {time.time() - t0:.2f}s")
    print(f"Window: {df.timestamp_local.min()}  ->  {df.timestamp_local.max()} ({config.TIMEZONE})")

    print("\nDaily peaks (first 5):")
    print(daily_peak(df).head())

    print("\nHottest hours overall:")
    print(hottest_hours(df).to_string(index=False))

    print(f"\nSaved -> {config.PROCESSED_DIR / 'forecast_hourly.csv'}")


# --------------------------------------------------------------------------- #
# 5. Historical archive (for hindcasting / skill evaluation)
# --------------------------------------------------------------------------- #

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_archive_raw(
    lats: Sequence[float],
    lons: Sequence[float],
    start_date: str,
    end_date: str,
    timeout: int = 60,
    retries: int = 3,
) -> list[dict]:
    """
    Pull OBSERVED/reanalysed weather from the Open-Meteo archive API.

    Same keyless, batched shape as the forecast endpoint but keyed by an explicit
    date range, which is what makes hindcasting possible: we can ask "what
    actually happened on 12 August?" and score yesterday's forecast against it.

    The archive lags the present by a few days (reanalysis needs to settle), so
    callers should end the range a few days before today.
    """
    if len(lats) != len(lons):
        raise ValueError("lats and lons must be the same length")

    out: list[dict] = []
    for lat_chunk, lon_chunk in zip(_chunks(lats, config.BATCH_SIZE),
                                    _chunks(lons, config.BATCH_SIZE)):
        params = {
            "latitude": ",".join(str(round(float(x), 5)) for x in lat_chunk),
            "longitude": ",".join(str(round(float(x), 5)) for x in lon_chunk),
            "hourly": ",".join(config.HOURLY_VARS),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": config.TIMEZONE,
            "wind_speed_unit": "kmh",
        }
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                r = requests.get(ARCHIVE_URL, params=params, timeout=timeout)
                r.raise_for_status()
                payload = r.json()
                out.extend(payload if isinstance(payload, list) else [payload])
                break
            except Exception as exc:                    # noqa: BLE001
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise UpstreamError(
                f"Open-Meteo archive fetch failed after {retries} attempts: {last_err}"
            ) from last_err
    return out


def get_archive(wards: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """Observed hourly weather for every ward across an explicit date range."""
    raw = fetch_archive_raw(wards["lat"].tolist(), wards["lon"].tolist(),
                            start_date, end_date)
    return to_dataframe(raw, wards)
