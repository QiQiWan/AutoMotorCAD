# V0.5 Motor-CAD 零接触运行接入

## 1. 官方前置条件

目标 Windows 机器必须安装有许可证的 Motor-CAD，并能被 PyMotorCAD 启动。目标 Motor-CAD 版本还需按官方说明完成 Automation registration。该动作是安装/升级后的环境初始化，不是每次仿真操作。

## 2. 自动发现与选择

```text
python scripts\scan_motorcad_installations.py --target 2026R1
```

也可以指定：

```text
python scripts\scan_motorcad_installations.py --select "C:\...\Motor-CAD.exe"
```

选择结果保存在 `data/runtime/motorcad_installation.json`。

## 3. 深度启动检查

```text
python scripts\bootstrap_motorcad.py
```

该脚本会：

```text
发现/选择EXE
→ set_motorcad_exe
→ MotorCAD()
→ 读取消息接口
→ quit
```

失败时首先检查：安装、Automation registration、许可证服务器、目标版本和 PyMotorCAD。

## 4. 导入 Automation 参数

为实际使用 Motor Type / Context 保存 Automation Parameter Names 文件，然后：

```text
python scripts\import_automation_parameters.py BPM_EMag.txt --machine-type BPM --context EMag --version 2026R1
```

真实工程建议对每一目标版本至少保存四类文件：EMag、Therm、Lab、Mechanical（仅对该 Motor Type 实际支持的 Context 导出）。

## 5. MOT 母版

使用现有 `onboard_motorcad_windows.bat` 生成 i5/e9/e14 验证 MOT，完成单 Case 人工结果基准后将 `MODEL_POLICY` 从 development 切到 validation。

## 6. 用户正常运行

环境初始化完成后，用户只需要操作 MotorCAD Studio：模板选择、参数、材料、场景、专家配置、分析类型和结果请求。Motor-CAD 本身可保持隐藏，实例由后台自动启动和退出。
