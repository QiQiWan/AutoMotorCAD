# Motor-CAD Onboarding

Current release: **MotorCAD Studio 0.89.6 / Schema 45**  
Windows qualification contract: **0.88-F**

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
5. In Runtime, confirm Motor-CAD installation, license, PyMotorCAD communication and native preflight.
6. Qualify V0.88-A semantic bindings for representative templates before treating native writes as production authority.

If automatic discovery fails, set `MOTORCAD_STUDIO_MOTORCAD_EXE` to the full executable path.

## Normal engineer use

Use Guided mode and the Design -> Validate -> Decide workflow. Worker/Scheduler/COM details remain diagnostic surfaces.

When Motor-CAD native validation fails, use the typed V0.88-C diagnosis in this order:

1. read the root-cause fault and affected parameter/component;
2. inspect the RepairPlan safety class;
3. use **安全修复并重新检查** only when Studio explicitly offers it;
4. for confirmation/manual faults, correct the Design Draft or Motor-CAD environment as instructed and rerun validation;
5. do not treat a design-time safe repair as formal production qualification evidence.

A V0.88-C safe repair only resynchronizes the current live Motor-CAD session to the frozen current BindingPlan. It does not modify the source template or silently alter design intent.

## V0.89 workflow/HMI check

Before native qualification, verify that the persistent context breadcrumb follows the active Project/Solution/Motor/Analysis lineage and that blocked Design/Validate/Decide stages show a clear prerequisite. Developer qualification can be opened from the System page to run/export the current HMI action registry. The fixed 0.89.3 shell baseline is 87/87 registered controls.

## V0.89-C transaction check

Before native qualification, exercise one Project edit and one Design/Analysis edit across navigation. Leaving dirty Project settings must present the explicit three-way decision. A blocked navigation must retain entered values; save-and-continue must persist once and close the editor only after navigation commits. In Analysis, step/domain/Common-Advanced transitions must preserve pending values. Rapid repeated clicks must not create duplicate Project, Revision or Task state transitions.

## Production qualification

After normal native computation is working:

1. run `run_windows_production_qualification.bat`;
2. complete the required fault/recovery evidence rows;
3. require V0.88-A semantic authority, V0.88-B post-solve NativeModelSnapshot authority and V0.88-C CLEAN repair-orchestration authority for every representative native scenario;
4. verify the V0.88-D editor transaction, V0.88-E native-preview reconciliation and V0.88-F spatial-geometry/result-overlay release gates;
5. verify `native_repair_attempt_count == 0` for formal scenarios;
6. only after Windows qualification passes, run `run_production_soak.bat` for the 100/500 Case endurance gate.

A template being present in the catalog does not mean the topology is production-qualified. Local simulated PyMotorCAD regression evidence also does not replace licensed target-workstation qualification.


## V0.88-F spatial evidence

After one representative native solve, open the Case result viewer and inspect the Native Spatial Authority card. A formal candidate should report `QUALIFIED`, a non-empty spatial-geometry hash and overlay hash, and coordinate alignment `CONFIRMED`. The region-boundary layer should come from GeometryTree. If native mesh connectivity is unavailable, the expected field display is native points; absence of a smooth contour is intentional evidence preservation.
