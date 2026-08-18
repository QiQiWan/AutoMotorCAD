from __future__ import annotations

import json
from pathlib import Path

from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"

def read(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")

def main() -> None:
    assert tuple(map(int, __version__.split("."))) >= (0, 64, 0)
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    index = read("index.html")
    viewer = read("design/viewer.js")
    editor = read("design/editor.js")
    draft_service = read("design/draft-service.js")
    workflow = read("workflow/flow-rail.js")
    results = read("results/fea-thermal.js")
    router = read("router.js")
    css = read("design-v065.css")

    renderer_modules = ["render-utils", "geometry", "winding", "materials", "validation", "parameter-inspector", "renderer"]
    assert f'data-studio-version="{__version__}"' in index
    assert f'/static/design-v065.css?v={__version__}' in index
    for name in renderer_modules:
        assert f'/static/design/{name}.js?v={__version__}' in index
    assert index.index("design/renderer.js") < index.index("design/editor.js")
    assert index.index("materials/library.js") < index.index("design/viewer.js") < index.index("design/workbench.js") < index.index("router.js")

    assert "/static/v031.js" not in index and "/static/v024.js" not in index
    assert "upgradeFlowBar" in workflow and "MCSWorkflowRail" in workflow
    assert "enhanceFEAViewer" in results and "enhanceThermalViewer" in results
    assert "abortController" in viewer and "new AbortController()" in viewer and "setTimeout" not in viewer
    assert "token!==visualState.requestToken" in viewer and "state.workspaceRevision?.id!==revisionId" in viewer
    assert "MCSRouter.navigate" in viewer and "/results/tasks/" in viewer
    assert "while (service.pending)" in draft_service and "expected_version" in draft_service and "queueDelete" in draft_service
    assert "MCSDesignRenderer?.renderWorkbenchView" in editor
    assert "function geometryHtml" not in editor and "function windingHtml" not in editor
    assert "MCSDesignViewer?.state?.view" in router and "MCSDesignViewer?.applyRouteView" in router
    assert "container-name:design-workspace" in css and "container-name:design-viewer" in css
    assert "@container design-viewer (max-width:980px)" in css and "@container design-workspace (max-width:1320px)" in css

    observers = sum(path.read_text(encoding="utf-8").count("new MutationObserver") for path in STATIC.rglob("*.js"))
    assert observers == 1
    unsafe = [str(path.relative_to(STATIC)) for path in STATIC.rglob("*.js") if "routeCtx&&!routeCtx.active()" in path.read_text(encoding="utf-8")]
    assert not unsafe, unsafe
    print(f"V0.64+ Design renderer modularization contract verification passed on {__version__}")

if __name__ == "__main__":
    main()
