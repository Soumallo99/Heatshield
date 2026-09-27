"""
Multilingual alert copy tests.

The failure mode this file is guarding against is not a missing word — it is a
warning that goes out with a number silently changed, or with a line dropped
because a template placeholder did not exist in one language. So the tests
assert that the *numbers* are byte-identical across languages and that every
language carries every key.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from core import i18n
from core.alerts import compose_message

SAMPLE = {
    "ward_id": 24,
    "ward_name": "Ward 24",
    "event_date": date(2026, 5, 21),
    "lead_days": 3,
    "risk_score": 78.4,
    "risk_band": "Critical",
    "wbgt_peak_c": 32.6,
    "utci_peak_c": 44.1,
    "tmax_ward_c": 41.2,
    "uhi_delta_c": 2.4,
    "exposed_population": 12489,
}


# --------------------------------------------------------------- coverage
def test_every_language_carries_every_template_key():
    """A missing key falls back to English, which is how a warning goes out
    half-translated with nobody noticing. So there must not be one."""
    english = set(i18n._TEMPLATES["en"])
    for code, table in i18n._TEMPLATES.items():
        assert table.keys() == english, f"{code} is missing {english - table.keys()}"


def test_every_language_covers_every_band_and_guidance():
    bands = set(i18n._BANDS["en"])
    for code, table in i18n._BANDS.items():
        assert table.keys() == bands, code
    for code, table in i18n._GUIDANCE.items():
        assert table.keys() == bands, code


def test_supported_languages_are_wired_into_sachet_coverage():
    wired = [code for code, _label, state in i18n.SACHET_TARGET_LANGUAGES
             if state.startswith("wired")]
    assert tuple(wired) == i18n.SUPPORTED_LANGUAGES
    assert len(i18n.SACHET_TARGET_LANGUAGES) == 12


@pytest.mark.parametrize("raw,expected", [
    ("hi", "hi"), ("hi-IN", "hi"), ("HI", "hi"), ("bn_IN", "bn"),
    ("en-GB", "en"), ("ta", "en"), ("", "en"), (None, "en"), ("zz", "en"),
])
def test_language_normalisation(raw, expected):
    assert i18n.normalise_language(raw) == expected


def test_unknown_language_falls_back_to_english_never_raises():
    assert i18n.compose_message(SAMPLE, "ta") == i18n.compose_message(SAMPLE, "en")


# --------------------------------------------------------------- composition
def test_numbers_and_units_are_identical_in_every_language():
    """Only the words translate. 41.2 °C is 41.2 °C in Bengali."""
    def numbers(text: str) -> list[str]:
        return re.findall(r"\d+(?:[.,]\d+)?", text)

    english = numbers(i18n.compose_message(SAMPLE, "en"))
    for code in i18n.SUPPORTED_LANGUAGES[1:]:
        assert numbers(i18n.compose_message(SAMPLE, code)) == english, code


def test_every_language_renders_the_same_facts():
    for code in i18n.SUPPORTED_LANGUAGES:
        body = i18n.compose_message(SAMPLE, code)
        assert "Ward 24" in body, code
        assert "21 May" in body, code
        assert "3" in body, code                  # lead time
        assert "32.6" in body and "44.1" in body, code   # WBGT and UTCI
        assert "41.2" in body, code
        assert "12,489" in body, code
        assert "/ward/24" in body, code
        assert "STOP" in body.upper(), code


def test_the_english_message_still_fits_two_sms_segments():
    """The UTCI line was added without pushing past the segment budget."""
    body = i18n.compose_message(SAMPLE, "en")
    assert len(body) <= 320
    assert i18n.segment_count(body, "en") == 2


def test_devanagari_and_bengali_cost_more_segments_than_english():
    """UCS-2 halves the segment size. Silently budgeting 160 chars for a
    Bengali warning under-quotes the send by more than half."""
    assert i18n.segment_count(i18n.compose_message(SAMPLE, "en"), "en") == 2
    for code in ("hi", "bn"):
        body = i18n.compose_message(SAMPLE, code)
        assert i18n.segment_count(body, code) > i18n.segment_count(body, "en")
    assert i18n.segment_count("", "bn") == 0


def test_missing_values_degrade_to_empty_not_nan():
    """An alert must compose even when a field is missing."""
    sparse = {**SAMPLE, "utci_peak_c": None, "uhi_delta_c": float("nan")}
    body = i18n.compose_message(sparse, "en")
    assert "nan" not in body.lower()
    assert "heat island" not in body and "UHI" not in body


def test_core_alerts_delegates_to_the_shared_implementation():
    """One composition path: the SMS and the CAP description cannot drift."""
    assert compose_message(SAMPLE) == i18n.compose_message(SAMPLE, "en")
    assert compose_message(SAMPLE, "bn") == i18n.compose_message(SAMPLE, "bn")


def test_language_tags_are_ietf():
    assert i18n.language_tag("en") == "en-IN"
    assert i18n.language_tag("hi-IN") == "hi-IN"
    assert i18n.language_tag("bn") == "bn-IN"


def test_daynames_follow_the_local_week():
    thursday = date(2026, 5, 21)          # a Thursday
    assert i18n.dayname(thursday, "en") == "Thu"
    assert i18n.dayname(thursday, "hi") == "गुरु"
    assert i18n.dayname(thursday, "bn") == "বৃহঃ"
    assert i18n.dayname("not a date") == ""


def test_translation_status_is_declared_not_implied():
    """Reviewers must be able to see that the copy is not yet signed off."""
    assert "reviewed" in i18n.TRANSLATION_STATUS.lower()
    assert "english is authoritative" in i18n.TRANSLATION_STATUS.lower()
