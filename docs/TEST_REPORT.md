# V0.3 自动测试报告

执行命令：

```text
python -m compileall -q motorcad_studio scripts
node --check motorcad_studio/static/app.js
pytest -q
```

结果：

```text
11 passed
```

已验证：

1. 33套模板可加载；
2. e9 同名 `Shaft_Speed` 按 `Miscellaneous` 分区解析为6000 rpm；
3. Mock任务可通过独立子进程完成；
4. 慢速求解超过限制后进入TIMEOUT；
5. 强制取消能够终止子进程；
6. 求解成功与结果质量状态独立；
7. Mock结果标记为UNVERIFIED且不可进入正式缓存；
8. 仿真指纹包含模板文件哈希；
9. 有效缓存命中后成果会克隆到新Case目录；
10. 基准结果可捕获并生成误差比较报告；
11. CSV、HTML和ZIP导出保持兼容。
