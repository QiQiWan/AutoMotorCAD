@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title MotorCAD Studio

echo.
echo ==============================================
echo   MotorCAD Studio
echo ==============================================
echo.

if defined MOTORCAD_STUDIO_PYTHON (
  "%MOTORCAD_STUDIO_PYTHON%" -m motorcad_studio.bootstrap_cli %*
  set "EXIT_CODE=!errorlevel!"
  goto :finish
)

where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m motorcad_studio.bootstrap_cli %*
  set "EXIT_CODE=!errorlevel!"
  goto :finish
)

where python >nul 2>&1
if %errorlevel%==0 (
  python -m motorcad_studio.bootstrap_cli %*
  set "EXIT_CODE=!errorlevel!"
  goto :finish
)

echo [ERROR] Python 3 was not found.
echo Install Python 3.10 or newer and enable "Add Python to PATH".
echo You may also set MOTORCAD_STUDIO_PYTHON to a Python executable path.
set "EXIT_CODE=9009"

:finish
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Startup failed with exit code %EXIT_CODE%.
  echo See README.md and logs\startup.log in this program folder.
  pause
)
exit /b %EXIT_CODE%
