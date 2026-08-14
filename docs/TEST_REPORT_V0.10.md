# V0.10 Test Report

## Static / compile checks

```text
python -m compileall -q motorcad_studio scripts tests   PASS
node --check motorcad_studio/static/app.js             PASS
```

## Regression suite

```text
PYTHONPATH=. pytest -q
41 passed
```

V0.10 新增专项测试覆盖：

- structured JSONL / text logging；
- sensitive payload redaction；
- warning/error problem-signature aggregation；
- timeout/license diagnostic recommendations；
- diagnostic ZIP；
- HTTP `X-Request-ID` propagation；
- log query APIs；
- Task/Case solver-child correlation；
- Task timeline；
- per-Case `solver_runtime.jsonl` Artifact。

## Isolated smoke test

使用独立临时 runtime/results/factory/logs 目录执行 `scripts/smoke_test.py`：

```text
Studio version: 0.10.0
Templates: 33
Task: COMPLETED
Smoke test: PASS
```

随后直接对该临时日志目录运行：

```text
python scripts/analyze_logs.py --minutes 60
```

能够聚合 Mock `UNVERIFIED` Case warning，并列出受影响 Task/Case，验证日志生产 -> 聚合 -> CLI 分析链路成立。

## 边界

当前构建环境没有 Motor-CAD 程序和许可证，因此以下能力尚不能通过本机自动化测试证明：

- PyMotorCAD RPC 真实连接；
- Motor-CAD GUI hidden/blackbox lifecycle；
- 真实许可等待和回收；
- Motor-CAD FEA超时、崩溃和孤立进程诊断；
- 真正电磁/热结果与人工GUI基准的一致性。

这些必须使用 Windows + 目标 Motor-CAD + license 工作站执行 V0.10 实机验证方案。
