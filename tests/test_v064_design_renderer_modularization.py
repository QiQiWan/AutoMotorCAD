from pathlib import Path

from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"

def source(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")

def test_v064_release_physically_loads_stable_design_renderer_modules():
    index = source("index.html")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/design-v065.css?v=0.70.0' in index
    modules = ["render-utils", "geometry", "winding", "materials", "validation", "parameter-inspector", "renderer"]
    for name in modules:
        assert f'/static/design/{name}.js?v=0.70.0' in index
    assert index.index("design/renderer.js") < index.index("design/editor.js")
    assert index.index("materials/library.js") < index.index("design/viewer.js") < index.index("design/workbench.js") < index.index("router.js")

def test_v031_compatibility_functionality_is_split_into_stable_workflow_and_result_modules():
    workflow = source("workflow/flow-rail.js")
    results = source("results/fea-thermal.js")
    index = source("index.html")
    assert "/static/v031.js" not in index
    assert "upgradeFlowBar" in workflow and "window.MCSWorkflowRail" in workflow
    assert "enhanceFEAViewer" in results and "enhanceThermalViewer" in results
    assert "window.MCSResultVisuals" in results
    for token in ("function decorateDesignViewer", "function applyRouteView", "MCSVisualV031"):
        assert token not in workflow + results

def test_stable_renderer_modules_have_single_responsibility_facade():
    assert "window.MCSDesignGeometry" in source("design/geometry.js")
    assert "window.MCSDesignWinding" in source("design/winding.js")
    assert "window.MCSDesignMaterials" in source("design/materials.js")
    assert "window.MCSDesignValidation" in source("design/validation.js")
    assert "window.MCSDesignParameterInspector" in source("design/parameter-inspector.js")
    facade = source("design/renderer.js")
    for token in ("MCSDesignGeometry", "MCSDesignWinding", "MCSDesignMaterials", "MCSDesignValidation", "MCSDesignParameterInspector"):
        assert token in facade

def test_read_only_design_viewer_aborts_stale_workbench_requests_and_restores_route_view():
    viewer = source("design/viewer.js")
    assert "abortController" in viewer and "new AbortController()" in viewer
    assert "controller.signal.aborted" in viewer
    assert "token!==visualState.requestToken" in viewer
    assert "state.workspaceRevision?.id!==revisionId" in viewer
    assert "const requested=" in viewer and "const routed=" in viewer and "const preserved=" in viewer
    assert "MCSDesignStore?.currentView" in viewer
    assert "setTimeout" not in viewer
    assert "MCSRouter.navigate" in viewer and "/results/tasks/" in viewer

def test_design_draft_autosave_is_serialized_and_explicit_delete_uses_same_queue():
    editor = source("design/editor.js")
    service = source("design/draft-service.js")
    assert "savePromise" in service and "pending" in service
    assert "async function drain" in service
    assert "while (service.pending)" in service
    assert "payloadVersion" in service and "persistedVersion" in service and "session" in service
    assert "queueDelete" in service and "expected_version" in service
    assert "MCSDesignRenderer?.renderWorkbenchView" in editor
    assert "MCSDesignParameterInspector?.editorParameterRows" in editor
    assert "function geometryHtml" not in editor and "function windingHtml" not in editor

def test_design_layout_uses_component_width_contracts_instead_of_viewport_only():
    css = source("design-v065.css")
    assert "container-name:design-workspace" in css
    assert "container-name:design-viewer" in css
    assert "clamp(280px,25cqw,360px)" in css
    assert "@container design-viewer (max-width:980px)" in css
    assert "@container design-viewer (max-width:680px)" in css
    assert "@container design-workspace (max-width:1320px)" in css
    assert "@container design-workspace (max-width:860px)" in css
    assert "@container design-workspace (min-width:1321px)" in css
    assert "min-width:620px" in css and "overflow:auto" in css

def test_router_uses_stable_design_viewer_and_editor_without_v031_fallback():
    router = source("router.js")
    v046 = source("workflow/engineering-contexts.js")
    workbench = source("design/workbench.js")
    assert "MCSDesignViewer?.state?.view" in router
    assert "MCSDesignViewer?.applyRouteView" in router
    assert "MCSDesignEditor?.applyRouteView" in router
    assert "MCSVisualV031" not in router
    assert "MCSVisualV031" not in v046
    assert "MCSDesignViewer?.state?.view" in workbench
