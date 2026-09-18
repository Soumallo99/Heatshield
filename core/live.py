"""
Live tracking layers for the operations globe — keyless, opt-in, additive.

Three layers, three public keyless upstreams:

  aircraft    adsb.lol      ADS-B positions around a point (volunteer feed)
  earthquakes USGS          the GeoJSON summary feeds (hour / day / week)
  satellites  CelesTrak     GP element sets (OMM JSON) for one orbital group

What this module is NOT:

  * It is not a second data pipeline. Nothing here feeds the risk model, the
    alerts or the warning system. The globe is an extra view of the same city;
    these layers are context an operator can glance at, and the app is
    completely usable — and completely honest — with all three switched off.
  * It is not a browser-facing host. The browser never talks to adsb.lol, USGS
    or CelesTrak: it asks this process through `/api/live/*` and this process
    does the fetching. That is what keeps the promise in THIRD-PARTY.md
    ("no third-party host is reached from the browser") true while the globe
    can still show something live.
  * It is not allowed to invent data. An upstream that does not answer produces
    `available: false`, a `notice` naming the upstream and the reason, and an
    empty `data` list. Never a synthetic aircraft, never a smoothed position.

Failure is *data* here, not an error, and the difference from the weather
routes is deliberate. `/forecast` answers 503 when Open-Meteo is unreachable
because the forecast IS the product: without it the numbers on screen cannot
exist. A tracking layer is additive — the globe, the choropleth and every
number on it are still correct without it — so the route answers 200 and says
so in the payload. A 503 would make the whole layer look like a bug in
HeatShield rather than a third party being unreachable.

Run standalone:   python -m core.live            # hits the real upstreams
Use in code:      from core import live
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import requests

from core import config

# --------------------------------------------------------------------------- #
# 0. Sources — named, licensed, and keyless
# --------------------------------------------------------------------------- #

#: The contact string sent to every upstream. adsb.lol and the USGS both ask
#: for an identifiable agent; this one is a real project URL and contains no
#: credential, because there is no credential to send.
USER_AGENT = "HeatShield/0.1 (+https://github.com/Soumallo99/Heatshield)"

ADSB_URL = "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}"
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_{window}.geojson"
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"

SOURCES = {
    "aircraft": {
        "name": "adsb.lol",
        "url": "https://api.adsb.lol",
        "licence": "Public ADS-B aggregation; community/volunteer feeder network, no key",
        "attribution": "Aircraft positions: adsb.lol (community ADS-B feed), keyless",
        "docs": "https://api.adsb.lol",
    },
    "earthquakes": {
        "name": "USGS Earthquake Hazards Program",
        "url": "https://earthquake.usgs.gov/fdsnws/event/1/",
        "licence": "US Government work, public domain",
        "attribution": "Earthquakes: USGS Earthquake Hazards Program (public domain)",
        "docs": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php",
    },
    "satellites": {
        "name": "CelesTrak",
        "url": "https://celestrak.org",
        "licence": "Public GP (TLE/OMM) element sets; see celestrak.org for terms",
        "attribution": "Satellite orbits: CelesTrak GP element sets, propagated with satellite.js (MIT)",
        "docs": "https://celestrak.org/NORAD/documentation/gp-data-formats.php",
    },
}

# The satellite groups an operator may ask for. A whitelist, not a free string:
# `?group=` reaches CelesTrak's query interface, and an unbounded parameter
# would let a caller make this server request anything that host serves.
SATELLITE_GROUPS = (
    "stations",    # crewed stations (ISS, Tiangong) — the default glance view
    "weather",
    "geo",
    "science",
    "gps-ops",
    "noaa",
    "resource",
)

# USGS summary feeds, smallest first. `all_month` is deliberately absent: it is
# a multi-megabyte feed of low-magnitude events, and a glance layer that costs
# that much per refresh is a layer nobody should switch on.
EARTHQUAKE_WINDOWS = ("hour", "day", "week")

#: A position fix older than this is not a live track. adsb.lol reports
#: `seen_pos` (seconds since the last position message); a feeder that has gone
#: quiet would otherwise leave an aircraft frozen mid-air on the globe, which
#: reads as a real aircraft sitting still at 38,000 ft.
AIRCRAFT_MAX_FIX_AGE_S = 120.0

#: Feet (what ADS-B reports) to metres (what everything else in HeatShield uses).
FEET_TO_METRES = 0.3048


class LiveSourceError(RuntimeError):
    """A live upstream could not be reached, or answered with something unusable.

    Raised inside this module only; the routes turn it into an honest
    `available: false` payload. It exists as a type so a caller can tell "the
    third party is unreachable" from "the input was wrong".
    """


# --------------------------------------------------------------------------- #
# 1. Fetch
# --------------------------------------------------------------------------- #

def _sleep_between_attempts(attempt: int, retries: int) -> None:
    """Back off *between* attempts only — never after the last one.

    A retry loop that sleeps after its final attempt makes every failure pay
    for a nap it cannot benefit from, and in a test run that is the difference
    between a fast suite and a slow one.
    """
    if attempt + 1 < retries:
        time.sleep(0.25 * (attempt + 1))


def fetch_json(url: str, *, params: dict | None = None,
               timeout: float | None = None, retries: int | None = None) -> object:
    """GET `url` and parse the JSON body, retrying a couple of times.

    Short deadline and few retries, unlike the weather pipeline: these layers
    are decoration on a warning system, and an operator waiting eight seconds
    for an aircraft icon has been failed by the design, not by the network.
    """
    timeout = config.LIVE_TIMEOUT_S if timeout is None else timeout
    retries = max(1, config.LIVE_RETRIES if retries is None else retries)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:                      # noqa: BLE001 - named below
            last = exc
            _sleep_between_attempts(attempt, retries)
    raise LiveSourceError(f"{url} did not answer: {last}")


# --------------------------------------------------------------------------- #
# 2. Envelope + the small success-only cache
# --------------------------------------------------------------------------- #

def _env(layer: str, *, rows: list[dict], available: bool, notice: str | None = None,
         truncated: bool = False, fetched_at: str | None = None,
         window: dict | None = None) -> dict:
    """One shape for all three layers, available or not.

    `source` always names the upstream, even when it failed: an operator who
    sees "unavailable" needs to know whose status page to look at.
    """
    return {
        "layer": layer,
        "available": available,
        "count": len(rows),
        "truncated": truncated,
        "fetched_at": fetched_at or _utcnow(),
        "window": window or {},
        "source": SOURCES[layer],
        "notice": notice,
        "data": rows,
    }


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Successful payloads only, keyed by layer + the query that produced them. A
# failure is never cached: an upstream that is down for thirty seconds must not
# stay "down" on screen for a minute after it recovers.
_CACHE: dict[str, tuple[float, dict]] = {}


def clear_cache() -> None:
    """Forget every cached live payload (tests, and a forced refresh)."""
    _CACHE.clear()


def _remember(key: str, payload: dict, ttl: float) -> None:
    if ttl > 0 and payload.get("available"):
        _CACHE[key] = (time.monotonic(), payload)


def _recall(key: str, ttl: float) -> dict | None:
    if ttl <= 0:
        return None
    entry = _CACHE.get(key)
    if entry is None:
        return None
    stored_at, payload = entry
    if time.monotonic() - stored_at > ttl:
        _CACHE.pop(key, None)
        return None
    # The payload is reused verbatim, so its `fetched_at` is the upstream
    # fetch time, not the time of this request — which is what "how old is
    # this?" on screen should mean.
    return payload


def _disabled(layer: str) -> dict:
    """The payload when this deployment has the live layers turned off."""
    return _env(
        layer,
        rows=[],
        available=False,
        notice=("Live tracking layers are turned off on this deployment "
                "(HS_LIVE_LAYERS=0). Nothing is shown rather than a guess."),
    )


def _failed(layer: str, exc: Exception, *, window: dict | None = None) -> dict:
    """The payload when an upstream did not cooperate. Never data, never a 500."""
    reason = str(exc)
    if len(reason) > 300:
        reason = reason[:300] + "…"
    return _env(layer, rows=[], available=False, window=window,
                notice=f"{SOURCES[layer]['name']} is unavailable right now — {reason}. "
                       "Nothing is shown rather than a guess.")


# --------------------------------------------------------------------------- #
# 3. Aircraft
# --------------------------------------------------------------------------- #

def _num(value) -> float | None:
    """JSON numbers only. 'ground' and None are both "no number here"."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # NaN has no place in a JSON response, and a silent NaN in a coordinate
    # would draw an entity somewhere unplaceable.
    return None if math.isnan(out) else out


