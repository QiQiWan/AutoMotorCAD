from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _browser(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(headless=True, executable_path=str(executable) if executable.is_file() else None, args=["--no-sandbox"])


def _load(page, body: str, prelude: str = ""):
    page.set_content(f"<html><body>{body}</body></html>")
    page.add_style_tag(content=(STATIC / "action-readiness.css").read_text(encoding="utf-8"))
    page.add_script_tag(content=f"""
      window.MCSAppState={{}};
      window.MCSEngineeringContext={{get:()=>({{}})}};
      {prelude}
    """)
    page.add_script_tag(content=(STATIC / "workflow" / "action-readiness.js").read_text(encoding="utf-8"))
    page.evaluate("MCSActionReadiness.refreshNow()")


@pytest.mark.e2e
def test_project_create_blocker_has_focus_recovery_and_unlocks_in_same_input_turn():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        _load(page, '<input id="projectCreateName"><button id="projectCreate" class="primary">创建项目</button>')
        before = page.evaluate("""() => ({disabled:projectCreate.disabled,status:projectCreate.dataset.actionReadiness,blocker:projectCreate.dataset.actionBlocker,recovery:projectCreate.dataset.actionRecovery,dead:MCSActionReadiness.qualify().dead_end_count})""")
        assert before["disabled"] is True
        assert before["status"] == "BLOCKED"
        assert "项目名称" in before["blocker"]
        assert before["recovery"] == "填写项目名称"
        assert before["dead"] == 0
        page.locator('[data-action-recovery-for="projectCreate"]').click()
        assert page.evaluate("document.activeElement===projectCreateName") is True
        page.locator("#projectCreateName").fill("工程项目A")
        # No wait: G2 requires readiness to converge in the same input turn.
        after = page.evaluate("""() => ({disabled:projectCreate.disabled,status:projectCreate.dataset.actionReadiness,qualified:MCSActionReadiness.qualify().qualified})""")
        assert after == {"disabled": False, "status": "READY", "qualified": True}
        browser.close()


@pytest.mark.e2e
def test_design_save_idle_is_not_a_dead_end_and_dirty_design_becomes_ready():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        _load(page, '<button id="workbenchSaveV024" class="primary">保存设计</button>', prelude="""
          window.__tx={active:true,dirty_count:0,save_busy:false,conflict:null};
          window.MCSDesignEditor={inspectTransaction:()=>window.__tx,verification:{snapshot:()=>({precheckCurrent:true,precheck:{issues:[]}})}};
        """)
        idle_row = page.evaluate("""() => ({disabled:workbenchSaveV024.disabled,status:workbenchSaveV024.dataset.actionReadiness,dead:MCSActionReadiness.qualify().dead_end_count})""")
        assert idle_row == {"disabled": True, "status": "IDLE", "dead": 0}
        page.evaluate("window.__tx.dirty_count=2; MCSActionReadiness.refreshNow()")
        ready = page.evaluate("""() => ({disabled:workbenchSaveV024.disabled,status:workbenchSaveV024.dataset.actionReadiness})""")
        assert ready == {"disabled": False, "status": "READY"}
        browser.close()


@pytest.mark.e2e
def test_analysis_submit_blocker_chain_always_exposes_executable_recovery():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        _load(page, '''
          <button id="analysisCreateV076" class="primary">新建分析</button>
          <button id="analysisInitialPlanV076">加载执行计划</button>
          <button id="analysisFullCheckV076" class="primary">完整检查</button>
          <button id="analysisSubmitV076" class="primary">开始计算</button>
        ''', prelude="""
          window.__a={active:true,executionPlan:null,fullCheck:null};
          window.MCSUnifiedAnalysis={state:window.__a};
          window.MCSEngineeringContext={get:()=>({projectId:'P1',motorRevisionId:'R1'})};
        """)
        first = page.evaluate("""() => ({status:analysisSubmitV076.dataset.actionReadiness,recovery:analysisSubmitV076.dataset.actionRecovery,dead:MCSActionReadiness.qualify().dead_end_count})""")
        assert first["status"] == "BLOCKED" and "执行计划" in first["recovery"] and first["dead"] == 0
        page.evaluate("window.__a.executionPlan={can_submit:true}; MCSActionReadiness.refreshNow()")
        second = page.evaluate("""() => ({status:analysisSubmitV076.dataset.actionReadiness,recovery:analysisSubmitV076.dataset.actionRecovery,dead:MCSActionReadiness.qualify().dead_end_count})""")
        assert second["status"] == "BLOCKED" and "完整计算前检查" in second["recovery"] and second["dead"] == 0
        page.evaluate("window.__a.fullCheck={valid:true}; MCSActionReadiness.refreshNow()")
        assert page.evaluate("analysisSubmitV076.dataset.actionReadiness") == "READY"
        assert page.locator("#analysisSubmitV076").is_enabled()
        browser.close()


@pytest.mark.e2e
def test_optimization_submit_and_promotion_have_recovery_or_idle_semantics():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        _load(page, '''
          <button data-opt-preview-v069>生成计划</button>
          <div data-opt-preview-result-v069></div>
          <button data-opt-submit-v069 class="primary">提交参数研究</button>
          <button data-opt-inspector-validate-v087e>验证候选</button>
          <button data-opt-inspector-promote-v087e class="primary" disabled>采用候选</button>
        ''', prelude="""
          window.__opt={preview:null}; window.MCSOptimizationWorkbench={state:window.__opt};
          window.__decision={selectedCandidateId:'C1',data:{candidates:[{candidate_id:'C1',is_baseline:false}]}};
          window.MCSOptimizationDecisionWorkbench={state:window.__decision};
        """)
        q1 = page.evaluate("""() => {const b=document.querySelector('[data-opt-submit-v069]');return {status:b.dataset.actionReadiness,recovery:b.dataset.actionRecovery,dead:MCSActionReadiness.qualify().dead_end_count}}""")
        assert q1["status"] == "BLOCKED" and q1["recovery"] == "生成计划并检查" and q1["dead"] == 0
        promote = page.evaluate("""() => {const b=document.querySelector('[data-opt-inspector-promote-v087e]');return {status:b.dataset.actionReadiness,recovery:b.dataset.actionRecovery,dead:MCSActionReadiness.qualify().dead_end_count}}""")
        assert promote["status"] == "BLOCKED" and promote["recovery"] == "先验证候选" and promote["dead"] == 0
        page.evaluate("window.__decision.data.candidates[0].is_baseline=true; MCSActionReadiness.refreshNow()")
        idle_status = page.evaluate("document.querySelector('[data-opt-inspector-promote-v087e]').dataset.actionReadiness")
        assert idle_status == "IDLE"
        browser.close()


@pytest.mark.e2e
def test_material_save_and_automation_import_remove_opaque_disabled_states():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        _load(page, '''
          <input id="materialNameV061"><button data-material-save-v089g2 class="primary">保存材料</button>
          <textarea id="automationText"></textarea><button id="importAutomationRegistry" class="primary">导入参数</button>
        ''')
        initial = page.evaluate("""() => ({m:document.querySelector('[data-material-save-v089g2]').dataset.actionReadiness,a:importAutomationRegistry.dataset.actionReadiness,dead:MCSActionReadiness.qualify().dead_end_count})""")
        assert initial == {"m": "BLOCKED", "a": "BLOCKED", "dead": 0}
        page.locator("#materialNameV061").fill("N42SH - Studio")
        page.locator("#automationText").fill("slot_count=12")
        after = page.evaluate("""() => ({m:document.querySelector('[data-material-save-v089g2]').dataset.actionReadiness,a:importAutomationRegistry.dataset.actionReadiness,q:MCSActionReadiness.qualify().qualified})""")
        assert after == {"m": "READY", "a": "READY", "q": True}
        browser.close()


@pytest.mark.e2e
def test_unmanaged_primary_and_missing_recovery_are_release_visible_failures():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        _load(page, '<button id="unmanagedFuturePrimary" class="primary" disabled>未来主操作</button>')
        report = page.evaluate("MCSActionReadiness.qualify()")
        assert report["qualified"] is False
        assert report["unmanaged_count"] == 1
        # Unmanaged disabled primaries cannot silently pass the gate.
        assert report["actions"][0]["status"] == "UNMANAGED"
        browser.close()
