/* V0.65 Design draft verification service.
 * Studio checks are explicit, cancellable and version-aware; Motor-CAD native
 * verification can only run against the same draft version that passed Studio checks.
 */
(() => {
  function create(options = {}) {
    const state = {
      precheck: null,
      precheckVersion: -1,
      precheckBusy: false,
      precheckAbort: null,
      nativeAbort: null,
      session: 0,
      nativeCheck: null,
      nativeVersion: -1,
      nativeBusy: false,
      lastError: null,
    };
    const notify = () => { try { options.onStateChange?.(snapshot()); } catch {} };
    const currentVersion = () => Number(options.getEditVersion?.() || 0);
    const blocking = result => (result?.issues || []).filter(issue => issue.severity === 'BLOCKING');

    function snapshot() {
      const version = currentVersion();
      return {
        ...state,
        currentVersion: version,
        precheckCurrent: state.precheckVersion === version && Boolean(state.precheck),
        nativeCurrent: state.nativeVersion === version && Boolean(state.nativeCheck),
        nativeStale: state.nativeVersion !== version && Boolean(state.nativeCheck),
        blockingCount: state.precheckVersion === version ? blocking(state.precheck).length : null,
      };
    }

    function begin(precheck = null) {
      state.session += 1;
      state.precheckAbort?.abort();
      state.nativeAbort?.abort();
      state.precheckAbort = null;
      state.nativeAbort = null;
      state.precheck = precheck;
      state.precheckVersion = precheck ? currentVersion() : -1;
      state.precheckBusy = false;
      state.nativeCheck = null;
      state.nativeVersion = -1;
      state.nativeBusy = false;
      state.lastError = null;
      notify();
    }

    function invalidateNative() {
      // Retain the prior evidence as explicitly stale. V0.88-D surfaces this distinction
      // instead of making native evidence disappear after the next design edit.
      state.nativeVersion = -1;
      notify();
    }

    async function runStudio() {
      const revisionId = options.getRevisionId?.();
      if (!revisionId || state.precheckBusy) return state.precheck;
      state.precheckAbort?.abort();
      const controller = new AbortController();
      const version = currentVersion();
      const session = state.session;
      state.precheckAbort = controller;
      state.precheckBusy = true;
      state.lastError = null;
      notify();
      try {
        const result = await api(`/api/design-revisions/${encodeURIComponent(revisionId)}/workbench/precheck`, {
          method: 'POST',
          body: JSON.stringify({
            parameters: options.getParameters?.() || {},
            changed_parameter_ids: options.getChangedIds?.() || [],
          }),
          signal: controller.signal,
        });
        if (controller.signal.aborted || session !== state.session || version !== currentVersion()) return null;
        state.precheck = result;
        state.precheckVersion = version;
        if (state.nativeVersion !== version) state.nativeVersion = -1;
        return result;
      } catch (error) {
        if (error?.name === 'AbortError') return null;
        if (session === state.session && version === currentVersion()) state.lastError = error;
        throw error;
      } finally {
        if (state.precheckAbort === controller) state.precheckAbort = null;
        if (session === state.session && version === currentVersion()) state.precheckBusy = false;
        notify();
      }
    }

    async function runNative({repairPolicy = 'suggest'} = {}) {
      if (state.nativeBusy) return state.nativeCheck;
      const version = currentVersion();
      const session = state.session;
      if (state.precheckVersion !== version || !state.precheck) await runStudio();
      if (session !== state.session || version !== currentVersion()) return null;
      const blocks = blocking(state.precheck);
      if (blocks.length) {
        const error = new Error(`Studio 设计检查存在 ${blocks.length} 项阻断，Motor-CAD 原生检查未启动`);
        error.code = 'STUDIO_PRECHECK_BLOCKED';
        throw error;
      }
      await options.ensurePersisted?.();
      const designId = options.getDesignId?.();
      const draft = options.getDraft?.();
      const transaction = draft?.editor_transaction || options.getEditorTransaction?.();
      if (!designId || !draft || !transaction?.transaction_hash || !transaction?.intent_hash) {
        const error = new Error('当前设计事务尚未完整保存，无法安全启动 Motor-CAD 原生检查');
        error.code = 'EDITOR_TRANSACTION_NOT_PERSISTED';
        throw error;
      }
      state.nativeAbort?.abort();
      const controller = new AbortController();
      state.nativeAbort = controller;
      state.nativeBusy = true; state.lastError = null; notify();
      try {
        const result = await api(`/api/solutions/${encodeURIComponent(designId)}/draft/native-check`, {
          method: 'POST',
          body: JSON.stringify({
            expected_version: Number(draft.version || 0),
            transaction_hash: transaction.transaction_hash,
            intent_hash: transaction.intent_hash,
            timeout_s: 180, force: repairPolicy === 'safe_auto', repair_policy: repairPolicy,
          }),
          signal: controller.signal,
        });
        if (controller.signal.aborted || session !== state.session || version !== currentVersion()) return null;
        options.onNativeResult?.(result);
        state.nativeCheck = result; state.nativeVersion = version;
        return result;
      } catch (error) {
        if (error?.name === 'AbortError') return null;
        if (session === state.session && version === currentVersion()) state.lastError = error;
        throw error;
      } finally {
        if (state.nativeAbort === controller) state.nativeAbort = null;
        if (session === state.session && version === currentVersion()) state.nativeBusy = false;
        notify();
      }
    }

    function dispose() {
      state.session += 1;
      state.precheckAbort?.abort();
      state.nativeAbort?.abort();
      state.precheckAbort = null;
      state.nativeAbort = null;
      state.precheckBusy = false;
      state.nativeBusy = false;
      notify();
    }

    return {state, snapshot, begin, invalidateNative, runStudio, runNative, dispose};
  }

  window.MCSDesignPrecheck = {create};
})();
