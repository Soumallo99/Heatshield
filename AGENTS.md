# AGENTS.md — read this before changing anything

> Orientation for AI coding agents (Codex, Copilot, Claude, Gemini, Cursor, Antigravity).
> This file is the single source of truth about the project. `CLAUDE.md`, `GEMINI.md` and
> `.github/copilot-instructions.md` are pointers back here — edit **this** file, not those.

---

## 1. What this project is

**HeatShield** — *Extreme Heatwave Early Warning and Human Thermal Stress Index*.

An **impact-based health warning system**, not a weather app. It ingests an open forecast for
Kolkata, runs human thermal-physics models, adjusts for each ward's urban heat island, weights the
result by ward-level vulnerability, and produces **ward-level heat warnings with SMS copy** and a
2–5 day lead time.

Built for **Smart India Hackathon 2026**. 141 real KMC wards. Currently being presented to judges.

The one-sentence distinction that matters: **IMD tells you the temperature will be 40 °C.
HeatShield tells you Ward 24 crosses the danger threshold on Monday and 12,489 residents there
are exposed.**

---

## 2. Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend/web && npm install && cd ../..

./start.sh                    # Windows: start.bat
#   dashboard :5173 · API :8000 · docs :8000/docs · PWA build :4173 (./start.sh --pwa)

