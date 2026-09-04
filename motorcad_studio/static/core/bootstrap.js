import {EventBus} from './event-bus.js';
import {ApiClient} from './api-client.js';
import {DisposableScope} from './disposable-scope.js';
import {FeatureRegistry} from './feature-registry.js';
import {Store} from './store.js';
import {Diagnostics} from './diagnostics.js';
import {installLegacyRuntime, CLASSIC_RUNTIME_CATALOG} from './legacy-runtime.js';
import {installBinaryFieldViewer} from '../features/results/binary-field-viewer.js';
import {installControlPlaneFeature} from '../features/control-plane/feature.js';
import {installNavigationBridge} from './navigation-bridge.js';
import {installInteractionMonitor} from './interaction-monitor.js';

const root = document.documentElement;
const documentVersion = String(root.dataset.studioVersion || '');
if (!documentVersion) throw new Error('Document release version is missing');
if (root.dataset.bootstrapState === 'loading' || root.dataset.bootstrapState === 'ready') {
  throw new Error(`Frontend bootstrap already ${root.dataset.bootstrapState}`);
}

const namespace = window.MotorCADStudio && typeof window.MotorCADStudio === 'object'
  ? window.MotorCADStudio
  : {};
const bus = new EventBus();
const diagnostics = new Diagnostics();
const features = new FeatureRegistry({bus});
const appScope = new DisposableScope('application');
const api = new ApiClient({bus});
const stores = Object.freeze({
  engineeringContext: new Store({projectId: null, solutionId: null, revisionId: null}),
  workflow: new Store({stage: 'bootstrap', blockers: [], primaryAction: null}),
  results: new Store({caseId: null, frameIndex: 0, field: null}),
  language: new Store({language: root.lang || 'zh-CN'}),
  optimization: new Store({campaignId: null, candidateId: null, version: 0}),
  qualification: new Store({campaignId: null, decision: null, evidenceCount: 0}),
  nativeRuntime: new Store({leaseId: null, fencingToken: null, state: 'idle'}),
  requirements: new Store({setId: null, revisionId: null, version: 0}),
});

Object.assign(namespace, {
  version: documentVersion,
  bus,
  api,
  stores,
  features,
  diagnostics,
  runtime: {
    state: 'loading',
    loaded: [],
    failed: null,
    runtimeAssetCount: 1,
    sourceCount: CLASSIC_RUNTIME_CATALOG.source_count,
    sourceSha256: CLASSIC_RUNTIME_CATALOG.source_sha256,
  },
  dispose() {
    if (namespace.runtime.state === 'disposed') return;
    features.dispose();
    appScope.dispose();
    namespace.legacyRuntime?.dispose?.();
    namespace.runtime.state = 'disposed';
  },
});
const existingDescriptor = Object.getOwnPropertyDescriptor(window, 'MotorCADStudio');
if (!existingDescriptor) {
  Object.defineProperty(window, 'MotorCADStudio', {
    value: namespace,
    configurable: false,
    enumerable: true,
    writable: false,
  });
} else if (existingDescriptor.value !== namespace) {
  throw new Error('MotorCADStudio namespace is owned by another runtime');
}

root.dataset.bootstrapState = 'loading';
root.dataset.bootstrapLoaded = '0';
root.dataset.bootstrapTotal = '1';
root.dataset.classicSourceCount = String(CLASSIC_RUNTIME_CATALOG.source_count);

// A durable /app/... URL is authoritative from the first paint.  The legacy
// runtime still owns most page renderers, so there is a short hydration window
// before its router can reconstruct project/design/analysis context.  Shield
// that window instead of rendering the default dashboard and visibly jumping
// to the requested page seconds later.
const routeHydrationShield = (() => {
  if (!String(window.location.pathname || '').startsWith('/app/')) return null;
  root.dataset.routeBoot = 'hydrating';
  const node = document.createElement('div');
  node.id = 'routeHydrationShield';
  node.setAttribute('role', 'status');
  node.setAttribute('aria-live', 'polite');
  node.style.cssText = 'position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;background:#f6f8fb;color:#172033;font:500 15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif';
  node.innerHTML = '<div style="display:grid;gap:10px;text-align:center"><b style="font-size:18px">正在恢复当前工程页面</b><span style="color:#637086">读取 URL 中的项目、方案、电机版本与页面上下文…</span></div>';
  document.body.appendChild(node);
  return node;
})();
function releaseRouteHydrationShield(status = 'ready') {
  root.dataset.routeBoot = status;
  routeHydrationShield?.remove?.();
}
if (routeHydrationShield) {
  appScope.listen(window, 'mcs:route-ready', () => releaseRouteHydrationShield('ready'), {once: true});
  appScope.listen(window, 'mcs:route-error', () => releaseRouteHydrationShield('failed'), {once: true});
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
}

function assertReleaseManifest() {
  const release = namespace.compat?.MCS_RELEASE || {};
  const productVersion = String(release.productVersion || '');
  const assetVersion = String(release.assetVersion || '');
  if (productVersion !== documentVersion || assetVersion !== documentVersion) {
    throw new Error(`Frontend release mismatch: document=${documentVersion}, product=${productVersion || '-'}, assets=${assetVersion || '-'}`);
  }
}

