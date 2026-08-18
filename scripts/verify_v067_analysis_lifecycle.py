from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
EXECUTION = (STATIC / "analysis" / "execution.js").read_text(encoding="utf-8")

BASE_PLAN = {
    "analysis_definition_id": "ANL-LIFE",
    "analysis_name": "并发保护分析",
    "project_id": "PRJ-LIFE",
    "module": "EMag",
    "recipe_id": "emag",
    "recipe": {"label": "电磁", "sections": []},
    "design": {"id": "DSN-LIFE", "name": "BPM", "motor_type_id": "BPM"},
    "design_revision": {"id": "DREV-LIFE", "revision": 2, "content_hash": "d" * 64},
    "analysis_revision": {"id": "AREV-OLD", "revision": 4, "content_hash": "a" * 64},
    "load_cases": [{}],
    "case_count": 1,
    "input_domains": {"materials": {"magnet_material": "N30UH"}},
    "required_input_domains": ["materials"],
    "missing_required_input_domains": [],
    "solver_settings": {},
    "requested_outputs": ["shaft_torque_nm"],
    "studio_precheck": {"valid": True, "blocking": 0, "warnings": 0, "issues": []},
    "task_validation": {"valid": True, "blocking": 0, "warnings": 0, "issues": []},
    "runtime_readiness": {"ok": True, "checks": []},
    "recent_tasks": [],
    "can_submit": True,
}


def bootstrap(page, api_script: str) -> None:
    page.set_content("<body><div id='toastStack'></div></body>")
    page.add_script_tag(content=f"""
      window.state={{activeProjectId:'PRJ-LIFE'}};
      window.esc=v=>String(v??''); window.toast=()=>{{}}; window.showTab=()=>{{}};
      window.MCSV060={{state:{{checks:new Map()}},fetchCases:async()=>{{}}}};
      window.MCSRouter={{navigate:path=>{{window.__routes.push(path)}},setUrl:()=>{{}}}};
      window.__routes=[];
      {api_script}
    """)
    page.add_script_tag(content=EXECUTION)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])

        # A stale browser plan must be reloaded and must not submit the newer Analysis Revision silently.
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        old_plan = json.dumps(BASE_PLAN, ensure_ascii=False)
        new_plan = dict(BASE_PLAN)
        new_plan["analysis_revision"] = {"id": "AREV-NEW", "revision": 5, "content_hash": "b" * 64}
        new_plan_json = json.dumps(new_plan, ensure_ascii=False)
        bootstrap(page, f"""
          const oldPlan={old_plan}, newPlan={new_plan_json}; let planReads=0;
          window.api=async (url,options={{}})=>{{
            if(url.endsWith('/execution-plan')) return structuredClone((planReads++===0)?oldPlan:newPlan);
            if(url.endsWith('/calculation-check')) return {{valid:true,status:'PASS',studio:{{valid:true}},motorcad:{{status:'PASS'}},evidence:{{id:'PCK-LIFE-123456'}}}};
            if(url.endsWith('/execute')) {{const e=new Error('分析设置已更新');e.status=409;e.detail={{code:'ANALYSIS_EXECUTION_STALE',message:'分析设置或设计版本已在其他窗口更新，请刷新执行计划后重新检查。'}};throw e;}}
            throw new Error('unexpected api '+url);
          }};
        """)
        page.evaluate("() => window.MCSAnalysisExecution.open('ANL-LIFE')")
        page.wait_for_selector("[data-run-check-v067]")
        page.locator("[data-run-check-v067]").click()
        page.wait_for_function("() => window.MCSAnalysisExecution.state.fullCheck?.valid === true")
        page.locator("[data-submit-v067]").click()
        page.wait_for_function("() => window.MCSAnalysisExecution.state.plan?.analysis_revision?.id === 'AREV-NEW'")
        assert page.evaluate("window.MCSAnalysisExecution.state.fullCheck") is None
        assert page.locator("[data-submit-v067]").is_disabled()
        assert page.evaluate("window.__routes.length") == 0
        assert not errors, errors
        page.close()

        # Results from a long native precheck are discarded after the route/editor is disposed.
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        bootstrap(page, f"""
          const plan={old_plan}; let resolveCheck;
          window.__resolveCheck=()=>resolveCheck?.({{valid:true,status:'PASS',studio:{{valid:true}},motorcad:{{status:'PASS'}},evidence:{{id:'PCK-LATE-123456'}}}});
          window.api=async (url,options={{}})=>{{
            if(url.endsWith('/execution-plan')) return structuredClone(plan);
            if(url.endsWith('/calculation-check')) return await new Promise(resolve=>{{resolveCheck=resolve}});
            throw new Error('unexpected api '+url);
          }};
        """)
        page.evaluate("() => window.MCSAnalysisExecution.open('ANL-LIFE')")
        page.wait_for_selector("[data-run-check-v067]")
        page.locator("[data-run-check-v067]").click()
        page.evaluate("() => window.MCSAnalysisExecution.close()")
        page.evaluate("() => window.__resolveCheck()")
        page.wait_for_timeout(80)
        assert page.locator("#analysisExecutionV067").count() == 0
        assert page.evaluate("window.MCSAnalysisExecution.state.fullCheck") is None
        assert not errors, errors
        page.close()

        browser.close()
    print("V0.67 analysis lifecycle contract: PASS")


if __name__ == "__main__":
    main()
