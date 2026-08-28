/* V0.89-B Full Button HMI Qualification Authority.
 *
 * This module is intentionally loaded before the product modules. It records
 * click-handler registration, gives every fixed/dynamic button a deterministic
 * control/action identity, and exposes a fail-visible qualification report.
 */
(() => {
  const CONTRACT_VERSION = '0.89-B';
  const AUTHORITY = 'HMIActionQualificationAuthorityV1';
  const directBindings = new WeakMap();
  const delegatedClickRoots = new WeakSet();
  const observedControls = new Map();
  const families = new Map();
  let bootAnnotated = false;
  let mutationObserver = null;
  let sequence = 0;

  const originalAddEventListener = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(type, listener, options) {
    try {
      if (type === 'click') {
        if (this === document || this === document.body || this === window) delegatedClickRoots.add(this);
        else if (this && this.nodeType === 1) directBindings.set(this, (directBindings.get(this) || 0) + 1);
      }
    } catch {}
    return originalAddEventListener.call(this, type, listener, options);
  };

  const ACTION_ATTRIBUTES = [
    ['data-hmi-action', 'HMI'],
    ['data-tab', 'NAV_TAB'],
    ['data-go', 'NAV_GO'],
    ['data-engineer-stage', 'ENGINEER_STAGE'],
    ['data-analysis-step-v076', 'ANALYSIS_STEP'],
    ['data-fea-mode-v022', 'FEA_MODE'],
    ['data-event-filter', 'EVENT_FILTER'],
    ['data-viewer-mode', 'VIEWER_MODE'],
    ['data-workflow-action-route', 'WORKFLOW_ROUTE'],
    ['data-project-enter', 'PROJECT_ENTER'],
    ['data-project-edit', 'PROJECT_EDIT'],
    ['data-project-restore', 'PROJECT_RESTORE'],
    ['data-canonical-create-solution', 'SOLUTION_CREATE'],
    ['data-canonical-motor', 'MOTOR_OPEN'],
    ['data-canonical-analysis', 'ANALYSIS_OPEN'],
    ['data-workspace-design', 'SOLUTION_SELECT'],
    ['data-workspace-revision', 'MOTOR_REVISION_SELECT'],
    ['data-template-id', 'TEMPLATE_SELECT'],
    ['data-template-use', 'TEMPLATE_USE'],
    ['data-template-detail', 'TEMPLATE_DETAIL'],
    ['data-template-compare', 'TEMPLATE_COMPARE'],
    ['data-use-template', 'TEMPLATE_USE'],
    ['data-open-task-v076', 'TASK_OPEN'],
    ['data-open-viewer-case', 'RESULT_CASE_OPEN'],
    ['data-viewer-scalar', 'RESULT_SCALAR'],
    ['data-fix-first-v081a', 'ANALYSIS_FIX_FIRST'],
    ['data-svp-run', 'STANDARD_VALIDATION_RUN'],
    ['data-native-preview-source', 'NATIVE_PREVIEW_SOURCE'],
    ['data-field-view-mode', 'FIELD_VIEW_MODE'],
    ['data-result-mode', 'RESULT_MODE'],
    ['data-candidate-action', 'CANDIDATE_ACTION'],
    ['data-workflow-action-endpoint', 'WORKFLOW_ENDPOINT'],
  ];

  const SAFE_DELEGATED_SELECTORS = [
    '[data-tab]','[data-go]','[data-engineer-stage]','[data-analysis-step-v076]',
    '[data-fea-mode-v022]','[data-event-filter]','[data-viewer-mode]',
    '[data-project-enter]','[data-project-edit]','[data-project-restore]',
    '[data-canonical-create-solution]','[data-canonical-motor]','[data-canonical-analysis]',
    '[data-template-detail]','[data-template-compare]','[data-use-template]',
    '[data-workspace-design]','[data-workspace-revision]','[data-workflow-action-route]',
    '[data-open-task-v076]','[data-open-viewer-case]','[data-viewer-scalar]',
    '[data-fix-first-v081a]','[data-svp-run]','[data-native-preview-source]',
    '[data-field-view-mode]','[data-result-mode]','[data-candidate-action]',
    '#solverPlaybackToggleV022','#nativeFEAPlayV023'
  ];
  const DEFERRED_OWNER_IDS = new Set(['analysisCommonModeV081A','analysisAdvancedModeV081A','analysisBackToMotorV076','analysisRefreshV076','analysisCreateV076']);

  const norm = value => String(value ?? '')
    .trim().replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '').toUpperCase() || 'ACTION';
  const textOf = el => String(el?.getAttribute?.('aria-label') || el?.getAttribute?.('title') || el?.textContent || '').replace(/\s+/g,' ').trim();
  const scopeOf = el => el.closest?.('section.tab')?.id || el.closest?.('#projectShell')?.id || el.closest?.('header')?.className?.split?.(' ')?.[0] || el.closest?.('nav')?.className?.split?.(' ')?.[0] || 'global';
  const actionableAttribute = el => {
    for (const [attr,prefix] of ACTION_ATTRIBUTES) {
      if (el.hasAttribute?.(attr)) return {attr,prefix,value:el.getAttribute(attr) || 'default'};
    }
    return null;
  };
  const familyOf = el => {
    if (el.id) return `ID:${el.id}`;
    const action = actionableAttribute(el);
    if (action) return `${action.prefix}:${action.value}`;
    return `TEXT:${scopeOf(el)}:${norm(textOf(el)).slice(0,48)}`;
  };
  const actionIdOf = el => {
    if (el.dataset?.hmiAction) return norm(el.dataset.hmiAction);
    if (el.id) return norm(el.id);
    const action = actionableAttribute(el);
    return action ? `${action.prefix}_${norm(action.value)}` : `${norm(scopeOf(el))}_${norm(textOf(el)).slice(0,48)}`;
  };
  const controlIdOf = (el, origin) => {
    if (el.dataset?.hmiControlId) return el.dataset.hmiControlId;
    const scope = norm(scopeOf(el));
    const base = el.id ? `ID_${norm(el.id)}` : `${scope}_${actionIdOf(el)}`;
    const siblings = [...document.querySelectorAll('button')].filter(other => other !== el && (other.dataset?.hmiControlId || '').startsWith(base));
    return siblings.length ? `${base}_${siblings.length + 1}` : base;
  };
  const isDestructive = el => el.classList?.contains('danger-ghost') || /删除|清除|回收|trash|delete|clear/i.test(textOf(el));
  const delegatedEvidence = el => SAFE_DELEGATED_SELECTORS.some(selector => { try { return el.matches(selector); } catch { return false; } });
  const bindingEvidence = el => {
    const direct = directBindings.get(el) || 0;
    if (direct > 0) return {bound:true,kind:'direct',count:direct};
    if (typeof el.onclick === 'function') return {bound:true,kind:'onclick',count:1};
    if (delegatedEvidence(el)) return {bound:true,kind:'declared-delegated-family',count:1};
    if (el.id && DEFERRED_OWNER_IDS.has(el.id) && window.MCSUnifiedAnalysis) return {bound:true,kind:'deferred-page-owner',count:1};
    return {bound:false,kind:'none',count:0};
  };

  function annotateButton(el, origin='dynamic') {
    if (!(el instanceof HTMLButtonElement)) return null;
    if (!el.dataset.hmiOrigin) el.dataset.hmiOrigin = origin;
    if (!el.dataset.hmiActionId) el.dataset.hmiActionId = actionIdOf(el);
    if (!el.dataset.hmiControlId) el.dataset.hmiControlId = controlIdOf(el, origin);
    if (!el.dataset.hmiFamily) el.dataset.hmiFamily = familyOf(el);
    const record = {
      control_id: el.dataset.hmiControlId,
      action_id: el.dataset.hmiActionId,
      family: el.dataset.hmiFamily,
      origin: el.dataset.hmiOrigin,
      scope: scopeOf(el),
      label: textOf(el),
      destructive: isDestructive(el),
      disabled: Boolean(el.disabled),
      visible: Boolean(el.getClientRects?.().length),
      sequence: ++sequence,
    };
    observedControls.set(record.control_id, record);
    const family = families.get(record.family) || {family:record.family,instances:0,controlIds:new Set(),origins:new Set(),labels:new Set()};
    family.controlIds.add(record.control_id);
    family.instances = family.controlIds.size;
    family.origins.add(record.origin);
    if(record.label) family.labels.add(record.label);
    families.set(record.family,family);
    return record;
  }

  function scan(root=document, {origin=null}={}) {
    const buttons = root instanceof HTMLButtonElement ? [root] : [...(root.querySelectorAll?.('button') || [])];
    for (const button of buttons) annotateButton(button, origin || button.dataset.hmiOrigin || (bootAnnotated ? 'dynamic' : 'fixed'));
    return buttons;
  }

  function qualify(root=document) {
    scan(root);
    const buttons = [...root.querySelectorAll('button')];
    const rows = buttons.map(el => {
      const binding = bindingEvidence(el);
      const label = textOf(el);
      const row = {
        control_id: el.dataset.hmiControlId || null,
        action_id: el.dataset.hmiActionId || null,
        family: el.dataset.hmiFamily || null,
        origin: el.dataset.hmiOrigin || 'unknown',
        scope: scopeOf(el), label,
        visible: Boolean(el.getClientRects().length),
        enabled: !el.disabled,
        destructive: isDestructive(el),
        stable_identity: Boolean(el.dataset.hmiControlId && el.dataset.hmiActionId),
        label_present: Boolean(label),
        handler_bound: binding.bound,
        handler_evidence: binding.kind,
        direct_handler_count: binding.count,
      };
      const readiness = window.MCSActionReadiness?.evaluate?.(el) || null;
      const recovery = readiness?.recovery ? {
        kind: readiness.recovery.kind || null,
        label: readiness.recovery.label || null,
        selector: readiness.recovery.selector || null,
        tab: readiness.recovery.tab || null,
      } : null;
      row.readiness_state = readiness?.status || null;
      row.blocker = readiness?.blocker || '';
      row.recovery_action = recovery;
      row.qualified = row.stable_identity && row.label_present && row.handler_bound;
      return row;
    });
    const fixed = rows.filter(row=>row.origin==='fixed');
    const dynamic = rows.filter(row=>row.origin!=='fixed');
    const qualified = rows.filter(row=>row.qualified).length;
    const missing = rows.filter(row=>!row.qualified);
    const actionReadiness = window.MCSActionReadiness?.qualify?.(root,{render:false}) || null;
    return {
      authority: AUTHORITY,
      contract_version: CONTRACT_VERSION,
      generated_at: new Date().toISOString(),
      total_controls: rows.length,
      fixed_controls: fixed.length,
      dynamic_controls_rendered: dynamic.length,
      qualified_controls: qualified,
      qualification_percent: rows.length ? Number((qualified * 100 / rows.length).toFixed(1)) : 100,
      fixed_qualification_percent: fixed.length ? Number((fixed.filter(row=>row.qualified).length * 100 / fixed.length).toFixed(1)) : 100,
      missing_count: missing.length,
      missing,
      controls: rows,
      observed_dynamic_families: [...families.values()].map(row=>({family:row.family,instances:row.instances,origins:[...row.origins],labels:[...row.labels]})).sort((a,b)=>a.family.localeCompare(b.family)),
      delegated_click_root_registered: delegatedClickRoots.has(document) || delegatedClickRoots.has(document.body) || delegatedClickRoots.has(window),
      action_readiness: actionReadiness,
      dead_end_count: Number(actionReadiness?.dead_end_count || 0),
      unmanaged_primary_count: Number(actionReadiness?.unmanaged_count || 0),
    };
  }

  function renderQualification(target='#hmiQualificationSummaryV089B') {
    const host = typeof target === 'string' ? document.querySelector(target) : target;
    const report = qualify();
    if (!host) return report;
    const missing = report.missing.slice(0,12);
    const deadEnds=Number(report.action_readiness?.dead_end_count||0),unmanaged=Number(report.action_readiness?.unmanaged_count||0);
    host.innerHTML = `<div class="hmi-qualification-score-v089b action-readiness-v089g2 ${report.missing_count||deadEnds||unmanaged?'blocked':'ready'}"><div><span>固定按钮资格</span><b>${report.fixed_qualification_percent}%</b><small>${report.fixed_controls} 个固定按钮 · 当前渲染 ${report.total_controls} 个按钮</small></div><div><span>未绑定/不稳定</span><b>${report.missing_count}</b><small>${report.missing_count?'需要修复后才能通过 HMI Release Gate':'当前渲染控件全部具备稳定身份与点击处理证据'}</small></div><div class="dead-end-count-v089g2 ${deadEnds||unmanaged?'blocked':'ready'}"><span>动作死路 / 未纳管</span><b>${deadEnds} / ${unmanaged}</b><small>${deadEnds||unmanaged?'主操作必须提供明确且可执行的恢复动作':'当前可见主操作均有可执行状态与恢复路径'}</small></div></div>${missing.length?`<div class="hmi-qualification-issues-v089b">${missing.map(row=>`<div><code>${row.control_id||'NO_ID'}</code><span>${row.label||'无标签'} · ${row.handler_evidence}</span></div>`).join('')}</div>`:''}`;
    return report;
  }

  function exportReport() {
    const report = qualify();
    const blob = new Blob([JSON.stringify(report,null,2)], {type:'application/json'});
    const url = URL.createObjectURL(blob); const link=document.createElement('a');
    link.href=url; link.download=`motorcad-hmi-qualification-${Date.now()}.json`; document.body.appendChild(link); link.click(); link.remove();
    requestAnimationFrame(()=>URL.revokeObjectURL(url));
    return report;
  }

  scan(document,{origin:'fixed'}); bootAnnotated = true;
  if (document.body && window.MutationObserver) {
    mutationObserver = new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes || []) {
        if (node?.nodeType !== 1) continue;
        if (node.matches?.('button')) annotateButton(node,'dynamic');
        scan(node,{origin:'dynamic'});
      }
    });
    mutationObserver.observe(document.body,{childList:true,subtree:true});
  }
  document.addEventListener('DOMContentLoaded',()=>scan(document),{once:true});
  window.addEventListener('load',()=>setTimeout(()=>scan(document),0),{once:true});
  document.querySelector('#runHmiQualificationV089B')?.addEventListener('click',()=>renderQualification());
  document.querySelector('#exportHmiQualificationV089B')?.addEventListener('click',()=>exportReport());

  window.MCSHMIQualification = {authority:AUTHORITY,contractVersion:CONTRACT_VERSION,scan,qualify,renderQualification,exportReport,observedControls,families};
})();
