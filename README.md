# MotorCAD Studio V0.70.0 - Motor Domain Foundation + Runtime Convergence

MotorCAD Studio is an engineer-facing design, simulation, optimization, result-analysis and data-production environment backed by Ansys Motor-CAD / PyMotorCAD.

V0.70 starts the domain-object migration planned after V0.69. The release introduces a solver-agnostic motor core so Design, visualization, Motor-CAD binding, Analysis, Results and Optimization can progressively consume one engineering definition instead of re-interpreting flat parameter dictionaries in every layer. The migration is deliberately incremental: every V0.69 dict contract remains available through a lossless legacy adapter while new Design Revisions persist an immutable typed snapshot.

```text
Project
  ↓
Design → immutable Design Revision
  ↓
MotorSnapshot v2
  ├─ MotorIdentity: native type / physical family / topology / template origin
  ├─ ParameterSet + ParameterDescriptor
  ├─ MotorAssemblySnapshot
  ├─ WindingModel
  ├─ MaterialAssignmentSet
  └─ MotorCapabilitySet
  ↓
MotorModel (pure domain object)
  ├─ immutable parameter patch → MotorChangeSet
  ├─ component parameter projection
  └─ design-owned optimization space
  ↓
future V0.71 visualization providers / V0.72 Motor-CAD native binding
```

## V0.70 motor-domain foundation

The new `motorcad_studio/motor_domain/` package defines `MotorIdentity`, `ParameterDescriptor`, `ParameterSet`, `MotorAssemblySnapshot`, `WindingModel`, `MaterialAssignmentSet`, `MotorCapabilitySet`, `MotorSnapshot`, `MotorChangeSet`, `MotorModel` and `MotorDomainRegistry`. Templates remain presets/origins rather than becoming the type system. `config/motor_topologies.yaml` now separates the Motor-CAD native type (`BPM`, `BPMOR`, `IM`, ...), physical family (`rfpm`, `afpm`, ...), concrete topology (`rfpm_spm`, `rfpm_ipm`, `outer_rotor_pm`, ...), and template ID.

`MotorModel` is intentionally pure: it has no database, HTTP, browser or Motor-CAD dependency. Applying design changes produces a new immutable model plus an explicit `MotorChangeSet` containing affected owners, views, Analysis domains and the native-readback requirement. The same descriptor layer exposes the design-owned optimization space while excluding scenario/operating-point variables.

Database Schema **23** adds `motor_snapshot_json`, `motor_snapshot_schema_version` and `motor_snapshot_hash` to immutable Design Revisions and persistent Design Drafts. New and edited designs persist MotorSnapshot schema **2** automatically. Existing projects can be upgraded through the project backfill endpoint without rewriting the legacy Design payload. Unknown/native-extension parameters and raw material provenance are retained during snapshot ↔ legacy round trips.

The new HTTP/browser boundary is:

- `GET /api/motor-domain/catalog` — topology and typed parameter descriptor catalog.
- `POST /api/projects/{project_id}/motor-domain/backfill` — idempotent snapshot persistence for existing Design Revisions/Drafts.
- `GET /api/design-revisions/{revision_id}/motor-snapshot` — immutable typed Design contract plus compatibility payload.
- `POST /api/design-revisions/{revision_id}/motor-snapshot/change-impact` — typed parameter-change impact without mutating the Design.
- `static/domain/motor-domain.js` — browser-side catalog/snapshot/change-impact boundary for V0.71 visualization migration.

## V0.70 runtime convergence

The single-Case Result Viewer is now owned by `static/results/case-viewer.js`. `results/workbench.js` mounts it directly and the route controller no longer falls back into the legacy Result Viewer owner in `app.js`; the remaining app-level functions are compatibility delegates only.

Eight historical active runtime scripts were physically migrated to stable module paths: execution lease, resource scheduler, execution readiness, native result evidence, engineering contexts, FEA field viewer, native result tables and usability closure. The active/physical top-level `v0xx.js` count is now **9**, down from **17** in V0.69. This release intentionally avoids a broad UI rewrite while changing ownership boundaries underneath the existing engineering workflow.

The V0.68 Windows + Motor-CAD 2026R1 native qualification boundary is unchanged. The Linux build can verify the Studio domain/runtime contracts but cannot promote BPM/SPM/IPM/AFPM native qualification without evidence from the licensed target Windows workstation.

