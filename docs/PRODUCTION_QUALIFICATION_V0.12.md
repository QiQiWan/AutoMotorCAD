# V0.12 Production Qualification Guide

## Purpose

Qualification answers a stronger question than “Can Motor-CAD start?”:

> Can this exact Motor-CAD version, template, parameter/material mapping and analysis recipe be executed and read back reliably on this workstation?

## Recommended acceptance sequence

### Level 0 — host environment

Verify Windows, Python, PyMotorCAD import, writable runtime/results/log directories and sufficient disk space.

### Level 1 — Motor-CAD runtime

Verify target executable selection, Motor-CAD process creation, RPC connection, message API and clean shutdown.

### Level 2 — template model

For each curated template (`i5`, `e9`, `e14` initially):

- require or prepare a verified local `.mot` master;
- load the model in an isolated instance;
- switch required contexts;
- record actual Motor-CAD version and model hash.

### Level 3 — engineering mapping

Verify:

- all required canonical inputs resolve to real Automation variables;
- unit conversion is correct;
- write/readback matches requested values;
- component materials exist in the selected Motor-CAD database and read back correctly;
- geometry validation passes;
- no unexpected Motor-CAD warning/error message is produced.

Store the complete parameter/material audit as the qualification evidence.

### Level 4 — solver smoke

Run a low-cost real calculation and extract at least one trusted result:

- EMag: magnetic calculation + `ShaftTorque` readback;
- steady thermal: steady-state solve + selected temperature result;
- Lab/Mechanical should receive dedicated smoke recipes before being marked qualified.

A licence API returning no exception is not sufficient. A module becomes `QUALIFIED` only after a real calculation successfully checks out the required capability and returns a plausible result.

## Template production record

A future persistent qualification record should contain:

```text
template_id
motorcad_version
studio_version
mot_sha256
mapping_hash
material_database
qualification_level
qualified_analyses
parameter_roundtrip_summary
material_roundtrip_summary
geometry_status
baseline_case
completed_at
```

V0.12 returns the qualification result through the API/UI. Persisting signed/approved qualification records is a recommended next step before declaring a template Production Ready.

## Minimum real-workstation gate before V1.0

For `i5`, `e9`, and `e14`:

1. Level-4 EMag qualification;
2. Level-4 thermal qualification where supported;
3. manual GUI baseline comparison;
4. no required parameter mapping failures;
5. no material mapping ambiguity;
6. at least 20 repeated cases without orphan Motor-CAD processes;
7. at least one interruption/recovery test;
8. then 100-case stability per primary template.
