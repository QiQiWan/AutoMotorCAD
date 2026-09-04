/* MotorCAD Studio design state store.
 * This is the single shared state boundary for read-only design viewing,
 * draft editing and router synchronization. Legacy view/editor modules keep
 * their compatibility state but mirror through this store.
 */
(() => {
  const listeners = new Set();
  let revision = 0;
  const state = {
    projectId: null,
    designId: null,
    revisionId: null,
    mode: 'read',
    view: 'radial',
    selectedParameter: null,
    data: null,
    dirtyCount: 0,
    draftStatus: 'saved',
    transactionHash: null,
    intentHash: null,
    nativeStatus: 'UNCHECKED',
    nativeEvidenceCurrent: false,
    source: 'init',
  };

  function snapshot() {
    return Object.freeze({...state, stateRevision: revision});
  }

  function notify(previous, source) {
    revision += 1;
    state.source = source || 'unknown';
    const next = snapshot();
    listeners.forEach(listener => {
      try { listener(next, previous); } catch (error) { console.error('design store listener failed', error); }
    });
    window.dispatchEvent(new CustomEvent('mcs:design-state', {detail: next}));
    return next;
  }

  function patch(values = {}, options = {}) {
    const previous = snapshot();
    let changed = false;
    Object.entries(values).forEach(([key, value]) => {
      if (!(key in state)) return;
      if (state[key] !== value) {
        state[key] = value;
        changed = true;
      }
    });
    if (!changed) return snapshot();
    return options.silent ? snapshot() : notify(previous, options.source || 'patch');
  }

  function setContext(context = {}, options = {}) {
    const hasDesign = Object.prototype.hasOwnProperty.call(context, 'designId');
    const hasRevision = Object.prototype.hasOwnProperty.call(context, 'revisionId');
    const identityChanged = (hasDesign && context.designId !== state.designId) || (hasRevision && context.revisionId !== state.revisionId);
    return patch({
      projectId: context.projectId ?? state.projectId,
      designId: hasDesign ? context.designId : state.designId,
      revisionId: hasRevision ? context.revisionId : state.revisionId,
      mode: context.mode ?? state.mode,
      view: context.view ?? state.view,
      selectedParameter: Object.prototype.hasOwnProperty.call(context, 'selectedParameter') ? context.selectedParameter : (identityChanged ? null : state.selectedParameter),
      data: Object.prototype.hasOwnProperty.call(context, 'data') ? context.data : (identityChanged ? null : state.data),
      dirtyCount: Object.prototype.hasOwnProperty.call(context, 'dirtyCount') ? context.dirtyCount : (identityChanged ? 0 : state.dirtyCount),
      draftStatus: Object.prototype.hasOwnProperty.call(context, 'draftStatus') ? context.draftStatus : (identityChanged ? 'saved' : state.draftStatus),
      transactionHash: Object.prototype.hasOwnProperty.call(context, 'transactionHash') ? context.transactionHash : (identityChanged ? null : state.transactionHash),
      intentHash: Object.prototype.hasOwnProperty.call(context, 'intentHash') ? context.intentHash : (identityChanged ? null : state.intentHash),
      nativeStatus: Object.prototype.hasOwnProperty.call(context, 'nativeStatus') ? context.nativeStatus : (identityChanged ? 'UNCHECKED' : state.nativeStatus),
      nativeEvidenceCurrent: Object.prototype.hasOwnProperty.call(context, 'nativeEvidenceCurrent') ? Boolean(context.nativeEvidenceCurrent) : (identityChanged ? false : state.nativeEvidenceCurrent),
    }, {source: options.source || 'context', silent: options.silent});
  }

  function setView(view, options = {}) {
    if (!view) return snapshot();
    return patch({view}, {source: options.source || 'view', silent: options.silent});
  }

  function setMode(mode, options = {}) {
    if (!['read', 'edit'].includes(mode)) return snapshot();
    return patch({mode}, {source: options.source || 'mode', silent: options.silent});
  }

  function selectParameter(parameterId, options = {}) {
    return patch({selectedParameter: parameterId || null}, {source: options.source || 'parameter', silent: options.silent});
  }

  function reset(options = {}) {
    const previous = snapshot();
    Object.assign(state, {
      projectId: null,
      designId: null,
      revisionId: null,
      mode: 'read',
      view: 'radial',
      selectedParameter: null,
      data: null,
      dirtyCount: 0,
      draftStatus: 'saved',
      transactionHash: null, intentHash: null, nativeStatus: 'UNCHECKED', nativeEvidenceCurrent: false,
      source: 'reset',
    });
    return options.silent ? snapshot() : notify(previous, options.source || 'reset');
  }

  function subscribe(listener, options = {}) {
    if (typeof listener !== 'function') return () => {};
    listeners.add(listener);
    if (options.immediate) listener(snapshot(), null);
    return () => listeners.delete(listener);
  }

  window.MCSDesignStore = {
    getState: snapshot,
    patch,
    setContext,
    setView,
    setMode,
    selectParameter,
    reset,
    subscribe,
    currentView: () => state.view,
    currentMode: () => state.mode,
  };
})();
