# HeatShield — Running it in **Google Antigravity** (exact steps)

> Goal: open this project in Antigravity on your laptop and get **byte-for-byte the same
> behaviour** as the sandbox: 141 wards · 20,304 ward-hours · 846 ward-days · 52 tests passing ·
> dashboard on :5173 · API on :8000.
>
> Follow the steps **in order**. Every command below is copy-paste ready.
> Anything marked ⚠️ is a step people get wrong — read those twice.

---

## 0. First: what actually changes when you move from VS Code to Antigravity

Antigravity is a **fork of VS Code**, so it reads the same `.vscode/` folder, the same
`launch.json`, the same `tasks.json`. **Zero code changes are needed.** Only three things differ:

| # | VS Code | Google Antigravity | What you must do |
|---|---------|--------------------|------------------|
| 1 | Microsoft Marketplace | **Open VSX** registry | Install `basedpyright` instead of Pylance (see Step 3) |
| 2 | Pylance works | **Pylance does not exist on Open VSX** (`404`) | Do not try to install it. Use `detachhead.basedpyright` |
| 3 | venv at `.venv/bin/python` | Same on Mac/Linux; on **Windows** it is `.venv\Scripts\python.exe` | Already patched in `.vscode/settings.json` — but still verify in Step 5 |

I verified every extension ID in this guide against the Open VSX registry API.
`ms-python.python`, `ms-python.debugpy`, `ms-python.black-formatter`, `charliermarsh/ruff`,
`detachhead/basedpyright`, `esbenp.prettier-vscode`, `bradlc.vscode-tailwindcss`,
`christian-kohler.path-intellisense`, `eamodio.gitlens`, `streetsidesoftware.code-spell-checker`
→ all available.
`ms-python.vscode-pylance` and `ms-vscode-remote.remote-containers` → **not available**, and both
have been removed from `.vscode/extensions.json` so Antigravity won't nag you about them.

> **If you prefer the official Microsoft marketplace**, Antigravity lets you switch it:
> Settings → Antigravity Settings → Editor → set *Marketplace Item URL* to
> `https://marketplace.visualstudio.com/items` and *Marketplace Gallery URL* to
> `https://marketplace.visualstudio.com/_apis/public/gallery`, then restart.
> **You do not need to do this** — everything below works on the default Open VSX registry.

---

## 1. Prerequisites (check these BEFORE anything else)

Open Antigravity's terminal (`` Ctrl+` `` / `` Cmd+` ``) and run:

```bash
python3 --version     # must be 3.10+ ; 3.11 is the sweet spot
node --version        # must be v18 or newer
npm --version         # ships with Node
```

| Requirement | Version | Where to get it |
|---|---|---|
| Python | **3.10 – 3.12** (3.11 recommended) | https://www.python.org/downloads/ |
| Node.js | **18 LTS or newer** | https://nodejs.org (LTS installer) |
| Antigravity | latest | https://antigravity.google/ |
| Internet | yes, on first run | the pipeline fetches a live forecast |

⚠️ **Windows users:** when installing Python, tick **"Add python.exe to PATH"** at the bottom of
the installer. If you already installed it without that tick, re-run the installer and choose
*Modify*. Almost every "python is not recognised" failure comes from this one checkbox.

⚠️ **Python 3.13+ works but is slower to install** (some scientific packages must compile from
source). If `pip install` hangs for more than ~5 minutes, install Python 3.11 and start over.

---

## 2. STEP 1 — Unzip to a short path with **no spaces**

The zip contains **one single top-level folder named `heatshield`** — so unzipping always
produces exactly one folder and there is no guesswork about where the project root is.

Extract it to a simple, short parent location with **no spaces**:

