# HeatShield 🛡️ — Extreme Heatwave Early Warning & Human Thermal Stress Index

> **Is this real data?** Almost entirely — and the split is documented in **[`DATA.md`](DATA.md)**.
> Weather, ward boundaries, ward population, literacy / households / workers (official Census
> 2011 Primary Census Abstract), green cover and buildings are all real and citable
> (population sums to the official Census figure exactly). Only **population aged 60+** and
> **slum share** are missing, and they are deliberately **absent rather than invented**.

> **New here?** Read [`SETUP.md`](SETUP.md) for step-by-step install instructions, or just run
> `./setup.sh` (macOS/Linux) / `setup.bat` (Windows).
> Editor-specific walkthroughs: [`VSCODE.md`](VSCODE.md) · [`ANTIGRAVITY.md`](ANTIGRAVITY.md).
> Putting it on GitHub: [`GITHUB.md`](GITHUB.md).
> **Working with an AI agent on this code?** It should read [`AGENTS.md`](AGENTS.md) first —
> architecture, physics formulas, invariants and hard constraints in one file.

## Run it on your laptop

**One command:**

```bash
./start.sh          # macOS / Linux / WSL
start.bat           # Windows
```

That boots the API on `:8000` and the dashboard on `:5173`, and shuts both down
cleanly on Ctrl-C. Add `--pwa` (`start.sh --pwa`) to also build and serve the
offline-capable production build on `:4173`. `./stop.sh` stops everything.

```bash
./start.sh --pwa    # + production PWA build on :4173 (offline capable)
./stop.sh
```

Logs land in `logs/` (`api.log`, `web.log`, `pwa.log`, `build.log`).

If you prefer to run the pieces yourself:

You need **Python 3.10+** and **Node 18+**. Nothing else — no API keys, no database.
Open-Meteo is keyless for non-commercial use, and Twilio is only needed to actually send SMS.

```bash
# --- one time -------------------------------------------------------------
git clone <your-repo-url> heatshield && cd heatshield

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # or: pip install -r requirements.lock.txt

cd frontend/web && npm install && cd ../..

# --- every time (two terminals) -------------------------------------------
# Terminal 1 — API on http://localhost:8000  (docs at /docs)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — UI on http://localhost:5173
cd frontend/web && npm run dev
```

Then open **http://localhost:5173**. The Vite dev server proxies `/api/*` to the FastAPI
backend, so the browser never calls port 8000 directly.

Want one command instead of two?

```bash
./setup.sh          # macOS / Linux
setup.bat           # Windows
```

### If you get stale data
The forecast is cached for 30 minutes. To force a fresh fetch and rebuild every table:

```bash
python -m scripts.refresh
```

### Production build
```bash
cd frontend/web && npm run build && npm run preview
```

### Actually sending SMS / WhatsApp
Everything is **dry-run by default** — it prints what it would send and touches no
credentials. To go live, copy `.env.example` to `.env` and fill in Twilio:

```ini
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=whatsapp:+14155238886
ALERT_TO_NUMBERS=+91...          # fallback when a ward has no subscribers
HS_ALLOW_LIVE_SEND=1             # second lock — without this, sending is refused
```

Live dispatch needs **two** things, on purpose: real credentials *and*
`HS_ALLOW_LIVE_SEND=1`. Missing credentials is a config problem; a missing flag
is the operator not having decided yet. Either one absent and dispatch refuses
with `PermissionError` — you cannot SMS a city by forgetting an argument.

Then preview first, and only dispatch for real when you are happy:

```bash
python -m core.alerts                      # plan only, sends nothing
curl -X POST localhost:8000/alerts/dispatch -H 'content-type: application/json' \
     -d '{"dry_run": true, "per_ward": true}'
```

`per_ward: true` resolves recipients from the subscriber registry (local
residents + citywide duty officers per ward) instead of one flat list.

> **Dry runs never suppress real alerts.** `dispatch()` logs every attempt, but
> only rows with status `sent` count for the 12-hour de-duplication. A rehearsal
> therefore cannot silence the warning it was rehearsing, and a *failed* send
> stays eligible for retry.

---

Impact-based heat warning system: weather forecast → thermal stress (WBGT/HI) → mortality
risk score → ward-level GIS map → SMS/WhatsApp alerts.

## Phases

