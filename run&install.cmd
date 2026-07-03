@echo off
setlocal

REM ─── CONFIG — change these if the entry point moves ──────────────────────────
set "MAIN_SCRIPT=src\main.py"
REM ─────────────────────────────────────────────────────────────────────────────

REM --- Get the directory of this batch file ---
set "BASE_DIR=%~dp0"

REM --- Auto-update: runs in this terminal, waits to fully complete before continuing ---
if exist "%BASE_DIR%runtime.exe" (
    echo Checking for updates...
    "%BASE_DIR%runtime.exe"
    echo Update check done. Launching app...
)

REM --- Define environment paths ---
set "ENV_DIR=%BASE_DIR%.venv"
set "ENV_PYTHON=%ENV_DIR%\Scripts\python.exe"

REM --- If venv still missing after updater ran, show error (runtime.exe should have handled this) ---
if not exist "%ENV_PYTHON%" (
    echo ERROR: Virtual environment not found. runtime.exe may have encountered an error above.
    echo Please check the log above, or run env-Init.cmd manually to set up the environment.
    exit /b 1
)

REM --- Launch app ---
set PYTHONDONTWRITEBYTECODE=1
"%ENV_PYTHON%" "%BASE_DIR%%MAIN_SCRIPT%"

echo.
echo Script complete.
endlocal
