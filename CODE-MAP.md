# CODE-MAP — a newcomer's map of HeatShield

Read this first if you have just cloned the repository. It is not a tutorial and
it does not repeat the README: the README says *what the platform is and how to
run it*, this file says *where everything lives and which rules will bite you*.

Every claim here was checked against the code on 2026-09-18. The numbers that
matter are asserted by tests, so if one of them is wrong, a gate is red:

| Fact | Number | Enforced by |
|---|---|---|
| API routes | **42** | `tests/test_route_smoke.py` (walks the table), `tests/test_live_layers.py` (the three `/live/*`) |
| Frontend checks | 43 passing | `npm test` |
| Python tests | 302 passing | `pytest -q` |
| Citizen phone cold-open | 112,983 gzip bytes of 122,880 | `npm run budget` |

---

## 1. The shape of it: two processes

```
browser ──► Vite dev server :5173 ──proxy /api/*──► FastAPI :8000 ──► Open-Meteo
   │                                                    │
   │                                                    └──► adsb.lol / USGS / CelesTrak
   │                                                         (the globe's optional layers)
   └──► built static site (GitHub Pages) ──► public/static-api/*.json snapshots
```

- **`frontend/web`** — Vite + React. Everything the browser loads. It never
  names a remote API host: calls go to `./api/...`, which Vite proxies to
  FastAPI in dev (`vite.config.js`). On a static host there is no API at all,
  and the app falls back to the exported snapshots in `public/static-api/`.
- **FastAPI (`app/main.py` + `core/`)** — the only process that touches
  upstream providers. It is optional in the sense that the *site* works without
  it, but every number on the dashboard comes from here.
- **GitHub Pages** — files only. The Deploy workflow builds the frontend and
  publishes `frontend/web/dist`; the API is not part of it, which is why the
  operations maps say "snapshot" there.

The one rule that explains most of the code: **the browser shows real data or it
says so.** There is no mock mode, no sample ward, no "last known" number dressed
up as current. `frontend/web/src/api.js` throws on failure and the UI renders an
honest state; `core/live.py` answers `available: false` with a reason rather
than inventing a row.

---

## 2. Repository layout

```
app/main.py                 FastAPI app: middleware, 42 routes, cache rules
core/
  config.py                 every tunable, read from the environment once
  weather.py                Open-Meteo fetch → tidy DataFrame → disk cache
  thermal.py, risk.py       WBGT/heat index → ward risk scores (Phases 2–3)
  htsi.py, coupled.py,      heat-health index, coupled heat+AQI, advance warnings
  warnings.py, alerts.py
  health_impact.py          mortality/hospitalisation estimates (labelled synthetic)
  notify.py, subscribers.py notifications and the opt-in registry (phones redacted)
  demo.py                   the Heat Risk Demo's four synthetic scenarios
  response_cache.py         per-process cache for the public reads
  security.py               rate limiter, admin gate, phone redaction
  live.py                   the globe's three live layers (aircraft/quakes/satellites)
frontend/web/
  index.html, vite.config.js
  plugins/                  Vite plugins: siteMeta.js, satelliteWasmStub.js
  public/                   sw.js, manifest, icons, offline.html, static-api/ snapshots
  src/                      App.jsx (router), api.js, live.js, staticApi.js, routes.js
    components/             Dashboard, DelhiOps, RiskMap, Landing, Sources, …
    mobile/                 the citizen phone app (2D only, budget-gated)
    demo/                   the Heat Risk Demo
    globe/                  lazy CesiumJS globe + the live layers
  scripts/                  build helpers + the `npm test` suites
scripts/                    backend scripts: refresh, export_static, backup, …
tests/                      pytest suite (302 tests)
data/                       wards, census, climatology, processed runs, snapshots
.github/workflows/          CI, Deploy to GitHub Pages, Uptime, two data validations
```

---

## 3. The API: 42 routes

`app/main.py` is the whole surface. Routes are grouped below in the order they
appear in the file; `{ward_id}` is 1–141 (KMC wards).

### Service
| Route | What it answers |
|---|---|
| `GET /` | service banner + the endpoint inventory |
| `GET /health` | status, version, server time, timezone |

### Weather and the ward grid
| Route | What it answers |
|---|---|
| `GET /zones` | 141 ward centroids + Census 2011 demographics |
| `GET /forecast` | hourly raw weather (Open-Meteo), `?hours` `?ward_id` |
| `GET /forecast/daily` | daily Tmax/Tmin/RH per ward |

### Thermal stress and risk (Phases 2–3)
| Route | What it answers |
|---|---|
| `GET /thermal` | hourly WBGT / heat index per ward |
| `GET /thermal/daily` | daily peaks |
| `GET /thermal/ward/{ward_id}` | one ward's thermal series |
| `GET /risk` | the UHI-adjusted risk series |
| `GET /risk/daily` | daily risk per ward |
| `GET /risk/ranking` | the ward league table the dashboard and globe colour |
| `GET /risk/ward/{ward_id}` | drivers + impact for one ward |

