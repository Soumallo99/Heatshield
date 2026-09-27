"""
PHASE 8 — Ward geometry for alert areas
=======================================
A heat warning that names a ward but cannot draw it is a message, not an alert.
CAP areas, the GeoJSON feed and any GIS hand-off all need the ward polygon — so
this module is the single place that knows where the geometry lives.

Where the geometry comes from
-----------------------------
The 141 KMC ward polygons ship with the frontend
(``frontend/web/public/data/kolkata_wards.geojson``, ODbL — datameet
Municipal_Spatial_Data). ``scripts/build_wards.py`` writes the same file to
``data/geo/`` when the offline data build is run, and that path wins if it
exists; otherwise the committed frontend copy is used. ``HS_WARD_GEOJSON``
overrides both.

The honest degradation
----------------------
If no GeoJSON is found, :func:`ward_area` falls back to a CAP ``<circle>``
built from the ward centroid and its real area (r = √(area/π)). That is a
weaker area — a circle over a ward is not the ward — so the payload always
reports which one it used through :func:`geometry_status`. A downstream
consumer must be able to tell the difference, and must never be handed a
silently-faked polygon.

Run standalone:  python -m core.geo
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]

#: Candidate locations, first match wins.
GEOJSON_CANDIDATES: tuple[Path, ...] = (
    BASE_DIR / "data" / "geo" / "kolkata_wards.geojson",       # offline data build
    BASE_DIR / "frontend" / "web" / "public" / "data" / "kolkata_wards.geojson",
)

#: CAP areas are read by humans on small screens and machines on slow links.
#: 141 wards × hundreds of vertices is megabytes of XML, so rings are thinned
#: to this many points. Thinning keeps the vertex order (and so the shape) — it
#: is decimation, not simplification, and it never invents a corner.
MAX_RING_POINTS = 60


def geojson_path() -> Path | None:
    """The ward GeoJSON this process will use, or None if there isn't one."""
    override = os.getenv("HS_WARD_GEOJSON", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.exists() else None
    for candidate in GEOJSON_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


@lru_cache(maxsize=1)
def _load_features() -> tuple[dict[int, list], Path | None]:
    """``{ward_id: [ring, ring, ...]}`` with rings as ``[(lon, lat), ...]``.

    Cached because the file is ~2.4 MB and the API builds a CAP feed on every
    request. The result is immutable by convention — callers must not mutate
    the lists they are handed.
    """
    path = geojson_path()
    if path is None:
        return {}, None

    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)

    rings: dict[int, list] = {}
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        try:
            ward_id = int(properties.get("ward_id"))
        except (TypeError, ValueError):
            continue
        rings[ward_id] = _rings_of(geometry)
    return rings, path


