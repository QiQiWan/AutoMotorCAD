/** Scoped event bus used by the 0.90 frontend composition root. */
export class EventBus {
  constructor() { this._target = new EventTarget(); }
  on(type, listener, options = {}) {
    const wrapped = event => listener(event.detail, event);
    this._target.addEventListener(type, wrapped, options);
    return () => this._target.removeEventListener(type, wrapped, options);
  }
  once(type, listener) { return this.on(type, listener, {once: true}); }
  emit(type, detail = null) {
    this._target.dispatchEvent(new CustomEvent(type, {detail}));
  }
}