| OS | Unzip to | Project root becomes |
|---|---|---|
| Windows | `C:\` | `C:\heatshield` |
| macOS | your Home folder | `~/heatshield` |
| Linux | your Home folder | `~/heatshield` |

⚠️ Do **not** unzip into `C:\Users\Your Name\OneDrive\Desktop\SIH 2026\final final\`.
Spaces and non-ASCII characters in the path break `npm`/`vite` and some Python tools in ways that
look like mysterious bugs later.

⚠️ Do **not** create a folder called `heatshield` first and unzip *into* it — you'll end up with
`heatshield/heatshield/…` and then open the wrong level. Just unzip; let the archive create the
folder.

After unzipping, the folder must contain **exactly** these at the top level:

```
heatshield/
├── ANTIGRAVITY.md     ← this file
├── VSCODE.md
├── README.md  DATA.md  SETUP.md
├── requirements.txt          requirements.lock.txt
├── setup.sh   setup.bat      start.sh   start.bat   stop.sh
├── app/       core/          scripts/    tests/
├── data/      frontend/      .vscode/
└── .env.example
```

---

## 3. STEP 2 — Open the *right* folder in Antigravity

Antigravity → **File → Open Folder…** → select the **`heatshield`** folder that the zip created
(the one that directly contains `requirements.txt` and `start.sh`).

⚠️ **The single most common mistake:** opening one level too high. If you see a lone folder named
`heatshield` inside the Explorer, you are in the wrong place — you'll get
`No module named 'core'`, `ENOENT`, or a missing `requirements.txt`.

**How to confirm you're in the right place:** the Explorer panel's top level must show `app`,
`core`, `data`, `frontend`, `scripts`, `tests`, `requirements.txt` and `start.sh` **side by side**.
A fast check in the terminal:

```bash
ls requirements.txt start.sh core/ app/      # all four must exist, no errors
```

When you open it, Antigravity will pop up *"This workspace has extension recommendations"* →
click **Install All** (or see Step 3 to do it manually).

---

## 4. STEP 3 — Install the extensions

Open the Extensions panel (`Ctrl+Shift+X` / `Cmd+Shift+X`) and install these **three**. They are
the only ones that affect whether the project *runs*:

| Extension | ID | Why required |
|---|---|---|
| **Python** | `ms-python.python` | interpreter selection, test discovery, environment |
| **Python Debugger** | `ms-python.debugpy` | makes the `F5` configs in `.vscode/launch.json` work |
| **basedpyright** | `detachhead.basedpyright` | the open-source stand-in for Pylance (type checking + IntelliSense) |

Optional but nice: `ms-python.black-formatter`, `charliermarsh.ruff`, `esbenp.prettier-vscode`,
`bradlc.vscode-tailwindcss`, `christian-kohler.path-intellisense`, `eamodio.gitlens`,
`streetsidesoftware.code-spell-checker`.

⚠️ **Do not search for "Pylance".** It is not on Open VSX. If you previously used VS Code, do not
try to copy it over — installing it from a VSIX violates Microsoft's marketplace terms and can
leave Antigravity in a broken state.

After installing, run **Developer: Reload Window** from the command palette
(`Ctrl+Shift+P` / `Cmd+Shift+P`) once.

---

## 5. STEP 4 — Create the virtual environment

Run these in the Antigravity **integrated terminal** (it opens in the project root).

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Windows — PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

⚠️ **If PowerShell refuses to run the activate script** (`running scripts is disabled on this
system`), run this **once** in the same terminal, then retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

This only affects the current Antigravity session — it is safe and does not change your machine
settings.

### Windows — Command Prompt (if PowerShell gives you trouble)

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Expected:** the install takes 1–4 minutes and ends with `Successfully installed …`.
Your prompt should now start with `(.venv)`.

**Want the exact same package versions as the sandbox?** Use the pinned lockfile instead:

```bash
pip install -r requirements.lock.txt
```

This installs the identical versions (FastAPI 0.141.1, pandas, numpy, scikit-learn, pytest 9.1.1,
…) — use this if you want maximum reproducibility for the demo.

---

## 6. STEP 5 — Select the interpreter inside Antigravity  ⚠️ MOST IMPORTANT STEP

Creating the venv is not enough. Antigravity must be **pointed at it**, otherwise `F5` and the
`Ctrl+Shift+B` tasks will silently use your system Python and fail with
`ModuleNotFoundError: No module named 'fastapi'`.

1. Press `Ctrl+Shift+P` / `Cmd+Shift+P`
2. Type: `Python: Select Interpreter`
3. Choose **Enter interpreter path…** → **Find…**
4. Navigate into the project and pick:

| OS | Path |
|---|---|
| macOS / Linux | `heatshield/.venv/bin/python` |
| Windows | `heatshield\.venv\Scripts\python.exe` |

5. **Close every terminal tab** (`Ctrl+Shift+P` → *Terminal: Kill All Terminals*) and open a fresh
   one — existing terminals keep the old PATH.

Verify it worked:

```bash
python -c "import sys; print(sys.executable)"
```

✅ The printed path must **end with** `.venv/bin/python` (or `.venv\Scripts\python.exe`).
❌ If it prints `/usr/bin/python3` or `C:\Users\…\AppData\Local\Programs\Python\…`, stop and
   redo this step — nothing else will work.

---

## 7. STEP 6 — Install the frontend dependencies

```bash
cd frontend/web
npm install
cd ../..
```

**Expected:** `added 141 packages`. Takes ~10–60 s.

---

## 8. STEP 7 — Run it

### Option A — the terminal one-liner (most reliable, use this first)

```bash
./start.sh                 # macOS / Linux
start.bat                  # Windows
```

Leave it running. It boots the API on :8000, the dashboard on :5173, and prints a summary box.
Press `Ctrl+C` to stop everything cleanly.

### Option B — `F5` in Antigravity

1. Open the **Run and Debug** panel (`Ctrl+Shift+D` / `Cmd+Shift+D`)
2. In the dropdown at the top, pick **`HeatShield: Full stack (API + Web)`**
3. Press `F5`

This starts the API as a background task, then Vite, and lets you set breakpoints in
`core/*.py` and `app/main.py`.

The 7 configs available: *Full stack*, *API (FastAPI)*, *Web (Vite)*, *Refresh forecast data*,
*Run scheduler (one cycle)*, *Hindcast (30 days)*, *Pytest: all tests*.

⚠️ If the dropdown is empty or says *"No configurations"*, the **Python Debugger** extension
(Step 3) isn't installed, or you opened the wrong folder (Step 2). Reload the window and recheck.

### Option C — `Ctrl+Shift+B` tasks

`Ctrl+Shift+B` / `Cmd+Shift+B` → **Start everything**.
Other tasks: *Refresh forecast data*, *Run scheduler once*, *Hindcast (30 days)*, *Run tests*,
*Build frontend*, *Seed demo subscribers*.

---

## 9. STEP 8 — Open the app

| What | URL |
|---|---|
| **Dashboard (what the judges see)** | http://localhost:5173 |
| Interactive API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Offline PWA build (`./start.sh --pwa`) | http://localhost:4173 |

In Antigravity you can also ask its browser agent to open `http://localhost:5173` — but a normal
browser tab is more reliable for the demo.

**To stop everything:** `Ctrl+C` in the terminal, or run `./stop.sh` / `stop.bat`.

---

## 10. Verify you got the *exact same* result

Some numbers are **invariants** — they must match exactly, and if they don't, something is wrong.
Others are **live** — they legitimately change because the model runs on a real, live forecast.

### ✅ Invariants — these MUST match exactly

Run the pipeline and the tests:

```bash
python -m scripts.refresh
python -m pytest tests -q
```

`scripts.refresh` must print (structure identical):

```
Loaded 141 wards
Weather : 20,304 ward-hours in <a few seconds>
Window  : <today> 00:00:00  ->  <today+5> 23:00:00
Thermal : 20,304 ward-hours, 846 ward-days
Risk    : 846 ward-days
  alert engine defaults: threshold=60.0, lead>=1d
```

| Invariant | Exact value |
|---|---|
| Wards | **141** |
| Ward-hours fetched | **20,304** (141 × 144 h) |
| Ward-days scored | **846** (141 × 6 days) |
| API requests to Open-Meteo | **4** (batched 40 coords/request) |
| `pytest tests -q` | **52 passed** |
| `curl localhost:8000/zones` → `count` | **141** |
| `curl localhost:8000/health` → `status` | `"ok"` |
| Alert threshold | **60.0** |
| Dashboard HTTP status | **200** |

### 🌤️ Live values — these WILL differ (that's correct, not a bug)

The forecast window, the peak ward, and the individual risk scores come from the live
Open-Meteo forecast for Kolkata. On **2026-09-08** this run produced:

```
Dates   : 2026-09-07 -> 2026-09-12
  min_lead_days=1:   3 wards queued, lead times [1]
  active today        :   0 wards (nowcasts, not warnings)

Top ward: Ward 24 · risk 63.0 · Danger · peak WBGT 33.45°C · HI 45.63°C
          UHI +3.47°C · vulnerability 80.5 · exposed 12,489 residents
Band counts on peak day (2026-09-09): Caution 91, Danger 50
```

Your run will show **today's** dates and whatever the weather actually is. If your top ward is a
different number or a different day, that is the model responding to real weather — not an error.

Expect **small drift even between two runs minutes apart**. Verified today: `scripts.refresh` run at
12:39 gave top ward **Ward 24 · risk 63.0** with 3 wards queued; the same command at 12:45 gave
**Ward 24 · risk 62.2** with 2 wards queued. Open-Meteo updates its forecast continuously, so a
±1 risk-point wobble or a ±1 change in the queued-ward count is normal. The **invariants above
never move** — that's what you check.

⚠️ **If the dates shown are 3+ days old**, the pipeline didn't refresh. Run
`python -m scripts.refresh` and restart the API (it caches the CSVs at startup).

### Quick "is it really computing?" test

```bash
curl -s "http://localhost:8000/risk/ranking?limit=1"
curl -s "http://localhost:8000/alerts/plan" | head -c 400
```

You should see a top-ranked ward with a `risk_score`, `wbgt_peak_c`, `uhi_delta_c` and
`excess_deaths_per_day`, and an alert plan with `threshold: 60.0`.

---

## 11. Antigravity-specific gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `python : The term 'python' is not recognized` | Python not on PATH (Windows) | Reinstall Python with *Add to PATH*, or use `py -3.11 -m venv .venv` |
| `ModuleNotFoundError: No module named 'core'` | Wrong working directory, or interpreter not selected | Re-do Step 2 and Step 5 |
| `Pylance` not found in Extensions | Not on Open VSX | Install `detachhead.basedpyright` (Step 3) |
| F5 dropdown empty | Python Debugger extension missing | Install `ms-python.debugpy`, reload window |
| `npm run dev` fails with `vite: not found` | `npm install` skipped | Re-run Step 6 |
| Blank map on the dashboard | API not running, so `/api/*` proxy fails | Start the API first; check http://localhost:8000/health |
| `Address already in use :5173` | Old process still running | `./stop.sh`, or `HS_WEB_PORT=5174 ./start.sh` |
| Blank page + `Mixed Content` | Not applicable locally | — |
| Antigravity's agent edited your files | Agents have shell access | Run `python -m pytest tests -q`; `git diff` if you versioned it |

---

## 12. Troubleshooting the running app

| Symptom | Fix |
|---|---|
| Dashboard shows stale dates | `python -m scripts.refresh` then restart the API |
| `0 wards queued` in the alert plan | Correct behaviour if no ward crosses risk 60 with ≥1 day lead. Not a fault |
| `ModuleNotFoundError: No module named 'pytest'` | `pip install pytest` — it is now in `requirements.txt`; if you installed from an older zip, add it manually |
| Port 8000 busy | `HS_API_PORT=8010 ./start.sh` |
| Everything slow on first load | Vite is compiling; wait ~10 s |
| Forecast fetch fails / no internet | The dashboard still renders from the bundled `data/processed/*.csv`. Only the *live refresh* needs internet |

---

## 13. The 60-second demo script (for the judges)

1. `./start.sh` (or `start.bat`)
2. Open **http://localhost:5173**
3. Show the three views via the pill at the bottom: **Overview · Operations · Citizen**
4. Say: *"141 real KMC wards, live forecast, WBGT + Heat Index physics, UHI adjustment,
   vulnerability-weighted risk, ward-level SMS alerts with a dry-run dispatch queue."*
5. Open **http://localhost:8000/docs** to prove it's a real, documented API — not a mockup.
6. Run `python -m scripts.schedule --once` to show the unattended daemon path.

---

## Quick command reference

```bash
# first time only
python3 -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend/web && npm install && cd ../..

# every time
./start.sh                      # Windows: start.bat
#    → dashboard :5173 · API :8000 · docs :8000/docs

# useful
python -m scripts.refresh       # re-fetch live forecast + re-score all wards
python -m scripts.schedule --once   # one unattended cycle (alert dispatch, dry-run)
python -m scripts.hindcast --days 30
python -m pytest tests -q       # expect: 52 passed
python -m core.subscribers --seed --stats
./stop.sh                       # Windows: stop.bat
```

---

## Where the real data comes from

| File | Source | Real or placeholder |
|---|---|---|
| `data/wards.csv`, `kolkata_wards.geojson` | KMC / Datameet ward boundaries | **Real** — 141 wards |
| `data/census2011_ward_demographics.csv` | Census 2011 PCA (Kolkata) | **Real** |
| `data/processed/forecast_hourly.csv` | Open-Meteo API, fetched live | **Real, live** |
| `data/mortality_labels.SYNTHETIC.example.csv` | Generated for model validation | **Synthetic** — labelled as such |
| Population 60+, slum share | — | **Absent on purpose** (no ward-level data exists; not invented) |

More detail in `DATA.md`.
