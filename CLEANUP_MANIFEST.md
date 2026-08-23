# Clean Release Manifest

This package is intentionally **latest-only**.

Removed from the shipped source tree:

- historical `TEST_REPORT_V*` files;
- historical `V0.*_IMPLEMENTATION_AND_NEXT` files;
- old roadmap/completion/iteration documents;
- `docs/archive/` static-history snapshots;
- `docs/sample_output/` generated examples;
- obsolete V0.68/V0.73/V0.75/V0.78/V0.82 Windows runners;
- old `verify_v*` and pre-current acceptance helper scripts;
- `tests/history/` and pre-current version-contract test files;
- obsolete packaged V0.82 fault-matrix template;
- Python cache/compiled artifacts.

Retained because they are part of the current product/runtime contract:

- all active application/domain/runtime modules under `motorcad_studio/`;
- active current configuration and supplied model data;
- SPM/IPM/AFPM Golden Starter and current semantic/analysis/result/optimization authorities;
- current Windows Production Qualification and Production Soak authorities;
- compact current-release core/product/qualification tests;
- evergreen architecture, Motor-CAD onboarding and official mapping documentation.

Historical version identifiers may still appear **inside authority contract metadata** (for example a contract version such as `0.87-F-C`). Those values are provenance/schema identifiers and are intentionally preserved; they are not duplicate runtime implementations.
Current-release regression policy:

- every release gate must load the complete current shell with all current JavaScript assets;
- retired DOM removal must be accompanied by bootstrap-listener cleanup;
- current product smoke tests must exercise Project → Design → Validate → Decide at the API/control-plane level.

