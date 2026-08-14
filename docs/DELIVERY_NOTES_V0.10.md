# V0.10 Delivery Notes

## 运行前

正常开发模式：

```bat
setup_windows.bat
run_windows.bat
```

真实 Motor-CAD 工作站首次部署继续参考 `docs/MOTORCAD_ONBOARDING.md`。

## 推荐日志配置

开发：

```text
MOTORCAD_STUDIO_LOG_LEVEL=DEBUG
```

生产：

```text
MOTORCAD_STUDIO_LOG_LEVEL=INFO
MOTORCAD_STUDIO_LOG_MAX_BYTES=20971520
MOTORCAD_STUDIO_LOG_BACKUP_COUNT=8
MOTORCAD_STUDIO_LOG_RETENTION_DAYS=14
```

## 发生问题时

1. 进入 `日志与问题`；
2. 按 Task/Case 过滤；
3. 查看 Problems Center；
4. 查看实时监控 Stage/Waiting Reason；
5. 点击 `导出诊断包`；
6. 如需命令行分析，运行 `scripts/analyze_logs.py`。
