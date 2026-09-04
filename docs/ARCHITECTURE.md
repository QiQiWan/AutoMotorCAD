# 架构说明

## 1. 应用装配

MotorCAD Studio 0.91.6 使用单一 Composition Root、密封 ServiceContainer、FastAPI Application Factory 和协调式生命周期。

```text
main.py
  -> bootstrap/composition_root.py
  -> ServiceContainer
  -> bootstrap/app_factory.py
  -> platform routers + bounded-context operation catalog
```

数据库、日志、TaskManager、Motor-CAD Worker Pool、运行时调度器、结果网关、控制平面和所有 Router 都由 Composition Root 构造。Router 不自行创建进程级资源。

当前应用图：

- OpenAPI 路径：397；
- OpenAPI 操作：425；
- FastAPI 方法签名：428；
- 重复方法与路径：0；
- ServiceContainer 必需服务：96/96；
- 每个 OpenAPI 操作均具有 `x-module-owner`；
- 后端兼容操作：0；
- 后端模块化率：100%。

## 2. 后端有界上下文

公共处理器位于 `motorcad_studio/api/operations`，按业务职责拆分：

```text
analysis.application
execution.application
data-factory.application
optimization.application
qualification.application
requirements.application
native.closure
workspace.projects
workspace.solutions
workspace.motor-design
workspace.materials
engineering.experience
platform.semantics
```

`HttpOperationCatalog` 在应用装配阶段校验：

- 操作 ID 唯一；
- `(HTTP method, path)` 唯一；
- 模块所有权完整；
- 不存在 catch-all 兼容 Router；
- 模块依赖无缺失和循环。

旧的 `api.legacy`、`api.domain_handlers`、`api.route_pool.py` 和 `modules/route_manifest.py` 已移除。

## 3. M5-B/M5-C 事务控制平面

控制平面位于 `motorcad_studio/modules/control_plane`，共享应用数据库和同一个事务边界。

### 3.1 Command Ledger

关键写操作必须提供 `Idempotency-Key`。系统记录：

- Scope；
- Request Hash；
- Command 状态；
- Response；
- Error；
- 创建、更新和完成时间。

同一 Key 与相同负载会重放第一次结果；同一 Key 与不同负载返回冲突；仍在执行的命令返回可轮询状态。

### 3.2 Transactional Outbox

业务聚合更新和 Outbox Event 在同一 SQLite 事务中提交。事件具有 Payload Hash、聚合版本和投递状态，避免业务状态提交后事件丢失。

### 3.3 Optimization 与 Data Factory

Optimization 支持 Campaign、Candidate、Result Evidence、Promotion Gate 和 Replay Plan。Candidate 参数按规范化 JSON 哈希去重，更新使用 Compare-and-Set，Promotion 要求有效结果证据和可选资格决策。

Data Factory 支持 Dataset、DatasetVersion、BuildJob、QualityReport 和 Publication。DatasetVersion、QualityReport 和 Publication 为不可变证据；发布前必须通过构建完成和质量门禁。

### 3.4 Qualification、Requirements 与 Native Runtime

Qualification Evidence 使用前序哈希形成不可变证据链，Decision 只能引用完整证据头。

Requirements 使用不可变 RequirementRevision、ToleranceRevision 和 ProbabilisticQualification。概率要求评价采用 Wilson 95% 置信区间下界作为通过门槛。

Native Runtime Safety 提供：

- Runtime Lease；
- TTL 与 Heartbeat；
- 单调 Fencing Token；
- `.mot` Artifact Lock；
- Native Process Observation；
- Orphan Reconciliation；
- Native Snapshot。

TaskManager 的真实 Motor-CAD 执行路径已接入该服务。每个本地 Runtime Scheduler Worker Slot 具有稳定身份，获得持久租约后才进入求解；进度和 Worker Heartbeat 会续租；进程启动会登记 Observation；退出求解区域会释放持久租约。旧 Worker 持有的过期 Fencing Token 不能继续写入受控资源。

## 4. 工程执行链

```text
Project
  -> Solution
  -> Motor Revision
  -> Analysis Definition Revision
  -> Execution Plan
  -> Task
  -> Case
  -> ResultBundle
  -> FieldData
```

工程上下文解析器在单个数据库快照中验证祖先关系和跨上下文冲突。设计编辑使用不可变 Revision 和乐观并发。计算前检查保持显式工程师操作，不自动跳转参数页、任务页或结果页。

运行时资源调度器以原子方式同时分配 Worker Slot、许可证容量和内存余量。Worker Slot 标识由固定槽位池管理，乱序释放时也不会向两个活动 Case 分配同一 Token。

## 5. 前端装配

HTML 只直接加载：

```text
/static/app.css
/static/core/bootstrap.js
```

`bootstrap.js` 建立唯一的 `window.MotorCADStudio` 根对象，并装配：

- ApiClient；
- EventBus；
- FeatureRegistry；
- DisposableScope；
- Engineering Context Store；
- Workflow Store；
- Result Store；
- I18n Store；
- Control Plane Client；
- Binary Field Viewer。