## V0.70 verification

The release adds typed-domain, persistence/backfill, HTTP impact-contract, runtime ownership and browser-runtime tests. Final release gates also cover the V0.62–V0.70 compatibility contracts, Python compilation, JavaScript syntax, configuration parsing and the existing Playwright/Chromium Design/Analysis/Results responsive-runtime contracts. See `docs/V0.70_MOTOR_DOMAIN_FOUNDATION_RUNTIME_CONVERGENCE.md` for the implementation and migration details.

## V0.69 result and optimization surfaces

The routed Results workbench provides five surfaces: **结果总览**, **单 Case**, **Case 比较**, **版本比较**, and **参数研究与优化**. The generic Case comparator is deliberately scoped to 2–8 Cases from one immutable Task/Run Configuration, so unlike-condition results are not silently presented as a clean engineering comparison. Design Revision comparison accepts 2–6 revisions and only computes performance deltas when result evidence is genuinely comparable. Parameter studies are pinned to one immutable Design Revision, one immutable Analysis Revision and one selected operating point.

The engineer-facing study strategies are full-factorial sweep, Latin Hypercube DOE, Pareto candidate search and NSGA-II. Result-based feasibility constraints are editable in the same study contract; constrained candidates are carried into feasible/Pareto filtering and candidate ranking. Preview computes the initial/total Case budget and rejects studies beyond the 5000-Case safety boundary before submission. Multi-objective results expose Pareto candidates, per-objective best candidates, generation convergence and an equal-weight normalized balanced candidate as decision support.

Candidate promotion writes only the study's explicit design-variable IDs into a new Design Revision. Shaft speed, current, DC bus voltage, phase advance, coolant/environment inputs and other Analysis-owned operating-point values cannot leak into Design intent through this workflow.

V0.69 also carries the V0.68 native-qualification boundary forward. Optimization can be used for exploratory engineering before workstation qualification is complete, but the workbench displays that status and does not claim the candidate is Motor-CAD-native qualified. This delivery environment is Linux, so the packaged Motor-CAD 2026R1 workstation qualification remains 0% until the V0.68 Windows suite is run on the licensed target workstation.

## V0.68 native parity chain

```text
Studio template / canonical parameter registry
    ↓
Motor-CAD 2026R1 registered template or verified local MOT
    ↓
native parameter readback
    ↓
Studio write → native readback round trip
    ↓
geometry / winding native validation
    ↓
material assignment round trip
    ↓
Radial + Axial native screenshots
    ↓
real EMag calculation
    ↓
Studio output extraction ↔ native direct readback
    ↓
CSV / MOT / PNG / JSON / Markdown evidence
    ↓
verified MOT promotion only after a complete PASS
```

The four profiles are configured in `config/native_parity_profiles.yaml`:

- **BPM**: `a1`, a generic brushless-PM family baseline.
- **SPM**: `i5_Industrial_SPM_Servo_Tooth_Wound`.
- **IPM**: `e9_eMobility_IPM`.
- **AFPM**: `e14_eMobility_AFM`.

## Qualification environment

V0.68 freezes the qualification environment to **Motor-CAD 2026R1** and **PyMotorCAD 0.8.8**. `requirements-motorcad.txt` and the optional `motorcad` dependency both pin `ansys-motorcad-core==0.8.8`. The worker records the actual runtime version; a mismatch blocks qualification while still allowing diagnostic evidence to be collected.

Database Schema 22 adds `native_parity_runs`. Qualification records are scoped to the active Motor-CAD version, so an older-version PASS cannot qualify 2026R1.

## What V0.68 checks

Each profile verifies:

1. target PyMotorCAD/runtime connectivity;
2. native model load and baseline source;
3. required geometry readback;
4. winding/input readback;
5. canonical parameter write/readback;
6. Motor-CAD geometry validation;
7. Motor-CAD winding diagnostics;
8. structured `get_winding_coil` topology: phase, path, slot domain and turns;
9. component material write/readback and independent native snapshot;
10. required Radial/Axial native geometry screenshots;
11. real EMag solve;
12. scalar/series result extraction parity;
13. native EMag CSV export;
14. verified local MOT baseline retention/promotion.

