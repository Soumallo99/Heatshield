"""
CAP 1.2 feed tests — the interoperability layer.

These tests exist because a CAP document that looks right and is subtly
invalid is worse than no feed at all: SACHET (or any aggregator) will reject
it silently, and the warning simply does not go out. So the things asserted
here are the things a validator would check — element presence, element
*order*, lat/lon order, and the refusal to publish synthetic data.
"""
from __future__ import annotations

from datetime import date, datetime
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pytest

from core import cap, i18n
from core.cap import (CAP_NAMESPACE, alerts_geojson, build_cap, cap_payload,
                      cap_xml, certainty_for, make_identifier, severity_for,
                      urgency_for)

IST = ZoneInfo("Asia/Kolkata")


def _events(count: int = 2) -> list[dict]:
    base = [
        {"ward_id": 24, "ward_name": "Ward 24", "event_date": date(2026, 5, 21),
         "lead_days": 3, "risk_score": 78.4, "risk_band": "Critical",
         "wbgt_peak_c": 32.6, "utci_peak_c": 44.1, "tmax_ward_c": 41.2,
         "uhi_delta_c": 2.4, "exposed_population": 12489, "population": 31000},
        {"ward_id": 57, "ward_name": "Ward 57", "event_date": date(2026, 5, 22),
         "lead_days": 4, "risk_score": 66.1, "risk_band": "Danger",
         "wbgt_peak_c": 30.9, "utci_peak_c": 41.7, "tmax_ward_c": 39.4,
         "uhi_delta_c": 1.8, "exposed_population": 8240, "population": 25000},
    ]
    return base[:count]


def _q(tag: str) -> str:
    """Qualify a tag with the CAP namespace — parsed elements carry it."""
    return f"{{{CAP_NAMESPACE}}}{tag}"


def _parse(xml_text: str) -> ET.Element:
    root = ET.fromstring(xml_text)
    assert root.tag == _q("alert")
    return root


# --------------------------------------------------------------- derivations
def test_severity_urgency_and_certainty_follow_a_documented_table():
    assert severity_for("Caution") == "Minor"
    assert severity_for("Danger") == "Moderate"
    assert severity_for("Critical") == "Severe"
    assert severity_for("Extreme") == "Extreme"

    assert urgency_for(0) == "Immediate"
    assert urgency_for(2) == "Expected"
    assert urgency_for(5) == "Future"

    # forecast confidence falls with lead time
    assert certainty_for(1) == "Likely"
    assert certainty_for(4) == "Possible"


def test_identifier_is_deterministic_for_the_same_batch():
    sent = datetime(2026, 5, 18, 6, 0, tzinfo=IST)
    first = make_identifier(_events(), sent)
    second = make_identifier(list(reversed(_events())), sent)   # order must not matter
    assert first == second
    assert first.startswith("HS-KMC-20260518T060000-")
    assert make_identifier(_events(1), sent) != first


# --------------------------------------------------------------- XML document
def test_cap_document_carries_every_required_element():
    root = _parse(cap_xml(_events(), languages=("en",)))
    tags = [child.tag for child in root]
    for required in ("identifier", "sender", "sent", "status", "msgType", "scope"):
        assert _q(required) in tags, required
    info = root.find(_q("info"))
    assert info is not None
    for required in ("language", "category", "event", "urgency", "severity",
                     "certainty", "senderName", "headline", "description",
                     "instruction", "area"):
        assert info.find(_q(required)) is not None, required


