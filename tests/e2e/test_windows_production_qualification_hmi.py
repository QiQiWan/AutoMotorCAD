from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


@pytest.mark.e2e
def test_v087fb_windows_production_matrix_surfaces_scenarios_faults_and_fail_closed_status():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None, args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content('''<!doctype html><html><body>
          <span id="workstationAcceptanceBadge"></span>
          <div id="workstationAcceptanceSummary"></div>
        </body></html>''')
        page.evaluate("""
          window.api=async(path)=>({
            authority:'WindowsMotorCADProductionQualificationV2',contract_version:'0.87-F-B',formal_qualified:false,
            qualification_percent:0,evidence_coverage_percent:71,
            matrix:{representative_scenarios:[
              {id:'SPM',template_id:'i5_Industrial_SPM_Servo_Tooth_Wound'},
              {id:'IPM',template_id:'e9_eMobility_IPM'},
              {id:'AFPM',template_id:'e14_eMobility_AFM'},
              {id:'IM',template_id:'i4_Industrial_IM'}]},
            latest_run:{qualification_blockers:['LICENSED_MOTORCAD_EVIDENCE_MISSING','REQUIRED_FAILURE_EVIDENCE_INCOMPLETE'],coverage:{scenario_passed:3,scenario_required:4,fault_passed:12,fault_required:17,evidence_coverage_percent:71},evidence:{
              licensed_motorcad_evidence:false,
              environment:{deep_preflight_pass:true},
              runtime_lifecycle:{local_qualified:true,shutdown_clean:true},
              onboarding:{first_native_result_bundle:true,restart_reopen_pass:true},
              representative_scenarios:[
                {id:'SPM',required:true,status:'PASS',native_motorcad:true,native_closure_qualified:true,restart_reopen_pass:true},
                {id:'IPM',required:true,status:'PASS',native_motorcad:true,native_closure_qualified:true,restart_reopen_pass:true},
                {id:'AFPM',required:true,status:'PENDING',native_motorcad:false,native_closure_qualified:false,restart_reopen_pass:false},
                {id:'IM',required:true,status:'PASS',native_motorcad:true,native_closure_qualified:true,restart_reopen_pass:true}
              ],
              failure_injections:Array.from({length:17},(_,i)=>({id:'F'+i,required:true,status:i<12?'PASS':'PENDING',evidence:i<12?{sha256:'x'}:{}}))
            }}
          });
        """)
        page.add_script_tag(content=(STATIC / "runtime" / "workstation-acceptance.js").read_text(encoding="utf-8"))
        page.evaluate("MCSWorkstationAcceptance.load()")
        page.wait_for_function("document.body.innerText.includes('正式工作站资格尚未完成')")
        text = page.locator("#workstationAcceptanceSummary").inner_text()
        badge = page.locator("#workstationAcceptanceBadge").inner_text()
        browser.close()

    assert badge == "待工作站验收"
    assert "71% evidence" in text
    assert "3/4 代表场景" in text
    assert "12/17 故障证据" in text
    assert "Runtime生命周期" in text
    assert "AFPM" in text
    assert "run_windows_production_qualification.bat" in text
    assert "LICENSED_MOTORCAD_EVIDENCE_MISSING" in text
