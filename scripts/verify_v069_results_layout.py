from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
CSS = (STATIC / "results-v069.css").read_text(encoding="utf-8")
WORKBENCH = (STATIC / "results" / "workbench.js").read_text(encoding="utf-8")
COMPARE = (STATIC / "results" / "revision-compare.js").read_text(encoding="utf-8")
CASE_COMPARE = (STATIC / "results" / "case-compare.js").read_text(encoding="utf-8")
OPTIMIZATION = (STATIC / "results" / "optimization.js").read_text(encoding="utf-8")

PROJECT = {
    "project": {"id": "P1", "name": "V0.69 layout"},
    "summary": {"designs": 1, "design_revisions": 3, "analyses": 1, "tasks": 2, "completed_tasks": 2, "usable_cases": 18, "optimization_tasks": 1},
    "native_parity": {"complete": False, "native_workstation_qualification_percent": 50},
    "designs": [{
        "id": "D1", "name": "SPM 基准电机", "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound", "revision_count": 3,
        "revisions": [
            {"id": "R1", "revision": 1, "content_hash": "111111111111"},
            {"id": "R2", "revision": 2, "content_hash": "222222222222"},
            {"id": "R3", "revision": 3, "content_hash": "333333333333"},
        ],
    }],
    "analyses": [{"id": "A1", "name": "额定点电磁分析", "recipe_id": "emag", "analysis_revision": 4, "analysis_revision_id": "AR4", "design_revision_id": "R3"}],
    "tasks": [
        {"id": "T1", "name": "额定点计算", "status": "COMPLETED", "case_count": 1, "usable_cases": 1, "optimization": False, "experiment_mode": "single"},
        {"id": "T2", "name": "气隙与磁体 Pareto", "status": "COMPLETED", "case_count": 17, "usable_cases": 17, "optimization": True, "experiment_mode": "nsga2"},
    ],
}

CASE_TASK = {
    "id": "T2", "name": "气隙与磁体 Pareto", "status": "COMPLETED", "analysis": "emag", "solver_mode": "motorcad", "design_revision_id": "R3",
    "request": {"analysis_definition_revision_id": "AR4", "design_revision_id": "R3"},
    "cases": [
        {"id": f"C{i}", "case_index": i - 1, "execution_status": "SUCCEEDED", "quality_status": "VALID",
         "scenario": {"shaft_speed_rpm": 3000, "peak_current_a": 20},
         "result": {"scalars": {"shaft_torque_nm": 10 + i * .2, "magnet_loss_w": 50 - i}}}
        for i in range(1, 10)
    ],
}

CASE_COMPARISON = {
    "comparison_scope": "same_task", "task_id": "T2", "baseline_case_id": "C1",
    "cases": CASE_TASK["cases"][:3],
    "quality": [{"case_id": f"C{i}", "execution_status": "SUCCEEDED", "quality_status": "VALID", "warnings": 0} for i in range(1, 4)],
    "traceability": [{"case_id": f"C{i}", "run_configuration_id": "RC1", "design_revision_id": "R3"} for i in range(1, 4)],
    "results": [
        {"key": "shaft_torque_nm", "label": "轴转矩", "unit": "Nm", "values": [{"case_id": f"C{i}", "value": 10 + i * .2, "relative_percent": 0 if i == 1 else i * 2} for i in range(1, 4)]},
        {"key": "magnet_loss_w", "label": "永磁体损耗", "unit": "W", "values": [{"case_id": f"C{i}", "value": 50 - i, "relative_percent": 0 if i == 1 else -i * 2} for i in range(1, 4)]},
    ],
    "parameters": [{"key": "air_gap", "label": "气隙", "unit": "mm", "values": [{"case_id": f"C{i}", "value": .7 + .05 * i, "relative_percent": i - 1} for i in range(1, 4)]}],
    "changed_domains": {"design": [], "scenario": [], "solver": []},
    "decision_summary": [{"case_id": f"C{i}", "pareto": i < 3, "improvements": ["shaft_torque_nm"], "regressions": ["magnet_loss_w"]} for i in range(1, 4)],
    "interpretation_boundary": "参数—结果影响为候选集描述性关系。",
}

