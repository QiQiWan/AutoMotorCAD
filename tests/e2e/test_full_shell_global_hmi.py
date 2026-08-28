from __future__ import annotations

import re
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _browser(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(
        headless=True,
        executable_path=str(executable) if executable.is_file() else None,
        args=["--no-sandbox"],
    )


def _full_shell_html() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'<link[^>]+href="/static/[^"]+"[^>]*>', "", html)
    script_re = re.compile(r'<script\s+src="(/static/[^"]+)"\s*></script>')
    mock = r'''
<script>
(() => {
  const store=new Map([['motorcad-studio-active-project','STALE-PROJECT']]);
  Object.defineProperty(window,'localStorage',{value:{
    getItem:k=>store.has(k)?store.get(k):null,
    setItem:(k,v)=>store.set(k,String(v)),
    removeItem:k=>store.delete(k),
    clear:()=>store.clear()
  },configurable:true});
  try{history.replaceState=()=>{};history.pushState=()=>{}}catch{}
  window.__mockRequests=[];
  const projects=[]; const fullProjects=new Map();
  const starter={id:'golden_spm_servo',label:'Golden SPM Servo',topology:'rfpm_spm',maturity:'golden_candidate',parameter_inputs:[],guided_inputs:[],standard_analysis_package:{templates:['rated_emag']},result_scorecard:['shaft_torque_nm'],scorecard_metrics:[],optimization_variables:['air_gap'],qualification:{production_verified:false}};
  const resp=(data,status=200)=>({ok:status>=200&&status<300,status,headers:{get:()=>null},json:async()=>data,text:async()=>typeof data==='string'?data:JSON.stringify(data),blob:async()=>new Blob([JSON.stringify(data)],{type:'application/json'})});
  window.fetch=async(input,opts={})=>{
    const raw=typeof input==='string'?input:input.url;
    const u=raw.startsWith('/')?{pathname:raw.split('?',1)[0],search:raw.includes('?')?'?'+raw.split('?').slice(1).join('?'):''}:new URL(raw);
    const path=u.pathname; window.__mockRequests.push(path+(u.search||''));
    if(path==='/api/health')return resp({version:'0.89.9',solvers:{motorcad:{available:false,pymotorcad_version:null}},templates:33,data_dir:'test',max_workers:1,model_policy:'development'});
    if(path==='/api/registry')return resp({scenario:{cooling_types:[],initial_condition_modes:[]},quality_profiles:{},analysis_recipes:{},parameters:{},outputs:{},motorcad_version:'2026R1',solver_controls:{contexts:{}}});
    if(path==='/api/templates')return resp([{id:'i5_Industrial_SPM_Servo_Tooth_Wound',name:'SPM',sector:'Industrial',topology:'SPM',motor_type:'BPM',is_axial:false,parameter_ids:[],defaults:{},warnings:[],capabilities:{motorcad:{}}}]);
    if(path==='/api/projects'&&String(opts.method||'GET').toUpperCase()==='POST'){
      const body=JSON.parse(opts.body||'{}');
      const p={id:'P1',name:body.name||'E2E Project',description:body.description||'',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),status:'ACTIVE',deleted_at:null,counts:{designs:0,scenarios:0,experiments:0,tasks:0}};
      projects.splice(0,projects.length,p);fullProjects.set('P1',{...p,designs:[],scenarios:[],experiments:[]});return resp(fullProjects.get('P1'),201);
    }
    if(path==='/api/projects')return resp(projects);
    if(path==='/api/projects/P1'&&String(opts.method||'GET').toUpperCase()==='PATCH'){
      const body=JSON.parse(opts.body||'{}'),current=fullProjects.get('P1');Object.assign(current,body,{updated_at:new Date().toISOString()});Object.assign(projects[0]||{},body,{updated_at:current.updated_at});return resp(current);
    }
    if(path==='/api/projects/P1')return resp(fullProjects.get('P1'));
    if(path==='/api/dashboard')return resp({templates:{total:33,curated:15,axial:3,by_sector:{Industrial:12}},tasks:{total:0,running:0,completed:0,failed:0,cases:0},recent_tasks:[]});
    if(path==='/api/projects/P1/engineer-journey')return resp({authority:'EngineerJourneyV1',project_id:'P1',stages:[{id:'design',label:'设计',status:'CURRENT',summary:'建立并冻结电机设计版本'},{id:'validate',label:'验证',status:'BLOCKED',summary:'配置工况并执行工程分析'},{id:'decide',label:'决策',status:'BLOCKED',summary:'基于结果做判断'}],current_stage:'design',primary_next_action:{id:'CREATE_DESIGN',label:'创建设计',route:'/app/projects/P1/designs',stage:'design'}});
    if(path==='/api/client-contract')return resp({version:'0.89.9',static_cache_epoch:'0.89.9'});
    if(path==='/api/design-starters')return resp({contract_version:'0.87-D',starters:[starter]});
    if(path==='/api/system/installations')return resp({target_version:'2026R1',selected:null,selected_version_match:false,installations:[]});
    if(path==='/api/system/preflight')return resp({motorcad:{checks:[{status:'WARNING',message:'未绑定 Motor-CAD.exe'}]}});
    if(path==='/api/workstation-acceptance'||path==='/api/windows-production-qualification')return resp({formal_qualification_percent:0,qualification_percent:0,evidence_coverage_percent:0,scenarios:[],faults:[],matrix:{scenarios:[],faults:[]},status:'PENDING'});
    if(path==='/api/production-soak-qualification')return resp({formal_qualification_percent:0,qualification_percent:0,evidence_coverage_percent:0,tiers:[],matrix:{tiers:[]},status:'PENDING'});
    if(path==='/api/runtime/lifecycle/qualification')return resp({authority:'RuntimeLifecycleQualificationV1',qualified:true,status:'RUNNING',runtime:{}});
    if(path==='/api/system/metrics'||path==='/api/system/overview')return resp({host:{cpu_percent:1,memory_percent:1,memory_used_gb:1,memory_total_gb:10,disk_percent:1,disk_free_gb:10,pid:1},solver_pool:{capacity:1,busy:0,available:1,utilization_percent:0,case_parallelism:1},license_pool:{resources:{}},motorcad_processes:[],tasks:{},cases:{},alerts:[],timestamp:new Date().toISOString(),health_score:100});
    if(path==='/api/tasks')return resp([]);
    if(path==='/api/result-viewer/catalog')return resp({});
    if(path==='/api/logs')return resp([]);
    if(path==='/api/logs/summary')return resp({});
    if(path==='/api/logs/diagnostics')return resp([]);
    if(path==='/api/materials')return resp({materials:[]});
    if(path.startsWith('/api/projects/STALE-PROJECT/')&&path.endsWith('/engineer-journey'))return resp({detail:'not found'},404);
    return resp({});
  };
  window.EventSource=class{constructor(url){this.url=url;this.listeners={};setTimeout(()=>this.onerror?.({}),5)}addEventListener(t,f){this.listeners[t]=f}close(){}};
})();
</script>
'''
    first = html.find('<script src=')
    html = html[:first] + mock + html[first:]

    def inline_script(match: re.Match[str]) -> str:
        src = match.group(1)
        rel = src.removeprefix('/static/').split('?', 1)[0]
        code = (STATIC / rel).read_text(encoding="utf-8").replace('</script>', '<\\/script>')
        return f'<script>\n/* {src} */\n{code}\n</script>'

    return script_re.sub(inline_script, html)


