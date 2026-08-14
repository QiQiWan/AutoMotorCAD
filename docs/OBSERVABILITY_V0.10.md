# MotorCAD Studio V0.10 Observability Plane

V0.10 将日志从“故障后查看文本”升级为运行时可观测性系统。目标是在百/千 Case、长时间 Motor-CAD 批处理和 Data Factory 场景下，可以回答四个问题：

1. 系统正在做什么；
2. 哪个 Task / Case / Stage / Worker 出了问题；
3. 问题第一次从哪里出现；
4. 应该先检查许可证、Motor-CAD、参数映射、资源还是数据工厂。

## 1. 日志层级

```text
Application / API
      |
Task Engine -------- Data Factory
      |
Solver Process Supervisor
      |
Case Solver Worker ---- Motor-CAD / PyMotorCAD
      |
Monitoring Plane
```

### 中央日志

`data/logs/studio.jsonl`

机器可读 JSONL，每条记录至少包含：

- `seq`
- `timestamp`
- `level`
- `channel`
- `component`
- `event_type`
- `message`
- `request_id`
- `trace_id`
- `task_id`
- `case_id`
- `stage`
- `pid`
- `thread`
- `payload`

`trace_id` 默认使用 Task ID；没有 Task 时使用 HTTP Request ID。

### 人工日志

`data/logs/studio.log`

用于无需工具时快速查看。

### 审计日志

`data/logs/audit.jsonl`

POST / PUT / PATCH / DELETE API 请求进入独立 audit channel。请求体不会直接落日志，并对 token/password/secret/API key/license key 字段做递归脱敏。

### Case Solver 日志

每个真实或 Mock Solver Worker 在 Case 工作目录写：

`solver_runtime.jsonl`

该文件同时作为 Case Artifact 注册，包含：

- child process start；
- adapter ready；
- solver run begin；
- successful finish；
- child exception；
- PID / Stage / 时间。

因此即使父进程异常退出，Case 本地仍保留独立求解运行记录。

## 2. 日志轮转与保留

环境变量：

```text
MOTORCAD_STUDIO_LOG_DIR=data/logs
MOTORCAD_STUDIO_LOG_LEVEL=INFO
MOTORCAD_STUDIO_LOG_MAX_BYTES=20971520
MOTORCAD_STUDIO_LOG_BACKUP_COUNT=8
MOTORCAD_STUDIO_LOG_RETENTION_DAYS=14
```

生产默认不将高频 `CASE_PROGRESS` 写入 INFO 中央文件，该事件降为 DEBUG，避免 1000 Case 任务造成无意义的日志膨胀。

服务重启时会扫描已有 JSONL 并恢复最大 `seq`，保证 SSE cursor 单调递增。

## 3. 运行时 API

```text
GET /api/logs
GET /api/logs/summary
GET /api/logs/diagnostics
GET /api/logs/stream
GET /api/logs/export.zip
GET /api/tasks/{task_id}/logs
GET /api/tasks/{task_id}/timeline
```

`/api/logs` 支持：

- minimum level；
- component；
- Task；
- Case；
- Stage；
- Request ID；
- keyword；
- time window；
- limit。

## 4. Problems Center

V0.10 不按原始消息逐条显示错误，而先生成 problem signature。

动态 Task/Case ID、Request ID、数字和地址等易变信息会归一化，因此：

```text
CASE-001 solver timeout after 120 s
CASE-013 solver timeout after 121 s
CASE-078 solver timeout after 119 s
```

可聚合成同一类问题。

每个问题包含：

- severity；
- occurrence count；
- first / last occurrence；
- affected tasks；
- affected cases；
- problem score；
- recommendation。

当前内置诊断规则覆盖：

- timeout；
- license waiting/failure；
- Worker heartbeat/process loss；
- Automation parameter/mapping；
- Data Factory/Dataset；
- disk/storage。

## 5. 系统告警状态机

Monitoring Plane 对以下异常采用“变化才记录”的策略：

- `DISK_HIGH`
- `DISK_CRITICAL`
- `MEMORY_HIGH`
- `MEMORY_CRITICAL`
- `WORKER_PROCESS_LOST`
- `WORKER_HEARTBEAT_STALE`
- `MOTORCAD_ORPHAN_CANDIDATE`

新问题产生 `SYSTEM_ALERT`；恢复产生 `SYSTEM_ALERT_RESOLVED`。监控接口每秒运行也不会每秒重复刷相同日志。

## 6. Diagnostic Bundle

GUI 或 API 可导出 ZIP：

```text
logs_filtered.jsonl
diagnostics.json
raw/studio.log
raw/studio.jsonl
raw/audit.jsonl
task_state.json      # 选择 Task 时
```

这应成为真实 Motor-CAD 工作站问题反馈的标准附件。

## 7. 离线分析

```bash
python scripts/analyze_logs.py --minutes 240
python scripts/analyze_logs.py --task-id TASK-XXXX --level WARNING
python scripts/analyze_logs.py --case-id TASK-XXXX-C0007 --level INFO
python scripts/analyze_logs.py --minutes 1440 --json > diagnostics.json
```

## 8. 后续扩展

V0.10 没有引入外部 ELK/Prometheus 基础设施。单机科研/工程工作站阶段，本地 JSONL + SQLite event + SSE 的复杂度更低。

当进入多节点求解后，可保持当前结构化事件合同，再增加 OpenTelemetry/Prometheus/Loki exporter，而不改变 Solver/Task 业务代码。