function registerFeatureLifecycles() {
  features.register({
    id: 'application-shell',
    match: () => true,
    mount: () => diagnostics.record('INFO', 'SHELL_FEATURE_MOUNTED'),
  });
  features.register({
    id: 'design-workspace',
    match: () => Boolean(document.querySelector('#designWorkspace.active, [data-canonical-stage="design"].active')),
    mount: () => diagnostics.record('INFO', 'DESIGN_FEATURE_MOUNTED'),
  });
  features.register({
    id: 'analysis-workflow',
    match: () => Boolean(document.querySelector('#analysisWorkspace.active, [data-canonical-stage="analysis"].active')),
    mount: () => diagnostics.record('INFO', 'ANALYSIS_FEATURE_MOUNTED'),
  });
  features.register({
    id: 'results-workspace',
    match: () => Boolean(document.querySelector('#resultViewer.active, [data-canonical-stage="results"].active')),
    mount: ({scope}) => {
      scope.defer(() => namespace.compat?.MCSFieldViewer?.dispose?.());
      diagnostics.record('INFO', 'RESULTS_FEATURE_MOUNTED');
    },
  });
}

async function synchronizeFeatures(reason) {
  await features.sync({reason, location: window.location.href});
}

try {
  const legacyRuntime = await installLegacyRuntime(namespace, {verifyHash: true});
  namespace.runtime.loaded.push('/static/core/classic-runtime-source.js');
  root.dataset.bootstrapLoaded = '1';
  bus.emit('bootstrap:progress', {
    loaded: 1,
    total: 1,
    path: '/static/core/classic-runtime-source.js',
    sourceCount: CLASSIC_RUNTIME_CATALOG.source_count,
  });
  assertReleaseManifest();

  const moduleReport = namespace.compat?.MCSFrontendModuleRegistry?.snapshot?.();
  if (!moduleReport?.compatible) {
    const detail = (moduleReport?.issues || []).map(row => row.code || String(row)).join(', ');
    throw new Error(`Frontend module validation failed${detail ? `: ${detail}` : ''}`);
  }

  const navigationBridge = installNavigationBridge({namespace, scope: appScope});
  namespace.runtime.navigationBridge = navigationBridge;
  const interactionMonitor = installInteractionMonitor({namespace, bus, scope: appScope});
  namespace.runtime.interactionMonitor = interactionMonitor;
  const controlPlane = installControlPlaneFeature({namespace, scope: appScope});
  namespace.runtime.controlPlane = controlPlane;
  const binaryFieldViewer = installBinaryFieldViewer({namespace, scope: appScope});
  namespace.runtime.binaryFieldViewer = binaryFieldViewer;
  registerFeatureLifecycles();

  for (const eventName of ['mcs:route-ready', 'mcs:canonical-page-enter', 'mcs:canonical-page-leave', 'popstate', 'hashchange']) {
    appScope.listen(window, eventName, () => synchronizeFeatures(eventName), {passive: true});
  }
  appScope.listen(window, 'error', event => diagnostics.record('ERROR', 'WINDOW_ERROR', {
    message: event.message,
    source: event.filename,
    line: event.lineno,
  }));
  appScope.listen(window, 'unhandledrejection', event => diagnostics.record('ERROR', 'UNHANDLED_REJECTION', {
    reason: String(event.reason?.message || event.reason || 'unknown'),
  }));
  appScope.listen(window, 'pagehide', () => namespace.dispose(), {once: true});

  await synchronizeFeatures('bootstrap');
  namespace.runtime.state = 'ready';
  namespace.runtime.legacySnapshot = legacyRuntime.snapshot();
  root.dataset.bootstrapState = 'ready';
  root.dataset.moduleCompatibility = 'compatible';
  stores.workflow.set({stage: 'ready'}, {source: 'bootstrap'});
  window.dispatchEvent(new CustomEvent('mcs:bootstrap-ready', {
    detail: {
      version: documentVersion,
      runtimeAssetCount: 1,
      classicSourceCount: CLASSIC_RUNTIME_CATALOG.source_count,
    },
  }));
  diagnostics.record('INFO', 'BOOTSTRAP_READY', {
    version: documentVersion,
    runtimeAssetCount: 1,
    classicSourceCount: CLASSIC_RUNTIME_CATALOG.source_count,
    classicSourceSha256: CLASSIC_RUNTIME_CATALOG.source_sha256,
    compatibilityGlobals: legacyRuntime.snapshot().compatibilityGlobalCount,
  });
} catch (error) {
  releaseRouteHydrationShield('failed');
  namespace.runtime.state = 'failed';
  namespace.runtime.failed = String(error?.message || error);
  root.dataset.bootstrapState = 'failed';
  diagnostics.record('ERROR', 'BOOTSTRAP_FAILED', {message: namespace.runtime.failed});
  console.error(error);
  features.dispose();
  appScope.dispose();
  namespace.legacyRuntime?.dispose?.();
  const host = document.createElement('section');
  host.className = 'startup-failure';
  host.innerHTML = `<h1>MotorCAD Studio 启动失败</h1><p>${escapeHtml(namespace.runtime.failed)}</p><p>请关闭旧服务，确认完整解压最新代码包，然后重新启动。</p>`;
  document.body.replaceChildren(host);
}
