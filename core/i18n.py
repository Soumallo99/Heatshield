"""
PHASE 8 — Multilingual alert copy
=================================
A heat warning that only English speakers can read is not a public warning in
Kolkata. This module carries the alert copy in the languages the city actually
speaks, and it is the layer that makes the CAP feed (*core/cap.py*) able to
emit one ``<info>`` block per language — which is what NDMA's SACHET portal
expects, since it disseminates in twelve regional languages.

Design rules
------------
1. **English is authoritative.** ``en`` is the source of truth for every key.
   A missing key in another language falls back to English rather than
   dropping the line — a half-translated warning is worse than an English one,
   but a warning with a missing instruction is worse than both.
2. **Numbers and units never move.** Only the words around them are
   translated. ``38.4 °C`` is ``38.4 °C`` in every language; re-formatting
   numerals per locale is how a warning gets misread on a feature phone.
3. **Translations are operational drafts, not certified copy.** They are
   reviewed by the issuing authority (KMC / NDMA) before a live send. The
   module records that in :data:`TRANSLATION_STATUS` so the UI can say so
   instead of implying official sign-off.
4. **SMS length still matters.** Bengali and Hindi in Unicode are UCS-2, so a
   160-character GSM segment becomes 70 characters. :func:`segment_count`
   reports the real cost; nothing here pretends otherwise.

Run standalone:  python -m core.i18n
"""
from __future__ import annotations

import os
from datetime import date

# --------------------------------------------------------------------------- #
# 1. Languages
# --------------------------------------------------------------------------- #

#: Public base URL for the "details" link in alert copy. Overridable so a
#: self-hosted deployment does not send residents to someone else's site.
WEB_BASE = os.getenv("HS_WEB_BASE", "https://heatshield.app")

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "hi", "bn")
DEFAULT_LANGUAGE = "en"

#: IETF tags for CAP <language>. NDMA's SACHET portal disseminates in twelve
#: regional languages; the three below are wired, the rest are listed so the
#: gap is visible in a payload rather than discovered during an incident.
LANGUAGE_TAGS: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "bn": "bn-IN",
}

SACHET_TARGET_LANGUAGES: tuple[tuple[str, str, str], ...] = (
    ("en", "English", "wired"),
    ("hi", "हिन्दी / Hindi", "wired"),
    ("bn", "বাংলা / Bengali", "wired"),
    ("mr", "मराठी / Marathi", "not wired — needs translation review"),
    ("ta", "தமிழ் / Tamil", "not wired — needs translation review"),
    ("te", "తెలుగు / Telugu", "not wired — needs translation review"),
    ("gu", "ગુજરાતી / Gujarati", "not wired — needs translation review"),
    ("kn", "ಕನ್ನಡ / Kannada", "not wired — needs translation review"),
    ("ml", "മലയാളം / Malayalam", "not wired — needs translation review"),
    ("or", "ଓଡ଼ିଆ / Odia", "not wired — needs translation review"),
    ("pa", "ਪੰਜਾਬੀ / Punjabi", "not wired — needs translation review"),
    ("ur", "اُردُو / Urdu", "not wired — needs translation review"),
)

#: Shown in the UI next to any non-English copy.
TRANSLATION_STATUS = (
    "Operational draft translations. English is authoritative; Hindi and "
    "Bengali copy is reviewed by the issuing authority before a live send."
)

# --------------------------------------------------------------------------- #
# 2. Strings
# --------------------------------------------------------------------------- #

#: Band labels. Keyed by the risk band produced by core.risk.risk_band().
_BANDS: dict[str, dict[str, str]] = {
    "en": {"Caution": "Caution", "Danger": "Danger",
           "Critical": "Critical", "Extreme": "Extreme"},
    "hi": {"Caution": "सावधानी", "Danger": "खतरा",
           "Critical": "गंभीर", "Extreme": "अत्यंत गंभीर"},
    "bn": {"Caution": "সতর্কতা", "Danger": "বিপদ",
           "Critical": "সংকটজনক", "Extreme": "চরম"},
}

