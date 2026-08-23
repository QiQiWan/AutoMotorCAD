# MotorCAD Studio changelog

## 0.88.1 — V0.88-A Native Semantic Binding Authority

- Added source-scoped `NativeSemanticBindingAuthority` profiles for exact Motor-CAD variable and material-component names.
- Promoted a name to write authority only after live read -> idempotent same-value write -> readback verification.
- Added model-source fingerprint invalidation and native binding contract `motorcad-2026R1-v2`.
- Kept read-only observations from downgrading an existing write-qualified profile.
- Added one-to-many material semantic support, so one Studio component can freeze multiple exact native Motor-CAD material components when required by the loaded template.
- Made template-inherited material binding readback-only in the canonical executor; explicit material changes use only authority-resolved native component names after qualification.
- Native Closure now bootstraps semantic authority immediately after model load, freezes the profile as evidence and rebuilds the BindingPlan in the same run.
- Validation/production normal solves fail closed when the active template lacks a source-compatible `QUALIFIED` semantic profile; development mode keeps reviewed candidate fallback for diagnosis.
- Integrated semantic authority into the formal Windows production matrix: every representative native scenario must carry `native_semantic_binding_qualified` plus a frozen semantic-profile hash, and the release gate now requires semantic authority.
- Repaired the current Windows production runner so it no longer references a removed historical baseline test.
- Added semantic-authority API/UI status, a standalone Windows qualification runner, operator documentation and 10 dedicated V0.88-A regression tests.

## 0.88.0 — Engineering Closure

- Repaired the undefined workflow-readiness helper and stale DOM boot listeners.
- Rebuilt the RFPM longitudinal r-z engineering preview and winding fill behaviour.
- Converged design-save/return interaction, winding marker legend, material assignment UX and resizable material-library dialog.
- Added magnet material engineering curves with explicit raw/derived provenance.
- Preserved material provenance through the design model and introduced actionable native validation fault stages.
- Corrected the field diagnostic where a template-inherited conductor material was being rewritten through an invalid generic component alias.

## 0.87.9 — Interaction Integrity & Automatic Self-check Progress

- Fixed whole-shell startup crashes caused by legacy task-form DOM listeners after clean-source consolidation.
- Delayed Engineer Journey refresh until active project context validation; stale project IDs self-invalidate without noisy UI failures.
- Added automatic shallow environment self-check progress with explicit 0–100% stage feedback; deep Motor-CAD process validation remains manual.
- Added full-shell browser simulation using the current `index.html` and all JavaScript assets, plus a product control-plane smoke chain across Design -> Validate -> Decide.
