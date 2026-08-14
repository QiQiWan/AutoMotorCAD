# Changelog

## 0.35.0

- 将 Motor-CAD `winding_pattern.txt` 从普通附件升级为可降级解析的 `winding_definition.json`，记录线圈槽对、相别、匝数、支路、原生校验、源文件 SHA-256 与字段证据状态。
- 绕组视图在存在结构化原生证据时绘制实际进/回槽关系；尚无证据时保持参数示意并明确显示其权限层级。
- 新增后端热网络证据合同和 `/api/cases/{case_id}/thermal-network`；原生热节点/热阻与标量温度摘要采用不同 authority 和 completeness。
- FEA normalizer 保留区域、字段、元素/节点编号元数据；结果页支持多步回放、字段/区域筛选、全范围/分位/手动色标、最近原生点探测及原始 CSV 下载。
- 新增 `/api/cases/{case_id}/fea-probe`；缺少完整节点坐标与连接时关闭真实网格、连续云图和等值线能力，避免伪造物理场。
- Case 对比升级为 Schema 2，增加设计/工况/求解三域变化、目标方向、Pareto 非支配解、改善/退化、质量门禁、完整追溯和描述性影响。
- 新增 V0.35 决策工作台、证据能力提示与响应式样式。
- 全量 241 项测试通过；Python compileall 与前端 JavaScript 静态语法检查通过。

## 0.31.0

- 将 Design Revision 的主视觉升级为径向截面、轴向截面、绕组排布、槽内定义、材料、原生证据和版本对比七个领域视图。
- 新增服务端 `design_views` 视图—参数契约；不同模板只暴露自身实际支持的参数，轴向磁通模板自动优先轴向视图。
- 新增结构化 `winding_design` 摘要，覆盖相数、匝数、并联支路、槽满率、槽/相/支路整数关系与模板来源。
- 明确线径、铜径、并绕根数、槽衬、线圈分隔、导体间距和绕组因数的原生证据边界；未回读时不提供伪编辑值。
- 设计首页与 Motor Model Workbench 复用同一组参数化 SVG，参数选择、区域高亮与当前视图编辑入口保持一致。
- 工程模式收敛为四阶段状态条，统一表达 completed/current/pending/blocked/running，并下沉项目概览和数据资产入口。
- 新增热结果整体拓扑视图；原生热网络表存在时显示真实节点与连接，否则显示带显著证据说明的工程热路径摘要。
- 新增原生 FEA 场控制台，支持场选择、自动或 2–98% 分位色标、图例、外框、网格和矢量；缺少原生节点/单元/场值时不生成替代云图。
- 兼容 FEA 单元的 0/1 起始节点编号；原生热网络缺少画布坐标时自动布局，节点与边仍保留原生数据来源。
- 修复受限 PID namespace 中 `psutil` 暂时无法读取新子进程 create-time 时误伤 Solver Case 的问题；身份时间证据降级为空，不影响求解生命周期。
- 新增 V0.31 视觉工作流与证据边界回归测试，并更新历史版本静态资产契约；全量 234 项测试通过，Python compileall 与前端 JavaScript syntax check 通过。

## 0.30.0

- 新增工程师四步持续流程：设计电机 → 设置分析 → 计算模型 → 分析结果。
- 新增统一 UI 词汇配置 `config/ui_terms.yaml` 与 `UIGuidanceService`。
- 新增 `/api/ui/lexicon` 和 `/api/projects/{project_id}/ui-guidance`。
- 默认 UI 收敛为 READY / NEEDS_CHECK / BLOCKED / RUNNING / COMPLETED 五种用户状态。
- Engineering 模式将仿真五步 Wizard 收敛为单页连续配置；Guided 模式仍保留逐步向导。
- 新增动态单一主操作，根据当前状态显示“选择电机 / 检查 / 修复 / 开始计算”。
- 错误提示统一为“发生了什么 / 为什么 / 影响 / 怎么处理”，技术代码折叠。
- Worker Pool、资源租约、Execution Lease 等技术信息默认下沉到高级视角。
- 运行环境将 Worker/资源调度收进高级折叠区。
- 结果页新增工程结果摘要和关键性能卡。
- 统一默认工程词汇：电机方案、设计版本、运行工况、计算记录、计算算例等。
- 回归测试：230 passed；Python compileall 与全部前端 JS syntax check 通过。

## 0.29.0

- Reframed the project shell around an engineer mental model: `Overview → Model → Simulation → Results → Data`. Live solve/monitor is now a secondary Simulation destination rather than a separate primary stage.
- Promoted Engineering mode to the default workspace for new/upgraded V0.29 browsers; the previous Operator experience remains available as Guided mode.
- Added a persistent engineering context strip showing the current model revision, scenario/operating point, analysis, Motor-CAD readiness, and active task across project pages.
- Added a sticky Simulation Run Summary for Engineering/Expert/Developer modes with direct step navigation, model/scenario/analysis/method/Case/output context, current gate state, and direct repair/model/review actions.
- Remembered output selections per project and analysis so engineers do not repeatedly reselect the same result set. Required outputs remain enforced; “recommended outputs” can still reset the preference.
- Added five-minute model-fingerprint caching for optional independent Motor-CAD geometry/winding checks. Rechecking the identical snapshot reuses native evidence; a dedicated “force recheck” action bypasses the cache.
- Reduced route waterfalls: route-owned project activation no longer triggers legacy cross-page task/readiness refreshes, and project overview reuses its already-fetched workflow-readiness payload instead of issuing a duplicate request.
- Kept task-time Execution Lease validation authoritative. Independent Motor-CAD checks remain diagnostic evidence and no longer need to be repeatedly launched while an engineer iterates on an unchanged invalid model.
- Added V0.29 engineer-flow regression tests. Split regression runs cover 224 tests (64 + 100 + 38 + 22), all passing; Python compileall and all 21 frontend JavaScript files pass syntax checks. Local Chromium E2E navigation is blocked by the current container administrator policy and remains a Windows/CI acceptance item.