def test_element_order_follows_the_cap_1_2_sequence():
    """CAP 1.2 is a sequence, not a bag. Out-of-order elements fail validation."""
    alert_order = ("identifier", "sender", "sent", "status", "msgType", "source",
                   "scope", "restriction", "addresses", "code", "note",
                   "references", "incidents", "info")
    info_order = ("language", "category", "event", "responseType", "urgency",
                  "severity", "certainty", "audience", "eventCode", "effective",
                  "onset", "expires", "senderName", "headline", "description",
                  "instruction", "web", "contact", "parameter", "resource", "area")

    root = _parse(cap_xml(_events(), languages=("en",)))
    tags = [child.tag for child in root]
    assert tags == sorted(tags, key=lambda t: alert_order.index(t.split("}")[-1]))

    info = root.find(_q("info"))
    tags = [child.tag for child in info]
    assert tags == sorted(tags, key=lambda t: info_order.index(t.split("}")[-1]))

    area = info.find(_q("area"))
    order = ("areaDesc", "polygon", "circle", "geocode", "altitude", "ceiling")
    tags = [child.tag for child in area]
    assert tags == sorted(tags, key=lambda t: order.index(t.split("}")[-1]))


def test_one_info_block_per_language():
    root = _parse(cap_xml(_events()))
    languages = [block.findtext(_q("language")) for block in root.findall(_q("info"))]
    assert languages == ["en-IN", "hi-IN", "bn-IN"]

    root = _parse(cap_xml(_events(), languages=("en", "bn")))
    languages = [block.findtext(_q("language")) for block in root.findall(_q("info"))]
    assert languages == ["en-IN", "bn-IN"]


def test_polygons_are_latitude_first_and_closed():
    """CAP is lat,lon; GeoJSON is lon,lat. Getting this backwards is the
    classic CAP bug, and it draws the ward in the wrong hemisphere."""
    root = _parse(cap_xml(_events(1), languages=("en",)))
    polygon = root.find(f"./{_q('info')}/{_q('area')}/{_q('polygon')}").text
    pairs = [pair.split(",") for pair in polygon.split()]
    assert len(pairs) >= 4
    assert pairs[0] == pairs[-1], "a CAP polygon must close on its first point"
    lats = [float(pair[0]) for pair in pairs]
    lons = [float(pair[1]) for pair in pairs]
    # Kolkata, not Somalia
    assert 22.4 < sum(lats) / len(lats) < 22.7
    assert 88.2 < sum(lons) / len(lons) < 88.5


def test_wards_appear_as_geocoded_areas():
    root = _parse(cap_xml(_events(), languages=("en",)))
    areas = root.findall(f"./{_q('info')}/{_q('area')}")
    assert len(areas) == 2
    codes = {area.find(f"./{_q('geocode')}/{_q('value')}").text for area in areas}
    assert codes == {"24", "57"}


def test_parameters_carry_the_heatshield_quantities():
    root = _parse(cap_xml(_events(), languages=("en",)))
    names = {p.findtext(_q("valueName")) for p in root.findall(f"./{_q('info')}/{_q('parameter')}")}
    for expected in ("HS:wardCount", "HS:riskScoreMax", "HS:leadDaysMin",
                     "HS:wbgtPeakC", "HS:utciPeakC", "HS:exposedPopulation"):
        assert expected in names, expected
    # NaN must never be serialised — a CAP document with NaN in it is not XML-safe
    for value in root.findall(f"./{_q('info')}/{_q('parameter')}/{_q('value')}"):
        assert "nan" not in (value.text or "").lower()


def test_an_empty_batch_is_a_valid_document_with_no_info():
    """'Nothing to warn about' is a valid CAP message, not an error."""
    root = _parse(cap_xml([], languages=("en",)))
    assert root.findtext(_q("identifier")).endswith("-empty")
    assert root.find(_q("info")) is None


# --------------------------------------------------------------- honesty
def test_synthetic_events_are_refused():
    """A demo scenario must never reach a public alerting channel."""
    tainted = [{**_events(1)[0], "ward_name": "Ward 24 (demo-synthetic)"}]
    with pytest.raises(ValueError, match="demo/synthetic"):
        cap_payload(tainted)
    with pytest.raises(ValueError, match="demo/synthetic"):
        cap_xml(tainted)
    with pytest.raises(ValueError, match="demo/synthetic"):
        alerts_geojson(tainted)


