"""Structural tests for the lazy keyless 3D globe.

Three properties are load-bearing and each one has already been broken once
while building this feature, so they are asserted rather than trusted:

1. LAZY — CesiumJS (~1.1 MB gzip) may only be reached through a dynamic import
   from the operations consoles. If it ever enters the entry graph, the citizen
   phone cold-open pays for a globe it never shows (``npm run budget`` catches
   the size; these tests catch the wiring, before a build).
2. KEYLESS — the globe's source catalogue contains no keyed provider and no
   ion/token code path at all. A keyed tile cannot be requested because no keyed
   URL is ever constructed, and the viewer boots with ``baseLayer: false`` so
   Cesium's token-hungry default imagery is never even created.
3. ATTRIBUTED + LICENCE-CLEAN — gods-eye-view's MIT notice is preserved, the
   snapshot commit is pinned in THIRD-PARTY.md, and nothing from that project's
   NonCommercial datasets (TeleGeography, Bhote Koshi) or bundled models was
   vendored.

Comments are stripped before the keyless scan: the files explain at length which
credentials they refuse to use, and those explanations are the point.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"
SRC = WEB / "src"
GLOBE = SRC / "globe"
PINNED_COMMIT = "0d41b6be5490db1f10a171f238be75db4d4ec3b4"


def _code_only(source: str) -> str:
    """Strip comments so prose about *refused* credentials cannot trip the
    credential scan — while keeping string literals, where the real URLs (and
    therefore the real providers) live.

    A naive ``re.sub(r"//", ...)`` is wrong here: it eats the ``//`` inside
    ``https://…`` and every URL in the file vanishes, which would make the scan
    pass for the wrong reason.
    """
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""
        if char in "\"'`":
            quote = char
            out.append(char)
            index += 1
            while index < length:
                if source[index] == "\\":
                    out.append(source[index:index + 2])
                    index += 2
                    continue
                out.append(source[index])
                if source[index] == quote:
                    index += 1
                    break
                index += 1
            continue
        if char == "/" and following == "*":
            end = source.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == "/" and following == "/":
            end = source.find("\n", index)
            index = length if end == -1 else end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _globe_sources() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(GLOBE.glob("*.js"))}


# ------------------------------------------------------------------ 1. lazy


def test_globe_is_reached_only_through_a_dynamic_import():
    dashboard = (SRC / "components" / "Dashboard.jsx").read_text(encoding="utf-8")
    delhi = (SRC / "components" / "DelhiOps.jsx").read_text(encoding="utf-8")
    for surface, source in (("Dashboard", dashboard), ("DelhiOps", delhi)):
        assert "lazy(() => import('../globe/HeatGlobe'))" in source, surface
        assert "HeatGlobe" in source, surface
        assert "MapViewSwitch" in source, surface
    # Both consoles default to the 2D map: the globe is opt-in, never the
    # only path (low-end devices, offline demos, no-WebGL browsers).
    assert "useState('2d')" in dashboard and "useState('2d')" in delhi


def test_nothing_outside_the_globe_lazy_chunks_imports_cesium():
    static_import = re.compile(r"^\s*import[^\n]*from\s+['\"](?:cesium|\.\./globe|\./globe|\.\./\.\./globe)")
    offenders = []
    for path in sorted(SRC.rglob("*.js*")):
        if GLOBE in path.parents:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if static_import.search(line) and "lazy(" not in line:
                offenders.append(f"{path.relative_to(WEB)}: {line.strip()}")
    assert offenders == [], offenders

    # The citizen phone app is 2D forever: it must not import the globe, and
    # must not reference Cesium anywhere. (Word-level "globe" is not the test —
    # the citizen screens legitimately talk about a "measured globe reading".)
    for path in sorted((SRC / "mobile").rglob("*.js*")) + [SRC / "App.jsx"]:
        source = path.read_text(encoding="utf-8")
        assert "cesium" not in source.lower(), path
        assert "HeatGlobe" not in source, path
        assert not re.search(r"from\s+['\"][^'\"]*globe", source), path


def test_vite_keeps_cesium_and_its_dependency_closure_in_their_own_chunk():
    """`nosleep.js` (Cesium's wake-lock dependency) carries ~12 kB of base64
    video and does not match 'cesium' by path — when it slipped into the shared
    chunk, the citizen cold-open grew by 5 kB gzip. The budget gate catches the
    size; this catches the rule."""
    vite = (WEB / "vite.config.js").read_text(encoding="utf-8")
    assert "if (id.includes('cesium') || id.includes('nosleep')) return 'cesium'" in vite
    # Vite's own runtime helpers need their own home, or Rollup parks them in
    # the forced Cesium chunk and every route has to load it.
    assert "id.startsWith('\\0vite/')" in vite
    budget = (ROOT / "scripts" / "check_phone_budget.mjs").read_text(encoding="utf-8")
    assert "globe code entered phone cold-open" in budget
    assert "/cesium|nosleep|protobuf|globe/i" in budget


# --------------------------------------------------------------- 2. keyless


def test_globe_providers_are_keyless_and_fallback_to_osm():
    sources = _globe_sources()
    imagery = _code_only(sources["imagery.js"])
    catalogue = _code_only(sources["sources.js"])

    # Keyless endpoints only, on two different CDNs.
    assert "services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer" in imagery
    assert "tile.openstreetmap.org" in imagery
    # Two-stage fallback to OSM, with the reason travelling to the UI.
    assert "constructionFallback" in catalogue and "'osm'" in catalogue
    assert "tileFailureFallback" in catalogue
    assert "keyless" in catalogue.lower()

    forbidden = re.compile(
        r"accessToken|IonImageryProvider|IonResource|Cesium\.Ion|defaultAccessToken"
        r"|maptiler|thunderforest|cartocdn|api[_-]?key|apikey|\?key=|&key=",
        re.IGNORECASE,
    )
    for name in ("imagery.js", "terrain.js", "sources.js", "viewer.js", "scene.js", "controller.js"):
        hit = forbidden.search(_code_only(sources[name]))
        assert hit is None, f"{name} contains a keyed/token path: {hit.group(0)!r}"


def test_globe_viewer_boots_without_a_base_layer_and_probes_webgl():
    viewer = _code_only(_globe_sources()["viewer.js"])
    # The guarantee: no base layer at construction, so Cesium never builds its
    # ion-hosted default imagery. Remove this and the first boot demands a key.
    assert "baseLayer: false" in viewer
    assert "supportsWebgl" in viewer
    globe = (GLOBE / "HeatGlobe.jsx").read_text(encoding="utf-8")
    # A device without WebGL is told the truth, and the 2D map keeps working.
    assert "supportsWebgl()" in globe
    assert "The 3D globe is unavailable on this device." in globe


def test_globe_credit_line_follows_the_active_source():
    credits = (GLOBE / "credits.js").read_text(encoding="utf-8")
    assert "addStaticCredit" in credits and "removeStaticCredit" in credits
    globe = (GLOBE / "HeatGlobe.jsx").read_text(encoding="utf-8")
    # The Cesium credit container stays mounted and visible — provider
    # attribution is a licence term, not decoration.
    assert "creditRef" in globe and "globe-credits" in globe
    globe_css = (GLOBE / "globe.css").read_text(encoding="utf-8")
    assert ".globe-credits" in globe_css
    assert "display: none" not in globe_css.replace("display: none", "display: none")  # no hidden credits
    assert "display: none" not in globe_css


# ------------------------------------------------- 3. attribution + licences


def test_vendored_globe_code_keeps_its_mit_notice_and_pinned_snapshot():
    licence = (GLOBE / "LICENSE-gods-eye-view").read_text(encoding="utf-8")
    assert "MIT License" in licence
    assert "Copyright (c) 2026 Bilawal Sidhu" in licence
    assert PINNED_COMMIT in licence

    third_party = (ROOT / "THIRD-PARTY.md").read_text(encoding="utf-8")
    assert PINNED_COMMIT in third_party
    assert "gods-eye-view" in third_party and "MIT" in third_party
    assert "CesiumJS" in third_party and "Apache-2.0" in third_party
    assert "Esri" in third_party and "OpenStreetMap" in third_party

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "THIRD-PARTY.md" in readme
    assert "gods-eye-view" in readme

    globe_readme = (GLOBE / "README.md").read_text(encoding="utf-8")
    assert PINNED_COMMIT in globe_readme
    # The derived files say what they are derived from.
    for name in ("imagery.js", "terrain.js", "registry.js", "credits.js", "controller.js", "viewer.js"):
        assert "gods-eye-view" in (GLOBE / name).read_text(encoding="utf-8"), name


def test_globe_ui_shows_source_attribution_and_labels_every_colour():
    globe = (GLOBE / "HeatGlobe.jsx").read_text(encoding="utf-8")
    for credit in ("Esri", "OpenStreetMap", "Re:Earth", "CesiumJS", "Apache-2.0"):
        assert credit in globe, credit
    assert "No API key is used or required anywhere on this map." in globe
    # Colour is never the only channel: a text legend accompanies every layer.
    assert "globe-legend" in globe
    assert "BAND_LEGEND" in globe and "ALERT_LEGEND" in globe
    layers = (GLOBE / "heatLayers.js").read_text(encoding="utf-8")
    assert "levelLabel(row.alert_level)" in layers  # zone labels spell the level out
    assert "PRISM_NOTE" in layers  # the stylised height is labelled as stylised
    assert "not a measurement" in layers


def test_no_noncommercial_upstream_data_or_models_are_vendored():
    """gods-eye-view's `src/data/local_data/` (TeleGeography CC BY-NC-SA,
    Bhote Koshi CC BY-NC) and `public/models/` are licence carve-outs: code was
    vendored, data was not."""
    vendored = [path for path in GLOBE.rglob("*") if path.is_file()]
    assert vendored, "globe directory is empty"
    for path in vendored:
        assert "local_data" not in path.parts and "models" not in path.parts, path
    # Only *code* is scanned for references to those datasets. The README and
    # licence header name them on purpose — recording the carve-out is how the
    # next contributor learns why the directory is absent.
    code = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in vendored
        if path.suffix in {".js", ".jsx"}
    )
    assert code, "expected code files in src/globe"
    for forbidden in ("telegeography", "bhote koshi", "local_data", "public/models"):
        assert forbidden.lower() not in code.lower(), forbidden
    # And the licence file states the carve-out, so the next person knows why.
    licence = (GLOBE / "LICENSE-gods-eye-view").read_text(encoding="utf-8")
    assert "local_data" in licence and "models" in licence


# --------------------------------------------- both cities, plus 2D fallback


def test_globe_serves_both_cities_with_the_same_layers_the_2d_maps_use():
    heat = (GLOBE / "heatLayers.js").read_text(encoding="utf-8")
    assert "addWardChoropleth" in heat and "MultiPolygon" in heat  # real ward geometry
    assert "addZoneMarkers" in heat and "PRISM_METRES_PER_POINT" in heat
    dashboard = (SRC / "components" / "Dashboard.jsx").read_text(encoding="utf-8")
    delhi = (SRC / "components" / "DelhiOps.jsx").read_text(encoding="utf-8")
    assert 'mode="wards"' in dashboard and 'area="kolkata"' in dashboard
    assert 'mode="zones"' in delhi and 'area="delhi"' in delhi
    # The globe shares the selection state with the 2D map and the tables.
    assert "selectedId={selected?.ward_id}" in dashboard
    assert "onSelect={setSelectedId}" in dashboard
    assert "selectedId={zoneId}" in delhi and "onSelect={(id) => setZoneId(String(id))}" in delhi