def _rings_of(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """GeoJSON Polygon/MultiPolygon -> a flat list of exterior rings."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        # coordinates = [exterior, hole, hole, ...]; holes are not part of the
        # ward outline for warning purposes.
        return [coordinates[0]] if coordinates else []
    if kind == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    return []


def _shoelace(ring: list[tuple[float, float]]) -> float:
    """Absolute ring area in degrees² — only used to pick the largest part."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _thin(ring: list[tuple[float, float]], max_points: int = MAX_RING_POINTS) -> list[tuple[float, float]]:
    """Keep the shape with at most ``max_points`` vertices, order preserved."""
    if len(ring) <= max_points:
        return list(ring)
    step = len(ring) / max_points
    kept = [ring[min(int(i * step), len(ring) - 1)] for i in range(max_points)]
    return kept


def ward_polygon(ward_id: int, max_points: int = MAX_RING_POINTS) -> list[tuple[float, float]] | None:
    """
    The ward outline as ``[(lon, lat), ...]``, or None if there is no geometry.

    For a MultiPolygon the largest part is used: the warning area is the ward's
    main body, and a CAP ``<area>`` may hold several polygons if a caller wants
    the islands too (see :func:`ward_polygons`).
    """
    rings, _ = _load_features()
    candidates = rings.get(int(ward_id)) or []
    if not candidates:
        return None
    largest = max(candidates, key=_shoelace)
    return _thin(largest, max_points)


def ward_polygons(ward_id: int, max_points: int = MAX_RING_POINTS) -> list[list[tuple[float, float]]]:
    """Every part of a ward, thinned — for consumers that accept multi-part areas."""
    rings, _ = _load_features()
    return [_thin(ring, max_points) for ring in rings.get(int(ward_id)) or []]


def cap_polygon(ward_id: int, max_points: int = MAX_RING_POINTS) -> str | None:
    """
    The ward outline as a CAP 1.2 ``<polygon>`` value:

        whitespace-separated ``lat,lon`` pairs, first pair repeated last.

    Note the latitude-first order — CAP is lat,lon; GeoJSON is lon,lat. Getting
    this backwards is the single most common CAP bug and it silently draws the
    ward in the middle of Somalia.
    """
    ring = ward_polygon(ward_id, max_points)
    if not ring:
        return None
    points = [f"{lat:.5f},{lon:.5f}" for lon, lat in ring]
    if points[0] != points[-1]:
        points.append(points[0])
    return " ".join(points)


def cap_circle(ward_id: int, wards: Any = None) -> str | None:
    """
    CAP 1.2 ``<circle>`` fallback: ``"lat,lon radius"`` with radius in km.

    Radius comes from the ward's real area (r = √(A/π)), so the circle covers
    the right number of square kilometres even though it has the wrong shape.
    """
    lat, lon, area = _centroid_and_area(ward_id, wards)
    if lat is None:
        return None
    radius = math.sqrt(area / math.pi) if area and area > 0 else 1.0
    return f"{lat:.5f},{lon:.5f} {radius:.2f}"


def ward_area(ward_id: int, wards: Any = None) -> dict[str, Any]:
    """
    The best available CAP area for a ward.

    Returns ``{"areaDesc": ..., "polygon": str | None, "circle": str | None,
    "geocode": {...}}``. Exactly one of ``polygon`` / ``circle`` is populated;
    which one says how much to trust the shape.
    """
    polygon = cap_polygon(ward_id)
    geocode = {"KMC_WARD": str(int(ward_id))}
    return {
        "areaDesc": f"KMC Ward {int(ward_id)}, Kolkata",
        "polygon": polygon,
        "circle": None if polygon else cap_circle(ward_id, wards),
        "geocode": geocode,
        "shape": "polygon" if polygon else "circle",
    }


def ward_feature(ward_id: int, properties: dict[str, Any] | None = None,
                 wards: Any = None) -> dict[str, Any]:
    """A GeoJSON ``Feature`` for one ward, carrying ``properties``.

    Falls back to a Point at the centroid when there is no polygon — the feed
    keeps every ward, because a ward that vanishes from the map looks like a
    data outage rather than a geometry gap.
    """
    rings, _ = _load_features()
    candidates = rings.get(int(ward_id)) or []
    if candidates:
        largest = _thin(max(candidates, key=_shoelace))
        # RFC 7946 §3.1.6: a linear ring's first and last positions MUST be
        # identical. Thinning can drop the duplicate closing vertex.
        if largest[0] != largest[-1]:
            largest = [*largest, largest[0]]
        geometry: dict[str, Any] = {
            "type": "Polygon",
            "coordinates": [[[float(x), float(y)] for x, y in largest]],
        }
    else:
        lat, lon, _area = _centroid_and_area(ward_id, wards)
        geometry = {"type": "Point", "coordinates": [float(lon or 0.0), float(lat or 0.0)]}

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {"ward_id": int(ward_id), **(properties or {})},
    }


def _centroid_and_area(ward_id: int, wards: Any = None) -> tuple[float | None, float | None, float | None]:
    if wards is None:
        from core.weather import load_wards        # deferred: core.weather imports pandas

        wards = load_wards()
    row = wards[wards["ward_id"] == int(ward_id)]
    if row.empty:
        return None, None, None
    row = row.iloc[0]
    return float(row["lat"]), float(row["lon"]), float(row.get("area_km2", 0.0) or 0.0)


def geometry_status() -> dict[str, Any]:
    """
    Provenance for the geometry, shipped with every feed.

    ``shape`` is ``polygon`` when real ward outlines are available and
    ``circle`` when the feed is running on centroid fallbacks. A consumer must
    be able to see that difference without reading the source.
    """
    rings, path = _load_features()
    return {
        "source": str(path) if path else None,
        "wards_with_geometry": len(rings),
        "shape": "polygon" if rings else "circle",
        "max_ring_points": MAX_RING_POINTS,
        "note": (
            "Real KMC ward polygons (ODbL, datameet/Municipal_Spatial_Data). "
            "When unavailable the feed falls back to centroid circles sized from "
            "each ward's real area — a circle is not a ward outline."
        ),
    }


def clear_cache() -> None:
    """Drop the cached geometry — used by tests that repoint HS_WARD_GEOJSON."""
    _load_features.cache_clear()


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    status = geometry_status()
    print("Ward geometry")
    print("=" * 68)
    for key, value in status.items():
        print(f"  {key:<22} {value}")

    polygon = cap_polygon(1)
    print("\nWard 1 as a CAP <polygon> (first 120 chars):")
    print(" ", (polygon or "<none>")[:120])

    feature = ward_feature(1, {"risk_score": 71.2})
    print("\nWard 1 as a GeoJSON Feature (geometry head):")
    print(" ", json.dumps(feature["geometry"])[:120])
    print("\nWard 1 area record:", {k: (str(v)[:60] if v else v)
                                    for k, v in ward_area(1).items()})
