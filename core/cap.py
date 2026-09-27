"""
PHASE 8 — CAP 1.2 alert feed and the SACHET hand-off
====================================================
HeatShield composes a ward-level warning; until now the only thing that could
read it was HeatShield. Twilio is a pilot channel, not a public-warning
channel: it reaches subscribers, not the district administration, and it cannot
be ingested by the national alerting infrastructure.

This module emits the same warning as a **CAP 1.2** message (OASIS Common
Alerting Protocol, also ITU-T X.1303 / ISO 22322) — the format India's
**SACHET** portal (``sachet.ndma.gov.in``, NDMA) consumes and redistributes in
twelve regional languages. One warning, one composition path, many channels.

What makes it CAP-shaped
------------------------
* ``<identifier>`` is **deterministic** for a given batch: the same wards
  warned at the same minute produce the same identifier, so a consumer can
  de-duplicate a re-poll without tracking state.
* One ``<info>`` block **per language** (en / hi / bn). CAP is explicit that
  repeat ``<info>`` blocks are translations of the *same* event, which is
  exactly the SACHET multilingual model. English is always present; the others
  are added only when requested.
* One ``<area>`` per ward, carrying the real KMC ward polygon as a
  ``<polygon>`` (or an area-sized ``<circle>`` when the geometry is missing —
  see :mod:`core.geo` — and the feed says which it used).
* HeatShield's own quantities ride in ``<parameter>`` blocks, which is the
  sanctioned extension point. Risk score, lead time, WBGT, UTCI, UHI increment
  and exposed population all travel with the alert instead of being lost.
* ``<severity>`` / ``<urgency>`` / ``<certainty>`` are derived from the risk
  band and the lead time by a documented table, not by vibes.

Honesty rules carried over from the rest of the pipeline
--------------------------------------------------------
* Every message carries a ``<note>``: the values are **modelled from forecast**,
  not measured, and this is a pilot system.
* Demo / synthetic events are **refused** — :func:`build_cap` raises on a row
  stamped ``demo-synthetic``. A synthetic scenario must never reach a public
  alerting channel, for the same reason live dispatch refuses it.
* An empty event list produces a valid, empty feed rather than an error.

Run standalone:  python -m core.cap
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd

from core import geo, i18n
from core.config import TIMEZONE, WEB_BASE

# --------------------------------------------------------------------------- #
# 0. Constants
# --------------------------------------------------------------------------- #

CAP_NAMESPACE = "urn:oasis:names:tc:emergency:cap:1.2"
# The issuing authority's CAP sender address. This is a pilot placeholder —
# SACHET ingestion requires the real authority address registered with NDMA.
SENDER = "heatshield@kolkata.example"
CONTACT = "heatshield-kmc-pilot@example.org"
SENDER_NAME_FALLBACK = "HeatShield"
SOURCE = "HeatShield-KMC-pilot"

#: CAP <severity> per HeatShield risk band.
SEVERITY_BY_BAND: dict[str, str] = {
    "Caution": "Minor",
    "Danger": "Moderate",
    "Critical": "Severe",
    "Extreme": "Extreme",
}

#: CAP <urgency>: how soon the event is expected.
URGENCY_IMMEDIATE_MAX_LEAD = 0     # happening now
URGENCY_EXPECTED_MAX_LEAD = 2      # within a couple of days
# beyond that: "Future"

#: CAP <certainty>: forecast confidence falls as lead time grows.
CERTAINTY_LIKELY_MAX_LEAD = 2

#: CAP <category> — a heat warning is both a weather and a health event.
CATEGORIES: tuple[str, ...] = ("Met", "Health")

#: The US SAME code for an Excessive Heat Warning. Included because it is the
#: heat event code most CAP consumers already recognise; replaced with the
#: national code once NDMA publishes one for SACHET ingestion.
EVENT_CODE_NAME = "SAME"
EVENT_CODE_VALUE = "EH.W"

NOTE = (
    "Pilot heat-health early warning. Values are MODELLED from forecast weather "
    "(WBGT, UTCI, risk score) — not measured. Issued by the HeatShield KMC pilot; "
    "verify against IMD bulletins before operational use."
)

#: Where this feed is meant to go, shipped in the payload so the hand-off is
#: self-documenting rather than living in someone's notebook.
SACHET_HANDOFF: dict[str, Any] = {
    "portal": "https://sachet.ndma.gov.in",
    "operator": "National Disaster Management Authority (NDMA), Government of India",
    "protocol": "CAP 1.2 (OASIS standard; ITU-T X.1303 / ISO 22322)",
    "status": "Documented and format-valid. Live ingestion requires NDMA onboarding "
              "of the issuing authority — an administrative step, not a code change.",
    "endpoints": {
        "json": "/alerts/cap",
        "xml": "/alerts/cap.xml",
        "geojson": "/alerts/geojson",
    },
    "languages_published_by_sachet": 12,
    "languages_wired_here": len(i18n.SUPPORTED_LANGUAGES),
    "pending_languages": [code for code, _label, state in i18n.SACHET_TARGET_LANGUAGES
                          if not state.startswith("wired")],
    "next_steps": [
        "Register the issuing authority (KMC / state disaster management authority) with NDMA.",
        "Replace SENDER with the authority's real CAP sender address.",
        "Have the Hindi and Bengali copy reviewed and signed off by the authority.",
        "Add the remaining SACHET languages to core.i18n._TEMPLATES as they are reviewed.",
        "Poll /alerts/cap.xml on the same cadence as scripts/schedule.py and POST to SACHET.",
    ],
}

BAND_ORDER = ("Normal", "Caution", "Danger", "Critical", "Extreme")

# Emit the CAP namespace as the document's default namespace (`xmlns=`), not as
# a generated prefix. ElementTree would otherwise write ns0: on every element,
# which is valid XML and still unreadable to a human checking a feed by eye.
ET.register_namespace("", CAP_NAMESPACE)


# --------------------------------------------------------------------------- #
# 1. Derivations — documented tables, not ad-hoc strings
# --------------------------------------------------------------------------- #

def severity_for(band: str) -> str:
    return SEVERITY_BY_BAND.get(str(band), "Unknown")


def urgency_for(lead_days: int) -> str:
    if lead_days <= URGENCY_IMMEDIATE_MAX_LEAD:
        return "Immediate"
    if lead_days <= URGENCY_EXPECTED_MAX_LEAD:
        return "Expected"
    return "Future"


def certainty_for(lead_days: int) -> str:
    return "Likely" if lead_days <= CERTAINTY_LIKELY_MAX_LEAD else "Possible"


def _ist() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def _event_window(event_date: date) -> tuple[datetime, datetime]:
    """``(onset, expires)`` — the local calendar day of the event."""
    zone = _ist()
    start = datetime.combine(event_date, time(0, 0), tzinfo=zone)
    return start, start + timedelta(days=1) - timedelta(seconds=1)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _events_as_records(events: pd.DataFrame | Iterable[dict]) -> list[dict[str, Any]]:
    if isinstance(events, pd.DataFrame):
        return [dict(row) for row in events.to_dict("records")]
    return [dict(row) for row in events]


def _reject_synthetic(records: list[dict[str, Any]]) -> None:
    """Demo rows must never reach a public alerting channel.

    Live notification dispatch refuses them behind both locks; the CAP feed is
    the same rule with no lock to open, because a CAP document that has left
    the building cannot be recalled.
    """
    for row in records:
        blob = " ".join(str(row.get(key, "")) for key in
                        ("ward_name", "risk_band", "data_source", "source", "kind"))
        if "demo" in blob.lower() or "synthetic" in blob.lower():
            raise ValueError(
                "refusing to build a CAP message from a demo/synthetic event "
                f"(ward {row.get('ward_id')!r}) — synthetic data must never be "
                "published to a public alerting channel"
            )


def make_identifier(records: Sequence[dict[str, Any]], sent: datetime) -> str:
    """Deterministic CAP identifier for one batch.

    Same wards, same minute, same identifier — so a consumer polling every
    cycle can drop a repeat without remembering anything.
    """
    wards = ",".join(str(int(r["ward_id"])) for r in sorted(records, key=lambda r: int(r["ward_id"])))
    digest = hashlib.sha1(wards.encode("utf-8")).hexdigest()[:8]
    return f"HS-KMC-{sent.strftime('%Y%m%dT%H%M%S')}-{digest}"


# --------------------------------------------------------------------------- #
# 2. Element construction (order matters — CAP 1.2 is a sequence)
# --------------------------------------------------------------------------- #

def _q(tag: str) -> str:
    """Qualify a tag with the CAP namespace.

    Every element is created qualified so that the tree handed back by
    :func:`build_cap` is the same tree a consumer parses out of :func:`cap_xml`
    — an xmlns *attribute* would leave the in-memory tree unqualified and the
    two would quietly disagree.
    """
    return f"{{{CAP_NAMESPACE}}}{tag}"


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    child = ET.SubElement(parent, _q(tag))
    if text is not None:
        child.text = str(text)
    return child


def _parameters(parent: ET.Element, rows: list[dict[str, Any]]) -> None:
    """
    Batch-level quantities as CAP ``<parameter>`` blocks.

    ``<parameter>`` lives on ``<info>``, not on ``<area>``, so these describe
    the product the way NWS zone products do: one info, many areas, aggregate
    parameters. Per-ward numbers are served alongside in ``/alerts/cap`` and
    ``/alerts/geojson`` — nothing is dropped, it just rides in the channel
    that has room for it.
    """
    def _max(key: str) -> float:
        values = [_float_or_nan(r.get(key)) for r in rows]
        values = [v for v in values if v == v]
        return max(values) if values else float("nan")

    def _sum(key: str) -> float:
        return float(sum(v for v in (_float_or_nan(r.get(key)) for r in rows) if v == v))

    values: list[tuple[str, float]] = [
        ("HS:wardCount", float(len(rows))),
        ("HS:riskScoreMax", _max("risk_score")),
        ("HS:leadDaysMin", float(min((int(r.get("lead_days", 0) or 0) for r in rows), default=0))),
        ("HS:wbgtPeakC", _max("wbgt_peak_c")),
        ("HS:utciPeakC", _max("utci_peak_c")),
        ("HS:uhiDeltaCMax", _max("uhi_delta_c")),
        ("HS:exposedPopulation", _sum("exposed_population")),
    ]
    for name, number in values:
        if number != number:                     # NaN — never emit one
            continue
        parameter = _sub(parent, "parameter")
        _sub(parameter, "valueName", name)
        _sub(parameter, "value", f"{number:g}")
    if rows:
        parameter = _sub(parent, "parameter")
        _sub(parameter, "valueName", "HS:wardIdList")
        _sub(parameter, "value", ",".join(str(int(r["ward_id"]))
                                          for r in sorted(rows, key=lambda r: int(r["ward_id"]))))


def _float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _info_block(alert: ET.Element, rows: list[dict[str, Any]], language: str,
                wards: Any, contact: str) -> None:
    code = i18n.normalise_language(language)
    # Severity/urgency/certainty describe the batch: the worst band and the
    # shortest lead time in it. A message that under-reports its worst ward is
    # worse than one that over-reports its mildest.
    worst_band = max((str(r.get("risk_band", "Normal")) for r in rows),
                     key=lambda b: BAND_ORDER.index(b) if b in BAND_ORDER else 0)
    shortest_lead = min(int(r.get("lead_days", 0) or 0) for r in rows)
    # One representative ward drives the human-readable headline/description;
    # the per-ward numbers are all in the <parameter> blocks of each area's
    # parent info, and every ward gets its own <area>.
    headline_row = max(rows, key=lambda r: float(r.get("risk_score") or 0))

    info = _sub(alert, "info")
    _sub(info, "language", i18n.language_tag(code))
    for category in CATEGORIES:
        _sub(info, "category", category)
    _sub(info, "event", i18n.template("event", code))
    _sub(info, "responseType", "Prepare")
    _sub(info, "urgency", urgency_for(shortest_lead))
    _sub(info, "severity", severity_for(worst_band))
    _sub(info, "certainty", certainty_for(shortest_lead))
    _sub(info, "senderName", i18n.template("sender_name", code))
    _sub(info, "headline", _filled("headline", headline_row, code))
    _sub(info, "description", _filled("description", headline_row, code))
    _sub(info, "instruction", _filled("instruction", headline_row, code))
    _sub(info, "web", f"{WEB_BASE}/ward/{headline_row.get('ward_id', '')}")
    _sub(info, "contact", contact)

    event_code = _sub(info, "eventCode")
    _sub(event_code, "valueName", EVENT_CODE_NAME)
    _sub(event_code, "value", EVENT_CODE_VALUE)

    _parameters(info, rows)

    onset, expires = _event_window(_as_date(headline_row["event_date"]))
    for row in rows:
        area = _sub(info, "area")
        record = geo.ward_area(int(row["ward_id"]), wards)
        _sub(area, "areaDesc", record["areaDesc"])
        if record["polygon"]:
            _sub(area, "polygon", record["polygon"])
        else:
            _sub(area, "circle", record["circle"])
        geocode = _sub(area, "geocode")
        _sub(geocode, "valueName", "KMC_WARD")
        _sub(geocode, "value", str(int(row["ward_id"])))

    # CAP element order: effective/onset/expires come before senderName, but
    # the block above is built in reading order. Re-sort once, explicitly, so
    # the emitted document validates rather than trusting construction order.
    _reorder(info, _INFO_ORDER)

    # effective/onset/expires belong to the whole info block
    _insert_before(info, "senderName", "effective", _iso(onset))
    _insert_before(info, "senderName", "onset", _iso(onset))
    _insert_before(info, "senderName", "expires", _iso(expires))


_INFO_ORDER = (
    "language", "category", "event", "responseType", "urgency", "severity",
    "certainty", "audience", "eventCode", "effective", "onset", "expires",
    "senderName", "headline", "description", "instruction", "web", "contact",
    "parameter", "resource", "area",
)

_ALERT_ORDER = (
    "identifier", "sender", "sent", "status", "msgType", "source", "scope",
    "restriction", "addresses", "code", "note", "references", "incidents", "info",
)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _reorder(parent: ET.Element, order: Sequence[str]) -> None:
    children = list(parent)
    children.sort(key=lambda el: (order.index(_localname(el.tag))
                                  if _localname(el.tag) in order else len(order)))
    parent[:] = children


def _insert_before(parent: ET.Element, before: str, tag: str, text: str) -> None:
    element = ET.Element(_q(tag))
    element.text = text
    children = list(parent)
    index = next((i for i, el in enumerate(children)
                  if _localname(el.tag) == before), len(children))
    parent.insert(index, element)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _filled(template_key: str, row: dict[str, Any], code: str) -> str:
    fields = {
        "band": i18n.band_label(str(row.get("risk_band", "")), code),
        "ward": row.get("ward_name", ""),
        "date": _as_date(row["event_date"]).strftime("%d %b %Y"),
        "risk": f"{float(row.get('risk_score') or 0):.0f}",
        "wbgt": f"{float(row.get('wbgt_peak_c') or 0):.1f}",
        "utci": f"{float(row.get('utci_peak_c') or 0):.1f}",
        "tmax": f"{float(row.get('tmax_ward_c') or 0):.1f}",
        "exposed": f"{float(row.get('exposed_population') or 0):,.0f}",
        "guidance": i18n.guidance(str(row.get("risk_band", "")), code),
    }
    return i18n.template(template_key, code).format(**fields)


# --------------------------------------------------------------------------- #
# 3. Public API
# --------------------------------------------------------------------------- #

def build_cap(events: pd.DataFrame | Iterable[dict],
              languages: Sequence[str] = i18n.SUPPORTED_LANGUAGES,
              status: str = "Actual",
              msg_type: str = "Alert",
              scope: str = "Public",
              sender: str = SENDER,
              contact: str = CONTACT,
              wards: Any = None,
              now: datetime | None = None) -> ET.ElementTree:
    """
    Build a CAP 1.2 ``<alert>`` document for a batch of ward events.

    ``events`` is the output of :func:`core.alerts.find_upcoming_events` (a
    DataFrame or an iterable of dicts). Demo/synthetic rows raise
    :class:`ValueError` — see :func:`_reject_synthetic`.
    """
    rows = _events_as_records(events)
    _reject_synthetic(rows)
    sent = now or datetime.now(_ist())

    # Namespaced in memory, not via an xmlns attribute: ElementTree treats an
    # `xmlns` attribute as ordinary data, which leaves the in-memory tree with
    # unqualified tags and the serialised tree with qualified ones. Building it
    # qualified (and registering "" above) makes both identical, so a test that
    # inspects the ElementTree checks the same document a consumer receives.
    alert = ET.Element(_q("alert"))
    _sub(alert, "identifier", make_identifier(rows, sent) if rows
         else f"HS-KMC-{sent.strftime('%Y%m%dT%H%M%S')}-empty")
    _sub(alert, "sender", sender)
    _sub(alert, "sent", _iso(sent))
    _sub(alert, "status", status)
    _sub(alert, "msgType", msg_type)
    _sub(alert, "source", SOURCE)
    _sub(alert, "scope", scope)
    _sub(alert, "note", NOTE)

    if rows:
        for language in languages:
            _info_block(alert, rows, language, wards, contact)

    _reorder(alert, _ALERT_ORDER)
    # A feed with no events is still a valid CAP message — status "Actual",
    # msgType "Alert" and no <info> says "nothing to warn about" without the
    # consumer having to special-case an empty response. Emitting an <info> with
    # no <area> would instead be invalid, so the block is skipped entirely.
    return ET.ElementTree(alert)


def cap_xml(events: pd.DataFrame | Iterable[dict], **kwargs: Any) -> str:
    """The CAP document as a UTF-8 XML string with an XML declaration."""
    tree = build_cap(events, **kwargs)
    ET.indent(tree, space="  ")
    body = ET.tostring(tree.getroot(), encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def cap_payload(events: pd.DataFrame | Iterable[dict],
                languages: Sequence[str] = i18n.SUPPORTED_LANGUAGES,
                wards: Any = None,
                now: datetime | None = None,
                **kwargs: Any) -> dict[str, Any]:
    """
    The same warning as JSON — what ``/alerts/cap`` serves.

    Not a replacement for the XML: it exists so a dashboard can show what would
    be published, and so a static host (GitHub Pages) can serve the feed. The
    XML remains the interchange format.
    """
    rows = _events_as_records(events)
    _reject_synthetic(rows)
    sent = now or datetime.now(_ist())

    infos = []
    for language in languages:
        code = i18n.normalise_language(language)
        infos.append({
            "language": i18n.language_tag(code),
            "event": i18n.template("event", code),
            "sender_name": i18n.template("sender_name", code),
            "messages": [
                {
                    "ward_id": int(row["ward_id"]),
                    "ward_name": row.get("ward_name"),
                    "language": i18n.language_tag(code),
                    "sms_segments": i18n.segment_count(
                        i18n.compose_message(row, code), code),
                    "message": i18n.compose_message(row, code),
                    "headline": _filled("headline", row, code),
                }
                for row in rows
            ],
        })

    areas = []
    for row in rows:
        record = geo.ward_area(int(row["ward_id"]), wards)
        areas.append({
            "ward_id": int(row["ward_id"]),
            "ward_name": row.get("ward_name"),
            "area_desc": record["areaDesc"],
            "shape": record["shape"],
            "severity": severity_for(str(row.get("risk_band", ""))),
            "urgency": urgency_for(int(row.get("lead_days", 0) or 0)),
            "certainty": certainty_for(int(row.get("lead_days", 0) or 0)),
            "onset": _iso(_event_window(_as_date(row["event_date"]))[0]) if row.get("event_date") else None,
            "expires": _iso(_event_window(_as_date(row["event_date"]))[1]) if row.get("event_date") else None,
        })

    return {
        "protocol": "CAP 1.2",
        "namespace": CAP_NAMESPACE,
        "identifier": make_identifier(rows, sent) if rows else f"HS-KMC-{sent.strftime('%Y%m%dT%H%M%S')}-empty",
        "sender": kwargs.get("sender", SENDER),
        "sent": _iso(sent),
        "status": kwargs.get("status", "Actual"),
        "msg_type": kwargs.get("msg_type", "Alert"),
        "scope": kwargs.get("scope", "Public"),
        "note": NOTE,
        "rows": len(rows),
        "languages": [i18n.language_tag(i18n.normalise_language(lang)) for lang in languages],
        "wards": areas,
        "info": infos,
        "geometry": geo.geometry_status(),
        "sachet": SACHET_HANDOFF,
        "xml_path": "/alerts/cap.xml",
        "is_synthetic": False,
    }


def alerts_geojson(events: pd.DataFrame | Iterable[dict],
                   languages: Sequence[str] = i18n.SUPPORTED_LANGUAGES,
                   wards: Any = None) -> dict[str, Any]:
    """
    The alert batch as a GeoJSON FeatureCollection.

    This is the layer a district control room drops into QGIS or a web map —
    the same data as the CAP polygons, in the format every GIS tool reads.
    """
    rows = _events_as_records(events)
    _reject_synthetic(rows)
    features = []
    for row in rows:
        properties = {
            "ward_name": row.get("ward_name"),
            "event_date": str(_as_date(row["event_date"])) if row.get("event_date") else None,
            "lead_days": row.get("lead_days"),
            "risk_score": row.get("risk_score"),
            "risk_band": row.get("risk_band"),
            "wbgt_peak_c": row.get("wbgt_peak_c"),
            "utci_peak_c": row.get("utci_peak_c"),
            "severity": severity_for(str(row.get("risk_band", ""))),
            "urgency": urgency_for(int(row.get("lead_days", 0) or 0)),
            "certainty": certainty_for(int(row.get("lead_days", 0) or 0)),
            "exposed_population": row.get("exposed_population"),
        }
        features.append(geo.ward_feature(int(row["ward_id"]), properties, wards))

    return {
        "type": "FeatureCollection",
        "schema_version": 1,
        "protocol": "GeoJSON (RFC 7946)",
        "generated_at": _iso(datetime.now(_ist())),
        "note": NOTE,
        "geometry": geo.geometry_status(),
        "languages": [i18n.language_tag(i18n.normalise_language(lang)) for lang in languages],
        "features": features,
        "is_synthetic": False,
    }


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    sample = [
        {"ward_id": 24, "ward_name": "Ward 24", "event_date": date(2026, 5, 21),
         "lead_days": 3, "risk_score": 78.4, "risk_band": "Critical",
         "wbgt_peak_c": 32.6, "utci_peak_c": 44.1, "tmax_ward_c": 41.2,
         "uhi_delta_c": 2.4, "exposed_population": 12489, "population": 31000},
        {"ward_id": 57, "ward_name": "Ward 57", "event_date": date(2026, 5, 22),
         "lead_days": 4, "risk_score": 66.1, "risk_band": "Danger",
         "wbgt_peak_c": 30.9, "utci_peak_c": 41.7, "tmax_ward_c": 39.4,
         "uhi_delta_c": 1.8, "exposed_population": 8240, "population": 25000},
    ]

    print("=" * 74)
    print("A) JSON payload summary")
    print("=" * 74)
    payload = cap_payload(sample)
    print(f"identifier : {payload['identifier']}")
    print(f"rows       : {payload['rows']}   languages: {payload['languages']}")
    print(f"geometry   : {payload['geometry']['shape']} "
          f"({payload['geometry']['wards_with_geometry']} wards)")
    for area in payload["wards"]:
        print(f"  ward {area['ward_id']:<4} {area['severity']:<8} "
              f"{area['urgency']:<9} {area['certainty']:<8} {area['shape']}")

    print("\n" + "=" * 74)
    print("B) CAP 1.2 XML (English <info> only, for brevity)")
    print("=" * 74)
    print(cap_xml(sample, languages=("en",))[:1800])

    print("\n" + "=" * 74)
    print("C) GeoJSON feed")
    print("=" * 74)
    feed = alerts_geojson(sample)
    print(f"{len(feed['features'])} features, geometry: {feed['geometry']['shape']}")
    print("  properties:", sorted(feed["features"][0]["properties"]))

    print("\n" + "=" * 74)
    print("D) Synthetic events are refused")
    print("=" * 74)
    try:
        cap_payload([{**sample[0], "ward_name": "Ward 24 (demo-synthetic)"}])
        print("  FAIL — a demo row was accepted")
    except ValueError as exc:
        print(f"  refused: {exc}")

    print("\n" + "=" * 74)
    print("E) SACHET hand-off")
    print("=" * 74)
    for key, value in SACHET_HANDOFF.items():
        if isinstance(value, list):
            print(f"  {key}:")
            for item in value:
                print(f"    - {item}")
        else:
            print(f"  {key}: {value}")
