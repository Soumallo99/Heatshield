"""
Build the REAL ward dataset from open sources.

Sources (all free, all citable):
  * Ward polygons  — datameet/Municipal_Spatial_Data, KMC 141 wards (ODbL)
  * Population     — Wikidata, stated-in Census of India 2011 (WB) Kolkata District PCA
                     (verified: ward populations sum to 4,496,694 = official KMC 2011 total)
  * Green / water  — OpenStreetMap via Overpass (ODbL)
  * Buildings      — OpenStreetMap via Overpass (ODbL), used as an impervious-surface proxy

Writes:
  data/wards.csv               model input (real values only)
  data/geo/kolkata_wards.geojson   display geometry with properties baked in

Run:  python scripts/build_wards.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

BASE = Path(__file__).resolve().parents[1]
GEO = BASE / "data" / "geo"

WARDS_SRC = GEO / "kolkata_datameet.json"
GREEN_SRC = GEO / "green.json"
BUILD_SRC = GEO / "buildings.json"
POP_SRC = BASE / "data" / "wikidata_kmc_population.json"

# OSM tags we accept as vegetation (pitch/playground excluded — often paved or synthetic)
GREEN_TAGS = {
    ("leisure", "park"), ("leisure", "garden"), ("leisure", "golf_course"),
    ("leisure", "nature_reserve"),
    ("landuse", "grass"), ("landuse", "forest"), ("landuse", "meadow"),
    ("landuse", "village_green"), ("landuse", "recreation_ground"),
    ("natural", "wood"), ("natural", "scrub"), ("natural", "grassland"),
}
WATER_TAGS = {("natural", "water"), ("natural", "wetland")}


def load_population() -> pd.DataFrame:
    rows = json.load(open(POP_SRC))["results"]["bindings"]
    out = []
    for r in rows:
        label = r["wLabel"]["value"]
        m = re.search(r"Ward No\.\s*(\d+)", label)
        borough = r.get("boroughLabel", {}).get("value", "")
        bm = re.search(r"Borough No\.\s*(\d+)", borough)
        if not m:
            continue
        out.append({
            "ward_id": int(m.group(1)),
            "ward_name": f"Ward {int(m.group(1))}",
            "borough": int(bm.group(1)) if bm else None,
            "population": int(float(r["pop"]["value"])),
        })
    return pd.DataFrame(out).sort_values("ward_id").reset_index(drop=True)


def geod_area_km2(geom) -> float:
    """Geodesic area on WGS84 — correct at this latitude, unlike degree² math."""
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    return abs(geod.geometry_area_perimeter(geom)[0]) / 1e6


def main() -> int:
    for p in (WARDS_SRC, POP_SRC):
        if not p.exists():
            print(f"missing {p} — run the fetch commands in README first", file=sys.stderr)
            return 1

    print("loading ward polygons…")
    wards_gj = json.load(open(WARDS_SRC))
    pop = load_population()
    print(f"  {len(wards_gj['features'])} polygons, {len(pop)} population records")

    polys, ids = [], []
    for f in wards_gj["features"]:
        w = f["properties"].get("WARD")
        w = int(re.sub(r"\D", "", str(w)) or 0)
        g = shape(f["geometry"])
        if g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        polys.append(g)
        ids.append(w)
    print(f"  parsed {len(polys)} ward geometries")

    # ---------------------------------------------------------------- green / water
    green_polys, water_polys = [], []
    if GREEN_SRC.exists():
        print("loading OSM green/water…")
        gj = json.load(open(GREEN_SRC))
        for el in gj.get("elements", []):
            tags = el.get("tags", {})
            if not el.get("geometry"):
                continue
            key = next(((k, tags[k]) for k in ("leisure", "landuse", "natural") if k in tags), None)
            if key is None:
                continue
            try:
                geom = shape({"type": "Polygon", "coordinates": [[(p["lon"], p["lat"]) for p in el["geometry"]]]})
            except Exception:
                continue
            if not geom.is_valid:
                geom = geom.buffer(0)
            if key in WATER_TAGS:
                water_polys.append(geom)
            elif key in GREEN_TAGS:
                green_polys.append(geom)
        print(f"  {len(green_polys)} green, {len(water_polys)} water polygons")

    green_tree = STRtree(green_polys) if green_polys else None
    water_tree = STRtree(water_polys) if water_polys else None

    # ---------------------------------------------------------------- buildings
    bpts = None
    if BUILD_SRC.exists():
        print("loading OSM buildings (100 MB, be patient)…")
        gj = json.load(open(BUILD_SRC))
        lons, lats = [], []
        for el in gj.get("elements", []):
            c = el.get("center")
            if c:
                lons.append(c["lon"])
                lats.append(c["lat"])
        bpts = np.column_stack([np.asarray(lons), np.asarray(lats)])
        del gj
        print(f"  {len(bpts):,} building centroids")
    # shapely 2.x STRtree.query() returns INDICES into the input list, not geometries
    bpts_geoms = [Point(x, y) for x, y in bpts] if bpts is not None else None
    btree = STRtree(bpts_geoms) if bpts_geoms else None

    # ---------------------------------------------------------------- per-ward metrics
    print("computing per-ward metrics…")
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    rows = []
    for g, wid in zip(polys, ids):
        area_km2 = abs(geod.geometry_area_perimeter(g)[0]) / 1e6
        c = g.representative_point()

        def covered(tree, pool):
            if tree is None:
                return 0.0
            tot = 0.0
            for cand in tree.query(g):
                inter = g.intersection(pool[int(cand)] if isinstance(cand, (int, np.integer)) else cand)
                if not inter.is_empty:
                    tot += abs(geod.geometry_area_perimeter(inter)[0]) / 1e6
            return tot

        green_km2 = covered(green_tree, green_polys)
        water_km2 = covered(water_tree, water_polys)

        n_b = 0
        if btree is not None:
            for cand in btree.query(g):
                pt = bpts_geoms[int(cand)] if isinstance(cand, (int, np.integer)) else cand
                if g.contains(pt):
                    n_b += 1

        rows.append({
            "ward_id": wid,
            "lat": round(c.y, 6),
            "lon": round(c.x, 6),
            "area_km2": round(area_km2, 4),
            "green_km2": round(green_km2, 4),
            "water_km2": round(water_km2, 4),
            "building_count": n_b,
        })
    print(f"  done {len(rows)} wards")

    df = pd.DataFrame(rows).merge(pop, on="ward_id", how="left")
    df["population"] = df["population"].fillna(0).astype(int)
    df["pop_density_km2"] = (df["population"] / df["area_km2"].replace(0, np.nan)).round(0)
    df["green_cover_pct"] = (100 * df["green_km2"] / df["area_km2"].replace(0, np.nan)).round(2)
    df["water_pct"] = (100 * df["water_km2"] / df["area_km2"].replace(0, np.nan)).round(2)
    df["building_density_km2"] = (df["building_count"] / df["area_km2"].replace(0, np.nan)).round(0)
    df = df.fillna(0).sort_values("ward_id").reset_index(drop=True)

    out_cols = ["ward_id", "ward_name", "borough", "lat", "lon", "population",
                "area_km2", "pop_density_km2", "green_cover_pct", "water_pct",
                "green_km2", "water_km2", "building_count", "building_density_km2"]
    df[out_cols].to_csv(BASE / "data" / "wards.csv", index=False)
    print(f"wrote data/wards.csv  ({len(df)} wards, pop total {df.population.sum():,})")

    # ---------------------------------------------------------------- display geojson
    props = df.set_index("ward_id").to_dict("index")
    feats = []
    for f, wid in zip(wards_gj["features"], ids):
        p = props.get(wid, {})
        feats.append({
            "type": "Feature",
            "properties": {
                "ward_id": wid,
                "ward_name": p.get("ward_name", f"Ward {wid}"),
                "borough": p.get("borough"),
                "population": int(p.get("population", 0)),
                "area_km2": p.get("area_km2"),
                "pop_density_km2": p.get("pop_density_km2"),
                "green_cover_pct": p.get("green_cover_pct"),
                "building_density_km2": p.get("building_density_km2"),
            },
            "geometry": f["geometry"],
        })
    (GEO / "kolkata_wards.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))
    )
    print(f"wrote {GEO / 'kolkata_wards.geojson'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