## 0.28.0

- Fixed the Design Revision first-frame hydration defect: Task Builder and Motor Model Workbench now render the quick geometry preview from the immutable Revision effective snapshot immediately, without waiting for the first input event.
- Rebased parameter-field defaults after Revision hydration so change badges and Task override counts are relative to the selected Design Revision rather than the template defaults.
- Added canonical Workbench `effective_parameters`, `preview_signature`, and `preview_source` evidence.
- Removed the independent deep Motor-CAD preflight from the normal `/api/tasks` hard gate. Daily submission now performs non-launching static runtime admission; authoritative Motor-CAD parameter readback + native Geometry/Winding validation happens in the Task Execution Lease and flows directly into Full Solve in the same Worker/Session.
- Added `/api/runtime/submission-readiness` and a six-stage operator execution-flow visualization covering Design snapshot, fast checks, runtime admission, resource lease, Motor-CAD native validation, and solve/result.
- Preserved independent deep Motor-CAD preflight as an explicit Runtime diagnostic and optional calculation-page check.
- Added a narrowly scoped one-time isolated-process fallback for persistent-worker transport/process failures. Engineering/model/license/capability failures are never hidden by this fallback.
- Motor-CAD installation changes now refresh the calculation submission-readiness state immediately.
- V0.28 includes the V0.27 atomic Worker/licence/memory resource scheduler, effective executable authority, worker capability handshake, and Runtime Contract evidence.
- Added V0.28 regression coverage. 214 test cases complete successfully in the current Linux environment; a legacy suite-teardown wait remains tracked for the next reliability iteration. V0.28-specific tests: 8 passed. Python compileall and all JavaScript syntax checks pass.

## 0.27.0

- Added an atomic Motor-CAD runtime resource scheduler. A real Case now obtains Worker capacity, Studio-declared local licence capacity, and memory headroom as one resource lease, preventing a Case from holding a licence slot while waiting for a Worker or vice versa.
- Added `runtime_resource_lease_id` / `resource_wait_ms` Case evidence, runtime queue/blocking-reason telemetry, effective concurrency calculation, and a routed operator panel for Worker/licence/memory admission.
- Preserved Motor-CAD native licence checkout as the authority. Studio licence capacities are admission limits only; every real solver context still calls PyMotorCAD `get_licence()` before calculation.
- Fixed a high-impact executable-authority bug: a manually selected `Motor-CAD.exe` persisted by the UI could previously differ from the immutable startup `settings.motorcad_exe` still used by some Task/preflight/worker paths. V0.27 centralizes the effective executable in `TaskManager`, propagates it to all new workers/preflights/support scripts, and recycles persistent workers when the selected installation changes.
- Added persistent-worker capability handshake evidence without intentionally launching Motor-CAD: Python/PyMotorCAD availability and version, configured executable existence/fingerprint, target/selected Motor-CAD version compatibility, blackbox flag, and installation identity. Incompatible started workers are excluded from real Case allocation.
- Added an observational runtime contract registry that accumulates real Case reuse evidence by Worker generation/analysis, records clean success streaks and RSS high-water marks, recommends a Case memory reservation, expires stale evidence, and rotates evidence when the effective Motor-CAD executable/environment changes.
- Added `scripts/run_motorcad_runtime_contract.py` for explicit Windows endurance campaigns using PyMotorCAD reuse/free semantics. The runner requires `--confirm-license-use` because native licence checkout is real; it can optionally solve, post a machine-readable report to Studio, or commit locally while Studio is stopped. This campaign was not executed in the Linux development environment.
- Fixed runtime alert flapping by assigning stable alert identities and hysteresis thresholds. Small memory changes around the warning threshold no longer emit alternating alert/resolved records for every sample.
- Added Schema 17 fields/indexes for runtime resource evidence, runtime readiness/contract/capability-probe APIs, diagnostic-bundle scheduler/contract snapshots, and frontend Case resource-wait evidence.
- Added V0.27 regression coverage. Full suite: 206 tests passing, plus Python compileall and all JavaScript syntax checks.

## 0.26.0

- Added a lazy Persistent Motor-CAD Worker Pool. Each worker is a long-lived Python process and serially owns one Case at a time; Motor-CAD itself is launched only when the worker receives its first real Case.
- Enabled official PyMotorCAD instance reuse/free semantics only behind the persistent owner boundary; successful reusable Cases call `set_free()`, while cancel/timeout/solver exception kills and recreates the complete worker process tree.
- Added per-Case Validate-and-Run execution leases. Model load, parameter readback, material application, native Geometry/Winding validation and the subsequent Full Solve occur inside the same worker/session.
- Added a canonical-reset contract: every Case clears the native message log and reloads the canonical local MOT / registered template before applying Case intent, avoiding cross-Case model-state carryover.
- Validation Evidence Hash now binds Run Configuration, Case input, actual model source, runtime defaults, parameter readback, material audit, native validation and analysis.
- Added worker generation identity, jobs/RSS/restart tracking and automatic recycle by job count or memory threshold. Motor-CAD installation changes invalidate/recycle existing workers.
- Added Schema 16 Case fields for `motorcad_worker_id`, `execution_lease_id` and `validation_evidence_hash`.
- Added runtime APIs and UI for worker-pool observability, safe idle-worker recycle, and live Case execution-lease evidence.
- Clarified the UI boundary between advisory pre-submit Motor-CAD checks and authoritative Task-time Validate-and-Run evidence.
- Added V0.26 regression coverage. Full suite: 199 tests passing, plus Python compileall and all JavaScript syntax checks.

