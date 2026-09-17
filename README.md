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

> **Want the full product with no network, no data and no credentials?** Open the
> **Heat Risk Demo** (`#/demo`, or the amber *Heat Risk Demo* button on the landing page and
> dashboard header). It runs entirely offline from labelled synthetic scenarios — see
> [Heat Risk Demo & impact-based early warning](#heat-risk-demo--impact-based-early-warning).

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
OpenStreetMap green/water/buildings · Open-Meteo forecast · basemaps from CARTO,
Esri World Imagery and OpenTopoMap (all keyless — see [Map basemaps](#map-basemaps)).

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
**Both Operations and Citizen carry a city switch — Kolkata ↔ Delhi NCR.** Kolkata keeps the
141-ward risk map, gauge and scenario levers; Delhi NCR swaps in the eight-zone advance-warning
console (zone table, lead days +0…+5, HTSI/impact views and the keyless demo-style map, fed by
the live `/warnings/advance` rows — or the labelled snapshot when the provider is down). The
Kolkata-specific scenario levers (+0…+8 °C) only re-score the Kolkata model, so they stay on the
Kolkata branch.
The **scenario switcher** (+0 / +2 / +4 / +6 / +8 °C) re-scores every ward live — the fastest way
to demo how the model behaves under a real heatwave.

Production build: `npm run build` → `frontend/web/dist` (107 KB gzipped).
Installable as a PWA (offline + push) — see `frontend/MOBILE.md`.

### Map basemaps

The ward map is a real slippy map, not a static image: pinch/scroll zoom to z20,
`@2x` retina tiles, a scale bar, hover readout, ward search, geolocation, fullscreen,
and a layer switcher with four basemaps — **Dark** (CARTO Dark Matter, default),
**Streets** (CARTO Voyager: full street names, POIs, transit), **Satellite** (Esri
World Imagery with a street-label overlay on top — the "hybrid" look), and **Terrain**
(OpenTopoMap relief + contours). Ward name/score labels thin out by zoom the way a
consumer map does, and risk shading can be toggled off to read the streets underneath.

All four are **keyless** — clone and run, no signup, matching the rest of the project.
Registry lives in [`frontend/web/src/basemaps.js`](frontend/web/src/basemaps.js).

**An *"API key required"* tile can never appear.** The optional keyed-provider upgrade
(`VITE_MAPTILER_KEY` / `VITE_THUNDERFOREST_KEY`) has been removed from the shipped code —
there is no key slot left to misconfigure. And if a tile CDN is unreachable (blocked
network, hostile proxy), `RiskMap` counts `tileerror`s and automatically degrades to
OpenStreetMap standard tiles on a *different* CDN with a visible notice; the demo/Delhi
map does the same. Every map keeps rendering keyless, whatever the network does.

**On "just use Google Maps":** pulling tiles from `mt{n}.google.com/vt` is a ToS
violation and is not done here. The licensed route is the Maps JavaScript API or the
Map Tiles API, both of which require a billing-enabled Google Cloud key — if you have
one, add a Google entry to `basemaps.js` (or swap `MapContainer` for `@vis.gl/react-google-maps`)
and everything else keeps working. The keyless Streets/Satellite styles above are
already drawn from the same underlying OSM + Maxar/Esri imagery Google licenses, so
the cartographic fidelity is comparable without the key or the legal exposure.

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

## Phone app: Delhi NCR + Kolkata briefs

The **Citizen** tab (or `#/phone`) is the installable, thumb-first HeatShield
experience for both covered cities — **Delhi NCR** (heat *and* air) and
**Kolkata** (WBGT thermal-stress-led) — with a city switch at the top; the
choice persists in `localStorage`. It is a deliberately separate surface from
the operations console: a resident needs one clear next action, not a
ward-ranking table.

### Five screens, one decision at a time

| Screen | What it answers | Data shown |
|---|---|---|
| **Now** | *What is my immediate heat + air burden?* | locality, temperature, PM2.5, indicative Indian AQI, combined heat–air load and one plain-language instruction |
| **Outlook** | *Which day needs planning?* | a short daily Tmax/AQI/load table |
| **Watch** | *Is a heatwave developing 3–5 days ahead?* | fixed-normal departure, two-day episode status and an absolute-temperature watch |
| **Safety** | *What should I do?* | hydration, shade, smoke-exposure and neighbour-check actions; emergency symptoms are explicit |
| **About** | *Can I trust this number?* | source, snapshot state, AQI method and model limits |

Swipe left/right anywhere in the card to move between screens. The bottom tabs
are equally usable with a keyboard or assistive technology, and locality chips
provide a non-gesture alternative. The user can always see whether a card is
**live**, a **last exported snapshot**, or a **synthetic outage exercise**.
Synthetic rows are intentionally labelled; they exercise the warning path and
must never be interpreted as observations or a forecast.

### Two cities, one contract

Both briefs speak the same phone payload contract (live `/api/citizen` ↔
`/api/citizen/kolkata`; static `citizen.json` ↔ `citizen-kolkata.json`), so
every screen, normaliser and test serves both:

- **Delhi NCR** keeps the combined heat+air load — the coupled AQI is the one
  validated surface and only ships where that validation exists.
- **Kolkata bundles no air-quality source.** PM2.5/AQI/load fields stay `null`
  with band `Unavailable`, every envelope says so in `source_notice`, and the
  Now/Outlook/Safety cards lead with **estimated WBGT** thermal stress instead —
  plus the plain facts residents asked for: temperature, humidity, wind speed
  and heat index.
- **Kolkata heatwave labels** come from the IMD **coastal absolute-temperature
  rule** (Hot-day ≥ 37 °C; Heat Wave / Severe Heat Wave ≥ 40 °C with two-day
  persistence). `climatology.available` is explicitly `false` — with no fixed
  per-ward normals, departures are never claimed and window-mean pseudo-normals
  never masquerade as climatology.

### Location and notifications

- **Location permission never gates data.** With location off, the app still
  shows the *entire* brief for every ward/locality (chips + search work as
  usual) and offers a one-shot banner **and** browser notification asking the
  user to turn on location so the nearest zone can be pre-selected. Both are
  dismissed forever from `localStorage`; nothing is transmitted anywhere.
- With 🔔 granted, one unified rule (`personalNotificationFor`) decides what to
  send: in a **heat-danger state** (heatwave watch, Extreme/Critical WBGT
  stress in Kolkata, or Poor+ combined load / ≥ 40 °C in Delhi NCR) it fires a
  protective-action alert; **not in danger** it sends a calm informational
  update with temperature, humidity and wind speed (plus estimated WBGT in
  Kolkata). Synthetic payloads always lead with *"Practice data"*.

### Motion and accessibility contract

The phone route uses short horizontal spring transitions and a progress rail;
gesture recognition requires a 48 px predominantly horizontal swipe, so normal
vertical reading does not jump screens. Motion is limited to **transform** and
**opacity**. It never animates `width`, `height`, `top`, `left`, or `filter`.
`prefers-reduced-motion` removes the slide and spinner motion without removing
any state change or controls.

There is no headless browser in this repository's verification environment.
`tests/test_mobile_app.py` instead renders every rich and empty screen through
`react-dom/server` against `public/static-api/citizen.json` **and**
`citizen-kolkata.json` (both cities). It rejects `NaN`,
`undefined` and `Invalid Date`, checks every declared JSX field against the real
generated payload, and enforces the composite-only motion rule. This caught
states that a successful Vite build cannot see.

### Static hosting and cold-open budget

GitHub Pages has no FastAPI proxy. Run the export **before** building Vite:

```bash
HS_FORECAST_DAYS=5 .venv/bin/python -m scripts.export_static --check
HS_FORECAST_DAYS=5 .venv/bin/python -m scripts.export_static
cd frontend/web
npm run build
npm run budget
```

`export_static.py` materialises the whole public catalogue — the nine `/ncr/*`
routes, `/heatwave/advance`, `/warnings/advance`, `/notifications/preview`,
`/citizen/kolkata` and all six `/demo/*` payload families (18 files) — in
`frontend/web/public/static-api/` (31 exports). `citizen-kolkata.json` is a
secondary, on-demand payload (~45 KB gzipped): it is fetched only when the user
switches the citizen tab to Kolkata, so it stays out of the cold-open budget by
design. The phone and demo clients use
relative URLs, go directly to the snapshots on GitHub Pages, and otherwise try
the live relative `/api` first before falling back to those labelled snapshots.
The export catalogue is checked against FastAPI routes (`--check`) so adding a
new endpoint cannot silently become a static-host 404.

The production Vite base, manifest, service-worker registration and cache keys
are all relative (`./`), which keeps a project deployed at
`https://<owner>.github.io/Heatshield/` inside its own path. The current budget
gate limits the actual phone cold-open set (entry + React + motion + phone chunk
+ CSS, never Leaflet, never the demo chunk) to **120 KiB gzip** and the initial
citizen snapshot to **45 KiB uncompressed**. The checked build is currently
**110,996 gzip bytes** and **26,032 bytes** respectively. Full hourly detail exports load
only after the initial brief.

### NCR heatwave method and skill reporting

`GET /heatwave/advance` applies the IMD plains **departure-from-normal** rule:
Tmax must be at least 40 °C and at least 4.5 °C above a fixed 1991–2020 normal;
6.5 °C is severe. Two consecutive qualifying days form an episode. A Tmax of
45 °C is retained as a separate extreme-temperature watch rather than replacing
the anomaly rule. That distinction matters: on a seven-day event peaking at
46.2 °C, a forecast-window mean normal of 43.9 °C can flag **0/7** anomaly days,
whereas a 39.5 °C historical normal flags **5/7**. A window's own mean is never
silently used as a substitute.

Build the normal on a networked machine (the command refuses to invent a file
if its source is unavailable):

```bash
python -m scripts.build_climatology --ncr
```

The resulting `data/climatology_normals.json` stores 366 daily Tmax normals and
12 monthly fallbacks for each of eight NCR locations, derived from the
Open-Meteo historical archive over 1991–2020. It is gridded reanalysis, **not**
a certified IMD station normal; the metadata and UI say so. The manual
`Build NCR climatology` GitHub workflow is a reproducible alternative when a
developer sandbox cannot reach Open-Meteo. It uploads the raw response for
review and, for a same-repository PR, commits only the small generated aggregate.

Heatwave verification reports **Critical Success Index (CSI)** and **Heidke
Skill Score (HSS)** with hits, misses, false alarms and correct negatives; it
does not report bare accuracy. In a mostly non-event data set, a model that
never predicts an event can score 0.951 accuracy while having CSI = 0.

### Coupled AQI: what is—and is not—validated

The NCR hourly air source is Open-Meteo's CAMS atmospheric-composition forecast.
`aqi_india` is an indicative Indian PM2.5 breakpoint sub-index. It stays a
concentration index: HeatShield does **not** quietly increase AQI just because
it is hot. `heat_aqi_load` is a separate, capped heat multiplier intended for
plain-language simultaneous-exposure communication, and is explicitly marked
**parameterised, not a calibrated pollutant or mortality prediction**. Its
unfitted rule is `min(500, AQI × min(1.15, 1 + 0.015 × max(T − 35 °C, 0)))`.
That makes the 35 °C onset, 1.5%/°C increment, 15% cap and 500 cap inspectable
assumptions—not fitted claims.

Validate the concentration source against a named CPCB/CAAQMS station export,
not by changing coefficients until a graph feels plausible:

```bash
python -m scripts.validate_coupled_aqi \
  --observations data/raw/cpcb-station.csv \
  --lat 28.6469 --lon 77.3160 --station "Anand Vihar" \
  --source-url "https://airquality.cpcb.gov.in/ccr/#/caaqm-dashboard-all/caaqm-landing/caaqm-data-repository"
```

The reproducible report at `data/validation/coupled_aqi_validation.json` pairs
daily observed PM2.5 with the corresponding CAMS archive series and reports
MAE, RMSE, mean bias, Pearson *r*, CSI and HSS against a yesterday-observed
persistence baseline. It records the station, period and source URL. The
committed run is a **limited, observed station comparison**:

| Comparison | Samples | Result at 90 µg/m³ daily PM2.5 |
|---|---:|---|
| CAMS archive vs. Anand Vihar DPCC CAAQMS | 47 paired days, 1 Oct–25 Nov 2025 | MAE 103.26 µg/m³, bias −102.73 µg/m³, *r* = 0.722; 17 hits, 20 misses, 0 false alarms; CSI 0.459, HSS 0.266 |
| Yesterday-observed persistence | 41 **adjacent** paired days after coverage gaps | MAE 36.45 µg/m³, bias −4.56 µg/m³, *r* = 0.889; CSI 0.853, HSS 0.658 |

The station export is a SHA-256-checked, pinned public historical DPCC CAAQMS
extract; its exact retrieval URL, hash, daily range and quality screen are in
the report and the `Validate observed NCR PM2.5` workflow. Of 54 days with an
observation, 47 passed the transparent 18-valid-hour (75%) daily coverage
screen. The seven sparse days were excluded; this screen is a quality filter,
not a regulatory certificate. The archive series substantially underestimates
this short, high-pollution station sample and is worse than the persistence
reference. That is a useful validation result—not a reason to tune the heat
multiplier or to claim an operational forecast skill score.

It does **not** claim to validate the heat multiplier, health outcomes, all NCR
locations, the station export's regulatory status, or a lead-time forecast
retrospectively. `/ncr/validation` serves that exact boundary rather than a
flattering chart.

---

## Heat Risk Demo & impact-based early warning

HeatShield is an **impact-based heat-health early-warning platform**: it forecasts what heat
will *do to people* — not just the dry-bulb temperature — with usable **3–5 day advance
warnings** for municipal corporations, health systems, disaster management and residents, and a
**Heat Risk Demo mode** that shows the entire product offline, with no API keys, credentials or
network.

### Why temperature alone is not enough

A 41 °C dry May afternoon and a 35 °C afternoon at 75 % relative humidity are not the same
disaster: humidity suppresses the evaporative cooling that keeps a human body alive, so the humid
day can be the more dangerous one even though the thermometer reads lower. Wind, shortwave
radiation and — critically — **departure from the local climate normal** (acclimatisation) all
shift what a given temperature does to a body. And the same thermal stress lands on populations
with very different capacity to cope. HeatShield therefore keeps three quantities **conceptually
and structurally separate**:

1. **Meteorological thermal stress** — what the weather does to a standard human body (HTSI).
2. **Vulnerability** — who is exposed and how well they can cope (zone profiles).
3. **Health-impact pressure** — a transparent, *parameterised* combination of the two, never
   labelled a validated mortality forecast.

### Architecture and data flow

```
Open-Meteo forecast + CAMS air composition (keyless)
  └─> core/coupled.py        NCR fetch for 8 zones; on provider outage a LABELLED
       │                     synthetic fallback answers (never an HTTP 500)
       ├─> core/htsi.py      Heat Index, estimated WBGT, HTSI + quality flags
       ├─> climatology       fixed 1991–2020 Tmax normals → departures
       │                     (never a forecast-window average)
       ├─> heatwave rules    IMD departure rule + 2-day persistence → episodes,
       │                     single-day candidates stay early "watch" signals
       └─> core/health_impact.py   parameterised indicator + model-status vocabulary
            └─> core/warnings.py   advance warning rows: lead times, alert levels,
                 │                 action matrix, provenance
                 ├─> core/notify.py    previews + dry-run dispatch (SMS/WhatsApp)
                 └─> core/demo.py      deterministic demo scenarios (fixed clock)
                      └─> app/main.py (FastAPI) → React dashboard · citizen phone
                           app · Heat Risk Demo (#/demo) → scripts/export_static.py
```

### Metric definitions and formulas

**Heat Index (HI).** NWS Rothfusz regression with the three standard NWS adjustments.
Documented valid range travels with every value in `HTSI_METADATA`: shade-assumed, light wind,
T ≥ 26.7 °C (80 °F), RH 20–100 %; below 20 °C it degenerates to air temperature. HI *understates*
stress in direct sun and for windy, wet conditions outside its fit range — the metadata says so.

**WBGT — estimated, never measured.** `0.7·Tw + 0.2·Tg + 0.1·Ta` outdoors (wet bulb via Stull,
globe temperature from a Ranz–Marshall convective + radiative energy balance), or the shade form
`0.7·Tw + 0.3·Ta` when radiation is missing. Every WBGT value carries a quality flag from one
fixed vocabulary:

| Flag | Meaning |
|---|---|
| `measured` | a physical instrument observed this — **never produced by this codebase** (reserved for ingested station data) |
| `estimated` | all required inputs present; computed with the documented formula |
| `partial-input` | a required input was missing and replaced by a **listed documented assumption** (no radiation → shade form, *understates* sun stress; no wind → 0.13 m/s free-convection floor, *overstates* globe in breezy shade) |
| `unavailable` | a mandatory input (temperature or humidity) is missing — **no value is produced rather than inventing one** |

**UTCI is deliberately not faked.** It is not implemented; nothing labelled UTCI appears in any
payload (a test enforces this).

**HTSI (Human Thermal Stress Index), 0–100:**

```
HTSI = 100 · clip((WBGT_est − 25) / (36 − 25), 0, 1)^1.4
       + min(8, 1.6 · max(0, Tmax − Tmax_normal(1991–2020)))
```

The anomaly term (capped at +8) encodes acclimatisation; it is only added when a **fixed
historical normal** exists. Bands: **Normal** < 30 ≤ **Watch** < 55 ≤ **Warning** < 75 ≤
**Severe**. Vulnerability and demographics are *never* HTSI inputs — enforced by tests.

**Health-impact indicator, 0–100** (`core/health_impact.py`):

```
impact = clip( 0.62·HTSI + 0.28·vulnerability
               + min(6, 1.6·max(0, departure_c − 2))
               + min(6, max(0, AQI − 200)/25), 0, 100 )
```

Bands: Low / Moderate / High / Very High. It is a **parameterised** combination of stated
assumptions — inspectable, not fitted — and it does **not** predict a number of deaths or
admissions. Any downstream count is illustrative arithmetic on stated assumptions.

### Mortality & hospitalisation risk — the validation boundary

Every health-impact payload carries one of three explicit model statuses:

| Status | When it may appear |
|---|---|
| `validated_observed_outcome_model` | **only** when (a) a committed evaluation report at `data/validation/health_outcome_model_evaluation.json` **names the observed dataset** (`observed_data_source`) and contains outcome-linked `metrics`, **and** (b) that dataset — ward/zone-level death or admission counts — loads cleanly against the strict schema below. |
| `parameterised_health_risk_indicator` | live routes without the above — the honest default. |
| `synthetic_demo` | every demo-scenario row, always. |

This repository ships **no** observed outcome data (only the labelled
`data/mortality_labels.SYNTHETIC.example.csv` example) and **no** evaluation report, so
`validated_observed_outcome_model` is **unreachable** — and `tests/test_health_impact.py` proves
no API payload can contain that label today. To actually validate: ingest real historical
mortality/hospitalisation records with `core.health_impact.load_health_outcomes()` — the strict
CSV schema requires `date` (ISO), `location_id`, `outcome_type` (`mortality` or
`hospitalisation`), non-negative `count`, a named `source`, and `data_quality` (`official`,
`provisional`, `estimated` or `incomplete`); malformed files are rejected wholesale — then
commit the evaluation report and the status resolver will pick it up. Until then:
**parameterised ≠ validated, and retrospective analysis ≠ operational forecast skill.** Where HeatShield does report forecast skill (heatwave
contingency), it reports **CSI and HSS with hits, misses, false alarms and correct negatives** —
never raw accuracy, which is meaningless for rare events.

### True 3–5 day early warnings

`GET /warnings/advance` (live) and `GET /demo/warnings?scenario=...` (demo) return one row per
zone per target date carrying: forecast **issuance time**, **target date/time** (peak 15:00
IST), **lead days and lead hours**, heatwave-candidate and **persistent-episode** status
(2-day IMD persistence; a single qualifying day is an early **watch**, never a declared
heatwave), thermal-stress level (HTSI band), vulnerability level, health-impact status,
recommended action level, and **data source + quality/confidence** provenance
(`live-forecast` / `synthetic-fallback` / `demo-synthetic`). Departures always compare against
the fixed **1991–2020** climatology — a forecast window's own mean is never substituted for a
normal. If Open-Meteo or CAMS is unreachable, the route answers 200 with labelled synthetic
fallback rows and a `fallback_reason`; it must never 500 (tested).

**Action matrix** (shipped in every payload, rendered on the Impact screen): routine →
monitoring; watch → cooling-centre readiness, staff briefs, ORS pre-positioning, utility
heads-up; warning → open cooling centres, shift outdoor work hours, hydration points,
health-worker checks on high-risk households; severe → emergency coordination, ambulance
surge readiness, power-demand operations, DM war-room. Resident advice accompanies each level.

### Heat Risk Demo mode

**Open it:** `http://localhost:5173/#/demo`, the amber **Heat Risk Demo** button on the landing
hero and dashboard header, or the **Heat Demo** nav tab. No sign-up, no keys, no network needed.

**How it stays offline:** the browser tries the relative live API (`./api/demo/*`) first and
falls back to the exported snapshots in `frontend/web/public/static-api/demo-*.json`; on GitHub
Pages (or any static host) it goes straight to the snapshots. Nothing in the demo path touches
Twilio, WhatsApp or any credential.

**Four deterministic scenarios** (fixed issuance **2026-05-18 06:00 IST** — the demo clock never
depends on today's date):

| Scenario | What it teaches | Levels you can see |
|---|---|---|
| **Dry extreme heatwave** | the classic Delhi May heatwave: Tmax to ~47 °C, declared multi-day episodes, Day +3/+4/+5 warnings | Watch → Warning → Severe |
| **Humid dangerous heat** | 35–38 °C at 68–76 % RH: est. WBGT ~36 °C and HTSI ~100 **without any IMD heatwave label** — humidity danger the temperature-only view misses | Warning → Severe |
| **Severe heat + high pollution** | compound exposure: heat *and* PM2.5-driven AQI in the 400s, with the capped heat–air load kept separate from raw AQI | Warning → Severe |
| **Monsoon break** | the honest quiet case: pre-monsoon showers, Normal band, **zero** planned notifications | Normal → Watch |

Each scenario covers **8 NCR zones × leads Day +0…+5** (48 warning rows) with different
vulnerability profiles, so the map shows genuinely different risk levels side by side.

**Screens:** *Now* (issue-day hourly thermal detail), *Outlook* (lead-time table + Day +3/+4/+5
cards), *Zones* (the accessible, map-independent table for any lead day), *Impact* (HTSI /
vulnerability / health-impact breakdown + actions), *Alerts* (notification preview cards),
*Method* (what is real, synthetic and assumed). The GIS panel offers alert-level, thermal-stress,
vulnerability and heatwave-outlook layers plus demo cooling centres — every colour is paired
with a text label in the legend, tooltip and tables (never red/green-only), and the Zones table
is a full keyboard-accessible alternative to the map.

**The disclaimer is not decorative.** The canonical string —
`Demo / synthetic scenario — not a live forecast or observation.` — is defined exactly once
(`core/warnings.py`), appears in every demo payload, every demo notification message, and every
server-rendered demo screen (all enforced by tests). Inside the demo, what is **real**: the
1991–2020 climatology normals, the formulas, thresholds, persistence rule and action matrix.
What is **synthetic**: the weather, the air quality, the zone vulnerability profiles, the
cooling centres and every derived number.

### Notifications — previews and dry-run safety

`GET /notifications/preview`, `GET /demo/notifications?scenario=...` and
`POST /notifications/dispatch` build messages from **real generated alert data**: zone,
severity, target date, lead time, reason, recommended action and data-quality state. Two
template families: the **3–5 day early warning** and the **same-day escalation**. Audiences:
municipal control room, disaster management, healthcare, residents; channels: SMS and WhatsApp
(SMS previews include character count and segment estimate).

Safety properties, all tested: `dry_run=true` is the default everywhere; live sending requires
**both** `HS_ALLOW_LIVE_SEND=1` **and** Twilio credentials; rows whose quality state is
`demo-synthetic` or `synthetic-fallback` are **refused for live dispatch even with both locks
open**; dry runs append to a gitignored CSV log; no credential ever appears in Git or chat.

### Static export & PWA

Every public route — including all six demo payload families for all four scenarios — is in the
`scripts/export_static.py` catalogue (31 exports, including the Kolkata brief `citizen-kolkata.json`),
checked against the live FastAPI route table:

```bash
HS_FORECAST_DAYS=5 .venv/bin/python -m scripts.export_static --check   # catalogue vs routes
HS_FORECAST_DAYS=5 .venv/bin/python -m scripts.export_static           # write public/static-api/
cd frontend/web && npm run build                                       # Vite build (relative base)
cd frontend/web && npm run budget                                      # phone cold-open gate
```

The service worker caches the snapshots with the rest of the app, so after one visit the demo
also survives going fully offline. All paths stay project-relative (`./`), preserving GitHub
Pages deployment under `https://<owner>.github.io/Heatshield/`.

### Running the tests

```bash
HS_FORECAST_DAYS=5 .venv/bin/python -m pytest -q     # 172 passed
```

The demo-relevant suites: `tests/test_demo_scenarios.py` (determinism, fixed clock, band/level
coverage, disclaimer), `tests/test_htsi.py` (HI range, WBGT quality flags, missing inputs,
vulnerability-not-in-HTSI, UTCI-not-faked), `tests/test_health_impact.py` (status vocabulary and
the unreachable-validated boundary), `tests/test_advance_warnings.py` (lead-time fields,
persistence, normals, outage fallback), `tests/test_notifications.py` (previews, templates,
dry-run locks, demo-row refusal), and `tests/test_demo_app.py` — which **server-renders every
demo screen through `react-dom/server` against the real exported payloads** for all four
scenarios plus the empty state, rejecting `NaN`/`undefined`/`Invalid Date`, today's date, a
missing disclaimer, colour-only legends and non-composite motion.

---

## Map keys, installability & notification automation

### Maps are keyless — no "API key required", ever

Every map (operations dashboard, Heat Risk Demo, Delhi NCR ops) renders out of the box with
keyless CARTO/Esri/OpenTopoMap tiles. The former *optional* commercial-key upgrade was
**removed from the shipped code entirely**: a misconfigured, expired or placeholder key could
paint the map with the provider's *"API key required"* error tiles, and a prototype must never
depend on a key nobody has. There is now no tile-key slot anywhere — `frontend/web/src/basemaps.js`
contains only keyless providers plus `OSM_FALLBACK` (automatic OpenStreetMap tiles on a
different CDN when one is blocked, with an honest on-map notice; a test enforces that no keyed
provider can creep back in).

If you genuinely want commercial tiles **for your own deployment**, add an entry to the
registry in `basemaps.js` yourself — a plain `{ id, label, hint, url, attribution, … }` object
consumed by `<TileLayer/>` — and keep the `tileerror` fallback behaviour in
`RiskMap.jsx`/`DemoMap.jsx` intact so a bad key can never blank the map again.

### Using Google tiles (and why there is no Google key field)

There is deliberately **no `VITE_GOOGLE_*` key slot**: the only licensed way to render Google
basemaps in a web app is the **Google Maps Tile API**, which requires a GCP project with
**billing enabled** and a session-token handshake per tile session — not a static key in a URL.
Scraping `mt{n}.google.com/vt` violates Google's Terms of Service and stays excluded (see the
comment at the top of `basemaps.js`). If you hold a billing-enabled key, the supported paths are:

1. Keep the keyless CARTO/ESRI basemaps (visually very close, zero cost), or
2. Take the MapTiler upgrade above (free tier), or
3. Add a `google` entry to the registry in `basemaps.js` using the official Map Tiles API
   with its session flow — a self-contained change to that one file.

**For *location* ("find me on the map") no Google key is needed at all:** the citizen tab's 📍
button uses the browser's built-in **Geolocation API** and matches your GPS fix to the nearest
Delhi-NCR zone with the payload's own coordinates (same 8-zone registry as the demo map —
verified identical lat/lon). Nothing leaves the device; no account, no key, no geocoding bill.

### Install on Android (PWA one-tap, or a real APK)

The citizen tab is an installable PWA (`manifest.webmanifest`: standalone display, 192/512 +
maskable icons; service worker caches everything for offline use).

- **One tap:** open the Citizen tab in Chrome/Edge on Android → the header shows an
  **Install** button (it appears whenever the browser offers the install prompt) → HeatShield
  lands on the home screen, runs full-screen and works offline.
- **iPhone/iPad:** Safari → Share → **Add to Home Screen** (Apple does not expose the install
  prompt to web apps).
- **A real, store-style APK/AAB:** package the deployed PWA with **PWABuilder** —
  1. Deploy the site (GitHub Pages works: `scripts/export_static` + `npm run build`, relative
     paths already configured).
  2. Go to <https://www.pwabuilder.com>, enter your deployed URL (e.g.
     `https://<owner>.github.io/Heatshield/#/phone`).
  3. *Package For Stores → Android → Generate* → download the **signed APK** (or the AAB for
     Play Store submission). The output is a Trusted Web Activity wrapping this exact PWA —
     it installs, launches full-screen and works offline.

  This keeps the repository's hard constraint (**AGENTS.md rule 2: PWA only — no Capacitor, no
  Gradle, no Android Studio**): the APK is generated *outside* the repo from the deployed site,
  so a clone still needs nothing but Python + Node.