| # | Phase | Status | Key file |
|---|-------|--------|----------|
| 1 | Weather Data Pipeline (Open-Meteo, 5-day hourly) | ✅ done | `core/weather.py` |
| 2 | Thermal Stress Engine (WBGT + Heat Index) | ✅ done | `core/thermal.py` |
| 3 | Mortality Risk Index (0–100) | ✅ done | `core/risk.py` |
| 4 | Animated UI (Vite + React + Framer Motion) | ✅ done | `frontend/web/` — see `frontend/UI_SPEC.md` |
| 5 | Alerting with lead time (Twilio SMS/WhatsApp) | ✅ done | `core/alerts.py` |
| 6 | Mobile PWA (installable, offline, push) | ✅ done | `frontend/web/public/sw.js` — see `frontend/MOBILE.md` |
| 7a | Unattended scheduler (self-running pipeline) | ✅ done | `scripts/schedule.py` |
| 7b | Ward-level subscriber registry + STOP handling | ✅ done | `core/subscribers.py` |
| 7c | Hindcast & forecast-skill harness | ✅ done | `scripts/hindcast.py` |

**Frontend decision:** Streamlit/Gradio dropped in favour of Vite + React + Framer Motion
(Tailwind, react-leaflet). Streamlit re-runs the script per interaction and blocks the DOM work
heavy animation needs. FastAPI is untouched — it is the data contract. Motion language is
prototyped in `frontend/prototype.html`; full spec in `frontend/UI_SPEC.md`.

**Mobile decision:** PWA, not a native APK. No JDK/Android Studio toolchain, works on iOS too,
and it wraps the same React build. Manifest + service worker ready in `frontend/pwa/`;
guide in `frontend/MOBILE.md`.

## Running it unattended

Everything above runs when you run it. These three make it run by itself and
reach the right people.

**1. Scheduler** — refreshes the forecast, re-scores risk, archives every snapshot
and dispatches alerts on a loop:

```bash
python -m scripts.schedule                          # every 6 h, dry-run
python -m scripts.schedule --interval-minutes 60
python -m scripts.schedule --once                   # single cycle, then exit
```

Stdlib only — no cron, no extra dependency. Each cycle archives its forecast to
`data/archive/`, which is the only way forecast skill can ever be measured.

**2. Subscriber registry** — ward-level recipients instead of one flat list.
`ward_id = 0` means citywide (duty officer, control room) and receives every alert.

```bash
python -m core.subscribers --seed            # DEMO placeholder rows
python -m core.subscribers --stats
python -m core.subscribers --add 9876543210 --ward 24 --name "R. Sen"
python -m core.subscribers --stop 9876543210   # STOP is honoured immediately
python -m core.subscribers --for-ward 24       # who would receive this alert
```

> The seeded rows in `data/subscribers.csv` are **placeholder numbers**, not real
> people. They exist so the prototype resolves to someone. Replace them before
> any live send.

**3. Hindcast / skill** — replays the model on *observed* weather and, once
snapshots exist, scores forecasts against what actually happened:

```bash
python -m scripts.hindcast --days 30
```

Section (A) works today: it runs the pipeline over reanalysis weather and reports
band distribution, threshold crossings and the worst days. Section (B) — true
forecast skill (POD / FAR / CSI by lead time) — needs archived predictions older
than the event, so it fills in automatically once the scheduler has been running
about a week. It says so explicitly rather than inventing a number.

## Data

141 real KMC wards. **See [`DATA.md`](DATA.md)** for the full provenance table:
what is measured, what is modelled, what is missing and why, and how to rebuild the
dataset from source.

Sources: OpenCity/datameet ward polygons (ODbL) · Census 2011 population via Wikidata ·
OpenStreetMap green/water/buildings · Open-Meteo forecast · CARTO basemap.

## Quickstart

```bash
# backend
cd heatshield
./setup.sh                             # Windows: setup.bat   (checks + installs + smoke tests)
source .venv/bin/activate              # Windows: .venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend (second terminal)
cd frontend/web
npm install
npm run dev                            # http://localhost:5173
```

Prefer exact versions? `./setup.sh --locked` installs `requirements.lock.txt`
(the combination verified working: pandas 3.0.5, numpy 2.5.2, scikit-learn 1.9.0).

Full install guide, prerequisites per OS and troubleshooting: **[`SETUP.md`](SETUP.md)**.

- API docs: http://localhost:8000/docs
- `GET /health` — service status
- `GET /zones` — 141 real KMC wards + Census 2011 demographics
- `GET /forecast?hours=24&ward_id=3` — hourly weather
- `GET /forecast/daily` — daily Tmax/Tmin/RH per ward
- `GET /thermal?hours=24&ward_id=3` — hourly WBGT + Heat Index + band
- `GET /thermal/daily` — daily peak WBGT/HI + IMD heatwave flags
- `GET /thermal/ward/14` — ward summary, band, guidance, work/rest rule
- `GET /risk/ranking` — ward league table (what the dashboard + alerts read)
- `GET /risk/daily?scenario_c=6` — ward-day risk, with heatwave stress-test offset
- `GET /risk/ward/3` — single-ward risk drivers + impact estimate
- `GET /risk?hours=24` — hourly risk scores

