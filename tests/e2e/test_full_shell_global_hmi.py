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
    if(path==='/api/health')return resp({version:'0.88.1',solvers:{motorcad:{available:false,pymotorcad_version:null}},templates:33,data_dir:'test',max_workers:1,model_policy:'development'});
    if(path==='/api/registry')return resp({scenario:{cooling_types:[],initial_condition_modes:[]},quality_profiles:{},analysis_recipes:{},parameters:{},outputs:{},motorcad_version:'2026R1',solver_controls:{contexts:{}}});
    if(path==='/api/templates')return resp([{id:'i5_Industrial_SPM_Servo_Tooth_Wound',name:'SPM',sector:'Industrial',topology:'SPM',motor_type:'BPM',is_axial:false,parameter_ids:[],defaults:{},warnings:[],capabilities:{motorcad:{}}}]);
    if(path==='/api/projects'&&String(opts.method||'GET').toUpperCase()==='POST'){
      const body=JSON.parse(opts.body||'{}');
      const p={id:'P1',name:body.name||'E2E Project',description:body.description||'',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),status:'ACTIVE',deleted_at:null,counts:{designs:0,scenarios:0,experiments:0,tasks:0}};
      projects.splice(0,projects.length,p);fullProjects.set('P1',{...p,designs:[],scenarios:[],experiments:[]});return resp(fullProjects.get('P1'),201);
    }
    if(path==='/api/projects')return resp(projects);
    if(path==='/api/projects/P1')return resp(fullProjects.get('P1'));
    if(path==='/api/dashboard')return resp({templates:{total:33,curated:15,axial:3,by_sector:{Industrial:12}},tasks:{total:0,running:0,completed:0,failed:0,cases:0},recent_tasks:[]});
    if(path==='/api/projects/P1/engineer-journey')return resp({authority:'EngineerJourneyV1',project_id:'P1',stages:[{id:'design',label:'设计',status:'CURRENT',summary:'建立并冻结电机设计版本'},{id:'validate',label:'验证',status:'BLOCKED',summary:'配置工况并执行工程分析'},{id:'decide',label:'决策',status:'BLOCKED',summary:'基于结果做判断'}],current_stage:'design',primary_next_action:{id:'CREATE_DESIGN',label:'创建设计',route:'/app/projects/P1/designs',stage:'design'}});
    if(path==='/api/client-contract')return resp({version:'0.88.1',static_cache_epoch:'0.88.1'});
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
        assert page.locator("#healthBadge").inner_text() == "服务正常 · 0.88.1"
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

        assert page_errors == []
        assert console_errors == []
        browser.close()