@pytest.mark.e2e
def test_complete_shell_boot_navigation_and_project_stage_simulation_has_no_page_errors():
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.set_content(_full_shell_html(), wait_until="load")
        page.wait_for_timeout(1200)

        assert page_errors == []
        assert console_errors == []
        assert page.locator("#healthBadge").inner_text() == "服务正常 · 0.89.9"
        assert page.locator("#setupAutoCheckPercent").inner_text() == "100%"
        assert "自动浅自检" in page.locator("#setupAutoCheckLabel").inner_text()
        requests = page.evaluate("window.__mockRequests")
        assert not any("STALE-PROJECT/engineer-journey" in row for row in requests)

        for tab in ("projects", "setup", "logs", "system"):
            page.evaluate("tab=>document.querySelector(`[data-tab=\"${tab}\"]`)?.click()", tab)
            page.wait_for_timeout(80)
            assert page.locator(".tab.active").get_attribute("id") == tab

        page.evaluate("document.querySelector('[data-tab=\"projects\"]')?.click()")
        page.fill("#projectCreateName", "Global E2E Project")
        page.click("#projectCreate")
        page.wait_for_timeout(500)
        assert page.evaluate("window.MCSAppState.activeProjectId") == "P1"

        for route, expected_tab in (
            ("/app/projects/P1/designs", "workspace"),
            ("/app/projects/P1/simulation/analyses", "analysisConfig"),
            ("/app/projects/P1/results", "resultViewer"),
        ):
            assert page.evaluate("async route=>await window.MCSRouter.apply(route)", route) is True
            page.wait_for_timeout(100)
            assert page.locator(".tab.active").get_attribute("id") == expected_tab
            shell_audit = page.evaluate("window.MCSGlobalShellConvergence.audit()")
            assert shell_audit["passed"] is True, shell_audit

        assert page_errors == []
        assert console_errors == []
        browser.close()