CATALOG = {
    "analysis_definition_id": "A1", "analysis_name": "额定点电磁分析", "analysis_revision_id": "AR4",
    "design_revision_id": "R3", "design_revision": 3,
    "design": {"id": "D1", "name": "SPM 基准电机", "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound"},
    "load_cases": [{"index": 0, "scenario": {"shaft_speed_rpm": 3000, "peak_current_a": 20}}],
    "parameters": [
        {"id": "air_gap", "label": "气隙", "unit": "mm", "current": 0.8, "suggested_low": 0.7, "suggested_high": 0.9, "recommended": True},
        {"id": "magnet_thickness", "label": "永磁体厚度", "unit": "mm", "current": 5, "suggested_low": 4.5, "suggested_high": 5.5, "recommended": True},
        {"id": "stator_outer_diameter", "label": "定子外径", "unit": "mm", "current": 80, "suggested_low": 72, "suggested_high": 88, "recommended": True},
    ],
    "outputs": [
        {"id": "shaft_torque_nm", "label": "轴转矩", "unit": "Nm", "requested": True, "suggested_direction": "max"},
        {"id": "magnet_loss_w", "label": "永磁体损耗", "unit": "W", "requested": True, "suggested_direction": "min"},
        {"id": "efficiency_percent", "label": "效率", "unit": "%", "requested": True, "suggested_direction": "max"},
    ],
}

COMPARISON = {
    "design": {"id": "D1", "name": "SPM 基准电机", "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound"},
    "baseline_revision_id": "R1",
    "revisions": PROJECT["designs"][0]["revisions"],
    "changed_parameters": [
        {"id": "air_gap", "label": "气隙", "unit": "mm", "category": "geometry", "values": [
            {"revision_id": "R1", "value": 0.8, "relative_percent": 0},
            {"revision_id": "R2", "value": 0.75, "relative_percent": -6.25},
            {"revision_id": "R3", "value": 0.7, "relative_percent": -12.5},
        ]},
        {"id": "magnet_thickness", "label": "永磁体厚度", "unit": "mm", "category": "magnet", "values": [
            {"revision_id": "R1", "value": 5, "relative_percent": 0},
            {"revision_id": "R2", "value": 5.5, "relative_percent": 10},
            {"revision_id": "R3", "value": 6, "relative_percent": 20},
        ]},
    ],
    "changed_materials": [{"component": "Magnet", "values": [{"revision_id": "R1", "value": "N30UH"}, {"revision_id": "R2", "value": "N35UH"}, {"revision_id": "R3", "value": "N35UH"}]}],
    "result_evidence": [{"revision_id": rid, "task": {"id": f"T-{rid}", "name": "额定点"}, "case": {"id": f"C-{rid}", "quality_status": "VALID"}} for rid in ("R1", "R2", "R3")],
    "results_comparable": True,
    "comparability_note": "结果证据来自相同分析类型、工况和求解设置。",
    "result_rows": [{"id": "shaft_torque_nm", "label": "轴转矩", "unit": "Nm", "values": [
        {"revision_id": "R1", "value": 10, "relative_percent": 0}, {"revision_id": "R2", "value": 10.8, "relative_percent": 8}, {"revision_id": "R3", "value": 11.2, "relative_percent": 12},
    ]}],
}

BASE = f"""
<!doctype html><html><head><meta charset='utf-8'><style>
*{{box-sizing:border-box}}html,body{{margin:0;max-width:100%;font-family:Arial,sans-serif;color:#101828;background:#f2f4f7}}body{{padding:10px}}.panel{{background:#fff;border:1px solid #e4e7ec;border-radius:12px;padding:16px}}.section-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}}.actions{{display:flex;gap:8px;flex-wrap:wrap}}button,input,select{{font:inherit;max-width:100%}}button{{min-height:34px;padding:6px 10px}}label{{display:grid;gap:5px}}.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.hidden{{display:none!important}}.badge{{padding:5px 8px;background:#f2f4f7;border-radius:999px}}.help-empty{{padding:24px;display:grid;gap:6px;color:#667085}}small{{display:block;color:#667085}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border-bottom:1px solid #e4e7ec;text-align:left}}.primary{{background:#155eef;color:#fff;border:0}}
{CSS}
</style></head><body>
<div id='resultsWorkbenchV069' class='results-workbench-v069'></div><div id='resultsWorkbenchBodyV069' class='results-workbench-body-v069'></div><div id='viewerCaseMode' class='hidden'></div><div id='viewerBatchMode'></div><div id='resultsLegacyHeaderV069'></div><div id='toastStack'></div>
</body></html>
"""