_GUIDANCE: dict[str, dict[str, str]] = {
    "en": {
        "Caution": "Increase fluids. Schedule heavy work before 11:00.",
        "Danger": "Hourly shaded breaks. Watch for cramps and dizziness.",
        "Critical": "Suspend non-essential outdoor labour 12:00–15:00.",
        "Extreme": "Stop all outdoor work. Activate cooling centres.",
    },
    "hi": {
        "Caution": "तरल पदार्थ अधिक लें। भारी काम 11:00 से पहले करें।",
        "Danger": "हर घंटे छाया में आराम लें। चक्कर या ऐंठन पर सावधान रहें।",
        "Critical": "12:00–15:00 तक अनावश्यक बाहरी काम बंद रखें।",
        "Extreme": "सभी बाहरी काम रोकें। कूलिंग सेंटर खोलें।",
    },
    "bn": {
        "Caution": "প্রচুর তরল পান করুন। ভারী কাজ সকাল ১১টার আগে সারুন।",
        "Danger": "প্রতি ঘণ্টায় ছায়ায় বিশ্রাম নিন। খিঁচুনি ও মাথা ঘোরা লক্ষ্য করুন।",
        "Critical": "দুপুর 12:00–15:00 টায় বাইরের অপ্রয়োজনীয় কাজ বন্ধ রাখুন।",
        "Extreme": "সব বাইরের কাজ বন্ধ করুন। কুলিং সেন্টার খুলুন।",
    },
}

_DAYNAMES: dict[str, tuple[str, ...]] = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "hi": ("सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि"),
    "bn": ("সোম", "মঙ্গল", "বুধ", "বৃহঃ", "শুক্র", "শনি", "রবি"),
}

