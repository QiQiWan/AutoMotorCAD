# V0.11 非开发人员交互设计

## 基本原则

普通工程师默认只需要理解五个对象：

1. 模板；
2. 工程参数；
3. 材料与运行场景；
4. 自动化任务；
5. 结果。

Motor-CAD Automation Name、API drift、原生 solver variable、版本注册表属于开发/维护层，默认折叠。

## 推荐操作路径

```text
选择模板
  ↓
修改工程参数
  ↓  实时快速几何预览
选择常用材料
  ↓
配置工况
  ↓
第一次先“单次计算”
  ↓
预检查
  ↓
提交任务
  ↓
实时监控
  ↓
结果查看器
  ↓
需要时再做扫描 / DOE / NSGA-II
```

## 工程参数编辑器

每个参数呈现：

- 中文工程名称；
- 单位；
- 当前值；
- 模板默认值；
- 实机验证状态；
- `?` 工程作用说明；
- 折叠的 canonical ID / Motor-CAD variable / context。

这样普通用户不需要理解 Automation variable；维护人员仍可以追踪实际映射。

## 高级区域

高级区域默认关闭：

- Expert Automation；
- curated Solver Controls；
- raw solver variables；
- Automation registry importer；
- PyMotorCAD API compatibility audit。

其中 raw solver variables 明确标注“普通用户不要填写”。

## 双语

顶部 `EN / 中` 切换。中文是默认工程操作语言；英文模式保留用于文档、论文截图和跨团队协作。
