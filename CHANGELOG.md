# Changelog

## 0.70.0

- Added the solver-agnostic `motorcad_studio/motor_domain/` foundation: typed identity, parameters/native-binding metadata, components, winding, materials, capabilities, immutable `MotorSnapshot`, explicit `MotorChangeSet`, pure `MotorModel` and a registry/legacy-adapter boundary.
- Added `config/motor_topologies.yaml` to separate Motor-CAD native type, physical motor family, concrete topology and template/preset identity.
- Upgraded the database to Schema 23 and persisted `motor_snapshot_json`, schema version and SHA-256 content hash on Design Revisions and persistent Design Drafts.
- Added idempotent project snapshot backfill plus typed catalog/snapshot/change-impact APIs; unknown parameters and raw material provenance survive legacy round trips.
- Added a browser motor-domain boundary (`static/domain/motor-domain.js`) so V0.71 Geometry/Winding/Material projections can consume one immutable snapshot contract.
- Moved the complete single-Case Result Viewer out of `app.js` into `static/results/case-viewer.js`; routed Results now have one stable Result Workbench owner with no legacy Case fallback.
- Physically migrated eight active historical scripts to stable runtime/workflow/results paths: execution lease, resource scheduler, execution readiness, native result evidence, engineering contexts, FEA field viewer, native result tables and usability closure. Active top-level historical `v0xx.js` files are reduced from 17 to 9.
- Added V0.70 domain/runtime release and Playwright browser-runtime contracts while preserving V0.62–V0.69 compatibility gates. Native Motor-CAD 2026R1 workstation qualification remains intentionally unclaimed in the Linux build environment.

## 0.69.0

- Added the stable route-owned **Results & Optimization Workbench** with four engineer surfaces: result overview, single-Case native result review, Design Revision comparison, and parameter-study/optimization.
- Added project-level result aggregation with immutable Design/Analysis lineage, usable-Case counts, optimization-task detection and explicit Motor-CAD native-qualification trust status.
- Added a stable same-Task **Case 工程结果比较** surface with exact refresh-safe deep links, 2–8 Case selection, server-side Task/Run-Configuration scope enforcement, quality/traceability evidence, changed design/scenario/solver inputs and relative result deltas.
- Added `GET /api/designs/{design_id}/revision-compare` for 2–6 immutable Design Revisions. Parameter and material deltas are always traceable; performance deltas are only computed when solver authority, analysis, quality profile, operating point and solver settings match.
- Prevented DOE/optimization Cases from masquerading as frozen Design Revision performance evidence. Revision comparison now uses only single-execution Tasks with usable Cases.
- Added exact refresh-safe revision-comparison deep links including the selected Design and Revision set.
- Added Analysis-pinned parameter-study catalog and engineer workflows for full-factorial sweep, Latin Hypercube DOE, Pareto candidate search and NSGA-II. Operating point, Analysis Revision and Design Revision are frozen before study generation.
- Added engineer-editable result feasibility constraints (`<=`, `<`, `>=`, `>`, `==`) to the study UI and result workbench. Constraint outputs are automatically added to the immutable output request; duplicate multi-objective result IDs are rejected before execution.
- Added deterministic study-size preview with a 5000-Case hard safety limit, registry validation of variables/objectives/constraints, stale Design/Analysis Revision guards, native-precheck reuse, idempotent submission keys and immutable Run Configuration creation.
- Added `GET /api/tasks/{task_id}/optimization-workbench` with feasible/Pareto candidates, per-objective best candidates, equal-weight normalized balanced candidate, generation convergence and traceable candidate tables.
- Added 2–8 Case engineering comparison directly inside optimization results, reusing the existing quality-aware Result Viewer comparison service.
- Added candidate promotion to a new immutable Design Revision. Only explicit experiment design variables are written back; operating-point values remain owned by Analysis. Optional Analysis rebinding is concurrency guarded.
- Added native-parity decision-boundary banners so exploratory optimization remains available while formal engineering recommendations are visibly unqualified until the applicable V0.68 Motor-CAD workstation profile has passed.
- Added component-container responsive layouts and local table overflow containment for result, revision-comparison and optimization views; Playwright verifies 1500/1000/720-class widths without root horizontal overflow.
- Extended responsive verification to the same-Task Case comparator and dynamic constraint editor; a 720 px number-input min-content overflow found by Chromium was fixed with explicit grid-item/input containment.
- Added V0.69 API/runtime/release contracts and targeted regression tests. Final regression: 396 tests across 57 test files passed in four isolated batches (98 + 104 + 84 + 110); all 56 static JavaScript files passed `node --check`, Python compileall passed, and V0.62–V0.69 compatibility contracts passed. Motor-CAD 2026R1 native workstation qualification remains intentionally unclaimed in this Linux build environment.

## 0.68.0

