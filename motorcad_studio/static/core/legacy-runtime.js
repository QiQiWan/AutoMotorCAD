import {CLASSIC_RUNTIME_CATALOG, CLASSIC_RUNTIME_SOURCE} from './classic-runtime-source.js';

const CAPTURE = options => typeof options === 'boolean' ? options : Boolean(options?.capture);
const WINDOW_METHODS = new Set([
  'addEventListener', 'removeEventListener', 'dispatchEvent', 'alert', 'confirm', 'prompt',
  'open', 'close', 'focus', 'blur', 'postMessage', 'getComputedStyle', 'matchMedia',
  'scroll', 'scrollTo', 'scrollBy', 'atob', 'btoa', 'queueMicrotask', 'structuredClone',
]);
const INTERNAL_IDENTIFIERS = new Set(['scope', '__mcs_source__', 'arguments']);

function asListener(listener) {
  if (typeof listener === 'function') return listener;
  if (listener && typeof listener.handleEvent === 'function') {
    return function legacyObjectListener(event) { return listener.handleEvent(event); };
  }
  return null;
}

function abortError(message) {
  return globalThis.DOMException
    ? new DOMException(message, 'AbortError')
    : Object.assign(new Error(message), {name: 'AbortError'});
}

async function sha256Text(text) {
  if (!globalThis.crypto?.subtle || !globalThis.TextEncoder) return null;
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

/**
 * Owns every resource created by the sealed classic runtime.  The EventTarget
 * interception remains installed only for this capsule's lifetime and records
 * listeners solely while a legacy callback is executing.
 */
class LegacyRuntimeScope {
  constructor(hostWindow, namespace) {
    this.host = hostWindow;
    this.namespace = namespace;
    this.compat = Object.create(null);
    this.currentOwner = null;
    this.disposed = false;
    this.events = [];
    this.timeouts = new Map();
    this.intervals = new Map();
    this.frames = new Map();
    this.idleCallbacks = new Map();
    this.workers = new Set();
    this.observers = new Set();
    this.cleanup = [];
    this.lastFailure = null;
    this.fetchController = new AbortController();
    this.metrics = {
      registeredListeners: 0,
      clearedListeners: 0,
      createdWorkers: 0,
      terminatedWorkers: 0,
      createdObservers: 0,
      disconnectedObservers: 0,
      createdIdleCallbacks: 0,
      clearedIdleCallbacks: 0,
      fetches: 0,
      abortedFetches: 0,
    };
    this._patchEventTarget();
    this.proxy = this._createProxy();
  }

  setOwner(owner) {
    this.currentOwner = owner ? String(owner) : null;
  }

  withOwner(owner, callback, receiver = undefined, args = []) {
    const previous = this.currentOwner;
    this.currentOwner = owner || previous;
    try { return callback.apply(receiver, args); }
    finally { this.currentOwner = previous; }
  }

  _patchEventTarget() {
    const prototype = this.host.EventTarget?.prototype;
    if (!prototype) return;
    const originalAdd = prototype.addEventListener;
    const originalRemove = prototype.removeEventListener;
    const scope = this;

    function patchedAdd(type, listener, options) {
      const owner = scope.currentOwner;
      const callable = asListener(listener);
      if (!owner || !callable || scope.disposed) {
        return originalAdd.call(this, type, listener, options);
      }
      const capture = CAPTURE(options);
      const existing = scope.events.find(row => (
        row.active && row.target === this && row.type === type && row.listener === listener && row.capture === capture
      ));
      if (existing) return undefined;
      const target = this;
      const wrapped = function legacyTrackedListener(...args) {
        return scope.withOwner(owner, callable, listener && typeof listener !== 'function' ? listener : target, args);
      };
      const record = {target, type, listener, wrapped, options, capture, owner, active: true};
      scope.events.push(record);
      scope.metrics.registeredListeners += 1;
      return originalAdd.call(target, type, wrapped, options);
    }

    function patchedRemove(type, listener, options) {
      const capture = CAPTURE(options);
      const record = scope.events.find(row => (
        row.active && row.target === this && row.type === type && row.listener === listener && row.capture === capture
      ));
      if (!record) return originalRemove.call(this, type, listener, options);
      record.active = false;
      scope.metrics.clearedListeners += 1;
      return originalRemove.call(this, type, record.wrapped, options);
    }

    prototype.addEventListener = patchedAdd;
    prototype.removeEventListener = patchedRemove;
    this.cleanup.push(() => {
      if (prototype.addEventListener === patchedAdd) prototype.addEventListener = originalAdd;
      if (prototype.removeEventListener === patchedRemove) prototype.removeEventListener = originalRemove;
    });
    this._originalEventRemove = originalRemove;
  }

  _trackedTimeout(callback, delay, ...args) {
    const owner = this.currentOwner;
    const id = this.host.setTimeout(() => {
      this.timeouts.delete(id);
      if (!this.disposed) this.withOwner(owner, callback, this.host, args);
    }, delay);
    this.timeouts.set(id, owner);
    return id;
  }

  _trackedInterval(callback, delay, ...args) {
    const owner = this.currentOwner;
    const id = this.host.setInterval(() => {
      if (!this.disposed) this.withOwner(owner, callback, this.host, args);
    }, delay);
    this.intervals.set(id, owner);
    return id;
  }

  _trackedAnimationFrame(callback) {
    const owner = this.currentOwner;
    const id = this.host.requestAnimationFrame(timestamp => {
      this.frames.delete(id);
      if (!this.disposed) this.withOwner(owner, callback, this.host, [timestamp]);
    });
    this.frames.set(id, owner);
    return id;
  }

  _trackedIdleCallback(callback, options) {
    const owner = this.currentOwner;
    const nativeRequestIdleCallback = this.host.requestIdleCallback;
    if (typeof nativeRequestIdleCallback !== 'function') return undefined;
    const id = nativeRequestIdleCallback.call(this.host, deadline => {
      this.idleCallbacks.delete(id);
      if (!this.disposed) this.withOwner(owner, callback, this.host, [deadline]);
    }, options);
    this.idleCallbacks.set(id, owner);
    this.metrics.createdIdleCallbacks += 1;
    return id;
  }

  _cancelIdleCallback(id) {
    if (this.idleCallbacks.delete(id)) this.metrics.clearedIdleCallbacks += 1;
    const nativeCancelIdleCallback = this.host.cancelIdleCallback;
    if (typeof nativeCancelIdleCallback === 'function') {
      return nativeCancelIdleCallback.call(this.host, id);
    }
    return undefined;
  }

  _trackedObserver(NativeObserver) {
    const scope = this;
    if (typeof NativeObserver !== 'function') return NativeObserver;
    return class TrackedLegacyObserver extends NativeObserver {
      constructor(callback) {
        const owner = scope.currentOwner;
        super((...args) => scope.withOwner(owner, callback, undefined, args));
        this.__mcsOwner = owner;
        scope.observers.add(this);
        scope.metrics.createdObservers += 1;
      }
      disconnect() {
        if (scope.observers.delete(this)) scope.metrics.disconnectedObservers += 1;
        return super.disconnect();
      }
    };
  }

  _trackedWorkerClass() {
    const NativeWorker = this.host.Worker;
    const scope = this;
    if (typeof NativeWorker !== 'function') return NativeWorker;
    function TrackedLegacyWorker(url, options) {
      const worker = new NativeWorker(url, options);
      worker.__mcsOwner = scope.currentOwner;
      scope.workers.add(worker);
      scope.metrics.createdWorkers += 1;
      const terminate = worker.terminate.bind(worker);
      worker.terminate = () => {
        if (scope.workers.delete(worker)) scope.metrics.terminatedWorkers += 1;
        return terminate();
      };
      return worker;
    }
    TrackedLegacyWorker.prototype = NativeWorker.prototype;
    Object.setPrototypeOf(TrackedLegacyWorker, NativeWorker);
    return TrackedLegacyWorker;
  }

  _trackedFetch(input, init = {}) {
    this.metrics.fetches += 1;
    const central = this.fetchController.signal;
    const external = init?.signal;
    let signal = central;
    if (external) {
      if (globalThis.AbortSignal?.any) signal = AbortSignal.any([central, external]);
      else {
        const controller = new AbortController();
        const abort = reason => { if (!controller.signal.aborted) controller.abort(reason); };
        if (central.aborted) abort(central.reason);
        else central.addEventListener('abort', () => abort(central.reason), {once: true});
        if (external.aborted) abort(external.reason);
        else external.addEventListener('abort', () => abort(external.reason), {once: true});
        signal = controller.signal;
      }
    }
    return this.host.fetch(input, {...init, signal});
  }

  _createProxy() {
    const scope = this;
    const host = this.host;
    const compat = this.compat;
    const trackedResizeObserver = this._trackedObserver(host.ResizeObserver);
    const trackedMutationObserver = this._trackedObserver(host.MutationObserver);
    const trackedIntersectionObserver = this._trackedObserver(host.IntersectionObserver);
    const trackedWorker = this._trackedWorkerClass();
    let proxy;
    proxy = new Proxy(compat, {
      has(_target, property) {
        if (property === Symbol.unscopables) return false;
        if (typeof property === 'string' && INTERNAL_IDENTIFIERS.has(property)) return false;
        return true;
      },
      get(target, property) {
        if (property === Symbol.unscopables) return undefined;
        if (property === 'window' || property === 'self' || property === 'globalThis') return proxy;
        if (property === 'MotorCADStudio') return scope.namespace;
        if (property === '__MCS_LEGACY_OWNER__') return owner => scope.setOwner(owner);
        if (property === 'setTimeout') return scope._trackedTimeout.bind(scope);
        if (property === 'clearTimeout') return id => { scope.timeouts.delete(id); host.clearTimeout(id); };
        if (property === 'setInterval') return scope._trackedInterval.bind(scope);
        if (property === 'clearInterval') return id => { scope.intervals.delete(id); host.clearInterval(id); };
        if (property === 'requestAnimationFrame') return scope._trackedAnimationFrame.bind(scope);
        if (property === 'cancelAnimationFrame') return id => { scope.frames.delete(id); host.cancelAnimationFrame(id); };
        if (property === 'requestIdleCallback') {
          return typeof host.requestIdleCallback === 'function' ? scope._trackedIdleCallback.bind(scope) : undefined;
        }
        if (property === 'cancelIdleCallback') return scope._cancelIdleCallback.bind(scope);
        if (property === 'fetch') return scope._trackedFetch.bind(scope);
        if (property === 'ResizeObserver') return trackedResizeObserver;
        if (property === 'MutationObserver') return trackedMutationObserver;
        if (property === 'IntersectionObserver') return trackedIntersectionObserver;
        if (property === 'Worker') return trackedWorker;
        if (Reflect.has(target, property)) return Reflect.get(target, property);
        const value = host[property];
        if (typeof property === 'string' && WINDOW_METHODS.has(property) && typeof value === 'function') {
          return value.bind(host);
        }
        return value;
      },
      set(target, property, value) {
        if (property === 'MotorCADStudio') {
          if (value && value !== scope.namespace) Object.assign(scope.namespace, value);
          return true;
        }
        Reflect.set(target, property, value);
        return true;
      },
      defineProperty(target, property, descriptor) {
        Reflect.defineProperty(target, property, {...descriptor, configurable: true});
        return true;
      },
      deleteProperty(target, property) { return Reflect.deleteProperty(target, property); },
      ownKeys(target) { return [...new Set([...Reflect.ownKeys(host), ...Reflect.ownKeys(target)])]; },
      getOwnPropertyDescriptor(target, property) {
        return Reflect.getOwnPropertyDescriptor(target, property)
          || (() => {
            const descriptor = Reflect.getOwnPropertyDescriptor(host, property);
            return descriptor ? {...descriptor, configurable: true} : null;
          })()
          || {configurable: true, enumerable: true, writable: true, value: undefined};
      },
    });
    return proxy;
  }

  snapshot() {
    const globals = Object.keys(this.compat).sort();
    return {
      authority: 'MotorCADStudioLegacyRuntimeSnapshotV1',
      sourceCount: CLASSIC_RUNTIME_CATALOG.source_count,
      sourceSha256: CLASSIC_RUNTIME_CATALOG.source_sha256,
      currentOwner: this.currentOwner,
      disposed: this.disposed,
      compatibilityGlobalCount: globals.length,
      compatibilityGlobals: globals,
      activeListeners: this.events.filter(row => row.active).length,
      activeTimeouts: this.timeouts.size,
      activeIntervals: this.intervals.size,
      activeAnimationFrames: this.frames.size,
      activeIdleCallbacks: this.idleCallbacks.size,
      activeWorkers: this.workers.size,
      activeObservers: this.observers.size,
      lastFailure: this.lastFailure ? {...this.lastFailure} : null,
      metrics: {...this.metrics},
    };
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.setOwner(null);
    if (!this.fetchController.signal.aborted) {
      this.fetchController.abort(abortError('MotorCAD Studio legacy runtime disposed'));
      this.metrics.abortedFetches += 1;
    }
    for (const row of this.events.splice(0).reverse()) {
      if (!row.active) continue;
      row.active = false;
      try { this._originalEventRemove?.call(row.target, row.type, row.wrapped, row.options); }
      catch (_) {}
      this.metrics.clearedListeners += 1;
    }
    for (const id of this.timeouts.keys()) this.host.clearTimeout(id);
    for (const id of this.intervals.keys()) this.host.clearInterval(id);
    for (const id of this.frames.keys()) this.host.cancelAnimationFrame(id);
    for (const id of this.idleCallbacks.keys()) this._cancelIdleCallback(id);
    this.timeouts.clear();
    this.intervals.clear();
    this.frames.clear();
    this.idleCallbacks.clear();
    for (const worker of [...this.workers]) {
      try { worker.terminate(); } catch (_) {}
    }
    this.workers.clear();
    for (const observer of [...this.observers]) {
      try { observer.disconnect(); } catch (_) {}
    }
    this.observers.clear();
    for (const cleanup of this.cleanup.splice(0).reverse()) {
      try { cleanup(); } catch (_) {}
    }
  }
}

export async function installLegacyRuntime(namespace, {verifyHash = true} = {}) {
  if (!namespace || typeof namespace !== 'object') throw new TypeError('MotorCADStudio namespace is required');
  if (namespace.legacyRuntime && !namespace.legacyRuntime.disposed) {
    throw new Error('Legacy runtime capsule is already installed');
  }
  if (verifyHash) {
    const digest = await sha256Text(CLASSIC_RUNTIME_SOURCE);
    if (digest && digest !== CLASSIC_RUNTIME_CATALOG.source_sha256) {
      throw new Error(`Legacy runtime source hash mismatch: ${digest}`);
    }
  }
  const runtime = new LegacyRuntimeScope(window, namespace);
  Object.defineProperty(namespace, 'compat', {
    value: runtime.compat,
    configurable: false,
    enumerable: true,
    writable: false,
  });
  Object.defineProperty(namespace, 'legacyRuntime', {
    value: runtime,
    configurable: false,
    enumerable: true,
    writable: false,
  });
  const evaluatorFactory = new Function(
    'scope',
    'with (scope) { return function(__mcs_source__) { return eval(__mcs_source__); }; }',
  );
  const evaluate = evaluatorFactory(runtime.proxy);
  runtime.setOwner('classic-runtime-capsule');
  try {
    evaluate(CLASSIC_RUNTIME_SOURCE);
  } catch (error) {
    runtime.lastFailure = {
      owner: runtime.currentOwner || 'classic-runtime-capsule',
      name: String(error?.name || 'Error'),
      message: String(error?.message || error || 'unknown legacy runtime failure'),
    };
    const owner = runtime.lastFailure.owner;
    const message = runtime.lastFailure.message;
    const enriched = new Error(`Legacy runtime ${owner} failed: ${message}`, {cause: error});
    enriched.name = String(error?.name || 'Error');
    throw enriched;
  } finally {
    runtime.setOwner(null);
  }
  return runtime;
}

export {CLASSIC_RUNTIME_CATALOG};