### Alerts and notifications
| Route | What it answers |
|---|---|
| `GET /alerts/plan` | who would be warned, with how many days of lead |
| `POST /alerts/dispatch` | **admin** — actually sends |
| `GET /notifications/preview` | dry-run message previews |
| `POST /notifications/dispatch` | **admin** — sends them |

### Delhi NCR (coupled heat + AQI, advance warnings)
| Route | What it answers |
|---|---|
| `GET /ncr/zones`, `/ncr/forecast`, `/ncr/daily`, `/ncr/summary` | the 8 zones and their runs |
| `GET /ncr/air-quality`, `/ncr/heat-aqi` | PM2.5 and the coupled index |
| `GET /ncr/metadata`, `/ncr/validation` | provenance and measured skill |
| `GET /ncr/alerts` | NCR alert levels |
| `GET /heatwave/advance`, `/warnings/advance` | true 3–5 day warnings |
| `GET /citizen/kolkata` | one JSON brief for the whole city (the phone's payload) |

### Heat Risk Demo (labelled synthetic, always)
| Route | What it answers |
|---|---|
| `GET /demo/scenarios`, `/demo/zones`, `/demo/forecast`, `/demo/thermal`, `/demo/warnings`, `/demo/notifications` | the four practice scenarios. Never dispatched live, never shown as real |

### Subscriber registry (personal data — the guarded part)
| Route | What it answers |
|---|---|
| `GET /subscribers`, `POST /subscribers`, `POST /subscribers/stop`, `GET /subscribers/for-ward/{ward_id}` | **admin** — phones are redacted (`+91••••••3210`) even here |
| `GET /subscribers/stats` | aggregate counts only, therefore public |

### Live tracking layers (the globe's optional overlays)
| Route | What it answers |
|---|---|
| `GET /live/aircraft` | ADS-B traffic within `radius_nm` of `lat`/`lon` (adsb.lol) |
| `GET /live/earthquakes` | USGS events for `window=hour\|day\|week` at or above `min_mag` |
| `GET /live/satellites` | CelesTrak GP element sets for one whitelisted `group` |

Three things about these three routes, because they look like the rest and are
not quite:

1. **They proxy.** The browser calls `./api/live/*`; this process calls the
   provider. No tracking host is ever reached from a browser.
2. **Failure is data, not a 503.** `/forecast` answers 503 when Open-Meteo is
   down because the forecast *is* the product. These layers are additive, so
   they answer `200` with `available: false`, a `notice` naming the upstream
   and an empty `data` list.
3. **They are never cached by the shared response cache** (it cannot tell a
   success from a degraded payload). Successful payloads are held briefly
   inside `core/live.py` instead; failures are never held.

### How a request is handled

`app/main.py` installs one HTTP middleware (`guard`) which, in order: refuses
`/docs` when documentation is off → refuses oversized bodies → rate limits →
answers from the response cache (or coalesces onto a request already in flight)
→ runs the route → stores a 200 → adds the security headers. Cheap rejections
happen before pandas; a cache hit happens before anything runs at all.

Two details worth knowing before you add a route:

- **Cacheability is a list, not a decoration.** `_CACHEABLE_READS` maps path
  prefixes to seconds. Anything containing personal data (`/subscribers*`) and
  anything that mutates stays `no-store`. If you add a public read, decide
  deliberately whether it belongs in that list.
- **`tests/test_route_smoke.py` walks every route** with hostile path and query
  values and fails on any 5xx. Bound your parameters (`Query(ge=…, le=…)`,
  `Literal[...]`) or it will find you.

---

## 4. The frontend

### Routing
`src/routes.js` is a pure function (`resolveRoute(hash)`) — the router is
tested without a browser. `src/App.jsx` renders one of: landing, dashboard,
delhi, phone, demo, and the static pages (privacy, terms, …). Unknown
hashes are a 404, never a silent landing page.

`useRoute` has one definition of "go to this hash", shared by the hash listener
and `go()` — so a press applies its own route immediately instead of waiting
for `hashchange` to come back. That was a real bug (the Citizen tab needed a
reload); `scripts/test-app-sweep.mjs` mounts the app with `hashchange`
deliberately undeliverable and asserts the phone page still opens.

### Lazy chunks, and why
CesiumJS (~1.1 MB gzip) is reachable only through
`lazy(() => import('../globe/HeatGlobe'))`. `scripts/check_phone_budget.mjs`
fails the build if `cesium`, `nosleep`, `protobuf` or `globe` ever enter the
citizen phone's cold-open set, and `vite.config.js` gives Vite's own runtime
helpers their own chunk so they cannot drag the globe in with them.

### Data layer
- `src/staticApi.js` — `isStaticHost()`, deadlines (`withTimeout`), `readJSON`.
  **Every** browser fetch has a 15-second deadline; a server that sends headers
  and then stalls must surface as a failure, not an eternal skeleton.
- `src/api.js` — the `/api/*` calls, live-first with the exported snapshot as
  the documented fallback.
- `src/live.js` — `useLive`: keeps the last good payload, always exposes the
  error, and never polls on its own (refresh is a button or the `R` key).

### The globe (`src/globe/`)
`HeatGlobe.jsx` is the React component; the vendored gods-eye-view plumbing
(controller, sources, imagery, terrain, registry, credits) sits beside it;
`heatLayers.js` turns HeatShield payloads into Cesium entities. The three live
layers are `liveData.js` (fetching + orbit maths) and `live.js` (the
`useLiveLayer` hook). They are **off by default**, fetched only while on, and
never fetched at all on a static host.

### The service worker (`public/sw.js`)
Navigations are **network-first** (a cache-first `index.html` keeps asking for
chunk names the last deploy deleted — that was the Citizen-tab bug); hashed
assets, the ward GeoJSON, `/api` responses and tiles are cache-first.
**Every release that changes shipped frontend code bumps `VERSION`**
(`heatshield-phone-v7` today), and the worker's tile-host list must match the
two basemap registries — `tests/test_frontend_shell.py` fails on drift.

---

## 5. Data and provenance

- `data/wards.csv` — 141 real KMC wards with real Census 2011 demographics.
- `data/processed/` — the last computed run (forecast, thermal, risk, alerts).
  "Offline" means "serving this, clearly timestamped".
- `data/cache/` — the forecast cache (parquet if pyarrow is installed, else
  pickle). `data/cache/forecast_5d.parquet` is committed so a cold clone can
  render without hitting Open-Meteo.
- `DATA.md` — where every dataset came from and what is deliberately absent.
- `THIRD-PARTY.md` — vendored code, runtime services, licences, and the
  carve-outs (notably: nothing NonCommercial from gods-eye-view was taken).

`scripts/export_static.py` writes the `public/static-api/*.json` snapshots the
static site uses; `--check` verifies them in CI.

---

## 6. The gates (run all of these before you open a PR)

```bash
# frontend
cd frontend/web && npm ci
npm test            # 43 checks: routing, page metadata, console hygiene, the
                    # app sweep (jsdom), and the live layers
npm run build       # must succeed: the Python suite measures this output
npm run budget      # phone cold-open ≤ 122,880 gzip bytes
npm run a11y        # contrast, labels, alt text — a static scan of src/

# backend (from the repository root)
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
HS_FORECAST_DAYS=5 .venv/bin/python -m pytest -q      # 302 tests
```

`tests/conftest.py` builds the frontend once per session (or reuses `dist/` when
`HS_TEST_SKIP_BUILD=1`, as CI does) because several tests measure real build
output. **No test in this repository needs the network**: upstreams are faked,
and `HS_LIVE_LAYERS=0` is set for the whole suite so the live routes answer
"off" instantly.

Five workflows run on GitHub: **CI** (backend + frontend), **Deploy to GitHub
Pages** (on `main`), **Uptime** (every six hours), and two data validations
(NCR climatology, observed PM2.5).

---

## 7. The invariants — read this before your first change

1. **Keyless, everywhere.** No API key exists in this project: not for maps,
   not for weather, not for the live layers. There is no key slot to
   misconfigure, and `tests/test_demo_app.py` fails on `key=`, `apikey`,
   `cartocdn`, `maptiler` or `thunderforest` in the map registries.
2. **No invented data.** A missing upstream, a missing field and a stale fix
   are all *reported*, never filled in. Demo data is synthetic and labelled
   synthetic wherever it appears.
3. **Colour is never the only channel.** Every band carries a word; every
   marker on the globe carries a text label.
4. **Paths are relative.** The app is served from `/Heatshield/` on GitHub
   Pages, so `./api/…` and `publicURL()`, never `/api/…`.
5. **Cache-bump discipline.** New shipped frontend code ⇒ new `VERSION` in
   `public/sw.js`.
6. **Attribution follows the source.** If tiles degrade to OSM, the credit says
   OSM. Add a runtime service, add a row to `THIRD-PARTY.md` and to
   `src/components/Sources.jsx`.
7. **Never weaken a gate to make it pass.** Fix the cause. The gates are the
   only reason the launch claims in the README are worth anything.

---

## 8. Where to make a common change

| You want to… | Start here |
|---|---|
| add an API route | `app/main.py` (route + `_CACHEABLE_READS` decision + the `/` inventory), then `tests/test_route_smoke.py` picks it up automatically |
| change how risk is computed | `core/risk.py` → `core/thermal.py` (WBGT) → `core/weather.py` (inputs) |
| add a dashboard panel | `frontend/web/src/components/Dashboard.jsx` + `src/api.js` |
| touch the phone app | `src/mobile/` — then run `npm run budget`; the phone must stay 2D and under budget |
| touch the globe | `src/globe/` — then run `npm run build` and `npm run budget`; Cesium must stay lazy |
| change the map providers | `src/basemaps.js` (2D) and `src/globe/imagery.js` (3D) — then update `public/sw.js` `TILE_HOSTS`, or the drift test fails |
| change what crawlers see | `plugins/siteMeta.js` + `scripts/gen-site-meta.mjs` |
| add an upstream data source | `core/` (new module) + `core/config.py` + a faked-upstream test; never fetch it from the browser |