def normalise_aircraft(payload, *, limit: int) -> tuple[list[dict], bool]:
    """adsb.lol `/v2/point` -> rows the globe can draw, oldest fixes dropped.

    Rows without a usable position are dropped rather than defaulted to 0,0 —
    an aircraft drawn at the Gulf of Guinea because its transponder did not
    report a fix yet is worse than an aircraft not drawn.
    """
    rows: list[dict] = []
    seen = 0
    for entry in (payload or {}).get("ac") or []:
        seen += 1
        lat = _num(entry.get("lat"))
        lon = _num(entry.get("lon"))
        if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        age = _num(entry.get("seen_pos")) or 0.0
        if age > AIRCRAFT_MAX_FIX_AGE_S:
            continue
        altitude = entry.get("alt_baro")
        on_ground = altitude == "ground"
        alt_ft = None if on_ground else _num(altitude)
        callsign = (entry.get("flight") or "").strip() or None
        rows.append({
            "icao": entry.get("hex"),
            "callsign": callsign,
            "registration": (entry.get("r") or "").strip() or None,
            "type": (entry.get("t") or "").strip() or None,
            "lat": lat,
            "lon": lon,
            "alt_m": None if alt_ft is None else round(alt_ft * FEET_TO_METRES, 1),
            "on_ground": on_ground,
            "speed_kts": _num(entry.get("gs")),
            "heading_deg": _num(entry.get("track")),
            "seen_s": round(age, 1),
        })
    # Closest first is the wrong order for a glance layer; highest first reads
    # as "the traffic above you", which is the question an operator has.
    rows.sort(key=lambda row: row["alt_m"] if row["alt_m"] is not None else -1, reverse=True)
    kept = rows[:limit]
    return kept, len(rows) > len(kept)


