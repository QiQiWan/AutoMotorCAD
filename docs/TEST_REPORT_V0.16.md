# V0.16 Test Report

## Automated regression

```text
85 passed in 18.68s
```

同时通过：

```text
python -m compileall -q motorcad_studio scripts tests
node --check motorcad_studio/static/app.js
node --check motorcad_studio/static/production.js
node --check motorcad_studio/static/geometry.js
node --check motorcad_studio/static/realtime.js
node --check motorcad_studio/static/i18n.js
node --check motorcad_studio/static/locale-data.js
```

## V0.16 专项覆盖

- e14 `slot_count` → `Stator_Poles` / `Stator_Pole_Angle` 联动；
- e14 template interaction notes；
- Studio 抽象材料组件 → Motor-CAD 实际组件别名解析；
- 正式前端 Motor-CAD-only / Project-first 合同；
- 日志诊断 ZIP 导出；
- offline runtime diagnostics client contract。

## 尚未自动验收

当前容器无 Motor-CAD 与工程许可证，因此以下必须在目标 Windows 工作站完成：
- e14 baseline geometry；
- e14 slot-count runtime qualification；
- 真实组件材料 set/get；
- EMag/Thermal/Lab 求解和结果提取。
