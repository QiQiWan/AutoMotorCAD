from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "motorcad_studio" / "static" / "native-parity-v068.css").read_text(encoding="utf-8")

HTML = """
<!doctype html><html><head><meta charset='utf-8'><style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:#f2f4f7;color:#101828}.panel{width:100%;max-width:1500px;margin:0 auto;padding:16px;background:#fff}.section-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.actions{display:flex;gap:8px;flex-wrap:wrap}button{min-height:34px;padding:0 12px}.table-wrap{max-width:100%;overflow:auto}table{width:100%;min-width:760px;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}
__CSS__
</style></head><body><article class='panel' id='nativeParityPanelV068'>
<div class='section-head'><div><span>V0.68</span><h2>Motor-CAD 原生一致性资格中心</h2><p>目标 Windows + Motor-CAD 2026R1 工作站。</p></div><div class='actions'><button>刷新</button><button>运行四模型原生资格套件</button></div></div>
<div class='native-parity-overview-v068'><div class='native-parity-score-v068'><span>Native workstation qualification</span><strong>50.0%</strong><span>真实证据。</span></div><div><h3>资格判定</h3><p>已通过 2/4 个 Profile。</p></div></div>
<div class='native-parity-profiles-v068'>
__CARDS__
</div>
<div class='table-wrap native-parity-table-v068'><table><thead><tr><th>Profile</th><th>模板</th><th>状态</th><th>得分</th><th>证据</th><th>阻断项</th></tr></thead><tbody><tr><td>SPM</td><td>i5_Industrial_SPM_Servo_Tooth_Wound</td><td>PASS</td><td>100%</td><td>NPR-123</td><td>—</td></tr></tbody></table></div>
</article></body></html>
"""
CARD = """<article class='native-parity-profile-v068'><div class='native-parity-profile-head-v068'><div><span>BPM</span><h3>{name}</h3><p>较长的原生一致性资格说明，用于验证窄屏自动换行与卡片收缩。</p></div><span class='native-parity-state-v068 pass'>已通过</span></div><div class='native-parity-profile-meta-v068'><span>模板 <b>{template}</b></span><span>目标 <b>2026R1</b></span><span>得分 <b>100%</b></span></div><div class='actions'><button>运行原生逐项对照</button><button>查看证据</button></div></article>"""


def main() -> None:
    cards = "".join(CARD.format(name=name, template=template) for name, template in [
        ("BPM 基准族", "a1"),
        ("SPM 工业伺服", "i5_Industrial_SPM_Servo_Tooth_Wound"),
        ("IPM eMobility", "e9_eMobility_IPM"),
        ("AFPM e14 YASA", "e14_eMobility_AFM"),
    ])
    html = HTML.replace("__CSS__", CSS).replace("__CARDS__", cards)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.set_content(html)
        for width in (1500, 1000, 720):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_timeout(30)
            root_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            assert not root_overflow, width
            columns = page.eval_on_selector(".native-parity-profiles-v068", "el => getComputedStyle(el).gridTemplateColumns")
            if width <= 900:
                assert " " not in columns.strip(), (width, columns)
            else:
                assert " " in columns.strip(), (width, columns)
        browser.close()
    print("V0.68 native parity responsive layout: PASS")


if __name__ == "__main__":
    main()
