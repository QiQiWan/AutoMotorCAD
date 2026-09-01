/* V0.65 stable Design Editor controller.
 * Owns draft editing lifecycle, explicit verification, event delegation and route-safe exit.
 * Rendering is delegated to MCSDesignRenderer / MCSDesignParameterInspector.
 */
(() => {
  const $q = (selector, root = document) => root.querySelector(selector);
  const $$q = (selector, root = document) => [...root.querySelectorAll(selector)];
  const safe = value => window.MCSDesignRenderUtils?.safe?.(value) ?? (typeof window.esc === 'function' ? window.esc(value) : String(value ?? ''));
  const revisionLabel = value => window.MCSDesignRenderUtils?.revisionLabel?.(value, 'motor') || String(value ?? '—');

  const wb = {
    revisionId: null,
    data: null,
    values: {},
    baseValues: {},
    changed: new Set(),
    selected: null,
    group: 'topology',
    view: 'radial',
    visualSource: 'design',
    materials: {},
    baseMaterials: {},
    materialDirty: false,
    explicitIds: new Set(),
    saveBusy: false,
    commitKey: null,
    commitFingerprint: null,
    leavePrepared: false,
    windingText: null,
    previewFrame: 0,
    editVersion: 0,
    shellAbort: null,
    slotFillMode: 'auto',
    slotFillEstimate: null,
  };

  const stableValue = value => {
    if (Array.isArray(value)) return value.map(stableValue);
    if (value && typeof value === 'object') {
      const out = {};
      Object.keys(value).sort().forEach(key => { out[key] = stableValue(value[key]); });
      return out;
    }
    return value;
  };
  const objectSnapshot = value => { try { return JSON.stringify(stableValue(value || {})); } catch { return String(value); } };
  const cloneValue = value => typeof structuredClone === 'function' ? structuredClone(value || {}) : JSON.parse(JSON.stringify(value || {}));
  function editableMaterials(data, revision) {
    const saved = revision?.materials || {};
    const effective = data?.materials || saved;
    return {
      ...cloneValue(saved),
      material_database_path: effective.material_database_path ?? saved.material_database_path ?? null,
      component_materials: cloneValue(effective.component_materials || saved.component_materials || {}),
      material_provenance: cloneValue(effective.material_provenance || saved.material_provenance || {}),
      cooling_fluids: cloneValue(saved.cooling_fluids || {}),
    };
  }
  const recordFor = id => (wb.data?.parameters || []).find(row => row.id === id) || null;
  const changedIds = () => [...wb.changed];
  const totalChangeCount = () => wb.changed.size + (wb.materialDirty ? 1 : 0);
  const parameterLabel = id => recordFor(id)?.label || id;
  const sameValue = (a, b) => {
    const na = Number(a), nb = Number(b);
    if (a !== '' && b !== '' && Number.isFinite(na) && Number.isFinite(nb)) return Math.abs(na - nb) <= Math.max(1e-9, Math.abs(nb) * 1e-9);
    return String(a ?? '') === String(b ?? '');
  };
  const slotFillDrivers = new Set(['turns_per_coil','strands_in_hand','slot_width','slot_depth','slot_opening','slot_corner_radius']);
  function motorObjectFor(values) {
    return window.MCSMotorObject?.resolve?.(wb.data, values || {}, wb.materials)
      || window.MCSPMMotorObject?.resolve?.(wb.data, values || {}, wb.materials)
      || null;
  }
  function applySlotFillCoupling(changedId) {
    if (changedId === 'slot_fill_factor') { wb.slotFillMode = 'manual'; wb.slotFillEstimate = null; return false; }
    if (wb.slotFillMode !== 'auto' || !slotFillDrivers.has(changedId) || !recordFor('slot_fill_factor')) return false;
    const estimate = window.MCSDesignDerivedParameters?.estimateSlotFill?.(
      wb.values,
      wb.baseValues,
      {motorObject: motorObjectFor(wb.values), baselineMotorObject: motorObjectFor(wb.baseValues)},
    );
    if (!estimate) return false;
    wb.slotFillEstimate = estimate;
    if (sameValue(wb.values.slot_fill_factor, estimate.value)) return false;
    wb.values.slot_fill_factor = estimate.value;
    refreshChanged('slot_fill_factor');
    const input = $q('[data-workbench-input="slot_fill_factor"]');
    if (input) input.value = String(estimate.value);
    return true;
  }
  function restoreAutomaticSlotFill() {
    wb.slotFillMode = 'auto';
    const driver = slotFillDrivers.has(wb.selected) ? wb.selected : 'turns_per_coil';
    const before = wb.values.slot_fill_factor;
    applySlotFillCoupling(driver);
    if (!sameValue(before, wb.values.slot_fill_factor)) markEdited();
    renderParameters(); renderVisual(); renderSelected(); renderPrecheck(); renderEvidence();
    draftService?.schedule?.({reason: 'slot-fill-auto'});
  }
  function inferSlotFillMode() {
    const estimate = window.MCSDesignDerivedParameters?.estimateSlotFill?.(
      wb.values,
      wb.baseValues,
      {motorObject: motorObjectFor(wb.values), baselineMotorObject: motorObjectFor(wb.baseValues)},
    );
    wb.slotFillEstimate = estimate;
    wb.slotFillMode = estimate && !sameValue(wb.values.slot_fill_factor, estimate.value) ? 'manual' : 'auto';
  }

  function draftPayload() {
    const design = state.workspaceDesign, revision = state.workspaceRevision;
    if (!design || !revision) return null;
    return {
      base_revision_id: revision.id,
      parameters: wb.values,
      materials: wb.materials,
      explicit_parameter_ids: [...new Set([...wb.explicitIds, ...changedIds()])],
      active_view: wb.view,
      notes: `基于 Rev.${revision.revision} 的设计草稿`,
    };
  }

  const draftService = window.MCSDesignDraftService?.create?.({
    getDesignId: () => state.workspaceDesign?.id || null,
    hasChanges: totalChangeCount,
    buildPayload: draftPayload,
    onStateChange: updateDraftStatus,
  });
  const verification = window.MCSDesignPrecheck?.create?.({
    getRevisionId: () => wb.revisionId,
    getDesignId: () => state.workspaceDesign?.id || null,
    getTemplateId: () => wb.data?.revision?.template_id,
    getParameters: () => wb.values,
    getChangedIds: changedIds,
    getMaterials: () => wb.materials,
    getExplicitIds: () => [...new Set([...(state.workspaceRevision?.explicit_parameter_ids || []), ...changedIds()])],
    getEditVersion: () => wb.editVersion,
    getDraft: () => draftService?.state?.draft || null,
    getEditorTransaction: () => draftService?.state?.draft?.editor_transaction || null,
    ensurePersisted: async () => {
      const currentDraft = draftService?.state?.draft || null;
      const tx = currentDraft?.editor_transaction || null;
      // Native check needs a persisted editor transaction even when the user has
      // made no value changes. A legacy/clean draft therefore gets a forced PUT
      // that materializes transaction_hash + intent_hash without creating a new
      // immutable motor revision.
      if (!currentDraft || !tx?.transaction_hash || !tx?.intent_hash) {
        await draftService?.persist?.({silent: true, reason: 'native-reconciliation-bootstrap', force: true});
      } else if (totalChangeCount() || draftService?.hasUnpersistedChanges?.()) {
        await draftService?.flush?.({silent: true, reason: 'native-reconciliation'});
      }
      return draftService?.state?.draft || null;
    },
    onNativeResult: result => {
      if (result?.draft) draftService?.acceptServerState?.(result.draft);
      renderTransactionState(); renderVisual();
    },
    onStateChange: () => {
      renderPrecheck();
      if (wb.view === 'native' || wb.view === 'evidence') renderVisual();
    },
  });

  function draftConflict() { return draftService?.state?.conflict || null; }
  function refreshChanged(id) {
    const row = recordFor(id); if (!row) return;
    if (sameValue(wb.values[id], row.value)) wb.changed.delete(id); else wb.changed.add(id);
  }
  function conflictRevisionLabel(conflict = draftConflict()) {
    const id = conflict?.base_revision_id || conflict;
    const row = (state.workspaceDesign?.revisions || []).find(item => item.id === id);
    return row?.revision ? revisionLabel(row.revision) : (window.MCS_I18N?.t?.('另一个电机版本','Another motor revision')||'另一个电机版本');
  }
  function markEdited() {
    wb.editVersion += 1;
    // Any new local intent must use a new immutable commit identity. A key is
    // deliberately retained across a failed/unknown commit response so the exact
    // same request can be replayed safely.
    wb.commitKey = null; wb.commitFingerprint = null;
    wb.visualSource = 'design';
    verification?.invalidateNative?.();
    if (!totalChangeCount()) verification?.begin?.(wb.data?.precheck || null);
  }

  function draftStatusText() {
    const state = draftService?.snapshot?.() || {};
    if (state.busy) return '正在保存草稿…';
    if (state.conflict?.kind === 'stale_same_revision') return '草稿已在另一个窗口更新';
    if (state.conflict) return '其他版本存在草稿';
    if (state.lastError) return '草稿保存失败 · 需要处理';
    if (state.lastSavedAt) return `草稿已保存 ${new Date(state.lastSavedAt).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`;
    return totalChangeCount() ? '草稿等待自动保存' : '基于已保存版本';
  }

  function transactionProjection() {
    const draftState = draftService?.snapshot?.() || {};
    const draft = draftState.draft || null;
    const tx = draft?.editor_transaction || null;
    const native = tx?.native_reconciliation || {};
    const check = verification?.snapshot?.() || {};
    const unsaved = Boolean(draftState.busy || draftState.queued || draftState.lastError || (totalChangeCount() && !draftState.lastSavedAt));
    const localState = totalChangeCount() ? (unsaved ? '已修改未保存' : '草稿已保存') : '未修改';
    const localTone = draftState.lastError ? 'error' : unsaved ? 'dirty' : totalChangeCount() ? 'saved' : 'clean';
    const nativeStale = Boolean(check.nativeStale || (unsaved && (native.status && native.status !== 'UNCHECKED')));
    const nativeStatus = nativeStale ? 'STALE' : String(native.status || 'UNCHECKED').toUpperCase();
    const nativeLabel = nativeStale ? 'Native Evidence 已过期' : (native.label || ({CURRENT:'已应用到 Motor-CAD',DRIFT:'Native 已漂移',PARTIAL:'Native 证据不完整',FAILED:'Native 检查失败',UNCHECKED:'待 Motor-CAD 检查'})[nativeStatus] || '待 Motor-CAD 检查');
    const nativeTone = nativeStatus === 'CURRENT' ? 'current' : nativeStatus === 'DRIFT' || nativeStatus === 'FAILED' ? 'error' : nativeStatus === 'STALE' ? 'stale' : 'pending';
    return {draftState,draft,tx,native,localState,localTone,nativeStatus,nativeLabel,nativeTone};
  }

  function editorVisualizationReconciliation() {
    const p = transactionProjection(), base = wb.data?.visualization_reconciliation || {};
    if (p.nativeStatus === 'STALE') return {...base, status:'STALE_NATIVE_EVIDENCE', default_source:'design', native_render_allowed:false, native_authoritative:false, compare_allowed:false, reason:'当前草稿在最近一次 Motor-CAD 检查后已经变化；旧原生投影不会套用到新设计。'};
    if (p.native?.native_preview_projection) return window.MCSDesignRenderer?.runtimeReconciliation?.(wb.data, p.native) || base;
    return base;
  }

  function renderTransactionState() {
    const box = $q('#editorTransactionStateV088D'); if (!box) return;
    const p = transactionProjection(), tx = p.tx || {};
    const txLabel = tx.transaction_id ? String(tx.transaction_id).replace(/^EDT-/, '').slice(-8) : '等待首次草稿保存';
    box.innerHTML = `<div class="editor-transaction-cell-v088d"><span>编辑事务</span><b>${safe(txLabel)}</b><small>${tx.intent_version ? `Intent v${safe(tx.intent_version)}` : '几何 / 绕组 / 材料共享'}</small></div><div class="editor-transaction-cell-v088d ${safe(p.localTone)}"><span>设计状态</span><b>${safe(p.localState)}</b><small>${p.draftState.lastSavedAt ? `最近保存 ${safe(new Date(p.draftState.lastSavedAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}))}` : '自动保存草稿'}</small></div><div class="editor-transaction-cell-v088d ${safe(p.nativeTone)}"><span>Motor-CAD 状态</span><b>${safe(p.nativeLabel)}</b><small>${p.nativeStatus === 'CURRENT' && p.native.native_model_design_state_hash ? `状态 ${safe(String(p.native.native_model_design_state_hash).slice(0,10))}` : p.nativeStatus === 'STALE' ? '设计变化后必须重新检查' : '检查结果对应当前设计'}</small></div><div class="editor-transaction-cell-v088d readonly"><span>起始模板</span><b>只读</b><small>保存后形成新的电机版本</small></div>`;
    window.MCSDesignStore?.patch?.({
      transactionHash: tx.transaction_hash || null, intentHash: tx.intent_hash || null,
      nativeStatus: p.nativeStatus, nativeEvidenceCurrent: p.nativeStatus === 'CURRENT',
    }, {source: 'editor-transaction'});
  }

  function renderConflictBanner() {
    const box = $q('#workbenchDraftConflictV065');
    if (!box) return;
    const conflict = draftConflict();
    const workbench = $q('.model-workbench-v024');
    workbench?.classList.toggle('draft-conflict-locked-v062', Boolean(conflict));
    if (!conflict) { box.innerHTML = ''; box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    if (conflict.kind === 'stale_same_revision') {
      box.innerHTML = `<div class="draft-conflict-banner-v062 draft-conflict-banner-v065"><div><b>此草稿已在另一个窗口更新</b><span>服务器草稿版本已变化。当前窗口的未保存修改不会继续覆盖最新草稿，请重新加载后再编辑。</span></div><div class="actions"><button type="button" data-reload-stale-draft-v065>重新加载最新草稿</button></div></div>`;
      return;
    }
    box.innerHTML = `<div class="draft-conflict-banner-v062"><div><b>该电机已有未冻结草稿</b><span>现有草稿基于 ${safe(conflictRevisionLabel(conflict))}。为避免覆盖另一版本的设计修改，请先恢复现有草稿或明确放弃它。</span></div><div class="actions"><button type="button" data-open-existing-draft-v062>打开现有草稿</button><button type="button" class="danger-quiet" data-replace-existing-draft-v062>放弃现有草稿并编辑当前版本</button></div></div>`;
  }

  function updateDraftStatus() {
    const status = draftService?.snapshot?.() || {};
    const node = $q('#workbenchDraftStatusV062');
    if (node) {
      node.textContent = draftStatusText();
      node.dataset.state = status.conflict ? 'conflict' : status.lastError ? 'error' : status.busy ? 'saving' : status.lastSavedAt ? 'saved' : totalChangeCount() ? 'dirty' : 'clean';
    }
    const retry = $q('#workbenchDraftRetryV065');
    if (retry) retry.classList.toggle('hidden', !status.lastError || Boolean(status.conflict));
    renderConflictBanner();
    const storeStatus = status.conflict ? 'conflict' : status.lastError ? 'error' : status.busy ? 'saving' : status.lastSavedAt ? 'saved' : totalChangeCount() ? 'dirty' : 'saved';
    window.MCSDesignStore?.patch?.({draftStatus: storeStatus, dirtyCount: totalChangeCount()}, {source: 'draft-status'});
    renderTransactionState();
  }

  function renderShell() {
    const data = wb.data, revision = data?.revision;
    const canvas = $q('#workspaceCanvas'), inspector = $q('#workspaceInspector');
    if (!canvas || !revision) return;
    document.body.classList.add('design-editing-v062');
    canvas.innerHTML = `<div class="workspace-object-header model-workbench-header-v024 workbench-draft-header-v062"><div><span class="eyebrow">电机设计草稿</span><h2>${safe(revision.design_name)} · ${safe(revisionLabel(revision.revision))}</h2><p>几何、绕组和材料修改会自动保留为草稿；确认后点击“保存设计”。</p><div class="draft-status-line-v065"><span id="workbenchDraftStatusV062" class="draft-save-status-v062">${safe(draftStatusText())}</span><button id="workbenchDraftRetryV065" type="button" class="link-button-v065 hidden">重试保存</button></div></div><div class="actions"><button id="workbenchDiscardV062" type="button" class="danger-quiet">放弃草稿</button><button id="workbenchCancelV024" type="button">退出编辑（保留草稿）</button><button id="workbenchSaveV024" class="primary" type="button">保存设计</button></div></div>
    <div id="workbenchDraftConflictV065" class="hidden"></div>
    <div id="editorTransactionStateV088D" class="editor-transaction-state-v088d" aria-label="设计事务与 Motor-CAD 状态"></div>
    <div class="editor-transaction-rule-v088d">几何、绕组和材料属于同一份未保存设计；切换步骤不会创建新的设计分支。保存后系统会自动关联当前 Motor-CAD 检查证据。</div>
    <div class="model-workbench-v024 ${draftConflict() ? 'draft-conflict-locked-v062' : ''}">
      <aside class="workbench-tree-v024">
        <div class="workbench-search-v024"><label for="workbenchSearchV024">设计参数</label><input id="workbenchSearchV024" placeholder="搜索参数名称或部件"><div class="parameter-coverage-v066"><span>结构化核心参数用于高频设计；完整参数来自当前 Motor-CAD 版本的 Automation Parameter Names。</span><button id="workbenchOpenParameterCatalogV066" type="button">高级：全部 Motor-CAD 参数</button></div></div>
        <div id="workbenchGroupsV024" class="workbench-groups-v024"></div>
        <div class="workbench-region-box-v024"><span class="eyebrow">模型区域</span><div id="workbenchRegionsV024"></div></div>
      </aside>
      <main class="workbench-main-v024">
        <section class="workbench-visual-v024">
          <div class="workbench-navigation-v062"><div id="workbenchStageNavV062" class="workbench-stage-nav-v062" aria-label="设计草稿步骤"></div><div id="workbenchSubviewNavV062" class="workbench-subview-nav-v062" aria-label="当前草稿视图"></div></div>
          <div id="workbenchVisualStageV024" class="workbench-visual-stage-v024"></div>
        </section>
        <section class="workbench-parameter-editor-v024">
          <div class="workbench-editor-head-v024"><div><span class="eyebrow">参数编辑</span><h3 id="workbenchGroupTitleV024"></h3></div><div class="actions"><button id="restoreGroupPreviousV024" type="button">本组恢复上一可行值</button><button id="restoreGroupTemplateV024" type="button">本组恢复模板基线</button></div></div>
          <div id="workbenchParameterRowsV024" class="workbench-parameter-rows-v024"></div>
          <footer class="workbench-save-footer-v088"><div><b>完成本组修改后保存</b><small>保存会更新当前设计，并自动保留一条历史快照；不会写回 Motor-CAD 起始模板。</small></div><button id="workbenchQuickSaveV088" type="button" class="primary">保存修改并返回参数总览</button></footer>
        </section>
      </main>
      <aside class="workbench-diagnostics-v024">
        <section id="workbenchStatusV024" class="workbench-diagnostic-card-v024"></section>
        <section id="workbenchSelectedV024" class="workbench-diagnostic-card-v024"></section>
        <section id="workbenchEvidenceV024" class="workbench-diagnostic-card-v024"></section>
      </aside>
    </div>`;
    if (inspector) inspector.innerHTML = `<div class="inspector-block"><span class="eyebrow">当前电机</span><h3>${safe(revision.design_name)}</h3><div class="property-grid"><span>设计版本</span><b>版本 ${safe(revision.revision)}</b><span>草稿修改</span><b id="workbenchChangeCountV024">0 项</b><span>起始模板</span><b>${safe(revision.template_id)}</b><span>验证状态</span><b id="workbenchInspectorStatusV024">—</b></div><div class="inspector-note">参数示意随输入实时更新；Studio 设计检查和 Motor-CAD 原生检查只在明确触发时运行。</div></div>`;
    renderGroups(); renderRegions(); renderParameters(); renderVisual(); renderSelected(); renderEvidence(); renderPrecheck(); bindShell(); updateDraftStatus(); renderTransactionState();
  }

  function renderGroups(filter = '') {
    const box = $q('#workbenchGroupsV024'); if (!box) return;
    box.innerHTML = window.MCSDesignParameterInspector?.editorGroupButtons?.({data: wb.data, group: wb.group, changed: wb.changed, filter}) || '';
  }
  function renderRegions() {
    const box = $q('#workbenchRegionsV024'); if (!box) return;
    box.innerHTML = window.MCSDesignParameterInspector?.editorRegionButtons?.({data: wb.data}) || '';
  }
  function renderParameters() {
    const box = $q('#workbenchParameterRowsV024'); if (!box) return;
    const group = (wb.data?.groups || []).find(row => row.id === wb.group), title = $q('#workbenchGroupTitleV024');
    if (title) title.textContent = group?.label || wb.group;
    box.innerHTML = window.MCSDesignParameterInspector?.editorParameterRows?.({data: wb.data, group: wb.group, values: wb.values, changed: wb.changed, selected: wb.selected}) || '<div class="workspace-empty compact">当前分组没有可编辑设计参数。</div>';
    const fillRow = box.querySelector('[data-workbench-param-row="slot_fill_factor"]');
    if (fillRow) fillRow.insertAdjacentHTML('afterbegin', `<div class="slot-fill-coupling-v089g41 ${wb.slotFillMode}"><b>${wb.slotFillMode === 'auto' ? '自动联动' : '手动值'}</b><span>${wb.slotFillMode === 'auto' ? '按固定线径/绝缘假设，随匝数与槽面积更新；Motor-CAD 回读为最终值。' : '当前槽满率已手动锁定，不再随匝数变化。'}</span>${wb.slotFillMode === 'manual' ? '<button type="button" data-workbench-slot-fill-auto>恢复自动联动</button>' : ''}</div>`);
    updateChangeCount();
  }
  function updateChangeCount() {
    const count = totalChangeCount(), parts = [];
    if (wb.changed.size) parts.push(`${wb.changed.size} 参数`);
    if (wb.materialDirty) parts.push('材料');
    const node = $q('#workbenchChangeCountV024'); if (node) node.textContent = count ? parts.join(' + ') : '0 项';
    [$q('#workbenchSaveV024'), $q('#workbenchQuickSaveV088')].filter(Boolean).forEach(save => { save.disabled = wb.saveBusy || count === 0 || Boolean(draftConflict()); });
    window.MCSDesignStore?.patch?.({dirtyCount: count}, {source: 'editor-dirty'});
    updateDraftStatus();
  }

  function workbenchStageForView(view) { return window.MCSDesignNavigation?.stageForView?.(view) || 'geometry'; }
  function renderWorkbenchNavigation() {
    const stageBox = $q('#workbenchStageNavV062'), subBox = $q('#workbenchSubviewNavV062'); if (!stageBox || !subBox) return;
    if (window.MCSDesignNavigation?.render) window.MCSDesignNavigation.render({stageBox, subBox, data: wb.data, view: wb.view, mode: 'edit', variant: 'workbench'});
    else { stageBox.textContent = workbenchStageForView(wb.view); subBox.textContent = ''; }
  }
  function workbenchDefaultViewForStage(stage) { return window.MCSDesignNavigation?.defaultViewForStage?.(stage, wb.data, {mode: 'edit'}) || 'radial'; }

  function renderVisual() {
    const box = $q('#workbenchVisualStageV024'); if (!box || !wb.data) return;
    window.MCSDesignStore?.setContext?.({projectId: state.activeProjectId || null, designId: state.workspaceDesign?.id || null, revisionId: wb.revisionId, mode: 'edit', view: wb.view, selectedParameter: wb.selected, data: wb.data, dirtyCount: totalChangeCount()}, {source: 'editor-render'});
    renderWorkbenchNavigation();
    $$q('[data-workbench-view]').forEach(button => button.classList.toggle('active', button.dataset.workbenchView === wb.view));
    const check = verification?.snapshot?.() || {};
    const reconciliation = editorVisualizationReconciliation();
    const effectiveSource = window.MCSDesignRenderer?.resolveVisualSource?.(reconciliation, wb.visualSource, 'edit') || 'design';
    if (wb.visualSource !== 'design' && effectiveSource === 'design' && !reconciliation.native_render_allowed) wb.visualSource = 'design';
    const draftData = {...wb.data, effective_parameters: wb.values, materials: wb.materials, draft_validation: check, editable: true, visualization_reconciliation: reconciliation};
    const ctx = {data: draftData, values: wb.values, materials: wb.materials, precheck: check.precheckCurrent ? check.precheck : null, selected: wb.selected, editable: true, visualSource: effectiveSource, visualizationReconciliation: reconciliation};
    const auxiliary = window.MCSDesignRenderer?.renderAuxiliaryView?.(wb.view, draftData);
    const toolbar = ['radial','axial','winding','slot','materials'].includes(wb.view) ? (window.MCSDesignRenderer?.toolbar?.(draftData,{source:wb.visualSource,mode:'edit',reconciliation}) || '') : '';
    const viewHtml = auxiliary ?? window.MCSDesignRenderer?.renderWorkbenchView?.(wb.view, ctx);
    box.innerHTML = toolbar + (viewHtml ?? '<div class="native-empty-v031">当前设计视图不可用。</div>');
    const next = window.MCSDesignNavigation?.next?.(wb.view, wb.data, {mode: 'edit'});
    if (next) box.insertAdjacentHTML('beforeend', `<div class="design-next-step-v063 design-next-step-v064 design-next-step-v065"><div><span>编辑流程</span><b>${safe(next.label)}</b><small>${next.target === 'commit' ? '保存前可先运行设计验证；草稿会持续自动保存。' : '草稿会自动保存，可在各设计阶段之间直接切换。'}</small></div><button type="button" class="primary" data-workbench-next-v063="${safe(next.target)}">${safe(next.label)} →</button></div>`);
    highlightSelectedRegion();
  }

  function renderSelected() {
    const box = $q('#workbenchSelectedV024'); if (!box) return;
    box.innerHTML = window.MCSDesignParameterInspector?.editorSelectedCard?.({data: wb.data, values: wb.values, selected: wb.selected}) || '<span class="eyebrow">参数联动</span><h3>选择一个参数</h3>';
  }

  function currentPrecheck() {
    const check = verification?.snapshot?.() || {};
    return check.precheckCurrent ? check.precheck : null;
  }
  function renderPrecheck() {
    const box = $q('#workbenchStatusV024'); if (!box || !wb.data) return;
    const check = verification?.snapshot?.() || {};
    const inspector = $q('#workbenchInspectorStatusV024');
    if (check.precheckBusy) {
      box.className = 'workbench-diagnostic-card-v024 workbench-status-warning-v024';
      box.innerHTML = '<div class="diagnostic-title-v024"><div><span class="eyebrow">设计验证</span><h3>正在执行 Studio 设计检查…</h3></div><span class="badge warn">检查中</span></div><p>检查几何包含关系、槽极/相/支路约束及当前设计参数一致性。</p>';
      if (inspector) inspector.textContent = '检查中';
      return;
    }
    if (check.lastError && !check.precheckCurrent) {
      box.className = 'workbench-diagnostic-card-v024 workbench-status-blocking-v024';
      box.innerHTML = `<div class="diagnostic-title-v024"><div><span class="eyebrow">设计验证</span><h3>最近一次检查未完成</h3></div><span class="badge error">失败</span></div><p>${safe(check.lastError.message || check.lastError)}</p><div class="verification-actions-v065"><button type="button" data-workbench-run-studio-check-v065>重新运行 Studio 检查</button></div>`;
      if (inspector) inspector.textContent = '检查失败';
      return;
    }
    const precheck = currentPrecheck();
    if (!precheck) {
      box.className = 'workbench-diagnostic-card-v024 workbench-status-warning-v024';
      box.innerHTML = `<div class="diagnostic-title-v024"><div><span class="eyebrow">设计验证</span><h3>${totalChangeCount() ? '当前草稿尚未验证' : '等待设计检查'}</h3></div><span class="badge warn">待验证</span></div><p>参数调整阶段不会自动启动网络检查。完成一轮设计修改后，在此显式运行 Studio 检查。</p><div class="verification-actions-v065"><button type="button" data-workbench-run-studio-check-v065>运行 Studio 设计检查</button></div>`;
      if (inspector) inspector.textContent = '待验证';
      return;
    }
    const blocks = (precheck.issues || []).filter(issue => issue.severity === 'BLOCKING');
    const warns = (precheck.issues || []).filter(issue => issue.severity !== 'BLOCKING');
    const tone = blocks.length ? 'blocking' : warns.length ? 'warning' : 'pass';
    box.className = `workbench-diagnostic-card-v024 workbench-status-${tone}-v024`;
    box.innerHTML = `<div class="diagnostic-title-v024"><div><span class="eyebrow">当前草稿 · Studio 检查</span><h3>${blocks.length ? '存在需要修复的设计问题' : warns.length ? '通过，但有工程提示' : '当前草稿通过 Studio 设计检查'}</h3></div><span class="badge ${blocks.length ? 'error' : warns.length ? 'warn' : 'ok'}">${blocks.length ? `${blocks.length} 项阻断` : warns.length ? `${warns.length} 项提示` : '通过'}</span></div>${(precheck.issues || []).length ? `<div class="workbench-issue-list-v024">${(precheck.issues || []).map((issue, index) => `<button type="button" data-workbench-issue="${index}" class="${issue.severity === 'BLOCKING' ? 'blocking' : 'warning'}"><b>${safe(issue.message || issue.code)}</b><small>${(issue.parameter_ids || []).map(parameterLabel).join(' / ') || '电机模型'}</small></button>`).join('')}</div>` : '<p>当前版本未发现确定性几何、绕组和参数关系问题。</p>'}<div class="verification-actions-v065"><button type="button" data-workbench-run-studio-check-v065>重新运行 Studio 检查</button><button type="button" class="primary" data-workbench-run-native-check-v065 ${blocks.length || check.nativeBusy ? 'disabled' : ''}>${check.nativeBusy ? 'Motor-CAD 检查中…' : '运行 Motor-CAD 原生检查'}</button></div>`;
    if (inspector) inspector.textContent = blocks.length ? 'BLOCKING' : warns.length ? 'WARNING' : check.nativeCurrent && check.nativeCheck?.status === 'PASS' ? 'NATIVE PASS' : 'STUDIO PASS';
  }

  function nativeFailureSummary(result) {
    const typedFaults = Array.isArray(result?.native_fault_tree) ? result.native_fault_tree : [];
    const repairPlan = result?.native_repair_plan || {};
    if (typedFaults.length) {
      const root = typedFaults[0] || {}, actions = Array.isArray(repairPlan.actions) ? repairPlan.actions.filter(action => action.fault_id === root.fault_id) : [];
      const parameters = (root.parameter_ids || []).filter(id => recordFor(id));
      const components = root.component_ids || [];
      const autoCount = (repairPlan.auto_safe_action_ids || []).length;
      const manualLabels = actions.filter(action => action.safety !== 'AUTO_SAFE').slice(0, 3).map(action => action.label).filter(Boolean);
      return `<div class="native-failure-summary-v024 native-fault-tree-v088c"><div class="native-root-cause-v088"><div class="native-fault-code-v088c"><b>首要故障 · ${safe(root.code || 'NATIVE_VALIDATION')}</b><span>${safe(root.domain || 'native_model')} · ${safe(root.stage || 'post_native_validation')}</span></div><span>${safe(root.message || 'Motor-CAD 原生模型检查未通过')}</span>${root.repair_hint ? `<small>${safe(root.repair_hint)}</small>` : ''}</div>${parameters.length ? `<div class="native-fault-locators-v088c">${parameters.map(id => `<button type="button" data-workbench-select="${safe(id)}">定位 ${safe(parameterLabel(id))}</button>`).join('')}</div>` : ''}${components.length ? `<div class="native-fault-components-v088c"><small>涉及部件：${safe(components.join(' / '))}</small></div>` : ''}${autoCount ? `<div class="native-repair-callout-v088c"><div><b>检测到 ${autoCount} 项安全同步动作</b><small>只同步当前 Motor-CAD 会话，不改变已保存设计。</small></div><button type="button" class="primary" data-workbench-native-safe-repair-v088c>安全修复并重新检查</button></div>` : manualLabels.length ? `<div class="native-repair-callout-v088c manual"><div><b>需要工程师确认</b><small>${safe(manualLabels.join('；'))}</small></div></div>` : ''}</div>`;
    }
    const geometry = result?.geometry?.details || result?.geometry || {}, winding = result?.winding?.details || result?.winding || {};
    const root = result?.root_cause || (result?.checks || []).find(row => String(row?.status || '').toUpperCase() === 'FAIL') || {};
    const details = root?.details || {};
    const rootId = String(root?.id || '').toLowerCase();
    const causes = [...(winding.causes || []), ...((geometry.geometry_diagnosis || {}).causes || [])];
    const codes = [...(winding.codes || []), ...((geometry.geometry_diagnosis || {}).codes || [])];
    const binding = firstNativeBinding(codes);
    let stage = rootId === 'materials' ? '材料绑定' : rootId === 'winding' ? '绕组检查' : rootId === 'geometry' ? '几何检查' : rootId === 'parameter_roundtrip' ? '参数回读' : '模型检查';
    let primary = causes[0] || root?.message || result?.geometry?.message || result?.winding?.message || 'Motor-CAD 返回模型不可行';
    let action = '';
    let technical = '';
    if (rootId === 'materials' || /set_component_material|组件材料设置失败|material binding/i.test(primary)) {
      const component = details.component || '电机部件', material = details.material || '所选材料';
      primary = `${component} → ${material} 未完成 Motor-CAD 材料回读`;
      action = details.source_kind === 'template_mtt'
        ? '该材料来自模板继承；Studio 会沿用模板原生绑定，不再重复写入。若仍出现此错误，请重新运行检查并确认当前模板/数据库版本。'
        : '请确认材料存在于当前 Motor-CAD 数据库；若材料名称正确，检查下方组件候选别名与 Motor-CAD 返回错误。';
      technical = [...(details.candidate_targets || []).map(x => `候选组件：${x}`), ...(details.errors || []).slice(0, 2)].join(' · ');
    } else if (rootId === 'winding') action = '检查槽数/相数/并联支路、槽满率及线圈连接。下方可直接定位已绑定的绕组参数。';
    else if (rootId === 'geometry') action = '根据 Motor-CAD 返回的几何原因定位槽口、齿宽、槽深、气隙或相交部位，再运行一次原生检查。';
    else if (rootId === 'parameter_roundtrip') action = '恢复失败参数到模板值后逐项修改，并确认 Motor-CAD 2026R1 参数映射与单位回读一致。';
    return `<div class="native-failure-summary-v024"><div class="native-root-cause-v088"><b>失败阶段：${safe(stage)}</b><span>${safe(primary)}</span>${action ? `<small>${safe(action)}</small>` : ''}${technical ? `<code>${safe(technical)}</code>` : ''}</div>${binding.length ? `<div>${binding.map(id => `<button type="button" data-workbench-select="${safe(id)}">定位 ${safe(parameterLabel(id))}</button>`).join('')}</div>` : ''}</div>`;
  }
  function firstNativeBinding(codes) {
    for (const code of codes || []) {
      const ids = wb.data?.issue_bindings?.[code]?.parameter_ids || [];
      if (ids.length) return ids.filter(id => recordFor(id));
    }
    return [];
  }
  function renderEvidence() {
    const box = $q('#workbenchEvidenceV024'); if (!box || !wb.data) return;
    const evidence = wb.data.native_evidence, check = verification?.snapshot?.() || {}, native = check.nativeCurrent ? check.nativeCheck : null, previous = wb.data.previous_feasible;
    let nativePart = '';
    if (check.nativeBusy) nativePart = '<div class="native-check-result-v024 history"><b>Motor-CAD 原生检查正在运行…</b><small>检查对象已经冻结为当前持久化 Editor Transaction；检查期间的新编辑不会继承本次结果。</small></div>';
    else if (check.nativeStale && check.nativeCheck) {
      nativePart = '<div class="native-check-result-v024 fail native-stale-v088d"><b>Native Evidence 已过期</b><small>最近一次 Motor-CAD 结果对应旧的设计意图。保存当前草稿后重新运行原生检查。</small></div>';
    } else if (native) {
      const pass = native.status === 'PASS';
      nativePart = `<div class="native-check-result-v024 ${pass ? 'pass' : 'fail'}"><b>${pass ? '✓ 当前草稿已通过 Motor-CAD 原生材料、几何与绕组检查' : '当前草稿未通过 Motor-CAD 原生模型检查'}</b>${pass ? '' : nativeFailureSummary(native)}</div>`;
    } else {
      const txNative = transactionProjection().native || {};
      if (txNative.status && txNative.status !== 'UNCHECKED') nativePart = `<div class="native-check-result-v024 ${txNative.status === 'CURRENT' ? 'pass' : 'history'}"><b>${safe(txNative.label || txNative.status)}</b><small>该状态由服务器端 Editor Transaction 与 Native Evidence Hash 协调得到。</small></div>`;
      else if (evidence) nativePart = `<div class="native-check-result-v024 history"><b>冻结版本最近一次模型检查：${['SUCCEEDED', 'COMPLETED'].includes(evidence.execution_status || evidence.task_status) ? '已完成' : '需要关注'}</b><small>${safe(evidence.finished_at || '')}</small></div>`;
      else nativePart = '<p class="hint">当前设计版本还没有 Motor-CAD 模型检查记录。</p>';
    }
    box.innerHTML = `<span class="eyebrow">模型检查记录</span><h3>${previous?.source === 'revision' ? `上一可行版本 ${safe(previous.revision)}` : previous ? '起始模板可行' : '等待首次检查'}</h3>${nativePart}<div class="evidence-rule-v024"><b>验证顺序</b><span>Studio 参数关系 → Motor-CAD 材料、几何与绕组 → 分析工况检查 → 正式计算 → 结果验证</span></div>`;
  }

  function highlightSelectedRegion() {
    const row = recordFor(wb.selected), regions = row?.dependency?.region_ids || [], stage = $q('#workbenchVisualStageV024');
    if (!stage) return;
    $$q('[data-schematic-part]', stage).forEach(element => {
      const tags = String(element.dataset.schematicPart || '').split(/\s+/);
      element.classList.toggle('workbench-part-selected-v024', regions.some(region => tags.includes(region)));
    });
  }
  function selectParameter(id, {switchGroup = true} = {}) {
    const row = recordFor(id); if (!row) return;
    wb.selected = id;
    window.MCSDesignStore?.selectParameter?.(id, {source: 'editor-select'});
    if (switchGroup && row.category !== wb.group) { wb.group = row.category; renderGroups($q('#workbenchSearchV024')?.value || ''); renderParameters(); }
    else $$q('[data-workbench-param-row]').forEach(element => element.classList.toggle('selected', element.dataset.workbenchParamRow === id));
    renderSelected(); highlightSelectedRegion();
    const input = $q(`[data-workbench-input="${CSS.escape(id)}"]`); input?.focus({preventScroll: true}); input?.closest('[data-workbench-param-row]')?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }
  function selectRegion(regionId) {
    const ids = (wb.data?.regions?.[regionId]?.parameter_ids || []).filter(id => recordFor(id));
    if (ids.length) selectParameter(ids[0]);
  }
  function setValue(id, value, {render = true} = {}) {
    if (draftConflict()) return;
    const row = recordFor(id); if (!row) return;
    let next = value;
    if (row.type === 'integer') next = Math.round(Number(value)); else if (typeof value === 'string' && value.trim() !== '') next = Number(value);
    if (!Number.isFinite(Number(next))) return;
    const before = wb.values[id];
    wb.values[id] = Number(next); refreshChanged(id);
    if (!sameValue(before, wb.values[id])) markEdited();
    applySlotFillCoupling(id);
    const input = $q(`[data-workbench-input="${CSS.escape(id)}"]`); if (input && String(input.value) !== String(next)) input.value = String(next);
    if (render) { renderParameters(); renderVisual(); renderSelected(); renderPrecheck(); renderEvidence(); draftService?.schedule?.({reason: 'parameter-edit'}); }
  }
  function restoreGroup(source) {
    if (draftConflict()) return;
    const rows = (wb.data?.parameters || []).filter(row => row.category === wb.group);
    rows.forEach(row => { const value = source === 'previous' ? row.previous_feasible_value : row.template_default; if (value !== undefined) setValue(row.id, value, {render: false}); });
    renderParameters(); renderVisual(); renderSelected(); renderPrecheck(); renderEvidence(); draftService?.schedule?.({reason: 'group-restore'});
  }

  async function runStudioCheck() {
    try {
      const result = await verification?.runStudio?.();
      if (!result) return;
      const blocks = (result.issues || []).filter(issue => issue.severity === 'BLOCKING').length;
      toast(blocks ? `Studio 设计检查发现 ${blocks} 项阻断。` : '当前草稿已完成 Studio 设计检查。', blocks ? 'WARNING' : 'SUCCESS', 5000);
    } catch (error) { toast(`Studio 设计检查失败：${error.message}`, 'ERROR', 7000); }
    finally { renderPrecheck(); renderEvidence(); renderVisual(); }
  }
  async function runNativeCheck({repairPolicy = 'suggest'} = {}) {
    try {
      const result = await verification?.runNative?.({repairPolicy});
      if (!result) return;
      const attempts = result.native_repair_attempts || [], lastAttempt = attempts[attempts.length - 1];
      if (repairPolicy === 'safe_auto' && lastAttempt) {
        toast(lastAttempt.outcome === 'REPAIRED' ? '安全同步已完成，Motor-CAD 原生模型已重新验证。' : `安全同步结果：${lastAttempt.outcome}。请查看首要故障。`, lastAttempt.outcome === 'REPAIRED' ? 'SUCCESS' : 'WARNING', 8000);
      } else {
        toast(result.status === 'PASS' ? '当前草稿已通过 Motor-CAD 原生材料、几何与绕组检查。' : 'Motor-CAD 原生模型检查未通过；已显示首要故障和修复动作。', result.status === 'PASS' ? 'SUCCESS' : 'ERROR', 7000);
      }
    } catch (error) {
      if (error?.code === 'STUDIO_PRECHECK_BLOCKED') toast(error.message, 'WARNING', 6500);
      else toast(`Motor-CAD 原生检查失败：${error.message}`, 'ERROR', 8000);
    } finally { renderPrecheck(); renderEvidence(); renderVisual(); renderTransactionState(); }
  }

  function activeAnalysisForDesign() {
    const design = state.workspaceDesign; if (!design) return null;
    const active=window.MCSUnifiedAnalysis?.state?.active||null;const revisionIds=new Set((design.revisions||[]).map(row=>String(row.id)));return active&&revisionIds.has(String(active.design_revision_id||''))?active:null;
  }
  async function revisionNotesSheet() {
    const candidate = activeAnalysisForDesign();
    if (!window.StudioDialog?.sheet) return {notes: `基于 Rev.${state.workspaceRevision?.revision} 的设计工作台修改`, analysis_definition_id: null};
    const check = verification?.snapshot?.() || {};
    const verificationNote = check.nativeCurrent && check.nativeCheck?.status === 'PASS' ? '当前草稿已通过 Motor-CAD 原生检查。' : check.precheckCurrent ? '当前草稿已完成 Studio 设计检查；Motor-CAD 原生检查尚未取得 PASS。' : '当前草稿尚未执行设计验证；仍可保存为中间电机版本。';
    const value = await StudioDialog.sheet({
      title: '保存新的电机版本',
      html: `<div class="step-help-sheet"><p>将当前 ${totalChangeCount()} 组修改保存为新的电机版本。已有计算任务和其他分析配置继续使用原版本。</p><p class="revision-verification-note-v065">${safe(verificationNote)}</p>${candidate ? `<label class="revision-analysis-link-v062"><input id="workbenchLinkAnalysisV062" type="checkbox" checked><span><b>让当前分析案例采用新版本</b><small>${safe(candidate.name || candidate.id)} 将切换到新电机版本；其他分析配置保持原版本。</small></span></label>` : '<p class="hint">当前没有与此电机匹配的活动分析案例；保存设计不会改变任何分析案例的版本引用。</p>'}<label>版本说明<textarea id="workbenchRevisionNotesV024" rows="4" placeholder="例如：调整槽口和齿宽以降低槽满率风险"></textarea></label></div>`,
      actions: [
        {label: '取消', value: null},
        {label: '确认保存', primary: true, getValue: box => ({notes: box.querySelector('#workbenchRevisionNotesV024')?.value.trim() || '', analysis_definition_id: candidate && box.querySelector('#workbenchLinkAnalysisV062')?.checked ? candidate.id : null})},
      ],
    });
    return value === false ? null : value;
  }
  function newCommitKey() {
    return `EDC-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`.replace(/[^A-Za-z0-9-]/g, '').slice(0, 120);
  }
  function commitKeyForDraft(designId) {
    const draft = draftService?.state?.draft || {};
    const tx = draft.editor_transaction || {};
    const fingerprint = [designId, draft.version || 0, tx.transaction_hash || tx.intent_hash || '', tx.intent_version || 0].join(':');
    if (!wb.commitKey || wb.commitFingerprint !== fingerprint) {
      wb.commitKey = newCommitKey(); wb.commitFingerprint = fingerprint;
    }
    return wb.commitKey;
  }
  function actionLock(key, operation) {
    return window.MCSNavigationTransaction?.withActionLock ? window.MCSNavigationTransaction.withActionLock(key, operation) : Promise.resolve().then(operation);
  }
  function saveRevision(options = {}) {
    const designId = state.workspaceDesign?.id || 'none';
    return actionLock(`design-commit:${designId}`, () => saveRevisionImpl(options));
  }
  async function saveRevisionImpl(options = {}) {
    if (wb.saveBusy || !totalChangeCount() || draftConflict()) return false;
    // Product-facing save is intentionally simple. Internally the immutable commit
    // carries a durable commit_key. If the server completed but the browser lost the
    // response, a retry returns the exact same Revision instead of creating another.
    const withNotes = options?.withNotes === true;
    const commit = withNotes ? await revisionNotesSheet() : {
      notes: `设计参数保存（自动历史）· 基于 Rev.${state.workspaceRevision?.revision}`,
      analysis_definition_id: null,
    };
    if (commit === null) return false;
    const notes = typeof commit === 'object' ? (commit.notes || '') : String(commit || '');
    const analysisDefinitionId = typeof commit === 'object' ? (commit.analysis_definition_id || null) : null;
    wb.saveBusy = true; updateChangeCount();
    const buttons = [$q('#workbenchSaveV024'), $q('#workbenchQuickSaveV088')].filter(Boolean);
    buttons.forEach(button => { button.dataset.saveLabelV088 = button.textContent; button.textContent = '正在保存设计…'; button.disabled = true; });
    try {
      const design = state.workspaceDesign; if (!design) throw new Error('当前电机设计不存在');
      await draftService?.flush?.({silent: true, reason: 'commit'});
      const expectedVersion = Number(draftService?.state?.draft?.version || 0);
      const commitKey = commitKeyForDraft(design.id);
      const created = await api(`/api/solutions/${encodeURIComponent(design.id)}/draft/commit`, {method: 'POST', body: JSON.stringify({expected_version: expectedVersion, commit_key: commitKey, notes: notes || `设计参数保存（自动历史）`, analysis_definition_id: analysisDefinitionId})});
      wb.commitKey = null; wb.commitFingerprint = null;
      draftService?.begin?.({}); verification?.dispose?.(); wb.saveBusy = false;
      const priorRevisions=(design.revisions||[]).filter(row=>String(row.id)!==String(created.id));
      const updatedDesign={...design,updated_at:created.created_at||design.updated_at,revisions:[created,...priorRevisions]};
      if(state.workspaceProject){state.workspaceProject={...state.workspaceProject,designs:(state.workspaceProject.designs||[]).map(row=>row.id===design.id?{...row,updated_at:updatedDesign.updated_at}:row)};}
      document.body.classList.remove('design-editing-v062');
      window.MCSDesignStore?.setMode?.('read', {source: 'editor-save'});
      window.MCSDesignStore?.selectParameter?.(null, {source: 'editor-save'});
      queueMicrotask(()=>window.MCSUnifiedAnalysis?.refresh?.({skipFlush:true}).catch?.(()=>{}));
      toast(created.idempotent_replay ? `已恢复先前完成的保存；仍为 ${revisionLabel(created.revision)}，未重复创建版本。` : `设计已保存。模板基线未改动；${revisionLabel(created.revision)} 已作为自动历史快照保留。`, 'SUCCESS', 6200);
      await openWorkspaceDesign(design.id,null,updatedDesign);
      if (created.id) await Promise.resolve(selectWorkspaceRevision(created.id));
      window.MCSDesignStore?.selectParameter?.(null, {source: 'editor-save-overview'});
      window.MCSRouter?.setRevisionEditMode?.(false, {view: wb.view, replace: true});
      window.MCSRouter?.syncDesignView?.(wb.view, {replace: true});
      return true;
    } catch (error) {
      if (error?.status === 409 && error?.detail?.code === 'DESIGN_DRAFT_STALE') {
        wb.commitKey = null; wb.commitFingerprint = null;
        draftService?.setConflict?.({kind: 'stale_same_revision', current_version: error.detail.current_version, updated_at: error.detail.updated_at});
        renderConflictBanner(); renderPrecheck(); renderEvidence();
      }
      // For transport/unknown failures the key is intentionally retained. The next
      // click replays the same immutable commit request and the backend can recover it.
      toast(error.message, 'ERROR', 8500); wb.saveBusy = false;
      buttons.forEach(button => { button.textContent = button.dataset.saveLabelV088 || (button.id === 'workbenchQuickSaveV088' ? '保存修改并返回参数总览' : '保存设计'); });
      updateChangeCount();
      return false;
    }
  }

  async function confirmDestructive(title, message, confirmLabel = '确认') {
    if (!window.StudioDialog?.sheet) { toast('确认对话框尚未加载，已取消该操作。', 'WARNING', 4200); return false; }
    const result = await StudioDialog.sheet({title, html: `<div class="step-help-sheet"><p>${safe(message)}</p><p class="hint">此操作不会影响已保存的电机版本。</p></div>`, actions: [{label: '取消', value: false}, {label: confirmLabel, value: true, primary: true}]});
    return result === true;
  }
  function exitWorkbenchPreservingDraft() {
    const designId = state.workspaceDesign?.id || 'none';
    return actionLock(`design-exit:${designId}`, async () => {
      try { await draftService?.flush?.({silent: true, reason: 'editor-exit'}); }
      catch (error) { toast(`草稿尚未安全保存：${error.message}`, 'ERROR', 7000); return false; }
      verification?.dispose?.(); wb.shellAbort?.abort(); document.body.classList.remove('design-editing-v062');
      window.MCSDesignStore?.setMode?.('read', {source: 'editor-exit'}); window.MCSRouter?.setRevisionEditMode?.(false, {view: wb.view, replace: true});
      await openWorkspaceDesign(state.workspaceDesign.id); window.MCSRouter?.syncDesignView?.(wb.view, {replace: true}); return true;
    });
  }
  function discardDraft() {
    const design = state.workspaceDesign; if (!design) return Promise.resolve(false);
    return actionLock(`design-discard:${design.id}`, async () => {
      const ok = await confirmDestructive('放弃当前设计草稿', '未冻结的参数和材料修改将被删除。', '放弃草稿'); if (!ok) return false;
      try {
        await draftService?.delete?.({silent: true, force: true, reason: 'discard'}); wb.commitKey = null; wb.commitFingerprint = null; verification?.dispose?.(); wb.shellAbort?.abort(); document.body.classList.remove('design-editing-v062');
        window.MCSDesignStore?.setMode?.('read', {source: 'editor-discard'}); toast('设计草稿已放弃。', 'SUCCESS', 3200);
        window.MCSRouter?.setRevisionEditMode?.(false, {view: wb.view, replace: true}); await openWorkspaceDesign(design.id); window.MCSRouter?.syncDesignView?.(wb.view, {replace: true}); return true;
      } catch (error) { toast(`草稿删除失败：${error.message}`, 'ERROR', 6500); return false; }
    });
  }
  async function reloadStaleDraft() {
    const ok = await confirmDestructive('重新加载最新设计草稿', '当前窗口尚未保存到服务器的修改将被丢弃，并重新读取另一窗口保存的最新草稿。', '重新加载'); if (!ok) return;
    await open();
  }

  async function loadNativeWinding() {
    const artifact = wb.data?.native_evidence?.winding_pattern_artifact; if (!artifact) return;
    const pre = $q('#nativeWindingTextV024'); if (!pre) return;
    if (wb.windingText !== null) { pre.textContent = wb.windingText; pre.classList.toggle('hidden'); return; }
    try { const response = await fetch(artifact.download_url, {cache: 'no-store'}); if (!response.ok) throw new Error(`HTTP ${response.status}`); wb.windingText = await response.text(); pre.textContent = wb.windingText.slice(0, 24000); pre.classList.remove('hidden'); }
    catch (error) { pre.textContent = `读取失败：${error.message}`; pre.classList.remove('hidden'); }
  }

  function navigateEditorView(target, source) {
    if (!target) return;
    wb.view = target; window.MCSDesignStore?.setView?.(target, {source}); renderVisual(); draftService?.schedule?.({reason: 'view-change'}); window.MCSRouter?.syncDesignView?.(target, {replace: true});
  }

  function bindShell() {
    wb.shellAbort?.abort();
    const controller = new AbortController(); wb.shellAbort = controller; const signal = controller.signal;
    $q('#workbenchCancelV024')?.addEventListener('click', exitWorkbenchPreservingDraft, {signal});
    $q('#workbenchDiscardV062')?.addEventListener('click', discardDraft, {signal});
    $q('#workbenchSaveV024')?.addEventListener('click', () => saveRevision(), {signal});
    $q('#workbenchQuickSaveV088')?.addEventListener('click', () => saveRevision(), {signal});
    $q('#workbenchDraftRetryV065')?.addEventListener('click', () => draftService?.persist?.({silent: false, reason: 'manual-retry'}).catch(() => {}), {signal});
    $q('#workbenchSearchV024')?.addEventListener('input', event => renderGroups(event.target.value), {signal});
    $q('#workbenchOpenParameterCatalogV066')?.addEventListener('click', () => { if (totalChangeCount()) { toast('当前草稿已有修改。请先保存为 Revision 或放弃草稿，再进入全量 Motor-CAD 参数目录，避免产生并行版本分支。', 'WARNING', 7000); return; } window.MCSDesignParameterCatalog?.open?.(); }, {signal});
    $q('#restoreGroupPreviousV024')?.addEventListener('click', () => restoreGroup('previous'), {signal});
    $q('#restoreGroupTemplateV024')?.addEventListener('click', () => restoreGroup('template'), {signal});
    const canvas = $q('#workspaceCanvas');
    canvas?.addEventListener('click', async event => {
      const reload = event.target.closest('[data-reload-stale-draft-v065]'); if (reload) { await reloadStaleDraft(); return; }
      const existing = event.target.closest('[data-open-existing-draft-v062]'); if (existing) { const target = draftConflict()?.base_revision_id || draftConflict(); if (!target) return; await Promise.resolve(window.selectWorkspaceRevision?.(target)); await open(); return; }
      const replace = event.target.closest('[data-replace-existing-draft-v062]'); if (replace) { const ok = await confirmDestructive('替换现有设计草稿', `将删除基于 ${conflictRevisionLabel()} 的现有草稿，并从当前版本重新开始编辑。`, '删除旧草稿并继续'); if (!ok) return; try { await draftService?.delete?.({silent: true, force: true, reason: 'replace-conflict'}); draftService?.begin?.({}); renderConflictBanner(); updateChangeCount(); toast('旧草稿已放弃，现在可以编辑当前版本。', 'SUCCESS', 3800); } catch (error) { toast(`旧草稿删除失败：${error.message}`, 'ERROR', 6500); } return; }
      const visualSource = event.target.closest('[data-visual-source-v088e]'); if (visualSource) { wb.visualSource = visualSource.dataset.visualSourceV088e || 'design'; renderVisual(); return; }
      const group = event.target.closest('[data-workbench-group]'); if (group) { wb.group = group.dataset.workbenchGroup; renderGroups($q('#workbenchSearchV024')?.value || ''); renderParameters(); return; }
      const region = event.target.closest('[data-workbench-region]'); if (region) { selectRegion(region.dataset.workbenchRegion); return; }
      const select = event.target.closest('[data-workbench-select]'); if (select) { selectParameter(select.dataset.workbenchSelect); return; }
      const restore = event.target.closest('[data-workbench-restore]'); if (restore) { const row = recordFor(restore.dataset.paramId), value = restore.dataset.workbenchRestore === 'previous' ? row?.previous_feasible_value : row?.template_default; if (value !== undefined) setValue(row.id, value); return; }
      if (event.target.closest('[data-workbench-slot-fill-auto]')) { restoreAutomaticSlotFill(); return; }
      const set = event.target.closest('[data-workbench-set]'); if (set) { setValue(set.dataset.workbenchSet, Number(set.dataset.workbenchValue)); return; }
      const material = event.target.closest('[data-workbench-material-component]'); if (material) {
        if (draftConflict()) return;
        const component = material.dataset.workbenchMaterialComponent, type = material.dataset.materialTypeV062 || '';
        const componentSpec=(window.MCSDesignMaterials?.MATERIAL_COMPONENTS_V062||[]).find(item=>item.key===component||(item.aliases||[]).includes(component));
        const componentLabel=window.MCS_I18N?.t?.(componentSpec?.label||component,componentSpec?.en||component)||componentSpec?.label||component;
        if (!window.MCSMaterialLibrary?.pick) { toast(window.MCS_I18N?.t?.('材料库模块尚未就绪，请刷新页面后重试。','The material library is not ready. Refresh the page and try again.')||'材料库模块尚未就绪。', 'ERROR', 7000); return; }
        try { await window.MCSMaterialLibrary.pick({kind: 'solid', materialType: type, componentLabel, title: window.MCS_I18N?.t?.(`选择${componentLabel}材料`,`Choose material for ${componentLabel}`)||`选择${componentLabel}材料`, onSelect: row => {
          const components = {...(wb.materials.component_materials || {})}, provenance = {...(wb.materials.material_provenance || {})};
          components[component] = row.name; provenance[component] = {material_record_id: row.id, source_kind: row.source_kind, source_database_path: row.source_database_path, source_database_hash: row.source_database_hash, material_section_hash: row.material_section_hash, motorcad_version: row.motorcad_version};
          const before = objectSnapshot(wb.materials); wb.materials = {...wb.materials, component_materials: components, material_provenance: provenance}; wb.materialDirty = objectSnapshot(wb.materials) !== objectSnapshot(wb.baseMaterials);
          if (before !== objectSnapshot(wb.materials)) markEdited(); renderVisual(); renderPrecheck(); renderEvidence(); updateChangeCount(); draftService?.schedule?.({reason: 'material-edit'});
        }}); } catch (error) { toast(`${window.MCS_I18N?.t?.('材料库打开失败','Failed to open material library')||'材料库打开失败'}：${error.message||error}`, 'ERROR', 7000); } return;
      }
      const stage = event.target.closest('[data-workbench-stage-v062]'); if (stage) { navigateEditorView(workbenchDefaultViewForStage(stage.dataset.workbenchStageV062), 'editor-stage'); return; }
      const view = event.target.closest('[data-workbench-view]'); if (view) { navigateEditorView(view.dataset.workbenchView, 'editor-tab'); return; }
      const next = event.target.closest('[data-workbench-next-v063]'); if (next) { const target = next.dataset.workbenchNextV063; if (target === 'commit') { saveRevision(); return; } navigateEditorView(target, 'editor-next'); return; }
      const issue = event.target.closest('[data-workbench-issue]'); if (issue) { const row = currentPrecheck()?.issues?.[Number(issue.dataset.workbenchIssue)], id = (row?.parameter_ids || []).find(parameterId => recordFor(parameterId)); if (id) selectParameter(id); return; }
      if (event.target.closest('[data-workbench-run-studio-check-v065]')) { await runStudioCheck(); return; }
      if (event.target.closest('[data-workbench-run-native-check-v065]')) { await runNativeCheck(); return; }
      if (event.target.closest('[data-workbench-native-safe-repair-v088c]')) { await runNativeCheck({repairPolicy: 'safe_auto'}); return; }
      if (event.target.closest('#loadNativeWindingV024')) { await loadNativeWinding(); return; }
      const schematic = event.target.closest('[data-schematic-part]'); if (schematic) { const tags = String(schematic.dataset.schematicPart || '').split(/\s+/), regionId = tags.find(tag => wb.data?.regions?.[tag]); if (regionId) selectRegion(regionId); }
    }, {signal});
    canvas?.addEventListener('input', event => {
      if (draftConflict()) return;
      const input = event.target.closest('[data-workbench-input]'); if (!input) return;
      const id = input.dataset.workbenchInput, number = Number(input.value); if (!Number.isFinite(number)) return;
      const next = recordFor(id)?.type === 'integer' ? Math.round(number) : number, before = wb.values[id]; wb.values[id] = next; refreshChanged(id); wb.selected = id;
      if (!sameValue(before, next)) markEdited();
      applySlotFillCoupling(id);
      window.MCSDesignStore?.selectParameter?.(id, {source: 'editor-input'}); input.closest('[data-workbench-param-row]')?.classList.toggle('changed', wb.changed.has(id)); updateChangeCount(); renderPrecheck(); renderEvidence(); draftService?.schedule?.({reason: 'parameter-input'});
      cancelAnimationFrame(wb.previewFrame); wb.previewFrame = requestAnimationFrame(() => { renderSelected(); renderVisual(); });
    }, {signal});
    canvas?.addEventListener('focusin', event => { const input = event.target.closest('[data-workbench-input]'); if (input) { wb.selected = input.dataset.workbenchInput; window.MCSDesignStore?.selectParameter?.(wb.selected, {source: 'editor-focus'}); renderSelected(); highlightSelectedRegion(); } }, {signal});
  }

  async function open(routeCtx = null) {
    const design = state.workspaceDesign, revision = state.workspaceRevision;
    if (!design || !revision) { toast('请先选择电机版本', 'WARNING'); return false; }
    const canvas = $q('#workspaceCanvas'); if (canvas) canvas.innerHTML = '<div class="workspace-empty"><span class="connection-pulse"></span><b>正在加载电机设计…</b><p>读取设计参数、材料、影响关系、草稿和模型检查状态。</p></div>';
    try {
      const options = routeCtx?.signal ? {signal: routeCtx.signal} : {};
      const [data, draftResult] = await Promise.all([
        api(`/api/design-revisions/${encodeURIComponent(revision.id)}/workbench`, options),
        api(`/api/solutions/${encodeURIComponent(design.id)}/draft`, options).catch(() => ({exists: false, draft: null})),
      ]);
      if (routeCtx && !window.MCSPageRuntime?.isContextActive?.(routeCtx)) return false;
      wb.shellAbort?.abort(); verification?.dispose?.();
      wb.revisionId = revision.id; wb.data = data; wb.values = {...(data.effective_parameters || {})}; wb.visualSource = 'design';
      (data.parameters || []).forEach(row => { if (!(row.id in wb.values)) wb.values[row.id] = row.value; });
      wb.baseValues = cloneValue(wb.values); wb.slotFillMode = 'auto'; wb.slotFillEstimate = null;
      wb.baseMaterials = editableMaterials(data, revision);
      wb.materials = cloneValue(wb.baseMaterials);
      wb.changed = new Set(); wb.materialDirty = false; wb.explicitIds = new Set(revision.explicit_parameter_ids || []); wb.windingText = null; wb.editVersion = 0; wb.commitKey = null; wb.commitFingerprint = null; wb.leavePrepared = false;
      const draft = draftResult?.draft || null; let conflict = null;
      if (draft && draft.base_revision_id === revision.id) {
        wb.values = {...wb.values, ...(draft.parameters || {})}; wb.materials = draft.materials || wb.materials; wb.explicitIds = new Set(draft.explicit_parameter_ids || revision.explicit_parameter_ids || []);
        (data.parameters || []).forEach(row => refreshChanged(row.id)); wb.materialDirty = objectSnapshot(wb.materials) !== objectSnapshot(wb.baseMaterials); if (totalChangeCount()) wb.editVersion = 1;
      } else if (draft) conflict = draft;
      inferSlotFillMode();
      draftService?.begin?.({draft: draft && draft.base_revision_id === revision.id ? draft : null, conflict});
      verification?.begin?.(totalChangeCount() ? null : data.precheck || null);
      wb.selected = (data.parameters || [])[0]?.id || null; wb.group = recordFor(wb.selected)?.category || data.groups?.[0]?.id || 'topology';
      wb.view = (draft && draft.base_revision_id === revision.id && draft.active_view) || window.MCSDesignStore?.currentView?.() || window.MCSDesignViewer?.state?.view || ((data.design_views || []).find(row => row.preferred)?.id || 'radial');
      window.MCSDesignStore?.setContext?.({projectId: state.activeProjectId || null, designId: design.id, revisionId: revision.id, mode: 'edit', view: wb.view, selectedParameter: wb.selected, data, dirtyCount: totalChangeCount()}, {source: 'editor-load'});
      renderShell(); window.MCSRouter?.setRevisionEditMode?.(true, {view: wb.view, replace: true});
      if (draft && draft.base_revision_id === revision.id) toast('已恢复上次未冻结的设计草稿。', 'INFO', 4200);
      return true;
    } catch (error) {
      if (window.MCSPageRuntime?.isAbortError?.(error)) return false;
      if (canvas) canvas.innerHTML = `<div class="workspace-empty"><b>设计工作台加载失败</b><p>${safe(error.message || error)}</p></div>`;
      toast(error.message, 'ERROR', 8000); return false;
    }
  }

  async function openView(view = 'radial', parameterId = null) {
    const ok = await open(); if (!ok) return false;
    if (view) wb.view = view;
    if (parameterId && recordFor(parameterId)) { wb.selected = parameterId; wb.group = recordFor(parameterId)?.category || wb.group; renderParameters(); renderSelected(); }
    renderVisual(); window.MCSRouter?.syncDesignView?.(wb.view, {replace: true}); return true;
  }
  function applyRouteView(route) {
    let requested = route?.designView || window.MCSAppCore?.viewForRoute?.(route?.designSection, route?.designSubview);
    if (requested === 'evidence') requested = 'native'; if (!requested) return;
    wb.view = requested; window.MCSDesignStore?.setView?.(requested, {source: 'editor-route'}); if (wb.data) { renderVisual(); draftService?.schedule?.({reason: 'route-view'}); }
  }
  async function prepareRouteChange(route) {
    if (!wb.data || window.MCSDesignStore?.getState?.()?.mode !== 'edit') return true;
    const sameEditor = route?.tab === 'workspace' && route?.editRevision && route?.designId === state.workspaceDesign?.id && route?.revisionId === wb.revisionId;
    if (sameEditor) return true;
    const conflict = draftConflict();
    if (conflict && !totalChangeCount()) return true;
    if (conflict?.kind === 'stale_same_revision' && totalChangeCount()) {
      toast('当前草稿已在另一个窗口更新。请先重新加载最新草稿，再离开编辑页面。', 'ERROR', 7500); return false;
    }
    try {
      await draftService?.flush?.({silent: true, reason: 'route-change'});
      wb.leavePrepared = true;
      return true;
    } catch (error) { toast(`草稿未能安全保存，已取消页面跳转：${error.message}`, 'ERROR', 8000); return false; }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('#workspaceEditRevision');
    if (!button) return;
    event.preventDefault(); event.stopImmediatePropagation();
    open().catch(error => toast(`设计编辑器打开失败：${error.message}`, 'ERROR', 8000));
  }, true);

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && window.MCSDesignStore?.getState?.()?.mode === 'edit' && draftService?.hasUnpersistedChanges?.()) {
      draftService.flush({silent: true, reason: 'visibility-hidden'}).catch(() => {});
    }
  });

  function editorGuardState() {
    const mode = window.MCSDesignStore?.getState?.()?.mode;
    const draft = draftService?.snapshot?.() || {};
    return {active: mode === 'edit' && Boolean(wb.data), design_id: state.workspaceDesign?.id || null, revision_id: wb.revisionId, dirty_count: totalChangeCount(), unpersisted: Boolean(draftService?.hasUnpersistedChanges?.()), conflict: draft.conflict || null, save_busy: wb.saveBusy};
  }
  window.MCSNavigationTransaction?.registerGuard?.({
    id: 'design-editor', priority: 100,
    isActive: () => editorGuardState().active,
    unsafe: () => editorGuardState().unpersisted,
    inspect: editorGuardState,
    prepare: prepareRouteChange,
  });
  window.addEventListener('mcs:navigation-transaction-committed', event => {
    if (!wb.leavePrepared) return;
    const route = event.detail?.meta?.route || null;
    const sameEditor = route?.tab === 'workspace' && route?.editRevision && route?.designId === state.workspaceDesign?.id && route?.revisionId === wb.revisionId;
    if (sameEditor) { wb.leavePrepared = false; return; }
    wb.leavePrepared = false; verification?.dispose?.(); wb.shellAbort?.abort(); document.body.classList.remove('design-editing-v062');
    window.MCSDesignStore?.setMode?.('read', {source: 'navigation-transaction-commit'});
  });
  document.addEventListener('mcs-language-change',()=>{if(wb.data&&window.MCSDesignStore?.getState?.()?.mode==='edit')renderVisual()});

  window.MCSDesignEditor = {open, openView, applyRouteView, prepareRouteChange, inspectTransaction: editorGuardState, selectParameter, setValue, runStudioCheck, runNativeCheck, saveRevision, discardDraft, exitWorkbenchPreservingDraft, state: wb, draftService, verification};
})();
