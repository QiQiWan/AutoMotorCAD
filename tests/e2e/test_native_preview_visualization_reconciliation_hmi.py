from __future__ import annotations

from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _launch(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(headless=True, executable_path=str(executable) if executable.is_file() else None, args=["--no-sandbox"])


@pytest.mark.e2e
def test_v088e_design_native_compare_toolbar_and_compare_canvas_render_without_errors():
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.set_content('<!doctype html><html><body><div id="root"></div></body></html>')
        page.add_style_tag(content=(STATIC / "design-workbench.css").read_text(encoding="utf-8"))
        page.evaluate('''
          window.esc=v=>String(v??'');
          window.MCSDesignGeometry={render:(view,ctx)=>`<div class="probe-view" data-source="${ctx.visualSource}">${view}:${ctx.visualSource}</div>`};
          window.MCSDesignWinding={render:()=>null};
          window.MCSDesignMaterials={render:()=>null};
          window.MCSDesignValidation={render:()=>null};
          window.MCSDesignParameterInspector={readOnlyPanel:()=>''};
        ''')
        page.add_script_tag(content=(STATIC / "design" / "render-utils.js").read_text(encoding="utf-8"))
        page.add_script_tag(content=(STATIC / "design" / "renderer.js").read_text(encoding="utf-8"))
        page.evaluate('''
          const data={design_views:[{id:'radial',parameter_ids:['air_gap']}],effective_parameters:{air_gap:0.8},parameters:[{id:'air_gap',label:'气隙',unit:'mm',category:'geometry'}]};
          const reconciliation={authority:'NativePreviewReconciliationAuthorityV1',status:'NATIVE_CURRENT',default_source:'native',native_render_allowed:true,native_authoritative:true,compare_allowed:true,native_projection:{geometry_evidence:{region_names:['Stator','Rotor','Magnet']}},source:{phase:'post_solve',design_state_hash:'abcdef0123456789'},diffs:[{semantic_id:'air_gap',label:'气隙',unit:'mm',category:'geometry',design_value:0.8,native_value:0.82,status:'DELTA'}]};
          const toolbar=MCSDesignRenderer.toolbar(data,{source:'compare',mode:'read',reconciliation});
          const view=MCSDesignRenderer.renderWorkbenchView('radial',{data,visualSource:'compare',visualizationReconciliation:reconciliation,editable:false});
          document.querySelector('#root').innerHTML=toolbar+view;
        ''')
        assert errors == []
        assert page.locator("[data-visual-source-v088e='design']").inner_text() == "设计意图"
        assert page.locator("[data-visual-source-v088e='native']").inner_text() == "Motor-CAD 原生"
        assert page.locator("[data-visual-source-v088e='compare']").inner_text() == "差异对比"
        assert page.locator(".visual-reconciliation-compare-v088e section").count() == 2
        assert page.locator(".probe-view[data-source='design']").count() == 1
        assert page.locator(".probe-view[data-source='native']").count() == 1
        assert "1 项需要关注" in page.locator(".visual-diff-summary-v088e").inner_text()
        assert "GeometryTree 3 regions" in page.locator(".visual-source-status-v088e").inner_text()
        browser.close()
