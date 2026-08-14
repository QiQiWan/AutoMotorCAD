# V0.9 Test Report

## Commands

```bash
PYTHONPATH=. pytest -q
node --check motorcad_studio/static/app.js
python -m compileall -q motorcad_studio scripts tests
```

## Result

```text
39 passed
```

The complete test suite exits normally.

## V0.9-specific coverage

New tests validate:

- Project -> Design -> DesignRevision chain;
- Project -> Scenario -> ScenarioRevision chain;
- derived metrics;
- constraint violation calculation;
- NSGA-II multi-generation dynamic Case creation;
- optimizer run persistence;
- Data Factory automatic ingestion;
- quality report row counts;
- immutable Dataset Version creation;
- deterministic partition generation;
- CSV download;
- Quarantine download;
- creation of a later version without overwriting the first.

## Static validation

- Python compileall: passed.
- Browser JavaScript syntax check: passed.

## Physical validation boundary

The suite validates software behavior with MockSolver and test doubles. It does not validate real Motor-CAD physics, licences, RPC stability or output equivalence because Motor-CAD is unavailable in the current environment.
