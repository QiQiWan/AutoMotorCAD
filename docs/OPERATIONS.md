# Operations

## Normal Windows start

`start_windows_motorcad.bat`

## Environment/onboarding

`onboard_motorcad_windows.bat`

## Production qualification

`run_windows_production_qualification.bat`

## Production soak

`run_production_soak.bat`

## Diagnostics

Current diagnostic utilities are kept under `scripts/`. Historical version-specific verification scripts are intentionally excluded from this release package.
## Automatic startup self-check

On application startup, the Guided runtime page automatically runs the shallow environment check. The visible progress contract is:

1. installation and bound `Motor-CAD.exe` discovery;
2. shallow path/Python/runtime dependency checks without launching Motor-CAD;
3. Windows production qualification and soak evidence status loading;
4. a final ready / warning / blocked summary.

The deep Motor-CAD check remains an explicit engineer action because it launches a Motor-CAD process and may consume a license.

The full-shell browser regression must load the current `index.html` together with every current JavaScript asset. This gate exists to catch DOM/API drift that module-level HMI tests cannot detect.