#: Alert message templates. Placeholders are the same in every language:
#: {band} {ward} {day} {date} {lead} {risk} {wbgt} {utci} {tmax} {uhi}
#: {guidance} {exposed} {url}
_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "title": "HeatShield {band} HEAT WARNING",
        "when": "{ward} — {day} {date}, in {lead} day(s)",
        "metrics": "Risk {risk}/100 · peak WBGT {wbgt}°C · UTCI {utci}°C",
        "ward_peak": "Ward peak temp {tmax}°C{uhi}",
        "uhi": " (+{uhi}°C UHI)",
        "action": "Action: {guidance}",
        "exposed": "About {exposed} residents exposed.",
        "details": "Details: {url}",
        "stop": "Reply STOP to opt out.",
        "headline": "{band} heat warning for {ward} on {date}",
        "description": (
            "HeatShield forecasts {band}-level heat stress in {ward} on {date}. "
            "Peak wet-bulb globe temperature {wbgt} °C, UTCI {utci} °C, ward peak "
            "air temperature {tmax} °C. About {exposed} residents are exposed."
        ),
        "instruction": "{guidance} Check on elderly neighbours and people living alone.",
        "sender_name": "HeatShield — Kolkata Municipal Corporation pilot",
        "event": "Extreme Heat Warning",
        "area_prefix": "Ward",
    },
    "hi": {
        "title": "हीटशील्ड {band} हीट चेतावनी",
        "when": "{ward} — {day} {date}, {lead} दिन में",
        "metrics": "जोखिम {risk}/100 · अधिकतम WBGT {wbgt}°C · UTCI {utci}°C",
        "ward_peak": "वार्ड अधिकतम तापमान {tmax}°C{uhi}",
        "uhi": " (शहर से +{uhi}°C अधिक)",
        "action": "क्या करें: {guidance}",
        "exposed": "लगभग {exposed} निवासी प्रभावित।",
        "details": "विवरण: {url}",
        "stop": "बंद करने के लिए STOP भेजें।",
        "headline": "{ward} के लिए {date} को {band} हीट चेतावनी",
        "description": (
            "हीटशील्ड का अनुमान: {date} को {ward} में {band} स्तर की गर्मी। "
            "अधिकतम WBGT {wbgt} °C, UTCI {utci} °C, वार्ड अधिकतम तापमान {tmax} °C। "
            "लगभग {exposed} निवासी प्रभावित।"
        ),
        "instruction": "{guidance} बुजुर्ग पड़ोसियों और अकेले रहने वालों की जाँच करें।",
        "sender_name": "हीटशील्ड — कोलकाता नगर निगम पायलट",
        "event": "अत्यधिक गर्मी की चेतावनी",
        "area_prefix": "वार्ड",
    },
    "bn": {
        "title": "হিটশিল্ড {band} তাপ সতর্কতা",
        "when": "{ward} — {day} {date}, {lead} দিন পর",
        "metrics": "ঝুঁকি {risk}/100 · সর্বোচ্চ WBGT {wbgt}°C · UTCI {utci}°C",
        "ward_peak": "ওয়ার্ডের সর্বোচ্চ তাপমাত্রা {tmax}°C{uhi}",
        "uhi": " (শহরের চেয়ে +{uhi}°C বেশি)",
        "action": "করণীয়: {guidance}",
        "exposed": "প্রায় {exposed} বাসিন্দা ঝুঁকিতে।",
        "details": "বিস্তারিত: {url}",
        "stop": "থামতে STOP লিখুন।",
        "headline": "{date} তারিখে {ward}-এর জন্য {band} তাপ সতর্কতা",
        "description": (
            "হিটশিল্ডের পূর্বাভাস: {date} তারিখে {ward}-এ {band} মাত্রার তাপচাপ। "
            "সর্বোচ্চ WBGT {wbgt} °C, UTCI {utci} °C, ওয়ার্ডের সর্বোচ্চ বায়ু "
            "তাপমাত্রা {tmax} °C। প্রায় {exposed} বাসিন্দা ঝুঁকিতে।"
        ),
        "instruction": "{guidance} বয়স্ক প্রতিবেশী ও একা থাকেন এমন মানুষের খোঁজ নিন।",
        "sender_name": "হিটশিল্ড — কলকাতা পৌরসংস্থা পাইলট",
        "event": "চরম তাপ সতর্কতা",
        "area_prefix": "ওয়ার্ড",
    },
}


# --------------------------------------------------------------------------- #
# 3. Lookup
# --------------------------------------------------------------------------- #

