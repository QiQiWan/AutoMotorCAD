from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"

# Load the stable Design boundary in the same relative order as index.html. This
# catches missing globals/module initialization errors without needing network
# access from Chromium, which is intentionally blocked in the release container.
MODULES = [
    "frontend-core.js",
    "app-core-v062.js",
    "design/store.js",
    "design/navigation.js",
    "design/draft-service.js",
    "design/precheck.js",
    "design/render-utils.js",
    "design/geometry.js",
    "design/winding.js",
    "design/materials.js",
    "design/validation.js",
    "design/parameter-inspector.js",
    "design/renderer.js",
    "materials/library.js",
    "design/editor.js",
    "design/viewer.js",
    "design/workbench.js",
]


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_content("<body><div id='toastStack'></div><main id='workspaceCanvas'></main></body>")
        page.add_script_tag(content="""
          window.state = {};
          window.api = async () => ({});
          window.toast = () => {};
          window.esc = value => String(value ?? '');
          window.showTab = () => {};
        """)
        for relative in MODULES:
            page.add_script_tag(content=(STATIC / relative).read_text(encoding="utf-8"))
        page.wait_for_timeout(100)
        globals_state = page.evaluate("""() => ({
            decorate: typeof window.decorateDesignViewer,
            viewer: typeof window.MCSDesignViewer,
            editor: typeof window.MCSDesignEditor,
            materials: typeof window.MCSMaterialLibrary,
            renderer: typeof window.MCSDesignRenderer,
            store: typeof window.MCSDesignStore
        })""")
        assert globals_state == {
            "decorate": "function",
            "viewer": "object",
            "editor": "object",
            "materials": "object",
            "renderer": "object",
            "store": "object",
        }, globals_state
        page.evaluate("() => window.decorateDesignViewer()")
        page.wait_for_timeout(50)
        assert not errors, errors
        browser.close()
    print("V0.66 shell runtime contract: PASS")


if __name__ == "__main__":
    main()
