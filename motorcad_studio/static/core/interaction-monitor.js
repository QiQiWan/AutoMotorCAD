/**
 * Detects visible button clicks that have no observable application effect.
 *
 * This is diagnostic evidence, not a replacement for action handlers.  The
 * monitor records silent no-ops in root logs through MCSPageRuntime.report so
 * field failures no longer require a browser console reproduction.
 */
function labelOf(button) {
  return String(button?.getAttribute?.('aria-label') || button?.title || button?.textContent || '')
    .replace(/\s+/g, ' ').trim().slice(0, 180);
}

function activeTab() {
  return document.querySelector('section.tab.active')?.id || null;
}

function isMeaningfulButton(button) {
  if (!(button instanceof HTMLButtonElement)) return false;
  if (button.disabled || button.getAttribute('aria-disabled') === 'true') return false;
  if (button.type === 'submit' && button.form) return true;
  if (button.closest('[role="dialog"], section.tab, header, nav, main, #projectShell')) return true;
  return Boolean(button.id || button.dataset.hmiActionId || button.dataset.tab || button.dataset.go);
}

export function installInteractionMonitor({namespace, bus, scope, settleMs = 900}) {
  if (!namespace || !scope) throw new TypeError('namespace and scope are required');
  let apiSequence = 0;
  let routeSequence = 0;
  let mutationSequence = 0;
  const pending = new WeakMap();

  scope.onBus(bus, 'api:request', () => { apiSequence += 1; });
  scope.listen(window, 'mcs:route-start', () => { routeSequence += 1; }, {passive: true});
  scope.listen(window, 'mcs:route-ready', () => { routeSequence += 1; }, {passive: true});

  const observer = new MutationObserver(records => {
    if (records.some(record => record.type === 'childList' || record.type === 'attributes')) mutationSequence += 1;
  });
  scope.observe(observer, document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'disabled', 'aria-busy', 'hidden']});

  const onClick = event => {
    const button = event.target?.closest?.('button');
    if (!isMeaningfulButton(button)) return;
    const before = {
      href: location.href,
      tab: activeTab(),
      apiSequence,
      routeSequence,
      mutationSequence,
      text: labelOf(button),
      id: button.id || null,
      controlId: button.dataset.hmiControlId || null,
      actionId: button.dataset.hmiActionId || null,
      tabTarget: button.dataset.tab || button.dataset.go || null,
      createdAt: performance.now(),
    };
    pending.set(button, before);
    scope.timeout(() => {
      if (pending.get(button) !== before) return;
      pending.delete(button);
      if (!button.isConnected) return;
      const busy = button.disabled
        || button.getAttribute('aria-busy') === 'true'
        || document.documentElement.dataset.routeTransition === 'loading'
        || Boolean(document.querySelector('[aria-busy="true"], .operation-progress-card, .preflight-running'));
      const effect = busy
        || location.href !== before.href
        || activeTab() !== before.tab
        || apiSequence !== before.apiSequence
        || routeSequence !== before.routeSequence
        || mutationSequence !== before.mutationSequence;
      if (effect) return;
      const payload = {
        label: before.text,
        button_id: before.id,
        control_id: before.controlId,
        action_id: before.actionId,
        requested_tab: before.tabTarget,
        route: location.pathname + location.search,
        active_tab: before.tab,
        settle_ms: Math.round(performance.now() - before.createdAt),
      };
      namespace.compat?.MCSPageRuntime?.report?.(
        'FRONTEND_BUTTON_NO_EFFECT', 'WARNING',
        `按钮点击后没有检测到路由、网络或界面状态变化：${before.text || before.id || 'button'}`,
        payload,
      );
      namespace.diagnostics?.record?.('WARNING', 'BUTTON_NO_EFFECT', payload);
    }, settleMs);
  };
  scope.listen(document, 'click', onClick, true);

  const qualify = reason => {
    const report = namespace.compat?.MCSHMIQualification?.qualify?.(document);
    if (!report) return null;
    const missing = Number(report.missing_controls?.length || report.missing_count || 0);
    const percent = Number(report.qualification_percent ?? 100);
    namespace.runtime.buttonQualification = {
      reason,
      total: report.total_controls || 0,
      qualified: report.qualified_controls || 0,
      qualificationPercent: percent,
      missing,
    };
    if (missing || percent < 100) {
      const missingControls = (report.missing || report.missing_controls || []).slice(0, 24).map(row => ({
        control_id: row.control_id || null,
        action_id: row.action_id || null,
        label: row.label || null,
        scope: row.scope || null,
        handler_evidence: row.handler_evidence || null,
      }));
      namespace.compat?.MCSPageRuntime?.report?.(
        'FRONTEND_BUTTON_BINDING_GAP', 'WARNING',
        `按钮绑定资格 ${percent}%`,
        {reason, total: report.total_controls || 0, qualified: report.qualified_controls || 0, missing, missing_controls: missingControls},
      );
    }
    return report;
  };

  scope.listen(window, 'mcs:route-ready', () => scope.timeout(() => qualify('route-ready'), 0), {passive: true});
  scope.timeout(() => qualify('bootstrap'), 0);
  return Object.freeze({qualify});
}
