@echo off
setlocal
cd /d %~dp0
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -U pip
python -m pip install -r requirements-motorcad.txt
set MOTORCAD_STUDIO_DEFAULT_SOLVER=motorcad
set MOTORCAD_STUDIO_MAX_WORKERS=1
set MOTORCAD_STUDIO_MOTORCAD_VISIBLE=false
python scripts\bootstrap_motorcad.py
if errorlevel 1 (
  echo.
  echo Motor-CAD environment check failed. Review the JSON diagnostics above.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8765
python -m motorcad_studio.main