- Added a version-scoped Motor-CAD Native Parity qualification framework for BPM, SPM, IPM and AFPM with profile contracts for geometry, winding, materials, operating inputs, native screenshots and required EMag outputs.
- Upgraded the database to Schema 22 with `native_parity_runs`; qualification evidence is scoped to the configured Motor-CAD version so an older-version PASS cannot qualify 2026R1.
- Added isolated native-parity worker processes and a one-click Windows suite runner. A hung Motor-CAD RPC/licence/UI session can be terminated without taking down the Studio host.
- Added the `native_parity` model policy. Registered Motor-CAD templates may bootstrap candidate baselines, while validation/production remain strict. Candidate MOT files are promoted to verified local baselines only after all preceding required checks pass.
- Added strict native readback plus idempotent Studio canonical write -> Motor-CAD readback contracts for geometry, winding and operating inputs.
- Added structured winding topology qualification through `get_winding_coil`, checking phase coverage, parallel-path coverage, native slot domain and turns per coil.
- Added component-material write/readback qualification and independent native material snapshots for every required component.
- Added mandatory Radial/Axial Motor-CAD geometry evidence, explicit screen navigation before capture, and a visual-review manifest linked to the Studio geometry contract.
- Added real EMag qualification solve, Studio scalar/series extraction versus independent native readback, and native EMag CSV export.
- Fixed a concrete native geometry parity defect: `Slot_Opening` was present in source MTT templates but missing from Studio canonical MTT extraction. Baseline slot openings now resolve for a1/i5/e9/e14.
- Added native-parity report mismatch tables, evidence SHA/artifact packages, per-run ZIP download and an expert/system qualification center with single-profile and full-suite execution.
- Frozen V0.68 workstation qualification on `ansys-motorcad-core==0.8.8`; the runtime version is recorded and an incompatible PyMotorCAD version blocks qualification while preserving diagnostics.
- Removed a browser-native `alert()` fallback from the new native-parity UI and kept all operator feedback inside Studio dialogs/toasts.
- Full build-environment regression: 385 tests across 56 test files passed in four isolated batches (89 + 118 + 91 + 87). Target Windows Motor-CAD 2026R1 native qualification remains intentionally unclaimed until the four-profile suite is executed on the licensed workstation.

## 0.67.0

- Closed the deferred Analysis/Calculate milestone with one six-step engineer workflow: operating points → physical inputs → solver settings → Precheck → submit → live monitor.
- Physically removed historical `static/v060.js`; stable ownership now lives in `analysis/workbench.js`, `analysis/execution.js` and `analysis/monitor.js`, while `window.MCSV060` is retained only as a narrow compatibility export from the stable workbench.
- Added `GET /api/analysis-definitions/{analysis_id}/execution-plan` as the authoritative read-only execution contract built from one frozen Design Revision and the current Analysis Revision, including operating points, required input domains, solver settings, outputs, precheck/task readiness and the prepared Task request.
- Added revision-bound calculation-check requests and short-lived Precheck evidence. Evidence records the exact Design/Analysis revision pair that was actually checked and is reusable at submit time without repeating the native model check.
- Added `ANALYSIS_EXECUTION_STALE` concurrency protection. Precheck and submit compare browser-displayed Design/Analysis revision IDs with current server authority; a concurrently updated Analysis/Design cannot be silently submitted from a stale page.
- Added `POST /api/analysis-definitions/{analysis_id}/execute` as the normal submission boundary. It re-materializes the authoritative Task contract, validates/reuses Precheck evidence, assigns an idempotent submission key, creates the immutable Run Configuration and then creates the Task through the existing Task service.
- Added `GET /api/tasks/{task_id}/workflow-status` so the live monitor exposes Analysis Definition/Revision, Design/Revision, Run Configuration, Case progress, usable-result counts and result availability as one engineering lineage.
- Added exact refresh-safe deep links for `/simulation/analyses/{analysis}/execute/{cases|inputs|solver|precheck|submit|monitor}` and route/session disposal guards for long-running Precheck/submit calls.
- Removed the duplicate normal-workbench native Precheck owner. Legacy `newTask` is now an advanced compatibility path only; normal navigation and input/precheck handoffs stay inside the Analysis/Compute workbench.
- Added stale-submit UI recovery: on HTTP 409 the checked evidence/submission state is cleared, the newest execution plan is reloaded, and submission remains locked until the new revision pair passes Precheck.
- Preserved recipe-driven native solver authority: scenario load-case values are materialized into canonical parameters before the Motor-CAD adapter invokes electromagnetic, thermal, coupled or Motor-CAD Lab calculations.
- Static frontend debt improved from V0.66: active historical `v0xx.js` 18 → 17. Current metrics are 51 `setTimeout`, 353 `innerHTML`, 119 explicit `window.*` assignments and 1 global `MutationObserver`.
- Added V0.67 contract, execution runtime, responsive-layout and lifecycle verifiers. Full regression collection: **375 tests passed across four isolated batches (88 + 98 + 84 + 105)**; Python compileall, all 51 static JavaScript syntax checks, 26 JSON + 23 YAML parses and V0.62-V0.67 release contracts passed.

## 0.66.0

