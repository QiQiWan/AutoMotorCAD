# V0.7 Delivery Notes

V0.7 将 V0.6 的实时仿真驾驶舱推进为 DOE、多目标候选筛选与高可靠运行底座。

本版本交付：

- Full Factorial、Latin Hypercube、Random DOE 与 Pareto Search 候选空间；
- Pareto rank、crowding metadata、平行坐标和多 Case 曲线叠加；
- EMag / Thermal / Lab / Mechanical 平台侧 LicensePool；
- EMag→Thermal 输入签名检查点与 MOT/结果阶段恢复；
- Task 级 `optimization_summary.json` Artifact；
- 许可证使用态势、等待量与优化结果实时 GUI；
- 36 项自动测试和 13 Case 独立 Pareto Mock 冒烟测试；
- 多进程 Queue feeder thread 显式清理，完整测试进程可稳定退出。

## 需要实机确认的边界

当前容器没有 Motor-CAD 与许可证，因此以下能力只完成代码路径，尚未完成物理验收：

- EMag checkpoint MOT 在新 Motor-CAD 实例中的恢复一致性；
- 实际许可证容量与平台 `LicensePool` 配置的对应关系；
- `reuse_parallel_instances` 多模板长期复用状态；
- Lab / Mechanical 并发；
- i5 / e9 / e14 真实 100+ Case DOE 稳定性。

`Pareto Search` 当前是固定设计空间采样后的非支配筛选，不应表述为自适应 NSGA-II。真正动态生成新 Case 的优化器建议在 V0.8 实现。
