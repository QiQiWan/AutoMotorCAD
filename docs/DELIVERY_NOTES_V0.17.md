# V0.17 Delivery Notes

## 升级建议

建议完整替换旧版本代码目录，不要只复制 `static/` 或 Python 文件。V0.17 同时包含数据库 Schema 11、后端工程血缘规则和新的 `workflow.js`。

首次启动后数据库会自动补充 `design_revisions.explicit_parameter_ids_json`。旧 Revision 保持可读，explicit intent 默认为空。

## 推荐使用顺序

1. 启动 Studio；
2. 创建或选择 Project；
3. 从模板库选择模板，在当前 Project 中创建 Design；
4. 选择 Design Revision；
5. 修改参数，需要长期保留时先“保存为新 Revision”；
6. 选择或保存 Scenario Revision；
7. 运行快速预检查/几何检查；
8. 首次计算自动执行 Motor-CAD Runtime Gate；
9. 查看 Task/Case 实时状态；
10. 使用 Result Viewer；
11. Data Factory 只处理当前 Project 的 Task/Dataset。

## 本地诊断

Runtime Gate 的最新证据会写入：

```text
data/runtime/diagnostics/BOOT-*/runtime_gate.json
```

中央日志仍位于 `data/logs/`，Case 日志和审计文件位于对应结果目录。