- Corrected roadmap drift: completed the delayed Design/material parity work while also carrying out the V0.65-planned historical runtime migration. Analysis/Calculate convergence remains the next explicit milestone.
- Fixed `decorateDesignViewer is not defined` by loading stable Design controllers before historical compatibility layers and retaining a temporary `window.decorateDesignViewer` compatibility boundary owned by `design/viewer.js`.
- Rebuilt the radial-flux longitudinal assembly preview as a shaft-centerline section with stator/slot windows, active conductor sides, end windings, magnets, sleeve/banding, airgaps, rotor laminations, shaft/shaft-hole, bearings and housing; geometry is driven directly from current Draft values.
- Reworked winding visualization with slot-number labels aligned to the slot table, P1...Pn parallel-path visualization, and a parameter-reactive slot-definition drawing driven by slot opening/width/depth/corner, tooth-tip geometry, turns and fill factor.
- Expanded the canonical high-frequency design registry to 35 parameter IDs and widened radial/axial/slot workbench surfaces. Added a clear advanced path to the complete target-version Motor-CAD Automation Parameter Names catalog instead of hard-coding every context-dependent field into the primary editor.
- Added template `.mtt` material-default extraction and froze real template material assignments into newly created Design Rev.1 baselines where the template supplies them. Empty template assignments remain unassigned; imported native-model flows do not invent material defaults.
- Modularized the Material Library into `materials/library.js`; added independent list/detail scrolling, auto-selected material details, key engineering properties, B-H/demagnetization/loss curve previews, raw-field inspection and an explicit `用于当前部件` picker action.
- Updated Design Material Assignment so common parts inherit template defaults and normally require no user action; replacement follows a direct component → library → inspect → apply workflow.
- Replaced the previously sparse Design Validation surface with readiness cards for geometry, winding, materials and Motor-CAD evidence, Studio issue summaries and explicit verification/analysis next actions.
- Reflowed Geometry/Winding/Materials/Validation navigation using container width so the stage rail and version-comparison utility do not collide with the parameter inspector.
- Physically removed active `v020.js`, `v025.js` and `v061.js`; responsibilities now live in `workflow/model-gate.js`, `routing/page-controllers.js` and `materials/library.js`. Removed the retired V0.20 Design-editor hooks that remained in `v022.js` and `v041.js`.
- Static frontend debt improved from V0.65: active historical `v0xx.js` 21 → 18, `setTimeout` 54 → 51, `innerHTML` assignments 365 → 350, global `MutationObserver` remains 1. Explicit `window.*` assignments remain 114 because the Design Viewer compatibility alias is intentionally retained.
- Added V0.66 engineering-parity, component-layout and stable-shell runtime contracts. Full regression collection: 367 tests passed across four isolated batches (90 + 96 + 81 + 100); Python compileall, all static JavaScript syntax checks, 24 JSON + 23 YAML parses and V0.62-V0.66 compatibility/release contracts passed.

## 0.65.0

- Removed the historical `v024.js` and `v031.js` files from the active static tree and `index.html`; Design edit lifecycle now lives in `design/editor.js`, Draft persistence in `design/draft-service.js`, validation orchestration in `design/precheck.js`, workflow rail in `workflow/flow-rail.js`, and FEA/thermal visual compatibility in `results/fea-thermal.js`.
- Upgraded the database to Schema 21 and added a monotonically increasing Design Draft `version` used for optimistic concurrency.
- Guarded Draft PUT with `expected_version` and resolved that version at serialized send time, preventing false stale conflicts when a second local edit is queued while the first autosave is still in flight.
- Guarded Draft DELETE with `expected_version`, preventing one browser tab from discarding a newer Draft saved by another tab.
- Guarded Draft Revision commit with `expected_version` and a database critical section spanning version check, immutable Revision creation and Draft deletion, preventing concurrent updates from being silently committed or removed.
- Added structured `DESIGN_DRAFT_STALE` HTTP 409 handling and a read-only stale-Draft editor state that requires explicit reload/resolution before further editing or navigation.
- Added route-safe Draft flush: Router navigation, browser back/forward and project-tree Design/Revision changes now pass through `MCSDesignEditor.prepareRouteChange`; failed persistence restores the last stable route.
- Made Studio and Motor-CAD validation explicit, edit-version-aware and editor-session-scoped. Native validation receives its own `AbortController`; stale requests are discarded/canceled after editor replacement or route exit.
- Removed per-keystroke validation network traffic while keeping immediate local geometry/winding/material preview and Draft autosave.
- Added responsive V0.65 validation pipeline, action cards and stale-conflict treatment using the existing `design-workspace` container contract.
- Added `verify_v065_contract.py`, `verify_v065_draft_queue.js` and `verify_v065_interaction_layout.py`; retained V0.62-V0.64 compatibility verifiers.
- Full regression collection: 360 tests passed across four isolated batches (89 + 118 + 80 + 73); Python compileall, all static JavaScript syntax checks, 24 JSON + 23 YAML parses and Playwright/Chromium layout contracts passed.

## 0.64.0