```python
from core.weather import get_forecast
from core.thermal import compute_thermal, daily_thermal, heatwave_flags

df   = get_forecast()
th   = compute_thermal(df)                 # + wet_bulb_c, globe_c, wbgt_c, heat_index_c, stress_band
day  = heatwave_flags(daily_thermal(df))   # per-ward daily peaks + IMD flags
```

```python
from core.risk import daily_risk, ward_ranking

daily = daily_risk(get_forecast())          # UHI-downscaled, per ward-day
ward_ranking(daily).head()                  # league table: risk, band, drivers, impact
daily_risk(get_forecast(), temp_offset_c=6) # +6 C heatwave stress test
```

Tests: `pytest tests -q` (26 pass) — `tests/test_thermal.py` covers the 11 physics cases,
`tests/test_alerts.py` covers the alert engine and pins every risk-threshold default to one constant.
Heat Index tracks the published NWS chart within ±0.4 °C; Stull wet-bulb tracks a psychrometric
inversion within 0.18 °C mean in the humid regime.

```python
from core.weather import get_forecast, daily_peak
df = get_forecast()          # tidy: ward_id, timestamp_local, temp_c, rh_pct, wind_kmh, solar_wm2, ...
daily_peak(df).head()        # per-ward daily Tmax/Tmin/RH/solar
```

## Layout

```
heatshield/
├── core/
│   ├── config.py        # paths, API params, risk bands, Twilio env
│   └── weather.py       # PHASE 1: fetch -> tidy -> cache
├── app/
│   └── main.py          # FastAPI: /health /zones /forecast /thermal/*
├── frontend/
│   ├── UI_SPEC.md       # locked stack, routes, animation inventory
│   ├── MOBILE.md        # PWA guide (install, offline, push, testing)
│   ├── prototype.html   # animated concept, zero-dependency
│   └── pwa/             # manifest.webmanifest + service worker
├── data/
│   ├── wards.csv        # 141 real KMC ward centroids + real Census 2011 demographics
│   ├── raw/             # timestamped raw JSON from Open-Meteo
│   ├── processed/       # forecast_hourly.csv
│   └── cache/           # TTL cache (parquet or pickle)
├── requirements.txt
├── requirements.lock.txt
├── setup.sh  setup.bat  # one-command installers
├── SETUP.md             # full local install + Android build guide
├── scripts/package.py   # builds the downloadable zip
└── .env.example         # copy -> .env for Phase 5
```

## Gotchas learned in Phase 1

- Use `past_days`, **not** `past_hours` — `past_hours` conflicts with `forecast_days` and
  silently stretches the window to 16 days.
- Open-Meteo accepts comma-separated lat/lon: 141 wards = **1 HTTP request** (~3.8 s).
- Cache TTL defaults to 30 min so the free tier is never hammered while you demo.

## Gotchas learned in Phase 2

- **All 141 wards return near-identical weather.** Open-Meteo's grid is ~11 km; Cossipore and
  Ballygunge land in the same cell. Ward-level *differentiation must come from vulnerability and
  an urban-heat-island downscaling term*, not from the raw forecast — this is the central design
  problem Phase 3 has to solve.
- The Rothfusz dry-air adjustment produces `NaN` outside its valid window (80–112 °F). Clip the
  radicand — `np.where` evaluates both branches eagerly.
- Black-globe energy balance needs the sphere's projected-to-surface area ratio of **1/4**.
  Omit it and Tg lands ~50 °C above air instead of ~10–15 °C.
- `heatwave_flags()` uses the window's own mean as a pseudo-normal when no climatology is
  supplied. Fine for a demo, indefensible in production — load real monthly normals.

## Running the web app

```bash
cd frontend/web && npm install && npm run dev     # http://localhost:5173
```

Three routes: **Overview** (landing), **Operations** (ward risk map + gauge), **Citizen**
(mobile view). Vite proxies `/api/*` → FastAPI, so the browser never calls localhost directly.
The **scenario switcher** (+0 / +2 / +4 / +6 / +8 °C) re-scores every ward live — the fastest way
to demo how the model behaves under a real heatwave.

Production build: `npm run build` → `frontend/web/dist` (107 KB gzipped).
Installable as a PWA (offline + push) — see `frontend/MOBILE.md`.

## Gotchas learned in Phase 3

- **The whole city sits in one ~11 km grid cell**, so raw WBGT is nearly identical across all
  141 wards. Two mechanisms create real spatial spread: **UHI downscaling** (0.0 to +3.5 C,
  matching measured Kolkata UHI of 2-4 C) and the **vulnerability index** (22 to 84).
  Risk spread is now 32 to 64 instead of 14 identical values.
