from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
CSS = (STATIC / "styles.css").read_text(encoding="utf-8") + "\n" + (STATIC / "design-v065.css").read_text(encoding="utf-8")

HTML = """
<body class="design-editing-v062">
  <div id="workspaceCanvas" style="container-type:inline-size;container-name:design-workspace">
    <section class="model-workbench-v024">
      <aside class="workbench-tree-v024">tree</aside>
      <main class="workbench-main-v024">
        <section class="workbench-visual-v024">
          <div class="draft-validation-view-v065">
            <div class="validation-pipeline-v065">
              <article class="pass"><span>1</span><div><b>Studio 设计检查</b><small>尺寸和拓扑检查</small></div><strong>通过</strong></article>
              <i></i>
              <article class="pending"><span>2</span><div><b>Motor-CAD 原生验证</b><small>显式调用原生模型</small></div><strong>待验证</strong></article>
            </div>
            <div class="validation-action-grid-v065">
              <button><b>运行 Studio 检查</b><span>验证当前草稿</span></button>
              <button><b>运行 Motor-CAD 验证</b><span>使用本机原生环境</span></button>
            </div>
            <div class="draft-conflict-banner-v065"><div><b>草稿已更新</b><span>另一个窗口保存了新版本。</span></div><div class="actions"><button>重新加载</button></div></div>
          </div>
        </section>
        <section class="workbench-parameter-editor-v024">editor</section>
      </main>
      <aside class="workbench-diagnostics-v024">diag</aside>
    </section>
  </div>
</body>
"""


def set_width(page, width: int) -> None:
    page.eval_on_selector("#workspaceCanvas", f"el => el.style.width='{width}px'")
    page.wait_for_timeout(40)


def columns(page, selector: str) -> list[str]:
    value = page.eval_on_selector(selector, "el => getComputedStyle(el).gridTemplateColumns")
    return [part for part in value.split() if part]


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1800, "height": 1100})
        page.set_content(f"<style>{CSS}</style>{HTML}")

        set_width(page, 1200)
        assert len(columns(page, ".validation-pipeline-v065")) == 3, columns(page, ".validation-pipeline-v065")
        assert len(columns(page, ".validation-action-grid-v065")) == 2, columns(page, ".validation-action-grid-v065")

        set_width(page, 700)
        assert len(columns(page, ".validation-pipeline-v065")) == 1, columns(page, ".validation-pipeline-v065")
        assert len(columns(page, ".validation-action-grid-v065")) == 1, columns(page, ".validation-action-grid-v065")
        direction = page.eval_on_selector(".draft-conflict-banner-v065", "el => getComputedStyle(el).flexDirection")
        assert direction == "column", direction

        root_overflow = page.eval_on_selector("#workspaceCanvas", "el => ({client:el.clientWidth,scroll:el.scrollWidth})")
        assert root_overflow["scroll"] <= root_overflow["client"] + 1, root_overflow

        browser.close()

    print("V0.65 interaction/layout contract: PASS")


if __name__ == "__main__":
    main()
