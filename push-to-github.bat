@echo off
REM ===========================================================================
REM  HeatShield - push this folder to GitHub in ONE command.
REM
REM  Double-click this file, paste your repository URL, done.
REM ===========================================================================
setlocal enabledelayedexpansion

echo.
echo HeatShield -^> GitHub
echo.
echo   First, create an EMPTY repository at https://github.com/new
echo   Do NOT tick "Add a README file", "Add .gitignore" or "Choose a license" -
echo   this project already ships all three and they would collide.
echo.

set /p REPO=  Paste your repository URL (e.g. https://github.com/you/heatshield.git):
if "%REPO%"=="" (
  echo No URL given - nothing to do.
  exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
  echo git is not installed. Get it from https://git-scm.com/downloads
  exit /b 1
)

if not exist .git git init
git add -A

set N=0
for /f %%i in ('git ls-files ^| find /c /v ""') do set N=%%i
echo   %N% files staged for commit

if %N% GTR 400 (
  echo   That is far too many files - .venv\ or node_modules\ is being included.
  echo   Fix .gitignore before pushing. Aborting.
  exit /b 1
)

git ls-files | findstr /b /c:".venv/" /c:"node_modules/" /c:"__pycache__/" >nul
if not errorlevel 1 (
  echo   .venv\ or node_modules\ would be committed. Aborting.
  exit /b 1
)

git commit -q -m "HeatShield: extreme heatwave early warning + human thermal stress index"
git branch -M main
git remote remove origin >nul 2>nul
git remote add origin %REPO%

echo.
echo   Pushing...
echo   (if it asks for a password, use a Personal Access Token, not your password)
echo.

git push -u origin main
if not errorlevel 1 (
  echo.
  echo   Done. Open your repository on github.com and check the Actions tab -
  echo   the CI workflow should go green within a minute.
  echo   Verify: the repo must show ~110 files, and core/, app/, scripts/,
  echo   tests/, data/ and frontend/ must all be visible.
  goto :eof
)

echo.
echo   Push was rejected - the remote already has a commit.
echo   A half-finished browser upload lands here: it uploads top-level files
echo   and silently drops every nested folder, so GitHub shows ~22 files
echo   and no source code at all.
echo.
set /p YN=  Replace the remote contents with this complete project? [y/N]
if /i not "%YN%"=="y" (
  echo   Nothing pushed. Create a fresh EMPTY repo at github.com/new and re-run.
  goto :eof
)

echo.
echo   Force-pushing...
git push -u origin main --force
if errorlevel 1 (
  echo   Still failed. Check the URL, and use a Personal Access Token
  echo   (not your account password) when prompted.
) else (
  echo.
  echo   Done. Check the repo shows ~110 files with core/, app/, scripts/,
  echo   tests/, data/ and frontend/ all visible.
)