- Physically migrated Design presentation ownership from historical `v031.js` into stable `static/design/` modules for Geometry, Winding, Material Assignment, Design Validation, Parameter Inspector and a shared renderer facade.
- Added `design/viewer.js` as the read-only Design lifecycle owner with abortable workbench requests, request-token/revision guards and exact routed-view restoration.
- Replaced timeout-based evidence-result switching with deterministic result deep links; fallback loading explicitly awaits Case list hydration before opening a Case.
- Reduced `v031.js` to the workflow-state rail plus FEA/thermal result compatibility layer; Design renderer/controller functions no longer live there.
- Changed the persistent Draft autosave path to a serialized immutable-snapshot queue with request versions and editor sessions; older completions cannot update newer Draft UI state.
- Routed explicit Draft deletion through the same serialized queue so an in-flight PUT cannot recreate a Draft after the operator deletes it.
- Made `v024.js` delegate Geometry/Winding/Materials/Validation rendering and parameter-list/selected-parameter markup to stable Design modules, shrinking its local presentation ownership.
- Added component-width CSS contracts using named containers for the Design Viewer and workspace. The read-only inspector and Draft editor now reflow from the actual available workspace width, independent of browser viewport width.
- Added local overflow containment for winding/material tables to prevent root-page horizontal scrolling.
- Updated router, context navigation and workbench state fallbacks to prefer `MCSDesignViewer`, while retaining `MCSVisualV031` only as a compatibility fallback.
- Added `test_v064_design_renderer_modularization.py`, `verify_v064_contract.py` and a Playwright/Chromium component layout verifier.
- Full regression collection: 354 tests passed across four isolated batches (79 + 117 + 77 + 81); Python compileall, JavaScript syntax, JSON/YAML parsing and layout contract checks passed.

## 0.63.0

- Added `MCSDesignStore` as the shared state boundary for read-only design viewing, persistent Draft editing and router synchronization; project/design/revision/mode/view/selection no longer rely on independent renderer-local ownership.
- Added `MCSDesignNavigation` as the single stage/sub-view contract for Geometry, Winding, Materials and Design Validation, including deterministic next-step semantics for read and edit modes.
- Applied exact design-route state to the shared store before workspace rendering, and made the viewer prefer routed store state over legacy preferred-view state to prevent transient Winding-to-section view flashes after refresh/navigation.
- Design/revision identity changes now clear stale loaded data, parameter selection, dirty count and Draft status from the shared store before the new workspace data arrives, preventing cross-design state leakage during fast navigation.
- Reorganized the Draft editor into a responsive engineering workbench: component tree + visual canvas + sticky parameter inspector on wide screens, editor below canvas on medium screens, and a single-column fallback on narrow screens. Diagnostics now span below the work area instead of squeezing the visual model.
- Simplified the read-only Design object header to one primary `Edit Design` action. Revision history is explicitly secondary and direct Revision cloning is moved into the history rail.
- Added explicit next-step cards inside edit views so Geometry -> Winding -> Slot -> Materials -> Validation -> Save Revision remains visible while tuning parameters.
- Added `MCSPageRuntime.isContextActive()` and replaced unsafe direct route-context `.active()` calls. DOM events or foreign objects can no longer trigger the `routeCtx.active is not a function` failure class.
- Preserved the V0.62 persistent Design Draft, stale-base conflict protection, reusable Motor Design semantics, pinned Analysis Revision behavior and per-material section provenance.
- Added `test_v063_design_workbench_convergence.py` and `scripts/verify_v063_contract.py` for shared-state ownership, module load order, route safety, responsive workbench layout and global DOM-observer limits.
- Full regression collection: 347 tests passed across four isolated batches (79 + 117 + 77 + 74); Python compileall, all static JavaScript syntax checks and JSON/YAML parsing passed.


## 0.62.0

