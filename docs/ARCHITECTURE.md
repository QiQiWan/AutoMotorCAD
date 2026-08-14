# MotorCAD Studio V0.7 架构

## 1. 总体架构

```text
                           Web GUI
      ┌─────────────────────┼─────────────────────┐
      │                     │                     │
 Design / Template     Live Cockpit        Result Analytics
      │                     │                     │
      └─────────────── FastAPI Application ──────┘
                            │
          ┌─────────────────┼──────────────────┐
          │                 │                  │
 Registry / Config     Task Manager      Monitoring Plane
          │                 │                  │
          │           Case Scheduler      SQLite + psutil
          │                 │                  │
          │       isolated SolverProcess       │
          │                 │                  │
          └────────── MotorCADAdapter ─────────┘
                            │
                        Motor-CAD
```

## 2. 控制面与监控面解耦

### Control Plane

Task Manager、SolverProcessRunner、MotorCADAdapter负责真正改变模型和启动求解。

### Monitoring Plane

`MonitoringService`只读取持久化状态和操作系统进程，不持有Motor-CAD RPC对象。这样即使同步RPC正在阻塞计算，GUI仍然可以获取资源和heartbeat。

## 3. 实时通信

```text
REST    配置、历史数据、分页、导出
SSE     单向实时状态与事件
```

当前交互以服务器向浏览器推送为主，因此SSE比WebSocket更简单。后续如果需要浏览器向Worker发送交互式控制命令，可升级为WebSocket。

## 4. 参数体系

```text
Canonical Engineering Parameters
        ↓ unit conversion
Versioned Mapping
        ↓
Motor-CAD Automation Variables

Long-tail variables
Automation Parameter Registry
        ↓
Expert Parameter GUI
```

## 5. Runtime

```text
Task
 → Case Scheduler
   → Worker Python Process
      → PyMotorCAD RPC
         → Motor-CAD Process
```

监控层聚合Worker整个进程树，因此CPU/Memory包含其Motor-CAD子进程负载。

## 6. 结果层

```text
scalar
series
native Motor-CAD CSV
artifacts
quality flags
analytics flat dataset
```

`/analytics`只将数值设计参数和scalar结果扁平化，不覆盖原始Graph/FEA数据。


## V0.7 DOE 与优化层

```text
Experiment Definition
├── Full Factorial
├── Latin Hypercube
├── Random DOE
└── Pareto Search
        ↓
Case Generator
        ↓
Task / Case Scheduler
        ↓
LicencePool → Solver Slots → Worker Process
        ↓
Checkpoint + Result + Quality
        ↓
Optimization Analytics
├── Pareto Rank
├── Crowding Metadata
├── Parallel Coordinates
└── Series Overlay
```

### 资源调度

V0.7 将 Worker 并发与 Motor-CAD 模块许可并发分离。`max_workers` 控制进程并行上限，`LicensePool` 控制 EMag / Thermal / Lab / Mechanical 的平台侧并发容量。

### Checkpoint

检查点使用输入签名验证有效性。当前首先实现 `EMag → Thermal` 的电磁阶段恢复；检查点包含 MOT 与标准结果快照，并登记到 Case Stage。

### 优化数据合同

多目标分析只使用已标准化 `result.*` 字段；Motor-CAD 原始 CSV 继续作为审计 Artifact 保存，不直接参与 Pareto 算法。

---

# V0.9 Data Factory Architecture

V0.9 adds a persistent engineering-lineage and dataset plane above the existing solver/runtime architecture.

```text
Project
 ├─ Design
 │   └─ DesignRevision
 └─ Scenario
     └─ ScenarioRevision
          \
           Experiment
              |
             Task
              |
             Case  <---- Optimizer generations
              |
      Solver / Motor-CAD
              |
      Result + Artifacts
              |
       DataFactoryService
       /       |       \
 Raw Index  Curated   Features
                    /
              Quality Gate
                 |
             Dataset
                 |
          Immutable Version
```

## Separation of responsibilities

- Solver adapters produce solver-native and canonical results.
- TaskManager orchestrates execution and optimization generations.
- DataFactoryService owns post-run standardization, lineage, dataset quality and versioning.
- Optimizers consume evaluated engineering rows but do not own dataset storage.
- GUI reads the same registered dataset/optimization state; it does not recompute the authoritative data lineage.

## Data identity

Three identities are intentionally separate:

1. `input_hash`: simulation input identity for caching and deduplication;
2. `record_hash`: standardized row identity after result/feature production;
3. `content_hash`: ordered Dataset Version content identity.

This prevents conflating “same simulation request”, “same curated data row” and “same released dataset”.

# V0.10 Engineering UX & Observability Architecture

V0.10 does not replace the V0.9 engineering-lineage or Data Factory layers. It adds an Engineering Workspace and a cross-cutting Observability Plane.

```text
Engineering Workspace
  Project Tree -> Design -> Revision -> Task Builder
        |
        v
Application / API --------------------------+
        |                                   |
        v                                   v
Task / Case Runtime                    Observability Plane
        |                              - structured JSONL
        v                              - text / audit logs
SolverProcessRunner                    - Request/Trace IDs
        |                              - Problems Center
        v                              - diagnostic bundle
PyMotorCAD / Motor-CAD                      ^
        |                                   |
        +-------- solver child logs --------+
        |
        v
Artifacts -> Data Factory -> Dataset Version
```

The Observability Plane is intentionally independent from the Motor-CAD RPC object. Monitoring and log queries continue to work while a solver is blocked in a synchronous Motor-CAD calculation.

Correlation path:

```text
HTTP Request ID
  -> Task ID
  -> Case ID
  -> Stage
  -> Worker PID
  -> Motor-CAD process tree
  -> Artifact
  -> Dataset lineage
```

The central store uses bounded rotation and retention. High-frequency progress remains DEBUG by default. Monitoring alerts are state transitions, not one record per polling cycle.

# V0.11 Operator UX & Result Viewer Architecture

V0.11 adds two cross-cutting layers without replacing the V0.9/V0.10 backend contracts:

```text
Engineering Workspace / Bilingual Operator UI
        |
        +-- Parametric RFPM / AFPM Schematic
        +-- Material Selection Catalog
        +-- Progressive Disclosure of Advanced Motor-CAD Controls
        |
        v
Task / Case / Solver Runtime
        |
        +-- Isolated Deep Preflight
        +-- SSE -> Polling Fallback
        +-- Structured Logs / Diagnostic Bundle
        |
        v
Engineering Result Viewer
        +-- Scalar KPI / Performance / Losses
        +-- Series / Harmonics
        +-- Map2D / FEA Fields
        +-- Thermal / Lab / Mechanical
        +-- Native Artifacts / Audit
```

The Result Viewer enables modules only when data is present in a Case. Potential PyMotorCAD visualization capability and actually extracted data are intentionally separated.