## 0.25.0

- 前端切换为 Route-first 页面生命周期：每次路由过渡创建独立 `AbortController`，页面拥有 disposer、作用域 interval/timeout/listener，过期请求不会继续覆盖新页面。
- `router.js` 删除基于固定 `setTimeout` 的 Design / Revision / Task / Case 恢复逻辑，URL 成为工程对象导航的唯一入口。
- Project、Design Revision Workbench、Simulation Setup、Task、Monitor、Result 等高频页面增加 route-owned controller；Monitor 与日志实时通道在离开页面时自动释放。
- 新增非阻塞路由加载状态条；快速切换 Project/Design/Task 时旧请求自动 abort。
- Task 提交新增持久 `submission_key` + `submission_hash`，相同提交在响应丢失/网络重试时返回原 Task，避免重复生成 Run Configuration / Experiment / Task；修改后的配置复用同一 key 会返回 409。
- Schema 升级到 15，`tasks` 新增 `submission_key` / `submission_hash` 和唯一索引。
- 新增浏览器前端可观测性：路由失败、未捕获异常、未处理 Promise 与超过 2 s 的慢路由写入中央结构化日志，并在问题中心归为 `FRONTEND`。
- 进入项目、Task/Case 深链、项目设置等跳转不再先执行旧页面预加载再更新 URL，减少重复 API 请求和异步竞态。
- 完整回归测试扩展至 191 项。

## 0.24.0

- Replaced the ordinary Design Revision form as the primary edit path with a three-column Motor Model Workbench: parameter/Region navigation, live geometry/winding/native-evidence views, grouped parameter editing, and field-level constraint/evidence guidance.
- Added `ModelWorkbenchService` plus `/api/design-revisions/{id}/workbench` and `/workbench/precheck` APIs. The service exposes parameter dependency metadata, Motor-CAD automation candidates, previous-feasible baselines, native Case evidence, issue-to-field bindings, and repair actions.
- Added a configurable parameter dependency/Region/issue graph in `config/model_workbench.yaml`; deterministic model errors can now locate the relevant parameters and restore previous feasible/template values.
- Added Motor-CAD winding-pattern evidence export with `save_winding_pattern()`. The actual `winding_pattern.txt` is registered as a Case artifact and is explicitly separated from Studio's explanatory winding diagram.
- Generalized Motor-CAD geometry error parsing for `Regions "A" and "B" intersect`, including CoilDivider/Liner-style failures, and mapped generic region intersections plus FEA-aborted-by-winding consequences back to engineering fields.
- Upgraded the in-page Dialog action contract with value extraction before close, keeping Revision notes and destructive/confirmation flows non-blocking and browser-dialog free.
- Updated deep-link edit routing to prefer the V0.24 workbench and loaded the Router after all versioned feature extensions so route wrappers see the latest page functions.
- Added V0.24 regression coverage. Full suite: 183 tests passing, plus Python compileall and JavaScript syntax checks.

## 0.23.0

- Added best-effort Motor-CAD native FEA evidence export using the PyMotorCAD `save_fea_data()` contract. Each eligible EMag Case can retain the raw export, SHA-256 provenance, step-range attempts, X/Y-based normalized browser frames, field ranges, and source-MOT hash without converting an otherwise successful solve into a failure when FEA export is unavailable.
- Added a tolerant native FEA normalizer with explicit RAW_ONLY fallback. It recognizes coordinate/region/step fields, supports direct B or Bx/By magnitude reconstruction, and never synthesizes physical field data when the Motor-CAD export schema cannot be interpreted.
- Upgraded Live Monitor to three explicit visualization modes: real Task/Case process animation, Motor-CAD native FEA evidence playback, and Motor-CAD result-curve playback. Added B/Pt field selection, step slider, play/pause, global evidence-derived scale, and raw-evidence status.
- Added secure Case FEA APIs for evidence manifest, normalized frame, and raw export download. Evidence paths are constrained to the configured results root.
- Added Motor-CAD Session Supervisor V1 and schema version 14. Real solver Cases now persist Studio ownership, worker/Motor-CAD PID evidence, versions, state transitions, RSS peak, release status, and session manifest. Monitoring can distinguish Studio-owned released processes from unowned user processes.
- Corrected instance reuse semantics for the existing per-Case multiprocessing architecture. A short-lived Case child now records a reuse request but forces `reuse_effective=false` and cold release, logging `MOTORCAD_REUSE_DEFERRED` when requested. Cross-Case hot reuse is deferred until a persistent Python worker owns the PyMotorCAD object.
- Added V0.23 regression coverage. Full suite: 176 tests passing, plus Python compileall and JavaScript syntax checks.

## 0.22.0

