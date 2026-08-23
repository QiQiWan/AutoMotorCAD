from __future__ import annotations

from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


@pytest.mark.e2e
def test_v087fc_soak_hmi_separates_local_soak_from_formal_native_qualification():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None, args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content('''<!doctype html><html><body>
          <span id="productionSoakBadgeV087FC"></span>
          <div id="productionSoakSummaryV087FC"></div>
        </body></html>''')
        page.evaluate('''
          window.api=async()=>({
            authority:'ProductionSoakQualificationV1',contract_version:'0.87-F-C',
            formal_production_hardened:false,formal_qualification_percent:0,
            local_control_plane_qualified:true,evidence_coverage_percent:100,
            matrix:{tiers:[{id:'SOAK_100',required_cases:100},{id:'SOAK_500',required_cases:500}]},
            latest_run:{mode:'LOCAL_CONTROL_PLANE',qualification_blockers:[],coverage:{coverage_percent:100},evidence:{
              mode:'LOCAL_CONTROL_PLANE',tiers:[
                {id:'SOAK_100',status:'PASS',completed_operations:100,studio_rss_growth_mb:4.2},
                {id:'SOAK_500',status:'PASS',completed_operations:500,studio_rss_growth_mb:9.8}
              ],recovery_probes:{}
            }}
          });
        ''')
        page.add_script_tag(content=(STATIC / "runtime" / "production-soak.js").read_text(encoding="utf-8"))
        page.evaluate("MCSProductionSoak.load()")
        page.wait_for_function("document.body.innerText.includes('本地控制面 Soak 已通过，等待 Native Soak')")
        text = page.locator("#productionSoakSummaryV087FC").inner_text()
        badge = page.locator("#productionSoakBadgeV087FC").inner_text()
        browser.close()
    assert badge == "本地Soak通过"
    assert "100/100 operations" in text
    assert "500/500 operations" in text
    assert "Production hardening" in text
    assert "0%" in text
    assert "Cancel → Retry" in text
    assert "motorcad-studio-production-soak" in text
