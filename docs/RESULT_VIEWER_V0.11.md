# V0.11 Engineering Result Viewer

## 目标

结果查看器不是一个简单 CSV 表，而是 Motor-CAD Studio 的核心工程分析工作区。它将 Motor-CAD 多种结果统一到一个 Case 视图，同时严格区分：

- 当前 Case 已实际提取的数据；
- Motor-CAD/PyMotorCAD 理论支持的可视化能力。

没有数据的模块会禁用，不伪造结果。

## 模块

### 结果总览

执行状态、质量状态、关键 KPI、质量标志和警告。

### 性能指标

转矩、转矩脉动、效率、输出功率、峰值线电压等；未来承接 torque-speed envelope。

### 损耗分析

铜耗、定子铁耗、永磁体损耗和总损耗，并计算已提取分项占比。

### 输入与模型快照

工程参数、Scenario、材料、Solver Settings、Automation Overrides 和 simulation fingerprint。

### 电磁波形

基于 `get_magnetic_graph` 等批量 Graph API，支持转矩、反电动势、磁链、气隙磁密等序列。

### 谐波

使用 `get_magnetic_graph_harmonics` 等接口形成 spectrum 结果。

### FEA场结果

统一 `map2d / field` 数据合同。V0.11 Adapter 已提供 `get_magnetic_3d_graph` 的 registry-driven 提取入口，返回值标准化为：

```json
{
  "x": [],
  "y": [],
  "z": [[]],
  "x_label": "...",
  "y_label": "...",
  "z_label": "...",
  "source": "Motor-CAD Graph Viewer name"
}
```

具体 graph name 必须由目标 Motor-CAD 模型/版本验证，不能跨模板硬编码。

### Thermal

温度曲线、热流曲线、温升与未来热场 Map2D。

### Lab

目标包括：

- Torque-Speed Envelope；
- Efficiency Map；
- Loss Map；
- Operating Point；
- Duty Cycle。

### Mechanical / NVH

应力、力谐波、多工况力数据和 NVH 结果。

### Native results & audit

MOT、Motor-CAD原生 CSV、参数回读、输出审计、日志和 checkpoint。

## Mock 场图

Mock solver 生成的场图只用于验证 Viewer 的 heatmap/hover/模块导航，字段包含 `synthetic=true`。GUI 会明确显示“不可用于工程判断”。
