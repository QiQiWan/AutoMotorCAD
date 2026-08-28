from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _browser(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(headless=True, executable_path=str(executable) if executable.is_file() else None, args=["--no-sandbox"])


@pytest.mark.e2e
def test_v089f_engineer_focus_bar_answers_four_engineer_questions():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw); page = browser.new_page()
        page.set_content('''<body data-user-mode="operator"><section id="projectShell"><div id="engineeringContextBreadcrumbV089A" class="engineering-context-breadcrumb-v089a">technical</div><div id="engineerFocusBarV089F"></div></section><section id="workspace" class="tab active"></section><select id="userMode"><option value="operator">operator</option></select></body>''')
        page.evaluate("""() => {
          document.body.dataset.userMode='operator';
          window.MCSEngineeringContext={get:()=>({projectId:'P1',solutionId:'S1',solution:{name:'AFPM方案'},motorRevisionId:'R3',motorRevision:{revision:3}}),inspect:()=>({valid:true,issues:[]})};
          window.MCSRouter={navigate:r=>{window.__route=r}};
        }""")
        page.add_style_tag(content=(STATIC / 'engineer-ux-convergence.css').read_text(encoding='utf-8'))
        page.add_script_tag(content=(STATIC / 'workflow' / 'engineer-ux-convergence.js').read_text(encoding='utf-8'))
        page.evaluate("""() => MCSGlobalWorkflowTruth = undefined""")
        page.evaluate("""() => MCSEngineerUX.ingest({current_stage:'analysis',stages:[{id:'analysis',status:'CURRENT',summary:'配置工况并检查'}],run_center:{summary:{active:0}},failure_center:{items:[]},next_action:{label:'进入分析配置',route:'/app/projects/P1/simulation/analyses'}})""")
        text = page.locator('#engineerFocusBarV089F').inner_text()
        assert '当前' in text and '状态' in text and '下一步' in text
        assert 'AFPM方案' in text and 'Rev.3' in text
        assert page.locator('#engineeringContextBreadcrumbV089A').is_visible() is False
        page.click('[data-hmi-action="ENGINEER_FOCUS_NEXT"]')
        assert page.evaluate('window.__route') == '/app/projects/P1/simulation/analyses'
        browser.close()


@pytest.mark.e2e
def test_v089f_rc_gate_distinguishes_local_ready_from_formal_rc():
    playwright = pytest.importorskip("playwright.sync_api")
    summary={
      'label':'本地 RC 已就绪 · 实机资格待完成','local_rc_ready':True,'formal_rc_qualified':False,
      'next_action':'在 Windows 工作站执行正式资格','formal_blockers':['licensed_windows_native','human_engineer_acceptance'],
      'formal_checks':{'automated_release_gate':True,'licensed_windows_native':False,'windows_ui_golden_journeys':False,'native_100_500_soak':False,'ui_100_500_fault_recovery':False,'human_engineer_acceptance':False},
      'workstation':{'native_percent':0,'golden_journey_percent':0,'native_soak_percent':0,'ui_resilience_percent':0}
    }
    with playwright.sync_playwright() as pw:
        browser=_browser(pw);page=browser.new_page()
        page.set_content('<span id="releaseCandidateBadgeV089F"></span><button id="refreshReleaseCandidateGateV089F">刷新</button><button id="exportReleaseCandidateChecklistV089F">导出</button><div id="releaseCandidateGateSummaryV089F"></div>')
        page.evaluate('(v)=>{window.api=async()=>v}',summary)
        page.add_script_tag(content=(STATIC/'runtime'/'release-candidate-gate.js').read_text(encoding='utf-8'))
        page.evaluate('()=>MCSReleaseCandidateGate.refresh()')
        page.wait_for_function("() => document.querySelector('#releaseCandidateGateSummaryV089F').textContent.includes('LOCAL RC')")
        text=page.locator('#releaseCandidateGateSummaryV089F').inner_text()
        assert '本地 RC 已就绪' in text
        assert 'Windows + Motor-CAD 实机' in text
        assert '工程师人工验收' in text
        assert page.locator('#releaseCandidateBadgeV089F').inner_text() == '本地RC就绪'
        browser.close()

@pytest.mark.e2e
def test_v089f_guided_terminology_translates_internal_object_names_without_touching_expert_evidence():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw); page = browser.new_page()
        page.set_content('''<body data-user-mode="operator">
          <div id="guided">当前 Design Revision 的 ResultBundle / Case 使用 Native Binding。</div>
          <div class="expert-only" id="expert">Design Revision · ResultBundle · Native Binding · Case</div>
        </body>''')
        page.evaluate("() => Object.defineProperty(window,'localStorage',{value:{getItem:()=>null,setItem:()=>{}},configurable:true})")
        page.add_script_tag(content=(STATIC / 'i18n.js').read_text(encoding='utf-8'))
        page.evaluate("() => MCS_I18N.apply()")
        guided = page.locator('#guided').inner_text()
        assert '电机版本' in guided
        assert '计算结果' in guided
        assert '计算工况' in guided
        assert 'Motor-CAD 参数映射' in guided
        expert = page.locator('#expert').inner_text()
        assert 'Design Revision' in expert and 'ResultBundle' in expert and 'Native Binding' in expert and 'Case' in expert
        browser.close()
