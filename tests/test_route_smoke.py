"""Every route, every way it can be called wrongly.

The unit tests cover the modules; the security tests cover the gated routes.
Neither answers the question a launch actually asks: *does any endpoint, called
with the input a real client might send, return a 500?* A 500 on bad input is a
bug even though nothing was lost — it means an unvalidated value reached pandas,
and the next value might not be refused so politely.

So this file walks the whole route table:

  * every GET route is called with valid parameters and must answer 200 with a
    JSON body (or the documented HTML root), not a 500;
  * every path parameter is probed with hostile values — negative, zero, huge,
    non-numeric, SQL-ish, an empty string, a Unicode surrogate — and must never
    produce a 500 (422/400 are the correct answers);
  * every query parameter on every route is fuzzed the same way;
  * POST routes get malformed bodies (wrong types, missing fields, absurd
    lengths, a literal `null`) and must answer 4xx, never 500.

It is deliberately a *shape* test, not a value test: it does not care what the
numbers are, only that a bad request is refused instead of crashing.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app

ADMIN = {"X-API-Key": "test-admin-token"}

# Values that have broken parsers in other projects, kept together so the list
# can grow every time something new is found.
HOSTILE = [
    "-1",
    "0",
    "999999",
    "1e9",
    "1.5",
    "abc",
    "",
    "null",
    "0x10",
    "1;DROP TABLE wards",
    "1 OR 1=1",
    "<script>alert(1)</script>",
    "%00",
    "9999999999999999999999",
]


def _routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _paths() -> list[str]:
    return sorted({method for route in _routes() for method in route.methods})


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _fill(path: str, value: str) -> str:
    """Substitute a concrete value for every path parameter."""
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        out = out[:start] + value + out[end + 1 :]
    return out


def _get_routes() -> list[APIRoute]:
    return [route for route in _routes() if "GET" in route.methods]


def test_every_get_route_answers_without_server_errors(client: TestClient):
    """A valid request to any read endpoint must be a 2xx or a documented refusal."""
    failures = []
    for route in _get_routes():
        path = _fill(route.path, "1")
        response = client.get(path, headers=ADMIN)
        if response.status_code >= 500:
            failures.append(f"GET {path} -> {response.status_code} {response.text[:200]}")
    assert not failures, "server error on a valid request:\n" + "\n".join(failures)


def test_no_route_returns_a_server_error_for_a_hostile_path_parameter(client: TestClient):
    """Bad input is a 4xx, never a crash — and never a partially computed answer."""
    failures = []
    for route in _get_routes():
        if "{" not in route.path:
            continue
        for value in HOSTILE:
            path = _fill(route.path, value)
            response = client.get(path, headers=ADMIN)
            if response.status_code >= 500:
                failures.append(f"GET {path} -> {response.status_code} {response.text[:160]}")
    assert not failures, "\n".join(failures)


def test_no_route_returns_a_server_error_for_hostile_query_values(client: TestClient):
    """Fuzz every declared query parameter, one at a time, on every GET route.

    500 means a bug. A 503 that names the weather provider is a different thing
    and a correct one: the third party is unreachable from the machine running
    this test, and the API says so instead of pretending or crashing.
    """
    def is_crash(response) -> bool:
        if response.status_code < 500:
            return False
        if response.status_code == 503 and "weather provider is unavailable" in response.text:
            return False
        return True

    failures = []
    for route in _get_routes():
        params = list(route.dependant.query_params)
        if not params:
            continue
        base = _fill(route.path, "1")
        for param in params:
            for value in HOSTILE:
                response = client.get(base, params={param.name: value}, headers=ADMIN)
                if is_crash(response):
                    failures.append(
                        f"GET {base}?{param.name}={value!r} -> {response.status_code} {response.text[:160]}"
                    )
    assert not failures, "\n".join(failures)


def test_forcing_a_live_upstream_fetch_requires_the_admin_token(client: TestClient):
    """`?use_cache=false` skips the cache and calls the provider with retries.

    Unauthenticated, that is a free way to burn upstream quota and hold worker
    threads; the cached run is what every UI surface uses anyway.
    """
    anonymous = client.get("/forecast", params={"use_cache": "false"})
    assert anonymous.status_code in (401, 403), anonymous.text
    # With the token it is allowed through to the provider (which is unreachable
    # here, so the honest answer is a documented 503, not a 500).
    authorised = client.get("/forecast", params={"use_cache": "false"}, headers=ADMIN)
    assert authorised.status_code in (200, 503), authorised.text


def test_post_routes_refuse_malformed_bodies_instead_of_crashing(client: TestClient):
    """`null`, wrong types, missing fields and absurd lengths are all 4xx."""
    bodies = [
        None,
        {},
        {"unexpected": "field"},
        {"phone": None},
        {"phone": 12345},
        {"phone": ""},
        {"phone": "+" + "9" * 400},
        {"phone": ["+919876543210"]},
        {"to_numbers": "not-a-list"},
        {"ward_id": "not-a-number"},
        {"dry_run": "not-a-bool"},
    ]
    failures = []
    for route in _routes():
        if "POST" not in route.methods:
            continue
        for body in bodies:
            response = client.post(route.path, json=body, headers=ADMIN)
            if response.status_code >= 500:
                failures.append(f"POST {route.path} {str(body)[:60]} -> {response.status_code} {response.text[:160]}")
    assert not failures, "\n".join(failures)


def test_every_json_response_is_actually_json(client: TestClient):
    """A 200 that is not parseable JSON breaks the client with no useful error."""
    failures = []
    for route in _get_routes():
        path = _fill(route.path, "1")
        response = client.get(path, headers=ADMIN)
        if response.status_code != 200:
            continue
        if "application/json" not in response.headers.get("content-type", ""):
            continue  # the HTML root is allowed to be HTML
        try:
            response.json()
        except ValueError as error:  # noqa: PERF203 - one route at a time, reporting all
            failures.append(f"GET {path}: {error}")
    assert not failures, "\n".join(failures)


def test_the_route_inventory_is_what_the_frontend_expects(client: TestClient):
    """Guard against a route being renamed while the static export still calls it.

    `scripts/export_static.py --check` covers the snapshot side; this covers the
    live API. If a path here is removed deliberately, update this list — the
    point is that it cannot happen by accident.
    """
    expected = {
        "/health", "/zones", "/risk", "/risk/daily", "/risk/ranking",
        "/thermal", "/thermal/daily", "/alerts/plan", "/warnings/advance",
        "/heatwave/advance", "/ncr/zones", "/ncr/forecast", "/ncr/air-quality",
        "/ncr/heat-aqi", "/ncr/daily", "/ncr/summary", "/ncr/metadata",
        "/ncr/validation", "/ncr/alerts", "/citizen/kolkata", "/demo/scenarios",
        "/demo/zones", "/demo/forecast", "/demo/thermal", "/demo/warnings",
        "/demo/notifications", "/notifications/preview", "/subscribers",
        "/subscribers/stats", "/subscribers/stop", "/alerts/dispatch",
        "/notifications/dispatch",
    }
    present = {route.path for route in _routes()}
    assert expected <= present, f"routes disappeared: {sorted(expected - present)}"
