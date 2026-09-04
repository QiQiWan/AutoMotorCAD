import {DisposableScope} from './disposable-scope.js';

/** Mounts only features matching the current route and serializes lifecycle changes. */
export class FeatureRegistry {
  constructor({bus = null} = {}) {
    this.bus = bus;
    this.definitions = new Map();
    this.active = new Map();
    this._queue = Promise.resolve();
    this._disposed = false;
  }
  register(definition) {
    if (this._disposed) throw new Error('feature registry is disposed');
    if (!definition?.id || typeof definition.match !== 'function' || typeof definition.mount !== 'function') {
      throw new TypeError('feature requires id, match and mount');
    }
    if (this.definitions.has(definition.id)) throw new Error(`duplicate feature: ${definition.id}`);
    this.definitions.set(definition.id, definition);
    return () => { this._unmount(definition.id); this.definitions.delete(definition.id); };
  }
  sync(context = {}) {
    this._queue = this._queue.then(() => this._syncNow(context));
    return this._queue;
  }
  async _syncNow(context) {
    if (this._disposed) return;
    for (const [id, definition] of this.definitions) {
      const shouldMount = Boolean(await definition.match(context));
      if (shouldMount && !this.active.has(id)) {
        const scope = new DisposableScope(`feature:${id}`);
        try {
          const cleanup = await definition.mount({...context, scope});
          if (typeof cleanup === 'function') scope.defer(cleanup);
          this.active.set(id, scope);
          this.bus?.emit('feature:mounted', {id});
        } catch (error) {
          scope.dispose();
          this.bus?.emit('feature:error', {id, error});
          console.error(`Failed to mount feature ${id}`, error);
        }
      } else if (!shouldMount && this.active.has(id)) this._unmount(id);
    }
  }
  _unmount(id) {
    const scope = this.active.get(id);
    if (!scope) return;
    scope.dispose();
    this.active.delete(id);
    this.bus?.emit('feature:unmounted', {id});
  }
  dispose() {
    this._disposed = true;
    for (const id of [...this.active.keys()]) this._unmount(id);
    this.definitions.clear();
  }
  snapshot() {
    return {
      registered: [...this.definitions.keys()],
      active: [...this.active.keys()],
      disposed: this._disposed,
    };
  }
}
