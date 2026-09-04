/* Design workbench convergence controller.
 * Owns final object-header hierarchy and revision-history visibility without
 * observing arbitrary DOM mutations.
 */
(() => {
  const q = (selector, root = document) => root.querySelector(selector);
  const safe = value => typeof window.esc === 'function' ? window.esc(value) : String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const appState = () => typeof state !== 'undefined' ? state : null;
  const motorLabels = {
    BPM: '\u8868\u8d34\u5f0f\u6c38\u78c1\u540c\u6b65\u7535\u673a',
    SPM: '\u8868\u8d34\u5f0f\u6c38\u78c1\u540c\u6b65\u7535\u673a',
    IPM: '\u5185\u7f6e\u5f0f\u6c38\u78c1\u540c\u6b65\u7535\u673a',
    AFPM: '\u8f74\u5411\u78c1\u901a\u6c38\u78c1\u7535\u673a',
  };

  function designType(design, revision=null) {
    const identity = window.MCSMotorDomain?.identityOf?.(revision) || revision?.motor_snapshot?.identity || null;
    const code = String(identity?.native_motor_type || design?.motor_type_id || design?.motor_family || '').toUpperCase();
    const topology = String(identity?.topology_id || design?.motor_family || '');
    const physicalFamily = String(identity?.family_id || '');
    const label = topology==='rfpm_ipm'?'\u5185\u7f6e\u5f0f\u6c38\u78c1\u540c\u6b65\u7535\u673a':topology==='afpm'?'\u8f74\u5411\u78c1\u901a\u6c38\u78c1\u7535\u673a':(motorLabels[code] || topology || design?.motor_family || '\u6c38\u78c1\u7535\u673a');
    return {code: code || '-', label, topology, physicalFamily};
  }

  function currentStageLabel() {
    const designState = window.MCSDesignStore?.getState?.();
    const stage = window.MCSDesignNavigation?.stageForView?.(designState?.view || 'radial');
    return window.MCSDesignNavigation?.stageDefs?.find(row => row.id === stage)?.label || '\u51e0\u4f55';
  }

  function normalizeHeader() {
    if (!q('#workspace')?.classList.contains('active') || document.body.classList.contains('design-editing-v062')) return;
    const current = appState();
    const design = current?.workspaceDesign;
    const revision = current?.workspaceRevision;
    const header = q('#workspaceCanvas .workspace-object-header');
    if (!design || !revision || !header) return;
    header.classList.add('design-object-header-v063');
    const type = designType(design, revision);
    const lead = [...header.children].find(node => !node.classList.contains('actions'));
    if (lead) {
      const tr=(zh,en)=>window.MCS_I18N?.t?.(zh,en)??zh,revisionText=window.MCSDesignRenderUtils?.revisionLabel?.(revision.revision,'motor')||tr(`电机版本 ${revision.revision}`,`Motor revision ${revision.revision}`);
      lead.innerHTML = `<span class="eyebrow">${tr('\u7535\u673a\u8bbe\u8ba1','Motor design')}</span><h2>${safe(design.name)}</h2><div class="design-object-meta-v063"><span class="design-revision-pill-v063">${safe(revisionText)}</span><span>${safe(type.label)}</span><span>${tr('\u5f53\u524d','Current')}：${safe(currentStageLabel())}</span><details><summary>${tr('\u6280\u672f\u4fe1\u606f','Technical details')}</summary><div><code>${safe(design.id)}</code><span>${safe(type.code)}</span><span>${safe(type.physicalFamily || '-')} / ${safe(type.topology || '-')}</span><span>${safe(design.template_id || '-')}</span><code>${safe(String(revision.motor_snapshot_hash || revision.content_hash || '').slice(0, 16))}</code></div></details></div>`;
    }
    const actions = q('.actions', header);
    const edit = q('#workspaceEditRevision');
    const clone = q('#workspaceCreateRevision');
    const use = q('#workspaceUseRevision');
    if (edit) {
      edit.textContent = '\u7f16\u8f91\u8bbe\u8ba1';
      edit.classList.add('primary');
      edit.title = '\u57fa\u4e8e\u5f53\u524d Revision \u8fdb\u5165\u53ef\u81ea\u52a8\u4fdd\u5b58\u7684\u8bbe\u8ba1\u8349\u7a3f';
    }
    if (use) use.classList.add('hidden');
    let history = q('#workspaceRevisionHistoryV063', actions);
    if (!history && actions) {
      history = document.createElement('button');
      history.id = 'workspaceRevisionHistoryV063';
      history.type = 'button';
      history.textContent = '\u7248\u672c\u5386\u53f2';
      history.addEventListener('click', () => {
        const rail = q('#workspaceCanvas .revision-rail');
        if (!rail) return;
        const open = rail.classList.toggle('revision-rail-open-v063');
        history.setAttribute('aria-expanded', String(open));
        history.textContent = open ? '\u6536\u8d77\u7248\u672c\u5386\u53f2' : '\u7248\u672c\u5386\u53f2';
      });
      actions.append(history);
    }
    const rail = q('#workspaceCanvas .revision-rail');
    if (rail) {
      rail.classList.add('revision-rail-v063');
      if (clone && clone.parentElement !== rail) {
        clone.textContent = '\u76f4\u63a5\u590d\u5236\u5f53\u524d\u7248\u672c';
        clone.classList.remove('primary');
        clone.classList.add('revision-clone-v063');
        rail.append(clone);
      }
    }
  }

  function syncStore() {
    const current = appState();
    const design = current?.workspaceDesign;
    const revision = current?.workspaceRevision;
    if (!design || !revision) return;
    const existing = window.MCSDesignStore?.getState?.() || {};
    window.MCSDesignStore?.setContext?.({
      projectId: current?.activeProjectId || design.project_id || null,
      designId: design.id,
      revisionId: revision.id,
      mode: document.body.classList.contains('design-editing-v062') ? 'edit' : 'read',
      view: existing.view || window.MCSDesignViewer?.state?.view || 'radial',
    }, {source: 'workspace-controller'});
  }

  function refresh() {
    syncStore();
    normalizeHeader();
  }

  ['mcs:workspace-rendered', 'mcs:route-ready', 'mcs:design-state'].forEach(name => window.addEventListener(name, () => requestAnimationFrame(refresh)));
  window.addEventListener('mcs:route-start', () => {
    if (!location.pathname.includes('/designs/')) window.MCSDesignStore?.reset?.({source: 'route-leave'});
  });
  window.MCSDesignWorkbench = {refresh, normalizeHeader, syncStore};
})();