A successful profile currently contains 18 required high-level gates with row-level evidence inside the parameter, winding, material and result checks.

## Concrete parity repair found during V0.68

The V0.68 audit found a real canonical geometry gap: source Motor-CAD MTT files contain `Slot_Opening`, but the Studio MTT parser did not map it into `slot_opening`. This meant the preview/default registry could omit a geometry value that existed in the native template. The mapping is now restored; the audited baselines resolve to 4 mm (`a1`), 2 mm (`i5`), 3 mm (`e9`) and 3 mm (`e14`).

## Native evidence and visual review

Each target run keeps a native MOT snapshot, geometry contract, winding evidence, material/parameter audits, native screenshots, EMag CSV, full JSON evidence and a Markdown report. The report highlights row-level differences rather than only returning a global failure.

`native_visual_review_manifest.json` links the captured Motor-CAD Radial/Axial images with the Studio canonical geometry contract and provides a final operator review checklist. Studio previews intentionally simplify some regions, so Motor-CAD native geometry remains the geometric authority.

## Safe baseline bootstrapping

Normal `validation` and `production` policies still require a verified local `.mot`. V0.68 adds the special `native_parity` policy so a target-version registered template can be used as a candidate when the first verified local MOT does not exist. The candidate is promoted to `data/verified_models/.../template.mot` only after every preceding required parity gate passes. A failed run cannot poison the production baseline.

## Workstation runner

The one-click Windows entry point is:

```bat
run_v068_native_parity_windows.bat
```

It verifies/installs the pinned PyMotorCAD environment and executes the four profiles in isolated child processes. Planning without launching Motor-CAD is available with:

```bat
python scripts\run_v068_native_parity.py --plan
```

The expert/system UI also exposes a Motor-CAD native parity center with profile status, version-scoped matrix, single/suite execution, blockers, report opening and full evidence-package download.

## Current acceptance status

This source package was built and tested in Linux, where no licensed Motor-CAD 2026R1 GUI/RPC installation is available. Therefore:

- **Studio V0.68 implementation completion: 100%**.
- **Packaged native workstation qualification: 0%** until the Windows suite records real PASS evidence.

Linux unit/integration tests do not substitute for native Motor-CAD evidence. The target workstation must still execute the four-profile suite and complete the visual-review checklist.

## Verification

The complete V0.68 Python collection contains **385 tests across 56 files** and passed in four isolated batches: **89 + 118 + 91 + 87**. Targeted V0.68 tests cover profile/version contracts, DB version scoping, strict numeric comparison, registered-template bootstrapping, structured winding return normalization, isolated API recording/artifact packaging, the PyMotorCAD 0.8.8 pin, and the repaired MTT slot-opening extraction.

Additional release gates include Python compilation, static JavaScript syntax, configuration parsing, V0.62-V0.67 compatibility contracts, the V0.68 release contract, and a dry-run plan that resolves all four profiles.

The detailed qualification design and Windows acceptance procedure are in `docs/V0.68_MOTORCAD_NATIVE_PARITY_QUALIFICATION.md`.

## 历史版本摘要

### V0.23.0 — Native FEA Evidence & Session Supervisor

MotorCAD Studio 是以 Ansys Motor-CAD / PyMotorCAD 为后台求解器的电机工程设计、自动仿真、优化、结果分析和数据生产平台。

V0.23.0 在 V0.22 连续工程流程之上增加 Motor-CAD 原生 FEA 证据层和 Session Supervisor。EMag 求解完成后会以 best-effort 方式调用 PyMotorCAD `save_fea_data()`，保留原始 FEA 导出、SHA-256、Step 范围和可解析的浏览器回放帧；无法识别导出格式时只显示 RAW_ONLY，不生成伪场云图。Live Monitor 现在明确区分“实时过程 / 原生 FEA / 结果曲线”。

每个真实 Motor-CAD Case 同时生成 `motorcad_session.json`，记录 Studio ownership、Worker/Motor-CAD PID、版本、RSS、状态和释放证据。当前 Case 仍由短生命周期隔离 Worker 执行，因此 V0.23 会记录实例复用请求但强制 `reuse_effective=false`，避免一次性 Python Owner 退出后留下 free Motor-CAD 进程；真正热池留给后续持久 Worker 架构。详细说明见 `docs/V0.23_NATIVE_FEA_SESSION_SUPERVISOR.md`。

