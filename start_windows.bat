@echo off
setlocal
cd /d %~dp0
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -U pip
python -m pip install -r requirements.txt
start "" http://127.0.0.1:8765
python -m motorcad_studio.main