def open_page(browser, width: int):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_content(BASE)
    page.add_script_tag(content=f"""
      window.state={{activeProjectId:'P1'}}; window.esc=v=>String(v??''); window.toast=()=>{{}};
      window.MCSRouter={{navigate:()=>true}}; window.MCSPageRuntime={{isContextActive:()=>true,isAbortError:()=>false}};
      const project={json.dumps(PROJECT, ensure_ascii=False)}; const catalog={json.dumps(CATALOG, ensure_ascii=False)}; const comparison={json.dumps(COMPARISON, ensure_ascii=False)}; const caseTask={json.dumps(CASE_TASK, ensure_ascii=False)}; const caseComparison={json.dumps(CASE_COMPARISON, ensure_ascii=False)};
      window.api=async (url,options={{}})=>{{
        if(url.includes('/results-workbench')) return structuredClone(project);
        if(url.includes('/optimization-catalog')) return structuredClone(catalog);
        if(url.includes('/revision-compare')) return structuredClone(comparison);
        if(url==='/api/tasks/T2') return structuredClone(caseTask);
        if(url.includes('/api/tasks/T2/result-comparison')) return structuredClone(caseComparison);
        throw new Error('unmocked '+url);
      }};
    """)
    page.add_script_tag(content=COMPARE)
    page.add_script_tag(content=CASE_COMPARE)
    page.add_script_tag(content=OPTIMIZATION)
    page.add_script_tag(content=WORKBENCH)
    return page, errors


def assert_no_root_overflow(page, width: int, errors: list[str]):
    page.wait_for_timeout(30)
    metrics = page.evaluate("() => ({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})")
    if metrics["scroll"] > metrics["client"] + 1:
        wide = page.evaluate("""() => [...document.querySelectorAll('*')].map(el=>({tag:el.tagName,cls:el.className||'',id:el.id||'',left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,scroll:el.scrollWidth,client:el.clientWidth})).filter(x=>x.right>document.documentElement.clientWidth+1||x.scroll>x.client+80).slice(0,30)""")
        raise AssertionError((width, metrics, wide))
    assert not errors, (width, errors)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        for width in (1500, 1000, 720):
            page, errors = open_page(browser, width)
            page.evaluate("() => window.MCSResultsWorkbenchV069.mount({projectId:'P1',resultsMode:'overview'})")
            page.wait_for_selector(".results-overview-v069")
            assert_no_root_overflow(page, width, errors)
            if width <= 680:
                page.set_viewport_size({"width": 660, "height": 1000})
                page.wait_for_timeout(20)
                assert page.eval_on_selector(".results-nav-v069", "el=>getComputedStyle(el).overflowX") in {"auto", "scroll"}
            page.close()

        for width in (1500, 980, 720):
            page, errors = open_page(browser, width)
            page.evaluate("() => window.MCSResultsWorkbenchV069.mount({projectId:'P1',resultsMode:'compare',designId:'D1',revisionIds:['R1','R2','R3'],autoCompare:true})")
            page.wait_for_selector(".revision-comparison-summary-v069")
            assert_no_root_overflow(page, width, errors)
            assert page.eval_on_selector(".comparison-table-scroll-v069", "el=>getComputedStyle(el).overflowX") in {"auto", "scroll"}
            page.close()


        for width in (1500, 980, 720):
            page, errors = open_page(browser, width)
            page.evaluate("() => window.MCSResultsWorkbenchV069.mount({projectId:'P1',resultsMode:'caseCompare',caseCompareTaskId:'T2',caseCompareCaseIds:['C1','C2','C3'],autoCaseCompare:true})")
            page.wait_for_selector(".case-comparison-result-v069")
            assert_no_root_overflow(page, width, errors)
            assert page.eval_on_selector(".case-comparison-result-v069 .comparison-table-scroll-v069", "el=>getComputedStyle(el).overflowX") in {"auto", "scroll"}
            page.close()

        for width in (1500, 980, 720):
            page, errors = open_page(browser, width)
            page.evaluate("() => window.MCSResultsWorkbenchV069.mount({projectId:'P1',resultsMode:'optimization',analysisId:'A1'})")
            page.wait_for_selector(".optimization-config-v069")
            page.click("[data-opt-add-constraint-v069]")
            page.wait_for_selector("[data-opt-constraint-row-v069]")
            assert_no_root_overflow(page, width, errors)
            columns = page.eval_on_selector(".optimization-grid-v069", "el=>getComputedStyle(el).gridTemplateColumns")
            if width <= 1000:
                assert " " not in columns.strip(), (width, columns)
            page.close()
        browser.close()
    print("V0.69 results/case-compare/revision-compare/optimization responsive layout: PASS")


if __name__ == "__main__":
    main()