- Reorganized the operator surface around a continuous Motor-CAD-like engineering flow: Overview -> Model -> Calculation -> Solve Process -> Results -> Data. Scenario/Solver/Output/Run Configuration remain versioned underneath and move out of the normal operator navigation.
- Upgraded parameter editing to use live geometry driven by current parameter values, component highlighting, and parameter-dependency guidance instead of a template-only static schematic.
- Added a solver-process visualization to Live Monitor. During execution it animates the exact Case topology and real Task stage/progress; after completion it automatically switches to Motor-CAD-result-driven playback when TorqueVW and B Gap graph series are available. The UI explicitly distinguishes process animation from physical FEA field evidence.
- Added common default output selection. Torque, torque ripple, efficiency, line voltage, shaft power, total/magnet loss, winding temperatures, torque-angle and air-gap flux curves are selected by default for applicable analyses; currently uncalibrated direct copper/stator-iron loss variables remain opt-in.
- Added Motor-CAD graph extraction and derived-result fallbacks: shaft power is derived from validated torque and speed, while torque ripple is derived from the extracted TorqueVW curve, eliminating known 2026R1 direct-variable probe noise.
- Removed the invalid steady-state `Initial_Temperature` write attempt; initial temperature is applied only to transient thermal recipes. Scenario operating-point fields are now included in the actual Motor-CAD write intent, closing a V0.21 traceability/execution mismatch.
- Fixed concurrent immutable-revision allocation for Design, Scenario, Solver Profile and Output Profile with transaction-scoped MAX(revision)+INSERT, addressing the observed UNIQUE-constraint failure. Added frontend submit locks for Solver/Output profiles and Task submission.
- Debounced/deduplicated model prechecks with AbortController and shared in-flight promises, and stopped stale Task/Project routes before repeated 404 request storms.
- Made empty Output Profiles explicit at Run Configuration freeze time and backward-compatible on replay; the immutable hash now records the actual V0.22 default output IDs rather than an ambiguous empty list.
- Successful real Motor-CAD Task/Case execution now promotes template/analysis capability to reusable Level-4 workstation qualification evidence. Optional result-extraction warnings do not invalidate solver capability; verified-MOT provenance remains a separate production gate.
- Added V0.22 regression coverage. Full suite: 167 tests passing, plus Python compileall and JavaScript syntax checks.

## 0.21.0

- Split the engineering domain into durable Design Revision, operating/environment Scenario Revision, versioned Solver Profile Revision, and versioned Output Profile Revision.
- Removed operating-point fields from newly created Design Revisions and moved speed/current/DC-voltage/phase-angle ownership into Scenario. Legacy immutable revisions are preserved and surfaced by a project domain-integrity audit.
- Added immutable Run Configuration snapshots with content hashes, explicit baseline bindings, runtime override deltas, traceability status, and snapshot schema version.
- Tasks now automatically freeze a Run Configuration before execution; Task detail and Data Factory lineage preserve the Run Configuration and Solver/Output profile revision references.
- Added exact Run Configuration replay and rejected attempts to attach a Run Configuration ID to different effective inputs. Objective/constraint-driven output requirements are normalized before the immutable snapshot is frozen.
- Added a routed Simulation Configuration Assets workspace for Scenario, Solver Profile, Output Profile, and Run Configuration, including copyable asset-detail routes and a one-click immutable replay path.
- Added “save as new version” and “save as new configuration” workflows for Scenario/Solver/Output assets and explicit UI labeling for temporary runtime overrides.
- Added a V0.21 domain-integrity banner for migrated projects and preserved historical objects without silent rewriting. Legacy operating-point fields are recovered into a temporary Scenario when an old Design Revision is loaded, so migration does not silently fall back to template operating defaults.
- Treat material database/component/fluid changes as Design-domain overrides in validation, UI change counts, and Run Configuration lineage.
- Added atomic create-with-first-revision APIs for Scenario, Solver Profile, and Output Profile; default-asset repair fills orphan profile containers created by older/interrupted flows.
- Added typed Scenario persistence validation plus Solver quality-profile and Output registry validation before versioned assets are written.
- Extended dataset lineage with Run Configuration content hash/traceability and Solver/Output profile revision IDs.
- Added V0.21 regression coverage. Full suite: 156 tests passing, plus Python compileall and JavaScript syntax checks.

## 0.20.0

- Added durable History API routing for every major global/project/design/simulation/task/result/data operation, including deep-link refresh and browser back/forward restoration.
- Added FastAPI SPA fallback under `/app` so copied deep links reopen the same engineering context.
- Replaced remaining browser-native confirmation flows with non-blocking in-page Dialog/Sheet primitives.
- Restored the Design Revision live motor schematic and added debounced model-relation precheck; invalid geometry/winding relationships block immutable Revision creation.
- Added server-side immutable-Revision data integrity validation with structured HTTP 422 errors and `DESIGN_REVISION_MODEL_BLOCKED` auditing.
- Added contextual Chinese guidance and a live schematic/flow visualization to all five simulation setup steps.
- Unified task submission readiness into one authoritative model gate: Studio validation + deterministic feasibility + Motor-CAD native runtime PASS + exact configuration fingerprint are all required before Submit is enabled.
- Structured Motor-CAD runtime qualification root causes for geometry, winding, and parameter round-trip checks; native failures now drive the review-page repair guidance directly.
- Aligned Motor-CAD automation checks with PyMotorCAD guidance: Scripting screen during parameter automation, popup suppression, clean message-log capture, and explicit geometry-check semantics.
- Added one-shot SQLite schema reinitialization/retry for transient `no such table` monitoring failures and stopped stale deleted-Task 404 polling.
- Localized remaining operator-facing English headings/warnings and fixed long Design-tree names and Review-page action layout.
- Added V0.20 regression coverage. Full suite: 135 tests passing.

## 0.19.0

