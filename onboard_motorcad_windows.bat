@echo off
setlocal
cd /d %~dp0
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -U pip
python -m pip install -r requirements-motorcad.txt
set MOTORCAD_STUDIO_MOTORCAD_VERSION=2026R1
python scripts\scan_motorcad_installations.py --target 2026R1
if errorlevel 1 goto :failed
python scripts\bootstrap_motorcad.py
if errorlevel 1 goto :failed
python scripts\prepare_verified_models.py
if errorlevel 1 goto :failed
python scripts\verify_motorcad_runtime.py i5_Industrial_SPM_Servo_Tooth_Wound
if errorlevel 1 goto :failed
python scripts\verify_motorcad_runtime.py e9_eMobility_IPM
if errorlevel 1 goto :failed
python scripts\verify_motorcad_runtime.py e14_eMobility_AFM
if errorlevel 1 goto :failed
echo.
echo Motor-CAD onboarding completed. Review data\runtime\runtime_verify and verified model folders.
pause
exit /b 0
:failed
echo.
echo Motor-CAD onboarding failed. Review the diagnostics above.
pause
exit /b 1
