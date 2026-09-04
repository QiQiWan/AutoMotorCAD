/** Deterministic lifecycle scope for page features and heavy viewer resources. */
export class DisposableScope {
  constructor(name = 'scope') {
    this.name = name;
    this.disposed = false;
    this._cleanups = [];
  }
  defer(cleanup) {
    if (typeof cleanup !== 'function') return cleanup;
    if (this.disposed) {
      try { cleanup(); } catch (_) {}
      return cleanup;
    }
    this._cleanups.push(cleanup);
    return cleanup;
  }
  child(name) {
    const scope = new DisposableScope(`${this.name}:${name}`);
    this.defer(() => scope.dispose());
    return scope;
  }
  listen(target, type, listener, options) {
    target?.addEventListener?.(type, listener, options);
    return this.defer(() => target?.removeEventListener?.(type, listener, options));
  }
  subscribe(store, subscriber, options) {
    return this.defer(store?.subscribe?.(subscriber, options));
  }
  onBus(bus, type, listener, options) {
    return this.defer(bus?.on?.(type, listener, options));
  }
  timeout(callback, delay) {
    const id = setTimeout(() => { if (!this.disposed) callback(); }, delay);
    this.defer(() => clearTimeout(id));
    return id;
  }
  interval(callback, delay) {
    const id = setInterval(() => { if (!this.disposed) callback(); }, delay);
    this.defer(() => clearInterval(id));
    return id;
  }
  animationFrame(callback) {
    const id = requestAnimationFrame(timestamp => { if (!this.disposed) callback(timestamp); });
    this.defer(() => cancelAnimationFrame(id));
    return id;
  }
  abortController() {
    const controller = new AbortController();
    this.defer(() => {
      const reason = globalThis.DOMException
        ? new DOMException(`${this.name} disposed`, 'AbortError')
        : new Error(`${this.name} disposed`);
      controller.abort(reason);
    });
    return controller;
  }
  worker(url, options) {
    const worker = new Worker(url, options);
    this.defer(() => worker.terminate());
    return worker;
  }
  observe(observer, target, options) {
    observer.observe(target, options);
    this.defer(() => observer.disconnect());
    return observer;
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    for (const cleanup of this._cleanups.splice(0).reverse()) {
      try { cleanup(); } catch (error) { console.warn(`[${this.name}] cleanup failed`, error); }
    }
  }
}
