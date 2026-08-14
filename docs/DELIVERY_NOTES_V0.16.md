# V0.16 Delivery Notes

建议完整替换旧版本目录，不要只覆盖静态资源或 Python 文件。

升级后首先确认：
1. 页面和 `/api/health` 都显示 `0.16.0`；
2. 顶部选择当前 Project；
3. System 绑定目标 `Motor-CAD.exe`；
4. e14 不改参数做真实几何检查；
5. 再测试单独修改 `slot_count`；
6. 材料保持“沿用模板”，除非已经完成目标材料验证；
7. 失败时导出诊断包并保留 Case `model_validation.json` / `parameter_audit.json`。

正式交付包不应包含开发期 SQLite、Task结果、日志或 Dataset。Mock 只保留在测试代码内部，不作为产品计算模式。