def aircraft(lat: float = 22.5726, lon: float = 88.3639, radius_nm: int = 250,
             limit: int = 150) -> dict:
    """Live ADS-B traffic around a point. Kolkata by default, 250 nm radius."""
    window = {"lat": lat, "lon": lon, "radius_nm": radius_nm}
    if not config.LIVE_ENABLED:
        return _disabled("aircraft")
    key = f"aircraft:{lat:.3f}:{lon:.3f}:{radius_nm}:{limit}"
    cached = _recall(key, config.LIVE_AIRCRAFT_TTL_S)
    if cached is not None:
        return cached
    try:
        payload = fetch_json(ADSB_URL.format(lat=f"{lat:.4f}", lon=f"{lon:.4f}",
                                             radius=int(radius_nm)))
        rows, truncated = normalise_aircraft(payload, limit=limit)
    except LiveSourceError as exc:
        return _failed("aircraft", exc, window=window)
    out = _env("aircraft", rows=rows, available=True, truncated=truncated, window=window)
    _remember(key, out, config.LIVE_AIRCRAFT_TTL_S)
    return out


# --------------------------------------------------------------------------- #
# 4. Earthquakes
# --------------------------------------------------------------------------- #

def normalise_earthquakes(payload, *, limit: int, min_mag: float) -> tuple[list[dict], bool]:
    """A USGS GeoJSON summary feed -> rows, strongest and most recent first."""
    rows: list[dict] = []
    for feature in (payload or {}).get("features") or []:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        # Non-earthquake entries (quarry blasts, ice quakes) carry a different
        # `type`; they are real events but they are not this layer's subject.
        if properties.get("type") not in (None, "earthquake"):
            continue
        magnitude = _num(properties.get("mag"))
        if magnitude is None or magnitude < min_mag or len(coordinates) < 2:
            continue
        lat, lon = _num(coordinates[1]), _num(coordinates[0])
        if lat is None or lon is None:
            continue
        stamp = properties.get("time")
        rows.append({
            "id": feature.get("id"),
            "mag": magnitude,
            "mag_type": properties.get("magType"),
            "place": properties.get("place"),
            "lat": lat,
            "lon": lon,
            "depth_km": _num(coordinates[2]) if len(coordinates) > 2 else None,
            "time_utc": (datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
                         .replace(microsecond=0).isoformat()) if stamp else None,
            "tsunami": bool(properties.get("tsunami")),
            "url": properties.get("url"),
        })
    rows.sort(key=lambda row: (row["mag"], row["time_utc"] or ""), reverse=True)
    kept = rows[:limit]
    return kept, len(rows) > len(kept)


