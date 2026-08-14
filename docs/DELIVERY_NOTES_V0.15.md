# V0.15 Delivery Notes

## Upgrade

Use the complete V0.15 directory. Do not copy only Python files or only `static/`, because the frontend/backend client contract and cache-busting version must remain aligned.

After launch verify:

```text
frontend = 0.15.0
backend  = 0.15.0
```

## First target-workstation acceptance

1. bind or browse to the intended Motor-CAD.exe;
2. confirm the selected EXE version matches the Studio target mapping version;
3. run deep preflight;
4. run e14 Studio geometry precheck with no user edits;
5. run e14 Motor-CAD geometry check;
6. run one real EMag Case;
7. compare parameter readback and Motor-CAD GUI baseline;
8. repeat for e9 and i5;
9. only after baseline qualification start 20/100/500 Case jobs.

## If a geometry failure occurs

Export the Task diagnostic bundle and include at least:

- `model_validation.json`;
- `parameter_audit.json`;
- `runtime_defaults.json`;
- `solver_runtime.jsonl`;
- central logs for the current boot session.

Do not paste only the final Python traceback; V0.15 records structured geometry context specifically to avoid losing the engineering cause inside RPC stack traces.

## Delivery hygiene

The release package must not contain development SQLite databases, generated Task results, test datasets or runtime logs. Runtime directories are recreated/populated after first launch.
