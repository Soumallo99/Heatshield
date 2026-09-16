#!/usr/bin/env bash
# =============================================================================
# HeatShield — one-command local setup (macOS / Linux / WSL)
#   chmod +x setup.sh && ./setup.sh
# =============================================================================
set -euo pipefail

GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; BLUE=$'\033[1;36m'; OFF=$'\033[0m'
step() { printf "\n${BLUE}==>%s${OFF}\n" "$1"; }
ok()   { printf "  ${GREEN}OK${OFF}  %s\n" "$1"; }
warn() { printf "  ${YELLOW}!!${OFF}  %s\n" "$1"; }
die()  { printf "\n  ${RED}ERROR${OFF} %s\n" "$1"; exit 1; }

printf "${GREEN}\n  HeatShield setup\n${OFF}"

# ---------------------------------------------------------------- 1. Python
step "Checking Python"
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else die "Python not found. Install Python 3.11 from https://www.python.org/downloads/
       (macOS: brew install python@3.11   |   Ubuntu: sudo apt install python3.11 python3.11-venv)"; fi

PYVER=$("$PY" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYOK=$("$PY" -c 'import sys;print(1 if sys.version_info>=(3,10) else 0)')
[ "$PYOK" = "1" ] || die "Python $PYVER is too old. HeatShield needs 3.10+ (3.11 recommended)."
ok "Python $PYVER ($($PY -c 'import sys;print(sys.executable)'))"

# ---------------------------------------------------------------- 2. venv
step "Creating virtual environment (.venv)"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv || die "venv creation failed.
       Ubuntu/Debian: sudo apt install python3-venv
       macOS:         reinstall Python from python.org (the bundled build includes venv)"
  ok "created"
else
  ok "already exists, reusing"
fi

# shellcheck disable=SC1091
. .venv/bin/activate
ok "activated  (later, run: source .venv/bin/activate)"

# ---------------------------------------------------------------- 3. deps
step "Upgrading pip"
python -m pip install --upgrade pip --quiet 2>/dev/null || warn "pip upgrade failed (continuing)"
ok "pip $(python -m pip --version | awk '{print $2}')"

step "Installing Python dependencies (this takes 1-3 minutes)"
REQ=requirements.txt
[ "${1:-}" = "--locked" ] && { REQ=requirements.lock.txt; }
[ -f "$REQ" ] || REQ=requirements.txt
[ "$REQ" = "requirements.lock.txt" ] && ok "using pinned lockfile (exact versions)" \
                                     || ok "using $REQ (latest compatible)"
pip install -r "$REQ" --quiet \
  && ok "core dependencies installed" \
  || die "pip install failed. See the error above.
       Common fixes:
         - 'Microsoft Visual C++ 14.0 required'  -> install VS Build Tools (Windows)
         - SSL/CERTIFICATE_VERIFY_FAILED        -> pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
         - numpy build failure                  -> use Python 3.11 instead of 3.13 (better wheel support)"

# ---------------------------------------------------------------- 4. env + dirs
step "Preparing environment"
[ -f .env ] || { cp .env.example .env; ok "created .env from .env.example (fill this in for Phase 5)"; }
mkdir -p data/raw data/processed data/cache logs
ok "data/ and logs/ ready"

# ---------------------------------------------------------------- 5. Node (optional now)
step "Checking Node.js (needed for Phase 4 web UI + Android app)"
if command -v node >/dev/null 2>&1; then
  NODEV=$(node --version)
  NODEOK=$(node -e 'process.stdout.write(Number(process.versions.node.split(".")[0])>=18?"1":"0")')
  if [ "$NODEOK" = "1" ]; then ok "Node $NODEV"
  else warn "Node $NODEV is old — need 18+. Get it from https://nodejs.org (LTS)"; fi
else
  warn "Node.js not found — required for Phase 4 (web UI) and the Android app.
       Install from https://nodejs.org (LTS installer), then re-run this script.
       macOS:  brew install node     |     Ubuntu:  sudo apt install nodejs npm"
fi

# ---------------------------------------------------------------- 6. smoke test
step "Running smoke tests"
python -m core.weather >/dev/null && ok "Phase 1 pipeline: fetched live forecast"
PYTHONPATH=. python tests/test_thermal.py >/dev/null && ok "Phase 2 physics: 11/11 tests pass"

printf "${GREEN}\n  Setup complete.\n${OFF}"
cat <<'NEXT'

  Run the backend:
      source .venv/bin/activate
      uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  Then open  http://localhost:8000/docs

  Full install + Android build guide:  SETUP.md
NEXT