@pytest.mark.e2e
def test_v089a_context_restore_is_hint_only_and_visible_stage_gates_follow_canonical_context():
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.set_content(_full_shell_html(), wait_until="load")
        page.wait_for_timeout(900)

        result = page.evaluate("""
        () => {
          localStorage.setItem('motorcad-studio-engineering-context:P2', JSON.stringify({
            schemaVersion:'3.0', projectId:'P2', solutionId:'STALE-S', motorRevisionId:'STALE-R',
            analysisId:'STALE-A', stage:'analysis', revision:9
          }));
          MCSEngineeringContext.setProject('P2',{source:'e2e:v089a'});
          const restored=MCSEngineeringContext.get();
          const before={
            solutionId:restored.solutionId,
            motorRevisionId:restored.motorRevisionId,
            resumeSolution:restored.resumeHints.solutionId,
            resumeMotor:restored.resumeHints.motorRevisionId,
            valid:MCSEngineeringContext.inspect().valid,
            designDisabled:document.querySelector('[data-engineer-stage="design"]').disabled,
            validateDisabled:document.querySelector('[data-engineer-stage="validate"]').disabled,
            decideDisabled:document.querySelector('[data-engineer-stage="decide"]').disabled,
          };
          MCSEngineeringContext.setSolution({id:'S2',name:'SPM方案'},{source:'e2e:v089a'});
          MCSEngineeringContext.setMotorRevision({id:'R2',revision:2},{solution:{id:'S2',name:'SPM方案'},source:'e2e:v089a'});
          MCSGlobalWorkflowTruth.sync();
          const after={
            validateDisabled:document.querySelector('[data-engineer-stage="validate"]').disabled,
            decideDisabled:document.querySelector('[data-engineer-stage="decide"]').disabled,
            valid:MCSEngineeringContext.inspect().valid,
            breadcrumb:document.querySelector('#engineeringContextBreadcrumbV089A').innerText,
          };
          MCSGlobalWorkflowTruth.ingest({project:{id:'P2',name:'E2E Project'},stages:[{id:'motor',completed:true},{id:'results',completed:true}],run_center:{summary:{total:1}}});
          after.decideDisabledAfterResult=document.querySelector('[data-engineer-stage="decide"]').disabled;
          return {before,after};
        }
        """)
        assert result["before"]["solutionId"] is None
        assert result["before"]["motorRevisionId"] is None
        assert result["before"]["resumeSolution"] == "STALE-S"
        assert result["before"]["resumeMotor"] == "STALE-R"
        assert result["before"]["valid"] is True
        assert result["before"]["designDisabled"] is False
        assert result["before"]["validateDisabled"] is True
        assert result["before"]["decideDisabled"] is True
        assert result["after"]["validateDisabled"] is False
        assert result["after"]["decideDisabled"] is True
        assert result["after"]["decideDisabledAfterResult"] is False
        assert result["after"]["valid"] is True
        assert "SPM方案" in result["after"]["breadcrumb"]
        assert "Rev.2" in result["after"]["breadcrumb"]
        assert page_errors == []
        browser.close()


