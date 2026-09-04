from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from motorcad_studio.tools.build_frontend_capsule import build
from motorcad_studio.release import PRODUCT_VERSION


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
LEGACY = ROOT / "motorcad_studio" / "frontend_legacy"


def test_frontend_has_one_module_entry_and_one_stylesheet():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', index)
    styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', index)
    assert scripts == [("core/bootstrap.js", PRODUCT_VERSION)]
    assert styles == [("app.css", PRODUCT_VERSION)]
    assert not (STATIC / "core" / "runtime-scripts.js").exists()


def test_classic_runtime_capsule_is_complete_unique_and_reproducible():
    report = build(check=True)
    assert report["compatible"] is True
    assert report["source_count"] == 89

    catalog = json.loads((STATIC / "core" / "classic-runtime.catalog.json").read_text(encoding="utf-8"))
    rows = catalog["sources"]
    assert catalog["source_count"] == len(rows) == 89
    assert rows[0]["runtime_path"] == "/static/release-manifest.js"
    assert rows[-1]["runtime_path"] == "/static/module-registry.js"
    assert len({row["runtime_path"] for row in rows}) == 89
    assert len({row["source_path"] for row in rows}) == 89

    for row in rows:
        path = ROOT / "motorcad_studio" / row["source_path"]
        assert path.is_file()
        raw = path.read_bytes()
        assert len(raw) == row["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert not (STATIC / row["runtime_path"].removeprefix("/static/")).exists()


def test_modern_static_modules_do_not_export_mutable_window_globals():
    assignment = re.compile(r"(?<![\w$])(?:window|globalThis)\.([A-Za-z_$][\w$]*)\s*=(?!=)")
    violations: list[str] = []
    for path in STATIC.rglob("*.js"):
        if path.name == "classic-runtime-source.js":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), 1):
            if assignment.search(line):
                violations.append(f"{path.relative_to(STATIC)}:{line_number}")
    assert violations == []

    bootstrap = (STATIC / "core" / "bootstrap.js").read_text(encoding="utf-8")
    assert "Object.defineProperty(window, 'MotorCADStudio'" in bootstrap
    assert "writable: false" in bootstrap
    assert "configurable: false" in bootstrap


def test_runtime_scope_deduplicates_resources_and_disposes_features():
    script = r"""
import {DisposableScope} from './motorcad_studio/static/core/disposable-scope.js';
import {FeatureRegistry} from './motorcad_studio/static/core/feature-registry.js';

const target = new EventTarget();
const scope = new DisposableScope('test');
let events = 0;
const listener = () => { events += 1; };
scope.listen(target, 'ping', listener);
target.dispatchEvent(new Event('ping'));
scope.dispose();
target.dispatchEvent(new Event('ping'));

let active = true;
let mounts = 0;
let unmounts = 0;
const registry = new FeatureRegistry();
registry.register({
  id: 'feature',
  match: () => active,
  mount: ({scope: featureScope}) => {
    mounts += 1;
    featureScope.defer(() => { unmounts += 1; });
  },
});
await registry.sync({reason: 'first'});
await registry.sync({reason: 'same-state'});
active = false;
await registry.sync({reason: 'leave'});
registry.dispose();
process.stdout.write(JSON.stringify({events, mounts, unmounts, snapshot: registry.snapshot()}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["events"] == 1
    assert payload["mounts"] == 1
    assert payload["unmounts"] == 1
    assert payload["snapshot"]["disposed"] is True
    assert payload["snapshot"]["active"] == []


def test_legacy_runtime_tracks_and_disposes_all_resource_classes():
    source = (STATIC / "core" / "legacy-runtime.js").read_text(encoding="utf-8")
    for token in (
        "this.events",
        "registeredListeners",
        "clearedListeners",
        "removeEventListener",
        "clearTimeout",
        "clearInterval",
        "cancelAnimationFrame",
        "requestIdleCallback",
        "cancelIdleCallback",
        "idleCallbacks",
        ".abort(",
        ".terminate()",
        ".disconnect()",
        "compatibilityGlobalCount",
        "verifyHash",
        "lastFailure",
    ):
        assert token in source


def test_legacy_runtime_binds_idle_callbacks_instead_of_calling_window_method_through_proxy():
    source = (STATIC / "core" / "legacy-runtime.js").read_text(encoding="utf-8")
    assert "nativeRequestIdleCallback.call(this.host" in source
    assert "nativeCancelIdleCallback.call(this.host" in source
    assert "if (property === 'requestIdleCallback')" in source
    assert "if (property === 'cancelIdleCallback')" in source


def test_frontend_module_registry_accepts_declared_cross_surface_dependencies():
    generator = (ROOT / "motorcad_studio" / "tools" / "sync_release_versions.py").read_text(encoding="utf-8")
    registry = (LEGACY / "module-registry.js").read_text(encoding="utf-8")
    for text in (generator, registry):
        assert "const contractIds = new Set(Object.keys(contracts));" in text
        assert "!moduleIds.has(dependency) && !contractIds.has(dependency)" in text


def test_all_served_and_capsule_sources_are_javascript_syntax_valid():
    files = sorted({*STATIC.rglob("*.js"), *LEGACY.rglob("*.js")})
    issues: list[str] = []
    for path in files:
        completed = subprocess.run(
            ["node", "--check", str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode:
            issues.append(f"{path.relative_to(ROOT)}: {completed.stderr.strip()}")
    assert issues == []


def test_control_plane_client_uses_canonical_v2_endpoints_and_updates_stores():
    script = r"""
