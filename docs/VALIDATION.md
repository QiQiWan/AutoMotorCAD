# 完成度、效果与验证边界

## 1. 四项优化完成度

| 优化范围 | 0.91.8 状态 | 自动化结论 |
|---|---|---|
| M5-B/M5-C 控制平面 | Command Ledger、Outbox、Optimization、Data Factory、Qualification、Native Runtime、Requirements 已实现并接入 Composition Root | 完成离线事务与合同验证 |
| 后端兼容处理器清理 | 251 个公共处理器按 13 个有界上下文物理组织，兼容操作为 0 | 后端模块化率 100% |
| 前端收敛 | 单入口、统一 ApiClient、Control Plane Client、密封 Runtime Capsule、生命周期资源回收已实现 | 500 次 Mount/Unmount Soak 通过 |
| FieldData/FEA | 二进制 TypedArray、Indexed Geometry、Range、Topology 复用、Scalar-only 更新和 WebGL2 恢复已实现 | 合成与合同验证通过；实机 GPU 资格待完成 |

89 个历史前端源码仍作为可读源码保留。它们已从浏览器逐文件装载路径和产品全局命名空间中退出，当前由一份可复现的密封 Capsule 运行。将每个历史函数人工重写为独立 ES Module 不属于本轮已声称完成的源码改写范围。

## 2. 自动化验证范围

统一验证器执行 25 项阻断检查：

1. Release Sync；
2. Module Audit；
3. Package Integrity；
4. Frontend Single Entry；
5. Frontend Navigation Actions；
6. Filename Convergence；
7. Root Layout；
8. Python Compile；
9. JavaScript Syntax；
10. CSS Syntax；
11. Main Entrypoint；
12. Legacy Backend Retired；
13. Frontend Runtime Capsule；
14. Frontend Browser Bootstrap Guard；
15. Frontend Control Plane；
16. Frontend Lifecycle Soak；
17. Binary FieldData；
18. Native FieldData Bridge；
19. FieldData Performance；
20. One-click Launcher；
21. Runtime Preflight Diagnostics；
22. Control Plane Contracts；
23. Native Execution Fencing；
24. OpenAPI Compatibility；
25. Application Graph。

Pytest 还覆盖：

- 幂等重放和负载冲突；
- Transactional Outbox；
- Candidate 去重、CAS 和 Promotion Gate；
- Dataset 构建、质量和发布门禁；
- Qualification Hash Chain；
- Native Lease、Fencing、`.mot` Lock 和 Orphan Reconciliation；
- TaskManager 与 Native Runtime Fencing 的真实代码路径桥接；
- Requirement/Tolerance Revision 与 Wilson 概率评价；
- 后端路由唯一性；
- 前端 Capsule 可复现构建；
- Control Plane Client；
- 安全的幂等写重试；
- 二进制 FieldData 编解码和 HTTP Range；
- 一键启动环境引导。


### 2.1 路由与按钮专项回归

0.91.6 增加以下发布阻断项：

- 13 个固定主页面均具有 History API 路由身份；
- `/app/projects/<id>/solutions` 等深链接由服务端返回 SPA Shell，并由前端从 API 恢复工程上下文；
- 91 个 `index.html` 固定按钮全部具有显式 action/data 属性或源码绑定证据；
- “新建方案”使用 `/app/projects/<id>/designs/templates` 持久路由；
- 路由恢复先于后台 Runtime Preflight；
- 点击后无可观察效果的按钮会写入 `logs/frontend.jsonl`；
- 每次路由完成会执行运行时 HMI 资格检查。

动态按钮仍由 `MCSHMIQualification` 在 DOM 创建后检查；运行时无效点击由 `interaction-monitor` 补充记录，因此现场可以直接从日志定位静默 no-op。


### 2.2 0.91.6 AFPM、设计编辑与刷新恢复专项回归

0.91.6 针对目标 Windows 工作站暴露出的 AFPM 和设计链路问题增加以下回归：

- `e14_eMobility_AFM` 默认状态的 Studio 几何检查与绕组检查必须通过；
- AFPM 模板的 Native check 必须使用根级 `motorcad_studio.validation.normalize_parameters`，禁止重新出现 `motorcad_studio.api.operations.validation` 的错误相对导入；
- Studio 内部模块导入异常不得被误标记为“PyMotorCAD 无法导入”；
- AFPM 设计意图图必须按 r-z 截面绘制上下两个环形活动区、双转子、单定子、两侧气隙和中心轴孔，禁止再次用贯穿活动半径的整块轴/实心矩形表达；
- 材料编辑和设计工作台关键克隆路径不再直接调用 Compatibility Proxy 上的 `structuredClone`，设计编辑器加载失败时必须记录 `DESIGN_EDITOR_LOAD_FAILED`、清理半初始化状态并提供重试；
- `/app/...` 深链接在旧运行时网络初始化前先进行 URL prime，现代 Bootstrap 在工程上下文恢复期间显示 route hydration shield，避免刷新先显示默认页、数秒后再跳回目标页；
- 历史 0.91.6 现场日志曾记录 PyMotorCAD 0.8.6，并采用过 0.8.8 固定资格基线；0.91.8 已取消该产品级版本绑定，实际 PyMotorCAD 版本仅作为环境证据，正式 Native 资格按 Motor-CAD 目标版本、API 可导入性/能力和工作站实测证据判定。

