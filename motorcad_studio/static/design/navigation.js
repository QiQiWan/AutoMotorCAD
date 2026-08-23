/* Shared design-stage navigation and next-step semantics. */
(() => {
  const stageDefs = Object.freeze([
    {id: 'geometry', label: '\u51e0\u4f55', description: '\u622a\u9762\u4e0e\u88c5\u914d', readViews: ['radial', 'axial'], editViews: ['radial', 'axial']},
    {id: 'winding', label: '\u7ed5\u7ec4', description: '\u8fde\u63a5\u4e0e\u69fd\u5185', readViews: ['winding', 'slot'], editViews: ['winding', 'slot']},
    {id: 'materials', label: '\u6750\u6599', description: '\u90e8\u4ef6\u7ed1\u5b9a', readViews: ['materials'], editViews: ['materials']},
    {id: 'validation', label: '\u8bbe\u8ba1\u9a8c\u8bc1', description: '\u6a21\u578b\u68c0\u67e5', readViews: ['evidence'], editViews: ['native']},
  ]);
  const labels = Object.freeze({
    radial: '\u5f84\u5411\u622a\u9762',
    axial: '\u7eb5\u5411\u88c5\u914d\u5256\u9762',
    winding: '\u7ed5\u7ec4\u8fde\u63a5',
    slot: '\u69fd\u5185\u5b9a\u4e49',
    materials: '\u6750\u6599\u914d\u7f6e',
    evidence: '\u6a21\u578b\u68c0\u67e5',
    native: '\u6a21\u578b\u68c0\u67e5',
    compare: '\u7248\u672c\u6bd4\u8f83',
  });

  function safe(value) {
    return typeof window.esc === 'function' ? window.esc(value) : String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }

  function availableViews(data) {
    const rows = data?.design_views || [];
    const views = new Set(rows.filter(row => row.available !== false).map(row => row.id));
    if (!rows.length) ['radial', 'axial', 'winding', 'slot', 'materials', 'evidence', 'native'].forEach(id => views.add(id));
    if (views.has('evidence')) views.add('native');
    if (views.has('native')) views.add('evidence');
    views.add('compare');
    return views;
  }

  function stageForView(view) {
    if (view === 'compare') return 'compare';
    return stageDefs.find(stage => [...stage.readViews, ...stage.editViews].includes(view))?.id || 'geometry';
  }

  function rowsForStage(stageId, data, options = {}) {
    const mode = options.mode === 'edit' ? 'edit' : 'read';
    const available = availableViews(data);
    const isAxial = Boolean(data?.template?.is_axial);
    const stage = stageDefs.find(row => row.id === stageId);
    if (!stage) return [];
    const ids = mode === 'edit' ? stage.editViews : stage.readViews;
    const seen = new Set();
    return ids.filter(id => {
      if (seen.has(id)) return false;
      seen.add(id);
      return available.has(id);
    }).map(id => ({
      id,
      label: id === 'axial' && isAxial ? '\u8f74\u5411\u5806\u53e0\u5256\u9762' : labels[id] || id,
    }));
  }

  function defaultViewForStage(stageId, data, options = {}) {
    return rowsForStage(stageId, data, options)[0]?.id || null;
  }

  function render(options = {}) {
    const stageBox = options.stageBox;
    const subBox = options.subBox;
    if (!stageBox || !subBox) return;
    const mode = options.mode === 'edit' ? 'edit' : 'read';
    const view = options.view || 'radial';
    const stage = stageForView(view);
    const available = availableViews(options.data);
    const variant = options.variant === 'workbench' ? 'workbench' : 'viewer';
    const stageMainClass = variant === 'workbench' ? 'workbench-stage-main-v062' : 'design-stage-main-v062';
    const stageAttr = variant === 'workbench' ? 'data-workbench-stage-v062' : 'data-design-stage-v062';
    const viewAttr = variant === 'workbench' ? 'data-workbench-view' : 'data-design-view-v031';
    const compareClass = variant === 'workbench' ? 'workbench-compare-v062' : 'design-compare-utility-v062';

    stageBox.innerHTML = `<div class="${stageMainClass}">${stageDefs.map((row, index) => {
      const ids = mode === 'edit' ? row.editViews : row.readViews;
      const enabled = ids.some(id => available.has(id));
      return `<button type="button" ${stageAttr}="${safe(row.id)}" class="${stage === row.id ? 'active' : ''}" ${enabled ? '' : 'disabled'}><span>${index + 1}</span><b>${safe(row.label)}</b><small>${safe(row.description)}</small></button>`;
    }).join('')}</div><button type="button" ${viewAttr}="compare" class="${compareClass} ${view === 'compare' ? 'active' : ''}"><b>${safe(labels.compare)}</b><small>${mode === 'edit' ? '\u8f85\u52a9\u5de5\u5177' : '\u4e0e\u4e0a\u4e00\u53ef\u884c\u7248\u672c\u6bd4\u8f83'}</small></button>`;

    const rows = rowsForStage(stage, options.data, {mode});
    if (view === 'compare') {
      subBox.innerHTML = '<span class="design-subview-caption-v062">\u8f85\u52a9\u5de5\u5177 \u00b7 \u7248\u672c\u6bd4\u8f83</span>';
    } else if (rows.length > 1) {
      subBox.innerHTML = `<span class="design-subview-caption-v062">\u5f53\u524d\u6b65\u9aa4</span>${rows.map(row => `<button type="button" ${viewAttr}="${safe(row.id)}" class="${row.id === view ? 'active' : ''}">${safe(row.label)}</button>`).join('')}`;
    } else {
      subBox.innerHTML = '';
    }
  }

  function next(view, data, options = {}) {
    const mode = options.mode === 'edit' ? 'edit' : 'read';
    const available = availableViews(data);
    const readMap = {
      radial: ['winding', '\u68c0\u67e5\u7ed5\u7ec4\u8fde\u63a5'],
      axial: ['winding', '\u68c0\u67e5\u7ed5\u7ec4\u8fde\u63a5'],
      winding: ['slot', '\u68c0\u67e5\u69fd\u5185\u5b9a\u4e49'],
      slot: ['materials', '\u786e\u8ba4\u90e8\u4ef6\u6750\u6599'],
      materials: ['evidence', '\u6267\u884c\u8bbe\u8ba1\u9a8c\u8bc1'],
      evidence: ['input_data', '\u914d\u7f6e\u5206\u6790\u5de5\u51b5'],
      native: ['input_data', '\u914d\u7f6e\u5206\u6790\u5de5\u51b5'],
    };
    const editMap = {
      radial: ['winding', '\u7ee7\u7eed\u7ed5\u7ec4\u8bbe\u8ba1'],
      axial: ['winding', '\u7ee7\u7eed\u7ed5\u7ec4\u8bbe\u8ba1'],
      winding: ['slot', '\u7ee7\u7eed\u69fd\u5185\u5b9a\u4e49'],
      slot: ['materials', '\u7ee7\u7eed\u6750\u6599\u914d\u7f6e'],
      materials: ['native', '\u7ee7\u7eed\u8bbe\u8ba1\u9a8c\u8bc1'],
      native: ['commit', '\u4fdd\u5b58\u65b0\u8bbe\u8ba1\u7248\u672c'],
      evidence: ['commit', '\u4fdd\u5b58\u65b0\u8bbe\u8ba1\u7248\u672c'],
    };
    const row = (mode === 'edit' ? editMap : readMap)[view];
    if (!row) return null;
    const [target, label] = row;
    if (!['input_data', 'commit'].includes(target) && !available.has(target)) return null;
    return {target, label, mode};
  }

  window.MCSDesignNavigation = {stageDefs, labels, availableViews, stageForView, rowsForStage, defaultViewForStage, render, next};
})();
