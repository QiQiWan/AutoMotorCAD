# MotorCAD Studio V0.6 测试报告

## 自动测试

执行：

```text
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
pytest -q
```

结果：

```text
31 passed
```

新增测试覆盖：

- System metrics API；
- Solver pool / host telemetry数据结构；
- Task monitor API；
- Task stage / event cursor；
- Analytics dataset；
- 参数扫描结果统计；
- 不存在Task的404行为。

## 覆盖率

当前容器总体覆盖率约：

```text
67%
```

MotorCADSolverAdapter真实RPC分支仍受当前环境没有Motor-CAD程序和许可限制，其覆盖率明显低于平台业务层。

## 前端静态检查

- JavaScript语法检查通过；
- HTML直接ID引用审计完成；
- 仅 `cancelTask`、`forceCancelTask`、`retryTask`、`closeTemplateDetail` 为运行时动态创建元素。

## 尚需Windows实机验证

- SSE运行同时进行真实Motor-CAD长时间计算；
- Motor-CAD进程是否稳定保持在Worker进程树中；
- BlackBox许可下进程名/父子关系；
- 多实例并行时CPU/Memory聚合；
- 真实Case 100点持续监控；
- 浏览器长时间SSE重连稳定性。