def normalise_language(lang: str | None) -> str:
    """Map any ``hi-IN`` / ``bn`` / ``HI`` spelling onto a supported code.

    Unknown languages fall back to English rather than raising: an alert must
    compose even if a caller passes something unexpected.
    """
    if not lang:
        return DEFAULT_LANGUAGE
    code = str(lang).strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def translate(group: str, key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Look up one string, falling back to English for a missing translation."""
    code = normalise_language(lang)
    tables = {"band": _BANDS, "guidance": _GUIDANCE, "template": _TEMPLATES}
    table = tables[group]
    value = table.get(code, {}).get(key)
    if value is None and code != DEFAULT_LANGUAGE:
        value = table[DEFAULT_LANGUAGE].get(key)
    return value if value is not None else key


def band_label(band: str, lang: str = DEFAULT_LANGUAGE) -> str:
    return translate("band", str(band), lang)


def guidance(band: str, lang: str = DEFAULT_LANGUAGE) -> str:
    return translate("guidance", str(band), lang)


def dayname(value: date, lang: str = DEFAULT_LANGUAGE) -> str:
    """Weekday abbreviation in the requested language (empty for a non-date)."""
    if not isinstance(value, date):
        return ""
    return _DAYNAMES[normalise_language(lang)][value.weekday()]


def language_tag(lang: str = DEFAULT_LANGUAGE) -> str:
    """IETF tag for a CAP ``<language>`` element."""
    return LANGUAGE_TAGS[normalise_language(lang)]


def template(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    return translate("template", key, lang)


# --------------------------------------------------------------------------- #
# 4. Message composition
# --------------------------------------------------------------------------- #

def _num(ev: dict, key: str, default: float = float("nan")) -> float:
    """Defensive numeric read — round-trips through JSON/CSV turn these into
    None or strings, and an alert must never fail to compose."""
    try:
        value = float(ev.get(key, default))
    except (TypeError, ValueError):
        return default
    return value


def _text(value: float, spec: str = "%.1f") -> str:
    return "" if value != value else spec % value      # NaN -> empty


def compose_message(ev: dict, lang: str = DEFAULT_LANGUAGE) -> str:
    """
    The SMS / WhatsApp body for one alert event, in the requested language.

    Same shape as the English-only message this replaces, plus the UTCI line —
    because the two indices answer different questions and the public gets both.
    """
    code = normalise_language(lang)
    event = ev["event_date"]
    day = dayname(event, code) if isinstance(event, date) else ""

    uhi = _num(ev, "uhi_delta_c")
    uhi_txt = (template("uhi", code).format(uhi=_text(uhi))
               if uhi == uhi and uhi > 0.05 else "")

    fields = {
        "band": band_label(str(ev.get("risk_band", "")), code).upper(),
        "ward": ev.get("ward_name", ""),
        "day": day,
        "date": event.strftime("%d %b") if isinstance(event, date) else str(event),
        "lead": str(int(_num(ev, "lead_days", 0))),
        "risk": _text(_num(ev, "risk_score"), "%.0f"),
        "wbgt": _text(_num(ev, "wbgt_peak_c")),
        "utci": _text(_num(ev, "utci_peak_c")),
        "tmax": _text(_num(ev, "tmax_ward_c")),
        "uhi": uhi_txt,
        "guidance": guidance(str(ev.get("risk_band", "")), code),
        "exposed": f"{_num(ev, 'exposed_population', 0):,.0f}",
        "url": f"{ev.get('web_base') or WEB_BASE}/ward/{ev.get('ward_id', '')}",
    }

    lines = [
        template("title", code).format(**fields),
        template("when", code).format(**fields),
        "",
        template("metrics", code).format(**fields),
        template("ward_peak", code).format(**fields),
        "",
        template("action", code).format(**fields),
        template("exposed", code).format(**fields),
        "",
        template("details", code).format(**fields),
        template("stop", code).format(**fields),
    ]
    return "\n".join(lines)


def segment_count(text: str, lang: str = DEFAULT_LANGUAGE) -> int:
    """
    How many SMS segments this message costs.

    Devanagari and Bengali push the message into UCS-2, where a single segment
    holds 70 characters instead of 160 and a concatenated message holds 67 per
    part. A warning that silently becomes three segments is a budget problem,
    so it is reported rather than discovered on the invoice.
    """
    if not text:
        return 0
    code = normalise_language(lang)
    single, multi = (160, 153) if code == "en" else (70, 67)
    return 1 if len(text) <= single else -(-len(text) // multi)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from datetime import date as _date

    sample = {
        "ward_id": 24,
        "ward_name": "Ward 24",
        "event_date": _date(2026, 5, 21),
        "lead_days": 3,
        "risk_score": 78.4,
        "risk_band": "Critical",
        "wbgt_peak_c": 32.6,
        "utci_peak_c": 44.1,
        "tmax_ward_c": 41.2,
        "uhi_delta_c": 2.4,
        "exposed_population": 12489,
    }

    for code in SUPPORTED_LANGUAGES:
        body = compose_message(sample, code)
        print("=" * 74)
        print(f"{code}  ({LANGUAGE_TAGS[code]})  —  {segment_count(body, code)} SMS segment(s)")
        print("=" * 74)
        print(body)
        print()

    print("SACHET language coverage:")
    for code, label, state in SACHET_TARGET_LANGUAGES:
        print(f"  {code}  {label:<22} {state}")
