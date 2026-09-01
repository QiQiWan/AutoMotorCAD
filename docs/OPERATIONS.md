# Operations

## Normal Windows start

`start_windows_motorcad.bat`

## Environment/onboarding

`onboard_motorcad_windows.bat`

## Production qualification

`run_windows_production_qualification.bat`

## Production soak

`run_production_soak.bat`

## Diagnostics and live logs

Current diagnostic utilities are kept under `scripts/`. Historical version-specific verification notes are intentionally excluded from the release root; durable operational guidance belongs in this document and release history belongs in `CHANGELOG.md`.

For a source checkout, Studio writes operational logs continuously to the project-root `logs/` directory while the process is running. The default can be overridden with `MOTORCAD_STUDIO_LOG_DIR`.

Primary files:

- `logs/studio.log`: human-readable chronological log for live inspection;
- `logs/studio.jsonl`: complete structured event stream;
- `logs/audit.jsonl`: validation, configuration and engineering audit events;
- `logs/native.jsonl`: Motor-CAD native binding/readback events when emitted;
- `logs/qualification.jsonl`: workstation/native qualification events;
- `logs/plugins.jsonl`: motor-family plugin lifecycle events;
- `logs/traces.jsonl`: timed operation spans.

On Windows PowerShell, live inspection can use:

`Get-Content .\logs\studio.log -Wait -Tail 100`

The Studio API also exposes `/api/logs/export.zip`. The standard validation surface includes a direct “导出当前运行日志” action, so a Motor-CAD precheck failure can be exported before any Result page exists.

Runtime log files are not source artifacts and must not be committed. The repository keeps only `logs/.gitkeep`.

## Automatic startup self-check

On application startup, the Guided runtime page automatically runs the shallow environment check. The visible progress contract is:

1. installation and bound `Motor-CAD.exe` discovery;
2. shallow path/Python/runtime dependency checks without launching Motor-CAD;
3. Windows production qualification and soak evidence status loading;
4. a final ready / warning / blocked summary.

The deep Motor-CAD check remains an explicit engineer action because it launches a Motor-CAD process and may consume a license.

The full-shell browser regression must load the current `index.html` together with every current JavaScript asset. This gate exists to catch DOM/API drift that module-level HMI tests cannot detect.

## AFPM Golden starter baseline rule

The `golden_afpm_ssdr` starter is based on the native `e14_eMobility_AFM` template. Values shown in the Guided create form are template values for reference. A displayed value that the engineer does not change must not be submitted as an explicit override or written back to Motor-CAD. This preserves the coupled native AFPM geometry baseline. Only changed Guided inputs become explicit parameter writes.

After this change, create a new AFPM starter revision for qualification. Revisions created by older builds may already contain redundant explicit writes and should not be used as proof of the corrected baseline behavior.

Final qualification still requires Windows + licensed Motor-CAD 2026R1. If the untouched starter fails native geometry validation, export the current-session logs directly from the validation page and inspect `MODEL_RUNTIME_CHECK`, `motorcad_input.json`, `motorcad_io.jsonl`, `motorcad_output.json`, and the reported `work_dir` before changing geometry values.

## V0.88-F native spatial evidence check

After a representative native Case completes, inspect:

1. `native_model_snapshot_post_solve.json` for a COMPLETE spatial geometry payload;
2. `native_fea/native_fea_manifest.json` for bound native lineage;
3. `native_fea/native_spatial_overlay_contract.json` for `status=QUALIFIED` and coordinate alignment `CONFIRMED`;
4. the Result Workbench Native Spatial Authority card and GeometryTree boundary toggle.

If the overlay is blocked, keep the raw `save_fea_data` evidence. Do not convert a point-only export into an interpolated contour as a workaround. Resolve the reported lineage, GeometryTree or coordinate-alignment blocker and rerun the native Case.
