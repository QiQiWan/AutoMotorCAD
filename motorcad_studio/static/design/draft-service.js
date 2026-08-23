/* V0.65 Design draft persistence service.
 * Owns serialized autosave, optimistic concurrency and route-safe flushing.
 * The editor owns engineering state; this service owns draft I/O lifecycle only.
 */
(() => {
  const clone = value => {
    if (typeof structuredClone === 'function') return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  };

  function create(options = {}) {
    const service = {
      draft: null,
      conflict: null,
      savePromise: null,
      pending: null,
      timer: 0,
      payloadVersion: 0,
      persistedVersion: 0,
      session: 0,
      busy: false,
      lastError: null,
      lastSavedAt: null,
      lastSaveReason: null,
    };

    const notify = () => {
      try { options.onStateChange?.(snapshot()); } catch {}
    };
    const designId = () => options.getDesignId?.() || null;
    const hasChanges = () => Boolean(options.hasChanges?.());
    const payload = () => options.buildPayload?.() || null;
    const expectedDraftVersion = () => Number(service.draft?.version || 0);
    const expectedDeleteVersion = () => Number(service.draft?.version ?? service.conflict?.version ?? service.conflict?.current_version ?? 0);

    function snapshot() {
      return {
        draft: service.draft,
        conflict: service.conflict,
        busy: service.busy,
        lastError: service.lastError,
        lastSavedAt: service.lastSavedAt,
        session: service.session,
        queued: Boolean(service.pending),
        hasChanges: hasChanges(),
        persistedVersion: service.persistedVersion,
      };
    }

    function begin({draft = null, conflict = null} = {}) {
      clearTimeout(service.timer);
      service.session += 1;
      service.draft = draft;
      service.conflict = conflict;
      service.pending = null;
      service.payloadVersion = 0;
      service.persistedVersion = 0;
      service.busy = false;
      service.lastError = null;
      service.lastSavedAt = draft?.updated_at || null;
      service.lastSaveReason = null;
      notify();
      return snapshot();
    }

    function setConflict(conflict) {
      service.conflict = conflict || null;
      service.lastError = conflict ? new Error('当前电机已有基于其他 Design Revision 的草稿') : null;
      notify();
    }

    function makeRequest({deleteDraft = false, silent = true, force = false, reason = 'autosave'} = {}) {
      const id = designId();
      if (!id) return null;
      const version = ++service.payloadVersion;
      const request = {
        designId: id,
        deleteDraft,
        force,
        silent,
        reason,
        version,
        session: service.session,
      };
      if (!deleteDraft) {
        const current = payload();
        if (!current) return null;
        request.payload = clone(current);
      }
      return request;
    }

    async function drain() {
      if (service.savePromise) return service.savePromise;
      service.savePromise = (async () => {
        while (service.pending) {
          const request = service.pending;
          service.pending = null;
          service.busy = true;
          service.lastError = null;
          service.lastSaveReason = request.reason;
          notify();
          try {
            if (request.deleteDraft) {
              if (request.force || service.draft) {
                const deleteVersion = expectedDeleteVersion();
                await api(`/api/solutions/${encodeURIComponent(request.designId)}/draft?expected_version=${encodeURIComponent(deleteVersion)}`, {method: 'DELETE'});
              }
              if (request.session === service.session && request.version >= service.persistedVersion) {
                service.draft = null;
                service.conflict = null;
                service.lastSavedAt = null;
                service.persistedVersion = request.version;
              }
            } else {
              // Resolve the optimistic version immediately before each serialized PUT.
              // A second edit may be queued while the previous PUT is still in flight;
              // binding expected_version at enqueue time would create a false stale-write
              // conflict after the first PUT advances the server draft version.
              const requestPayload = {...request.payload, expected_version: expectedDraftVersion()};
              const result = await api(`/api/solutions/${encodeURIComponent(request.designId)}/draft`, {
                method: 'PUT',
                body: JSON.stringify(requestPayload),
              });
              if (request.session === service.session && request.version >= service.persistedVersion) {
                service.draft = result.draft || null;
                service.conflict = null;
                service.lastSavedAt = service.draft?.updated_at || new Date().toISOString();
                service.persistedVersion = request.version;
              }
            }
            if (!request.silent) toast(request.deleteDraft ? '设计草稿已清除。' : '设计草稿已保存。', 'SUCCESS', 3200);
          } catch (error) {
            if (request.session === service.session) {
              service.lastSavedAt = null;
              service.lastError = error;
              if (error?.status === 409 && error?.detail?.code === 'DESIGN_DRAFT_STALE') {
                service.conflict = {
                  kind: 'stale_same_revision',
                  current_version: error.detail.current_version,
                  updated_at: error.detail.updated_at,
                };
              }
            }
            if (!request.silent) toast(`设计草稿保存失败：${error.message}`, 'ERROR', 6500);
            throw error;
          } finally {
            if (request.session === service.session) {
              service.busy = false;
              notify();
            }
          }
        }
        return service.draft;
      })().finally(() => {
        service.savePromise = null;
        service.busy = false;
        notify();
        if (service.pending) drain().catch(() => {});
      });
      return service.savePromise;
    }

    function enqueuePersist({silent = true, reason = 'autosave'} = {}) {
      if (service.conflict) return Promise.reject(new Error('当前设计草稿存在并发冲突，请先重新加载或处理冲突'));
      const request = makeRequest({deleteDraft: !hasChanges(), silent, reason});
      if (!request) return Promise.resolve(service.draft);
      clearTimeout(service.timer);
      service.pending = request;
      if (hasChanges()) service.lastSavedAt = null;
      service.lastError = null;
      notify();
      return drain();
    }

    function schedule({delay = 1000, reason = 'autosave'} = {}) {
      clearTimeout(service.timer);
      if (hasChanges()) service.lastSavedAt = null;
      service.lastError = null;
      notify();
      if (service.conflict) return;
      if (!hasChanges() && !service.draft) return;
      service.timer = window.setTimeout(() => enqueuePersist({silent: true, reason}).catch(() => {}), delay);
    }

    function queueDelete({silent = true, force = false, reason = 'discard'} = {}) {
      const request = makeRequest({deleteDraft: true, silent, force, reason});
      if (!request) return Promise.resolve(null);
      clearTimeout(service.timer);
      service.pending = request;
      service.lastSavedAt = null;
      service.lastError = null;
      notify();
      return drain();
    }

    async function flush({silent = true, reason = 'route-change'} = {}) {
      clearTimeout(service.timer);
      if (service.conflict) throw new Error('设计草稿存在并发冲突，无法安全离开编辑页面');
      if (service.pending) await drain();
      const needsPersist = hasChanges()
        ? (!service.draft || !service.lastSavedAt || Boolean(service.lastError))
        : Boolean(service.draft);
      if (needsPersist) await enqueuePersist({silent, reason});
      if (service.savePromise) await service.savePromise;
      if (service.lastError) throw service.lastError;
      return service.draft;
    }

    function hasUnpersistedChanges() {
      return Boolean(service.pending || service.busy || service.lastError || (hasChanges() && !service.lastSavedAt));
    }

    function dispose() {
      clearTimeout(service.timer);
      service.session += 1;
      service.pending = null;
      service.conflict = null;
      service.lastError = null;
      notify();
    }

    return {state: service, snapshot, begin, setConflict, schedule, persist: enqueuePersist, delete: queueDelete, flush, drain, hasUnpersistedChanges, dispose};
  }

  window.MCSDesignDraftService = {create};
})();
