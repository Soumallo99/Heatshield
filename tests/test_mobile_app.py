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
    assert "register('./sw.js', { scope: './' })" in index
    assert "const Landing = lazy" in app and "const PhoneApp = lazy" in app
    assert "const scopedURL" in worker and "inScope('api/')" in worker
    assert "navigator.serviceWorker.register('/sw.js'" not in index


def test_phone_bundle_budget_after_real_vite_build():
    """Run the same budget gate developers run; no asset-name assumptions in Python."""
    build = subprocess.run(
        ["npm", "run", "build"], cwd=WEB, text=True, capture_output=True, check=False
    )
    assert build.returncode == 0, build.stdout + build.stderr
    budget = subprocess.run(
        ["npm", "run", "budget"], cwd=WEB, text=True, capture_output=True, check=False
    )
    assert budget.returncode == 0, budget.stdout + budget.stderr
    assert "phone cold-open:" in budget.stdout
    assert "static citizen payload:" in budget.stdout
