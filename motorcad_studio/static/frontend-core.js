/* V0.25 route-first frontend runtime.
 *
 * Owns route transitions, page-scoped cancellation, cleanup and route state.
 * Legacy pages may still render existing DOM, but route changes no longer rely on
 * arbitrary delays to restore engineering objects.
 */
(() => {
  let sequence = 0;
  let active = null;
  const routeListeners = new Set();
  const reportTimes = new Map();

  function report(eventType, level, message, payload = {}) {
    const route = location.pathname + location.search;
    const signature = `${eventType}:${route}:${String(message).slice(0,180)}`;
    const now = Date.now();
    if (now - (reportTimes.get(signature) || 0) < 10000) return;
    reportTimes.set(signature, now);
    fetch('/api/client-events', {
      method: 'POST', keepalive: true,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({level, event_type: eventType, message: String(message).slice(0,4000), route, payload}),
    }).catch(() => {});
  }

  function isAbortError(error) {
    return Boolean(error && (error.name === 'AbortError' || error.code === 'ABORT_ERR' || error.mcsRouteAbort));
  }

  function isContextActive(context) {
    if (!context) return true;
    if (typeof context.active !== 'function') return false;
    try { return Boolean(context.active()); } catch { return false; }
  }

  function createProgress() {
    let node = document.getElementById('routeProgressV025');
    if (node) return node;
    node = document.createElement('div');
    node.id = 'routeProgressV025';
    node.className = 'route-progress-v025';
    node.setAttribute('aria-hidden', 'true');
    node.innerHTML = '<span></span>';
    document.body.appendChild(node);
    return node;
  }

  function setTransitionState(status, context = active) {
    document.documentElement.dataset.routeTransition = status;
    createProgress().dataset.state = status;
    const tab = context?.route?.tab;
    document.querySelectorAll('.tab').forEach(node => {
      if (node.id === tab) node.setAttribute('aria-busy', status === 'loading' ? 'true' : 'false');
      else node.removeAttribute('aria-busy');
    });
  }

  function disposeContext(context, reason = 'route-change') {
    if (!context || context.disposed) return;
    context.disposed = true;
    try { context.controller.abort(reason); } catch {}
    for (const dispose of context.disposers.splice(0).reverse()) {
      try { dispose(reason); } catch (error) { console.warn('route disposer failed', error); }
    }
  }

  function begin(route) {
    if (active) disposeContext(active, 'route-change');
    const controller = new AbortController();
    const id = ++sequence;
    const context = {
      id,
      route,
      controller,
      signal: controller.signal,
      disposers: [],
      disposed: false,
      startedAt: performance.now(),
      active() { return active === context && !context.disposed && !context.signal.aborted; },
      assertActive() {
        if (!context.active()) {
          const error = new DOMException('Route transition superseded', 'AbortError');
          error.mcsRouteAbort = true;
          throw error;
        }
      },
      onDispose(dispose) {
        if (typeof dispose !== 'function') return () => {};
        if (context.disposed) { try { dispose('already-disposed'); } catch {} return () => {}; }
        context.disposers.push(dispose);
        return () => {
          const index = context.disposers.indexOf(dispose);
          if (index >= 0) context.disposers.splice(index, 1);
        };
      },
      timeout(callback, delay) {
        const handle = window.setTimeout(() => { if (context.active()) callback(); }, delay);
        context.onDispose(() => window.clearTimeout(handle));
        return handle;
      },
      interval(callback, delay) {
        const handle = window.setInterval(() => { if (context.active()) callback(); }, delay);
        context.onDispose(() => window.clearInterval(handle));
        return handle;
      },
      listen(target, type, listener, options) {
        if (!target?.addEventListener) return () => {};
        target.addEventListener(type, listener, options);
        const dispose = () => target.removeEventListener(type, listener, options);
        context.onDispose(dispose);
        return dispose;
      },
      api(url, options = {}) {
        const merged = {...options};
        if (!merged.signal) merged.signal = context.signal;
        return api(url, merged);
      },
    };
    active = context;
    state.routeV025 = {...route, transition_id: id};
    setTransitionState('loading', context);
    window.dispatchEvent(new CustomEvent('mcs:route-start', {detail: {id, route}}));
    routeListeners.forEach(fn => { try { fn(state.routeV025); } catch {} });
    return context;
  }

  function complete(context) {
    if (!context?.active()) return false;
    setTransitionState('ready', context);
    const elapsed = performance.now() - context.startedAt;
    window.dispatchEvent(new CustomEvent('mcs:route-ready', {
      detail: {id: context.id, route: context.route, elapsed_ms: elapsed}
    }));
    if (elapsed > 2000) report('FRONTEND_ROUTE_SLOW', 'WARNING', `页面路由加载耗时 ${Math.round(elapsed)} ms`, {elapsed_ms: Math.round(elapsed), tab: context.route?.tab});
    return true;
  }

  function fail(context, error) {
    if (!context?.active()) return;
    setTransitionState('error', context);
    report('FRONTEND_ROUTE_FAILED', 'ERROR', error?.message || String(error), {tab: context.route?.tab, error_name: error?.name || null});
    window.dispatchEvent(new CustomEvent('mcs:route-error', {detail: {id: context.id, route: context.route, error}}));
  }

  function dispose(reason = 'manual') {
    if (!active) return;
    const old = active;
    active = null;
    disposeContext(old, reason);
    setTransitionState('idle', null);
  }

  function current() { return active; }
  function subscribe(listener) { routeListeners.add(listener); return () => routeListeners.delete(listener); }

  window.addEventListener('error', event => {
    const error = event.error;
    report('FRONTEND_UNCAUGHT_ERROR', 'ERROR', error?.message || event.message || 'Uncaught browser error', {
      filename: event.filename || null, line: event.lineno || null, column: event.colno || null, stack: error?.stack || null,
    });
  });
  window.addEventListener('unhandledrejection', event => {
    const reason = event.reason;
    if (isAbortError(reason)) return;
    report('FRONTEND_UNHANDLED_REJECTION', 'ERROR', reason?.message || String(reason || 'Unhandled promise rejection'), {stack: reason?.stack || null});
  });

  window.MCSPageRuntime = {begin, complete, fail, dispose, current, isAbortError, isContextActive, subscribe, report};
})();
