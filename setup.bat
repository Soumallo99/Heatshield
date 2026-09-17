@echo off
REM =============================================================================
REM HeatShield — one-command local setup (Windows)
REM   Double-click this file, or run:  setup.bat
REM =============================================================================
setlocal EnableDelayedExpansion

echo.
echo HeatShield setup (PWA dashboard; no Android tooling required)
echo.

REM ------------------------------------------------------------- 1. Python
echo ==^> Checking Python
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   ERROR: Python not found.
  echo   Install Python 3.11 from https://www.python.org/downloads/
  echo   IMPORTANT: tick "Add python.exe to PATH" during install, then re-run this file.
  echo.
  pause
  exit /b 1
)
for /f "tokens=2" %%v in ('python -c "import sys;print(f\"{sys.version_info.major}.{sys.version_info.minor}\")"') do set PYVER=%%v
echo   OK   Python %PYVER%
python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
  echo   ERROR: Python %PYVER% is too old. HeatShield needs 3.10+ ^(3.11 recommended^).
  pause
  exit /b 1
)

REM ------------------------------------------------------------- 2. venv
echo ==^> Creating virtual environment ^(.venv^)
if not exist .venv (
  python -m venv .venv
  if errorlevel 1 (
    echo   ERROR: venv creation failed. Reinstall Python and tick "pip" ^& "venv" in the installer.
    pause
    exit /b 1
  )
  echo   OK   created
) else (
  echo   OK   already exists, reusing
)
call .venv\Scripts\activate.bat

REM ------------------------------------------------------------- 3. deps
echo ==^> Upgrading pip
python -m pip install --upgrade pip --quiet
echo ==^> Installing Python dependencies ^(1-3 minutes^)
set REQ=requirements.txt
if /i "%~1"=="--locked" (
  if exist requirements.lock.txt (
    set REQ=requirements.lock.txt
    echo   OK   using pinned lockfile ^(exact versions^)
  ) else (
    echo   !!!  requirements.lock.txt not found, using requirements.txt
  )
) else (
  echo   OK   using requirements.txt ^(latest compatible^)
)
pip install -r %REQ% --quiet
if errorlevel 1 (
  echo.
  echo   ERROR: pip install failed. See the message above.
  echo   Common fix on Windows:
  echo     "Microsoft Visual C++ 14.0 is required"
  echo       -^> https://visualstudio.microsoft.com/visual-cpp-build-tools/
  echo       -^> install "Desktop development with C++", then re-run this file.
  echo.
  pause
  exit /b 1
)
echo   OK   dependencies installed

REM ------------------------------------------------------------- 4. env + dirs
echo ==^> Preparing environment
if not exist .env copy .env.example .env >nul
if not exist data\raw mkdir data\raw
if not exist data\processed mkdir data\processed
if not exist data\cache mkdir data\cache
if not exist logs mkdir logs
echo   OK   folders ready

REM ------------------------------------------------------------- 5. Node
echo ==^> Checking Node.js ^(needed for Phase 4 web UI + Android app^)
where node >nul 2>nul
if errorlevel 1 (
  echo   !!!  Node.js not found - required for the web UI and Android app.
  echo        Install the LTS installer from https://nodejs.org then re-run this file.
) else (
  for /f "tokens=1" %%v in ('node --version') do echo   OK   Node %%v
)

REM ------------------------------------------------------------- 6. smoke
echo ==^> Running smoke tests
python -m core.weather >nul && echo   OK   Phase 1 pipeline: fetched live forecast
set PYTHONPATH=.
python tests\test_thermal.py >nul && echo   OK   Phase 2 physics: 11/11 tests pass

echo.
echo   Setup complete.
echo.
echo   Run the backend:
echo       .venv\Scripts\activate
echo       uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
echo   Then open  http://localhost:8000/docs
echo.
echo   Full install + Android build guide:  SETUP.md
echo.
pause
