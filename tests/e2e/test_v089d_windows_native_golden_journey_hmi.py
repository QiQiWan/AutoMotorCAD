from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


@pytest.mark.e2e
def test_v089d_hmi_surfaces_native_predecessor_and_three_ui_golden_journeys():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        page.set_content('''<!doctype html><html><body>
          <span id="workstationAcceptanceBadge"></span>
          <div id="workstationAcceptanceSummary"></div>
        </body></html>''')
        page.evaluate("""() => {
          const evidence=()=>({packaged_path:'x',sha256:'abc',size:12});
          window.api=async(path)=>{
            if(path==='/api/windows-golden-journey-qualification') return {
              authority:'WindowsNativeGoldenJourneyQualificationV1',contract_version:'0.89-D',formal_qualified:false,
              qualification_percent:0,evidence_coverage_percent:88,
              matrix:{golden_journeys:['SPM','IPM','AFPM'].map((id,i)=>({
                id,starter_id:['golden_spm_servo','golden_ipm_emobility','golden_afpm_ssdr'][i],
                required_gates:['live_studio_shell','project_created_via_ui','starter_opened_via_ui','rev1_created_via_ui','analysis_created_via_ui','full_native_precheck_via_ui','task_submitted_via_ui','task_completed','result_bundle_ready','result_opened_via_ui','lineage_consistent','no_page_errors','no_console_errors','screenshot_evidence','trace_evidence']
              }))},
              latest_run:{qualification_blockers:['GOLDEN_JOURNEY_FAILED'],coverage:{release_gate_passed:3,release_gate_required:3,evidence_coverage_percent:88},evidence:{golden_journeys:[
                {id:'SPM',status:'PASS',lineage_consistent:true,no_page_errors:true,no_console_errors:true,screenshot_evidence:true,trace_evidence:true,live_studio_shell:true,project_created_via_ui:true,starter_opened_via_ui:true,rev1_created_via_ui:true,analysis_created_via_ui:true,full_native_precheck_via_ui:true,task_submitted_via_ui:true,task_completed:true,result_bundle_ready:true,result_opened_via_ui:true,evidence:{summary:evidence(),design_screenshot:evidence(),precheck_screenshot:evidence(),result_screenshot:evidence(),playwright_trace:evidence()}},
                {id:'IPM',status:'PASS',lineage_consistent:true,no_page_errors:true,no_console_errors:true,screenshot_evidence:true,trace_evidence:true,live_studio_shell:true,project_created_via_ui:true,starter_opened_via_ui:true,rev1_created_via_ui:true,analysis_created_via_ui:true,full_native_precheck_via_ui:true,task_submitted_via_ui:true,task_completed:true,result_bundle_ready:true,result_opened_via_ui:true,evidence:{summary:evidence(),design_screenshot:evidence(),precheck_screenshot:evidence(),result_screenshot:evidence(),playwright_trace:evidence()}},
                {id:'AFPM',status:'FAIL',lineage_consistent:true,no_page_errors:true,no_console_errors:true,screenshot_evidence:true,trace_evidence:true,live_studio_shell:true,project_created_via_ui:true,starter_opened_via_ui:true,rev1_created_via_ui:true,analysis_created_via_ui:true,full_native_precheck_via_ui:true,task_submitted_via_ui:true,task_completed:true,result_bundle_ready:true,result_opened_via_ui:false,evidence:{summary:evidence(),design_screenshot:evidence(),precheck_screenshot:evidence(),result_screenshot:evidence(),playwright_trace:evidence()}}
              ]}}
            };
            if(path==='/api/windows-production-qualification') return {
              authority:'WindowsMotorCADProductionQualificationV2',formal_qualified:true,
              latest_qualified_run:{evidence:{representative_scenarios:['SPM','IPM','AFPM','IM'].map(id=>({id,status:'PASS',native_motorcad:true})),failure_injections:Array.from({length:17},(_,i)=>({id:'F'+i,status:'PASS',required:true,evidence:{sha256:'x'}}))}}
            };
            throw new Error('unexpected '+path);
          };
        }""")
        page.add_script_tag(content=(STATIC / "runtime" / "workstation-acceptance.js").read_text(encoding="utf-8"))
        page.evaluate("MCSWorkstationAcceptance.load()")
        page.wait_for_function("document.body.innerText.includes('V0.89-D 正式工作站资格尚未完成')")
        text = page.locator("#workstationAcceptanceSummary").inner_text()
        badge = page.locator("#workstationAcceptanceBadge").inner_text()
        browser.close()

    assert badge == "Native通过 · 待UI旅程"
    assert "4/4 Native · 17/17 故障" in text
    assert "2/3 Golden Journeys" in text
    assert "3 条真实 UI Golden Journey" in text
    assert "SPM" in text and "IPM" in text and "AFPM" in text
    assert "待完整 UI Golden Journey" in text
    assert "GOLDEN_JOURNEY_FAILED" in text
    assert "88% evidence" in text
