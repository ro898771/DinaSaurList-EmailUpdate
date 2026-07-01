@echo off
setlocal

REM ─── Get the directory of this batch file ────────────────────────────────────
set "BASE_DIR=%~dp0"

REM ─── Define environment paths ────────────────────────────────────────────────
set "ENV_DIR=%BASE_DIR%.venv"
set "ENV_PYTHON=%ENV_DIR%\Scripts\python.exe"

REM ─── Check if virtual environment exists ─────────────────────────────────────
if not exist "%ENV_PYTHON%" (
    echo Virtual environment not found or Python executable missing.
    pause
    exit /b 1
)

REM ─── Run Python Script ───────────────────────────────────────────────────────
echo Activated myenv. Running main.py...
set PYTHONDONTWRITEBYTECODE=1
"%ENV_PYTHON%" "%BASE_DIR%src\main.py"

echo.
echo Script complete. Press Enter to exit.
pause >nul
endlocal
