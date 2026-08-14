from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def capture_baseline(case: dict[str, Any], output_path: Path, *, notes: str = "") -> Path:
    result = case.get("result") or {}
    payload = {
        "schema_version": 1,
        "template_id": case.get("template_id"),
        "source_case_id": case.get("id"),
        "parameters": case.get("parameters", {}),
        "scalars": result.get("scalars", {}),
        "quality_status": case.get("quality_status"),
        "execution_status": case.get("execution_status"),
        "notes": notes,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return output_path


def compare_scalars(
    actual: dict[str, Any],
    baseline: dict[str, Any],
    tolerances: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tolerances = tolerances or {}
    rows: list[dict[str, Any]] = []
    keys = sorted(set(actual) | set(baseline))
    for key in keys:
        av = actual.get(key)
        bv = baseline.get(key)
        tolerance = tolerances.get(key, {})
        abs_tol = float(tolerance.get("absolute", 1e-6))
        rel_tol = float(tolerance.get("relative", 0.01))
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            absolute = abs(float(av) - float(bv))
            relative = absolute / max(abs(float(bv)), 1e-12)
            passed = absolute <= abs_tol or relative <= rel_tol
        else:
            absolute = None
            relative = None
            passed = av == bv
        rows.append(
            {
                "result_id": key,
                "actual": av,
                "baseline": bv,
                "absolute_error": absolute,
                "relative_error": relative,
                "absolute_tolerance": abs_tol,
                "relative_tolerance": rel_tol,
                "passed": passed,
            }
        )
    return rows


def build_comparison_report(
    *,
    case: dict[str, Any],
    baseline_payload: dict[str, Any],
    output_path: Path,
    tolerances: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actual = (case.get("result") or {}).get("scalars", {})
    rows = compare_scalars(actual, baseline_payload.get("scalars", {}), tolerances)
    passed = all(row["passed"] for row in rows)
    html_rows = []
    for row in rows:
        rel = "-" if row["relative_error"] is None else f"{100 * row['relative_error']:.4g}%"
        css = "pass" if row["passed"] else "fail"
        html_rows.append(
            f"<tr class='{css}'><td>{html.escape(row['result_id'])}</td>"
            f"<td>{html.escape(str(row['baseline']))}</td><td>{html.escape(str(row['actual']))}</td>"
            f"<td>{html.escape(str(row['absolute_error']))}</td><td>{rel}</td>"
            f"<td>{'通过' if row['passed'] else '未通过'}</td></tr>"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>基准对比</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei';margin:28px;color:#1d2939}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #d0d5dd;padding:8px;text-align:left}.pass{background:#ecfdf3}.fail{background:#fef3f2}</style></head><body>"
        f"<h1>Motor-CAD 自动化结果基准对比</h1><p>Case: {html.escape(case.get('id',''))}</p>"
        f"<p>结论：{'通过' if passed else '未通过'}</p>"
        "<table><thead><tr><th>结果</th><th>基准</th><th>自动化</th><th>绝对误差</th><th>相对误差</th><th>结论</th></tr></thead>"
        f"<tbody>{''.join(html_rows)}</tbody></table></body></html>",
        encoding="utf-8",
    )
    return {"passed": passed, "rows": rows, "report": str(output_path)}
