/** Minimal observable state container with immutable snapshots. */
export class Store {
  constructor(initialState = {}) {
    this._state = Object.freeze({...initialState});
    this._subscribers = new Set();
  }
  get value() { return this._state; }
  set(patchOrUpdater, metadata = {}) {
    const patch = typeof patchOrUpdater === 'function' ? patchOrUpdater(this._state) : patchOrUpdater;
    const next = Object.freeze({...this._state, ...(patch || {})});
    if (Object.is(next, this._state)) return this._state;
    const previous = this._state;
    this._state = next;
    for (const subscriber of [...this._subscribers]) subscriber(next, previous, metadata);
    return next;
  }
  subscribe(subscriber, {immediate = false} = {}) {
    this._subscribers.add(subscriber);
    if (immediate) subscriber(this._state, this._state, {initial: true});
    return () => this._subscribers.delete(subscriber);
  }
}
