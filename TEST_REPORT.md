# Current Release Test Report

Release: **MotorCAD Studio 0.88.1 / Schema 44**  
Iteration: **V0.88-A — Native Semantic Binding Authority**  
Target native stack: **Motor-CAD 2026R1 / PyMotorCAD 0.8.8**

## 1. Regression verification

The clean current suite contains **79 tests**: **70 non-E2E** and **9 Chromium HMI E2E**. Non-E2E files were executed in isolated pytest processes because several current FastAPI/TestClient fixtures intentionally own process-level lifecycle state.

- Core API: 2/2 PASS
- MTT parser: 2/2 PASS
- Canonical project-flow UI contract: 5/5 PASS
- Global product control-plane/startup: 2/2 PASS
- Guided Golden Motor Starters: 4/4 PASS
- Engineering semantics + Standard Validation: 5/5 PASS
- Parameter Study + Optimization Decision: 5/5 PASS
- Runtime Lifecycle Qualification contract: 10/10 PASS
- Windows Production Qualification contract: 10/10 PASS
- Production Soak Hardening contract: 8/8 PASS
- V0.88 Engineering Closure regression: 7/7 PASS
- V0.88-A Native Semantic Binding Authority: 10/10 PASS
- **Non-E2E total: 70/70 PASS**

Chromium HMI:

- `pytest -q -m e2e tests/e2e`: **9/9 PASS**

Static/package gates:

- JavaScript `node --check`: **75/75 PASS**
- `python -m compileall -q motorcad_studio scripts tests`: **PASS**
- Pytest collection: **79/79 collected, 0 collection errors**
- Version/schema: **0.88.1 / 44**

## 2. V0.88-A semantic authority evidence

Dedicated regression coverage verifies:

1. live parameter/component names are persisted only after API evidence;
2. a source-qualified exact name replaces historical alias retry lists in write plans;
3. template-inherited material is readback-only and causes zero `set_component_material` calls;
4. explicit material changes write only authority-resolved native component names;
5. model-source fingerprint changes invalidate cached authority;
6. L2/read-only observations cannot become write authority;
7. read-only inspection cannot downgrade an existing L3/write-qualified profile;
8. a readable variable whose same-value write fails remains excluded from write authority;
9. one canonical material can freeze multiple exact native components when the Motor-CAD template requires a one-to-many mapping;
10. the formal Windows qualification contract remains fail-closed when scenario semantic authority/profile hash evidence is missing.

## 3. Windows production qualification integration

The formal Windows matrix is now contract **`0.88-A`**. Every SPM/IPM/AFPM/IM representative scenario requires:

- `native_semantic_binding_qualified = true`;
- a non-empty `native_semantic_binding_profile_hash`;
- native closure/readback/precheck/solver/result/restart/runtime/license/process gates;
- immutable scenario evidence containing the same semantic gate/hash.

The release-gate matrix also requires `native_semantic_authority = true`. The Windows runner was repaired to stop referencing the removed historical `test_v081d_engineering_result_interpretation_baseline.py` file and now includes the V0.88/V0.88-A regression suites.

## 4. Production boundary

This build environment cannot launch the user's licensed Windows Motor-CAD 2026R1 workstation. Therefore the V0.88-A authority mechanism, cache invalidation, planner/executor semantics, Windows qualification contract and HMI/API surfaces are locally verified, while **live L3 semantic profiles remain pending**.

A formal claim requires running on the target workstation:

```powershell
python scripts\qualify_native_semantic_bindings.py --fail-on-partial --visible
```

or completing Native Closure for the representative profiles. Production qualification and 100/500 native soak remain fail-closed until the resulting live evidence is imported.
