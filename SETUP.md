# HeatShield — Local Setup Guide

Everything you need to install, in order, with the exact commands.
**Estimated time: 10 minutes for the backend, +25 minutes if you also want the Android toolchain.**

---

## ⚡ TL;DR — if you just want it running

```bash
cd heatshield
./setup.sh                 # Windows: setup.bat
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open **http://localhost:8000/docs**. That's it — the script checks prerequisites, creates a
virtualenv, installs dependencies, and runs the smoke tests.

If something fails, jump to [Troubleshooting](#troubleshooting).

---

## 1. Prerequisites

| Tool | Version | Why | Windows | macOS | Linux (Ubuntu/Debian) |
|---|---|---|---|---|---|
| **Python** | 3.10–3.13 (3.11 recommended) | Backend + ML | [python.org](https://www.python.org/downloads/) — **tick "Add python.exe to PATH"** | `brew install python@3.11` | `sudo apt install python3.11 python3.11-venv python3-pip` |
| **pip** | latest | Packages | bundled | bundled | bundled |
| **Git** | any | Clone/version control | [git-scm.com](https://git-scm.com) | `brew install git` | `sudo apt install git` |
| **Node.js** | 18+ (LTS) | Web UI + PWA | [nodejs.org](https://nodejs.org) LTS installer | `brew install node` | `sudo apt install nodejs npm` |
| *(not needed)* JDK / Android Studio | — | skipped — mobile ships as a PWA | — | — | — |

> **Install Python before anything else.** If you're on Windows and skipped "Add to PATH"
> during install, re-run the installer → Modify → tick it.

Verify:
```bash
python3 --version     # 3.10+   (Windows: python --version)
node --version        # v18+
```

---

## 2. Backend setup

### Option A — automatic (recommended)

```bash
cd heatshield

# macOS / Linux / WSL
chmod +x setup.sh
./setup.sh

# Windows (double-click works too)
setup.bat
```

The script: checks Python → creates `.venv` → upgrades pip → installs dependencies →
creates `.env` from the template → builds `data/` folders → runs both smoke tests.

### Option B — manual

```bash
cd heatshield

# create + activate a virtual environment (never install into system Python)
python3 -m venv .venv                     # Windows: python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate

# you should now see (.venv) in your prompt
pip install --upgrade pip
pip install -r requirements.txt
```

**Exact-version install (use this if the above breaks):** we ship a lockfile pinned to the
combination verified working — pandas 3.0.5, numpy 2.5.2, scikit-learn 1.9.0, fastapi 0.141.1.

```bash
./setup.sh --locked          # Windows: setup.bat --locked
# or manually:
pip install -r requirements.lock.txt
```

### What gets installed

| Package | Used by |
|---|---|
| `fastapi`, `uvicorn` | REST API (all phases) |
| `requests`, `pandas`, `numpy` | Phase 1 data pipeline |
| `scikit-learn`, `joblib` | Phase 3 risk model |
| `streamlit`, `folium`, `plotly` | Legacy/alternative dashboard (kept for fallback) |
| `twilio`, `python-dotenv` | Phase 5 SMS/WhatsApp alerts |

> The animated web UI and Android app use npm, not pip — see Phase 4/6 below.

---

## 3. Run the backend

```bash
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **API docs (Swagger):** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health

`--host 0.0.0.0` matters: it exposes the server on your LAN so the **Android app can reach it**
(see Phase 6). `--reload` restarts on file changes.

### Verify each phase

```bash
python -m core.weather                     # Phase 1: fetch live forecast
python -m core.thermal                     # Phase 2: WBGT/HI + validation tables
pytest tests -q                            # 26 tests: 11 physics + 15 alert/threshold regressions
```

### Endpoints

```
GET /health                    service status
GET /zones                     141 wards + demographics
GET /forecast?hours=24         hourly weather
GET /forecast/daily            daily Tmax/Tmin/RH per ward
GET /thermal?hours=24          hourly WBGT + Heat Index + band
GET /thermal/daily             daily peaks + IMD heatwave flags
GET /thermal/ward/14           ward summary, band, guidance, work/rest rule
```

---

## 4. Configuration

```bash
cp .env.example .env      # setup.sh does this for you
```

| Variable | Default | Purpose |
|---|---|---|
| `HS_TIMEZONE` | `Asia/Kolkata` | Forecast timezone |
| `HS_FORECAST_DAYS` | `5` | Forecast window (3–16) |
| `HS_PAST_DAYS` | `1` | Days of history to include |
| `HS_CACHE_TTL_MIN` | `30` | Cache lifetime — protects the free API tier |
| `HS_ADMIN_TOKEN` | *(empty)* | Bearer token for the administrative routes (subscriber registry, dispatch). **Unset ⇒ those routes are disabled (503).** Setting it also turns the API docs off. |
| `HS_ALLOWED_ORIGINS` | *(empty)* | Extra browser origins allowed to call the API. Blank is correct for the shipped app (same-origin) |
| `HS_RATE_LIMIT_PER_MIN` | `120` | Requests per client per minute (`0` disables). In-process limiter |
| `HS_MAX_BODY_BYTES` | `262144` | Largest accepted request body |
| `HS_TRUST_PROXY` | *(empty)* | `1` when behind a proxy you control, so `X-Forwarded-For` may be believed for rate limiting |
| `TWILIO_*`, `ALERT_TO_NUMBERS` | — | Phase 5 only; safe to leave blank |

