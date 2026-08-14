# V0.9 Delivery Notes

## Delivered

- V0.9 source package.
- Engineering object/revision backend.
- Adaptive constrained multi-objective optimizer.
- Simulation Data Factory.
- Data Factory GUI.
- Versioned dataset registry.
- Quality/quarantine reports.
- Optional Parquet dependency file.
- Mock adaptive-optimization and dataset-manifest samples.

## Clean delivery policy

Delivery directories contain no runtime SQLite database, Task results or generated production datasets. `data/factory` ships empty except directory placeholders. Examples are stored only under `docs/sample_output`.

## First real-machine workflow

1. Run Motor-CAD onboarding.
2. Validate i5/e9/e14 Automation mappings.
3. Run controlled single-case baselines.
4. Run real DOE batches.
5. Inspect Data Factory quality reports.
6. Build first real-solver dataset version with `include_mock=false`.
7. Freeze the manifest externally for research reproducibility.
