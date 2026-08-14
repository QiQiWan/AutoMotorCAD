# V0.11 Test Report

执行：

```text
PYTHONPATH=. pytest -q
```

结果：

```text
47 passed
```

同时执行：

```text
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
```

## V0.11 新增专项覆盖

- material catalog API 与 N40UH public-reference 元数据；
- Project 删除；
- Monitoring alert transition 日志调用回归，防止 `/api/system/metrics` 再次因 `StructuredLogStore.log` 参数错误而 500；
- Mock Case Result Viewer / Map2D / Artifact；
- shallow preflight；
- 工作区刷新、DOE Seed、Data Factory Seed、日志实时开关等稳定 DOM ID；
- V0.10 diagnostic bundle 测试继续通过，覆盖滚动日志导出逻辑。

## 未在本环境执行

本容器没有真实 Motor-CAD 与许可证，因此没有声称以下内容已通过物理验收：

- i5/e9/e14真实FEA结果；
-真实材料数据库匹配；
-真实二维场图 Graph Viewer 名称；
-真实许可证 checkout；
-不同Motor-CAD版本的深度检查。
