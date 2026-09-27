"""
PHASE 8 — data.gov.in / api.data.gov.in adapter
===============================================
India's Open Government Data platform is the obvious place to close the two
gaps `DATA.md` has been honest about since the beginning: **population aged
60+** and **slum share** at ward level, plus the observed weather a real
forecast-verification loop needs.

This module is the adapter that makes those datasets usable *when they are
available*, and it is deliberately built so that its absence changes nothing.

The rule it must obey
---------------------
`AGENTS.md` §11: *"Keep it working keyless."* api.data.gov.in requires an API
key, and every HeatShield-in-a-box guarantee — `git clone` → `start.sh`, CI
with no secrets, a judge with no account — depends on that never becoming a
hard requirement. So:

* No key ⇒ :func:`configured` is False and :func:`fetch_resource` raises
  :class:`NotConfiguredError`. The pipeline never calls this module on its
  critical path; nothing degrades, nothing 500s.
* Key present ⇒ the same code fetches real records.

What is deliberately NOT here
-----------------------------
**No invented resource IDs.** api.data.gov.in addresses a dataset by an opaque
resource id, and those ids are not stable across re-uploads. Every entry in
:data:`CATALOGUE` therefore ships with `resource_id: None` and the steps to
find the real one. A placeholder that looks authoritative is worse than an
empty slot: it would make a 404 look like a data outage.

**No silent imputation for the missing demographics.** This adapter can *load*
a 60+ or slum column once a real source is configured. It cannot manufacture
one, and it will not substitute a proxy that would change what the
vulnerability index claims to measure.

Run standalone:  python -m core.datagov
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable
from urllib.parse import urlencode

import urllib.request
import urllib.error

# --------------------------------------------------------------------------- #
# 0. Endpoints and configuration
# --------------------------------------------------------------------------- #

#: api.data.gov.in resource endpoint. ``{resource_id}`` is per-dataset.
RESOURCE_URL = "https://api.data.gov.in/resource/{resource_id}"
#: The human-facing catalogue — where a resource id is actually found.
PORTAL_URL = "https://data.gov.in"
API_PORTAL_URL = "https://api.data.gov.in"

DEFAULT_TIMEOUT_S = 15
DEFAULT_LIMIT = 100
MAX_LIMIT = 10_000


class NotConfiguredError(RuntimeError):
    """No API key — the adapter is inert, by design."""


class UpstreamError(RuntimeError):
    """data.gov.in answered, but not with records."""


def api_key() -> str:
    """The configured key, or "" — never raises, never logs the value."""
    return (os.getenv("HS_DATAGOV_API_KEY")
            or os.getenv("DATAGOV_API_KEY")
            or "").strip()


def configured() -> bool:
    return bool(api_key())


# --------------------------------------------------------------------------- #
# 1. The catalogue — what each dataset would close, and how far along it is
# --------------------------------------------------------------------------- #

#: One entry per dataset a HeatShield operator might wire up. ``resource_id``
#: is intentionally None until a human looks it up and pastes it in: these ids
#: are per-upload and guessing one would turn "not configured" into a 404 that
#: looks like an outage.
CATALOGUE: tuple[dict[str, Any], ...] = (
    {
        "slug": "census-2011-dchb-part-b-kolkata",
        "title": "Census 2011 District Census Handbook, Part B — Kolkata",
        "publisher": "Office of the Registrar General & Census Commissioner, India",
        "portal": "https://censusindia.gov.in",
        "closes_gap": "population aged 60+ per ward",
        "geography": "ward (village/town directory + PCA)",
        "status": "not wired — published as per-district PDFs; needs a parser",
        "effort": "high",
        "resource_id": None,
    },
    {
        "slug": "census-2011-c14-single-year-age",
        "title": "Census 2011 C-14 — single-year age tables",
        "publisher": "Office of the Registrar General & Census Commissioner, India",
        "portal": "https://censusindia.gov.in",
        "closes_gap": "age structure (5-year bands, town level)",
        "geography": "town / district — NOT ward",
        "status": "not wired — too coarse for a ward index; usable as a city prior",
        "effort": "medium",
        "resource_id": None,
    },
    {
        "slug": "nfhs-5-district-factsheets",
        "title": "National Family Health Survey 5 — district factsheets",
        "publisher": "Ministry of Health and Family Welfare / IIPS",
        "portal": PORTAL_URL,
        "closes_gap": "household and health proxies (partial, coarse)",
        "geography": "district — NOT ward",
        "status": "not wired — a proxy, not a substitute for ward age structure",
        "effort": "low",
        "resource_id": None,
    },
    {
        "slug": "secc-2011",
        "title": "Socio Economic and Caste Census 2011",
        "publisher": "Ministry of Rural Development",
        "portal": PORTAL_URL,
        "closes_gap": "deprivation / housing quality (partial, coarse)",
        "geography": "village / ward (urban), published aggregates",
        "status": "not wired — needs a machine-readable extract",
        "effort": "medium",
        "resource_id": None,
    },
    {
        "slug": "imd-daily-station-observations",
        "title": "IMD daily weather station observations",
        "publisher": "India Meteorological Department",
        "portal": PORTAL_URL,
        "closes_gap": "forecast bias correction and verification (AGENTS.md gap 4)",
        "geography": "station — Alipore / Dum Dum for Kolkata",
        "status": "not wired — the highest-value dataset here after the demographics",
        "effort": "low",
        "resource_id": None,
    },
    {
        "slug": "cpcb-air-quality",
        "title": "CPCB ambient air quality (station daily)",
        "publisher": "Central Pollution Control Board",
        "portal": PORTAL_URL,
        "closes_gap": "ground truth for the coupled heat–AQI layer",
        "geography": "station",
        "status": "not wired — the NCR layer currently uses Open-Meteo's CAMS reanalysis",
        "effort": "low",
        "resource_id": None,
    },
)

REQUIRED_FIELDS = ("slug", "title", "publisher", "closes_gap", "geography",
                   "status", "effort", "resource_id")


def catalogue() -> list[dict[str, Any]]:
    """The registry as plain dicts (defensive copy — callers may annotate)."""
    return [dict(entry) for entry in CATALOGUE]


def dataset(slug: str) -> dict[str, Any] | None:
    return next((dict(entry) for entry in CATALOGUE if entry["slug"] == slug), None)


def resolve(slug: str) -> str | None:
    """
    The resource id for a dataset, or None.

    Returns None — rather than raising — when the operator has not filled the
    id in yet, because "nothing configured" is a normal state for a clone.
    """
    entry = dataset(slug)
    return entry["resource_id"] if entry else None


# --------------------------------------------------------------------------- #
# 2. Fetching
# --------------------------------------------------------------------------- #

def build_url(resource_id: str, *, limit: int = DEFAULT_LIMIT, offset: int = 0,
              filters: dict[str, Any] | None = None) -> str:
    """The request URL, with the key inside it — never log this verbatim."""
    if not resource_id:
        raise ValueError("resource_id is required — find it on data.gov.in and set it in CATALOGUE")
    params: list[tuple[str, str]] = [
        ("api-key", api_key()),
        ("format", "json"),
        ("limit", str(max(1, min(limit, MAX_LIMIT)))),
        ("offset", str(max(0, offset))),
    ]
    for name, value in (filters or {}).items():
        params.append((f"filters[{name}]", str(value)))
    return RESOURCE_URL.format(resource_id=resource_id) + "?" + urlencode(params)


def _http_get(url: str, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "HeatShield/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_resource(resource_id: str, *, limit: int = DEFAULT_LIMIT, offset: int = 0,
                   filters: dict[str, Any] | None = None,
                   timeout: float = DEFAULT_TIMEOUT_S,
                   getter: Any = None) -> dict[str, Any]:
    """
    Fetch one api.data.gov.in resource and return ``{"records", "total", "meta"}``.

    Raises :class:`NotConfiguredError` with no key, and :class:`UpstreamError`
    for a transport failure or a body without records — an empty result is a
    fact about the source, not a reason to fall back to invented numbers.

    ``getter`` overrides the HTTP call (tests inject a stub here).
    """
    if not resource_id:
        raise ValueError("resource_id is required — find it on data.gov.in and set it in CATALOGUE")
    _require_key()
    url = build_url(resource_id, limit=limit, offset=offset, filters=filters)
    try:
        body = (getter or _http_get)(url, timeout)
    except Exception as exc:                       # transport, DNS, TLS, timeout
        raise UpstreamError(f"data.gov.in request failed: {exc}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"data.gov.in returned non-JSON: {body[:200]!r}") from exc

    records = payload.get("records")
    if records is None:
        raise UpstreamError(
            "data.gov.in response carried no 'records' key — check the resource id "
            f"and the api-key (body: {body[:200]!r})"
        )
    return {
        "records": records if isinstance(records, list) else [],
        "total": payload.get("total"),
        "count": payload.get("count"),
        "meta": {key: value for key, value in payload.items() if key != "records"},
    }


def _require_key() -> None:
    """The single place that decides "no key" — and the only place that words it.

    The message reassures deliberately: an operator seeing this in a log must
    learn that nothing downstream broke, not go hunting for a failure.
    """
    if not configured():
        raise NotConfiguredError(
            "HS_DATAGOV_API_KEY is not set, so data.gov.in is not reachable. "
            "The pipeline is unaffected: this adapter is never on the critical path. "
            f"Register at {API_PORTAL_URL} and set the key to enable it."
        )


def fetch_dataset(slug: str, **kwargs: Any) -> dict[str, Any]:
    """Fetch a catalogued dataset by slug.

    Checks the key before the resource id: with no key the adapter is inert and
    that is the whole story, whereas a missing id is an operator to-do.
    """
    _require_key()
    resource_id = resolve(slug)
    if not resource_id:
        entry = dataset(slug)
        raise ValueError(
            f"dataset '{slug}' has no resource id yet"
            + (f" — {entry['status']}" if entry else "")
        )
    return fetch_resource(resource_id, **kwargs)


# --------------------------------------------------------------------------- #
# 3. Status — shipped in payloads so the gap is visible, not discovered
# --------------------------------------------------------------------------- #

def status() -> dict[str, Any]:
    """Configuration state + the registry, for /integrations/datagov."""
    return {
        "configured": configured(),
        "portal": PORTAL_URL,
        "api_portal": API_PORTAL_URL,
        "note": (
            "Optional and never on the critical path. Without a key the "
            "pipeline is unchanged; with one, these datasets close the "
            "demographic gaps DATA.md documents as absent."
        ),
        "datasets_wired": sum(1 for entry in CATALOGUE if entry["resource_id"]),
        "datasets_catalogued": len(CATALOGUE),
        "datasets": catalogue(),
    }


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 78)
    print("data.gov.in adapter — optional, keyless-safe")
    print("=" * 78)
    state = status()
    print(f"configured : {state['configured']}"
          f"  ({state['datasets_wired']}/{state['datasets_catalogued']} datasets wired)")
    if not state["configured"]:
        print(f"             set HS_DATAGOV_API_KEY to enable it (register at {API_PORTAL_URL})")
        print("             HeatShield runs identically without it — nothing here is required.")
    print()
    for entry in state["datasets"]:
        print(f"  {entry['slug']}")
        print(f"      closes : {entry['closes_gap']}")
        print(f"      geo    : {entry['geography']}")
        print(f"      status : {entry['status']}")
        print(f"      id     : {entry['resource_id'] or '(none — look it up on data.gov.in)'}")
    print()
    try:
        fetch_resource("some-resource-id")
        print("fetch_resource: unexpectedly succeeded with no key")
    except NotConfiguredError as exc:
        print("no-key behaviour: NotConfiguredError —", str(exc)[:110] + "…")
