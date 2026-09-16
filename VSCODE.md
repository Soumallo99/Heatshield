> **Using Google Antigravity instead of VS Code?** Read [`ANTIGRAVITY.md`](ANTIGRAVITY.md) —
> it has the same steps plus the three Antigravity-specific differences (Open VSX marketplace,
> no Pylance, Windows venv path). The project code is identical in both editors.

# HeatShield in Visual Studio Code

Run the exact same prototype locally — same data, same model, same UI. It works
**immediately on first run without any network**, because the last computed
forecast ships in `data/processed/`. With a network connection it pulls a live
forecast from Open-Meteo (keyless, no signup).

---

## 1. Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | **3.10+** (3.11 recommended) | `python3 --version` |
| Node.js | **18+** | `node --version` |
| VS Code | any recent | `code --version` |

Nothing else. No Docker, no database, no API keys.

---

## 2. Open it

```bash
unzip heatshield.zip
cd heatshield
code .
```

VS Code will prompt **"This workspace has extension recommendations"** → click
**Install All**. They're optional but give you IntelliSense, formatting and
Tailwind class completion.

---

## 3. Install dependencies

Open the VS Code terminal (`` Ctrl+` `` / `` Cmd+` ``).

**macOS / Linux / WSL:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend/web && npm install && cd ../..
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend\web; npm install; cd ..\..
```

> If PowerShell blocks the activate script, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

---

## 4. Run it

Pick whichever you prefer.

### Option A — one command (easiest)

```bash
./start.sh            # macOS / Linux / WSL
start.bat             # Windows
./start.sh --pwa      # also builds + serves the offline PWA on :4173
./stop.sh             # stop everything
```

### Option B — VS Code Run and Debug (`F5`)

Press **F5** and pick a configuration:

| Config | What it does |
|---|---|
| **HeatShield: Full stack (API + Web)** | Starts both. **Use this one.** |
| HeatShield: API (FastAPI) | Backend only, with reload + breakpoints |
| HeatShield: Web (Vite) | Frontend only |
| Refresh forecast data | Re-pulls the live forecast and re-scores |
| Run scheduler (one cycle) | One full unattended cycle |
| Hindcast (30 days) | Replays the model on observed weather |
| Pytest: all tests | Runs the 52-test suite |

### Option C — VS Code Tasks (`Ctrl+Shift+B` / `Cmd+Shift+B`)

`Start everything` · `Refresh forecast data` · `Run tests` · `Build frontend` ·
`Seed demo subscribers` · `Hindcast (30 days)`.

---

## 5. Open the app

| URL | What |
|---|---|
| **http://localhost:5173** | **The dashboard** |
| http://localhost:8000/docs | Interactive API docs (Swagger) |
| http://localhost:8000/health | Service status |
| http://localhost:4173 | Production PWA build (only with `--pwa`) |

Switch views with the pill at the bottom: **Overview · Operations · Citizen**.

---

## 6. Confirm it's really computing

Not rendering fixtures — actually running the model:

1. **Sort the ranked table by `Vuln`** → Ward 39/49 rise to the top despite not
   being the highest risk. Same score, different cause.
2. **Click any row** → map, gauge and hourly curve all follow.
3. **Scenario switcher (+2/+4/+6/+8 °C)** → re-scores all 141 wards live; the
   alert queue grows.
4. In a terminal: `python -m scripts.schedule --once` → full cycle, prints
   ward-hours scored and events found.

---

## 7. Debugging

Set a breakpoint anywhere — for example in `core/risk.py` inside
`vulnerability_index()` — then run **HeatShield: API (FastAPI)** with `F5` and
hit `http://localhost:8000/risk/ranking`. Execution stops in your file with full
variable inspection.

Useful entry points:

| File | What to inspect |
|---|---|
| `core/risk.py` | Vulnerability weights, hazard curve, risk formula |
| `core/alerts.py` | Threshold, lead-time rule, dispatch gating |
| `core/thermal.py` | WBGT / heat index physics |
| `core/weather.py` | Open-Meteo batching and caching |
| `core/subscribers.py` | Ward-level recipient resolution |

---

## 8. Troubleshooting

**"Stale / wrong dates in the UI"**
The cached forecast can look fresh after a file copy. Force a live pull:
`python -m scripts.refresh`

**Port already in use**
```bash
./stop.sh
# or
lsof -ti :8000 | xargs kill -9     # macOS/Linux
netstat -ano | findstr :8000       # Windows, then taskkill /PID <pid> /F
```

**`ModuleNotFoundError: No module named 'core'`**
Run scripts as modules from the project root: `python -m scripts.refresh`,
never `python scripts/refresh.py`.

**Map is blank / no wards**
The 2.5 MB GeoJSON is in `frontend/web/public/data/`. If missing, the UI falls
back gracefully. Check it's there, then hard-reload (`Cmd/Ctrl+Shift+R`).

**`uvicorn: command not found`**
The venv isn't active, or deps aren't installed:
`source .venv/bin/activate && pip install -r requirements.txt`

**`vite: not found`**
`cd frontend/web && npm install`

**Python 3.13 + pandas issues**
Pinned versions are in `requirements.lock.txt`:
`pip install -r requirements.lock.txt`

---

## 9. Project layout

```
heatshield/
├── app/main.py              FastAPI service (23 endpoints)
├── core/
│   ├── weather.py           Open-Meteo batch fetch + cache
│   ├── thermal.py           WBGT + heat index
│   ├── risk.py              0–100 risk index
│   ├── alerts.py            lead-time detection + Twilio dispatch
│   ├── subscribers.py       ward-level registry + STOP handling
│   └── config.py            all tunables
├── frontend/web/            Vite + React + Framer Motion app
├── scripts/
│   ├── refresh.py           one-shot pipeline run
│   ├── schedule.py          unattended scheduler
│   ├── hindcast.py          skill evaluation
│   └── package.py           builds heatshield.zip
├── data/
│   ├── wards.csv            141 real KMC wards
│   ├── processed/           precomputed forecast (works offline)
│   └── archive/             forecast snapshots for skill scoring
└── tests/                   52 tests
```

---

## 10. What is real vs placeholder

| Real | Placeholder |
|---|---|
| 141 KMC ward boundaries (OpenCity / ODbL) | Subscriber phone numbers in `data/subscribers.csv` |
| Census 2011 PCA demographics | — |
| Live Open-Meteo forecast + reanalysis | — |
| WBGT / heat index physics (11 validated tests) | `data/mortality_labels.SYNTHETIC.example.csv` — generated from the model, so its `R²` is circular |

**Not included anywhere, for any user:** ward-level 60+ population and slum
share (absent from the ward-level Census 2011 PCA), and real mortality outcomes.
The vulnerability index therefore measures exposure, urban form and socioeconomic
deprivation — not physiological frailty. This is stated in the UI's provenance
panel rather than papered over.