@pytest.mark.e2e
def test_v089b_all_fixed_buttons_are_registered_and_actual_click_sweep_has_no_browser_errors():
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page(accept_downloads=True)
        page_errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.set_content(_full_shell_html(), wait_until="load")
        page.wait_for_timeout(1200)

        report = page.evaluate("window.MCSHMIQualification.qualify()")
        assert report["authority"] == "HMIActionQualificationAuthorityV1"
        assert report["fixed_controls"] == 90
        assert report["fixed_qualification_percent"] == 100
        assert report["missing_count"] == 0
        assert all(row["stable_identity"] for row in report["controls"] if row["origin"] == "fixed")
        assert all(row["handler_bound"] for row in report["controls"] if row["origin"] == "fixed")

        page.fill("#projectCreateName", "HMI sweep project")
        control_ids = page.evaluate("[...document.querySelectorAll('button[data-hmi-origin=\"fixed\"]')].map(x=>x.dataset.hmiControlId)")
        sweep = []
        for control_id in control_ids:
            status = page.evaluate(
                """cid => {
                  const button=[...document.querySelectorAll('button')].find(x=>x.dataset.hmiControlId===cid);
                  if(!button)return 'missing';
                  if(button.disabled)return 'gated';
                  button.click(); return 'clicked';
                }""",
                control_id,
            )
            page.wait_for_timeout(15)
            sweep.append((control_id, status))
        page.wait_for_timeout(500)

        assert len(sweep) == 90
        assert all(status in {"clicked", "gated"} for _, status in sweep)
        # V0.89-G2 intentionally gates primary actions whose prerequisites are
        # absent. The qualification target is semantic recoverability rather
        # than maximizing blind click count on an empty shell.
        assert sum(status == "clicked" for _, status in sweep) >= 75
        readiness = page.evaluate("window.MCSActionReadiness.qualify()")
        assert readiness["qualified"] is True, readiness
        assert readiness["dead_end_count"] == 0
        assert readiness["unmanaged_count"] == 0
        gated_semantics = page.evaluate("""() => [...document.querySelectorAll('button[data-hmi-origin=\"fixed\"]:disabled')].map(button => ({
          stage: Boolean(button.dataset.engineerStage),
          status: button.dataset.actionReadiness || '',
          blocker: button.dataset.actionBlocker || '',
          recovery: button.dataset.actionRecovery || ''
        }))""")
        assert all(row["stage"] or row["status"] in {"BLOCKED", "IDLE", "BUSY"} for row in gated_semantics)
        assert all(row["stage"] or row["status"] != "BLOCKED" or (row["blocker"] and row["recovery"]) for row in gated_semantics)
        assert page_errors == []
        assert console_errors == []
        browser.close()


@pytest.mark.e2e
def test_v089c_project_editor_unsaved_navigation_blocks_or_saves_without_losing_context():
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.set_content(_full_shell_html(), wait_until="load")
        page.wait_for_timeout(900)

        page.fill("#projectCreateName", "Transaction Project")
        page.click("#projectCreate")
        page.wait_for_timeout(450)
        assert page.evaluate("window.MCSAppState.activeProjectId") == "P1"
        assert page.evaluate("async()=>await MCSRouter.navigate('/app/projects/P1/settings',{source:'e2e:project-settings'})") is True
        page.wait_for_timeout(120)
        assert not page.locator("#projectEditorPanel").evaluate("el=>el.classList.contains('hidden')")

        page.fill("#projectEditorName", "Unsaved Project Name")
        assert page.evaluate("MCSNavigationTransaction.inspect().unsafe") is True
        page.evaluate("void (window.__blockedLeave=MCSRouter.navigate('/app/projects',{source:'e2e:blocked-leave'}))")
        page.locator(".studio-floating-dialog").wait_for(state="visible")
        assert "尚未保存" in page.locator(".studio-floating-dialog").inner_text()
        page.locator('.studio-floating-dialog [data-dialog-action="0"]').click()
        assert page.evaluate("window.__blockedLeave") is False
        assert page.input_value("#projectEditorName") == "Unsaved Project Name"
        assert not page.locator("#projectEditorPanel").evaluate("el=>el.classList.contains('hidden')")

        page.evaluate("void (window.__savedLeave=MCSRouter.navigate('/app/projects',{source:'e2e:saved-leave'}))")
        page.locator(".studio-floating-dialog").wait_for(state="visible")
        page.locator('.studio-floating-dialog [data-dialog-action="2"]').click()
        assert page.evaluate("window.__savedLeave") is True
        page.wait_for_timeout(180)
        assert page.locator("#projectEditorPanel").evaluate("el=>el.classList.contains('hidden')")
        assert page.evaluate("MCSNavigationTransaction.inspect().unsafe") is False
        assert "Unsaved Project Name" in page.locator("#projectManagerList").inner_text()
        assert page_errors == []
        assert console_errors == []
        browser.close()