- 收敛工程师主路径为“电机设计 → 分析设置 → 计算 → 结果”，电机设计内部固定为“几何 → 绕组 → 材料 → 设计验证”；隐藏普通工程视图中的重复 Geometry / Winding / Input Data 上下文栏，版本比较下沉为辅助工具。
- 新增 `app-core-v062.js` 统一设计阶段/子视图映射与生命周期事件；设计路由升级为可刷新深链接，精确表达径向、纵向装配、绕组连接、槽内定义、材料和设计验证，并在 `/edit` 下恢复同一编辑视图。
- 新增后端持久化 Design Draft，数据库 Schema 升级至 20；草稿自动保存参数、材料、显式参数 ID 和当前视图，刷新后恢复，零差异自动删除，跨 Revision 草稿禁止静默覆盖。
- 草稿提交增加并发保护：基准 Revision 不再是最新版本时返回 409，避免另一个会话已经生成新 Revision 后继续静默分支。
- 修正 Design / Analysis 版本所有权：创建新的 Design Revision 不再批量推动该电机的全部分析案例；Analysis Definition 固定引用一个 Design Revision，并提供显式版本切换 API。
- 创建分析案例新增“已有电机设计”来源，一个 Motor Design 可以被多个 Analysis Definition 复用；编辑保存时明确询问当前活动案例是否采用新 Revision，其他分析和历史 Task 保持原版本。
- 材料管理拆分为系统级 Material Library 与设计级 Material Assignment。材料选择器记录来源数据库、源文件 SHA-256、单材料段 SHA-256、Motor-CAD 版本和 Studio/Motor-CAD 来源类型；冷却介质继续归属于分析设置。
- 错误 toast 增加 5 秒签名去重、重复次数聚合和最多 3 条可见限制，降低单一后台错误连续刷屏。
- 移除 `v020/v031/v041/v046/v059/v060` 等页面级全局 DOM 观察器，改用路由/工作区/分析/指导生命周期事件；当前仅保留 i18n 动态翻译所需的 1 个 MutationObserver。
- 修复材料草稿深层对象稳定比较，避免 JSON replacer 丢弃嵌套 provenance 字段；材料修改、恢复和自动保存可正确判断 dirty state。
- 设计草稿的放弃/替换改为 Studio 页内确认对话框；保存新 Revision 时明确显示分析案例版本切换影响，不再使用浏览器原生确认框。
- 进一步收敛响应式布局：编辑态隐藏项目树/只读 Inspector 并扩展设计画布，中等宽度自动重排诊断区，工作区根节点禁止横向溢出，1366–1920 桌面宽度优先保证几何/绕组可读空间。
- 完整 pytest 文件集合共 341 项，分四个隔离批次执行为 132 + 104 + 62 + 43 项全部通过；Python compileall、前端 JavaScript 语法、JSON/YAML 与 V0.62 版本合同同步验证。

## 0.60.1

- 修复项目刷新将 DOM `MouseEvent` 误传为路由上下文导致的 `routeCtx.active is not a function`，并统一清理任务、时间线、日志和 Case Viewer 的同类事件绑定。
- 重构径向磁通电机纵向装配剖面，并为轴向磁通模板提供独立盘式堆叠预览；视图选择增加会话保持和过期异步响应丢弃，解决绕组短暂选中后跳回其他截面。
- 修复绕组布局硬最小宽度与项目双列 Grid 的冲突；Motor-CAD 上下文栏占满项目工作区，绕组图、槽表和参数栏按组件实际宽度自适应。
- 新增 Motor-CAD 材料库模块：读取标准 `.mdb`、保留完整原始字段/曲线、记录来源路径与 SHA-256、支持 Studio 管理副本 CRUD、managed `.mdb` 导出并接入现有材料数据库计算路径。
- 在几何、绕组、槽内、材料和输入数据之间增加明确的“推荐路径”下一步入口，降低设计完成后的流程断点。
- 修复创建分析案例弹层透明、主题变量缺失时无底色、参数弹层叠层和关闭后滚动锁残留；两个工程弹层互斥并支持叉号、背景与 Esc 关闭。
- 创建案例或模型后只执行一次项目/设计路由，取消 `showTab + loadWorkspace + openWorkspaceDesign` 的重复加载，错误提示不再出现 `undefined`。
- 参数编辑改为实时本地预览、保存设计草稿、计算前统一检查；取消每次输入后的网络预检查和整组列表重绘。
- 新增“Studio 确定性预检查 → Motor-CAD 模型检查”的两阶段计算门禁；第一阶段失败时第二阶段保持锁定，计算与结果阶段灰显。
- 空数值 `null` 按“未覆盖”处理并回退到设计/模板值，修复 `slot_opening` 触发 Pydantic 原始 JSON 以及模型检查始终失败的问题。
- 全部参数保存会清除历史空覆盖值，直接创建新设计版本；分析案例自动跟随其电机的最新设计版本，历史任务仍保留冻结配置。
- Motor-CAD 检查只返回工程师可理解的结论和处理建议；完整 RPC、参数映射和异常细节继续写入问题中心与诊断日志。
- Python 全量回归 336 项通过；JavaScript 语法、Python compileall、材料库 round-trip、JSON/YAML 解析及 V0.60.1 版本一致性检查通过。

## 0.60.0

- 新增项目级“分析案例”对象与观察页，一个项目可管理多台电机及其独立分析；创建案例时一次完成分析类型、机型和设计起点选择，随后直接进入电机设计。
- 新增冷却、损耗、材料、接触界面、辐射、对流、端部空间和流动回路八个专用输入编辑器，包含工程标签、单位、范围、默认值和用途说明。
- 新增输入物化层：保存的输入模块自动进入 Scenario、MaterialConfiguration、Therm LossSource 和求解物理输入审计，多工况逐点继承并检查。
- 计算前检查覆盖几何包含关系、气隙、槽深、绕组整数关系、槽满率、运行工况、温度、流量、辐射、材料和求解离散设置，并返回字段级处理建议。
- 普通工程师模式移除 Design 快照、资源租约、原生证据、Worker 调度、JSON/MOT 清单等内部实现面板；技术信息继续保留在专家模式、问题中心和诊断包。
- 计算设置页收敛为当前分析案例、运行工况、批量方式、结果项和检查并计算；冷却/材料/热边界从分析案例输入自动读取，避免重复输入。
- 求解监控增加 CASE_INPUTS_READY 与 PHYSICAL_INPUTS 阶段，记录输入模块、映射数量、结果请求和异常上下文；每个 Motor-CAD 工况归档输入应用清单。
- 修复分析案例输入仅保存未进入求解、分析定义多工况漏取输入、空输入造成版本化配置伪覆盖，以及旧项目概览/计算页重复技术面板问题。
- Python 全量回归 327 项通过；JavaScript 语法、Python compileall、JSON/YAML 解析及 V0.60 版本一致性检查通过。

