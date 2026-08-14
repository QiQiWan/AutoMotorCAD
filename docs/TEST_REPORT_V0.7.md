# MotorCAD Studio V0.7 测试报告

## 自动检查

```text
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
python -m pytest -q
```

最终结果：

```text
36 passed
```

## V0.7 新增专项测试

- Full Factorial Case 数量；
- Latin Hypercube 固定 seed 可重复性；
- DOE 参数范围；
- Pareto dominance / rank；
- Pareto front 识别；
- LicencePool acquire/release；
- Checkpoint input signature；
- 过期 checkpoint 拒绝恢复；
- Pareto Search Mock 完整任务；
- Optimization API；
- Parallel Coordinates 数据。

## 未在当前环境验证

当前容器没有安装并许可 Motor-CAD，因此以下必须在 Windows 实机验收：

- EMag checkpoint MOT 在新 Motor-CAD 实例中恢复后的物理一致性；
- `reuse_parallel_instances` 长时间运行状态残留；
- 实际许可证容量与 LicensePool 配置一致性；
- Lab / Mechanical 并发行为；
- 真实 100+ Case DOE 稳定性。
