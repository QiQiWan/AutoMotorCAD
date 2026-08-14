# V0.12 Test Report

## Automated regression

Command:

```bash
PYTHONPATH=. pytest -q
```

Final result:

```text
53 passed
```

## V0.12-specific coverage

The new production-UX suite verifies:

1. project soft delete moves a Project to Trash;
2. Task `project_id` lineage remains intact after trashing;
3. Project restore returns the same engineering object to ACTIVE state;
4. `realtime.js`, user modes, Trash and qualification UI are wired into the application;
5. material catalog validation does not falsely claim Motor-CAD database verification;
6. reviewed Automation parameter metadata is applied while unknown native parameters remain unreviewed;
7. the template Qualification API contract can return Level/check results;
8. diagnostic bundles contain `environment.json` and `diagnostics.json`.

The complete legacy suite continues to cover Task/Case execution, database recovery, cache, checkpointing, DOE/NSGA-II, Data Factory, Result Viewer, observability and operator UX.

## Static validation

```text
python -m compileall -q motorcad_studio scripts tests   PASS
node --check motorcad_studio/static/app.js             PASS
node --check motorcad_studio/static/realtime.js        PASS
node --check motorcad_studio/static/i18n.js            PASS
```

## Important limitation

The current CI/container environment does not contain a licensed Motor-CAD installation. Therefore automated tests validate the qualification control path and failure isolation, but do not validate real RPC/FEA/Lab physics. Level-4 qualification must be run on the target Windows workstation.
