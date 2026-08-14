# V0.17 Test Report

最终回归环境执行：

```text
PYTHONPATH=. pytest -q
94 passed
```

同时执行：

```text
python -m compileall -q motorcad_studio scripts tests
node --check static/app.js
node --check static/production.js
node --check static/geometry.js
node --check static/realtime.js
node --check static/i18n.js
node --check static/locale-data.js
node --check static/workflow.js
```

全部通过。

V0.17 新增专项覆盖：

- validate 请求携带 Project/Design/Scenario 工程上下文；
- Design Revision 跨 Project 阻断；
- Design Revision 与 Template 错配阻断；
- Project-aware workflow readiness；
- Project-scoped Dataset Registry；
- Design Revision explicit parameter intent 持久化和 Solver 合并；
- 产品 Runtime Gate 在 Task 创建之前阻断不可用 Motor-CAD；
- Workflow ribbon / Design Revision Save 前端契约。

注意：自动测试不能替代目标 Windows 工作站上的真实 Motor-CAD / License / FEA / Lab 验收。
