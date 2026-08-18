from __future__ import annotations

import json
from pathlib import Path

from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def read(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def main() -> None:
    assert tuple(map(int,__version__.split("."))) >= (0,63,0)
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    index = read("index.html")
    store = read("design/store.js")
    navigation = read("design/navigation.js")
    controller = read("design/workbench.js")
    editor = read("design/editor.js")
    viewer = read("design/viewer.js")
    router = read("router.js")
    runtime = read("frontend-core.js")
    css = read("design-v065.css")

    assert f'data-studio-version="{__version__}"' in index
    assert index.index("design/store.js") < index.index("design/editor.js")
    assert index.index("design/navigation.js") < index.index("design/renderer.js") < index.index("design/editor.js")
    assert index.index("design/workbench.js") < index.index("router.js")
    assert "window.MCSDesignStore" in store
    assert "window.MCSDesignNavigation" in navigation
    assert "workspaceRevisionHistoryV063" in controller
    assert "MCSDesignNavigation.render" in editor and "MCSDesignNavigation.render" in viewer
    assert "MCSDesignStore?.currentView" in router
    assert "function isContextActive(context)" in runtime
    assert 'grid-template-areas:"tree visual editor" "diag diag diag"' in css
    observers = sum(path.read_text(encoding="utf-8").count("new MutationObserver") for path in STATIC.rglob("*.js"))
    assert observers == 1
    route_unsafe = [path.name for path in STATIC.rglob("*.js") if "routeCtx&&!routeCtx.active()" in path.read_text(encoding="utf-8")]
    assert not route_unsafe, route_unsafe
    print(f"V0.63+ design workbench convergence contract verification passed on {__version__}")


if __name__ == "__main__":
    main()
