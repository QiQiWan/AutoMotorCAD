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
def test_v087fb_windows_production_qualification_is_expert_visible_and_fail_closed_for_production():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        page.set_content('''<!doctype html><html><body>
          <article id="runtimeLifecyclePanelV087FA">
            <span id="runtimeLifecycleBadgeV087FA" class="badge">读取中</span>
            <button id="refreshRuntimeLifecycleV087FA" type="button">刷新生命周期</button>
            <div id="runtimeLifecycleSummaryV087FA"></div>
          </article>
        </body></html>''')
        page.evaluate('''
          window.fetch=async()=>({ok:true,json:async()=>({
            authority:'RuntimeLifecycleQualificationV1',contract_version:'0.87-F-A',local_qualified:true,
            production_qualified:false,production_boundary:'Windows + licensed Motor-CAD remains pending.',
            checks:[{code:'DATABASE_IDLE_WHEN_STOPPED',passed:true,message:'ok'}],
            database:{idle:true,active_connections:0,peak_connections:2},
            runtime:{state:'RUNNING',generation:3,active_task_thread_count:0,active_case_thread_count:0,
              scheduler:{lifecycle:{state:'OPEN'},active_leases:[]},
              worker_pool:{mode:'persistent',lifecycle:{state:'OPEN'},workers:[]}}
          })});
        ''')
        page.add_script_tag(content=(STATIC / "runtime" / "lifecycle-qualification.js").read_text(encoding="utf-8"))
        page.wait_for_function("document.body.innerText.includes('本地生命周期资格通过')")
        text = page.locator("#runtimeLifecyclePanelV087FA").inner_text()
        assert "Studio状态" in text
        assert "任务线程" in text
        assert "资源调度器" in text
        assert "SQLite" in text
        assert "生产资格保持 未通过" in text
        assert page.locator("#runtimeLifecycleBadgeV087FA").inner_text() == "本地生命周期通过"
        browser.close()
