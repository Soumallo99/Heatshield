"""The globe's live tracking layers: aircraft, earthquakes, satellites.

Everything here runs with the upstreams faked. That is the point of the file as
much as it is a convenience: these three layers reach *other people's* free
services, and a suite that depended on adsb.lol, the USGS and CelesTrak being
up would fail for somebody else's reasons — in CI most of all.

What is actually being asserted is the property the layers claim:

  * an upstream that does not answer produces an honest `available: false`
    payload naming the upstream, never a synthetic row;
  * a row that cannot be trusted (no position, a stale fix, an element set that
    will not initialise) is *dropped*, never defaulted to something drawable;
  * nothing in the browser talks to a tracking provider — the app calls
    `/api/live/*` and this process does the fetching;
  * no key is involved, because there is no key to send.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core import config
from core import live

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"
GLOBE = WEB / "src" / "globe"

# Real shapes, taken from the three providers. Not invented: the aircraft entry
# is an adsb.lol `/v2/point` row, the feature is a USGS GeoJSON summary entry
# and the satellite row is one CelesTrak OMM (JSON) record.
AIRCRAFT_PAYLOAD = {
    "ac": [
        {"hex": "800446", "type": "adsb_icao", "flight": "BDA201  ", "r": "VT-BDM", "t": "B752",
         "alt_baro": 38000, "gs": 451.0, "track": 304.43, "lat": 24.757187, "lon": 84.574992,
         "seen_pos": 0.241},
        {"hex": "80095e", "type": "adsb_icao_nt", "alt_baro": "ground", "gs": 0.0,
         "lat": 20.257974, "lon": 85.805869, "seen_pos": 0.074},
        {"hex": "deadbee", "flight": "STALE   ", "alt_baro": 35000, "lat": 22.1, "lon": 88.1,
         "seen_pos": 900},
        {"hex": "nofix", "flight": "NOFIX   ", "alt_baro": 36000, "lat": None, "lon": None,
         "seen_pos": 0.1},
    ]
}

EARTHQUAKE_PAYLOAD = {
    "type": "FeatureCollection",
    "features": [
        {"id": "us7000ti1p",
         "properties": {"mag": 6.5, "place": "169 km W of Nikolski, Alaska", "time": 1789654792210,
                        "type": "earthquake", "tsunami": 1, "url": "https://earthquake.usgs.gov/x",
                        "magType": "mww"},
         "geometry": {"type": "Point", "coordinates": [-171.3756, 52.8594, 98]}},
        {"id": "us7000tgrk",
         "properties": {"mag": 2.5, "place": "126 km NNE of Teluknaga, Indonesia",
                        "time": 1789161835907, "type": "earthquake", "tsunami": 0},
         "geometry": {"type": "Point", "coordinates": [106.8742, -4.9832, 372]}},
        {"id": "blast1",
         "properties": {"mag": 4.4, "place": "quarry blast", "time": 1789654792210,
                        "type": "quarry blast", "tsunami": 0},
         "geometry": {"type": "Point", "coordinates": [10.0, 10.0, 0]}},
    ],
}

SATELLITE_PAYLOAD = [
    {"OBJECT_NAME": "ISS (ZARYA)", "OBJECT_ID": "1998-067A", "EPOCH": "2026-09-18T03:25:38.782272",
     "MEAN_MOTION": 15.49160218, "ECCENTRICITY": 0.00048228, "INCLINATION": 51.6307,
     "RA_OF_ASC_NODE": 200.0361, "ARG_OF_PERICENTER": 152.4527, "MEAN_ANOMALY": 207.6718,
     "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 25544, "ELEMENT_SET_NO": 999,
     "REV_AT_EPOCH": 58616, "BSTAR": 0.00011125122, "MEAN_MOTION_DOT": 5.718e-5,
     "MEAN_MOTION_DDOT": 0},
    {"OBJECT_NAME": "UNNAMED DEBRIS", "OBJECT_ID": "2011-037PF", "EPOCH": "2026-09-17T21:51:18",
     "MEAN_MOTION": 12.44528997, "ECCENTRICITY": 0.0943724, "INCLINATION": 51.6466,
     "RA_OF_ASC_NODE": 82.5804, "ARG_OF_PERICENTER": 128.7321, "MEAN_ANOMALY": 240.1795,
     "NORAD_CAT_ID": 49271, "BSTAR": 0.019654},
    # No name and no usable elements: an unlabelled dot is noise, and a set
    # that cannot be initialised cannot be drawn honestly.
    {"OBJECT_NAME": "   ", "NORAD_CAT_ID": None},
    {"OBJECT_NAME": "NO ELEMENTS", "NORAD_CAT_ID": 99999},
]


@pytest.fixture(autouse=True)
def _forget_cached_payloads():
    """One test's cached live payload must not answer another test.

    Same reasoning as the API's own answer cache: a success held for twenty
    seconds is right in production and wrong inside one pytest process.
    """
    live.clear_cache()
    yield
    live.clear_cache()


@pytest.fixture
def upstream(monkeypatch):
    """Fake `core.live.fetch_json`, counting the calls and recording them."""
    calls: list[dict] = []

    def fake(url, *, params=None, timeout=None, retries=None):
        calls.append({"url": url, "params": params, "timeout": timeout, "retries": retries})
        if fake.raise_error is not None:
            raise fake.raise_error
        return json.loads(json.dumps(fake.payload))

    def use(payload):
        """Point the fake at a payload, forgetting anything cached before it.

        Without the `clear_cache`, a test that swaps payloads mid-test would be
        answered from the previous one — and would pass or fail depending on
        which other tests ran first.
        """
        fake.payload = payload
        fake.raise_error = None
        live.clear_cache()

    fake.calls = calls
    fake.use = use
    fake.payload: object = None
    fake.raise_error: Exception | None = None
    monkeypatch.setattr(live, "fetch_json", fake)
    monkeypatch.setattr(config, "LIVE_ENABLED", True)
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ------------------------------------------------------------------ 1. routes

def test_the_three_layers_are_public_reads_and_listed_at_the_root(client):
    paths = {route.path for route in app.routes if getattr(route, "path", "").startswith("/live/")}
    assert paths == {"/live/aircraft", "/live/earthquakes", "/live/satellites"}, paths

    # None of them is administrative: there is nothing here an operator must
    # protect, and nothing a visitor could abuse. (The group whitelist is the
    # guard on the one parameter that reaches an upstream query interface.)
    for route in app.routes:
        if getattr(route, "path", "").startswith("/live/"):
            assert "GET" in getattr(route, "methods", set()), route.path
            assert not getattr(route, "dependencies", []), route.path

    banner = client.get("/").json()
    for path in sorted(paths):
        assert path in banner["endpoints"], path


def test_every_live_source_is_keyless_and_stays_out_of_the_browser():
    """No key, and no tracking host in anything the browser loads."""
    source = (ROOT / "core" / "live.py").read_text(encoding="utf-8")
    # Comments are stripped first: this file explains at length why it uses no
    # credentials, and that prose is the point.
    code = "\n".join(line.split("#")[0] for line in source.splitlines())
    lowered = code.lower()
    # Word-boundary patterns rather than substrings: `sort(key=lambda …)` is not
    # a credential, and a check that says it is gets "fixed" by being deleted.
    for forbidden in (r"api[_\- ]?key", r"[?&]key=", r"token=", r"authorization", r"secret"):
        assert not re.search(forbidden, lowered), forbidden

    # The browser must only ever ask this origin. A direct fetch to a tracking
    # provider would break the promise in THIRD-PARTY.md, and it would also
    # break on a static host with a CSP that allows our own origin only.
    # (Naming a provider in a comment is required — that is the attribution —
    # so the check is for a URL, not for the word.)
    for name in ("liveData.js", "live.js", "HeatGlobe.jsx"):
        text = (GLOBE / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://(?:api\.)?(?:adsb\.lol|usgs\.gov|celestrak\.org)", text), name
        assert not re.search(r"fetch\(\s*[`'\"]https?://", text), name
    live_data = (GLOBE / "liveData.js").read_text(encoding="utf-8")
    assert "./api/live/" in live_data


# ------------------------------------------------------------- 2. the payload

def test_a_payload_always_names_its_source_even_when_it_has_nothing(upstream):
    upstream.raise_error = live.LiveSourceError("https://api.adsb.lol did not answer: timeout")
    payload = live.aircraft()
    assert payload["available"] is False
    assert payload["data"] == []
    assert payload["count"] == 0
    # The operator needs to know whose status page to look at.
    assert payload["source"]["name"] == "adsb.lol"
    assert "adsb.lol" in payload["notice"]
    assert "timeout" in payload["notice"]
    assert payload["layer"] == "aircraft"
    assert payload["fetched_at"]


def test_an_upstream_failure_is_reported_and_never_filled_in(client, upstream):
    """The one thing this file exists to prove: failure is not data."""
    upstream.raise_error = live.LiveSourceError("connection reset by peer")
    for path in ("/live/aircraft", "/live/earthquakes", "/live/satellites"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:200])
        body = response.json()
        assert body["available"] is False, path
        assert body["data"] == [], path
        assert body["notice"], path
        # Not a server error, and not cached as one either.
        assert response.headers["cache-control"] == "no-store", path


# ------------------------------------------------------------- 3. aircraft

def test_aircraft_rows_are_normalised_from_the_provider_shape(upstream):
    upstream.use(AIRCRAFT_PAYLOAD)
    payload = live.aircraft(lat=22.5726, lon=88.3639, radius_nm=250)
    assert payload["available"] is True
    rows = payload["data"]
    # Four upstream rows: one has no fix at all, one stopped reporting 15
    # minutes ago. Two remain, and they are the two you can trust.
    assert [row["icao"] for row in rows] == ["800446", "80095e"]
    highest = rows[0]
    assert highest["callsign"] == "BDA201"          # the padded provider field
    assert highest["registration"] == "VT-BDM"
    assert highest["type"] == "B752"
    assert highest["lat"] == 24.757187 and highest["lon"] == 84.574992
    # ADS-B reports feet; everything else in HeatShield is metres.
    assert highest["alt_m"] == pytest.approx(38000 * 0.3048, abs=0.1)
    assert highest["on_ground"] is False
    assert highest["speed_kts"] == 451.0 and highest["heading_deg"] == 304.43
    # "ground" is a real answer for an aircraft on the apron, not a missing one.
    assert rows[1]["on_ground"] is True and rows[1]["alt_m"] is None
    assert payload["window"] == {"lat": 22.5726, "lon": 88.3639, "radius_nm": 250}
    url = upstream.calls[0]["url"]
    assert url.startswith("https://api.adsb.lol/v2/point/"), url


def test_an_aircraft_without_a_usable_position_is_dropped_not_drawn_at_zero(upstream):
    """A fix that is missing, impossible or stale is not a fix.

    Drawing it anyway would put an aircraft at 0°N 0°E — or, worse, leave a
    frozen aircraft hovering where a feeder last heard it — and nothing on the
    globe would tell the operator which is which.
    """
    upstream.use(AIRCRAFT_PAYLOAD)
    rows = live.aircraft()["data"]
    assert "nofix" not in [row["icao"] for row in rows]
    assert "deadbee" not in [row["icao"] for row in rows]      # seen_pos 900 s
    assert live.AIRCRAFT_MAX_FIX_AGE_S == 120

    # Impossible coordinates are refused too, however they arrive.
    upstream.use({"ac": [{"hex": "x", "lat": 91.0, "lon": 181.0, "seen_pos": 0},
                         {"hex": "y", "lat": 22.5, "lon": 88.3, "seen_pos": 0}]})
    assert [row["icao"] for row in live.aircraft()["data"]] == ["y"]

    # A limit truncates, and says so: an operator seeing 2 of 4 must be able to
    # tell that from "there are only two".
    upstream.use(AIRCRAFT_PAYLOAD)
    limited = live.aircraft(limit=1)
    assert limited["count"] == 1 and limited["truncated"] is True


# ------------------------------------------------------------- 4. earthquakes

def test_earthquakes_are_filtered_by_magnitude_and_strongest_first(upstream):
    upstream.use(EARTHQUAKE_PAYLOAD)
    payload = live.earthquakes(window="day", min_mag=2.5)
    assert payload["available"] is True
    rows = payload["data"]
    # The 6.5 and the 2.5 are earthquakes; the 4.4 is a quarry blast, which is
    # a real event but not this layer's subject.
    assert [row["id"] for row in rows] == ["us7000ti1p", "us7000tgrk"]
    assert rows[0]["mag"] == 6.5 and rows[0]["place"] == "169 km W of Nikolski, Alaska"
    # GeoJSON is [lon, lat, depth]; the globe needs lat, lon.
    assert rows[0]["lat"] == 52.8594 and rows[0]["lon"] == -171.3756
    assert rows[0]["depth_km"] == 98.0
    assert rows[0]["tsunami"] is True and rows[0]["url"]
    # Milliseconds since the epoch, as UTC ISO, because that is what the UI shows.
    assert rows[0]["time_utc"] == "2026-09-17T14:19:52+00:00"
    assert payload["window"] == {"window": "day", "min_mag": 2.5}

    upstream.use(EARTHQUAKE_PAYLOAD)
    assert live.earthquakes(min_mag=5.0)["data"][0]["id"] == "us7000ti1p"

    # The check that keeps this from being vacuous: the filter is a filter.
    assert [row["id"] for row in live.earthquakes(min_mag=9.0)["data"]] == []


def test_the_earthquake_window_is_bounded_and_the_month_feed_is_not_offered(client, upstream):
    """`all_month.geojson` is a multi-megabyte feed: offering it would be
    offering a layer that costs more than it is worth.
    """
    upstream.use(EARTHQUAKE_PAYLOAD)
    assert "month" not in live.EARTHQUAKE_WINDOWS
    with pytest.raises(ValueError):
        live.earthquakes(window="month")
    # Through the route it never reaches the library: FastAPI refuses it.
    assert client.get("/live/earthquakes", params={"window": "month"}).status_code == 422
    assert client.get("/live/earthquakes", params={"window": "week"}).status_code == 200


# ------------------------------------------------------------- 5. satellites

def test_satellites_are_served_as_element_sets_not_positions(upstream):
    """Positions are propagated in the browser, once per frame, from one set.

    Sending positions from here would mean a number that is already wrong by
    the time it is drawn, and an upstream round trip per frame to keep it
    right.
    """
    upstream.use(SATELLITE_PAYLOAD)
    payload = live.satellites(group="stations")
    assert payload["available"] is True
    rows = payload["data"]
    assert len(rows) == 2
    iss = rows[0]
    assert iss["name"] == "ISS (ZARYA)" and iss["norad_id"] == 25544
    assert iss["group"] == "stations"
    # The elements, in HeatShield's own naming — no SCREAMING_CASE from CelesTrak.
    assert iss["mean_motion"] == 15.49160218
    assert iss["inclination"] == 51.6307
    assert iss["eccentricity"] == 0.00048228
    assert iss["ra_of_asc_node"] == 200.0361
    assert iss["arg_of_pericenter"] == 152.4527
    assert iss["mean_anomaly"] == 207.6718
    assert iss["bstar"] == 0.00011125122
    assert iss["rev_at_epoch"] == 58616
    assert iss["epoch"].startswith("2026-09-18")
    # And crucially: no position. There is nothing here to be stale.
    assert not any(key in iss for key in ("lat", "lon", "alt_km"))
    assert upstream.calls[0]["params"] == {"GROUP": "stations", "FORMAT": "json"}


def test_a_satellite_row_that_cannot_be_labelled_or_propagated_is_dropped(upstream):
    upstream.use(SATELLITE_PAYLOAD)
    names = [row["name"] for row in live.satellites()["data"]]
    assert "NO ELEMENTS" not in names          # no mean_motion / inclination
    assert "ISS (ZARYA)" in names

    upstream.use([{"OBJECT_NAME": "HALF A SET", "NORAD_CAT_ID": 1, "MEAN_MOTION": 15.5}])
    assert live.satellites()["data"] == []     # no inclination -> cannot propagate

    upstream.use([{"MEAN_MOTION": 15.5, "INCLINATION": 51.6}])   # nothing to label
    assert live.satellites()["data"] == []


def test_the_satellite_group_is_a_whitelist(client, upstream):
    """`group` reaches CelesTrak's query interface, so it is not a free string."""
    upstream.use(SATELLITE_PAYLOAD)
    assert "stations" in live.SATELLITE_GROUPS
    with pytest.raises(ValueError):
        live.satellites(group="../../../NORAD/elements/gp.php?GROUP=stations&FORMAT=tle")
    response = client.get("/live/satellites", params={"group": "not-a-group"})
    assert response.status_code == 422, response.text[:200]
    # The refusal is a validation error, not a crash, and not a request upstream.
    assert upstream.calls == []
    assert client.get("/live/satellites", params={"group": "gps-ops"}).status_code == 200


