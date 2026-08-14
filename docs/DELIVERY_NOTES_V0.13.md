# V0.13 Delivery Notes

V0.13 focuses on production evidence and target-workstation calibration rather than AI or broad new features.

Key additions:

- persistent qualification records and matrix;
- validation/production qualification gating;
- persistent material readback bindings;
- result graph probe/calibration registry;
- calibration-aware Solver extraction and cache fingerprint;
- diagnostic-bundle evidence;
- frontend production module split;
- Result Viewer mesh/vector field contracts.

The delivery archive is intentionally clean. Runtime SQLite databases, logs, Task results, calibration records and datasets are not pre-populated; they are generated on the target workstation.
