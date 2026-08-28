from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _load(page, summary):
    page.set_content('''
      <div id="uiSoakPanelV089E">
        <span id="uiSoakBadgeV089E"></span>
        <button id="refreshUISoakV089E">刷新</button>
        <div id="uiSoakSummaryV089E"></div>
      </div>
    ''')
    page.evaluate("value => { window.api = async () => value; }", summary)
    page.add_script_tag(content=(STATIC / 'runtime' / 'ui-soak-qualification.js').read_text(encoding='utf-8'))
    page.evaluate("() => window.MCSUISoakQualification.load()")


def _formal_summary():
    tiers = {
        'UI_SOAK_100': {'passed': True, 'issues': [], 'metrics': {'requested_cycles': 100, 'completed_cycles': 100, 'interaction_count': 145, 'js_heap_growth_mb': 12.4, 'dom_node_growth': 14}},
        'UI_SOAK_500': {'passed': True, 'issues': [], 'metrics': {'requested_cycles': 500, 'completed_cycles': 500, 'interaction_count': 730, 'js_heap_growth_mb': 44.2, 'dom_node_growth': 31}},
    }
    faults = {fid: {'passed': True, 'issues': []} for fid in [
        'DIRTY_NAVIGATION_GUARD','ROUTE_COMMIT_ROLLBACK','SAVE_RESPONSE_LOSS_REPLAY','DOUBLE_CLICK_SINGLE_FLIGHT',
        'HTTP_409_CONFLICT_RECOVERY','HTTP_500_RETRY_RECOVERY','NETWORK_OFFLINE_RECOVERY','BROWSER_RELOAD_CONTEXT_RESTORE',
        'MODAL_INTERRUPT_CLEANUP','ACTIVE_TASK_REFRESH_SURVIVAL','RESULT_REOPEN_AFTER_RELOAD','WORKER_RECYCLE_SURVIVAL'
    ]}
    native = {fid: {'passed': True, 'status': 'PASS'} for fid in [
        'EXECUTABLE_MISSING_OR_UNSUPPORTED','LICENSE_UNAVAILABLE','WORKER_CRASH','BROWSER_REFRESH_ACTIVE_TASK','STUDIO_RESTART_REOPEN'
    ]}
    raw_tiers = [
        {'id': tid, 'status': 'PASS', **row['metrics']} for tid, row in tiers.items()
    ]
    raw_faults = [{'id': fid, 'status': 'PASS'} for fid in faults]
    matrix = {
        'tiers': [{'id': 'UI_SOAK_100', 'required_cycles': 100}, {'id': 'UI_SOAK_500', 'required_cycles': 500}],
        'fault_scenarios': [{'id': fid} for fid in faults],
        'inherited_native_faults': list(native),
    }
    latest = {
        'run_id': 'V089E-FORMAL-001', 'formal_qualified': True, 'local_browser_qualified': False,
        'qualification_blockers': [],
        'coverage': {'coverage_percent': 100.0, 'tier_results': tiers, 'fault_results': faults, 'inherited_native_fault_results': native},
        'evidence': {'tiers': raw_tiers, 'fault_injections': raw_faults},
    }
    return {'formal_qualified': True, 'formal_qualification_percent': 100, 'local_browser_qualified': False, 'evidence_coverage_percent': 100.0, 'latest_run': latest, 'matrix': matrix}


@pytest.mark.e2e
def test_v089e_formal_hmi_renders_tiers_faults_and_native_inheritance():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None, args=["--no-sandbox"])
        page = browser.new_page()
        _load(page, _formal_summary())
        page.wait_for_function("() => document.querySelector('#uiSoakSummaryV089E').textContent.includes('500/500')")
        text = page.locator('#uiSoakSummaryV089E').inner_text()
        badge = page.locator('#uiSoakBadgeV089E').inner_text()
        browser.close()
    assert '100/100' in text
    assert '500/500' in text
    assert '12/12' in text
    assert '5/5' in text
    assert '100%' in text
    assert 'UI韧性' in badge or '正式' in badge


@pytest.mark.e2e
def test_v089e_pending_hmi_surfaces_blockers():
    summary = _formal_summary()
    summary['formal_qualified'] = False
    summary['formal_qualification_percent'] = 0
    summary['latest_run']['formal_qualified'] = False
    summary['latest_run']['qualification_blockers'] = ['V089D_PREDECESSOR_NOT_FORMAL', 'UI_SOAK_TIER_INCOMPLETE']
    summary['latest_run']['coverage']['coverage_percent'] = 78.4
    summary['evidence_coverage_percent'] = 78.4
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None, args=["--no-sandbox"])
        page = browser.new_page()
        _load(page, summary)
        page.wait_for_function("() => document.querySelector('#uiSoakSummaryV089E').textContent.includes('V089D_PREDECESSOR_NOT_FORMAL')")
        text = page.locator('#uiSoakSummaryV089E').inner_text()
        browser.close()
    assert 'V089D_PREDECESSOR_NOT_FORMAL' in text
    assert 'UI_SOAK_TIER_INCOMPLETE' in text
    assert '78% evidence' in text
