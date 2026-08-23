from __future__ import annotations

import html
import json
import zipfile
from pathlib import Path
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_scalars(scalars: dict[str, Any], output_schema: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in scalars.items():
        definition = output_schema.get(key, {})
        label = html.escape(str(definition.get("label", key)))
        unit = html.escape(str(definition.get("unit", "")))
        parts.append(f"<div><b>{label}</b>: {html.escape(_fmt(value))} {unit}</div>")
    return "".join(parts) or "-"


def _render_flags(flags: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for flag in flags:
        severity = html.escape(str(flag.get("severity", "")).lower())
        code = html.escape(str(flag.get("code", "")))
        message = html.escape(str(flag.get("message", "")))
        parts.append(f'<div class="flag {severity}">{code}: {message}</div>')
    return "".join(parts) or "-"


def build_html_report(task: dict[str, Any], output_path: Path, output_schema: dict[str, Any]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for case in task.get("cases", []):
        result = case.get("result") or {}
        scalars = result.get("scalars", {})
        flags = result.get("quality_flags", [])
        parameters = html.escape(json.dumps(case.get("parameters", {}), ensure_ascii=False, indent=2))
        rows.append(
            "<tr>"
            f"<td>{html.escape(case['id'])}</td>"
            f"<td>{html.escape(case['status'])}</td>"
            f"<td>{html.escape(str(case.get('execution_status','-')))}</td>"
            f"<td>{html.escape(str(case.get('quality_status','-')))}</td>"
            f"<td><pre>{parameters}</pre></td>"
            f"<td>{_render_scalars(scalars, output_schema)}</td>"
            f"<td>{_render_flags(flags)}</td>"
            "</tr>"
        )
    request_json = html.escape(json.dumps(task.get("request", {}), ensure_ascii=False, indent=2))
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(task['name'])}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:32px;color:#1d2939}}h1{{margin-bottom:4px}}.meta{{color:#667085;margin-bottom:24px}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #d0d5dd;padding:8px;vertical-align:top;text-align:left}}th{{background:#f2f4f7}}pre{{white-space:pre-wrap;max-width:380px;margin:0}}.flag{{margin:3px 0}}.blocking,.error{{color:#b42318}}.warning{{color:#b54708}}.info{{color:#175cd3}}
</style></head><body>
<h1>{html.escape(task['name'])}</h1>
<div class="meta">任务 {html.escape(task['id'])}｜项目 {html.escape(task['project_name'])}｜模板 {html.escape(task['template_id'])}｜状态 {html.escape(task['status'])}</div>
<h2>任务配置</h2><pre>{request_json}</pre>
<h2>算例结果</h2>
<table><thead><tr><th>Case</th><th>流程状态</th><th>执行状态</th><th>质量状态</th><th>参数</th><th>结果</th><th>质量标志</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
    output_path.write_text(body, encoding="utf-8")
    return output_path


def build_task_zip(task: dict[str, Any], task_dir: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if task_dir.exists():
            for path in task_dir.rglob("*"):
                if path.is_file() and path.resolve() != output_path.resolve():
                    archive.write(path, path.relative_to(task_dir.parent))
        manifest = json.dumps(task, ensure_ascii=False, indent=2, default=str)
        archive.writestr(f"{task['id']}/task_manifest.json", manifest)
    return output_path