- Reworked the product around an operator-first two-level information architecture: four global destinations (Projects, Runtime, Issues & Logs, System Diagnostics) and five project stages (Overview, Design, Simulation, Results, Data).
- Entering a Project now opens a Project Overview instead of dropping directly into the engineering workspace. The overview exposes one recommended next action, project readiness, engineering asset summary, and recent simulations.
- Added a persistent Project Shell with fixed current-project context, five macro stages, contextual Design/Simulation secondary navigation, and stage readiness states.
- Converted the template library into a Design-stage creation source rather than an independent top-level workspace.
- Added an operator-facing Design Revision editor. Long-lived geometry/winding parameter changes create a new immutable Revision directly from the Design stage; Task-level overrides are moved into an advanced temporary-override drawer.
- Reorganized Task Builder into a five-step operator wizard: Baseline, Scenario, Calculation Mode, Outputs, Review & Submit.
- Added baseline-first progressive disclosure: in Operator mode, scan/DOE/optimization modes remain locked until the current Project has at least one completed baseline Task.
- Changed Task creation continuity so a successfully submitted Task opens directly in Live Monitor with that Task selected.
- Runtime setup is first-run/exception-driven: when a valid Motor-CAD binding and solver capability are already present, startup routes to Project Management.
- Added a concise Motor-CAD runtime status chip to Project Management and normalized Design-page back navigation to Project Overview.
- Added static regression coverage for the new information architecture and operator flow. Full suite: 124 tests passing.

## 0.18.2

- Diagnosed the real Motor-CAD failure in `TASK-5359E95EE8`: the Task overrode the immutable i5 Design Revision from 12 to 16 slots; with 3 phases and 1 parallel path, Motor-CAD rejects `16 / 3 / 1 = 5.33333` as an infeasible winding. Native logs also report slot fill 1.094 > 1 and fundamental winding factor 0.
- Added data-driven winding metadata and a deterministic pre-solve winding guard. The verified i5 template now blocks invalid Slot/Phase/ParallelPath combinations before launching a Motor-CAD worker.
- Added Design Revision -> Task parameter delta diagnostics so hidden task-level overrides such as `slot_count 12 -> 16` are visible during `/api/validate`.
- Fixed frontend validation payload loss: Project, Design Revision, Scenario Revision, and explicit parameter intent are now sent during the precheck, matching the final Task submission context.
- Reworked the former geometry-only guard into a combined model-feasibility check covering geometry and winding relations while preserving the legacy endpoint contract.
- Motor-CAD runtime validation now distinguishes a successful `create_winding_pattern()` API return from an actually feasible winding, parses native API/MessageLog evidence, and raises structured `WindingValidationError` before FEA when possible.
- Added structured winding error details to solver-child IPC error frames and classified failed Cases as `WINDING_INVALID` when applicable.
- Reworked problem diagnosis with root-cause/consequence separation, category labels, and root-cause-first ranking so generic `TASK_FINISHED: FAILED` no longer outranks the actual solver error.
- Task detail now shows the highest-ranked root cause; Logs & Issues respects the Task filter when generating diagnostics.
- Diagnostic ZIPs now include task-scoped `root_cause.json`, model validation/audit files, solver runtime logs, and native Motor-CAD `MessageLogs`.
- Renamed the Data Factory `INGEST_READY` event to `INGEST_COMPLETE` and clarified that ingestion completion does not imply solver success.
- Added V0.18.2 regression coverage. Full suite: 114 tests passing.

## 0.18.1

- Fixed the template-to-workspace handoff race that could immediately overwrite the Design creation draft after selecting a template.
- Reworked template application as a persistent pending workspace action; every workspace refresh replays the pending creation draft until it is confirmed or cancelled.
- Added a full-width Design + Rev.1 confirmation panel so template application is visible in the main workspace rather than only in the narrow property inspector.
- Added atomic `POST /api/projects/{project_id}/designs/from-template`; Design and Rev.1 are committed in one SQLite transaction and roll back together on failure.
- Server now owns the Rev.1 template-default snapshot and validates the template ID, eliminating client-side two-request partial creation.
- Improved template CTA wording to explicitly create a Design in the active project and route users without a project to Project Management.
- Added regression coverage for the UI handoff contract, atomic endpoint, invalid-template behavior, and transaction rollback. Full suite: 106 tests passing.

## 0.18.0

- Moved Motor-CAD installation binding and runtime checks to a dedicated startup page that is always shown first.
- Fixed Windows native `Motor-CAD.exe` browsing by owning the WinForms `OpenFileDialog` with a TopMost window, surfacing cancellation/failure diagnostics, and logging browse request/result events.
- Changed runtime path precedence so an explicit Studio manual binding overrides environment variables until the binding is cleared.
- Added a dedicated Project Management page for project creation, basic-information editing, enter/open, Trash and Restore; removed the top-right project switcher.
- Project-scoped navigation is disabled until a Project is entered; workspace/task/monitor/result/data panels inherit the entered Project and switching is routed back through Project Management.
- Added project list object counts and `PATCH /api/projects/{project_id}` for basic metadata editing.
- Fixed a Windows multiprocessing IPC race where `SOLVER_RUN_SUCCESS` could be followed by `BrokenPipeError: [WinError 109]` during a second `Pipe.poll()`, causing a successfully solved Case to be marked failed. Final frames now stop polling immediately and pipe teardown errors are treated as EOF during shutdown.
- Added log diagnosis guidance for BrokenPipe / WinError 109 and a regression test that forbids polling again after the final solver frame.
- Added `/favicon.ico` 204 handling to remove non-actionable 404 noise from the problem center.
- Improved header sizing, current-project context display, startup guidance, and native-browser waiting/error states.
- Added V0.18 regression coverage; full suite now passes 101 tests.

