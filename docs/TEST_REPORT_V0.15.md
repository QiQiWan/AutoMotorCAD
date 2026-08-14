# V0.15 Test Report

## Automated regression

```text
79 passed in 21.68s
```

The suite covers prior V0.2–V0.14 contracts plus V0.15 geometry/observability/result-comparison behavior.

### New V0.15 coverage

- explicit impossible Slot Opening is blocked by Studio geometry guard;
- suspicious untouched template default is downgraded to Warning;
- geometry precheck API and operator controls exist;
- log boot sessions separate current and historical records;
- log API current-session filtering;
- 2-Case Result Viewer comparison contract;
- client-contract feature flags;
- Mock Task no longer depends on external SolverProcessRunner;
- installation API exposes target version/match contract.

### Reliability regression

During development, the complete suite reproduced a long-run multiprocessing lifecycle defect: many short spawned Mock Cases accumulated Queue semaphore resources and the final NSGA-II test could take minutes or never finish cleanly. Solver IPC was changed from Queue to Pipe and Mock Task execution was moved in-process. The final complete suite exits normally.

## Static checks

Final delivery must pass:

```text
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
node --check motorcad_studio/static/production.js
node --check motorcad_studio/static/geometry.js
node --check motorcad_studio/static/realtime.js
node --check motorcad_studio/static/i18n.js
node --check motorcad_studio/static/locale-data.js
```

## Important boundary

No real Motor-CAD/engineering licence is available in the delivery container. The tests validate Studio software behavior, fake Motor-CAD API contracts and Mock workflows. Real e14/i5/e9 qualification remains a Windows workstation acceptance activity.