MotorCAD Studio 是以 Ansys Motor-CAD / PyMotorCAD 为后台求解器的电机工程设计、自动仿真、优化、结果分析和数据生产平台。

V0.22.0 在 V0.21 领域模型之上收敛操作层：项目内主流程统一为“概览 → 模型 → 计算 → 求解过程 → 结果 → 数据”，把 Scenario / Solver Profile / Output Profile / Run Configuration 等版本化工程资产保留在底层，普通操作员不需要在多个管理页面之间反复切换。参数编辑增加随动几何、部件高亮和参数依赖提示；实时监控增加求解过程动画与 Motor-CAD 结果驱动回放；常用输出按分析类型自动勾选。

本版本同时修复诊断包暴露的并发 Revision 编号冲突、重复模型预检、过期 Task/Project 轮询、稳态热错误写入 `Initial_Temperature`、V0.21 Scenario 参数未完整进入 Motor-CAD 写入意图，以及空 Output Profile 在 Run Configuration 中语义不明确等问题。真实 Motor-CAD 成功 Case 会登记为本机模板/分析 Level-4 运行资格证据。详细说明见 `docs/V0.22_MOTORCAD_PARITY_LIVE_FEA.md`。

V0.21.0 收敛工程对象边界。Design Revision 只保存槽极、几何、永磁体、绕组和材料等长期设计定义；Scenario Revision 保存转速、电流、电压、环境和冷却边界；Solver Profile Revision 与 Output Profile Revision 分别版本化求解设置和结果选择。Task 提交前会把四类对象及本次临时覆盖冻结为不可变 Run Configuration。

```text
Project
  ├─ Design -> Design Revision
  ├─ Scenario -> Scenario Revision
  ├─ Solver Profile -> Solver Profile Revision
  ├─ Output Profile -> Output Profile Revision
  └─ Run Configuration
       = Design baseline
       + Scenario baseline / inline snapshot
       + Solver baseline / inline snapshot
       + Output baseline / inline snapshot
       + explicit runtime overrides
             ↓
            Task -> Case -> Result -> Dataset
```

V0.21 同时增加“仿真配置资产”页面与可复制深链接、旧数据领域边界审计、Run Configuration 内容哈希/追溯状态、不可变配置重算入口，以及 Data Factory 对 Run Configuration / Solver Profile / Output Profile 的血缘记录。进一步补齐了材料覆盖血缘、旧 Design 中运行点字段向临时 Scenario 的自然恢复、Scenario/Solver/Output 首个 Revision 原子创建，以及保存前的领域值校验，避免半成品配置资产和错误追溯状态。完整设计说明见 `docs/V0.21_DOMAIN_MODEL.md`。

## V0.18.2 求解可解性与根因日志修复

本版本针对实际 Motor-CAD 失败任务 `TASK-5359E95EE8` 做日志驱动修复。该任务把 i5 模板的槽数从 Design Rev.1 基线 12 改为 16，而模板为三相、1 并联支路，Motor-CAD 原生日志报告 `Slot_Number/Phases/Parallel Paths = 16/3/1 = 5.33333`，并同时报告绕组不可行、槽满率 1.094 > 1、基波绕组因子为 0。几何 API 仍返回成功，因此单独使用几何检查会产生错误的“可计算”信号。

V0.18.2 在提交前增加模板数据驱动的绕组可解性门禁；i5 模板已根据本次 2026R1 实机 MessageLog 固化整数约束。Task Builder 的 `/api/validate` 现在携带完整 Project / Design Revision / Scenario Revision / explicit intent，并显示 Design Revision 与任务参数的差异。16 槽会在启动 Motor-CAD 前直接阻断，12 槽基线可继续进入原生模型检查。

