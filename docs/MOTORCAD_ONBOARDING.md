# Motor-CAD Onboarding

## Target environment

- Windows workstation
- Motor-CAD 2026R1
- valid Motor-CAD license
- Python supported by this project
- `ansys-motorcad-core==0.8.8`

## Setup

1. Run `onboard_motorcad_windows.bat`.
2. Confirm the detected `Motor-CAD.exe` path and binary version.
3. Install dependencies with `requirements.txt` and `requirements-motorcad.txt`.
4. Start Studio with `start_windows_motorcad.bat`.
5. In the Runtime page, confirm Motor-CAD installation, license, PyMotorCAD communication and native preflight.

If automatic discovery fails, set `MOTORCAD_STUDIO_MOTORCAD_EXE` to the full executable path.

## Normal engineer use

Use Guided mode and the Design → Validate → Decide workflow. Worker/Scheduler/COM details are diagnostic surfaces and are not required for normal design work.

## Production qualification

After normal native computation is working:

- run `run_windows_production_qualification.bat`;
- attach/complete the 17 required fault/recovery evidence rows;
- after that qualification passes, run `run_production_soak.bat` for the 100/500 Case endurance gate.

A template being present in the catalog does not by itself mean the topology is production-qualified.
