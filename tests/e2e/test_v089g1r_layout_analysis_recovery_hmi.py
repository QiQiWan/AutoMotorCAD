from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _browser(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(headless=True, executable_path=str(executable) if executable.is_file() else None, args=["--no-sandbox"])


@pytest.mark.e2e
def test_material_workspace_defaults_to_90_percent_and_source_detail_is_collapsed():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.set_content("<html><body></body></html>")
        page.add_style_tag(content=(STATIC / "styles.css").read_text(encoding="utf-8"))
        page.add_script_tag(content="""
          window.toast=()=>{};
          window.api=async (path,opts={})=>{
            if(path==='/api/material-library/status') return {records:109,custom_records:1,motorcad_version:'2026R1',databases:[{path:'C:/MotorCAD/materials/solids.mdb',kind:'solid',material_count:92,file_hash:'abc',source:'Defaults.INI'}],discovered:[]};
            if(path.startsWith('/api/material-library?')) return {records:[{id:'MAT-1',name:'N42SH',kind:'solid',material_type:'Magnet',source_kind:'motorcad_database'}]};
            if(path==='/api/material-library/MAT-1') return {id:'MAT-1',name:'N42SH',kind:'solid',material_type:'Magnet',source_kind:'motorcad_database',properties:{},summary:{bh_curve:[],magnet_bh_curve:[],magnet_reference_curve:[{h:-300000,b:0},{h:0,b:1.2}],magnet_temperature_points:[{temperature:20,br:1.2,hcj:1900000},{temperature:180,br:1.0,hcj:1200000}],magnet_reference_meta:{reference_temperature:20},loss_points:[]}};
            throw new Error('unexpected '+path);
          };
        """)
        page.add_script_tag(content=(STATIC / "materials" / "library.js").read_text(encoding="utf-8"))
        page.evaluate("MCSMaterialLibrary.open()")
        page.wait_for_selector('.material-library-compact-head-v089g1r')
        metrics = page.evaluate("""() => {
          const dialog=document.querySelector('#materialLibraryV061>section').getBoundingClientRect();
          const details=document.querySelector('.material-source-details-v089g1r');
          const compact=document.querySelector('.material-library-compact-head-v089g1r').getBoundingClientRect();
          return {w:dialog.width/window.innerWidth,h:dialog.height/window.innerHeight,open:details.open,compactHeight:compact.height,curveTitle:document.querySelector('.material-curve-card-v061')?.innerText||'',circles:document.querySelectorAll('.material-curve-card-v061 circle').length};
        }""")
        assert 0.88 <= metrics["w"] <= 0.92
        assert 0.88 <= metrics["h"] <= 0.92
        assert metrics["open"] is False
        assert metrics["compactHeight"] < 70
        assert metrics["circles"] >= 2
        browser.close()


@pytest.mark.e2e
def test_analysis_load_failure_keeps_route_controls_alive_and_mount_resolves_fail_soft():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.set_content('''<html><body>
          <button id="analysisCommonModeV081A">常用</button><button id="analysisAdvancedModeV081A">高级</button>
          <button id="analysisBackToMotorV076">返回</button><button id="analysisRefreshV076">刷新</button><button id="analysisCreateV076">新建</button>
          <div id="analysisContextV076"></div><div id="analysisListV076"></div><div id="analysisSummaryV076"></div>
          <div id="analysisEmptyV076"></div><div id="analysisEditorV076" class="hidden"><nav id="analysisStepsV076"></nav><section id="analysisEditorBodyV076"></section></div>
        </body></html>''')
        page.evaluate("Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}})")
        page.add_script_tag(content="""
          var state={activeProjectId:'P1',registry:{outputs:{}}};
          window.__apiCalls=0; window.__backCalls=0; window.__mountRejected=false;
          window.api=async()=>{window.__apiCalls+=1; throw new Error('模拟项目读取失败')};
          window.toast=()=>{}; window.showTab=()=>{window.__backCalls+=1};
          window.MCSEngineeringContext={get:()=>({projectId:'P1'}),setStage:()=>{},setProject:()=>{},setAnalysis:()=>{},setMotorRevision:()=>{}};
          window.MCSNavigationTransaction={registerGuard:()=>{},withActionLock:(k,fn)=>Promise.resolve().then(fn)};
          window.MCSPageRuntime={isContextActive:()=>true,isAbortError:()=>false};
        """)
        page.add_script_tag(content=(STATIC / "analysis" / "unified-configuration.js").read_text(encoding="utf-8"))
        result = page.evaluate("""async () => {
          const ctx={listen:(el,event,fn)=>el&&el.addEventListener(event,fn),api:async()=>{window.__apiCalls+=1;throw new Error('模拟项目读取失败')},assertActive:()=>{}};
          try { const value=await MCSUnifiedAnalysis.mount({},ctx); return {rejected:false,value}; }
          catch(e) { return {rejected:true,message:e.message}; }
        }""")
        assert result["rejected"] is False
        assert page.locator('.analysis-load-error-v089g1r').is_visible()
        page.locator('#analysisBackToMotorV076').click()
        assert page.evaluate('window.__backCalls') == 1
        before = page.evaluate('window.__apiCalls')
        page.locator('[data-analysis-retry-v076]').click()
        page.wait_for_timeout(80)
        assert page.evaluate('window.__apiCalls') > before
        # The common/advanced controls are still event-bound after the load error.
        page.locator('#analysisAdvancedModeV081A').click()
        assert page.evaluate("MCSUnifiedAnalysis.state.hmiMode") == 'advanced'
        browser.close()


@pytest.mark.e2e
def test_engineering_shell_hides_technical_breadcrumb_and_uses_compact_three_part_focus_bar():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.set_content('''<html><body class="studio-v089g1" data-user-mode="engineering">
          <section id="projectShell" class="project-shell">
            <div class="project-shell-context"><div class="project-shell-title"><span>当前项目</span><b>AAA测试项目</b><small>PRJ-1</small></div></div>
            <nav class="project-stage-nav"><button><span>1</span><b>设计</b></button><button><span>2</span><b>验证</b></button><button><span>3</span><b>决策</b></button></nav>
            <div id="engineeringContextBreadcrumbV089A" class="engineering-context-breadcrumb-v089a">技术路径</div>
            <div id="engineerFocusBarV089F" class="engineer-focus-bar-v089f"><div class="engineer-focus-cell-v089f current"><span>当前</span><b>验证</b><small>SPM · Rev.2</small></div><div class="engineer-focus-cell-v089f clear"><span>状态</span><b>准备就绪</b><small>无阻断项</small></div><div class="engineer-focus-cell-v089f next"><span>下一步</span><b>配置分析</b><small>完成当前动作</small><button>继续 →</button></div></div>
          </section>
        </body></html>''')
        page.add_style_tag(content=(STATIC / "styles.css").read_text(encoding="utf-8"))
        page.add_style_tag(content=(STATIC / "engineer-ux-convergence.css").read_text(encoding="utf-8"))
        page.add_style_tag(content=(STATIC / "global-shell-convergence.css").read_text(encoding="utf-8"))
        values = page.evaluate("""() => ({breadcrumb:getComputedStyle(document.querySelector('#engineeringContextBreadcrumbV089A')).display,cols:getComputedStyle(document.querySelector('#engineerFocusBarV089F')).gridTemplateColumns,height:document.querySelector('#engineerFocusBarV089F').getBoundingClientRect().height,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+2})""")
        assert values['breadcrumb'] == 'none'
        assert values['height'] <= 60
        assert values['overflow'] is False
        assert len(values['cols'].split()) == 3
        browser.close()

@pytest.mark.e2e
def test_material_context_copy_does_not_overlap_primary_action():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page(viewport={"width": 900, "height": 700})
        page.set_content('''<body><aside class="design-context-panel-v031" style="width:360px;height:420px;display:flex;flex-direction:column">
          <span class="eyebrow">材料配置</span><h4>当前部件材料</h4><p>材料随电机版本保存；冷却介质在分析配置中设置。</p>
          <div class="context-rule-v031"><b>如何更换材料</b><span>进入材料配置后，在目标部件行点击“选择材料”；材料库会自动带入当前部件。</span></div>
          <button type="button" class="primary edit-view-v031">进入材料配置</button>
        </aside></body>''')
        page.add_style_tag(content=(STATIC / "styles.css").read_text(encoding="utf-8"))
        rects = page.evaluate("""() => {const copy=document.querySelector('.context-rule-v031').getBoundingClientRect(),btn=document.querySelector('.edit-view-v031').getBoundingClientRect();return {copyBottom:copy.bottom,btnTop:btn.top,copyHeight:copy.height}}""")
        assert rects['copyHeight'] > 20
        assert rects['btnTop'] >= rects['copyBottom']
        browser.close()


@pytest.mark.e2e
def test_forced_clean_draft_persist_uses_put_and_materializes_editor_transaction():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.set_content('<body></body>')
        page.add_script_tag(content="""
          window.__calls=[]; window.toast=()=>{};
          window.api=async (path,opts={})=>{window.__calls.push({path,method:opts.method||'GET',body:opts.body||null});return {draft:{design_id:'D1',base_revision_id:'R1',version:2,updated_at:'2026-08-26T00:00:00Z',editor_transaction:{transaction_hash:'tx-hash',intent_hash:'intent-hash'}}}};
        """)
        page.add_script_tag(content=(STATIC / "design" / "draft-service.js").read_text(encoding="utf-8"))
        result = page.evaluate("""async()=>{const svc=MCSDesignDraftService.create({getDesignId:()=> 'D1',hasChanges:()=>false,buildPayload:()=>({base_revision_id:'R1',parameters:{},materials:{}})});svc.begin({draft:null});const draft=await svc.persist({silent:true,reason:'native-reconciliation-bootstrap',force:true});return {draft,calls:window.__calls};}""")
        assert len(result['calls']) == 1
        assert result['calls'][0]['method'] == 'PUT'
        assert result['draft']['editor_transaction']['transaction_hash'] == 'tx-hash'
        browser.close()

@pytest.mark.e2e
def test_optional_analysis_catalog_failure_does_not_collapse_page_mount():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        page.set_content('''<html><body>
          <button id="analysisCommonModeV081A">常用</button><button id="analysisAdvancedModeV081A">高级</button>
          <button id="analysisBackToMotorV076">返回</button><button id="analysisRefreshV076">刷新</button><button id="analysisCreateV076">新建</button>
          <div id="analysisContextV076"></div><div id="analysisListV076"></div><div id="analysisSummaryV076"></div>
          <div id="analysisEmptyV076"></div><div id="analysisEditorV076" class="hidden"><nav id="analysisStepsV076"></nav><section id="analysisEditorBodyV076"></section></div>
        </body></html>''')
        page.evaluate("Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}})")
        page.add_script_tag(content="""
          var state={activeProjectId:'P1',registry:{outputs:{}}};
          window.toast=()=>{}; window.showTab=()=>{};
          window.MCSEngineeringContext={get:()=>({projectId:'P1'}),setStage:()=>{},setProject:()=>{},setAnalysis:()=>{},setMotorRevision:()=>{}};
          window.MCSNavigationTransaction={registerGuard:()=>{},withActionLock:(k,fn)=>Promise.resolve().then(fn)};
          window.MCSPageRuntime={isContextActive:()=>true,isAbortError:()=>false};
          window.api=async (path)=>{
            if(path==='/api/projects/P1') return {id:'P1',name:'项目一',designs:[{id:'D1',name:'SPM 工程设计'}]};
            if(path==='/api/solutions/D1') return {id:'D1',name:'SPM 工程设计',motor_type_id:'BPM',revisions:[{id:'R1',revision:2}]};
            if(path==='/api/projects/P1/analysis-definitions') return [];
            if(path.startsWith('/api/analysis-catalog?')) throw new Error('catalog unavailable');
            throw new Error('unexpected '+path);
          };
        """)
        page.add_script_tag(content=(STATIC / "analysis" / "unified-configuration.js").read_text(encoding="utf-8"))
        result = page.evaluate("""async () => {
          const ctx={listen:(el,event,fn)=>el&&el.addEventListener(event,fn),api:window.api,assertActive:()=>{}};
          try { const value=await MCSUnifiedAnalysis.mount({},ctx); return {rejected:false,value,catalog:MCSUnifiedAnalysis.state.catalog}; }
          catch(e) { return {rejected:true,message:e.message}; }
        }""")
        assert result['rejected'] is False
        assert result['catalog']['recipes'] == []
        assert page.locator('#analysisCreateV076').is_enabled()
        page.locator('#analysisCreateV076').click()
        page.wait_for_timeout(30)
        assert page.locator('#analysisEditorV076').is_visible()
        browser.close()
