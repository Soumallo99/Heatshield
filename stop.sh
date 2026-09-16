#!/usr/bin/env bash
# =============================================================================
# HeatShield — stop everything started by ./start.sh
#   ./stop.sh
# =============================================================================
set -uo pipefail
OFF=$'\033[0m'; GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'

echo "Stopping HeatShield..."

# uvicorn (API)
pkill -f "uvicorn app.main:app" 2>/dev/null && echo "  stopped API" \
  || echo "  no API process found"

# vite dev + preview
pkill -f "vite.*--port" 2>/dev/null && echo "  stopped web server(s)" \
  || echo "  no web server found"

sleep 1

# anything still holding our ports
for port in "${HS_API_PORT:-8000}" "${HS_WEB_PORT:-5173}" "${HS_PWA_PORT:-4173}"; do
  pid="$(lsof -ti ":$port" 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    kill -9 $pid 2>/dev/null && echo "  freed port $port"
  fi
done

printf "${GREEN}Done.${OFF}\n"