python -m scripts.refresh          # re-fetch live forecast + re-score all wards
python -m scripts.refresh --offline # no network: replay the cached fetch (says so loudly)
HS_FORECAST_DAYS=5 python -m pytest -q   # expect: 164 passed
```

Editor setup: `VSCODE.md` (VS Code) or `ANTIGRAVITY.md` (Google Antigravity).

> **No API key is required.** There is no `.env`, no token, no signup anywhere in the
> pipeline. See [section 11](#11-credentials--there-are-none-by-design).

---

## 3. Invariants — if these change, you broke something

| Invariant | Value |
|---|---|
| Wards | **141** (real KMC wards) |
| Ward-hours fetched per cycle | **20,304** (141 × 144 h) |
| Ward-days scored | **846** (141 × 6 days) — see the window note below |
| Open-Meteo requests per cycle | **4** (batched 40 coords/request) |
| Tests | **164 passed** (`HS_FORECAST_DAYS=5`) |
| `/zones` count | **141** |
| Alert threshold | **60.0** (`DEFAULT_RISK_THRESHOLD` in `core/alerts.py`) |
| Default min lead | **1 day** (`DEFAULT_MIN_LEAD_DAYS`) |
| Demo scenarios | **4** — fixed clock, issued **2026-05-18T06:00 IST**, 8 zones × leads 0–5 = 48 rows each |
| Demo disclaimer | defined **once**, in `core/warnings.py` (`DEMO_DISCLAIMER`) |
| Static exports | **30** files in `frontend/web/public/static-api/` (`scripts/export_static.py`) |

A full cycle takes **~4 seconds**. If yours takes minutes, you have un-batched the API calls.

**About the window — this trips people up.** `HS_PAST_DAYS=1` + `HS_FORECAST_DAYS=5` means Open-Meteo
returns **6 days: yesterday → today+4**, not "today → today+5". That is deliberate — yesterday is
included to give the model a "now" reference. So on 2026-09-16 the window prints
`2026-09-15 → 2026-09-20`, and 141 × 6 = **846** ward-days. If you ever see 705 (= 141 × 5),
something has dropped yesterday from the window.

---

## 4. Architecture — the pipeline

```
Open-Meteo (free, keyless)
   └─> core/weather.py      fetch → get_forecast(), daily_peak()
        └─> core/thermal.py  physics → compute_thermal(), daily_thermal()
             └─> core/risk.py      impact → compute_risk(), daily_risk(), ward_ranking()
                  └─> core/alerts.py    decisions → dispatch(), compose_message()
                       └─> data/processed/*.csv  →  app/main.py (FastAPI)  →  React dashboard
```

Orchestration: `scripts/refresh.py` (one-shot) · `scripts/schedule.py` (daemon, `--once`,
`--interval-minutes`, prunes archive to 400) · `scripts/hindcast.py` (A = replay over observed
weather, B = POD/FAR/CSI verification) · `scripts/build_wards.py` + `scripts/build_demographics.py`
(offline data build from open sources).

### Physics (`core/thermal.py`) — verified against source, do not "simplify"

| Quantity | Formula |
|---|---|
| Heat Index | NWS Rothfusz regression (evaluated in °F internally) + the 3 standard NWS adjustments. Returns air temperature below 20 °C |
| Wet bulb `Tw` | **Stull** (model path) · psychrometric bisection ×45 (validation path only). Agreement: 0.175 / 0.553 °C |
| Globe temp `Tg` | `Ta + (ε·S) / (4·(h_conv + h_rad))`, `Nu = 2 + 0.6·√Re·Pr^⅓` (Ranz–Marshall). Wind floored at 0.13 m/s. **The `/4` is not a typo** |
| WBGT | `0.7·Tw + 0.2·Tg + 0.1·Ta` when solar > 20, else `0.7·Tw + 0.3·Ta` |
| IMD heatwave (coastal) | Heatwave if `Tmax ≥ 37 °C` or departure `≥ 4.5 °C`; severe if `≥ 40 °C` or `≥ 6.4 °C` |

### Risk (`core/risk.py`)

```
UHI   = 0.45·log10(pop) + 0.35·green_deficit + 0.15·log1p(built) + 0.05·water_deficit
        → min-max normalised × 3.5 °C, clamped to (0, 5)
        apply_uhi() holds DEWPOINT constant, so relative humidity FALLS as temperature rises.
hazard = 100 · clip((WBGT − 25)/11, 0, 1)^1.4
vuln   = pop .22, green_def .22, built .13, water_def .08
         | illiteracy .20, crowding .08, outdoor_work .07
         weights RENORMALISE over the columns actually present → graceful degradation
         if Census data is missing for a city.
risk   = hazard × (0.55 + 0.45 · vuln/100)
RR     = exp(0.025 · max(0, WBGT − 27))      baseline mortality 7.2 / 1000 / yr
```

`ward_ranking()` picks each ward's **peak day** (`groupby(date).risk.max().idxmax()`), not the
horizon end. Changing that silently changes the headline number.

---

## 5. Repo map

```
core/          weather · thermal · risk · alerts · subscribers · config      ← Kolkata engine
               coupled · htsi · health_impact · warnings · demo · notify     ← NCR impact engine
app/main.py    FastAPI: /health /zones /risk/ranking /alerts/* /subscribers* /ncr/*
               /heatwave/advance /warnings/advance /notifications/* /demo/* /docs
scripts/       refresh · schedule · hindcast · build_wards · build_demographics · package
               build_climatology · validate_coupled_aqi · export_static · dispatch_notifications
frontend/web/  Vite + React + Framer Motion + Tailwind dashboard
               src/mobile (citizen phone PWA) · src/demo (Heat Risk Demo)
data/          wards, census, processed outputs, cache, subscribers.csv,
               climatology_normals.json, validation/
tests/         164 test cases, incl. the SSR harnesses tests/mobile/render_mobile.mjs
               and tests/demo/render_demo.mjs (react-dom/server, no browser)
```

---

## 6. Hard constraints — do not break these

1. **Never fabricate data.** Population 60+ and slum share are **deliberately absent** because no
   ward-level source exists. `DATA.md` and the UI state plainly that the index measures exposure,
   urban form and socioeconomic deprivation — *not* physiological frailty. Do not invent numbers
   to fill the gap, and do not quietly add a proxy that implies otherwise.
2. **PWA only. No APK, no Capacitor, no Android Studio.** Do not add `npx cap`, Gradle, or Java
   requirements. `frontend/web/public/sw.js` (`heatshield-v2`) is the offline story. A store-style
   Android APK/AAB is still available **without touching this rule**: package the *deployed* PWA
   through PWABuilder (TWA) — documented in README → "Install on Android". Packaging happens
   outside the repo, so a clone still needs only Python + Node.
3. **Both metrics are intentional.** WBGT drives the model; Heat Index appears in public/SMS copy.
   Do not collapse them into one.
4. **FastAPI is the backend; don't rewrite it** for frontend convenience. The API is stateless on
   purpose — that is what makes it horizontally scalable.
5. **UI bar is high.** Elegant typography; expert-level motion (spring physics, staggered
   entrances, `layoutId` shared transitions, `prefers-reduced-motion`, transform/opacity only,
   60 fps). Sloppy animation is a regression. Surfaces are flat on purpose: `.panel` carries **no**
   `backdrop-filter` (it used to blur nine dashboard cards at once — three times the
   `UI_SPEC.md` budget of three). Blur is opt-in via `.panel--blur` and reserved for the chrome
   that floats over moving content: the top bar, the route switcher, the map readout.
6. **Offline-first matters.** The dashboard must render from `data/processed/*.csv` with no
   network. Don't make a live fetch a hard dependency of first paint. "No network" means *no
   internet* — the browser still talks to the local FastAPI, which serves those CSVs. It never
   means "the frontend invents numbers" (see rule 8). On the API side, `get_forecast()` mirrors
   this: when the cache is stale *and* the live pull fails, it serves the last real fetch (up to
   7 days old, `STALE_FALLBACK_MIN`) instead of a 500, and re-probes the network at most every
   120 s (`FETCH_FAIL_COOLDOWN_S`). `fetched_at` travels with the data so age is always visible.
   `scripts/refresh` live mode still fails loudly — refreshing is the operator's explicit act.
7. **`scripts/refresh.py` must stay idempotent** and safe to run repeatedly. Re-scoring the same
   cached forecast must reproduce the committed `data/processed/*.csv` byte for byte.
8. **No demo data in the UI — live-first.** `frontend/web/src/api.js` throws when the API is
   unreachable; there is no `MOCK_*` fallback and there must not be one again. Components render
   an honest state instead (`components/LiveStatus.jsx`): *"API unreachable — showing last known
   data"* when a refresh fails over good data, or the exact command to start the API when there is
   nothing on screen. A dead backend must look dead.
   Refresh is **manual** — a button plus the `R` shortcut, with a "last updated HH:MM:SS" clock.
   No auto-polling. All calls are relative `/api/*` proxied by Vite; never `localhost` from
   browser code.

   **The one sanctioned exception: the Heat Risk Demo (`#/demo`).** Synthetic data is the demo's
   entire point — deterministic scenarios from `core/demo.py` served at `/demo/*` and exported to
   `public/static-api/demo-*.json` so it works offline with zero credentials. It never
   masquerades as live: every payload, notification message and server-rendered screen carries
   the canonical disclaimer (defined once in `core/warnings.py`, drift-guarded by tests), rows
   are stamped `demo-synthetic`, health-impact status is always `synthetic_demo`, the clock is
   fixed (2026-05-18T06:00 IST — never `today`), and demo/synthetic rows are **refused by live
   notification dispatch even with both locks open**. Demo frontend code lives in
   `frontend/web/src/demo/*` with its own data loader; it shares no path with `api.js`, and the
   live-first rule above still applies to every other surface.

---

## 7. Known gaps — good tasks for an agent

Ordered roughly by value to the judges:

1. **CAP / GeoJSON alert output** and a documented hand-off to **SACHET** (`sachet.ndma.gov.in`,
   NDMA's national CAP portal, 12 regional languages). Twilio is the pilot channel only.
2. **UTCI** — the SIH problem statement names both WBGT *and* UTCI; only WBGT is implemented.
3. **NCMRWF / IMD NCUM ingestion** instead of Open-Meteo. Engineering is trivial (only
   `core/weather.py` changes); access is an MoU, not a code problem.
4. **Bias correction / ensemble spread / real-time assimilation** — currently a deterministic
   single-model run with no uncertainty quantified end-to-end.
5. **Scale-out above ~10,000 wards:** CSV → PostGIS, parquet → Redis, one pandas process →
   chunked/parallel. See the numbers in section 8.
6. **Hindi/Bengali alert copy** — currently English-only.
7. **Real mortality calibration.** The boundary is now formalised in `core/health_impact.py`:
   three explicit model statuses, a strict observed-outcome CSV schema
   (`load_health_outcomes`) and an evaluation-report requirement — the repo ships only labelled
   synthetic examples, so `validated_observed_outcome_model` is unreachable by design and
   `tests/test_health_impact.py` enforces that no payload can claim it. **Blocked:** no
   ward-level outcome data exists. Do not pretend otherwise.

---

## 8. Scaling numbers (for the scalability question judges ask)

| Scale | Wards | Ward-hours | Requests | Cycle | Storage |
|---|---|---|---|---|---|
| Kolkata | 141 | 20,304 | 4 | ~4 s | 2.3 MB |
| 250 HAP cities | ~37,500 | 5.4 M | ~940 | ~14 min | ~630 MB |
| National | ~100,000 | 14.4 M | ~2,500 | ~37 min | ~1.7 GB |

Inflection point ≈ **10,000 wards**. Adding a city needs **no code change** — every ward feature
is derived from open data — just `build_wards` + `build_demographics` + `refresh`.

Two honest caveats to preserve if you touch this: vulnerability is min–max normalised **within a
city**, so cross-city ward scores are not comparable without per-city calibration; and delivery
(≈75k messages/event at national scale), not compute, is the real bottleneck.

---

## 9. Data provenance

| File | Source | Status |
|---|---|---|
| `data/wards.csv`, `kolkata_wards.geojson` | KMC / Datameet boundaries | **Real**, 141 wards |
| `data/census2011_ward_demographics.csv` | Census 2011 PCA, Kolkata | **Real** |
| `data/processed/forecast_hourly.csv` | Open-Meteo, fetched live | **Real, live** |
| `data/mortality_labels.SYNTHETIC.example.csv` | Generated for validation | **Synthetic** — labelled as such |
| Population 60+, slum share | — | **Absent on purpose** |

Full detail in `DATA.md`.

---

## 10. Before you open a PR

```bash
HS_FORECAST_DAYS=5 python -m pytest -q                    # must be 164 passed
python -m scripts.refresh                                 # must still print 20,304 / 846
HS_FORECAST_DAYS=5 python -m scripts.export_static --check # catalogue == FastAPI routes
HS_FORECAST_DAYS=5 python -m scripts.export_static        # refresh public/static-api/
cd frontend/web && npm run build                          # must succeed
cd frontend/web && npm run budget                         # phone cold-open gate (120 KiB gzip)
```

CI (`.github/workflows/ci.yml`) runs exactly these on every push.

If you change any physics or weighting constant, update the tables in section 4 above and the
corresponding note in `DATA.md` — they are quoted in the presentation.

---

## 11. Credentials — there are none, by design

**The forecast pipeline needs no API key.** The data source is
[Open-Meteo](https://open-meteo.com), which is keyless. Verified across the whole codebase:
there is no `apikey` parameter, no `Authorization` header and no `Bearer` token anywhere. There
is also no "sandbox mode" — nothing in the code branches on where it's running.

That's a feature worth protecting: **anyone can clone this repo and run the entire system
without registering for anything.** It's also a point in the judges' favour (zero marginal cost,
no vendor lock-in).

### The one optional credential

**Twilio**, for actually transmitting SMS. Without it the alert engine still runs completely — it
composes every message and logs what it *would* have sent. `dispatch()` defaults to
`dry_run=True`.

Live sending is behind **two independent locks**, in `core/alerts.py`:

```python
live_send_allowed()   # needs BOTH:
                      #   1. HS_ALLOW_LIVE_SEND in {1, true, yes}
                      #   2. TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_NUMBER
```

If either is missing, `dispatch(events, dry_run=False)` **raises `PermissionError`** with a
readable reason. It fails loudly — it never silently swallows the request, and it never sends.

### If you're asked to add a keyed provider

Someone may want IMD/NCMRWF (an MoU, not an API key), OpenWeather, Tomorrow.io, or an LLM.
Rules for that change:

1. **Only `core/weather.py` should change.** `thermal.py`, `risk.py`, `alerts.py`, `app/` and the
   frontend must not need to know where the weather came from. If your change leaks provider
   details into them, the design is wrong.
2. **Keep it working keyless.** Read the key from config, and fall back to Open-Meteo when it's
   absent. A clone without a `.env` must still run — that's already the contract, and CI depends
   on it.
3. **Add the variable to `core/config.py` and document it in `.env.example`.** Every knob is
   optional and has a working default; don't introduce a required one.
4. **Never commit a real key.** `.env` is gitignored. If a key reaches the repo, it must be
   rotated, not just deleted from the commit.

Everything currently configurable is listed in `.env.example` — read it before adding anything.
