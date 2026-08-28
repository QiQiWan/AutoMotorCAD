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
def test_v088f_native_geometrytree_card_renders_exact_region_primitives_in_browser():
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.set_content('<!doctype html><html><body><div id="root"></div></body></html>')
        page.add_style_tag(content=(STATIC / "design-workbench.css").read_text(encoding="utf-8"))
        page.evaluate('''
          window.esc=v=>String(v??'');
          window.MCSDesignGeometry={render:(view,ctx)=>`<div class="engineering-view">${view}:${ctx.visualSource}</div>`};
          window.MCSDesignWinding={render:()=>null};
          window.MCSDesignMaterials={render:()=>null};
          window.MCSDesignValidation={render:()=>null};
          window.MCSDesignParameterInspector={readOnlyPanel:()=>''};
        ''')
        page.add_script_tag(content=(STATIC / "design" / "render-utils.js").read_text(encoding="utf-8"))
        page.add_script_tag(content=(STATIC / "design" / "renderer.js").read_text(encoding="utf-8"))
        page.evaluate('''
          const spatial={
            authority:'NativeSpatialGeometryAuthorityV1',status:'COMPLETE',content_hash:'abcdef0123456789',drawable_region_count:1,entity_count:4,
            bounds:{xmin:-10,xmax:10,ymin:-5,ymax:5},
            regions:[{name:'Rotor',material:'M350-50A',entities:[
              {kind:'line',display_points:[[-10,-5],[10,-5]]},
              {kind:'line',display_points:[[10,-5],[10,5]]},
              {kind:'line',display_points:[[10,5],[-10,5]]},
              {kind:'line',display_points:[[-10,5],[-10,-5]]}
            ]}]
          };
          const reconciliation={authority:'NativePreviewReconciliationAuthorityV1',status:'NATIVE_CURRENT',default_source:'native',native_render_allowed:true,native_authoritative:true,compare_allowed:true,native_spatial_geometry:spatial,native_projection:{spatial_geometry:spatial},source:{phase:'post_solve',design_state_hash:'1234567890abcdef'}};
          const data={design_views:[{id:'radial',parameter_ids:[]}],effective_parameters:{},parameters:[]};
          document.querySelector('#root').innerHTML=MCSDesignRenderer.renderWorkbenchView('radial',{data,visualSource:'native',visualizationReconciliation:reconciliation,editable:false});
        ''')
        assert errors == []
        card = page.locator('.native-spatial-preview-v088f')
        assert card.count() == 1
        assert '原生区域边界' in card.inner_text()
        assert 'COMPLETE · 1 个区域 · 4 个几何元素' in card.inner_text()
        assert card.locator('polyline').count() == 4
        assert card.locator('title').text_content() == 'Rotor · M350-50A'
        assert page.locator('.engineering-view').inner_text() == 'radial:native'
        browser.close()
