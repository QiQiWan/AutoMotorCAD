@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_windows_production_qualification.ps1" %*
exit /b %ERRORLEVEL%