## 0.17.0

- Added a Project -> Design Revision -> Scenario Revision -> Task -> Case end-to-end workflow contract.
- Added project/design/scenario context to `/api/validate`, eliminating precheck/task context divergence.
- Added backend lineage guards for Design Revision project/template mismatches and Scenario Revision project mismatches.
- Added Schema 11 `design_revisions.explicit_parameter_ids_json` so immutable design versions preserve explicit engineering parameter intent.
- Added Task Builder Design Revision selector and “save current design changes as new Revision”.
- Made Task template a derived/read-only property of the selected Design Revision.
- Added Scenario Revision selection/save/reuse in Task Builder.
- Added Workflow Readiness API and clickable Project/Design/Motor-CAD/Qualification/Results ribbon.
- Added a cached Motor-CAD Runtime Gate before formal Task creation; unavailable launch/RPC now blocks before a Task is written.
- Deep preflight now refreshes Runtime Gate evidence and persists `runtime_gate.json` in the boot diagnostics directory.
- Project switching clears stale monitor/result/analytics state from the previous project.
- Scoped Data Factory summary, Dataset Registry and Dataset builds to the current Project; cross-project dataset mixing is blocked by default.
- Fixed project-delete messaging to reflect lineage-preserving Trash semantics rather than historical task detachment.
- Added V0.17 workflow regression coverage; full suite now passes 94 tests.

## 0.16.0

- Reworked the operator flow around a single active Project context; Task/Monitor/Result Viewer/Data Factory inherit the current Project instead of repeatedly asking users to select it.
- Product UI is Motor-CAD-only by default; Mock remains available only behind the internal test/development flag.
- Added e14 AFPM Yokeless slot-count dependency handling: explicit `slot_count` also synchronizes `Stator_Poles` and `Stator_Pole_Angle`, then runs winding/geometry validation.
- Added template-specific operator notes for e14 `slot_count` and strongly coupled `slot_opening`.
- Material quick selection now defaults to keeping template materials/fluids and no longer silently writes public-catalog examples into Motor-CAD.
- Added Motor-CAD component alias resolution for material application, including stator/rotor back-iron and tooth components.
- Continued Chinese-first/bilingual dynamic UI conversion for Project Tree, parameters, DOE constraints and material selection.
- Fixed native select and changed-count badge contrast.
- Hardened diagnostic ZIP download and maintained local structured logs plus per-boot offline diagnostics under the runtime directory.
- Preserved the unified Engineering Result Viewer as the single results entry.
- Added V0.16 regression coverage; full suite now passes 85 tests.

## 0.14.0

- Unified the navigation around the Engineering Result Viewer; the former standalone Results Analytics tab is now the batch/optimization mode inside the viewer.
- Made Project soft-delete visible from both the workspace toolbar and each Project tree row, with Trash/Restore lineage-preserving semantics.
- Added a frontend/backend client contract, V0.14 cache busting and no-store static HTML/JS responses to diagnose mixed-version deployments that caused missing `/api/materials/catalog` and `/api/result-viewer/catalog` routes.
- Added manual Motor-CAD executable binding, native Windows file browsing and persistent runtime selection when automatic installation discovery fails.
- Changed Motor-CAD canonical parameter application so untouched MTT candidate defaults are not rewritten into a newer/current runtime template; only explicit user/sweep/DOE/optimization intent is written.
- Added canonical `slot_opening` support and geometry-specific diagnosis for Slot Opening / Stator-StatorAir intersection failures.
- Added safe Motor-CAD geometry recovery through `check_if_geometry_is_valid(1)`, followed by revalidation; user-explicit parameters are never silently changed.
- Persisted `model_validation.json` on blocking geometry recovery failures and classify failed Cases as `GEOMETRY_INVALID`.
- Added final runtime `effective_parameters`; quality checks and Data Factory curated `param.*` now prefer actual Motor-CAD runtime readback while preserving differing requested values as `requested_param.*`.
- Downgraded unowned Motor-CAD process detection from an unproven orphan warning to informational status, avoiding false health penalties for manually opened/exiting instances.
- Added geometry-aware log diagnostic recommendations.
- Polished System, Result Viewer, Data Factory and Logs toolbar markup, labels and responsive behavior.
- Added V0.14 regression coverage; full suite now passes 70 tests.

## 0.13.0

- Added persistent target-workstation qualification evidence with template × analysis Level matrices.
- Qualification evidence now participates in runtime validation: validation mode requires Level 3 and production mode requires Level 4 real-solver qualification.
- Added persistent verified material bindings derived from Motor-CAD `set_component_material` / `get_component_material` readback.
- Added target Motor-CAD material verification from the engineering material panel.
- Added result calibration registry and isolated Graph probe workflow for Magnetic, harmonic, FEA path, Magnetic3d, temperature, heat-flow and power graphs.
- Added recommended Graph probes from the versioned output registry without pretending PyMotorCAD can enumerate Graph Viewer names.
- Verified result calibrations are injected into Solver worker registries and tried before versioned fallback graph names.
- Added runtime calibration evidence to simulation fingerprints so cache/data lineage changes when result extraction mappings change.
- Added qualification, material-binding and result-calibration evidence to online diagnostic bundles.
- Enriched template cards with persisted Motor-CAD qualification level.
- Split V0.12 production/runtime UX code out of the monolithic `app.js` into `production.js`.
- Added key-based `locale-data.js` resources for new production/calibration UI while preserving legacy bilingual compatibility.
- Expanded the Result Viewer contract with `mesh_field`, `vector_field` and `table` result types and initial unstructured mesh/vector rendering.
- Fixed result-probe harmonic handling to match the documented three-array PyMotorCAD return contract.
- Expanded regression coverage to 64 passing tests.