## 0.59.0

- 项目内导航合并为四阶段工程状态条，每个阶段同时显示完成条件、当前状态和唯一推荐操作，降低重复导航与上下文占用。
- 项目状态从“Task 已结束”升级为“存在 SUCCEEDED/CACHED 且质量为 VALID/WARNING 的可用 Case”；无可用结果时直接进入计算问题。
- 结果首页默认选择最近可用任务和首个通过结果验证的工况；结果侧栏只显示本次计算实际具有数据的模块，并汇总未生成模块。
- 已有可用结果不再受当前 Motor-CAD 环境状态阻断，离线时仍可分析历史性能、曲线与有限元场。
- 停止后续工况与立即终止当前工况增加页内确认、等待态和重复点击保护；任务结束后主动关闭 SSE 并提供结果/问题交接。
- 参数目录增加未保存修改保护；关闭侧栏或离开页面前要求确认，避免参数变更静默丢失。
- 结果输入快照递归展开嵌套工况、材料和求解配置，不在普通工程结果界面显示原始 JSON。
- 提升几何、绕组、槽内、FEA 与大图模板预览的最小高度和文字下限；补齐窄屏重排、深色模式及路由焦点播报。
- Python 全量回归 320 项通过；JavaScript 语法、Python compileall、JSON/YAML 解析及 V0.59 版本一致性检查通过。

## 0.58.0

- 机型拓扑卡升级为真实选择控件，并按拓扑筛选当前安装登记的工程模板；无匹配模板时明确回到机型默认模型、MOT 导入或 Revision 克隆。
- 参数目录增加实际变更计数、数值/整数/上下限即时校验、错误聚焦与无变更拦截；只持久化实际修改字段，避免隐式覆盖污染 Design Revision。
- 结果首页、Task 深链、Case 深链和批量跳转统一为单次 Case 自动打开合同；加入加载 token，过期响应不能覆盖用户最新选择。
- 普通任务与结果界面移除 JSON 主按钮、Result ID、PyMotorCAD API、证据级别和底层状态码；技术证据继续保留在诊断包。
- Input Data 卡片补齐实际去向，材料进入材料库、流动回路进入流路编辑器，其余物理域进入对应分析工作台。
- 有限元监控按模型输入、有限元求解、空间场输出、结果提取、结果验证与归档六个工程阶段聚合，并提供最近关键事件和定向诊断包入口。
- 两处全局 DOM 观察器改为逐帧合并扫描，降低结果、监控和参数表渲染期间的重复页面扫描。
- 完成宽屏、中屏与窄屏布局重排，统一键盘焦点、选中、修改、错误、加载、空状态和阻断状态，提高图表、卡片及说明文字可读性。
- Python 全量回归 309 项通过；JavaScript 语法、Python compileall、JSON/YAML 解析及 V0.58 版本一致性检查通过。

## 0.57.0

- 新建模型入口对齐 Motor-CAD 的九类机型，增加机型 → 拓扑 → 来源三级选择；保留新项目默认 BPM 直接进入模型的路径。
- 17 类分析配方补齐用途、求解方式、工况说明、工程输出与必需/可选结果；内部证据策略不再出现在普通工程界面。
- 重写绕组端部路径，使连线只在定子槽与端部绕组环带内闭合；槽内导体按左右槽腔分别裁剪、排布并执行非重合约束。
- 参数目录与 Input Data 改为工程语义卡片，默认显示物理意义、单位、范围、影响和结果用途；Automation 名称、指纹、JSON 与内部策略下沉到诊断包。
- 结果页自动选择首个 Case，并明确拆分执行状态和结果验证；INVALID Case 隐藏零值 KPI，只开放实际已有数据的结果模块。
- 修复 PyMotorCAD 0.8.x 屏幕抓取调用：初始化 Tab 名称，并向 `save_motorcad_screen_to_file` / `save_screen_to_file` 传入屏幕名和文件名。
- 扭矩—转速图增加多组目标版本候选图名，降低目标版本图名差异导致的必需结果缺失。
- 有限元监控新增导出尝试、文件形成、场标准化成功/告警事件；每次尝试的 Step 范围、字段集合和错误进入清单与任务诊断包。
- 日志诊断新增启动会话过滤与 PyMotorCAD 依赖根因，任务诊断包补齐 Case 状态、运行时输入、参数/材料/输出审计、会话、结果提取、有限元清单及首末帧样本。
- 对用户上传的 V0.56 诊断包完成根因审计：当前会话 0 ERROR；两次任务执行成功但结果验证 INVALID；历史 `No module named 'ansys'` 与当前任务分离。
- Python 全量回归 299 项通过；前端 JavaScript 语法、Python compileall 及发布配置解析通过。

