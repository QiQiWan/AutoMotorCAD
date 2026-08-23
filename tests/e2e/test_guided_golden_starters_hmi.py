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
def test_v087ab_guided_starter_cards_create_rev1_without_exposing_raw_template_catalog():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.set_content('''<!doctype html><html><body data-user-mode="operator">
          <section id="templates">
            <div id="goldenStarterStatusV087"></div>
            <div id="goldenStarterGridV087"></div>
            <div id="goldenStarterCreateV087" class="hidden"></div>
            <div class="engineering-catalog-only" id="rawCatalog">RAW TEMPLATE CATALOG</div>
          </section>
        </body></html>''')
        page.add_style_tag(content=(STATIC / "engineering-workflow.css").read_text(encoding="utf-8"))
        page.evaluate('''
          window.MCSEngineeringContext={get:()=>({projectId:'P1'})};
          window.__created=null;window.__route=null;window.toast=()=>{};
          const starter={id:'golden_spm_servo',label:'SPM 表贴式永磁电机',short_label:'SPM',description:'工程预制',topology_label:'径向磁通 · 内转子 · SPM',application:'工业伺服',default_name:'SPM 工程设计',guided_inputs:[{parameter_id:'air_gap',label:'气隙',unit:'mm',recommended_min:0.4,recommended_max:1.5,hard_min:0.05,hard_max:20,step:0.1,default_value:0.8}],standard_analysis_package:['rated_emag'],optimization_variables:['air_gap'],result_scorecard:['torque_nm'],qualification:{production_verified:false,message:'待 Windows 实机资格'}};
          window.api=async(url,opts={})=>{
            if(url==='/api/design-starters')return {contract_version:'0.87-D',starters:[starter]};
            if(String(url).includes('/design-starters/golden_spm_servo')){window.__created=JSON.parse(opts.body);return {id:'S1',revisions:[{id:'MR1',revision:1}]};}
            throw new Error('unexpected '+url);
          };
          window.MCSRouter={navigate:async p=>{window.__route=p}};
        ''')
        page.add_script_tag(content=(STATIC / "design" / "design-starters.js").read_text(encoding="utf-8"))
        page.evaluate("MCSDesignStarters.load()")
        page.wait_for_function("document.body.innerText.includes('SPM 表贴式永磁电机')")
        raw_display = page.locator("#rawCatalog").evaluate("el=>getComputedStyle(el).display")
        page.locator("[data-starter-use='golden_spm_servo']").click()
        page.locator("[data-starter-input='air_gap']").fill("0.9")
        page.locator("#goldenStarterConfirmV087").click()
        page.wait_for_function("window.__created!==null && window.__route!==null")
        created = page.evaluate("window.__created")
        route = page.evaluate("window.__route")
        browser.close()
    assert raw_display == "none"
    assert created["name"] == "SPM 工程设计"
    assert created["inputs"]["air_gap"] == 0.9
    assert route == "/app/projects/P1/designs/S1"