## 0.12.0

- Replaced destructive Project deletion with soft-delete Trash/Restore semantics that preserve full engineering and dataset lineage.
- Added guarded permanent purge for developer workflows.
- Added a shared RealtimeChannel manager for System, Task and Logs SSE with reconnect-state handling and automatic HTTP polling fallback.
- Added isolated Motor-CAD template qualification with template load, runtime parameter read/write, material readback, geometry validation and optional real solver smoke execution.
- Added Studio catalog vs real Motor-CAD material-database verification separation.
- Added Basic/Engineering/Expert/Developer UI complexity modes.
- Added parameter Fixed/DOE/Optimization roles, local bounds, Undo/Redo and keyboard shortcuts.
- Added an operator-oriented Experiment Wizard that maps engineering intent to Single/Sweep/LHS/NSGA-II modes.
- Added reviewed Automation parameter metadata with bilingual labels, descriptions, risk/category/source information and explicit unreviewed-state warnings.
- Added an i18n V2 key-based foundation while preserving legacy bilingual compatibility.
- Added environment.json to diagnostic bundles with platform, Motor-CAD target, registry hashes, model policy and licence-pool state.
- Fixed deep preflight/qualification cancellation-grace setting regression.
- Expanded regression coverage to 53 passing tests.

## 0.11.0

- Added safe Project deletion with history-preserving default behavior.
- Fixed the system-metrics structured-log call that could break the system SSE and leave the GUI permanently reconnecting.
- Added SSE retry/heartbeat/error isolation and automatic polling fallback after repeated stream failures.
- Moved deep Motor-CAD preflight to an isolated spawn process with timeout and process-tree cleanup.
- Changed ambiguous `get_licence() == None` preflight reporting from PASS to informational/unknown.
- Reworked the Engineering Parameter Inspector into an operator-oriented Chinese Engineering Parameter Editor with inline help, changed-state filtering and live schematic feedback.
- Added Motor-CAD-inspired RFPM/AFPM parametric schematics driven by live design inputs.
- Added Chinese explanations for expert Automation variables and curated solver controls; raw native variable input remains developer-only and collapsed.
- Added a built-in common material catalog for NdFeB/SmCo, NGO electrical steels, conductors, structures and cooling fluids, with public-reference metadata and supplier-authority warnings.
- Added the Engineering Result Viewer with overview, performance, loss, waveform, harmonic, FEA field, thermal, Lab, mechanical/NVH and native-artifact modules.
- Added generic versioned `get_magnetic_3d_graph` Map2D extraction support without inventing model-specific graph names.
- Added bilingual Chinese/English UI switching and translated Data Factory dynamic content.
- Expanded online diagnostic bundles to include rotated central logs and per-Case log artifacts for a selected Task.
- Moved developer-only API/Automation registry controls into collapsed diagnostic sections.
- Fixed accidental localized DOM IDs for Workspace refresh, DOE seed, Data Factory seed and log live-refresh controls.
- Expanded the automated regression suite to 47 passing tests.

## 0.10.0

- Added a unified Observability Plane with rotating structured JSONL, human-readable text, audit and per-Case solver runtime logs.
- Added API Request IDs, mutation audit logging and Task/Case/Stage/Worker correlation fields.
- Added log query, summary, diagnostics, SSE streaming and diagnostic-bundle export APIs.
- Added problem-signature aggregation with volatile-ID normalization, affected Task/Case tracking and targeted troubleshooting recommendations.
- Added system-alert transition logging for disk, memory, Worker heartbeat/process and orphan Motor-CAD conditions.
- Added `scripts/analyze_logs.py` for offline runtime-problem analysis.
- Added the Engineering Workspace UI backed by Project -> Design -> immutable Design Revision entities.
- Added project tree navigation, schematic motor preview, revision snapshots, revision cloning and direct Design Revision -> Task loading.
- Upgraded the template library with RFPM/AFPM schematic previews, maturity indicators and side-by-side template comparison.
- Upgraded the engineering parameter panel with search, changed-only filtering, changed-value highlighting and reset-to-template behavior.
- Added Task stage-performance and waiting-reason views to the real-time monitor.
- Added a Logs & Problems Center with live SSE, multi-dimensional filtering, Task/Case jump links and one-click diagnostic packages.
- Added Task-level diagnostic-package download and per-Case `solver_runtime.jsonl` artifacts.
- Added persistent log-sequence recovery across service restarts so SSE cursors remain monotonic.
- Expanded automated regression coverage with V0.10 observability/API/timeline tests.

## 0.9.0

- Added Project, DesignRevision, ScenarioRevision and persistent Experiment lineage.
- Added archive-based adaptive NSGA-II generations with engineering constraints.
- Added derived engineering metrics and feasibility/constraint violation calculation.
- Added automatic Raw Index -> Curated -> Features Task ingestion.
- Added immutable Dataset/Version registry with CSV, JSONL and optional Parquet outputs.
- Added deterministic development/validation/holdout partitioning.
- Added schema/content hashes and Case-level dataset membership lineage.
- Added Data Factory quality reports, input deduplication and quarantine reason tracking.
- Added Data Factory GUI, Dataset Builder and Dataset Registry.
- Added NSGA-II controls and constraint builder to the task GUI.
- Corrected simulation fingerprints to include materials, solver settings and automation overrides.
- Added task-level internal exception guard so optimizer failures cannot leave tasks permanently RUNNING.
- Added independent MOTORCAD_STUDIO_FACTORY_DIR for test/development/production isolation.
- Expanded regression suite to 39 passing tests.