完整 Pytest 数量以 0.91.8 发布包的最终自动化验证结果为准。由于本验证环境不是目标 Windows + Licensed Motor-CAD 2026 R1，`e14_eMobility_AFM` 的真实 Native 打开、模型检查和求解仍必须在目标工作站重新执行后才能判定模板的正式 Motor-CAD 资格。

### 2.3 0.91.7 实机日志与性能/AFPM 提交专项回归

0.91.7 针对 2026-09-04 上传的 Windows 运行日志增加以下发布回归：

- 安装扫描必须使用有界目录模式，并继续发现 `v261/motorcad/MotorCAD.exe` 类实际 ANSYS 安装布局；连续自动读取命中缓存，显式刷新可强制重扫。
- 浅层 Preflight 连续读取复用缓存、并发读取合并为一个检查；安装选择/清除后缓存立即失效。
- 分析模板目录对一个 Design Revision 只允许一次设计上下文、Motor 上下文和 Analysis Catalog 解析，防止模板数量放大数据库与资格检查成本。
- 历史 `当前Definition` 必须在任务准备阶段规范化为 `CurrentDefinition`；最终 Motor-CAD RPC 边界再次规范化并拒绝非法 Automation 标识，避免旧队列或恢复任务绕过上层校验。
- 原始 Automation 参数名不得参与前端中英文翻译。
- AFPM 运行可视化必须使用拓扑感知视图，表达双转子/单定子轴向堆叠，并按 Case 数据呈现极数、槽数、盘径、内径、轴径、磁体极弧和气隙。
- `待解锁` Journey 节点必须同时具备禁用 DOM 状态与点击级阻断，并在局部 Journey 渲染后重新同步全局 Workflow Truth。
- Motor-CAD 绕组消息必须按验证阶段增量判定：旧的 one-past-end 探针 `Coil index too high` 不污染当前检查；若当前验证新增同类消息，则必须阻断。

实机日志中的当前直接故障位于专家参数写入阶段：Motor-CAD 无法找到 `当前Definition`。同一任务已经获得持久 Worker 槽位并启动 Motor-CAD RPC，因此该故障与 Worker/许可证获取无直接证据关联。当前修复覆盖请求准备、注册表校验和最终 RPC 三个边界。真实 Windows + Licensed Motor-CAD 的提交与求解仍需用该版本重新执行 smoke test。

### 2.4 0.91.8 分析配置、交互生命周期与性能专项回归

0.91.8 针对第二组实机日志增加以下发布回归：

- Analysis mount 与 refresh 必须拥有独立 Promise；已失效路由的 mount 不得阻止新路由重新挂载。
- 分析页持久工具栏使用稳定 delegated owner；“新建分析配置”必须在任何路由 remount 后仍有可验证点击所有权。
- raw Solver JSON 必须跳过 i18n；CamelCase/API 标识必须保持原样；三项已观测坏值必须迁移为 `TorqueCalculation`、`BackEMFCalculation`、`CoggingTorqueCalculation`。
- 常规 `/api/system/installations` 不得触发注册表/文件系统发现；已选择安装走零发现热路径；只有显式刷新/自动选择可进行 host discovery。
- shallow preflight 只做进程内/路径级检查，不启动 PowerShell；deep preflight 保留 Motor-CAD 进程与二进制资格证据。
- SQLite SELECT 不再使用全局写锁且不提交只读事务，允许 WAL 并发读；写路径仍串行化。
- Studio 发布合同的 `required_pymotorcad_version` 必须为空，Windows 资格策略为 `capability-qualified`；全局状态栏不得将 PyMotorCAD 包版本显示成产品版本。

本轮上传日志中 100 个 HTTP 请求均返回 2xx。慢请求主要集中在安装发现（最高约 8.43 s）、分析创建（约 10.34 s）、Native check（约 20.40 s）以及显式 deep preflight（约 9.57 s）。分析路由还记录到 18.93 s、8.65 s 等明显卡顿。0.91.8 已移除普通页面最重的 host discovery 与同步只读锁争用，并修正 route lifecycle；目标工作站复测需要重新量化 warm/cold latency，禁止将自动化静态测试结果当成真实 Windows 性能结论。

## 3. 当前结构指标

- 产品模块合同：48；
- 后端目录模块：41；
- 前端目录模块：15；
- 跨前后端模块：8；
- OpenAPI 路径：397；
- OpenAPI 操作：425；
- 重复路由：0；
- 兼容操作：0；
- ServiceContainer 必需服务：96/96；
- 浏览器直接 JavaScript 入口：1；
- 浏览器直接 CSS 入口：1；
- Runtime Capsule 源文件：89；
- Runtime Capsule 当前大小：1,477,811 字节；
- Frontend Lifecycle Soak：500/500；
- 数据库 Schema：56；
- 控制平面 Schema：3。

