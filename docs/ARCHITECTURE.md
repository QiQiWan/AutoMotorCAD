# MotorCAD Studio Architecture

Current release: **0.87.9 / Schema 44**.

## Product workflow

The engineer-facing workflow is **Design → Validate → Decide**. Internal domain objects remain richer than the visible navigation so that engineering lineage, replay and qualification stay deterministic.

## Domain layers

### Design

- Project / Solution
- immutable Motor Design Revision
- Golden Motor Design Starter (SPM / IPM / AFPM)
- canonical parameter registry and engineering parameter semantics
- materials, winding and geometry projections
- Studio precheck and native binding/precheck

### Analysis

- Analysis Definition / immutable Analysis Revision
- Analysis Template and Recipe
- Standard Validation Package
- operating-point/scenario definitions
- execution plan and task/case lifecycle

### Results

- ResultBundle as the authoritative single-case result object
- ResultSet / comparison aggregates
- scalar, series, spectrum, map, field, vector, table and artifact result types
- provenance, quality, trust and comparability fingerprint
- Engineering Scorecard and requirement evaluation

### Optimization

- parameter study / full-factorial sweep
- NSGA-II / Pareto candidate sets
- Local / Morris / Sobol sensitivity
- convergence, response surface, parallel coordinates and Candidate Inspector
- candidate validation and immutable promotion to a new Design Revision

## Runtime

Motor-CAD execution is isolated behind runtime ownership boundaries:

- RuntimeResourceScheduler
- persistent or isolated Motor-CAD workers
- license capacity controls
- child-process isolation and cancellation
- SQLite lifecycle accounting
- graceful shutdown and runtime lifecycle qualification

## Production qualification

Three gates are intentionally separate:

1. local Runtime Lifecycle Qualification;
2. formal Windows + licensed Motor-CAD production qualification (SPM/IPM/AFPM/IM + 17 fault/recovery rows);
3. formal 100/500 native Case production soak.

Local/CI evidence cannot promote the formal Windows/native gates.

## Source authorities

- `motorcad_studio/config/` — single canonical configuration source.
- `motorcad_studio/seed_data/` — single canonical template/inventory seed source.
- `data/` — runtime working data materialized on first source launch; not a second source authority.
- `motorcad_studio/static/` — current active UI only; historical static snapshots are not shipped.
