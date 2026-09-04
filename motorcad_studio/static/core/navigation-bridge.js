/**
 * Durable navigation bridge.
 *
 * Fixed shell navigation is intercepted in capture phase and resolved by the
 * History API router.  Classic features can still render the existing DOM, but
 * a button click can no longer depend on a best-effort showTab side effect.
 */
const ROUTABLE_TABS = Object.freeze(new Set([
  'setup', 'projects', 'dashboard', 'solutions', 'templates', 'workspace',
  'analysisConfig', 'tasks', 'monitor', 'resultViewer', 'dataFactory', 'logs', 'system',
]));

function isPrimaryPointerClick(event) {
  return event.button == null || event.button === 0;
}

export function installNavigationBridge({namespace, scope}) {
  if (!namespace || !scope) throw new TypeError('namespace and scope are required');

  const navigateControl = event => {
    if (event.defaultPrevented || !isPrimaryPointerClick(event)) return;
    const control = event.target?.closest?.('[data-tab], [data-go]');
    if (!control || control.disabled || control.getAttribute('aria-disabled') === 'true') return;
    // Engineer-stage controls own richer result/decision semantics in their
    // dedicated workflow controller; do not steal those clicks here.
    if (control.hasAttribute('data-engineer-stage')) return;

    const tab = String(control.dataset.tab || control.dataset.go || '');
    if (!ROUTABLE_TABS.has(tab)) return;
    const router = namespace.compat?.MCSRouter;
    if (!router?.routeForTab || !router?.navigate) return;
    const path = router.routeForTab(tab);
    if (!path) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    Promise.resolve(router.navigate(path, {source: 'core:navigation-bridge'})).catch(error => {
      namespace.compat?.MCSPageRuntime?.report?.(
        'FRONTEND_NAVIGATION_FAILED', 'ERROR', error?.message || String(error),
        {tab, path, control_id: control.id || control.dataset.hmiControlId || null},
      );
      console.error('durable navigation failed', {tab, path}, error);
    });
  };

  scope.listen(document, 'click', navigateControl, true);
  return Object.freeze({tabs: [...ROUTABLE_TABS]});
}