运行时 `model_validation.json` 现在区分 `winding_refresh_api_succeeded` 与实际 `winding_refresh_succeeded`，并解析 Motor-CAD API 消息和原生 `MessageLogs` 形成 `winding_validation`。问题中心增加 `WINDING / GEOMETRY / IPC / LICENSE / TIMEOUT` 等类别、根因/后果标记和根因优先排序；Task 详情页直接显示最高优先级根因。诊断包额外包含 `root_cause.json`、`model_validation.json`、`runtime_defaults.json`、`parameter_audit.json`、`solver_runtime.jsonl` 和嵌套 Motor-CAD `MessageLogs`，无需再单独收集结果目录才能定位此类问题。

## V0.18.1 模板创建设计修复

V0.18.0 的模板卡片在“使用模板”后同时触发 `showTab("workspace")` 的异步工作区加载，以及另一条显式 `openWorkspaceProject()` 调用。两个请求完成顺序不固定；较晚完成的工作区刷新会把刚渲染的“创建 Design”确认表单覆盖掉。日志表现为模板预检查成功，但之后没有 `/api/designs` 请求，用户看到的仍是“项目中尚无 Design”。

V0.18.1 将模板选择保存为工作区待处理动作。进入或刷新工作区后，只要该动作尚未取消/完成，就重新渲染创建确认页，因此异步刷新无法再吞掉表单。同时，Design 与 Rev.1 改为单个原子 API 提交；服务端使用模板默认参数生成 Rev.1，并在同一 SQLite 事务内写入 Design 与 Revision。


## V0.18 核心变化

### 1. Motor-CAD 配置前置到启动首页

软件启动后首先进入“启动配置”，集中完成：

- 自动扫描 Motor-CAD 安装；
- 手动绑定 `Motor-CAD.exe`；
- Windows 本机原生文件选择；
- 浅检查；
- Motor-CAD 深度启动 / PyMotorCAD / RPC 检查。

Motor-CAD 路径属于 Studio 运行环境配置，不再放在项目后面的系统诊断页中。手工保存的 Studio 绑定优先于环境变量，清除绑定后才回退到 `MOTORCAD_STUDIO_MOTORCAD_EXE` / `MOTORCAD_EXE`。

### 2. 修复“浏览本机…”不弹出文件选择窗口

Windows 原生浏览改为由 PowerShell WinForms `OpenFileDialog` 打开，并创建 TopMost owner 窗口后使用 `ShowDialog(owner)`，降低选择器出现在浏览器后方或任务栏中无感知的概率。

同时增加：

- 浏览按钮等待态与防重复点击；
- 后端返回 `backend / returncode / reason / stderr / cancelled` 诊断信息；
- 浏览请求与结果写入审计日志；
- 弹窗受系统策略限制时仍可直接粘贴完整 EXE 路径。

### 3. 独立“项目管理”页面

顶部不再提供项目下拉切换。项目的创建、查看、基本信息编辑、进入、删除和恢复集中在“项目管理”页。

项目管理当前支持：

- 新建项目并进入；
- 编辑项目名称和说明；
- 显示 Designs / Scenarios / Experiments / Tasks 数量；
- 软删除到回收站；
- 从回收站恢复；
- 明确“进入项目”。

进入项目后，项目驾驶舱、项目工作区、模板、Task、监控、结果与 Data Factory 固定继承当前 Project；切换项目需要返回项目管理页完成。未进入 Project 时，项目级导航会被禁用。

### 4. 修复 Windows `WinError 109` 导致“求解成功后任务仍失败”

用户日志中的最新失败链路为：

```text
SOLVER_RUN_SUCCESS
 -> parent multiprocessing Pipe poll()
 -> BrokenPipeError: [WinError 109] 管道已结束
 -> CASE_FAILED
 -> TASK_FINISHED: FAILED
```

子求解器已经完成计算并发送 final frame，父进程随后再次对已关闭的 Windows Pipe 执行 `poll()`，`PeekNamedPipe` 抛出 WinError 109，成功结果因此被误判失败。

V0.18 在收到 final frame 后立即停止继续轮询，并在关闭阶段将 `EOFError / BrokenPipeError / OSError` 按 IPC 正常结束处理。新增回归测试确保 final frame 后不会再执行第二次 `poll()`。

### 5. 其他日志驱动修复与界面收敛

