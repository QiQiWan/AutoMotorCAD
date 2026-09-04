# MotorCAD Studio 0.92.0

MotorCAD Studio 是面向 Motor-CAD 的本地工程工作台，覆盖项目与方案管理、电机设计、材料配置、计算前检查、任务执行、结果查看、三维有限元场数据、优化、数据工厂、资格证据和原生运行时安全控制。

本发布包采用固定目录名 `AutoMotorCAD_Studio`。版本号只出现在发布压缩包名称和内部发布清单中，不再把 M、G、RC、Final、Updated 等阶段后缀写入正式目录或运行文件名。

## Windows 一键启动

建议使用完整替换部署：

1. 关闭 MotorCAD Studio 页面。
2. 在任务管理器中停止旧的 Python、Uvicorn 和由旧程序启动的 Motor-CAD 进程。
3. 备份旧程序目录中人为保存的 `data`、`runtime`、`results` 和 `logs`。
4. 删除旧程序目录。
5. 解压发布包，将完整的 `AutoMotorCAD_Studio` 文件夹复制到目标位置。
6. 双击根目录 `start.bat`。
7. 页面首次打开后执行一次 `Ctrl + Shift + R`。

`start.bat` 会完成 Python 识别、本地虚拟环境建立、缺失依赖安装、包完整性校验、版本与模块校验、端口检查、服务启动和浏览器打开。

仅检查部署环境，不启动服务：

```bat
start.bat --check-only
```

离线界面与流程验证：

```bat
start.bat --mock
```

不自动打开浏览器：

```bat
start.bat --no-browser
```

指定端口：

```bat
start.bat --host 127.0.0.1 --port 8766
```

工作站存在多个 Python 环境时，可显式指定：

```bat
set MOTORCAD_STUDIO_PYTHON=C:\Path\To\python.exe
start.bat
```

Python 版本要求为 3.10 或更高。正式 Motor-CAD 计算还要求目标工作站已安装并授权 Motor-CAD 2026 R1，以及与该安装匹配的 PyMotorCAD 环境。

## 数据目录

默认数据目录位于程序目录之外：

```text
%LOCALAPPDATA%\MotorCADStudio\data
```

`data`、`runtime`、`results`、`logs`、`baselines` 和 `factory` 属于运行时可变状态，不参与程序文件 SHA-256 清单。工程数据、结果和运行状态默认继续放在用户数据目录；诊断日志单独固定在程序根目录 `logs`，便于现场直接打包排查。

日志默认位于程序根目录：

```text
AutoMotorCAD_Studio\logs
```

其中 `startup.log`、`studio.log/jsonl`、`http.jsonl`、`preflight.jsonl`、`errors.log/jsonl`、`frontend.jsonl`、`tasks/`、`cases/` 和 `snapshots/` 分别保存启动、系统、HTTP、运行环境检查、错误、前端、任务、工况和诊断快照。替换程序目录前如需保留现场证据，应先备份 `logs`。工程数据库和结果仍默认位于 `%LOCALAPPDATA%\MotorCADStudio\data`。

## 当前架构状态

0.91.9 延续 0.91 系列的模块化架构，并进一步收敛设计资格/计算就绪两级门禁、ResultBundle evidence-first 结果工作台、单一 Binary FieldData FEA 渲染热路径以及真实热结果提取。

- Optimization、Data Factory、Qualification、Native Runtime Safety 和 Requirements 已进入统一事务控制平面，支持幂等命令、乐观并发、Transactional Outbox、不可变证据、租约和 Fencing Token。
- 后端公开处理器已按 13 个有界上下文物理拆分，兼容路由操作数为 0，全部 OpenAPI 操作带 `x-module-owner`。
- 浏览器只加载一个 ES Module 启动入口和一个样式文件；89 个历史源码由可复现的密封 Runtime Capsule 执行，事件、计时器、Observer、Worker、Fetch 和 WebGL 资源受统一生命周期控制。
- FieldData 支持 `MotorCADFieldDataBinaryV1`、TypedArray、Indexed Geometry、Range 请求、ETag、Topology Hash 复用、仅更新 Scalar Buffer、WebGL2 上下文恢复和 JSON/LOD 回退。

可读的 89 个历史前端源码仍保存在 `motorcad_studio/frontend_legacy`，用于差异定位和后续逐功能重写；浏览器不会逐文件装载这些源码，也不会允许它们直接污染产品全局命名空间。

## 发布前验证

在程序根目录执行：

```powershell
python -m motorcad_studio.tools.sync_release_versions --check
python -m motorcad_studio.tools.module_audit
python -m motorcad_studio.tools.validate_release
python -m pytest -q
```

有限元二进制链路性能诊断：

```powershell
python -m motorcad_studio.tools.benchmark_field_data --triangles 250000 --frames 30
```

当前自动化验证覆盖本地代码、API、事务、数据完整性、前端生命周期、二进制 FieldData 和合成性能。Licensed Motor-CAD 实际求解、真实百万级网格浏览器 GPU 性能和长时间工作站 Soak 需要在目标 Windows 工作站形成资格证据。

## 当前文档

- `docs/ARCHITECTURE.md`：模块边界、事务、前端和 FieldData 架构。
- `docs/DEPLOYMENT.md`：完整替换、一键启动和故障处理。
- `docs/VALIDATION.md`：完成度、自动化证据和资格边界。
- `docs/CHANGELOG.md`：当前稳定版本变更。