- **`uhi_delta()` returns a Series indexed by position, not by `ward_id`.** Merging it on
  `ward_id` silently shifts every ward by one row — Howrah got Rajarhat's delta and vice versa.
  Re-attach `ward_id` explicitly; there's now an `assert` guarding it.
- When applying a UHI temperature increment, **hold absolute humidity (dew point) constant** and
  let RH fall. Raising T at fixed RH invents moisture that isn't there and overstates wet-bulb.
- **`--scenario +6` breaks Heat Index** (it reads ~72 C). The Rothfusz regression is only
  calibrated to ~55 C. Above that, trust WBGT — HI is for public messaging, not extremes.
- `excess_deaths_per_day` is **illustrative**. Every assumption lives in `MORTALITY` — show it
  to judges rather than hiding it. Real calibration needs municipal mortality records.

## Gotchas learned in Phase 4

- **`/risk/ranking` didn't return `lat`/`lon`**, so the map computed `NaN` centroids and silently
  rendered nothing. Always return coordinates with the row the map consumes.
- **`head(24)` before filtering by ward** returns only ward 1 — rows are ordered ward-by-ward.
  Filter first, then take the window.
- **Timezones:** the server clock is not the forecast clock. Convert to the configured timezone
  before slicing "next 24 hours", or the endpoint silently returns an empty window at midnight.
- **`m.group(1)` doesn't exist** on a `RegExpMatchArray` (use `m[1]`). It white-screened the whole
  app — and only appeared once real data arrived, because the empty-data path never called it.
  There's now an `ErrorBoundary` so a single component can never blank the page mid-demo.
- **Don't animate the SVG `r` attribute** with Framer Motion keyframes; it writes `undefined`
  mid-flight. Animate a transform instead.
- Verified with headless Chrome across 3 routes x 2 viewports: **0 console errors, 0 failed
  requests, 0 horizontal overflow**.


## Gotchas learned in Phase 5

- **`np.int64` is not a Python `int`.** `isinstance()` checks against `int` silently fail on
  numpy integers, so Shapely `STRtree.query()` indices were passed as geometries. Use
  `isinstance(x, (int, np.integer))`.
- **Compose the message before serialising the date.** `to_dict()` + `str(event_date)` up front
  makes `date.strftime()` fail later with a confusing AttributeError.
- **De-duplication can hide everything.** After the CLI dispatch writes to the log, the plan
  endpoint returned `pending: 0` and the UI looked empty. The plan now shows all events, with
  `pending_after_dedupe` as a separate count.
- **Past days inflate "active" counts.** The forecast starts yesterday (`past_days=1`), so
  `date <= today` counted every ward twice (271 of 141). Must be `date == today`.
- **Under an extreme scenario the warning queue empties** — every ward crosses today, so lead
  time is 0 and there is nothing left to warn about. That is correct, not a bug: the endpoint
  now separates `total_events` (actionable warnings) from `active_now` (nowcasts).
- **A ward hot today *and* tomorrow got no warning for tomorrow.** Taking each ward's *first*
  threshold crossing and discarding it when lead time was 0 threw the ward away entirely, so a
  multi-day heatwave produced an empty queue. Fixed by restricting the search to
  `date >= today + min_lead_days` and taking the first crossing inside that window.

## Gotchas learned in Phase 6 (running it after a restore)

- **Restoring a snapshot makes a stale forecast look brand new.** Cache freshness is judged by
  file mtime vs `CACHE_TTL_MIN`, and a restore rewrites every mtime to "now". A three-day-old
  forecast then gets served forever, which silently starves Phase 5: with only one future day
  left in the table, no alert can ever show more than one day of lead time. Fix:

  ```bash
  python -m scripts.refresh     # force-refetch and rebuild every processed CSV
  ```

  Then restart the API so it re-reads them.
- **The map used to rank on the last day of the window, not the worst one.** `ward_ranking()`
  took `date.max()`, which is the furthest-out and often the coolest day — so the map showed a
  calm city while the alerts panel warned about a heatwave two days later. It now defaults to
  the **peak** day in the window. Pin a day with `?date=YYYY-MM-DD`.
- **Band thresholds and the alert threshold are deliberately different.** Bands are
  Normal <25 / Caution <50 / Danger 50–75 / Critical ≥75, but alerts only fire at **risk ≥ 60**
  (`DEFAULT_RISK_THRESHOLD` in `core/alerts.py`), with at least 1 day of lead time.
  So the map can legitimately show 81 wards in "Danger" while just 4 trigger a warning.
- **The sandbox does not persist installed packages.** `node_modules/` and pip packages are
  excluded from workspace snapshots, so after a recycle you must reinstall before anything
  will start:

  ```bash
  python -m pip install fastapi "uvicorn[standard]" python-dotenv pydantic
  cd frontend/web && npm install
  ```
