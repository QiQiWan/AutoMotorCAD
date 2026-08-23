from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _launch(pw):
    return pw.chromium.launch(
        headless=True,
        executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None,
        args=["--no-sandbox"],
    )


@pytest.mark.e2e
def test_v087d_standard_validation_is_one_primary_action_with_complete_scorecard_coverage():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.set_content('''<!doctype html><html><body>
          <section id="analysisConfig" class="tab active">
            <article id="standardValidationPackageV087D" class="hidden"></article>
          </section>
        </body></html>''')
        page.evaluate('''
          window.__post=null;window.__route=null;window.toast=()=>{};
          window.MCSEngineeringContext={get:()=>({projectId:'P1',motorRevisionId:'MR1'}),setExecution:()=>{}};
          window.MCSRouter={navigate:p=>{window.__route=p}};
          window.api=async(url,opts={})=>{
            if(opts.method==='POST'){
              window.__post=JSON.parse(opts.body);
              return {execution_status:'SUBMITTED',executions:[{analysis_template_id:'rated_emag',execution_status:'SUBMITTED',task_id:'T1',next_route:'/x'}]};
            }
            return {label:'标准设计验证',design_revision:1,starter:{label:'SPM 表贴式永磁电机'},ready_to_materialize:true,
              scorecard_contract:Array.from({length:8},(_,i)=>({metric_id:'M'+i})),
              scorecard_coverage:{complete:true,covered_count:8,metric_count:8,missing_metric_ids:[]},
              steps:[
                {sequence:1,short_label:'额定点 EMag',module:'EMag',ready:true,status:'READY',engineering_question:'额定工况下能否达到目标转矩、功率和电压要求？',expected_runtime:'medium'},
                {sequence:2,short_label:'稳态热',module:'Therm',ready:true,status:'READY',engineering_question:'连续运行温度是否安全？',expected_runtime:'high'}
              ]};
          };
        ''')
        page.add_script_tag(content=(STATIC / "analysis" / "standard-validation.js").read_text(encoding="utf-8"))
        page.evaluate("MCSStandardValidation.refresh({force:true})")
        page.wait_for_function("document.body.innerText.includes('Engineering Scorecard 8/8')")
        text = page.locator("#standardValidationPackageV087D").inner_text()
        primary_count = page.locator("#standardValidationPackageV087D [data-svp-run]").count()
        page.locator("[data-svp-run]").click()
        page.wait_for_function("window.__post!==null")
        payload = page.evaluate("window.__post")
        browser.close()
    assert "额定工况下能否达到目标转矩" in text
    assert "8/8 指标已被标准验证包覆盖" in text
    assert primary_count == 1
    assert payload["run_native_precheck"] is True
    assert payload["reuse_cache"] is True


@pytest.mark.e2e
def test_v087d_engineering_scorecard_is_decision_first_and_uses_engineering_groups():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.set_content('''<!doctype html><html><body>
          <section id="resultViewer" class="tab active">
            <article id="engineeringScorecardV087D" class="hidden"></article>
            <button data-viewer-mode="batch" id="batchButton">批量/优化</button>
            <select id="analyticsTaskSelect"><option>T1</option></select>
          </section>
        </body></html>''')
        page.evaluate('''
          window.__batch=false;window.toast=()=>{};
          document.querySelector('#batchButton').addEventListener('click',()=>window.__batch=true);
          window.MCSEngineeringContext={get:()=>({projectId:'P1',motorRevisionId:'MR1'})};
          window.api=async()=>({project_id:'P1',design_revision:7,starter:{short_label:'IPM'},overall_status:'READY_WITH_WARNING',
            conclusion:'结果可用于工程判断，1 项指标接近边界。',
            summary:{observed_count:3,warning_count:1,fail_count:0,missing_count:0},
            groups:[
              {group:'性能',metrics:[{metric_id:'shaft_torque_nm',label:'轴转矩',display_value:148.2,display_unit:'Nm',status:'PASS',description:'输出轴平均转矩',requirement:{margin_percent:8.5}}]},
              {group:'损耗',metrics:[{metric_id:'magnet_loss_w',label:'永磁体损耗',display_value:392,display_unit:'W',status:'WARNING',description:'永磁体附加损耗'}]},
              {group:'热',metrics:[{metric_id:'winding_max_temperature_c',label:'绕组最高温度',display_value:126,display_unit:'degC',status:'PASS',description:'绕组最高温度'}]}
            ],next_action:{label:'进入参数对比与优化',stage:'decide'}});
        ''')
        page.add_script_tag(content=(STATIC / "results" / "engineering-scorecard.js").read_text(encoding="utf-8"))
        page.evaluate("MCSEngineeringScorecard.refresh({force:true})")
        page.wait_for_function("document.body.innerText.includes('IPM Rev.7 工程结果')")
        text = page.locator("#engineeringScorecardV087D").inner_text()
        page.locator("[data-scorecard-next]").click()
        batch = page.evaluate("window.__batch")
        browser.close()
    assert "可判断 · 有关注项" in text
    assert "轴转矩" in text and "148.2" in text and "裕度 8.5%" in text
    assert "永磁体损耗" in text and "接近边界" in text
    assert "绕组最高温度" in text
    assert batch is True