## 0.7.0

- Added DOE experiment definitions for Full Factorial, Latin Hypercube and random sampling.
- Added Pareto Search candidate generation with non-dominated ranking and crowding-distance metadata.
- Added optimization analytics API, Pareto visualization data and normalized parallel-coordinate datasets.
- Added multi-Case series overlay API and GUI for torque, temperature, flux-density and other registered series.
- Added local Motor-CAD module licence scheduling for EMag, Thermal, Lab and Mechanical workloads.
- Added licence pool telemetry to the real-time system cockpit.
- Added persistent checkpoint manifests with input signatures; sequential EMag→Thermal runs can resume from a valid completed EMag checkpoint.
- Added checkpoint registration to Case stage history and persistent optimization-summary artifacts.
- Expanded the new-task GUI with DOE variable builders, sampling controls and multi-objective definitions.
- Expanded result analysis with Pareto front, parallel coordinates and multi-Case curve comparison.
- Expanded automated suite to 36 tests.
- Closed multiprocessing Queue feeder threads explicitly so the test/runtime process exits cleanly after large Case batches.

## 0.6.0

- Added a read-only Monitoring Plane based on persisted task state and psutil.
- Added system SSE and task SSE streams for low-latency browser updates.
- Added host CPU, memory, disk and solver-pool telemetry.
- Added Worker process-tree aggregation, including detected Motor-CAD descendant PIDs and total process-tree memory/CPU.
- Added heartbeat-staleness, resource-pressure and orphan-process candidate alerts with a system health score.
- Added task ETA, elapsed time, case throughput, stage summary and event severity telemetry.
- Added a dedicated real-time monitoring cockpit with stage pipeline, active-worker table, Case matrix and live event console.
- Added toast notifications for warnings, errors and task/case completions.
- Added task analytics endpoint and GUI for parameter-result scatter/line plots, quality coloring, result statistics and Pearson sensitivity snapshots.
- Added filtered batch result table.
- Added light/dark themes, Ctrl/Command+K command palette, live task configuration summary and changed-parameter highlighting.
- Added V0.6 interaction and monitoring documentation.
- Expanded automated suite to 31 tests; current container coverage remains approximately 67%.

## 0.5.0

- Added Motor-CAD Installation Manager with scan, explicit selection, target-version auto-selection and `set_motorcad_exe()` integration.
- Added official PyMotorCAD stable API capability catalog and runtime method compatibility endpoint.
- Added runtime API drift audit to compare documented catalog methods with the installed PyMotorCAD `MotorCAD` class.
- Added 26 curated high-frequency solver controls from official EMag/Thermal/Lab examples with context-scoped settings.
- Corrected official high-use candidate names such as `ShaftTorque`, `T_[Winding_Max]`, `Shaft_Speed_[RPM]`, `PeakCurrent`, `DCBusVoltage`, and `PhaseAdvance`.
- Switched graph extraction to bulk APIs first, with point-based compatibility fallback; added air-gap flux-density and torque-harmonic outputs.
- Added stage-specific native `export_results()` CSV archival for EMag, thermal and Lab results.
- Added version × motor type × context Automation Parameter Names importer/store.
- Added dynamic Expert Automation Parameter GUI and validation.
- Added material database, component material and cooling fluid configuration.
- Added thermal transient, native magnetic-thermal coupled, mechanical and Lab analysis recipes.
- Added motor-family catalog for the main supplied templates and explicit missing/specialized families.
- Defaulted Motor-CAD GUI visibility to off for zero-touch external automation.
- Added bootstrap, installation-scan and Automation Parameter import scripts.
- Expanded automated suite to 28 tests; current container coverage is approximately 66%.

## 0.4.0

- Added canonical-to-solver unit conversion with audited round-trip conversion.
- Added schema validation and cross-reference validation for YAML registries.
- Applied Motor-CAD parameters by analysis context instead of one global write pass.
- Added official Motor-CAD geometry validity checks and pre-solve model checkpoints.
- Added explicit model policies: development, validation and production.
- Added Case-level parallel scheduling inside a single Task.
- Added optional Motor-CAD parallel-instance reuse with `set_free()` lifecycle handling.
- Added PID creation-time tracking to reduce stale-PID process termination risk.
- Added scalar and series result extractor framework with context-aware extraction.
- Added physical consistency quality checks for mechanical power and efficiency.
- Added lightweight task summary and paginated Case APIs.
- Isolated automated tests from delivery/runtime databases and result directories.
- Expanded the automated suite to 17 tests.

## 0.3.0

- Fixed ambiguous `.mtt` default extraction with context-aware section selection.
- Added Motor-CAD 2026R1 versioned parameter/output/capability registries for i5, e9 and e14.
- Added verified local `.mot` model source layer and Windows onboarding scripts.
- Added runtime parameter default snapshot, write/readback audit and output extraction audit.
- Moved every Case solve into an isolated child process.
- Added heartbeat, timeout, forced cancellation and process-tree cleanup.
- Split execution status from result quality status.
- Added full simulation fingerprints and valid-result-only caching.
- Added cached artifact cloning and result artifact path rewriting.
- Added baseline capture, tolerance comparison and HTML comparison reports.
- Added 11 automated tests covering reliability features.

## 0.2.0

- Added Task–Case–Event–Artifact data model.
- Added template profiles, scenario configuration, quality checks and export packages.