### Personal heat-risk notifications (per user, on their own device)

The citizen tab's 🔔 button opts the device into **individual thermal-risk notifications**:

- Built from the payload the app already loaded — the resident's selected locality, its
  combined heat+air load index and band, temperature, and **one clear protective action**
  (band-specific advice mirrors the Safety screen).
- **Danger states** fire a protective-action alert: combined load band **Poor / Very Poor /
  Severe** or ≥ **40 °C** in Delhi NCR; a heatwave watch or **Extreme/Critical** WBGT stress
  band in Kolkata. **Non-danger states send a calm informational update instead of silence** —
  temperature, humidity and wind speed (plus estimated WBGT in Kolkata). Only a payload with
  nothing honest to say sends nothing.
- **Honesty preserved:** when the payload is a synthetic outage fallback or a static snapshot
  exercise, the notification body starts with *"Practice data … not a live forecast"* — a
  rehearsal can never masquerade as a live warning (enforced by the render-harness test).
- One notification per zone × timestamp × band × data-quality state (de-duplicated in
  `localStorage`), permission is opt-in and revocable, and nothing is transmitted anywhere —
  these are local browser notifications, no account and no key.
- Limitation, stated plainly: browser notifications need the app open (tab or installed PWA).
  For alerts that reach a **closed** app / basic phone, use the WhatsApp–SMS channel below.

