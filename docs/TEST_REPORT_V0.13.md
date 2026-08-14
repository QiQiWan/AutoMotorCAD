# V0.13 Test Report

## Automated regression

Final command:

```text
PYTHONPATH=. pytest -q
```

Final result:

```text
64 passed
```

The V0.13-specific tests cover:

- qualification evidence persistence;
- qualification matrix;
- material binding persistence from set/get evidence;
- recommended result probes from versioned output registry;
- result probe persistence;
- calibrated graph priority in Solver Registry;
- calibration participation in Simulation Fingerprint;
- diagnostic bundle calibration evidence;
- documented three-array harmonic probe contract;
- Result Viewer mesh/vector result-type contracts;
- frontend production module and calibration controls.

## Static checks

- `python -m compileall -q motorcad_studio scripts tests`
- `node --check motorcad_studio/static/app.js`
- `node --check motorcad_studio/static/production.js`
- `node --check motorcad_studio/static/realtime.js`
- `node --check motorcad_studio/static/i18n.js`
- `node --check motorcad_studio/static/locale-data.js`

## Boundary

These tests validate Studio behavior without a licensed Motor-CAD instance. They do not qualify real i5/e9/e14 physics or prove target-workstation graph/material names.
