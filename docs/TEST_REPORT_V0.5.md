# MotorCAD Studio V0.5 测试报告

日期：2026-08-11

## 自动回归

```text
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
pytest -q
```

结果：`28 passed`。

新增覆盖：

- Automation Parameter Names 表格解析；
- Automation Registry 版本/机型/上下文存储；
- Installation Manager 显式 EXE 和版本识别；
- 官方 API Catalog 和分析配方加载；
- System API capability endpoint；
- Automation Registry API import/read；
- Template dynamic UI schema 与电机家族识别；
- 官方示例 Solver Controls 注册与校验；
- Solver Settings 按 Context 分组写入；
- 官方变量候选优先级；
- Graph 批量提取与逐点回退；
- 原生 `export_results()` 归档辅助函数。

## Coverage

当前容器覆盖率为 **66%**。新增 Installation Manager 和真实 MotorCADAdapter 的大量 Windows/RPC 分支不能在无 Motor-CAD 的 Linux 容器中执行，因此总体覆盖率相较 V0.4 下降。业务/配置层仍具有较高覆盖；真实 Motor-CAD 适配器必须通过 Windows Integration Test 单独统计。

## 未覆盖的真实物理验收

- Motor-CAD 2026R1 实际 EXE 发现；
- Automation registration 检测的真实失败模式；
- EMag/Therm/Lab/Mechanical 许可证；
- 所有参数单位；
- 材料组件名；
- 图表名称；
- 并行许可证行为；
- 100 Case 稳定性。
