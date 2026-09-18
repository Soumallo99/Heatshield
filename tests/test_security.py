"""Security regression tests — the API hardening that came out of a pentest pass.

Every test here corresponds to something that was **actually exploitable** before
it was fixed, and each one is named for the failure it prevents. The threat model
is in `core/security.py`; the short version is that the API has no accounts, so
what matters is that anonymous requests cannot read personal data, cannot silence
someone's heat warnings, and cannot drive a send.

These run with `HS_ADMIN_TOKEN` set (see conftest) — i.e. the way an operator
deploys — and the disabled-by-default behaviour is asserted explicitly below.
"""
from __future__ import annotations

import importlib
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core import config
from core.security import RateLimiter, redact_phone, sanitise_cell

ADMIN = {"X-API-Key": "test-admin-token"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------- #
# 1. the registry is not public
# --------------------------------------------------------------------------- #

def test_anonymous_requests_cannot_read_the_subscriber_registry(client):
    """It used to return every phone number, name and role to anyone.

    Personal data of residents, ward officials and health workers, enumerable by
    one unauthenticated GET — and, because CORS was `*`, readable from any
    website a visitor happened to have open.
    """
    for path in ("/subscribers", "/subscribers/for-ward/24"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401, path


def test_registry_reads_are_redacted_even_with_a_valid_token(client):
    """The gate is the second layer; the first is not handing out the numbers."""
    body = client.get("/subscribers", headers=ADMIN).json()
    assert body["count"] > 0, "fixture registry should have rows"
    for row in body["data"]:
        assert "••••••" in row["phone"], row["phone"]
        assert len(row["phone"].split("•")[-1]) == 4, "last four digits only"
    recipients = client.get("/subscribers/for-ward/24", headers=ADMIN).json()["recipients"]
    assert recipients and all("••••••" in number for number in recipients)


def test_registry_endpoint_no_longer_500s_on_blank_fields(client):
    """NaN in a blank CSV cell made json.dumps refuse the whole payload."""
    response = client.get("/subscribers", headers=ADMIN)
    assert response.status_code == 200
    assert "NaN" not in response.text


def test_redact_phone_keeps_the_shape_not_the_person():
    assert redact_phone("+919876543210") == "+91••••••3210"
    assert redact_phone("9876543210") == "+91••••••3210"
    assert redact_phone("") == ""
    assert "98765" not in redact_phone("+919876543210")


# --------------------------------------------------------------------------- #
# 2. nobody can silence somebody else's warnings
# --------------------------------------------------------------------------- #

def test_anonymous_requests_cannot_opt_out_a_number(client):
    """`POST /subscribers/stop` took any phone number and silenced it.

    Against a heat-warning system that is a denial-of-warnings attack: name a
    number, and the resident stops receiving alerts. (A real STOP arrives as an
    inbound SMS webhook, where the number proves it belongs to the sender.)
    """
    assert client.post("/subscribers/stop", json={"phone": "+919900000000"}).status_code == 401
    assert client.post(
        "/subscribers", json={"phone": "+919999900009", "ward_id": 7}
    ).status_code == 401


def test_dispatch_routes_require_the_admin_token(client):
    """Dry-run by default, but anyone could drive them — and `to_numbers` aims a
    real send at numbers the caller chooses once live sending is enabled."""
    for path in ("/alerts/dispatch", "/notifications/dispatch"):
        assert client.post(path, json={"dry_run": True}).status_code == 401, path


def test_admin_routes_are_disabled_rather_than_trusted_without_a_token(monkeypatch, client):
    """Fail closed: an operator who forgets HS_ADMIN_TOKEN gets refusals, not an
    open registry."""
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    for path in ("/subscribers", "/subscribers/for-ward/24"):
        response = client.get(path)
        assert response.status_code == 503
        assert "HS_ADMIN_TOKEN" in response.json()["detail"]
    assert client.post("/alerts/dispatch", json={"dry_run": True}).status_code == 503


# --------------------------------------------------------------------------- #
# 3. input hardening
# --------------------------------------------------------------------------- #

def test_registry_fields_cannot_carry_spreadsheet_formulas(tmp_path, monkeypatch):
    """`=cmd|' /C calc'!A0` in a name field is a formula, not a person.

    The registry is a CSV that an operator opens in Excel or LibreOffice; a
    leading `=`, `+`, `-` or `@` executes there (CWE-1236).
    """
    from core import subscribers

    path = tmp_path / "subscribers.csv"
    result = subscribers.add_subscriber(
        "+919876543210", 24, "=cmd|calc!A1", "resident", path=path
    )
    assert result["ok"]
    for dangerous in ("=cmd|calc!A1", "+1+1", "@SUM(A1:A9)", "-2+3"):
        assert sanitise_cell(dangerous).startswith("'"), dangerous
    stored = path.read_text()
    # The field is quoted-for-spreadsheets, so it is inert when opened...
    assert ",'=cmd|calc!A1," in stored
    # ...and no field in the file begins a formula.
    for field in stored.split("\n")[1:]:
        for cell in field.split(",")[:2]:
            assert not cell.startswith(("=", "@", "-")), field


def test_sanitise_cell_strips_control_characters_and_caps_length():
    assert sanitise_cell("line\nbreak") == "line break"
    assert sanitise_cell("null\x00byte") == "nullbyte"
    assert len(sanitise_cell("A" * 5000, max_length=80)) == 80


def test_registry_writes_reject_wards_that_do_not_exist(client):
    for ward in (99999, -5):
        response = client.post(
            "/subscribers", json={"phone": "+919999900010", "ward_id": ward}, headers=ADMIN
        )
        assert response.status_code == 422, ward
    assert client.post(
        "/subscribers", json={"phone": "not-a-phone", "ward_id": 1}, headers=ADMIN
    ).status_code == 400
    assert client.post(
        "/subscribers", json={"phone": "+919999900011", "ward_id": 1, "role": "root"},
        headers=ADMIN,
    ).status_code == 400


def test_unbounded_numbers_are_rejected_before_any_work_happens(client):
    """`?scenario_c=1e9` used to burn ~9 seconds of CPU and then 500."""
    for query in ("scenario_c=1e9", "scenario_c=nan", "scenario_c=-999", "scenario_c=1e308"):
        assert client.get(f"/risk/ranking?{query}").status_code == 422, query
    assert client.get("/risk/ward/99999").status_code == 422
    assert client.get("/risk?ward_id=99999").status_code == 422
    assert client.get("/risk/ranking?date=';DROP TABLE").status_code == 422
    assert client.get("/thermal/ward/99999").status_code == 422


def test_oversized_bodies_are_rejected(client):
    body = {"name": "A" * (config.MAX_BODY_BYTES + 1000)}
    assert client.post("/subscribers", json=body, headers=ADMIN).status_code == 413


def test_dispatch_recipient_lists_are_capped_and_sanitised():
    from app.main import DispatchIn, NotifyDispatchIn

    payload = DispatchIn(to_numbers=["+919876543210", "junk", "+919876543210", "12345"])
    assert payload.recipients == ["+919876543210"], "normalised, de-duplicated, junk dropped"
    # An oversized list is rejected outright rather than silently trimmed.
    with pytest.raises(Exception):
        NotifyDispatchIn(to_numbers=[f"+9198765{i:05d}" for i in range(200)])
    assert len(NotifyDispatchIn(to_numbers=[f"+9198765{i:05d}" for i in range(50)]).recipients) == 50


# --------------------------------------------------------------------------- #
# 4. the browser-facing surface
# --------------------------------------------------------------------------- #

def test_cors_is_no_longer_a_wildcard(client):
    """`allow_origins=["*"]` let any website read the API from a visitor's browser."""
    evil = client.get("/zones", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    dev = client.get("/zones", headers={"Origin": "http://localhost:5173"})
    assert dev.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "vary" in {key.lower() for key in dev.headers}


def test_api_documentation_is_not_published_on_a_real_deployment(monkeypatch, client):
    """The schema is a map of every route, dispatch included."""
    monkeypatch.setattr(config, "ENABLE_DOCS", False)
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 404, path


def test_responses_carry_security_headers(client):
    headers = client.get("/zones").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"


def test_ratelimiter_counts_per_client_and_reports_retry_after():
    limiter = RateLimiter(3, window_seconds=60)
    assert [limiter.allow("a", now=100.0)[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.allow("a", now=100.0)
    assert allowed is False and retry_after >= 1
    # A different client has its own budget, and the window slides.
    assert limiter.allow("b", now=100.0)[0] is True
    assert limiter.allow("a", now=161.0)[0] is True
    # 0 disables it (how the suite runs).
    assert RateLimiter(0).allow("any")[0] is True


def test_rate_limit_is_enforced_by_the_app(monkeypatch, client):
    import app.main as main

    monkeypatch.setattr(main, "limiter", RateLimiter(2, window_seconds=60))
    codes = [client.get("/health").status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429
    assert client.get("/health").headers.get("retry-after")


def test_docs_setting_is_read_from_config(monkeypatch):
    """`config.ENABLE_DOCS` decides whether the schema is published.

    The default is computed at import (on in dev, off once an admin token
    exists); forcing it either way is one environment variable. The reload keeps
    this test honest about what the app does at construction time, and the final
    reload restores the module for the rest of the suite.
    """
    import app.main as main

    monkeypatch.setattr(config, "ENABLE_DOCS", False)
    reloaded = importlib.reload(main)
    assert reloaded.app.docs_url is None and reloaded.app.openapi_url is None

    monkeypatch.setattr(config, "ENABLE_DOCS", True)
    reloaded = importlib.reload(main)
    assert reloaded.app.docs_url == "/docs"

    monkeypatch.undo()
    importlib.reload(main)


# --------------------------------------------------------------------------- #
# 5. the page itself
# --------------------------------------------------------------------------- #

def test_the_page_forbids_inline_and_third_party_scripts(built_site):
    """A CSP meta tag is the only header control a static host leaves us.

    GitHub Pages serves the app and cannot set response headers, so the policy
    ships in the HTML. It stays strict because the bundle needs nothing looser:
    every script is same-origin, and the service-worker registration lives in a
    module instead of an inline block precisely so `script-src 'self'` holds.
    """
    from pathlib import Path

    html = (Path(built_site) / "index.html").read_text(encoding="utf-8")
    policy = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    assert policy, "index.html must ship a Content-Security-Policy"
    policy = policy.group(1)
    assert "script-src 'self'" in policy
    assert "'unsafe-eval'" not in policy
    assert "object-src 'none'" in policy
    assert "base-uri 'self'" in policy

    # No inline script survives the build, so the policy is enforceable rather
    # than aspirational.
    inline = [
        block for tag, block in re.findall(r"<script([^>]*)>([\s\S]*?)</script>", html)
        if "src=" not in tag and block.strip()
    ]
    assert not inline, f"inline scripts would need 'unsafe-inline': {inline[:1]}"
    assert re.search(r'src="\./assets/[^"]+\.js"', html), "app bundle still loads"


def test_app_code_contacts_only_the_hosts_it_is_supposed_to(built_site):
    """A supply-chain check on *our* bundles, not on the Cesium vendor chunk.

    The vendor chunk is excluded deliberately, and the reason matters: CesiumJS is
    a 4 MB library whose source comments cite dozens of documentation URLs
    (khronos.org, nvidia.com, cesium.com, stadiamaps.com…) and whose code paths
    for keyed providers exist but are never constructed here — we boot with
    `baseLayer: false` and register only keyless sources, which
    tests/test_globe_view.py asserts by scanning the providers we build.

    So this test answers a different question: does *HeatShield's own code* reach
    any host that is not tiles, terrain, fonts or the keyless data sources? A new
    analytics beacon or a CDN script would show up right here.
    """
    from pathlib import Path

    dist = Path(built_site)
    html = (dist / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" in html and "fonts.gstatic.com" in html
    assert not re.search(r'<script[^>]+src="https?://', html), "no third-party scripts"

    app_bundles = [
        path for path in (dist / "assets").glob("*.js")
        if not path.name.startswith("cesium-")
    ]
    assert app_bundles, "expected the app's own JS chunks"
    sources = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in app_bundles)
    hosts = set(re.findall(r"https?://([a-z0-9.-]+\.[a-z]{2,})/", sources))
    allowed = {
        "server.arcgisonline.com",     # Esri tiles: 2D satellite basemap
        "services.arcgisonline.com",   # Esri World Imagery MapServer: the 3D globe
        "tile.openstreetmap.org",      # keyless OSM tiles + the globe's fallback
        "tile.opentopomap.org",        # terrain basemap
        "terrain.reearth.land",        # keyless quantized-mesh terrain
        "fonts.googleapis.com", "fonts.gstatic.com",
        "www.w3.org",                  # SVG namespace inside inline data URIs
        "github.com",                  # provenance link in the demo credits
        "localhost", "127.0.0.1",      # documented dev-only API target
        "reactjs.org",                 # React's error-decoder URL in a message string
    }
    assert hosts <= allowed, f"unexpected external hosts: {sorted(hosts - allowed)}"


def test_service_worker_cannot_be_poisoned_into_caching_api_pii(built_site):
    """The worker caches `api/` responses for offline reuse.

    It must only ever do that for its own scope (same-origin, in-app), never for
    cross-origin responses, or a third party could plant content under our
    origin. Tile responses are cached separately and only opaque/image ones.
    """
    from pathlib import Path

    worker = (Path(built_site) / "sw.js").read_text(encoding="utf-8")
    assert "inScope('api/')" in worker
    assert "url.origin === self.location.origin" in worker, "shell writes are same-origin only"
    assert "TILE_HOSTS.some" in worker, "cross-origin caching is limited to tile hosts"
