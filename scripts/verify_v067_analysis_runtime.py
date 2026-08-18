from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
EXECUTION = (STATIC / "analysis" / "execution.js").read_text(encoding="utf-8")

PLAN = {
    "analysis_definition_id": "ANL-V067",
    "analysis_name": "基准电磁计算",
    "project_id": "PRJ-V067",
    "module": "EMag",
    "recipe_id": "emag",
    "recipe": {
        "label": "电磁单点",
        "sections": [
            {"label": "运行点", "fields": [
                {"key": "shaft_speed_rpm", "target": "load_case", "label": "转速", "unit": "rpm"},
                {"key": "peak_current_a", "target": "load_case", "label": "峰值电流", "unit": "A"},
            ]},
            {"label": "求解", "fields": [
                {"key": "calculation_type", "target": "solver", "label": "计算类型"},
            ]},
        ],
    },
    "design": {"id": "DSN-1", "name": "BPM 基准电机", "motor_type_id": "BPM", "template_id": "i5"},
    "design_revision": {"id": "DREV-1", "revision": 4, "content_hash": "designhash123456"},
    "analysis_revision": {"id": "AREV-1", "revision": 3, "content_hash": "analysishash123456"},
    "load_cases": [{"shaft_speed_rpm": 3000, "peak_current_a": 20}],
    "case_count": 1,
    "input_domains": {"materials": {"magnet_material": "N30UH"}},
    "required_input_domains": ["materials"],
    "missing_required_input_domains": [],
    "solver_settings": {"calculation_type": "single"},
    "requested_outputs": ["shaft_torque_nm", "efficiency_percent"],
    "studio_precheck": {"valid": True, "blocking": 0, "warnings": 0, "issues": []},
    "task_validation": {"valid": True, "blocking": 0, "warnings": 0, "issues": []},
    "runtime_readiness": {"ok": True, "checks": [], "authority": "test"},
    "recent_tasks": [],
    "can_submit": True,
}


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_content("<body><div id='toastStack'></div></body>")
        page.add_script_tag(content=f"""
          window.__calls = [];
          window.__routes = [];
          window.state = {{activeProjectId:'PRJ-V067'}};
          window.esc = value => String(value ?? '');
          window.toast = () => {{}};
          window.MCSV060 = {{state:{{checks:new Map()}}, fetchCases:async()=>{{}}}};
          window.MCSV040 = {{state:{{}}}};
          window.MCSV046 = {{openRecipeRevisionEditor:()=>{{}}}};
          window.MCSRouter = {{navigate:path=>window.__routes.push(path)}};
          window.showTab = () => {{}};
          const plan = {json.dumps(PLAN, ensure_ascii=False)};
          window.api = async (url, options={{}}) => {{
            window.__calls.push({{url, method:options.method||'GET', body:options.body||null}});
            if(url.endsWith('/execution-plan')) return structuredClone(plan);
            if(url.endsWith('/calculation-check')) return {{
              valid:true,status:'PASS',studio:{{valid:true}},
              motorcad:{{status:'PASS',message:'Motor-CAD 模型检查通过',suggestion:'可以提交'}},
              stages:[], evidence:{{id:'PCK-RUNTIME-123456',analysis_revision_id:'AREV-1',design_revision_id:'DREV-1',expires_in_s:900}}
            }};
            if(url.endsWith('/execute')) return {{task_id:'TASK-V067',run_configuration_id:'RUN-V067',idempotent_replay:false,precheck_evidence_reused:true}};
            if(url.includes('/analysis-definitions')) return [];
            throw new Error('unexpected api '+url);
          }};
        """)
        page.add_script_tag(content=EXECUTION)
        page.evaluate("() => window.MCSAnalysisExecution.open('ANL-V067')")
        page.wait_for_selector("#analysisExecutionV067 .analysis-execution-dialog-v067")
        assert page.locator("[data-step-v067]").count() == 6
        assert page.locator("[data-submit-v067]").is_disabled()

        page.locator("[data-run-check-v067]").click()
        page.wait_for_function("() => window.MCSAnalysisExecution.state.fullCheck?.valid === true")
        assert not page.locator("[data-submit-v067]").is_disabled()

        page.locator("[data-submit-v067]").click()
        page.wait_for_function("() => window.__routes.length === 1")
        calls = page.evaluate("window.__calls")
        precheck = next(item for item in calls if item["url"].endswith("/calculation-check"))
        precheck_body = json.loads(precheck["body"])
        assert precheck_body["expected_analysis_revision_id"] == "AREV-1", precheck_body
        assert precheck_body["expected_design_revision_id"] == "DREV-1", precheck_body
        execute = next(item for item in calls if item["url"].endswith("/execute"))
        body = json.loads(execute["body"])
        assert body["precheck_evidence_id"] == "PCK-RUNTIME-123456", body
        assert body["run_native_precheck"] is True
        assert body["expected_analysis_revision_id"] == "AREV-1", body
        assert body["expected_design_revision_id"] == "DREV-1", body
        assert page.evaluate("window.__routes[0]") == "/app/projects/PRJ-V067/simulation/monitor/TASK-V067"
        assert not errors, errors
        browser.close()
    print("V0.67 analysis runtime contract: PASS")


if __name__ == "__main__":
    main()
