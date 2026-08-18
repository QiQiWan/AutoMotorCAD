from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
DOMAIN = (STATIC / "domain" / "motor-domain.js").read_text(encoding="utf-8")
CASE = (STATIC / "results" / "case-viewer.js").read_text(encoding="utf-8")


def main() -> None:
    html = """
    <!doctype html><html><body>
      <div id='viewerCaseMode'><select id='viewerTaskSelect'></select><select id='viewerCaseSelect'></select></div>
      <div id='viewerBatchMode' class='hidden'></div>
      <div id='viewerEmpty'></div>
      <div id='viewerContent' class='hidden'>
        <aside id='viewerModuleNav'></aside><div id='viewerCaseHeader'></div><div id='viewerCanvas'></div><aside id='viewerInspector'></aside>
      </div>
      <button id='loadCaseViewer'></button><div id='toastStack'></div>
    </body></html>
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_content(html)
        page.add_script_tag(content="""
          window.state={activeProjectId:'P1',language:'zh',registry:{outputs:{shaft_torque_nm:{label:'轴转矩',unit:'Nm'}}}};
          window.$=s=>document.querySelector(s); window.$$=s=>[...document.querySelectorAll(s)];
          window.esc=v=>String(v??''); window.uiText=(zh,en)=>zh; window.toast=()=>{};
          window.loadAnalyticsLanding=()=>{}; window.MCSPageRuntime={isContextActive:()=>true,isAbortError:()=>false};
          window.populateTaskSelectors=async()=>{document.querySelector('#viewerTaskSelect').innerHTML='<option value="T1">T1</option>';return [{id:'T1',usable_cases:1,completed_cases:1}]};
          window.api=async (url,options={})=>{
            if(url==='/api/motor-domain/catalog') return {motor_snapshot_schema_version:2,parameter_count:35};
            if(url==='/api/design-revisions/R1/motor-snapshot') return {snapshot:{identity:{native_motor_type:'BPM',family_id:'rfpm',topology_id:'rfpm_ipm'},parameters:{values:{air_gap:1},unknown_values:{}}}};
            if(url==='/api/design-revisions/R1/motor-snapshot/change-impact') return {impact:{affected_views:['geometry.radial']}};
            if(url==='/api/projects/P1/motor-domain/backfill') return {updated:1};
            if(url==='/api/result-viewer/catalog') return {modules:{overview:{}}};
            if(url.startsWith('/api/tasks/T1/cases')) return {items:[{id:'C1',execution_status:'SUCCEEDED',quality_status:'VALID'}]};
            if(url==='/api/cases/C1/viewer') return {
              case:{id:'C1',analysis:'emag',solver_mode:'motorcad',template_name:'IPM',execution_status:'SUCCEEDED',quality_status:'VALID'},
              analysis_recipe:{label:'额定点电磁分析'}, modules:{overview:{available:true,label_zh:'总览',description_zh:'关键结果'}},
              results:{scalars:{shaft_torque_nm:12.5},series:{},maps:{},fields:{},vectors:{}}, artifacts:[], warnings:[], quality:[], result_calibrations:[], output_schema:{}
            };
            throw new Error('unmocked '+url);
          };
        """)
        page.add_script_tag(content=DOMAIN)
        page.add_script_tag(content=CASE)
        exports = page.evaluate("""() => ({domain:typeof window.MCSMotorDomainV070,viewer:typeof window.MCSCaseViewerV070})""")
        assert exports == {"domain": "object", "viewer": "object"}, exports

        domain = page.evaluate("""async()=>{
          const c=await MCSMotorDomainV070.catalog();
          const s=await MCSMotorDomainV070.snapshot('R1');
          const i=await MCSMotorDomainV070.previewChangeImpact('R1',{air_gap:1.1},['air_gap']);
          return {count:c.parameter_count,topology:MCSMotorDomainV070.identityOf(s).topology_id,air:MCSMotorDomainV070.parameterValue(s,'air_gap'),views:i.impact.affected_views};
        }""")
        assert domain == {"count": 35, "topology": "rfpm_ipm", "air": 1, "views": ["geometry.radial"]}, domain

        result = page.evaluate("""async()=>window.MCSCaseViewerV070.mount({projectId:'P1',taskId:'T1',caseId:'C1'})""")
        assert result == {"taskId": "T1", "caseId": "C1"}, result
        page.wait_for_selector(".viewer-kpi")
        assert "12.5" in page.locator("#viewerCanvas").inner_text()
        assert page.locator("#viewerContent").evaluate("el=>!el.classList.contains('hidden')")
        assert page.evaluate("() => window.MCSCaseViewerV070.routeForCurrent('P1')") == "/app/projects/P1/results/tasks/T1/cases/C1"
        assert not errors, errors
        browser.close()
    print("V0.70 motor-domain + stable Single Case browser runtime: PASS")


if __name__ == "__main__":
    main()