# ------------------------------------------------------------- 6. caching

def test_success_is_reused_and_failure_is_never_cached(upstream):
    # A failure must not be remembered: an outage that lasts thirty seconds
    # must not be shown on screen for a minute after it clears. So the failure
    # comes first, while the cache is still empty.
    upstream.raise_error = live.LiveSourceError("boom")
    assert live.aircraft()["available"] is False
    upstream.use(AIRCRAFT_PAYLOAD)
    assert live.aircraft()["available"] is True, "the failure was cached"
    assert len(upstream.calls) == 2

    # Two operators (or two presses) inside the TTL are one upstream request:
    # these are free services, not ours.
    live.clear_cache()
    first = live.aircraft()
    second = live.aircraft()
    assert first["available"] and second["available"]
    assert len(upstream.calls) == 3

    # And a real payload already held still wins over a fresh failure: it is
    # real, it carries the time it was fetched, and dropping the layer every
    # time an upstream blips would make the globe useless mid-shift.
    upstream.raise_error = live.LiveSourceError("boom")
    held = live.aircraft()
    assert held["available"] is True and held["fetched_at"]
    assert len(upstream.calls) == 3


def test_a_short_ttl_expires_and_a_zero_ttl_asks_every_time(upstream, monkeypatch):
    upstream.use(AIRCRAFT_PAYLOAD)
    monkeypatch.setattr(config, "LIVE_AIRCRAFT_TTL_S", 0)
    live.aircraft()
    live.aircraft()
    assert len(upstream.calls) == 2, "a zero TTL is a real setting, not a typo"