**No API key is needed for weather data** — Open-Meteo's free tier is keyless for
non-commercial use.

---

## 5. Web UI (Phase 4 — built)

```bash
cd frontend/web
npm install                # ~15 s
npm run dev                # http://localhost:5173
```

Requires the API running on :8000 — Vite proxies `/api/*` → `http://127.0.0.1:8000`, so the
browser never calls localhost directly.

Three routes: **Overview** (landing) · **Operations** (ward risk map, gauge, hourly curve) ·
**Citizen** (mobile view). The **scenario switcher** (+0/+2/+4/+6/+8 °C) re-scores all 141 wards
live — the fastest way to demo the model under a real heatwave.

```bash
npm run build              # -> frontend/web/dist  (107 KB gzipped)
npm run preview
```

Stack: Vite + React 18 + Framer Motion + Tailwind. Fonts load from Google Fonts
(Instrument Serif / Inter / JetBrains Mono) with complete local fallback stacks.

### Install it as a phone app (PWA)

Already wired: `public/manifest.webmanifest` + `public/sw.js` (offline-first, push-ready).

- **Android:** open the LAN URL in Chrome → ⋮ → *Install app*
- **iOS:** Safari → Share → *Add to Home Screen*
- **LAN URL:** `npm run dev -- --host 0.0.0.0`, then `http://<your-LAN-IP>:5173`
  (`localhost` does not work from a phone)

Push notifications require HTTPS — deploy to Render/Netlify for that. See `frontend/MOBILE.md`.

---

## 6. Mobile (Phase 6) — PWA, no native toolchain

Decision: **PWA, not an APK.** No JDK, no Android Studio, no 3 GB download, and it works on iOS.
The manifest and service worker are already in `frontend/web/public/`.

Full guide: **`frontend/MOBILE.md`** — install steps, offline behaviour, push notifications,
testing on a real phone, and the honest limitations.

If you later want a real APK, the Capacitor path takes ~20 minutes on top of the existing build.

---

## Troubleshooting

**`python3: command not found` (Windows)**
Use `python` instead of `python3`. Or re-run the installer and tick "Add python.exe to PATH".

**`python -m venv` fails / "ensurepip is not available"**
Ubuntu/Debian: `sudo apt install python3.11-venv`. Windows: reinstall Python with pip + venv ticked.

**"Microsoft Visual C++ 14.0 is required" (Windows)**
Install [VS Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) →
"Desktop development with C++". Or avoid compiled wheels entirely: `./setup.bat --locked`.

**`SSL: CERTIFICATE_VERIFY_FAILED` on pip install**
```bash
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

**`ModuleNotFoundError: No module named 'core'`**
Run from the project root, and set the path when running tests:
`PYTHONPATH=. python tests/test_thermal.py`

**`Address already in use` on port 8000**
```bash
lsof -ti:8000 | xargs kill -9          # macOS/Linux
netstat -ano | findstr :8000           # Windows, then: taskkill /PID <pid> /F
```
Or use another port: `uvicorn app.main:app --port 8010`

**Open-Meteo returns 429 / empty data**
Rate-limited. Wait a minute — the 30-minute disk cache in `data/cache/` usually prevents this.
Force a refetch: `rm -rf data/cache/*`

**Wards all show identical weather**
Expected, not a bug. Open-Meteo's grid is ~11 km; central Kolkata shares one cell. Ward
differentiation comes from the vulnerability + urban-heat-island layer in Phase 3.

**Phone can't reach the app** — the classic one
- `localhost` on the laptop is not the phone. Use your LAN IP: `ipconfig` / `ip addr | grep inet`
- Run both servers bound to `0.0.0.0`: `npm run dev` and `uvicorn --host 0.0.0.0`
- Phone and laptop must be on the same Wi-Fi

---

## What's in the folder

```
heatshield/
├── setup.sh, setup.bat        one-command installers
├── SETUP.md                   this file
├── README.md                  project overview + phase status
├── requirements.txt           dependency list
├── requirements.lock.txt      pinned versions (verified combination)
├── .env.example               config template
├── core/
│   ├── config.py              settings, risk bands
│   ├── weather.py             PHASE 1: Open-Meteo pipeline
│   └── thermal.py             PHASE 2: WBGT / Heat Index engine
├── app/main.py                FastAPI service
├── data/
│   ├── wards.csv              141 real KMC wards + Census 2011 demographics
│   └── processed/             sample pipeline output
├── tests/test_thermal.py      11 physics tests
├── tests/test_alerts.py       alert engine + threshold regression tests
├── frontend/
│   ├── web/                   Vite + React + Framer Motion app  (npm install && npm run dev)
│   │   └── public/            manifest.webmanifest + sw.js (PWA)
│   ├── UI_SPEC.md             locked web stack + animation inventory
│   ├── MOBILE.md              PWA install / offline / push guide
│   └── prototype.html         animated UI concept (open in any browser, no build)
└── scripts/package.py         regenerates the downloadable zip
```

Refresh the downloadable bundle after any change:
```bash
python scripts/package.py --label phases-1-2
```
