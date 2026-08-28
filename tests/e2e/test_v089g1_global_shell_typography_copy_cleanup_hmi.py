from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _browser(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(headless=True, executable_path=str(executable) if executable.is_file() else None, args=["--no-sandbox"])


def _mount(page, width=1920, height=1080):
    page.set_viewport_size({"width": width, "height": height})
    page.set_content('''
    <html lang="zh-CN"><body class="studio-v089g1" data-user-mode="operator">
      <section id="projectShell" class="project-shell">
        <div class="project-shell-context"><button>← 项目管理</button><div class="project-shell-title"><span>当前项目</span><b>AAA测试项目</b><small>PRJ-001</small></div></div>
        <nav class="project-stage-nav"><button><span>1</span><b>设计</b></button><button><span>2</span><b>验证</b></button><button><span>3</span><b>决策</b></button></nav>
        <div id="engineeringContextBreadcrumbV089A" class="engineering-context-breadcrumb-v089a">技术上下文</div>
        <div id="engineerFocusBarV089F" class="engineer-focus-bar-v089f">
          <div class="engineer-focus-cell-v089f"><span>当前位置</span><b>设计</b><small>AAA测试项目</small></div>
          <div class="engineer-focus-cell-v089f"><span>当前状态</span><b>待创建电机版本</b><small>尚未选择方案</small></div>
          <div class="engineer-focus-cell-v089f"><span>需要处理</span><b>选择预制设计</b><small>完成后继续</small></div>
          <div class="engineer-focus-cell-v089f next"><span>下一步</span><b>创建设计</b><small>选择一个工程预制设计</small><button>执行下一步 →</button></div>
        </div>
      </section>
      <main><section><div id="copyTarget"><button id="copyAction">保存设计</button></div></section></main>
      <div class="expert-only"><button>ResultBundle Evidence</button></div>
    </body></html>
    ''')
    page.add_style_tag(content=(STATIC / "styles.css").read_text(encoding="utf-8"))
    page.add_style_tag(content=(STATIC / "engineer-ux-convergence.css").read_text(encoding="utf-8"))
    page.add_style_tag(content=(STATIC / "global-shell-convergence.css").read_text(encoding="utf-8"))
    page.evaluate("window.MCS_I18N={language:'zh'}")
    page.add_script_tag(content=(STATIC / "workflow" / "global-shell-convergence.js").read_text(encoding="utf-8"))


@pytest.mark.e2e
def test_v089g1_focus_bar_spans_full_project_shell_and_typography_is_readable():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw); page = browser.new_page(); _mount(page)
        metrics = page.evaluate('''() => {
          const shell=document.querySelector('#projectShell').getBoundingClientRect();
          const focus=document.querySelector('#engineerFocusBarV089F').getBoundingClientRect();
          const value=getComputedStyle(document.querySelector('.engineer-focus-cell-v089f>b')).fontSize;
          const detail=getComputedStyle(document.querySelector('.engineer-focus-cell-v089f>small')).fontSize;
          return {shellWidth:shell.width,focusWidth:focus.width,value,detail,scroll:document.querySelector('#engineerFocusBarV089F').scrollWidth,client:document.querySelector('#engineerFocusBarV089F').clientWidth};
        }''')
        assert abs(metrics['shellWidth'] - metrics['focusWidth']) <= 3
        assert float(metrics['value'].replace('px','')) >= 14
        assert float(metrics['detail'].replace('px','')) >= 12
        assert metrics['scroll'] <= metrics['client'] + 2
        assert page.evaluate("MCSGlobalShellConvergence.audit().passed") is True
        browser.close()


@pytest.mark.e2e
def test_v089g1_focus_bar_remains_unclipped_at_compact_desktop_width():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw); page = browser.new_page(); _mount(page, width=1366, height=768)
        result = page.evaluate('''() => ({
          documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
          focusOverflow: document.querySelector('#engineerFocusBarV089F').scrollWidth > document.querySelector('#engineerFocusBarV089F').clientWidth + 2,
          focusRows: getComputedStyle(document.querySelector('#engineerFocusBarV089F')).gridTemplateColumns
        })''')
        assert result['documentOverflow'] is False
        assert result['focusOverflow'] is False
        assert result['focusRows']
        browser.close()


@pytest.mark.e2e
def test_v089g1_guided_copy_audit_detects_raw_english_and_ignores_expert_evidence():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw); page = browser.new_page(); _mount(page)
        assert page.evaluate("MCSGlobalShellConvergence.audit().passed") is True
        page.locator('#copyAction').evaluate("el=>el.textContent='Create design in current project'")
        bad = page.evaluate("MCSGlobalShellConvergence.audit()")
        assert bad['passed'] is False
        assert any('RAW_GUIDED_COPY:Create design in current project' in issue for issue in bad['issues'])
        page.locator('#copyAction').evaluate("el=>el.textContent='在当前项目中创建设计'")
        good = page.evaluate("MCSGlobalShellConvergence.audit()")
        assert good['passed'] is True
        browser.close()