## 0.56.0

- Motor-CAD 原生 `ElementsTable / NodesTable / RegionsTable` 标准化改为两遍流式扫描，移除执行路径中的整文件文本、全量单元行和全量节点字典驻留。
- 第一遍将节点坐标写入临时 SQLite `WITHOUT ROWID` 索引，第二遍只按显示预算查询入选单元引用的节点；成功、格式失败与异常路径均清理临时索引。
- 新增确定性在线工程采样，固定保留坐标边界、每个可用场的全源极值和区域代表点，其余容量按稳定哈希填充。
- 全局范围、逐帧范围、有限值覆盖率、坐标有效率和唯一坐标数均从完整源数据在线计算，不依赖显示样本。
- 标准化帧改为逐帧原子替换并登记 SHA-256；单帧完成即可形成独立完整归档，避免中断后留下半写 JSON。
- 支持从原生 ElementsTable 结构表头自动推断输出字段，并兼容逗号、分号、Tab 与竖线分隔符。
- 结果页显示“两遍流式标准化”和磁盘节点索引计数；诊断合同公开标准化 Schema、I/O 合同、节点索引与原子写入策略。
- 新增 10 万原生单元、双帧、真实节点连接、区域/极值保留和内存上界回归；全量 295 项测试通过。

## 0.53.0

- FEA 标准化升级至 Schema V4，全局色标、每帧范围和资格指标统一从完整源数据计算，不再受显示抽样影响。
- 浏览器帧采用区域/坐标边界/各场极值优先的确定性抽样，并记录区域覆盖、极值保留、有效坐标率和字段有限值覆盖率。
- 解析 Motor-CAD ElementsTable、NodesTable 与 RegionsTable；节点坐标完整时绘制真实三角单元填色和边界，缺少节点时明确降级为单元中心点。
- 机械场默认请求官方示例使用的 `SVM/Ux/Uy`，自动计算总位移；应力与位移单位分别记录为 MPa/mm，未确认字段保持原生单位待验收。
- 自动结果提取升级至 Contract V2，拦截非数值/非有限标量、坏曲线、坏二维图、场与矢量结构错误，并生成紧凑数据质量摘要。
- FEA 资格合同增加坐标丢弃比例、必需字段覆盖率、最少空间点、区域覆盖和极值保留门禁；历史清单保留兼容并显示质量指标缺失警告。
- 检查点清单升级至 Schema V2，使用原子替换和 SHA-256 校验；电磁-热恢复同时校验 MOT、载荷和全部 FEA 证据，证据不完整时自动重新执行电磁求解。
- 结果页增加抽样完整性、真实网格/中心点模式、单位依据、源单元/显示单元/三角形计数和提取数据质量摘要。
- 全量离线回归 273 项通过；Python、JavaScript、YAML/JSON 与 V0.53 发布合同验证通过。

## 0.52.1

- 修复 Analysis Definition 多工况只保存/执行首项的问题，逐 Case 冻结工况、哈希、执行与结果上下文。
- 首次创建分析定义与后续 Revision 统一使用专用配方编辑器，并冻结 `analysis_definition_revision_id`。
- 修复原生 FEA 平面配置被旧派生快照覆盖、字符串布尔误判及 required/optional 资格语义。
- 历史结果和缓存必须具有当前结果提取及 FEA 合同，缺失合同不能晋级 Level 4。
- FEA Viewer 使用真实 Case 阶段，增加全字段选择、全帧色标、区域筛选、最近点探测和异步竞态保护。
- 修复机械应力场未进入结构化结果、Case 热网络使用错误工况、重试 Attempt 重复累加与旧产物显示问题。
- 诊断包增加 Case 合同摘要、结果提取清单、FEA 清单、首末帧和受限大小的原始 FEA 样本。
- 扩大工程画布和可读性下限，完善中等宽度、窄屏与深色模式布局。
- 全量离线回归 264 项通过；Python、JavaScript、YAML/JSON 与发布合同验证通过。

## 0.52.0

- V0.47：分析定义升级为全工况默认值物化与逐 Case 类型、枚举、上下限校验；保存 FEA 计划与合同哈希。
- V0.48：原生 FEA 导出升级为策略驱动管线，增加 required/optional/not-applicable、字段/区域/坐标/连接完整度及机械应力/位移场标准化。
- V0.49：新增自动结果提取清单；必需标量、曲线、Map、场或表缺失/无效会阻止工程结果资格。
- V0.50：结果页新增八阶段 FEA 轨迹、提取矩阵、场选择、求解帧、全局色标和原始数据下载。
- V0.51：新增 Task FEA/提取汇总、定向重试不完整 Case，并限制真实寻优仅使用质量 VALID 的 Case。
- V0.52：移除独立 Scripting 工程上下文和 API；真实资格晋级要求质量、必需结果和 required FEA 三项同时通过。
- 全量离线回归 259 项通过；Windows + Motor-CAD 2026R1 实机验收继续按模板/配方记录，未取得证据时不晋级 NATIVE_QUALIFIED。

