# Production Qualification

The current release uses three separate gates. They must not be conflated.

## 1. Runtime lifecycle qualification

Checks deterministic startup/shutdown, Task/Case threads, scheduler leases, persistent-worker ownership, SQLite handles and residual Motor-CAD child processes. A dirty shutdown remains fail-visible.

## 2. Windows Motor-CAD production qualification

Formal PASS requires a real Windows workstation with licensed Motor-CAD 2026R1 and the supported PyMotorCAD version.

Required representative scenarios:

- SPM
- IPM
- AFPM
- IM

Each scenario must satisfy V0.88-A native semantic binding authority, native binding/readback, native precheck, solver, result extraction/integrity, restart/reopen, license evidence and clean process exit. The semantic profile must be source-compatible, `QUALIFIED`, and hash-frozen into scenario evidence. The fixed fault/recovery matrix contains 17 required evidence rows.

Before or during the formal run, semantic authority can be qualified explicitly with:

```powershell
python scripts\qualify_native_semantic_bindings.py --fail-on-partial --visible
```

Native Closure performs the same write-safe semantic qualification automatically. The formal Windows matrix is contract `0.88-A` and will remain fail-closed when any representative scenario lacks semantic-profile evidence.

Run:

```powershell
.\run_windows_production_qualification.ps1
```

## 3. Production soak

Formal production hardening requires native Motor-CAD campaigns of:

- 100/100 Cases
- 500/500 Cases

The gate verifies ResultBundle integrity, RSS/memory growth, worker recycle, SQLite/thread/process ownership, clean shutdown and recovery probes (Cancel→Retry, Worker Crash→Recovery, Studio Restart→Reopen, qualification retention).

Run:

```powershell
.\run_production_soak.ps1
```

Local control-plane soak is useful for Studio stability but cannot promote formal Windows/native qualification.
