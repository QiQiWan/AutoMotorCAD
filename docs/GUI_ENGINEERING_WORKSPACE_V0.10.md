# V0.10 Engineering Workspace 与人机交互设计

## 目标

V0.9 的后端工程对象已经形成，但前端仍偏“功能页面”。V0.10 首次把 Project、Design 和 immutable Design Revision 提升为主交互对象。

## 1. Engineering Workspace

三栏结构：

```text
Project Tree | Design Workspace | Property Inspector
```

Project Tree 展示：

- Designs；
- Scenarios；
- Experiments。

Design Workspace 展示：

- RFPM / AFPM schematic；
- Design metadata；
- Revision rail；
- parameter snapshot；
- traceability hash。

Inspector 展示当前选中对象的工程属性和验证状态。

### Revision 工作流

```text
Template
  -> Create Design
  -> Revision 1
  -> Clone Revision
  -> Revision 2
  -> Use Revision as Task Start
```

用户计算时不覆盖原 Design Revision，而是把 Revision 快照加载到 Task Builder。

## 2. Template Topology Browser

模板卡片新增：

- RFPM / AFPM topology schematic；
- maturity；
- Motor-CAD version；
- rating summary；
- Compare selection。

最多可同时比较三套模板，比较拓扑、Motor Type、成熟度、功率、转速、极槽、气隙、冷却、版本和能力。

## 3. Engineering Parameter Inspector

V0.10 增加：

- 参数全文搜索；
- `changed only`；
- 与模板 default 的变化高亮；
- Changed parameter count；
- Reset changed values。

这降低复杂模板中查找用户实际修改项的成本。

后续仍建议把 Fixed / Sweep / Optimize role 合并到同一个参数控件中。

## 4. Calculation Visualization

在 V0.9 的 SSE / Worker / PID / Case Matrix / Stage Pipeline 基础上增加：

### Stage Performance

按历史完成 Stage 显示：

- sample count；
- mean；
- median；
- P95；
- max。

用于判断真正瓶颈发生在 EMag、Thermal、Extraction 还是 Archive。

### Waiting Reason

Pending Case 不再只显示 PENDING，而区分：

- `WAITING_FOR_LICENSE`
- `WAITING_FOR_WORKER_OR_LICENSE`
- `STARTING_SOLVER`
- `RECOVERING_FROM_CHECKPOINT`
- `PRECHECK`
- `QUEUED`

用户可以直接理解“为什么还没有运行”。

## 5. Logs & Problems Center

一级页面新增：

- Observability metrics；
- aggregated Problems；
- structured logs；
- level/component/task/case/stage/keyword filters；
- real-time SSE；
- Task/Case jump links；
- diagnostic bundle export。

## 6. 视觉规范

V0.10 开始强化工业/CAE 信息密度：

- Card 主要用于 KPI / 独立模块；
- 参数采用 Property Grid；
- Project 使用 Tree；
- Design Revision 使用 rail；
- 日志采用 dense table；
- 状态始终使用颜色 + 文本，不仅依赖颜色。

## 尚未完成

以下仍建议放入后续工程工作台迭代：

- 真正参数驱动的几何尺寸变化，目前 schematic 主要表达拓扑；
- Winding Designer；
- Material Manager；
- Cooling Network Designer；
- Linked Selection across Pareto / geometry / table / curves；
- Design Compare candidate promotion；
- Map2D efficiency/loss/thermal views；
- React + TypeScript 前端组件化。