## 0.46.0

- V0.42：分析配方升级至 Schema V3，17 类配方分别定义字段组、Motor-CAD 方法、必需/可选输出和结果视图；资格改为五级证据链。
- V0.43：增加九个 Motor-CAD 工程上下文、八类 Input Data 物理域和四页绕组信息架构；Flow 明确表示物理冷却流动回路。
- V0.44：分析创建和版本编辑统一使用配方驱动专用表单；后端补齐默认值物化、类型、范围、枚举、必填和输出注册校验。
- V0.45：结果中心增加 Output Data、Graphs、热网络、温度、应力、NVH 视图；每个 Case 返回结果完整度、缺失必需输出和原生证据等级。
- V0.46：增加 DOE/敏感性计算量估算、冷却流动回路连通性校验、受控脚本静态校验、资格覆盖矩阵与全量高 DPI 响应式样式。
- 热求解控制扩展至模型规模、维度、损耗源、耦合方式、时间步与收敛容差；机械控制扩展至转速、部件、黏结、网格和 NVH 阶次。

## 0.41.0

- 修复 Windows 高 DPI 下设计工作区三层侧栏挤压主画布的问题；新增容器级响应式布局并整体提高几何、绕组、槽内、FEA 与热拓扑可读性。
- 修复表单 `.wide` 内容未跨列导致“电机模型”区域按钮和说明竖排的问题；模型区改名为“本次计算模型”，求解配置下沉到高级设置，运行配置追溯默认折叠。
- 修复默认项目创建异步按钮在 `await` 后访问失效 `currentTarget` 的前端异常。
- 修复失效项目路由导致 project/simulation-assets/domain-integrity/ui-guidance 连续 404；现在会清空旧上下文并返回项目管理。
- 修复 Design Revision 程序化载入后 Run Configuration 追溯仍显示“未选择”的状态同步错误。
- 新增槽口宽度、齿宽、槽数与定子内径的显式耦合阻断，覆盖诊断包中 Slot_Opening 自动改写和 Stator/StatorAir 相交故障。
- 关键几何/绕组任务覆盖提交前自动执行 Motor-CAD 原生检查；关键设计修改增加“Motor-CAD 检查并重绘”。
- 分析定义创建由浏览器 prompt 升级为页内工程表单。
- 新增 V0.41 诊断修复回归测试与完成度说明。

## 0.40.0

- 新增模型优先入口：新项目默认 BPM 模型，并支持按 9 种 Motor-CAD 机型、工程模板、MOT 文件或现有 Revision 创建模型。
- Design/Revision 新增 `source_kind`、`motor_type_id`、模型来源、几何模式、MOT 证据、Automation 参数与能力快照；数据库 Schema 升级至 18。
- 新增完整参数目录，将版本化工程参数与目标版本 Automation Parameter Names 合并，支持按求解上下文过滤并保存新 Revision。
- 新增五模块分析工作台与版本化 Analysis Definition；分析类型从 8 类扩展至 17 类，覆盖高级 EMag、Therm/Coupled、Lab、Mechanical/Weight。
- 新增 Motor-CAD 原生有限元画面捕获、Case FEA SSE 事件流，以及 B/Bx/By/Pt/J/JEddy 场变量、区域、步进、探测和原始证据视图。
- 计算工况补齐转速、峰值/RMS 电流、母线电压与相位超前角；从 Analysis Definition 进入计算设置时继承模型版本、分析类型、首个工况和输出选择。
- 工程界面以空间场、拓扑、曲线和指标为主；结构化原始数据保留在开发者诊断和 API 层。
- 将 Motor-CAD `winding_pattern.txt` 从普通附件升级为可降级解析的 `winding_definition.json`，记录线圈槽对、相别、匝数、支路、原生校验、源文件 SHA-256 与字段证据状态。
- 绕组视图在存在结构化原生证据时绘制实际进/回槽关系；尚无证据时保持参数示意并明确显示其权限层级。
- 新增后端热网络证据合同和 `/api/cases/{case_id}/thermal-network`；原生热节点/热阻与标量温度摘要采用不同 authority 和 completeness。
- FEA normalizer 保留区域、字段、元素/节点编号元数据；结果页支持多步回放、字段/区域筛选、全范围/分位/手动色标、最近原生点探测及原始 CSV 下载。
- 新增 `/api/cases/{case_id}/fea-probe`；缺少完整节点坐标与连接时关闭真实网格、连续云图和等值线能力，避免伪造物理场。
- Case 对比升级为 Schema 2，增加设计/工况/求解三域变化、目标方向、Pareto 非支配解、改善/退化、质量门禁、完整追溯和描述性影响。
- 新增 V0.35 决策工作台、证据能力提示与响应式样式。
- V0.40 无求解器服务验收、FEA 字段归一化、Python compileall、配置解析与前端 JavaScript 静态语法检查通过；V0.35 历史全量回归基线为 241 项。

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
