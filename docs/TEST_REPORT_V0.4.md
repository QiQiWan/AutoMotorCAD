# V0.4 自动测试报告

## 测试命令

```bash
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
pytest -q
pytest --cov=motorcad_studio --cov-report=term-missing -q
```

## 当前结果

```text
17 passed
```

总体代码覆盖率约：

```text
67%
```

高覆盖模块包括：

- config_schema：100%；
- db：约97%；
- models：约97%；
- template_service：约97%；
- registry：约80%；
- task_manager：约72%；
- solver_process：约72%。

MotorCADSolverAdapter 当前覆盖率约27%。主要原因是当前 CI/容器环境没有 Motor-CAD 软件和许可证，真实 RPC、许可证、上下文和 FEA 路径无法直接运行。

## V0.4 新增专项测试

1. `60 L/min → 0.001 m³/s → 60 L/min` 单位往返；
2. Therm 上下文写入只写热参数，并验证流量转换；
3. 几何有效性检查和绕组刷新调用；
4. 同一 Task 三个 Case 确实并行启动；
5. 配置中非法 conversion 在 Registry 构造期失败；
6. Validation 模式缺少本地 MOT 时阻断。

## 测试边界

自动测试能够验证平台逻辑，不能替代以下实机测试：

- Motor-CAD Automation Parameter 名称；
- 真实单位语义；
- 几何刷新行为；
- 许可证占用与释放；
- 实例复用；
- 电磁/热结果正确性；
- 连续 100 Case 稳定性。
