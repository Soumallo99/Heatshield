"""Render-contract tests for the installable citizen phone app.

There is intentionally no browser dependency here.  ReactDOMServer renders every
screen against the real generated static payload and its empty state.  That is
stronger than grepping JSX: it catches bad optional API values, bad date handling
and content regressions that a Vite build happily accepts.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"
PAYLOAD = WEB / "public" / "static-api" / "citizen.json"
RENDERER = ROOT / "tests" / "mobile" / "render_mobile.mjs"


def _render() -> dict:
    assert PAYLOAD.exists(), "run python -m scripts.export_static before phone render tests"
    result = subprocess.run(
        ["node", str(RENDERER), str(PAYLOAD)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_every_phone_screen_server_renders_real_payload_and_empty_state():
    result = _render()
    assert result["missingFields"] == []
    assert result["badOutput"] == []
    assert result["summary"]["zones"] == 8
    assert result["summary"]["daily"] >= 8 * 5

    first_zone = json.loads(PAYLOAD.read_text())["summary"]["data"][0]["zone_name"]
    expected = {
        "home": (first_zone, "Combined heat + air load", "No locality selected"),
        "outlook": ("5-day outlook", "No daily forecast is available"),
        "alerts": ("Heatwave watch", "No heatwave watch is currently active"),
        "safety": ("Stay safer outdoors", "Carry water."),
        "about": ("Data &amp; limits", "Delivery"),
    }
    for screen, phrases in expected.items():
        rich = result["renders"][screen]["rich"]
        empty = result["renders"][screen]["empty"]
        assert all(phrase in rich or phrase in empty for phrase in phrases), screen
        assert "NaN" not in rich + empty
        assert "undefined" not in rich + empty
        assert "Invalid Date" not in rich + empty


def test_personal_heat_alerts_are_labelled_and_location_maps_to_zones():
    """The opt-in 🔔 helper must stay honest, and 📍 must resolve to the same
    Delhi-NCR zone registry the payload (and demo map) uses."""
    result = _render()
    alerts = result["personalAlerts"]
    # A comfortable zone never interrupts the resident...
    assert alerts["cleanIsNull"] is True
    # ...a synthetic risky zone is labelled as practice data inside the body...
    assert alerts["syntheticProbeLabelled"] is True
    # ...and every alert built from the real payload carries a provenance label.
    if alerts["risky"]:
        assert alerts["allLabelled"] is True
    # Nearest-zone lookup hits the exact grid points (no geocoding key needed).
    assert alerts["nearestZoneId"] == "central-delhi"
    assert alerts["nearestFarZoneId"] == "noida"


def test_unified_notifications_are_danger_or_calm_facts_never_both_lies():
    """🔔 contract: danger state -> protective alert; otherwise a calm update
    with temperature/humidity/wind; synthetic data always labelled."""
    alerts = _render()["personalAlerts"]
    assert alerts["calmKind"] == "info"
    assert alerts["calmHasFacts"] is True          # 31.4 °C · humidity 58% · wind 11.2 km/h
    assert alerts["dangerKind"] == "danger"
    assert alerts["dangerLabelled"] is True        # synthetic -> "Practice data"
    # Kolkata profile has no AQ load: WBGT stress bands drive the danger call.
    assert alerts["kolkataDangerKind"] == "danger"
    assert alerts["kolkataDangerUsesWbgt"] is True


def test_kolkata_citizen_brief_renders_every_screen_honestly():
    """The Kolkata payload shares the phone contract: WBGT-led, AQ honestly
    unavailable, no departure claims without fixed normals."""
    kolkata_payload = WEB / "public" / "static-api" / "citizen-kolkata.json"
    assert kolkata_payload.exists(), "run python -m scripts.export_static first"
    result = subprocess.run(
        ["node", str(RENDERER), str(kolkata_payload)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    doc = json.loads(result.stdout)
    assert doc["missingFields"] == []
    assert doc["badOutput"] == []
    assert doc["summary"]["zones"] == 141

    home = doc["renders"]["home"]["rich"]
    assert "Estimated WBGT" in home
    assert "No air-quality source is bundled for Kolkata" in home
    assert "Humidity" in home and "Wind" in home          # plain facts visible
    outlook = doc["renders"]["outlook"]["rich"]
    assert "WBGT" in outlook and "Risk" in outlook
    watch = doc["renders"]["alerts"]["rich"]
    assert "Historical normal unavailable" in watch or "No heatwave watch" in watch
    about = doc["renders"]["about"]["rich"]
    assert "Kolkata wards" in about


def test_phone_contract_tracks_the_real_exported_payload_shape():
    """The static snapshot must stay a valid replacement for the live endpoints."""
    raw = json.loads(PAYLOAD.read_text())
    assert raw["schema_version"] == 1
    assert raw["static_snapshot"] is True
    summary = raw["summary"]
    assert {"data", "city", "data_source", "is_synthetic"}.issubset(summary)
    assert summary["data"]
    assert {"zone_id", "zone_name", "temp_c", "aqi_india", "heat_aqi_load"}.issubset(summary["data"][0])
    assert {"rows", "climatology", "data"}.issubset(raw["alerts"])
    assert raw["daily"]
    assert {"date", "tmax_c", "aqi_peak", "heat_aqi_load_peak"}.issubset(raw["daily"][0])


def test_phone_motion_contract_uses_composite_properties_only():
    """No phone animation may trigger layout/paint-heavy width/height/top/left/filter work."""
    source = (WEB / "src" / "mobile" / "PhoneApp.jsx").read_text()
    # All Framer props are short object literals in this component.  Inspect the
    # local span after each prop rather than performing a weak whole-file grep.
    for match in re.finditer(r"\b(?:initial|animate|exit|whileHover|whileTap)\s*=\s*\{", source):
        fragment = source[match.start():match.start() + 180]
        assert not re.search(r"\b(?:width|height|top|left|filter)\s*:", fragment), fragment

    css = (WEB / "src" / "index.css").read_text()
    phone_keyframes = re.findall(r"@keyframes\s+phone\w+\s*\{([\s\S]*?)\n\}", css)
    assert phone_keyframes, "phone animations need an inspectable reduced-motion contract"
    for keyframe in phone_keyframes:
        declarations = re.findall(r"([\w-]+)\s*:", keyframe)
        assert set(declarations) <= {"transform", "opacity"}, keyframe


def test_static_host_paths_are_relative_and_phone_is_code_split():
    vite = (WEB / "vite.config.js").read_text()
    index = (WEB / "index.html").read_text()
    worker = (WEB / "public" / "sw.js").read_text()
    app = (WEB / "src" / "App.jsx").read_text()

    assert "base: process.env.VITE_BASE_PATH || './'" in vite
    assert 'href="./manifest.webmanifest"' in index
    # Registration moved out of index.html into a module (src/main.jsx) so the
    # page needs no 'unsafe-inline' in its CSP; the relative scope is still what
    # keeps a GitHub Pages subdirectory working.
    assert "register('./sw.js', { scope: './' })" not in index, "inline script would need 'unsafe-inline'"
    assert "<script>" not in index, "no inline scripts: CSP is script-src 'self'"
    main_jsx = (WEB / "src" / "main.jsx").read_text(encoding="utf-8")
    assert "register('./sw.js', { scope: './' })" in main_jsx
    assert "import.meta.env.PROD" in main_jsx, "registration must stay production-only"
    assert "const Landing = lazy" in app and "const PhoneApp = lazy" in app
    assert "const scopedURL" in worker and "inScope('api/')" in worker
    assert "navigator.serviceWorker.register('/sw.js'" not in index
    # The shell is cache-first, so the cache name MUST be bumped on every
    # shipped frontend change; the file documents that discipline and the
    # version identifier is the mechanism.
    assert re.search(r"const VERSION = 'heatshield-phone-v\d+'", worker)
    assert "CACHE-BUMP DISCIPLINE" in worker
    assert "heatshield-phone-v1" not in worker


def test_phone_bundle_budget_after_real_vite_build(built_site):
    """Run the budget gate against a real Vite build; no asset-name assumptions.

    `built_site` performs the build (once per session, shared with the other
    tests that read dist/) — a developer's `npm run build && npm run budget`,
    with the build hoisted so it cannot run after the tests that need it.
    """
    budget = subprocess.run(
        ["npm", "run", "budget"], cwd=WEB, text=True, capture_output=True, check=False
    )
    assert budget.returncode == 0, budget.stdout + budget.stderr
    assert "phone cold-open:" in budget.stdout
    assert "static citizen payload:" in budget.stdout


def test_built_site_is_installable_and_has_an_offline_shell(built_site):
    """What `npm run build` must produce for the APK/PWA test round.

    Installability is a set of concrete files, not a vibe: a manifest with the
    three icon sizes, a worker that precaches the shell and the offline page,
    and — because the whole app is served from a repository subdirectory on
    GitHub Pages — relative paths everywhere.
    """
    dist = built_site

    manifest = json.loads((dist / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "./#/phone"
    assert manifest["scope"] == "./"
    purposes = {icon["purpose"] for icon in manifest["icons"]}
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert "maskable" in purposes and {"192x192", "512x512"} <= sizes
    for icon in manifest["icons"]:
        assert (dist / icon["src"]).exists(), icon["src"]

    worker = (dist / "sw.js").read_text(encoding="utf-8")
    # The built worker must be the bumped one: a stale dist/ would otherwise
    # "pass" installation checks while every installed phone keeps the old build.
    source_worker = (WEB / "public" / "sw.js").read_text(encoding="utf-8")
    version = re.search(r"const VERSION = '(heatshield-phone-v\d+)'", source_worker)
    assert version, "sw.js must declare a versioned cache name"
    assert f"const VERSION = '{version.group(1)}'" in worker, "rebuild after bumping sw VERSION"
    for shell_entry in ("./", "./index.html", "./manifest.webmanifest", "./offline.html"):
        assert f"'{shell_entry}'" in worker, shell_entry
    assert (dist / "offline.html").exists()
    assert (dist / "icons" / "badge-72.png").exists()
    assert (dist / "data" / "kolkata_wards.geojson").exists(), "ward geometry must ship for offline maps"

    # Every asset reference in the built HTML stays relative (subdirectory-safe).
    html = (dist / "index.html").read_text(encoding="utf-8")
    assert 'src="./assets/' in html and 'href="./assets/' in html
    assert 'href="./manifest.webmanifest"' in html

    # The lazy globe's runtime assets are copied next to the app, and its JS is
    # NOT part of the entry HTML — the citizen route must never fetch Cesium.
    assert (dist / "cesium" / "Workers").is_dir()
    assert not re.search(r'"(?:src|href)="\./assets/cesium-', html)
    assert not re.search(r'modulepreload[^>]*cesium-', html)
