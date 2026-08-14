# PyMotorCAD Stable 官方文档 → MotorCAD Studio V0.5 对接矩阵

日期：2026-08-11

## 1. 对接原则

V0.5 将官方文档中的能力拆成两个独立层次：

1. **PyMotorCAD API**：描述 Motor-CAD 可以执行哪些动作，例如启动实例、加载模型、切换上下文、执行 EMag/Thermal/Lab/Mechanical、材料管理、图表和 FEA 结果读取。
2. **Automation Parameters**：描述具体模型中有哪些可设置/读取变量。该列表与 Motor-CAD 版本、Motor Type 和 Context 有关，应从目标 Motor-CAD 的 `Help -> Automation Parameter Names` 导出。

因此系统不会把 API 文档错误当作“全量模型变量说明书”。

## 2. API 方法域

当前内置 Catalog 登记：

| 方法域 | 登记方法数 | V0.5 用途 |
|---|---:|---|
| Calculations | 15 | EMag、Thermal、Coupled、Mechanical 等求解 |
| General | 37 | 模板/MOT、消息、许可证、结果导出、实例生命周期 |
| Variables | 9 | 标量/数组变量读写与数据存取 |
| Geometry | 3 | 绕组与几何有效性检查 |
| AdaptiveGeometry | 17 | Adaptive Template 扩展入口 |
| FEAGeometry | 30 | FEA 几何、区域、路径、损耗和原始数据 |
| Graphs | 12 | EMag/Thermal/FEA/Harmonics 曲线 |
| InternalScripting | 3 | 内部脚本兼容能力 |
| Lab | 19 | 模型构建、工作点、磁/热、Duty Cycle |
| Materials | 11 | 材料数据库、组件材料、冷却介质 |
| Thermal | 22 | 热节点、热阻、热容、固定温度、外部回路 |
| UI | 13 | Context、可见性、消息与界面控制 |
| Utility | 2 | 文件/实例状态 |

另登记 3 个模块级 utility functions：`set_default_instance`、`set_motorcad_exe`、`set_server_ip`。

## 3. 当前平台配置覆盖

### 3.1 Canonical 工程参数

当前 23 项，覆盖主要几何、磁体、绕组、工作点和基础热边界。它们具备统一语义、单位转换、范围校验和版本映射。

### 3.2 Curated Solver Controls

当前 26 项：

- EMag：12；
- Therm：2；
- Lab：12；
- Mechanical：0（不猜测，使用 Automation Registry）。

### 3.3 Expert Automation Parameters

通过导入目标版本的 Automation Parameter Names 动态扩展，理论上可以把目标版本实际暴露的长尾变量全部带入系统，而不要求平台预先硬编码。

## 4. 主要电机形式

33 套原始模板已经覆盖 RFPM-SPM、RFPM-IPM、Spoke、AFPM、BPMOR、IM、IM1PH、SYNC、SynRel 和 SRM。V0.5 已建立 15 套 curated profile。

PMDC、CLAW-Therm 没有现成模板；真正空心杯/无铁心杯形绕组应使用专项 Adaptive/高保真路线，系统不标记为已完成。

## 5. 零人工运行链路

完成 Motor-CAD 官方要求的一次性 Automation registration 后，正常 Case 链路为：

```text
扫描/选择 Motor-CAD EXE
→ set_motorcad_exe
→ MotorCAD()
→ 隐藏 GUI / 禁止弹窗
→ 加载已验证 MOT
→ 按 Context 写入并回读参数
→ 几何校验
→ 求解
→ 批量 Graph / Scalar / 原生 CSV 提取
→ 保存检查点与审计
→ quit 或 set_free
```

用户不需要在每个 Case 中操作 Motor-CAD GUI。

## 6. 仍需 Windows 实机确认

- 各 Motor Type / Context 的 Automation Parameter Names 实际导出和单位；
- i5/e9/e14 的本地已验证 MOT；
- 各许可证的真实 checkout 行为；
- Mechanical 专家变量；
- 材料组件名和冷却类型名；
- Graph Viewer 中不同模板的具体曲线名；
- Lab/Mechanical/AFPM 的版本限制；
- 多实例并行、BlackBox licence 和长期稳定性。

这些项目无法用没有 Motor-CAD 和许可证的 Linux 容器替代验证。
