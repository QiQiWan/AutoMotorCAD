from pathlib import Path

from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def source(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def test_v063_release_loads_design_modules_before_legacy_compatibility_layers():
    index = source("index.html")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/design-v065.css?v=0.70.0' in index
    assert '/static/design/store.js?v=0.70.0' in index
    assert '/static/design/navigation.js?v=0.70.0' in index
    assert '/static/design/workbench.js?v=0.70.0' in index
    assert index.index("design/store.js") < index.index("design/editor.js")
    assert index.index("design/navigation.js") < index.index("design/renderer.js") < index.index("design/editor.js")
    assert index.index("materials/library.js") < index.index("design/viewer.js") < index.index("design/workbench.js") < index.index("router.js")


def test_design_viewer_and_editor_share_one_store_and_navigation_contract():
    store = source("design/store.js")
    navigation = source("design/navigation.js")
    viewer = source("design/viewer.js")
    editor = source("design/editor.js")
    router = source("router.js")

    assert "window.MCSDesignStore" in store
    assert "setContext" in store and "setView" in store and "subscribe" in store
    assert "identityChanged" in store and "identityChanged ? null : state.data" in store
    assert "window.MCSDesignNavigation" in navigation
    assert "rowsForStage" in navigation and "defaultViewForStage" in navigation and "function next" in navigation
    assert "MCSDesignNavigation.render" in viewer
    assert "MCSDesignNavigation.render" in editor
    assert "MCSDesignStore?.setContext" in viewer
    assert "MCSDesignStore?.setContext" in editor
    assert "MCSDesignStore?.currentView" in router
    assert "data-workbench-next-v063" in editor
    assert "const routed=available.has(window.MCSDesignStore?.currentView?.())" in viewer


def test_route_context_guards_are_type_safe_and_no_longer_call_unknown_active_member():
    runtime = source("frontend-core.js")
    assert "function isContextActive(context)" in runtime
    assert "typeof context.active !== 'function'" in runtime
    assert "isContextActive" in runtime.split("window.MCSPageRuntime", 1)[1]
    for path in STATIC.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert "routeCtx&&!routeCtx.active()" not in text, path.name


def test_v063_editor_layout_prioritizes_visual_canvas_and_inline_parameter_inspector():
    css = source("design-v065.css")
    assert 'grid-template-areas:"tree visual editor" "diag diag diag"' in css
    assert ".workbench-main-v024{display:contents}" in css
    assert ".workbench-parameter-editor-v024{grid-area:editor;position:sticky" in css
    assert "@container design-workspace (max-width:1320px)" in css
    assert "@container design-workspace (max-width:860px)" in css
    assert ".revision-rail-v063{display:none}" in css


def test_read_only_header_exposes_one_primary_edit_action_and_secondary_revision_history():
    controller = source("design/workbench.js")
    viewer = source("design/viewer.js")
    inspector = source("design/parameter-inspector.js")
    assert "workspaceRevisionHistoryV063" in controller
    assert "revision-rail-open-v063" in controller
    assert "workspaceCreateRevision" in controller
    assert "workspaceEditRevision" in controller
    assert "design-object-meta-v063" in controller
    assert ">编辑设计</button>" in inspector


def test_v063_does_not_reintroduce_global_dom_observers():
    observers = 0
    for path in STATIC.rglob("*.js"):
        observers += path.read_text(encoding="utf-8").count("new MutationObserver")
    assert observers == 1
