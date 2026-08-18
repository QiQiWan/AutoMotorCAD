from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
CSS = (STATIC / "styles.css").read_text(encoding="utf-8") + "\n" + (STATIC / "design-v065.css").read_text(encoding="utf-8")

HTML = """
<body class="design-editing-v062">
  <div id="workspaceCanvas">
    <div class="model-workbench-v024">
      <aside class="workbench-tree-v024">tree</aside>
      <main class="workbench-main-v024">
        <section class="workbench-visual-v024">visual</section>
        <section class="workbench-parameter-editor-v024"><div class="workbench-parameter-rows-v024">editor</div></section>
      </main>
      <aside class="workbench-diagnostics-v024">diag</aside>
    </div>
    <section class="design-viewer-v031">
      <div class="design-view-body-v031">
        <div class="design-view-stage-v031">
          <div class="winding-slot-table-v031"><table><tr><td style="width:620px">table</td></tr></table></div>
        </div>
        <div id="designParamPanelV031">inspector</div>
      </div>
    </section>
  </div>
</body>
"""

def cols(page, selector: str) -> str:
    return page.eval_on_selector(selector, "el => getComputedStyle(el).gridTemplateColumns")

def areas(page, selector: str) -> str:
    return page.eval_on_selector(selector, "el => getComputedStyle(el).gridTemplateAreas")

def set_workspace_width(page, width: int) -> None:
    page.eval_on_selector("#workspaceCanvas", f"el => el.style.width='{width}px'")
    page.wait_for_timeout(30)

def set_viewer_width(page, width: int) -> None:
    page.eval_on_selector(".design-viewer-v031", f"el => el.style.width='{width}px'")
    page.wait_for_timeout(30)

def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 2000, "height": 1200})
        page.set_content(f"<style>{CSS}</style>{HTML}")

        set_workspace_width(page, 1400)
        assert len(cols(page, ".model-workbench-v024").split()) == 3, cols(page, ".model-workbench-v024")
        assert '"tree visual editor"' in areas(page, ".model-workbench-v024")

        set_workspace_width(page, 1200)
        assert len(cols(page, ".model-workbench-v024").split()) == 2, cols(page, ".model-workbench-v024")
        assert '"tree visual"' in areas(page, ".model-workbench-v024") and '"editor editor"' in areas(page, ".model-workbench-v024")

        set_workspace_width(page, 800)
        assert len(cols(page, ".model-workbench-v024").split()) == 1, cols(page, ".model-workbench-v024")
        assert '"tree"' in areas(page, ".model-workbench-v024") and '"diag"' in areas(page, ".model-workbench-v024")

        set_workspace_width(page, 1500)
        set_viewer_width(page, 1200)
        assert len(cols(page, ".design-view-body-v031").split()) == 2, cols(page, ".design-view-body-v031")
        set_viewer_width(page, 900)
        assert len(cols(page, ".design-view-body-v031").split()) == 1, cols(page, ".design-view-body-v031")

        set_viewer_width(page, 600)
        overflow = page.eval_on_selector(
            ".winding-slot-table-v031",
            "el => ({client: el.clientWidth, scroll: el.scrollWidth, overflow: getComputedStyle(el).overflowX})",
        )
        assert overflow["scroll"] > overflow["client"], overflow
        assert overflow["overflow"] in {"auto", "scroll"}, overflow
        root_overflow = page.eval_on_selector("#workspaceCanvas", "el => ({client: el.clientWidth, scroll: el.scrollWidth})")
        assert root_overflow["scroll"] <= root_overflow["client"] + 1, root_overflow

        browser.close()
    print("V0.64 layout contract: PASS")

if __name__ == "__main__":
    main()
