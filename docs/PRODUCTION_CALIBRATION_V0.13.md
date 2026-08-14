# V0.13 目标工作站生产校准流程

## 推荐顺序

### 1. 环境

先执行浅检查和深度检查，确认 Motor-CAD EXE、PyMotorCAD、RPC 和进程清理正常。

### 2. 模板资格

对 i5、e9、e14 分别执行：

1. EMag Level 3；
2. EMag Level 4（勾选真实 Solver Smoke）；
3. Thermal Level 3；
4. Thermal Level 4。

production 模式下，没有对应 Level 4 证据的 Task 会被阻断。

### 3. 材料绑定

在任务编辑器选择目标材料，点击“目标 Motor-CAD 回读验证”。确认组件 material readback 与所选牌号一致。若目标 Motor-CAD 材料数据库不存在同名材料，应先选择/导入真实材料，不要只依赖 Studio 公共材料目录。

### 4. Graph 校准

进入 System -> 结果校准与 Graph 探测：

1. 选择模板；
2. 载入推荐 Graph；
3. 对照 Motor-CAD Help -> Graph Viewer 修改名称；
4. 如结果需要前置求解，勾选“探测前先执行一次真实计算”；
5. 执行探测；
6. VERIFIED 条目自动进入运行时结果提取覆盖。

建议至少校准：

- TorqueVW；
- B Gap (on load)；
- Torque harmonics；
- 目标模板使用的 Temperature/Heatflow graph；
- 计划进入 Result Viewer 的 Magnetic3dGraph。

### 5. 批量稳定性

完成校准后再运行：

- i5 EMag 100 Case；
- e9 EMag 100 Case；
- e14 EMag/Thermal 100 Case；
- e14 LHS 500 Case。

重点检查：

- 无孤立 Motor-CAD；
- 无参数串案；
- Graph calibration 没有跨模板误用；
- cache fingerprint 随 calibration 变化正确失效；
- Data Factory lineage 能定位 qualification/material/result calibration 证据。
