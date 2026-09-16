#!/usr/bin/env bash
# =============================================================================
# HeatShield — start the working prototype (macOS / Linux / WSL)
#
#   chmod +x start.sh && ./start.sh
#
# Boots everything the prototype needs and leaves it running:
#   :8000  FastAPI backend        (forecast -> WBGT -> risk -> alerts)
#   :5173  Vite dev dashboard     (the interactive UI)
#   :4173  production PWA build   (optional, --pwa; the offline-capable one)
#
# Ctrl-C shuts all of them down cleanly.
# =============================================================================
set -uo pipefail

GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; BLUE=$'\033[1;36m'; OFF=$'\033[0m'
step() { printf "\n${BLUE}==>%s${OFF}\n" "$1"; }
ok()   { printf "  ${GREEN}OK${OFF}  %s\n" "$1"; }
info() { printf "      %s\n" "$1"; }
warn() { printf "  ${YELLOW}!!${OFF}  %s\n" "$1"; }
die()  { printf "\n  ${RED}ERROR${OFF} %s\n" "$1"; exit 1; }

API_PORT="${HS_API_PORT:-8000}"
WEB_PORT="${HS_WEB_PORT:-5173}"
PWA_PORT="${HS_PWA_PORT:-4173}"
WITH_PWA=0
[ "${1:-}" = "--pwa" ] && WITH_PWA=1

cd "$(dirname "$0")" || die "cannot enter project directory"
ROOT="$PWD"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"
PIDS=()

cleanup() {
  printf "\n${YELLOW}Shutting down...${OFF}\n"
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  sleep 1
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null
  done
  printf "${GREEN}Stopped.${OFF}\n"
}
trap cleanup INT TERM EXIT

printf "${GREEN}\n  HeatShield — starting prototype\n${OFF}"

# ---------------------------------------------------------------- 1. Python
step "Python"
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate && ok "using .venv"
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3; ok "system python3"
else
  die "Python not found. Run ./setup.sh first."
fi

"$PY" -c "import uvicorn, fastapi, pandas" 2>/dev/null \
  || die "Python dependencies missing.
       Run ./setup.sh, or:  pip install -r requirements.txt"

# ---------------------------------------------------------------- 2. Node
step "Node"
command -v npm >/dev/null 2>&1 || die "npm not found. Install Node 18+ from https://nodejs.org"
if [ ! -d frontend/web/node_modules ]; then
  warn "node_modules missing — installing (this takes a minute)"
  (cd frontend/web && npm install --no-audit --no-fund) || die "npm install failed"
fi
ok "node_modules present"

# ---------------------------------------------------------------- 3. Data
step "Forecast data"
if [ ! -f data/processed/risk_daily.csv ]; then
  warn "no scored data — running the pipeline once"
  "$PY" -m scripts.refresh || die "pipeline failed"
  ok "pipeline ran"
else
  ok "existing data found (run: $PY -m scripts.refresh  # to force a live update)"
fi

# ---------------------------------------------------------------- 4. API
step "Starting API on :$API_PORT"
"$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" \
  >"$LOGDIR/api.log" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1 \
  && ok "API healthy" \
  || { warn "API did not come up; tail -f $LOGDIR/api.log"; }

# ---------------------------------------------------------------- 5. Web
step "Starting dashboard on :$WEB_PORT"
(cd frontend/web && npm run dev -- --host 0.0.0.0 --port "$WEB_PORT" \
  >"$LOGDIR/web.log" 2>&1) &
PIDS+=($!)

for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null 2>&1 \
  && ok "dashboard serving" \
  || { warn "dashboard did not come up; tail -f $LOGDIR/web.log"; }

# ---------------------------------------------------------------- 6. PWA (optional)
if [ "$WITH_PWA" = "1" ]; then
  step "Building + serving production PWA on :$PWA_PORT"
  (cd frontend/web && npm run build >"$LOGDIR/build.log" 2>&1) \
    && ok "production build" \
    || warn "build failed; tail -f $LOGDIR/build.log"
  (cd frontend/web && npm run preview -- --host 0.0.0.0 --port "$PWA_PORT" \
    >"$LOGDIR/pwa.log" 2>&1) &
  PIDS+=($!)
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$PWA_PORT/" >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
  curl -sf "http://127.0.0.1:$PWA_PORT/" >/dev/null 2>&1 \
    && ok "PWA serving (offline capable)" \
    || warn "PWA did not come up; tail -f $LOGDIR/pwa.log"
fi

# ---------------------------------------------------------------- summary
printf "\n${GREEN}─────────────────────────────────────────────────────${OFF}\n"
printf "${GREEN}  HeatShield is running${OFF}\n"
printf "    Dashboard   ${BLUE}http://localhost:$WEB_PORT${OFF}\n"
printf "    API         ${BLUE}http://localhost:$API_PORT${OFF}"
printf "  (docs: http://localhost:$API_PORT/docs)\n"
[ "$WITH_PWA" = "1" ] && printf "    PWA build   ${BLUE}http://localhost:$PWA_PORT${OFF}  (offline)\n"
printf "    Logs        ${BLUE}$LOGDIR/${OFF}\n"
printf "\n  Switch views with the pill at the bottom: Overview · Operations · Citizen\n"
printf "  Ctrl-C to stop everything.\n"
printf "${GREEN}─────────────────────────────────────────────────────${OFF}\n\n"

wait