- `/favicon.ico` 返回 204，避免无意义 404 告警污染问题中心；
- 问题诊断识别 `BrokenPipe / WinError 109 / 管道已结束`，给出 IPC teardown 定位提示；
- 顶部当前项目改为紧凑状态入口，仅用于返回项目管理，不承担项目切换；
- 修复 Header 下拉框受全局 `width:100%` 影响造成的异常占宽；
- 系统诊断页保留高级诊断、资格校准和开发者能力，安装路径与运行检查统一回到启动配置；
- 已保留 V0.14+ 对材料目录、Result Viewer 路由、Slot Opening / Stator-StatorAir 几何诊断等修复；日志中的这些记录属于较早会话，最新任务已经进入 `SOLVER_RUN_SUCCESS`。

## V0.17 能力继续保留

### V0.21 工程对象与执行血缘

项目对象按照 Design / Scenario / Solver / Output 四个版本化域组合为 Run Configuration；Task 只承担执行。历史 V0.20 及以前的对象继续保持不可变，领域审计会提示需要自然迁移的旧 Design Revision 与旧 Task。

Task 必须继承合法 Design Revision；Scenario Revision、模板和 Project 归属继续由后端校验。

### Motor-CAD Runtime Gate

正式产品创建 Task 前仍要求近期 Motor-CAD 启动/RPC成功证据；必要时自动执行隔离深检。失败时直接返回 `MOTORCAD_NOT_READY`，避免先创建注定失败的 Task。

### Data Factory 项目隔离

Data Factory summary、Task 来源、Dataset Registry 和 Dataset Build 均受当前 Project 约束，默认阻断跨 Project 数据集合并。

## 推荐使用顺序

1. 打开“运行环境”，扫描或绑定 `Motor-CAD.exe`；
2. 执行浅检查；首次正式运行前执行 Motor-CAD 深度检查；
3. 进入“项目管理”，新建或进入 Project；
4. 在“设计”维护 Design / Design Revision；
5. 在“仿真 -> 配置资产”维护 Scenario、Solver Profile 与 Output Profile；
6. 在“配置计算”选择版本化基线，必要时进行明确的本次临时覆盖；
7. 完成模型门禁后提交；Studio 自动冻结 Run Configuration 并进入实时监控；
8. 在 Task / Run Configuration 页面复查内容哈希、基线和覆盖差异，必要时按冻结配置重算；
9. 在 Result Viewer 审查结果，并在 Data Factory 构建带完整运行配置血缘的不可变 Dataset Version；
10. 需要切换项目时返回“项目管理”。

## Windows 启动

推荐：

```bat
start_windows_motorcad.bat
```

若自动扫描找不到 Motor-CAD，请在“运行环境 → Motor-CAD 安装与启动路径”中点击“浏览本机…”或粘贴 `Motor-CAD.exe` 完整路径。

## 测试

```text
214 test cases completed; V0.28-specific: 8 passed
```

同时通过 Python `compileall` 和全部前端 JavaScript 静态语法检查。

## 真实工作站仍需完成的验收

自动测试覆盖 Studio 控制逻辑，真实 Motor-CAD 工程有效性仍取决于目标工作站、模板、Motor-CAD 版本和具体设计参数。生产使用前建议继续完成：

- i5 / e9 / e14 Level-4 Qualification；
- e14 Yokeless AFPM 槽型与 Slot Opening 实机校准；
- 目标材料 Binding；
- EMag / Thermal / Lab 结果映射校准；
- 100 / 500 Case 稳定运行；
- 真实 Efficiency / Loss / Thermal Map 与 FEA 场结果验证。

## 文档

- `docs/V0.23_NATIVE_FEA_SESSION_SUPERVISOR.md`
- `docs/V0.23_NEXT_OPTIMIZATION_ROADMAP.md`
- `docs/V0.22_MOTORCAD_PARITY_LIVE_FEA.md`
- `docs/V0.21_DOMAIN_MODEL.md`
- `docs/V0.21_NEXT_OPTIMIZATION_ROADMAP.md`
- `docs/V0.18_LOG_DRIVEN_FIXES.md`
- `docs/V0.17_IMPLEMENTATION.md`
- `docs/V0.17_END_TO_END_USABILITY.md`
- `docs/TEST_REPORT_V0.17.md`
- `docs/V0.16_AFPM_RUNTIME.md`
- `docs/PRODUCTION_CALIBRATION_V0.13.md`
- `docs/OBSERVABILITY_V0.10.md`