import {ControlPlaneClient} from './motorcad_studio/static/features/control-plane/client.js';
import {Store} from './motorcad_studio/static/core/store.js';
const calls = [];
const api = {
  async get(path, options = {}) { calls.push({method:'GET', path, options}); return {authority:'ControlPlaneRuntimeV1'}; },
  async post(path, json, options = {}) {
    calls.push({method:'POST', path, json, options});
    if (path.endsWith('/campaigns')) return {campaign:{campaign_id:'CMP-1', version:1}, _command:{command_id:'CMD-1', replayed:false}};
    if (path.includes('/candidates')) return {candidate:{candidate_id:'CAN-1', version:2}, _command:{command_id:'CMD-2', replayed:false}};
    if (path.includes('/leases/')) return {lease:{lease_id:'L-1', fencing_token:3}, _command:{command_id:'CMD-3', replayed:false}};
    return {_command:{command_id:'CMD-X', replayed:false}};
  },
};
const stores = {
  optimization:new Store({campaignId:null,candidateId:null,version:0}),
  qualification:new Store({campaignId:null,decision:null,evidenceCount:0}),
  nativeRuntime:new Store({leaseId:null,fencingToken:null,state:'idle'}),
  requirements:new Store({setId:null,revisionId:null,version:0}),
};
const client = new ControlPlaneClient({api, stores});
await client.runtime();
await client.optimization.createCampaign({name:'campaign'}, {idempotencyKey:'KEY-1'});
await client.optimization.createCandidate('CMP-1', {parameters:{x:1}}, {idempotencyKey:'KEY-2'});
await client.nativeRuntime.acquire('motorcad:1', {owner_id:'worker'}, {idempotencyKey:'KEY-3'});
process.stdout.write(JSON.stringify({calls, optimization:stores.optimization.value, nativeRuntime:stores.nativeRuntime.value, snapshot:client.snapshot()}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    paths = [row["path"] for row in payload["calls"]]
    assert paths == [
        "/api/control-plane/runtime",
        "/api/optimization/v2/campaigns",
        "/api/optimization/v2/campaigns/CMP-1/candidates",
        "/api/native-runtime/v2/leases/motorcad%3A1",
    ]
    assert payload["calls"][1]["options"]["idempotencyKey"] == "KEY-1"
    assert payload["optimization"] == {"campaignId": "CMP-1", "candidateId": "CAN-1", "version": 2}
    assert payload["nativeRuntime"]["leaseId"] == "L-1"
    assert payload["nativeRuntime"]["fencingToken"] == 3
    assert payload["snapshot"]["connected"] is True


def test_control_plane_feature_is_part_of_single_bootstrap_composition():
    bootstrap = (STATIC / "core" / "bootstrap.js").read_text(encoding="utf-8")
    client = (STATIC / "features" / "control-plane" / "client.js").read_text(encoding="utf-8")
    feature = (STATIC / "features" / "control-plane" / "feature.js").read_text(encoding="utf-8")
    assert "installControlPlaneFeature" in bootstrap
    assert "namespace.runtime.controlPlane" in bootstrap
    for token in (
        "/api/optimization/v2/",
        "/api/data-factory/v2/",
        "/api/qualification/v2/",
        "/api/native-runtime/v2/",
        "/api/requirements/v2/",
    ):
        assert token in client
    assert "Idempotency-Key" not in feature
    assert "abortController" in feature
    assert "control-plane:refresh-requested" in feature


def test_classic_runtime_routes_shared_api_calls_through_modern_api_client():
    app_source = (LEGACY / "app.js").read_text(encoding="utf-8")
    assert "window.MotorCADStudio?.api" in app_source
    assert "client.request(url" in app_source
    first_api_line = next(line for line in app_source.splitlines() if line.startswith("const api=async"))
    assert "await fetch(" not in first_api_line
    assert "window.api=api" in first_api_line


def test_api_client_retries_idempotent_commands_with_one_stable_key():
    script = r"""
import {ApiClient} from './motorcad_studio/static/core/api-client.js';
const calls=[];
let attempt=0;
globalThis.fetch=async (_url, init)=>{
  attempt += 1;
  calls.push({attempt, key:init.headers.get('Idempotency-Key'), correlation:init.headers.get('X-Correlation-ID')});
  if(attempt===1) return new Response(JSON.stringify({detail:{message:'temporary'}}), {status:503, headers:{'Content-Type':'application/json'}});
  return new Response(JSON.stringify({ok:true}), {status:200, headers:{'Content-Type':'application/json'}});
};
const client=new ApiClient({timeoutMs:5000});
const result=await client.post('/api/command',{x:1},{retries:1,idempotencyKey:'COMMAND-KEY'});
process.stdout.write(JSON.stringify({result,calls}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["result"] == {"ok": True}
    assert len(payload["calls"]) == 2
    assert {row["key"] for row in payload["calls"]} == {"COMMAND-KEY"}
    assert len({row["correlation"] for row in payload["calls"]}) == 1


def test_solution_creator_and_primary_navigation_are_route_owned():
    canonical = (LEGACY / "canonical-project-flow.js").read_text(encoding="utf-8")
    router = (LEGACY / "router.js").read_text(encoding="utf-8")
    bootstrap = (STATIC / "core" / "bootstrap.js").read_text(encoding="utf-8")
    bridge = (STATIC / "core" / "navigation-bridge.js").read_text(encoding="utf-8")

    assert "data-canonical-create-solution" in canonical
    assert "designs/templates" in canonical
    assert "MCSRouter?.navigate" in canonical
    assert "window.showTab=showTab" in router
    assert "installNavigationBridge" in bootstrap
    assert "core:navigation-bridge" in bridge
    assert "stopImmediatePropagation" in bridge


def test_hard_refresh_route_hydrates_project_from_backend_before_mounting_page():
    router = (LEGACY / "router.js").read_text(encoding="utf-8")
    assert "async function hydrateProjectRoute" in router
    assert "`/api/projects/${clean(projectId)}`" in router
    assert "await hydrateProjectRoute(route,ctx)" in router
    assert "syncProjectContextSelectors" in router
    assert "updateProjectNavState" in router
    assert "workspaceProjects.some" not in router


def test_startup_runtime_preflight_does_not_block_durable_route_start():
    source = (LEGACY / "app.js").read_text(encoding="utf-8")
    route_start = source.index("const routeStart=")
    route_wait = source.index("await routeStart", route_start)
    preflight = source.index("loadStartupSetup(true)", route_wait)
    assert route_start < route_wait < preflight
    assert "FRONTEND_BACKGROUND_STARTUP_FAILED" in source


def test_classic_cross_module_helpers_are_explicitly_exported_to_capsule_proxy():
    source = (LEGACY / "app.js").read_text(encoding="utf-8")
    block_start = source.index("Object.assign(window, {")
    block = source[block_start:block_start + 400]
    for name in (
        "state",
        "esc",
        "toast",
        "changeActiveProject",
        "loadViewerCases",
        "renderMonitorSnapshot",
        "renderSystemSnapshot",
        "renderLiveEvents",
    ):
        assert re.search(rf"\b{re.escape(name)}\s*,", block), name


def test_fixed_buttons_have_declared_action_identity_or_source_binding_evidence():
    from html.parser import HTMLParser

    class ButtonParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons: list[dict[str, str]] = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "button":
                self.buttons.append({str(key): str(value or "") for key, value in attrs})

    parser = ButtonParser()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    corpus = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [*LEGACY.rglob("*.js"), *STATIC.rglob("*.js")]
        if path.name != "classic-runtime-source.js"
    )
    action_attributes = {
        "data-tab", "data-go", "data-engineer-stage", "data-analysis-step-v076",
        "data-fea-mode-v022", "data-event-filter", "data-viewer-mode",
        "data-workflow-action-route", "data-project-enter", "data-project-edit",
        "data-project-restore", "data-canonical-create-solution", "data-canonical-motor",
        "data-canonical-analysis", "data-workspace-design", "data-workspace-revision",
        "data-template-id", "data-template-use", "data-template-detail", "data-template-compare",
        "data-use-template", "data-open-task-v076", "data-open-viewer-case",
        "data-viewer-scalar", "data-fix-first-v081a", "data-svp-run",
        "data-native-preview-source", "data-field-view-mode", "data-result-mode",
        "data-candidate-action", "data-workflow-action-endpoint",
    }
    missing: list[str] = []
    for row in parser.buttons:
        if row.get("disabled") or row.get("aria-disabled") == "true":
            continue
        if row.get("onclick") or any(attr in row for attr in action_attributes):
            continue
        identifier = row.get("id", "")
        if identifier and identifier in corpus:
            continue
        if row.get("type") == "submit":
            continue
        missing.append(identifier or repr(row))
    assert parser.buttons, "index.html must contain fixed controls"
    assert missing == []


def test_silent_button_noop_monitor_is_installed_and_reports_to_root_frontend_log():
    bootstrap = (STATIC / "core" / "bootstrap.js").read_text(encoding="utf-8")
    monitor = (STATIC / "core" / "interaction-monitor.js").read_text(encoding="utf-8")
    assert "installInteractionMonitor" in bootstrap
    assert "FRONTEND_BUTTON_NO_EFFECT" in monitor
    assert "FRONTEND_BUTTON_BINDING_GAP" in monitor
    assert "MCSHMIQualification" in monitor
    assert "MCSPageRuntime?.report" in monitor