# ------------------------------------------------------------- 7. the switch

def test_the_layers_can_be_turned_off_for_a_deployment(client, monkeypatch):
    """A deployment with no egress gets an answer, not a timeout on every press."""
    monkeypatch.setattr(config, "LIVE_ENABLED", False)
    for path in ("/live/aircraft", "/live/earthquakes", "/live/satellites"):
        body = client.get(path).json()
        assert body["available"] is False, path
        assert body["data"] == [], path
        assert "HS_LIVE_LAYERS" in body["notice"], path
        # Off means off: not a request, not a retry, not a wait.
        assert body["source"]["name"]


def test_the_disabled_switch_never_reaches_the_network(monkeypatch):
    monkeypatch.setattr(config, "LIVE_ENABLED", False)

    def explode(**kwargs):
        raise AssertionError("a disabled layer must not be fetched")

    monkeypatch.setattr(live, "fetch_json", explode)
    for call in (live.aircraft, live.earthquakes, live.satellites):
        assert call()["available"] is False


# ------------------------------------------------------------- 8. the app

def test_the_routes_answer_with_the_same_payload_the_library_builds(client, upstream):
    upstream.use(AIRCRAFT_PAYLOAD)
    body = client.get("/live/aircraft", params={"lat": 28.6139, "lon": 77.209, "radius_nm": 100})
    assert body.status_code == 200
    payload = body.json()
    assert payload["available"] is True
    assert payload["count"] == 2
    # The globe asks for the city it is looking at; the URL must say so.
    assert "28.6139" in upstream.calls[-1]["url"]
    assert payload["source"] == live.SOURCES["aircraft"]

    # Live data is never replayed by the shared response cache: it cannot tell
    # a successful payload from a degraded one.
    assert body.headers["cache-control"] == "no-store"

    upstream.use(EARTHQUAKE_PAYLOAD)
    assert client.get("/live/earthquakes").json()["count"] == 2
    upstream.use(SATELLITE_PAYLOAD)
    assert client.get("/live/satellites").json()["count"] == 2


def test_the_shipped_worker_names_the_cache_that_ships_this_code(built_site):
    """A new asset in an old cache is the Citizen-tab bug all over again.

    The globe's live layers are new frontend code. If the installed service
    worker still answers from a cache built before they existed, the operator
    presses "Aircraft" and nothing happens — with no error anywhere.
    """
    worker = (built_site / "sw.js").read_text(encoding="utf-8")
    assert "heatshield-phone-v7" in worker
    # And the /api/live/* requests those layers make are already handled by the
    # worker's network-first branch, so they need no new host and no new cache.
    assert "api/" in worker
