# V0.14 Test Report

Final clean regression result:

```text
70 passed
```

V0.14-specific tests cover the client compatibility contract, required material/result-viewer routes, unified result navigation, Project delete controls, persistent manual Motor-CAD executable selection, explicit parameter intent, safe geometry auto-recovery and blocking of silent changes to user-specified geometry.

Static verification also includes Python `compileall` plus Node syntax checking for the production frontend modules.

Real Motor-CAD physics remains a workstation qualification boundary: these tests do not substitute for the i5/e9/e14 Level-4 runs on the licensed Windows target.
