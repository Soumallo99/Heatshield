"""
HeatShield — Streamlit operator console
=======================================
A second, deliberately boring surface for the same numbers: something a
municipal officer can open without a terminal, and something a judge can
screenshot in five seconds.

What it is
----------
A thin read-only view over the CSVs the pipeline already writes
(``data/processed/*.csv``). It computes nothing of its own, so it can never
disagree with the dashboard or the API — the same invariant the rest of the
project holds.

What it is NOT
--------------
Not a replacement for the FastAPI service, and not part of the request path.
The API stays stateless and horizontally scalable; this is a viewer that reads
the last computed run. It therefore works with **no network and no
credentials**, which is also why it can be shown offline.

Run
---
    streamlit run ops/console.py

If Streamlit is not installed:  pip install streamlit  (it is already in
requirements.txt, which is why this file adds no new dependency).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parents[1]
PROCESSED = BASE / "data" / "processed"

st.set_page_config(page_title="HeatShield — operator console", page_icon="🛡️",
                   layout="wide")

st.title("🛡️ HeatShield — operator console")
st.caption(
    "Read-only view of the last computed run. Reads "
    "`data/processed/*.csv` — no network, no credentials, no new computation."
)


# --------------------------------------------------------------------------- #
# Load — every frame is optional; a missing one is stated, never faked
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load(name: str) -> pd.DataFrame | None:
    path = PROCESSED / name
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:                      # corrupt or empty file
        st.warning(f"could not read {name}: {exc}")
        return None


risk = load("risk_daily.csv")
thermal = load("thermal_daily.csv")

if risk is None:
    st.error(
        "No scored run found. Run `python -m scripts.refresh` "
        "(or `--offline` to replay the cached forecast) and reload this page."
    )
    st.stop()

if "date" in risk:
    risk["date"] = pd.to_datetime(risk["date"], errors="coerce").dt.date

st.sidebar.header("Filters")
days = sorted(d for d in risk["date"].dropna().unique())
chosen_day = st.sidebar.selectbox("Day", days, index=len(days) - 1,
                                  format_func=lambda d: d.strftime("%a %d %b %Y"))
threshold = st.sidebar.slider("Alert threshold (risk score)", 0.0, 100.0, 60.0, 1.0)

day = risk[risk["date"] == chosen_day].copy()

# --------------------------------------------------------------------------- #
# Headline
# --------------------------------------------------------------------------- #
worst = day.nlargest(1, "risk_score").iloc[0] if len(day) else None
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Wards scored", f"{len(day):,}")
with col2:
    st.metric("Above threshold", f"{int((day['risk_score'] >= threshold).sum()):,}")
with col3:
    if worst is not None:
        st.metric("Worst ward", str(worst["ward_name"]), f"{worst['risk_score']:.0f}/100")
with col4:
    if worst is not None:
        st.metric("Peak WBGT", f"{worst.get('wbgt_peak_c', float('nan')):.1f} °C",
                  f"UTCI {worst.get('utci_peak_c', float('nan')):.1f} °C"
                  if "utci_peak_c" in worst else None)

st.divider()

# --------------------------------------------------------------------------- #
# League table
# --------------------------------------------------------------------------- #
st.subheader(f"Ward league table — {chosen_day:%a %d %b %Y}")
columns = [c for c in ("ward_name", "risk_score", "risk_band", "wbgt_peak_c",
                       "utci_peak_c", "hi_peak_c", "tmax_adj_c", "uhi_delta_c",
                       "vulnerability", "population", "exposed_population")
           if c in day.columns]
table = day.nlargest(25, "risk_score")[columns].reset_index(drop=True)
table.index = table.index + 1
st.dataframe(table.style.format({
    "risk_score": "{:.1f}", "wbgt_peak_c": "{:.1f}", "utci_peak_c": "{:.1f}",
    "hi_peak_c": "{:.1f}", "tmax_adj_c": "{:.1f}", "uhi_delta_c": "{:+.1f}",
    "vulnerability": "{:.0f}", "population": "{:,.0f}",
    "exposed_population": "{:,.0f}",
}), use_container_width=True)

st.caption(
    "Risk = hazard × vulnerability amplifier. Vulnerability is min–max "
    "normalised **within this city**, so ward scores are not comparable across "
    "cities without per-city calibration."
)

# --------------------------------------------------------------------------- #
# Alert copy, in the languages the city reads
# --------------------------------------------------------------------------- #
st.subheader("Alert copy")
try:
    from core import i18n
    from core.alerts import find_upcoming_events

    events = find_upcoming_events(risk, min_lead_days=1, risk_threshold=threshold)
    if events.empty:
        st.info(
            f"No ward crosses {threshold:.0f} with at least one day of lead time. "
            "Crossings today or earlier are nowcasts, not warnings — the "
            "intervention window has closed, so the system stays quiet on purpose."
        )
    else:
        tabs = st.tabs([label for _code, label, _state
                        in ((c, {"en": "English", "hi": "हिन्दी", "bn": "বাংলা"}[c], None)
                            for c in i18n.SUPPORTED_LANGUAGES)])
        for tab, code in zip(tabs, i18n.SUPPORTED_LANGUAGES):
            with tab:
                row = events.iloc[0].to_dict()
                body = i18n.compose_message(row, code)
                st.text_area("Message", body, height=190, key=f"msg-{code}")
                st.caption(
                    f"{len(body)} characters · "
                    f"{i18n.segment_count(body, code)} SMS segment(s). "
                    + ("Devanagari/Bengali are UCS-2: 70 characters per segment, "
                       "not 160." if code != "en" else "")
                )
        st.caption(i18n.TRANSLATION_STATUS)
except Exception as exc:                          # never let the viewer break the page
    st.warning(f"alert copy unavailable: {exc}")

# --------------------------------------------------------------------------- #
# CAP preview — what SACHET would receive
# --------------------------------------------------------------------------- #
st.subheader("CAP 1.2 — national hand-off")
try:
    from core import cap as cap_engine

    payload = cap_engine.cap_payload(events, wards=None) if not events.empty else None
    if payload:
        st.caption(
            f"{payload['protocol']} · identifier `{payload['identifier']}` · "
            f"{payload['rows']} ward(s) · languages "
            f"{', '.join(payload['languages'])} · geometry `{payload['geometry']['shape']}`"
        )
        with st.expander("CAP XML (first ward batch, English block)"):
            st.code(cap_engine.cap_xml(events, languages=("en",)), language="xml")
        st.caption(payload["sachet"]["status"])
    else:
        st.info("No CAP message to show — the alert queue is empty.")
except Exception as exc:
    st.warning(f"CAP preview unavailable: {exc}")

st.divider()
st.caption(
    "Excess-mortality figures are **illustrative**: a real baseline death rate "
    "times a real population, with an assumed dose–response. Population aged "
    "60+ and slum share are **absent, not modelled** — see DATA.md."
)
