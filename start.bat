@echo off
REM ============================================================================
REM  HeatShield - start the working prototype (Windows)
REM    start.bat            API + dashboard
REM    start.bat --pwa      also build + serve the offline PWA
REM
REM  Run setup.bat first if this is a fresh clone.
REM ============================================================================
setlocal enabledelayedexpansion

set API_PORT=8000
set WEB_PORT=5173
set PWA_PORT=4173
if defined HS_API_PORT set API_PORT=%HS_API_PORT%
if defined HS_WEB_PORT set WEB_PORT=%HS_WEB_PORT%
if defined HS_PWA_PORT set PWA_PORT=%HS_PWA_PORT%
set WITH_PWA=0
if "%1"=="--pwa" set WITH_PWA=1

echo.
echo   HeatShield - starting prototype
echo.

REM ---------------------------------------------------------------- 1. Python
where python >nul 2>&1
if errorlevel 1 (
  echo   ERROR Python not found. Run setup.bat first.
  exit /b 1
)
REM Prefer the virtualenv setup.bat created: deps live in .venv, not in the
REM system Python, so running the bare interpreter would report them missing.
if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
  echo   OK    using .venv
)
python -c "import uvicorn, fastapi, pandas" >nul 2>&1
if errorlevel 1 (
  echo   ERROR Python dependencies missing.
  echo         Run setup.bat, or:  pip install -r requirements.txt
  exit /b 1
)
echo   OK    Python dependencies present

REM ---------------------------------------------------------------- 2. Node
where npm >nul 2>&1
if errorlevel 1 (
  echo   ERROR npm not found. Install Node 18+ from https://nodejs.org
  exit /b 1
)
if not exist "frontend\web\node_modules" (
  echo   !!    node_modules missing - installing
  pushd frontend\web
  call npm install --no-audit --no-fund
  popd
)
echo   OK    node_modules present

REM ---------------------------------------------------------------- 3. Data
REM Always try a live refresh at boot (it is idempotent, ~5 s when online).
REM Offline it fails soft: the API then serves the last scored run instead.
echo   ==^>  Refreshing forecast (live; falls back to last run if offline)
if not exist logs mkdir logs
python -m scripts.refresh > logs\refresh.log 2>&1
if errorlevel 1 (
  echo   !!    live refresh failed (offline or API blocked^) - serving last scored run
  echo         see logs\refresh.log
) else (
  echo   OK    forecast refreshed
)

REM ---------------------------------------------------------------- 4. API
echo   ==^>  Starting API on :%API_PORT%
start "HeatShield API" /b python -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT% > logs\api.log 2>&1

REM ---------------------------------------------------------------- 5. Web
echo   ==^>  Starting dashboard on :%WEB_PORT%
pushd frontend\web
start "HeatShield Web" /b npm run dev -- --host 0.0.0.0 --port %WEB_PORT% > ..\..\logs\web.log 2>&1
popd

REM ---------------------------------------------------------------- 6. PWA
if "%WITH_PWA%"=="1" (
  echo   ==^>  Building + serving production PWA on :%PWA_PORT%
  pushd frontend\web
  call npm run build > ..\..\logs\build.log 2>&1
  start "HeatShield PWA" /b npm run preview -- --host 0.0.0.0 --port %PWA_PORT% > ..\..\logs\pwa.log 2>&1
  popd
)

echo.
echo   -------------------------------------------------------------
echo     HeatShield is running
echo       Dashboard   http://localhost:%WEB_PORT%
echo       API         http://localhost:%API_PORT%   (docs: /docs)
if "%WITH_PWA%"=="1" echo       PWA build   http://localhost:%PWA_PORT%   (offline)
echo       Logs        logs\
echo.
echo     Switch views with the pill at the bottom:
echo       Overview . Operations . Citizen
echo     Close this window to stop.
echo   -------------------------------------------------------------
echo.

pause
