from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
CSS = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("styles.css", "analysis-v067.css"))
EXECUTION = (STATIC / "analysis" / "execution.js").read_text(encoding="utf-8")

PLAN = {
    "analysis_definition_id": "ANL-LAYOUT",
    "analysis_name": "多工况电磁分析",
    "project_id": "PRJ-LAYOUT",
    "module": "EMag",
    "recipe_id": "emag",
    "recipe": {"label": "电磁", "sections": [{"label": "工况", "fields": [
        {"key": "shaft_speed_rpm", "target": "load_case", "label": "转速", "unit": "rpm"},
        {"key": "peak_current_a", "target": "load_case", "label": "峰值电流", "unit": "A"},
        {"key": "dc_bus_voltage_v", "target": "load_case", "label": "母线电压", "unit": "V"},
        {"key": "phase_advance_deg", "target": "load_case", "label": "超前角", "unit": "deg"},
    ]}]},
    "design": {"name": "IPM 工程电机", "motor_type_id": "IPM"},
    "design_revision": {"id": "DREV-L", "revision": 8, "content_hash": "d" * 64},
    "analysis_revision": {"id": "AREV-L", "revision": 5, "content_hash": "a" * 64},
    "load_cases": [
        {"shaft_speed_rpm": speed, "peak_current_a": 35, "dc_bus_voltage_v": 400, "phase_advance_deg": angle}
        for speed, angle in ((1000, 0), (3000, 5), (6000, 15), (9000, 25))
    ],
    "case_count": 4,
    "input_domains": {"materials": {"magnet_material": "N42UH"}, "losses": {"method": "bertotti"}},
    "required_input_domains": ["materials", "losses"],
    "missing_required_input_domains": [],
    "solver_settings": {"mesh_quality": "standard"},
    "requested_outputs": ["shaft_torque_nm", "efficiency_percent", "copper_loss_w", "iron_loss_w", "magnet_loss_w"],
    "studio_precheck": {"valid": True, "blocking": 0, "warnings": 1, "issues": []},
    "task_validation": {"valid": True, "blocking": 0, "warnings": 1, "issues": []},
    "runtime_readiness": {"ok": True, "checks": []},
    "recent_tasks": [{"id": "TASK-1", "name": "基准计算", "status": "COMPLETED", "usable_cases": 4, "case_count": 4}],
    "can_submit": True,
}


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        for width, height in ((1280, 900), (920, 900), (680, 900)):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors: list[str] = []
            page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
            page.set_content(f"<style>{CSS}</style><body><div id='toastStack'></div></body>")
            page.add_script_tag(content=f"""
              window.state={{activeProjectId:'PRJ-LAYOUT'}};
              window.esc=v=>String(v??''); window.toast=()=>{{}}; window.showTab=()=>{{}};
              window.MCSV060={{state:{{checks:new Map()}},fetchCases:async()=>{{}}}};
              window.MCSRouter={{navigate:()=>{{}}}};
              const plan={json.dumps(PLAN, ensure_ascii=False)};
              window.api=async url=>url.endsWith('/execution-plan')?structuredClone(plan):[];
            """)
            page.add_script_tag(content=EXECUTION)
            page.evaluate("() => window.MCSAnalysisExecution.open('ANL-LAYOUT')")
            page.wait_for_selector(".analysis-execution-dialog-v067")
            metrics = page.evaluate("""() => ({
              rootClient: document.documentElement.clientWidth,
              rootScroll: document.documentElement.scrollWidth,
              dialogClient: document.querySelector('.analysis-execution-dialog-v067').clientWidth,
              dialogScroll: document.querySelector('.analysis-execution-dialog-v067').scrollWidth,
              tableOverflow: getComputedStyle(document.querySelector('.analysis-table-scroll-v067')).overflowX,
              railDisplay: getComputedStyle(document.querySelector('.analysis-step-rail-v067')).display,
            })""")
            assert metrics["rootScroll"] <= metrics["rootClient"] + 1, (width, metrics)
            assert metrics["dialogScroll"] <= metrics["dialogClient"] + 1, (width, metrics)
            assert metrics["tableOverflow"] in {"auto", "scroll"}, (width, metrics)
            assert not errors, (width, errors)
            page.close()
        browser.close()
    print("V0.67 analysis layout contract: PASS")


if __name__ == "__main__":
    main()