## 4. FieldData 合成性能证据

`validation/field_data_benchmark.json` 保存两组诊断：

### 25 万三角面，30 帧

- 顶点：126,025；
- 首帧载荷：5,017,208 字节；
- 首帧编码：约 0.013 秒；
- 30 帧 Topology Hash 唯一值：1；
- 30 帧 Scalar Hash 唯一值：30；
- Topology 复用后的线传输节省：约 86.95%；
- Python tracemalloc 峰值：约 19.7 MB。

### 100 万三角面，3 帧

- 顶点：502,681；
- 首帧载荷：20,043,712 字节；
- 首帧编码：约 0.057 秒；
- Topology Hash 唯一值：1；
- Scalar Hash 唯一值：3；
- Python tracemalloc 峰值：约 78.7 MB。

这些数值来自 Linux 容器、本地内存和合成网格，用于检查编码器、哈希、拓扑复用和线传输模型。它们不能替代 Windows 浏览器 GPU 帧率、真实 Motor-CAD 文件读取和长时间内存 Soak。

## 5. 仍需目标工作站完成的资格

以下项目保持 `PENDING`：

- Licensed Motor-CAD 2026 R1 启动、建模、原生检查、求解和结果提取；
- 多任务许可证竞争；
- 持久 Worker 崩溃与恢复；
- 真实 `.mot` 并发写场景；
- 真实 Motor-CAD FEA 导出到二进制 FieldData；
- 100 万三角面浏览器 GPU 交互帧率；
- 30 帧连续播放后的 GPU/Worker/Heap 回落；
- 8 小时及以上运行时和 UI Soak；
- Windows 人工工程师旅程 12/12 验收。

Release Candidate Gate 会把自动化集成验证与人工/工作站资格分开记录。未形成工作站证据前，`formal_rc_qualified` 应保持 false。

## 6. 复验命令

```powershell
python -m motorcad_studio.tools.sync_release_versions --check
python -m motorcad_studio.tools.module_audit
python -m motorcad_studio.tools.validate_release
python -m pytest -q
python -m motorcad_studio.bootstrap_cli --skip-install --check-only --no-browser
```


## 0.91.2 startup regression validation

The release validator verifies that generated files under `data/runtime/diagnostics`, `runtime`, `results`, `logs`, `baselines` and `factory` do not alter package-integrity status, while an undeclared code file beside those runtime roots is still rejected. It also validates cleanup of stale installed-mode runtime-directory environment overrides.

The 0.91.2 frontend regression additionally verifies the compatibility-capsule startup path that failed on Windows in 0.91.1. The failure was traced to `/static/geometry.js` invoking `window.requestIdleCallback` through the compatibility proxy. The runtime now binds and tracks idle callbacks against the host Window, and module-registry validation accepts declared cross-surface backend contracts without requiring browser globals. A browser-harness smoke test must reach `data-bootstrap-state="ready"` with no `Illegal invocation` exception before release packaging.


## 0.91.3 runtime-preflight regression validation

0.91.3 针对 Windows 实机截图中的两个问题增加回归门禁：

- `terminate_process_tree` 在 `psutil.Process(pid)` 成功、随后 `children(recursive=True)` 抛出 `NoSuchProcess` 时必须返回 `already_exited`，不得向 FastAPI 泄漏异常；
- 两个并发深度 preflight 请求只能执行一次 `MotorCADPreflightRunner`，第二个请求等待并复用同一 generation 的结果；
- 浏览器运行环境检查使用明确 operation，后台 GET、轮询和启动读取不会累计到泛化“请求进行中”计数；
- 根目录 StructuredLogStore 必须生成 preflight、HTTP、error、frontend、task 和 case 分层日志。

该回归覆盖进程退出竞态和请求合并逻辑；真实 Motor-CAD 2026 R1 启动、许可证和 COM/PyMotorCAD 行为仍需目标 Windows 工作站继续验证。

## 0.91.6 现场回归边界

- 用户 0.91.5 日志确认默认 `e14_eMobility_AFM` 原生检查的 `explicit_parameter_ids=[]`、`parameter_write_count=0`，因此本次 Stator/Magnet 区域交叠并非 Studio 改写默认几何参数导致。
- 同一日志中模板加载、27/27 运行时参数解析、参数回读、绕组预检查和材料绑定均通过；唯一阻断根因是 AFM 通用几何重叠检查。
- 0.91.6 将该通用 API 保存为诊断证据，不执行其 AFM 自动修复。正式生产资格仍要求在目标 Windows + Licensed Motor-CAD 工作站执行至少一次真实 AFM 电磁求解 Smoke Test。
- 材料数据库扫描已增加自动发现和 UI 恢复链；最终能够发现的 `.mdb` 路径仍由目标工作站的 Defaults.INI / Default File Locations 决定。