def earthquakes(window: str = "day", min_mag: float = 2.5, limit: int = 200) -> dict:
    """USGS events for the last hour/day/week, at or above `min_mag`."""
    bounds = {"window": window, "min_mag": min_mag}
    if not config.LIVE_ENABLED:
        return _disabled("earthquakes")
    if window not in EARTHQUAKE_WINDOWS:
        # Unreachable through the route (FastAPI enforces the Literal); kept
        # because this is also a library function.
        raise ValueError(f"window must be one of {EARTHQUAKE_WINDOWS}, not {window!r}")
    key = f"earthquakes:{window}:{min_mag}:{limit}"
    cached = _recall(key, config.LIVE_EARTHQUAKE_TTL_S)
    if cached is not None:
        return cached
    try:
        payload = fetch_json(USGS_URL.format(window=window))
        rows, truncated = normalise_earthquakes(payload, limit=limit, min_mag=min_mag)
    except LiveSourceError as exc:
        return _failed("earthquakes", exc, window=bounds)
    out = _env("earthquakes", rows=rows, available=True, truncated=truncated, window=bounds)
    _remember(key, out, config.LIVE_EARTHQUAKE_TTL_S)
    return out


# --------------------------------------------------------------------------- #
# 5. Satellites
# --------------------------------------------------------------------------- #

#: CelesTrak's OMM JSON field -> the snake_case name this API serves. The
#: browser maps it back for satellite.js (see src/globe/liveData.js), which is
#: a deliberate two-step: the payload stays in HeatShield's own naming, so a
#: rename upstream is one line here instead of a change in the UI.
OMM_FIELDS = {
    "OBJECT_NAME": "name",
    "OBJECT_ID": "object_id",
    "NORAD_CAT_ID": "norad_id",
    "EPOCH": "epoch",
    "MEAN_MOTION": "mean_motion",
    "ECCENTRICITY": "eccentricity",
    "INCLINATION": "inclination",
    "RA_OF_ASC_NODE": "ra_of_asc_node",
    "ARG_OF_PERICENTER": "arg_of_pericenter",
    "MEAN_ANOMALY": "mean_anomaly",
    "BSTAR": "bstar",
    "MEAN_MOTION_DOT": "mean_motion_dot",
    "MEAN_MOTION_DDOT": "mean_motion_ddot",
    "REV_AT_EPOCH": "rev_at_epoch",
}


def normalise_satellites(payload, *, limit: int, group: str) -> tuple[list[dict], bool]:
    """CelesTrak GP (OMM JSON) -> rows. Positions are NOT computed here.

    Where a satellite *is* depends on when you ask, and the globe asks several
    times a second while it renders. Propagating here would mean one upstream
    round trip per frame; instead the element set is sent once and the browser
    runs SGP4 (satellite.js) locally. The numbers are the same either way —
    this is a bandwidth and politeness decision, not an accuracy one.
    """
    rows: list[dict] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        row = {"group": group}
        for upstream, ours in OMM_FIELDS.items():
            value = entry.get(upstream)
            row[ours] = value
        # An element set without a name and a catalogue number cannot be
        # labelled on screen, and an unlabelled dot is noise.
        if not row.get("name") or row.get("norad_id") is None:
            continue
        if _num(row.get("mean_motion")) is None or _num(row.get("inclination")) is None:
            continue
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("name")))
    kept = rows[:limit]
    return kept, len(rows) > len(kept)


def satellites(group: str = "stations", limit: int = 60) -> dict:
    """CelesTrak GP element sets for one group (`SATELLITE_GROUPS`)."""
    bounds = {"group": group}
    if not config.LIVE_ENABLED:
        return _disabled("satellites")
    if group not in SATELLITE_GROUPS:
        raise ValueError(f"group must be one of {SATELLITE_GROUPS}, not {group!r}")
    key = f"satellites:{group}:{limit}"
    cached = _recall(key, config.LIVE_SATELLITE_TTL_S)
    if cached is not None:
        return cached
    try:
        payload = fetch_json(CELESTRAK_URL, params={"GROUP": group, "FORMAT": "json"})
        rows, truncated = normalise_satellites(payload, limit=limit, group=group)
    except LiveSourceError as exc:
        return _failed("satellites", exc, window=bounds)
    out = _env("satellites", rows=rows, available=True, truncated=truncated, window=bounds)
    _remember(key, out, config.LIVE_SATELLITE_TTL_S)
    return out


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # A real end-to-end probe, which is the only honest way to check that the
    # upstreams still answer. Nothing in the test suite needs the network; this
    # does, on purpose.
    for label, call in (
        ("aircraft", lambda: aircraft()),
        ("earthquakes", lambda: earthquakes()),
        ("satellites", lambda: satellites()),
    ):
        try:
            payload = call()
            print(f"{label:12s} available={payload['available']} "
                  f"count={payload['count']} truncated={payload['truncated']} "
                  f"notice={payload['notice']}")
        except Exception as exc:                      # noqa: BLE001
            print(f"{label:12s} raised {type(exc).__name__}: {exc}")
