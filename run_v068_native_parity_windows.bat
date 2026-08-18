@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo MotorCAD Studio V0.68 - Motor-CAD 2026R1 Native Parity Suite
echo BPM / SPM / IPM / AFPM
echo ============================================================
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on PATH.
  exit /b 1
)
set PYMOTORCAD_VERSION=
for /f "delims=" %%V in ('python -c "import ansys.motorcad.core as p; print(getattr(p, '__version__', 'missing'))" 2^>nul') do set PYMOTORCAD_VERSION=%%V
if not "%PYMOTORCAD_VERSION%"=="0.8.8" (
  echo [INFO] V0.68 qualification freezes PyMotorCAD at 0.8.8. Current=%PYMOTORCAD_VERSION%
  echo        Installing the pinned workstation qualification environment ...
  python -m pip install -r requirements-motorcad.txt
  if errorlevel 1 exit /b 1
)
python scripts\run_v068_native_parity.py --profiles bpm,spm,ipm,afpm --timeout 1200
set EXITCODE=%ERRORLEVEL%
if %EXITCODE%==0 (
  echo [PASS] All V0.68 native parity profiles are NATIVE_QUALIFIED.
) else (
  echo [ATTENTION] Suite finished with unresolved native parity items. Exit code=%EXITCODE%
  echo Inspect data\runtime\native_parity\suites\ for the evidence report.
)
exit /b %EXITCODE%
