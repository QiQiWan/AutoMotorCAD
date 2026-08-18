from __future__ import annotations

import json
import re
from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def read(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def main() -> None:
    assert tuple(map(int, __version__.split("."))) >= (0, 65, 0)
    assert Database.SCHEMA_VERSION >= 21

    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert manifest["scope_metrics"]["database_schema_version"] >= 21

    index = read("index.html")
    editor = read("design/editor.js")
    draft_service = read("design/draft-service.js")
    precheck = read("design/precheck.js")
    router = read("router.js")
    app = read("app.js")
    operator = read("operator-flow.js")
    validation = read("design/validation.js")
    css = read("design-v065.css")
    main_py = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    workspace_py = (ROOT / "motorcad_studio" / "workspace.py").read_text(encoding="utf-8")
    models_py = (ROOT / "motorcad_studio" / "models.py").read_text(encoding="utf-8")

    required_assets = [
        "design/draft-service.js",
        "design/precheck.js",
        "design/editor.js",
        "workflow/flow-rail.js",
        "results/fea-thermal.js",
    ]
    assert f'data-studio-version="{__version__}"' in index
    assert f'/static/design-v065.css?v={__version__}' in index
    for asset in required_assets:
        assert f'/static/{asset}?v={__version__}' in index, asset

    assert not (STATIC / "v024.js").exists()
    assert not (STATIC / "v031.js").exists()
    assert "/static/v024.js" not in index and "/static/v031.js" not in index

    legacy_scripts = re.findall(rf'<script src="/static/(v\d+\.js)\?v={re.escape(__version__)}"></script>', index)
    assert len(legacy_scripts) <= 21, legacy_scripts

    # Optimistic Draft concurrency: bind version at serialized send time, guard delete and commit.
    assert "const requestPayload = {...request.payload, expected_version: expectedDraftVersion()}" in draft_service
    assert "expectedDeleteVersion" in draft_service
    assert "draft?expected_version=" in draft_service
    assert "DESIGN_DRAFT_STALE" in draft_service
    assert "while (service.pending)" in draft_service
    assert "expected_version: expectedVersion" in editor
    assert "stale_same_revision" in editor
    assert "expected_version: int | None" in models_py
    assert "expected_version: int | None = Query(default=None, ge=0)" in main_py
    assert "with workspace.db.locked():" in main_py
    assert "workspace.delete_design_draft(design_id, expected_version=current_version)" in main_py
    assert "class DesignDraftConflictError" in workspace_py

    # Route leave safety and exact tree/revision navigation.
    assert "async function allowRouteChange" in router
    assert "lastStablePath" in router
    assert "MCSDesignEditor.prepareRouteChange" in router
    assert "navigateWorkspaceDesignV065" in app and "navigateWorkspaceRevisionV065" in app
    assert "MCSWorkspaceNavigationV065" in app and "MCSWorkspaceNavigationV065" in operator
    assert "verification?.dispose?.(); wb.shellAbort?.abort();" in editor

    # Explicit/version-aware validation. Native Motor-CAD requests are cancelable and session scoped.
    assert "nativeAbort" in precheck and "session" in precheck
    assert "new AbortController()" in precheck and "signal" in precheck
    assert "precheckVersion" in precheck and "nativeVersion" in precheck
    assert "runStudio" in precheck and "runNative" in precheck
    assert "draftValidationView" in validation
    assert "validation-pipeline-v065" in css and "validation-action-grid-v065" in css
    assert "@container design-workspace (max-width:760px)" in css

    # Stable ownership: no active JS may use the retired v031/v024 controllers.
    active_js = [p for p in STATIC.rglob("*.js")]
    forbidden = []
    for path in active_js:
        text = path.read_text(encoding="utf-8")
        if "MCSVisualV031" in text or "MCSModelWorkbench" in text or "openRevisionEditorV024" in text:
            forbidden.append(str(path.relative_to(STATIC)))
    assert not forbidden, forbidden

    observers = sum(path.read_text(encoding="utf-8").count("new MutationObserver") for path in active_js)
    assert observers == 1, observers

    print(
        "V0.65 Design editor/concurrency convergence contract: PASS "
        f"({len(legacy_scripts)} active legacy v0xx scripts, {observers} global DOM observer)"
    )


if __name__ == "__main__":
    main()
