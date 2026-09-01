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


## V0.88-F native spatial evidence check

After a representative native Case completes, inspect:

1. `native_model_snapshot_post_solve.json` for a COMPLETE spatial geometry payload;
2. `native_fea/native_fea_manifest.json` for bound native lineage;
3. `native_fea/native_spatial_overlay_contract.json` for `status=QUALIFIED` and coordinate alignment `CONFIRMED`;
4. the Result Workbench Native Spatial Authority card and GeometryTree boundary toggle.

If the overlay is blocked, keep the raw `save_fea_data` evidence. Do not convert a point-only export into an interpolated contour as a workaround. Resolve the reported lineage, GeometryTree or coordinate-alignment blocker and rerun the native Case.