Control Plane Client 使用规范 API：

```text
/api/control-plane
/api/optimization/v2
/api/data-factory/v2
/api/qualification/v2
/api/native-runtime/v2
/api/requirements/v2
```

ApiClient 为写命令生成稳定 Idempotency-Key 和 Correlation ID。具备稳定幂等键且请求体可重用的写命令允许安全重试。

### 5.1 Runtime Capsule

89 个历史源码保存在 `frontend_legacy`。构建工具按确定顺序生成：

```text
static/core/classic-runtime.catalog.json
static/core/classic-runtime-source.js
```

Runtime Capsule 在单一词法作用域中执行这些源码，并将历史全局导出重定向到 `MotorCADStudio.compat`。它统一追踪并清理：

- Event Listener；
- Timeout 和 Interval；
- AnimationFrame；
- Fetch 和 AbortController；
- Worker；
- ResizeObserver；
- MutationObserver；
- IntersectionObserver。

该方案已经消除多脚本加载顺序和直接全局污染。源码层仍保留历史函数结构，后续可按功能逐步重写，不影响当前运行时边界。

## 6. FieldData 与 WebGL2

后端二进制格式为 `MotorCADFieldDataBinaryV1`：

```text
Magic + Version + JSON Header + aligned TypedArray payload
```

数据包含：

- Float32 Position；
- Uint32 Index；
- Float32 Scalar；
- Topology Hash；
- Scalar Hash；
- Frame Hash；
- Payload SHA-256；
- 坐标与来源权威信息。

HTTP 支持 ETag、304、Range、206 和 416。查看器先读取二进制清单和所需字节范围，失败时回退到 JSON/LOD。

WebGL2 使用独立 Position、Index 和 Scalar Buffer。相邻帧 Topology Hash 相同时保留 Position、Index 和 VAO，只更新 Scalar Buffer。查看器支持旋转、平移、缩放、标准视角、透视/正交投影、播放、上下文丢失恢复和确定性资源释放。

`field-worker.js` 负责几何构建、体单元外表面提取、内部面剔除、标量归一化和 Transferable TypedArray 返回。

## 7. 发布门禁

发布包由以下稳定文件描述：

```text
RELEASE_MANIFEST.json
MODULE_CATALOG.json
PACKAGE_CONTENT_MANIFEST.json
validation/evidence.json
validation/field_data_benchmark.json
validation/openapi_baseline.json
```

启动前拒绝缺失文件、额外文件、哈希不一致、符号链接、旧版本静态资源和模块版本混装。


## Immutable package boundary and mutable runtime state

The package manifest protects immutable application content. Runtime-owned roots (`data`, `runtime`, `results`, `logs`, `baselines`, `factory`) are explicitly outside that hash boundary. Installed builds default those roots to the user profile and sanitize legacy in-program directory overrides unless `MOTORCAD_STUDIO_ALLOW_IN_TREE_STATE=1` is intentionally enabled. This prevents normal lifecycle diagnostics from invalidating the next startup while preserving fail-closed checks for undeclared code, scripts and styles.


## Runtime preflight concurrency and diagnostics

运行环境深度检查是单一受控操作。浏览器端对同一次检查使用 single-flight；后端 `SystemService` 对并发深度检查请求进行合并，只有一个 `MotorCADPreflightRunner` 可以启动真实 Motor-CAD 进程。后到请求等待同一 generation 并复用结果。

Motor-CAD 检查子进程清理由 `terminate_process_tree` 负责，Windows 上进程在枚举子进程前自行退出属于正常竞态，`psutil.NoSuchProcess` 和 `ZombieProcess` 被视为 `already_exited`，不得转换成 HTTP 500。

运行诊断统一写入程序根目录 `logs`，中央日志同时按 HTTP、preflight、error、frontend、task 和 case 进行 fan-out，支持从单个目录收集完整现场证据。

## 6. Route-first 浏览器交互

浏览器 URL 是页面导航状态的持久权威。项目内主路径包括：

```text
/app/projects/<project>/overview
/app/projects/<project>/solutions
/app/projects/<project>/designs/templates
/app/projects/<project>/designs/<solution>/revisions/<revision>/<view>
/app/projects/<project>/simulation/analyses/<analysis>/configure/<step>
/app/projects/<project>/simulation/tasks/<task>
/app/projects/<project>/simulation/monitor/<task>
/app/projects/<project>/results/bundles/<bundle>
/app/projects/<project>/data
```

硬刷新时 Router 先根据 URL 调用 `/api/projects/<project>` 恢复项目上下文，再挂载页面。运行环境检查与工程 Readiness 属于补充状态，在路由可交互后后台刷新。

固定导航由 `static/core/navigation-bridge.js` 在捕获阶段统一转发到 `MCSRouter.navigate()`。历史功能按钮继续由各 Feature 所有者处理；`static/core/interaction-monitor.js` 会把静默 no-op 记录为 `FRONTEND_BUTTON_NO_EFFECT`，并在每个路由完成后调用 HMI 资格检查。