### Automating warnings on WhatsApp (Twilio) — opt-in, dry-run by default

The pipeline already composes real alert messages; sending them is a deliberate, double-locked
act.

1. **Get credentials (free to start):** Twilio Console → Messaging → **WhatsApp Sandbox** —
   join the sandbox by sending its join code from your WhatsApp, then copy:
   ```ini
   # .env  (repo root — gitignored; never commit, never paste into chat)
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxx
   TWILIO_FROM_NUMBER=whatsapp:+14155238886
   ALERT_TO_NUMBERS=whatsapp:+91xxxxxxxxxx,+91xxxxxxxxxx
   HS_ALLOW_LIVE_SEND=1        # second lock — without it, live sending is refused
   ```
   (A production WhatsApp sender needs Meta template approval via Twilio; the sandbox is for
   testing with joined numbers only. Plain SMS works with the same variables minus the
   `whatsapp:` prefixes.)
2. **Rehearse (default — sends nothing, logs everything):**
   ```bash
   python -m scripts.dispatch_notifications                       # whole plan
   python -m scripts.dispatch_notifications --audience residents --channel whatsapp
   ```
3. **Go live** (both locks open, and the current payload is genuinely live — demo and
   synthetic-fallback rows are refused *even with both locks open*):
   ```bash
   python -m scripts.dispatch_notifications --live
   ```
   Or via the API: `curl -X POST localhost:8000/notifications/dispatch -H 'content-type:
   application/json' -d '{"dry_run": false}'`.
4. **Automate on a schedule** (cron; the dry-run form is always safe, the `--live` form only
   sends when a real alert exists and the data is live):
   ```cron
   # every day at 07:00 IST — rehearse the queue and append to the log
   0 7 * * *  cd /path/to/Heatshield && .venv/bin/python -m scripts.dispatch_notifications >> logs/notify.log 2>&1
   ```
   Every dispatch — dry or live — appends to `data/processed/notification_dry_run_log.csv`
   (gitignored, path overridable with `HS_DRY_RUN_LOG`) for audit.