def test_the_feed_says_the_values_are_modelled_not_measured():
    root = _parse(cap_xml(_events(1), languages=("en",)))
    note = (root.findtext(_q("note")) or "").lower()
    assert "modelled" in note
    assert "pilot" in note


def test_sachet_handoff_is_documented_in_the_payload():
    payload = cap_payload(_events())
    handoff = payload["sachet"]
    assert handoff["protocol"].startswith("CAP 1.2")
    assert "sachet.ndma.gov.in" in handoff["portal"]
    # the gap is stated, not hidden: SACHET publishes in 12, we wire 3
    assert handoff["languages_published_by_sachet"] == 12
    assert handoff["languages_wired_here"] == 3
    assert len(handoff["pending_languages"]) == 9


# --------------------------------------------------------------- JSON payload
def test_json_payload_mirrors_the_xml_and_names_both():
    payload = cap_payload(_events())
    assert payload["protocol"] == "CAP 1.2"
    assert payload["rows"] == 2
    assert payload["xml_path"] == "/alerts/cap.xml"
    assert payload["is_synthetic"] is False
    assert payload["identifier"] == make_identifier(
        _events(), datetime.fromisoformat(payload["sent"]))
    # every ward, in every language, with the exact copy that would be sent
    assert len(payload["info"]) == 3
    for block in payload["info"]:
        assert len(block["messages"]) == 2
        for message in block["messages"]:
            assert message["message"]
            assert message["sms_segments"] >= 1


def test_geojson_feed_is_a_feature_collection_with_real_geometry():
    feed = alerts_geojson(_events())
    assert feed["type"] == "FeatureCollection"
    assert feed["protocol"].startswith("GeoJSON")
    assert len(feed["features"]) == 2
    for feature in feed["features"]:
        assert feature["geometry"]["type"] in {"Polygon", "Point"}
        if feature["geometry"]["type"] == "Polygon":
            ring = feature["geometry"]["coordinates"][0]
            assert ring[0] == ring[-1], "a GeoJSON ring must close"
            # lon,lat here — the opposite order to CAP, by specification
            assert 88.2 < ring[0][0] < 88.5
        assert feature["properties"]["severity"] in {"Minor", "Moderate", "Severe", "Extreme"}


def test_geometry_status_reports_polygons_or_circles_never_silently_neither(monkeypatch, tmp_path):
    from core import geo

    geo.clear_cache()
    monkeypatch.setenv("HS_WARD_GEOJSON", str(tmp_path / "missing.geojson"))
    try:
        status = geo.geometry_status()
        assert status["wards_with_geometry"] == 0
        payload = cap_payload(_events(), wards=_wards_frame())
        assert payload["geometry"]["shape"] == "circle"
        for area in cap_payload(_events())["wards"]:
            pass
        # with no polygons the areas must fall back to area-sized circles
        root = _parse(cap_xml(_events(), languages=("en",), wards=_wards_frame()))
        circle = root.find(f"./{_q('info')}/{_q('area')}/{_q('circle')}").text
        lat, lon, radius = circle.replace(",", " ").split()
        assert 22.4 < float(lat) < 22.7
        assert float(radius) > 0
    finally:
        monkeypatch.delenv("HS_WARD_GEOJSON")
        geo.clear_cache()


def _wards_frame():
    import pandas as pd

    return pd.DataFrame([
        {"ward_id": 24, "lat": 22.5863, "lon": 88.3583, "area_km2": 1.42},
        {"ward_id": 57, "lat": 22.5100, "lon": 88.3400, "area_km2": 2.10},
    ])


def test_build_cap_accepts_a_dataframe():
    import pandas as pd

    frame = pd.DataFrame(_events())
    root = build_cap(frame, languages=("en",)).getroot()
    assert len(root.findall(f"./{_q('info')}/{_q('area')}")) == 2
