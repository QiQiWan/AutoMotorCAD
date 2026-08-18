from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
CSS = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("styles.css", "design-v065.css", "design-v066.css"))

STAGES = "".join(
    f'<button><span>{i}</span><b>{label}</b><small>{desc}</small></button>'
    for i, (label, desc) in enumerate((("几何", "截面与装配"), ("绕组", "连接与槽内"), ("材料", "部件绑定"), ("设计验证", "模型检查")), 1)
)
RECORDS = "".join(f'<button class="material-record-v061"><span><b>Material {i:03d}</b><small>Steel · 固体</small></span><em>Motor-CAD</em></button>' for i in range(120))

HTML = f"""
<body>
  <div id="workspaceCanvas" style="container-type:inline-size;container-name:design-workspace;width:1200px">
    <section class="design-viewer-v031" style="width:100%">
      <div class="design-stage-nav-v062"><div class="design-stage-main-v062">{STAGES}</div><button class="design-compare-utility-v062"><b>版本比较</b><small>辅助工具</small></button></div>
      <div class="design-readiness-v066"><div class="design-readiness-grid-v066">
        <article class="pass"><span>01</span><div><b>几何参数</b><small>19 项结构化参数</small></div><strong>已就绪</strong></article>
        <article class="pass"><span>02</span><div><b>绕组定义</b><small>3 相 · 150 匝</small></div><strong>已就绪</strong></article>
        <article class="pass"><span>03</span><div><b>部件材料</b><small>5 个部件</small></div><strong>已配置</strong></article>
        <article class="pending"><span>04</span><div><b>Motor-CAD 原生证据</b><small>待运行</small></div><strong>待运行</strong></article>
      </div></div>
    </section>
  </div>
  <div id="materialLibraryV061" class="material-library-shell-v061">
    <section><header><div><span>材料工程数据</span><h2>Motor-CAD 材料库</h2><p>test</p></div><button>×</button></header>
      <div class="material-library-body-v061">
        <div class="material-manager-mode-v066"><b>材料管理模式</b><span>查看材料</span></div>
        <div class="material-library-intro-v061"><div><span>本机数据优先</span><h3>材料事实源</h3><p>intro</p></div></div>
        <section class="material-source-section-v061"><header><div><h3>数据库来源</h3><p>source</p></div><button>扫描</button></header><div class="material-source-grid-v061"><article class="material-source-card-v061"><div><b>solid</b><span>loaded</span></div></article></div></section>
        <section class="material-manager-v061"><aside><header><h3>材料列表</h3></header><div class="material-filter-v061"><input><select></select><select></select></div><div class="material-record-list-v061">{RECORDS}</div><div class="material-export-v061">export</div></aside>
          <main><div class="material-detail-head-v061"><div><span>Motor-CAD</span><h3>M350-50A</h3><p>details</p></div></div><section class="material-key-properties-v066">{''.join('<div><span>属性</span><b>123</b><small>Key</small></div>' for _ in range(8))}</section><section class="material-curve-preview-v061"><article class="material-curve-card-v061"><svg viewBox="0 0 520 190"><polyline points="34,150 200,90 480,30"/></svg></article></section><details class="material-raw-properties-v066"><summary><span><b>完整原始属性</b><small>125字段</small></span></summary></details></main>
        </section>
      </div>
    </section>
  </div>
</body>
"""


def columns(page, selector: str) -> list[str]:
    raw = page.eval_on_selector(selector, "el => getComputedStyle(el).gridTemplateColumns")
    return [part for part in raw.split() if part]


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1700, "height": 1050})
        page.set_content(f"<style>{CSS}</style>{HTML}")

        assert len(columns(page, ".design-stage-nav-v062")) == 2, columns(page, ".design-stage-nav-v062")
        assert len(columns(page, ".design-readiness-grid-v066")) == 4, columns(page, ".design-readiness-grid-v066")
        page.eval_on_selector("#workspaceCanvas", "el => el.style.width='900px'")
        page.wait_for_timeout(50)
        assert len(columns(page, ".design-stage-nav-v062")) == 1, columns(page, ".design-stage-nav-v062")
        assert len(columns(page, ".design-readiness-grid-v066")) == 2, columns(page, ".design-readiness-grid-v066")
        overflow = page.eval_on_selector("#workspaceCanvas", "el => ({client:el.clientWidth,scroll:el.scrollWidth})")
        assert overflow["scroll"] <= overflow["client"] + 1, overflow

        list_box = page.eval_on_selector(".material-record-list-v061", "el => ({client:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY})")
        detail = page.eval_on_selector(".material-manager-v061>main", "el => ({client:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY})")
        assert list_box["scroll"] > list_box["client"] and list_box["overflow"] in {"auto", "scroll"}, list_box
        assert detail["overflow"] in {"auto", "scroll"}, detail
        dialog = page.eval_on_selector(".material-library-shell-v061>section", "el => ({client:el.clientHeight,scroll:el.scrollHeight})")
        assert dialog["scroll"] <= dialog["client"] + 1, dialog

        browser.close()
    print("V0.66 engineering layout contract: PASS")


if __name__ == "__main__":
    main()
