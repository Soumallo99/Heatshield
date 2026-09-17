"""Render-contract tests for the Heat Risk Demo frontend.

Same philosophy as tests/test_mobile_app.py: no browser, no JSX grepping in
place of rendering.  ReactDOMServer renders every demo screen against the REAL
exported static payloads for all four scenarios plus the empty state, and the
assertions here are about resident-visible honesty: the disclaimer on every
screen, explicit lead days, text-labelled colours, dry-run notifications,
labelled (never "validated") health-impact output, and a fixed demo clock.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"
STATIC_API = WEB / "public" / "static-api"
RENDERER = ROOT / "tests" / "demo" / "render_demo.mjs"

SCENARIOS = ["dry-extreme", "humid-dangerous", "heat-plus-pollution", "monsoon-break"]
FIXED_ISSUED_AT = "2026-05-18T06:00"
DISCLAIMER = "Demo / synthetic scenario — not a live forecast or observation."


def _render(scenario_id: str) -> dict:
    assert STATIC_API.exists(), "run python -m scripts.export_static before demo render tests"
    result = subprocess.run(
        ["node", str(RENDERER), str(STATIC_API), scenario_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_every_demo_screen_server_renders_real_payloads_and_empty_states():
    for scenario_id in SCENARIOS:
        result = _render(scenario_id)
        assert result["missingFields"] == [], scenario_id
        assert result["badOutput"] == [], scenario_id
        assert result["missingDisclaimer"] == [], scenario_id

        summary = result["summary"]
        assert summary["scenarios"] == 4
        assert summary["zones"] == 8
        assert summary["warningRows"] == 48  # 8 zones x leads 0-5
        assert summary["leadDays"] == [0, 1, 2, 3, 4, 5]
        assert summary["issuedAt"] == FIXED_ISSUED_AT
        assert summary["referencePeriod"] == "1991-01-01 to 2020-12-31"
        assert summary["dryRun"] is True
        if scenario_id == "monsoon-break":
            assert summary["previews"] == 0  # nothing severe enough to notify
        else:
            assert summary["previews"] > 0

        for screen, states in result["renders"].items():
            for state, html in states.items():
                assert DISCLAIMER in html, f"{scenario_id}/{screen}/{state}"
                assert "NaN" not in html and "undefined" not in html and "Invalid Date" not in html


def test_demo_renders_use_the_fixed_clock_not_todays_date():
    result = _render("dry-extreme")
    today = dt.date.today().isoformat()
    for screen, states in result["renders"].items():
        for html in states.values():
            assert today not in html, screen
    now_rich = result["renders"]["now"]["rich"]
    assert FIXED_ISSUED_AT in now_rich
    outlook = result["renders"]["outlook"]["rich"]
    assert "Tue, 19 May" in outlook   # Day +1, formatDate() of fixed targets
    assert "Sat, 23 May" in outlook   # Day +5


def test_outlook_screen_shows_explicit_three_to_five_day_leads():
    html = _render("dry-extreme")["renders"]["outlook"]["rich"]
    for label in ("Day +3", "Day +4", "Day +5"):
        assert label in html, label
    assert "h to peak" in html                     # lead hours next to lead days
    assert "1991-01-01 to 2020-12-31" in html      # fixed normals provenance
    assert "never a forecast-window average" in html
    assert "Normal" in html and "Departure" in html


def test_zones_screen_lists_every_zone_with_words_not_just_colour():
    zones_doc = json.loads((STATIC_API / "demo-zones.json").read_text(encoding="utf-8"))
    zone_names = [zone["zone_name"] for zone in zones_doc["data"]]
    assert len(zone_names) == 8
    html = _render("dry-extreme")["renders"]["zones"]["rich"]
    for name in zone_names:
        assert name in html, name
    # Colour is never the only channel: band and level words are rendered as
    # text inside chips and in the legend next to every swatch.
    for word in ("Warning", "Severe", "Vulnerability", "Heatwave"):
        assert word in html, word
    assert "accessible alternative to the colour-coded map" in html


def test_impact_screen_keeps_health_risk_labelled_and_separate():
    html = _render("dry-extreme")["renders"]["impact"]["rich"]
    assert "Meteorological thermal stress" in html
    assert "kept separate from weather" in html
    assert "synthetic_demo" in html
    assert "NOT a validated mortality forecast" in html
    assert "estimated WBGT" in html.lower() or "Estimated WBGT" in html
    assert "validated_observed_outcome_model" not in html
    assert "Municipal / public-health actions" in html
    assert "Resident safety advice" in html


def test_notify_screen_previews_are_dry_run_and_honest():
    rich = _render("dry-extreme")["renders"]["notify"]["rich"]
    assert rich.count("demo-preview-card") >= 8          # capped card grid
    assert "PREVIEW · DRY RUN" in rich
    assert "demo-synthetic" in rich                      # per-row quality state
    assert "live" in rich.lower()                        # live-send lock wording
    empty = _render("monsoon-break")["renders"]["notify"]["rich"]
    assert "No alert in this scenario" in empty
    assert "demo-preview-card__message" not in empty     # zero preview cards


def test_empty_states_are_honest_not_broken():
    result = _render("dry-extreme")
    assert "No scenario loaded" in result["renders"]["now"]["empty"]
    assert "No zone selected" in result["renders"]["impact"]["empty"]
    assert "No zone rows" in result["renders"]["zones"]["empty"]
    assert "unavailable" in result["renders"]["outlook"]["empty"].lower() \
        or "No outlook rows" in result["renders"]["outlook"]["empty"]


def test_demo_motion_contract_transform_opacity_only():
    """Demo transitions animate composite properties only (colour included);
    nothing animates layout geometry."""
    css = (WEB / "src" / "index.css").read_text(encoding="utf-8")
    allowed = {"transform", "opacity", "color", "background-color", "border-color", "box-shadow", "none"}
    seen_demo_transition = False
    for selector, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        if "demo" not in selector:
            continue
        for prop, value in re.findall(r"(transition|animation)\s*:\s*([^;]+);", body):
            if prop == "animation":
                assert value.strip() == "none", (selector, value)
                continue
            seen_demo_transition = True
            for part in value.split(","):
                first = part.strip().split()[0] if part.strip() else ""
                assert first in allowed, (selector, part)
    assert seen_demo_transition, "demo hover transitions should exist and stay composite-only"
    assert re.search(r"prefers-reduced-motion[\s\S]{0,200}\.demo-btn\s*\{\s*transition:\s*none", css)

    # Framer props in the demo shell animate opacity/transform (y) only.
    source = (WEB / "src" / "demo" / "DemoApp.jsx").read_text(encoding="utf-8")
    for match in re.finditer(r"\b(?:initial|animate|exit)\s*=\s*\{", source):
        fragment = source[match.start():match.start() + 160]
        assert not re.search(r"\b(?:width|height|top|left|filter)\s*:", fragment), fragment


def test_demo_map_never_encodes_meaning_with_colour_alone():
    source = (WEB / "src" / "demo" / "DemoMap.jsx").read_text(encoding="utf-8")
    legend_entries = re.findall(r"\{\s*colour:\s*[^,]+,\s*label:", source)
    colour_entries = re.findall(r"colour:\s*'#", source)
    assert legend_entries and len(legend_entries) >= len(colour_entries)
    assert "aria-label" in source
    # Every layer renders a text legend under the map and a text tooltip.
    assert "demo-map-legend" in source and "Tooltip" in source


def test_both_cities_are_switchable_in_dashboard_and_citizen_tab():
    """Delhi NCR and Kolkata are both first-class: the ops console switches
    city (ward console <-> zone advance-warning console) and the citizen app
    switches its brief (citizen.json <-> citizen-kolkata.json)."""
    dashboard = (WEB / "src" / "components" / "Dashboard.jsx").read_text(encoding="utf-8")
    assert "CitySwitch" in dashboard and "DelhiOps" in dashboard
    assert "'Kolkata'" in dashboard and "'Delhi NCR'" in dashboard
    delhi_ops = (WEB / "src" / "components" / "DelhiOps.jsx").read_text(encoding="utf-8")
    # live-first with the labelled snapshot fallback, honest banner either way
    assert "'./api/warnings/advance'" in delhi_ops
    assert "warnings-advance.json" in delhi_ops
    assert "Practice data (provider outage fallback)" in delhi_ops
    assert "Not an official IMD declaration" in delhi_ops
    phone = (WEB / "src" / "mobile" / "PhoneApp.jsx").read_text(encoding="utf-8")
    assert "CITY_OPTIONS" in phone and "Kolkata" in phone
    assert "phone-location-prompt" in phone          # turn-on-location nudge
    assert "FULL brief for every locality" in phone  # data never gated on GPS
    data = (WEB / "src" / "mobile" / "data.js").read_text(encoding="utf-8")
    assert "citizen-kolkata.json" in data and "'./api/citizen/kolkata'" in data
    # No quoted absolute URLs in the loader (comments explaining GitHub Pages
    # URLs are fine); every fetch target must be relative.
    assert not re.search(r"[\"']https?://", data)
    # The Kolkata map renders with keyless tiles and degrades honestly.
    risk_map = (WEB / "src" / "components" / "RiskMap.jsx").read_text(encoding="utf-8")
    assert "KEYLESS_FALLBACK" in risk_map and "tileerror" in risk_map


def test_demo_is_route_level_code_split_and_prominently_linked():
    app = (WEB / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "demo: 'demo'" in app
    assert "const DemoApp = lazy" in app
    landing = (WEB / "src" / "components" / "Landing.jsx").read_text(encoding="utf-8")
    assert "onDemo" in landing and "Heat Risk Demo" in landing
    dashboard = (WEB / "src" / "components" / "Dashboard.jsx").read_text(encoding="utf-8")
    assert "onDemo" in dashboard and "Heat Risk Demo" in dashboard
    # The demo data loader only ever uses relative URLs (static-host safe).
    data = (WEB / "src" / "demo" / "data.js").read_text(encoding="utf-8")
    assert "http://" not in data and "https://" not in data
    assert "'./api/demo/" in data and "static-api/" in data
