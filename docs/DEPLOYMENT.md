# 部署说明

## 1. 完整替换部署

正式发布包内只有一个顶层目录：

```text
AutoMotorCAD_Studio
```

部署时执行：

1. 关闭浏览器中的 MotorCAD Studio 页面。
2. 停止旧 Python/Uvicorn 进程。
3. 确认旧程序启动的 Motor-CAD 进程已结束；仍在运行的手工 Motor-CAD 实例不要强制关闭。
4. 备份旧程序目录中人为保存的数据文件。
5. 删除旧程序目录。
6. 解压新包并复制完整 `AutoMotorCAD_Studio` 文件夹。
7. 双击 `start.bat`。
8. 页面打开后执行一次 `Ctrl + Shift + R`。

不要把新文件逐项覆盖到旧目录。内容门禁会拒绝未声明的旧 Python、JavaScript、CSS 和配置文件。

## 2. 一键启动流程

`start.bat` 按以下顺序寻找 Python：

1. `MOTORCAD_STUDIO_PYTHON`；
2. Windows Python Launcher 的 `py -3`；
3. PATH 中的 `python`。

启动器随后执行：

1. Python 3.10+ 检查；
2. 完整分发包校验；
3. `.venv` 创建或修复；
4. 系统级/Conda PyMotorCAD 包路径映射；
5. 缺失 Web 依赖安装；
6. Release Version Sync 检查；
7. Module Audit；
8. 端口占用检查；
9. Uvicorn 启动；
10. 健康接口就绪等待；
11. 浏览器打开。

启动日志：

```text
AutoMotorCAD_Studio\logs\startup.log
```

## 3. 常用命令

```bat
start.bat --check-only
start.bat --mock
start.bat --no-browser
start.bat --host 127.0.0.1 --port 8766
start.bat --skip-install --check-only
```

直接使用 Python 验证：

```powershell
python -m motorcad_studio.tools.sync_release_versions --check
python -m motorcad_studio.tools.module_audit
python -m motorcad_studio.tools.validate_release
python -m pytest -q
```

直接启动：

```powershell
python -m uvicorn motorcad_studio.main:app --host 127.0.0.1 --port 8765
```

## 4. 数据与环境变量

默认数据根目录：

```text
%LOCALAPPDATA%\MotorCADStudio\data
```

常用覆盖变量：

```text
MOTORCAD_STUDIO_DATA_DIR
MOTORCAD_STUDIO_RUNTIME_DIR
MOTORCAD_STUDIO_RESULTS_DIR
MOTORCAD_STUDIO_LOG_DIR
MOTORCAD_STUDIO_PYTHON
MOTORCAD_STUDIO_HOST
MOTORCAD_STUDIO_PORT
```

删除程序目录前，检查旧版本是否把数据写在程序目录内。发现 `data`、`runtime`、`results`、`logs` 或自定义模型文件时，先备份再清理。

## 5. Motor-CAD 工作站要求

正式原生计算需要：

- Windows；
- Motor-CAD 2026 R1；
- 有效许可证；
- 可由当前 Python 环境导入的 PyMotorCAD；
- 对项目结果目录和临时目录的读写权限；
- 允许本地回环地址 `127.0.0.1`；
- 足够的内存、磁盘空间和 GPU 驱动。

运行时由本地 Scheduler 原子分配 Worker Slot、许可证容量和内存预算。TaskManager 同时取得持久 Native Lease 和 Fencing Token。工作站时间异常、进程被外部强杀或数据库不可写时，任务会进入失败或恢复路径，不应绕过门禁直接修改数据库。

## 5.1 根目录日志

0.91.3 默认将支持诊断日志固定写入程序根目录 `logs`：

```text
logs/
├─ README.txt
├─ startup.log
├─ current_session.json
├─ studio.log
├─ studio.jsonl
├─ http.jsonl
├─ preflight.jsonl
├─ errors.log
├─ errors.jsonl
├─ frontend.jsonl
├─ tasks/
├─ cases/
└─ snapshots/preflight/
```

出现启动、运行环境检查、任务或工况异常时，优先保留整个 `logs` 目录。该目录属于运行时可变目录，不参与发布包不可变文件哈希检查。

## 6. 常见故障

### 包完整性失败

0.91.3 的完整性门禁只覆盖不可变程序文件；`data`、`runtime`、`results`、`logs`、`baselines` 和 `factory` 属于运行时状态，不会触发 `UNEXPECTED_FILE`。

如果仍出现 `UNEXPECTED_FILE`，说明程序目录中存在清单之外的代码、脚本、样式或其他不可变文件，应删除旧程序目录并重新解压完整发布包。`FILE_HASH_MISMATCH` 或 `MISSING_FILE` 同样表示正式程序文件被修改、缺失或混装。

从 0.91.0 升级时，如果旧目录里已经出现 `data/runtime/diagnostics/...`，可以保留或备份这些运行证据；0.91.3 不再把它们当作程序篡改。若系统环境变量 `MOTORCAD_STUDIO_*_DIR` 指向当前程序目录，正式安装启动器会自动忽略这些旧的目录覆盖并使用用户配置目录。

### 端口占用

关闭旧 Uvicorn/Python 进程，或使用：

```bat
start.bat --port 8766
```

### Python 或依赖识别错误

指定已验证的 Python：

```bat
set MOTORCAD_STUDIO_PYTHON=C:\Path\To\python.exe
start.bat --check-only
```

### 页面仍显示旧界面

确认服务版本为 0.91.9，随后执行 `Ctrl + Shift + R`。仍异常时关闭全部相关浏览器标签并重新打开。

### Motor-CAD 无法启动

先执行 `start.bat --check-only`，再检查安装路径、PyMotorCAD、许可证、工作目录权限和日志。不要同时运行多个旧版本 Studio 实例。


### 深度运行环境检查异常

界面中的一次“Motor-CAD 深度检查”只允许一个前台 operation。系统轮询和后台 GET 不再计入“请求进行中”数量。后端也会合并并发深度检查，避免双击或页面重试重复启动 Motor-CAD。

若检查失败，依次查看：

1. `logs/preflight.jsonl`：检查进程生命周期、超时和清理报告；
2. `logs/errors.log`：可读错误摘要；
3. `logs/errors.jsonl`：完整结构化错误及 HTTP traceback；
4. `logs/http.jsonl`：`/api/system/preflight` 请求耗时与状态；
5. `logs/snapshots/preflight/`：每次检查的结果快照。

## 7. 路由或按钮现场排错

页面刷新后状态异常时，先确认地址保持在 `/app/...`，然后执行 `Ctrl + Shift + R`。0.91.4 会根据 URL 从后端重新恢复项目上下文。

按钮点击后没有反应时，不需要只依赖浏览器控制台。等待约 1 秒后检查：

```text
logs/frontend.jsonl
logs/http.jsonl
logs/errors.log
```

`FRONTEND_BUTTON_NO_EFFECT` 表示点击后没有检测到路由、HTTP 请求、DOM 状态或忙碌状态变化；`FRONTEND_BUTTON_BINDING_GAP` 表示运行时 HMI 资格检查发现可见按钮缺少处理器证据。上传整个 `logs` 目录可同时保留前端、HTTP、Task、Case 和错误链路。
