# INTEGRATIONS.md — the open-source / open-data ecosystem around HeatShield

> **Read this alongside [`DATA.md`](DATA.md)** (what is real, what is modelled,
> what is missing) and [`AGENTS.md`](AGENTS.md) §7 (the known gaps, ranked).
>
> This file answers one question for every tool, API and dataset on the shortlist:
> **does it make HeatShield a better warning system, and if so, where exactly does
> it plug in?** Every entry ends in a verdict — *adopted*, *adopt next*, or
> *deliberately not used* — and the third column is the honest one. A warning
> system is judged as much by what it refuses to do as by what it does.

---

## 0. The short answer

| Resource | Verdict | What it does for HeatShield |
|---|---|---|
| [`data.gov.in`](https://data.gov.in) · [`api.data.gov.in`](https://api.data.gov.in) | **Adopted** (adapter) | Closes the two gaps `DATA.md` calls absent — population 60+, slum share — and supplies observed weather for forecast verification. `core/datagov.py` + `/integrations/datagov`. Keyless-safe. |
| [datameet](https://github.com/datameet) | **Already used** | The 141 KMC ward polygons and the Census 2011 PCA recovery come from here. |
| Streamlit | **Adopted** (viewer) | `ops/console.py` — a read-only operator console over the committed CSVs. |
| Faker / [Mockaroo](https://mockaroo.com) | **Adopted, fenced** | `scripts/gen_fixtures.py` — synthetic load-test rows that cannot dial out and cannot overwrite the live registry. |
| Semantic Scholar · [typeset.io](https://typeset.io) | **Adopted as practice** | Every physical constant in the pipeline cites a paper. The UTCI coefficient table is the newest example. |
| [FastAPI](https://github.com/tiangolo/fastapi) | **Already used** | The backend. Not being rewritten for frontend convenience (`AGENTS.md` §6.4). |
| Render · Railway · Vercel · Netlify · AWS Free | **Adopted** (configs) | `render.yaml`, `netlify.toml`, `vercel.json`, `Dockerfile`. GitHub Pages already ships the static build. |
| Supabase | **Adopt next** | The scale-out path above ~10,000 wards (`AGENTS.md` §8): CSV → Postgres/PostGIS. |
| Kaggle · [data.world](https://data.world) · [india-data](https://github.com/nicedoc/india-data) | **Discovery only** | Where to *look* for datasets. Anything adopted goes through the `DATA.md` provenance table — nothing is vendored from a licence-ambiguous mirror. |
| LangChain · Rasa | **Adopt next, off the critical path** | Operator "explain this warning" and a citizen chatbot. Never in the scoring path — see §4. |
| NJDG eCourts · e-District · NDHM HealthID · UIDAI Aadhaar | **Deliberately not used** | No heat signal, and two of them are identity systems where linking a heat warning to a person is a privacy regression, not a feature. |
| [jsonplaceholder](https://jsonplaceholder.typicode.com) | **Deliberately not used** | A live HTTP echo in CI is a flake source. The suite injects stubs instead. |
| NITI Aayog · PRS India · SIH · MyGov · AICTE · MIC | **Context, not data** | Problem-statement provenance, Heat Action Plan framing, submission surface. |
| Gamma · Whimsical · Figma · Excalidraw · Napkin · Descript | **Presentation layer** | The pitch, the architecture diagrams, the demo video. |

---

## 1. Adopted in this PR

### 1.1 UTCI — the second index the problem statement names

**Gap closed:** `AGENTS.md` §7.2 — *"UTCI — the SIH problem statement names both
WBGT and UTCI; only WBGT is implemented."*

**New file: [`core/utci.py`](core/utci.py).** UTCI is an *equivalent temperature*:
the air temperature of a reference environment that would provoke the same
physiological strain as the actual combination of air temperature, mean radiant
temperature, wind and humidity. It comes out of the Fiala multi-node
thermoregulation model, which is far too slow to run 20,304 times per cycle, so
the UTCI project published a 6th-order polynomial approximation. That 210-coefficient
table is vendored here, with the paper cited in `UTCI_METADATA`:

> Bröde, P.; Fiala, D.; Błażejczyk, K.; Holmér, I.; Jendritzky, G.; Kampmann, B.;
> Tinz, B.; Havenith, G. (2012). *Deriving the operational procedure for the
> Universal Thermal Climate Index (UTCI).* Int J Biometeorol 56(3):481–494.
> doi:10.1007/s00484-011-0454-1

**Where the literature tools came in.** Finding the *authoritative* coefficient
table — not a blog-post transcription — is the whole job here. Semantic Scholar
and typeset.io are the discovery path; the table was then verified numerically
against a published reference implementation across 4,000 random points spanning
the validity envelope (agreement ~1e-12 °C) **before** any value was baked into
a test. Transcription errors in a 210-term polynomial are invisible to the eye
and catastrophic in the output, so this is exactly the step that must not be
skipped.

**How the three indices coexist — they are not interchangeable:**

| Index | Audience | Drives |
|---|---|---|
| **WBGT** (ISO 7243) | occupational | hazard score, work/rest rules, the risk model |
| **Heat Index** (NWS) | public, English | SMS copy |
| **UTCI** (Bröde 2012) | public health | CAP severity, population heat-stress category, cross-city comparison |

UTCI is computed from the *same* globe temperature as WBGT (ISO 7726 conversion),
so the two radiation-aware metrics can never disagree because one was built on a
different sun. It is **not** an input to the risk score — WBGT stays the model
driver. Plumbing:

- `core/thermal.py` — `utci_c` / `utci_band` per ward-hour; `utci_peak_c` per ward-day
- `core/risk.py` — `utci_adj_c`, the **UHI-adjusted** value, because an alert
  quoting the grid cell instead of the ward would be wrong by up to 3.5 °C
- `core/htsi.py` — `utci_c` in the quality-flagged metadata layer, with its
  validity envelope and both fallback biases documented
- `app/main.py` — `/thermal/utci` (method card), `utci` in `/thermal/ward/{id}`
- 29 new tests in `tests/test_utci.py`

### 1.2 CAP 1.2 + GeoJSON — the SACHET hand-off

**Gap closed:** `AGENTS.md` §7.1 — *"CAP / GeoJSON alert output and a documented
hand-off to SACHET."*

Twilio is a pilot channel: it reaches subscribers, not the district
administration, and no aggregator can ingest an SMS. **CAP 1.2** (OASIS Common
Alerting Protocol — also ITU-T X.1303 / ISO 22322) is what NDMA's
[SACHET](https://sachet.ndma.gov.in) portal consumes and redistributes in twelve
regional languages.

**New files: [`core/cap.py`](core/cap.py), [`core/geo.py`](core/geo.py),
[`core/i18n.py`](core/i18n.py).**

```
/alerts/cap       → the CAP document described as JSON (for a dashboard / static host)
/alerts/cap.xml   → the wire format, application/cap+xml (RFC 7801)
/alerts/geojson   → RFC 7946 FeatureCollection — the layer a control room drops into QGIS
```

Design decisions worth defending to a judge:

- **One `<info>` block per language.** CAP repeats `<info>` for translations of
  the *same* event. That is precisely SACHET's multilingual model, so the
  language work (§1.3) and the interoperability work are the same work.
- **Deterministic `<identifier>`.** Same wards, same minute, same identifier — an
  aggregator polling on a timer can drop a repeat without tracking state.
- **Real ward polygons**, thinned to 60 vertices (decimation, never
  simplification — it cannot invent a corner). If the geometry file is missing
  the feed falls back to centroid *circles* sized from each ward's real area and
  **says which it used** in `geometry.shape`. A circle is not a ward outline and
  the payload does not pretend otherwise.
- **Element order is asserted.** CAP 1.2 is a sequence, not a bag.
  `tests/test_cap.py` checks the order, and that polygons are latitude-first
  (getting that backwards draws the ward in Somalia — the most common CAP bug
  there is).
- **Demo rows are refused.** Live dispatch refuses synthetic events behind two
  locks; the CAP feed refuses them with no lock to open, because a CAP document
  that has left the building cannot be recalled.
- **Empty is valid.** A run with no warnings emits a valid CAP message with no
  `<info>` rather than an error, so a consumer never has to special-case it.

`SACHET_HANDOFF` in `core/cap.py` carries the remaining administrative steps
(registering the issuing authority, replacing the placeholder sender address,
signing off the translations) — the honest statement that the *format* work is
done and the *onboarding* work is not a code change.

### 1.3 Hindi and Bengali alert copy

**Gap closed:** `AGENTS.md` §7.6.

English-only warnings in Kolkata are not public warnings. `core/i18n.py` carries
the copy in `en` / `hi` / `bn`, and the rules are enforced in
`tests/test_i18n.py`:

- **Numbers never move.** `41.2 °C` is `41.2 °C` in Bengali — the test extracts
  every number from every language and asserts they are identical. (This caught
  a real bug: the Bengali guidance used Bengali-Indic digits `১২`, which would
  have made the same warning read differently to two residents.)
- **English is authoritative**; a missing key falls back to it rather than
  dropping the line.
- **Segment cost is reported, not assumed.** Devanagari and Bengali are UCS-2:
  70 characters per SMS segment, not 160. The same message costs 2 segments in
  English and 5 in Bengali. `sms_segments` comes back with every alert row.
- **Translations are labelled as operational drafts** awaiting sign-off by the
  issuing authority — `TRANSLATION_STATUS`, surfaced in the UI.

`core/alerts.compose_message()` now delegates to `core/i18n`, so the SMS body
and the CAP `<description>` are composed by one implementation and cannot drift.

### 1.4 data.gov.in / api.data.gov.in — the demographics adapter

**New file: [`core/datagov.py`](core/datagov.py).** Route: `/integrations/datagov`.

`DATA.md` has been honest since the first commit that **population aged 60+**
and **slum share** are absent rather than modelled. Those are the two strongest
modifiers of heat mortality, and data.gov.in is where the machine-readable
versions would come from. The adapter:

- fetches `https://api.data.gov.in/resource/{id}` when `HS_DATAGOV_API_KEY` is set;
- raises `NotConfiguredError` when it is not — and the message says the pipeline
  is unaffected, because an operator reading a stack trace should not go hunting
  for a failure that isn't there;
- ships a **catalogue** of six datasets, each recording *which gap it would
  close*, its *geography* (ward vs. town vs. district — a district-level proxy
  cannot fix a ward-level index), and its *status*.

**No resource IDs are invented.** api.data.gov.in addresses datasets by an
opaque per-upload id; a plausible-looking placeholder would turn "not
configured" into a 404 that looks like a data outage. Every entry ships
`resource_id: None` with the steps to find the real one, and
`tests/test_datagov.py` asserts that stays true.

The highest-value entry is not the demographics at all — it is **IMD daily
station observations**, which is what closes `AGENTS.md` §7.4 (bias correction
and verification). Alipore and Dum Dum observed maxima against the forecast
that predicted them is the difference between "our model says" and "our model
skilled".

### 1.5 Streamlit operator console

**New file: [`ops/console.py`](ops/console.py).** `streamlit run ops/console.py`

Streamlit was already in `requirements.txt` and unused. The console is a
read-only view over `data/processed/*.csv` — it computes nothing of its own, so
it cannot disagree with the dashboard. It needs no network and no credentials,
which is exactly why it can be shown to a judge on a laptop with no signal. It
shows the league table, the alert copy in all three languages with segment
counts, and a live CAP XML preview.

It is **not** part of the request path and **not** a replacement for FastAPI —
the API stays stateless and horizontally scalable.

### 1.6 Faker / Mockaroo — synthetic fixtures, fenced

**New file: [`scripts/gen_fixtures.py`](scripts/gen_fixtures.py).**

`AGENTS.md` §6.1 is *never fabricate data*, and a generated row that looks like
a real resident is one config mistake away from a real send. So the generator is
built so that misuse is difficult and obvious:

1. it refuses to write to `data/subscribers.csv` without `--i-know-what-im-doing`;
2. every row carries `synthetic=true` and a note column;
3. phone numbers come from the reserved, unroutable `+91 0000 00xxxx` block, so
   a misrouted load test fails at the provider instead of texting a stranger;
4. output is deterministic for a given `--seed`, so a budget check cannot flap.

The scale-out table in `AGENTS.md` §8 says delivery, not compute, is the
bottleneck (~75k messages per event at national scale). This is how you test
that without endangering anyone.

### 1.7 Deployment — Render · Netlify · Vercel · Docker

| File | Host | Deploys |
|---|---|---|
| `render.yaml` | [Render](https://render.com) | FastAPI service (blueprint, env vars documented) |
| `netlify.toml` | [Netlify](https://netlify.app) | static frontend + security headers + SPA rewrite |
| `vercel.json` | [Vercel](https://vercel.com) | static frontend |
| `Dockerfile` | anywhere (AWS Free, Railway, Fly) | API container, non-root, healthcheck, ships the cache so it serves real numbers on its first request with no network |
| `.github/workflows/deploy-pages.yml` | GitHub Pages | **already** ships the static build — the zero-cost default |

Two things in those files are not boilerplate:

- **`sw.js` is `no-cache`** on every host. A stale service worker pins the
  entire app; a stale `/static-api/*` snapshot pins the numbers.
- **Free tiers sleep.** Render's free web service takes ~30 s to wake. That is
  acceptable for a demo and wrong for a warning system — a warning that arrives
  late is not a warning. Production wants an always-on instance.

---

## 2. Adopt next

Ordered by value to the mission.

| # | Task | Resource | Why it is next |
|---|---|---|---|
| 1 | **Forecast verification against observed weather** | `data.gov.in` IMD station data, Open-Meteo archive | `AGENTS.md` §7.4. `scripts/hindcast.py` section (B) already computes POD/FAR/CSI by lead time; it is starved of observed data. This is the difference between a demo and a verified system. |
| 2 | **Bias correction** | same | Once (1) exists, the systematic model bias becomes correctable. |
| 3 | **Scale-out: CSV → Postgres/PostGIS** | Supabase (free Postgres + PostGIS) | `AGENTS.md` §8 puts the inflection point at ~10,000 wards. The free tier is enough to prove the 250-city case. |
| 4 | **Remaining SACHET languages** | `core/i18n.py` | Nine of twelve are still marked `not wired`. Each needs a reviewer, not a machine. |
| 5 | **NCMRWF / IMD NCUM ingestion** | MoU, not an API | `AGENTS.md` §7.3. Only `core/weather.py` changes — the engineering is trivial, the access is not. |
| 6 | **Operator "explain this warning"** | LangChain, retrieval over HeatShield's own payloads | Off the scoring path only. See §4 for the boundary. |
| 7 | **Real mortality calibration** | — | `AGENTS.md` §7.7. **Blocked on data that does not exist at ward level.** Do not pretend otherwise. |

---

## 3. Where the data actually comes from today

Already in the repo, all citable, all in the `DATA.md` provenance table:

| Input | Source |
|---|---|
| 141 KMC ward polygons | **datameet/Municipal_Spatial_Data** (ODbL) |
| Ward population | Wikidata `P1082`, stated-in Census of India 2011 (CC0) |
| Literacy, households, workers, SC/ST per ward | **Census 2011 Primary Census Abstract**, official xlsx recovered via the Wayback Machine — censusindia.gov.in is defunct |
| Green cover, water, buildings | OpenStreetMap / Overpass (ODbL) |
| Forecast | Open-Meteo (CC-BY-4.0), keyless |
| Physics | Stull 2011, Rothfusz/NWS, ISO 7243, Ranz–Marshall, **Bröde 2012** |
| Heatwave criteria | IMD (coastal preset) |
| Basemaps and globe imagery/terrain | keyless Esri, OpenTopoMap, OSM, Re:Earth/Mapterhorn |

**Kaggle, data.world and nicedoc/india-data belong in the *discovery* column,
not the *vendor* column.** They are excellent places to find an Indian
heat–health dataset; they are poor places to source one that ships in the repo,
because licence terms and provenance are frequently ambiguous and a judge will
rightly ask. Anything found there gets the same treatment as everything else:
a row in `DATA.md` naming the source, the licence, and the verification.

---

## 4. Deliberately not used — and why

This section is here because a warning system is judged by its refusals.

| Resource | Why not |
|---|---|
| **NJDG eCourts** | Court-pendency data. No open bulk API, no thermal or demographic signal, and no defensible link to a heat warning. |
| **e-District** | State service-delivery portals. Interesting as a *last-mile channel* (they already reach citizens who will never install a PWA), not as a data source. Worth a conversation with the state; not a code change. |
| **NDHM / ABHA Health ID** | Health-identity infrastructure. Linking a heat warning to an individual's health record is a consent and privacy question that must be settled by the issuing authority, not by a hackathon prototype. The system warns *wards*, not people. |
| **UIDAI / Aadhaar** | Same, stronger. Aadhaar is an identity system with no heat data, and using it here would be a privacy regression dressed as a feature. Deliberately out of scope, permanently. |
| **LangChain / Rasa in the scoring path** | A warning must be deterministic, reproducible and auditable. An LLM that paraphrases a warning can drop the number that matters, and two runs of the same forecast must produce byte-identical output (`AGENTS.md` §6.7 — idempotency is a hard constraint). Off the critical path, for an operator Q&A surface with retrieval over HeatShield's own payloads, there is a real and narrow use. |
| **jsonplaceholder** | A live third-party echo in CI is a flake source and an outage dependency for zero benefit. The suite injects stubs (`tests/test_datagov.py` passes a `getter`) and asserts the same behaviour. |
| **Faker / Mockaroo in the data pipeline** | See §1.6 — fenced to fixtures, never published numbers. |
| **Perplexity / Semantic Scholar inside the app** | Research-time tools, not runtime dependencies. A warning system must not need a search engine to decide what to say. |

---

## 5. Presentation layer

Gamma, Whimsical, Figma, Excalidraw, Napkin and Descript do not touch the
pipeline, and that is correct. Two notes from experience on this repo:

- **Excalidraw** is the right choice for the architecture diagram: it exports
  SVG, which diffs in git and stays readable in the README.
- **SIH · MyGov · AICTE · MIC** are the submission surface, not inputs. The
  problem statement is itself a constraint to quote: it names **both** WBGT and
  UTCI, which is why §1.1 exists.
- **NITI Aayog** and **PRS India** are the policy frame — Heat Action Plans,
  and the question of who has the legal authority to issue a warning. That
  question is administrative, and it is the one real blocker in §1.2.

---

## 6. Verify this work

```bash
HS_FORECAST_DAYS=5 python -m pytest -q            # 366 passed
python -m scripts.refresh --offline               # 20,304 ward-hours / 846 ward-days
python -m core.utci                               # UTCI validation table
python -m core.cap                                # CAP XML + GeoJSON + SACHET hand-off
python -m core.i18n                               # the same warning in three languages
python -m core.datagov                            # adapter state (inert without a key)
python -m scripts.gen_fixtures --subscribers 5000 --out /tmp/subs.csv
streamlit run ops/console.py                      # operator console, no network needed
```

New API surface:

```
GET /thermal/utci           UTCI method card: formula, envelope, provenance
GET /alerts/plan?lang=bn    the alert queue with Bengali copy + segment count
GET /alerts/cap             CAP 1.2 as JSON
GET /alerts/cap.xml         CAP 1.2 as XML (application/cap+xml)
GET /alerts/geojson         RFC 7946 FeatureCollection
GET /integrations/datagov   optional-adapter state and dataset catalogue
```
