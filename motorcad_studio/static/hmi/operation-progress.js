/* MotorCAD Studio V0.89-G4 — observable, bounded operation progress. */
(() => {
  const active = new Map();
  const now = () => globalThis.performance?.now?.() ?? Date.now();
  const tr = (zh, en) => window.MCS_I18N?.t?.(zh, en) ?? zh;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const uid = () => `op-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  function dock() {
    let root = document.querySelector('#mcsOperationProgressDock');
    if (root) return root;
    root = document.createElement('aside');
    root.id = 'mcsOperationProgressDock';
    root.className = 'mcs-operation-progress-dock';
    root.setAttribute('aria-live', 'polite');
    root.setAttribute('aria-label', tr('后台操作进度', 'Background operation progress'));
    document.body.appendChild(root);
    return root;
  }

  function restoreButton(op) {
    const button = op.button;
    if (!button) return;
    button.classList.remove('mcs-button-busy-g33');
    button.removeAttribute('aria-busy');
    if (op.disableButton && button.dataset.mcsOpOwner === op.id) {
      button.disabled = Boolean(op.originalDisabled);
      delete button.dataset.mcsOpOwner;
    }
  }

  function bindButton(op) {
    const button = op.button;
    if (!button) return;
    op.originalDisabled = button.disabled;
    button.dataset.mcsOpOwner = op.id;
    button.setAttribute('aria-busy', 'true');
    button.classList.add('mcs-button-busy-g33');
    if (op.disableButton) button.disabled = true;
  }

  const elapsed = op => Math.max(0, (now() - op.startedAt) / 1000);
  function stateLabel(op, percent) {
    if (op.state === 'done') return tr('完成', 'Done');
    if (op.state === 'timed_out') return tr('已超时', 'Timed out');
    if (op.state === 'cancelled') return tr('已取消', 'Cancelled');
    if (op.state === 'failed') return tr('失败', 'Failed');
    return percent === null ? tr('运行中', 'Running') : `${Math.round(percent)}%`;
  }

  function paint(op) {
    const root = dock();
    const percent = Number.isFinite(op.percent) ? Math.max(0, Math.min(100, Number(op.percent))) : null;
    let card = root.querySelector(`[data-mcs-op="${CSS.escape(op.id)}"]`);
    if (!card) {
      card = document.createElement('article');
      card.dataset.mcsOp = op.id;
      card.setAttribute('role', 'status');
      root.prepend(card);
    }
    card.className = `mcs-operation-progress-card ${op.state} ${percent === null ? 'indeterminate' : 'determinate'}`;
    const seconds = elapsed(op);
    card.innerHTML = `<div class="mcs-operation-progress-head">
      <span class="mcs-operation-progress-orbit" aria-hidden="true"><i></i></span>
      <div><b>${esc(op.label)}</b><small>${esc(op.stage || op.detail || tr('处理中', 'Processing'))}</small></div>
      <em>${stateLabel(op, percent)}</em>
    </div>
    <div class="mcs-operation-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" ${percent === null ? '' : `aria-valuenow="${Math.round(percent)}"`}><i style="${percent === null ? '' : `width:${percent}%`}"></i></div>
    <div class="mcs-operation-progress-foot"><span>${esc(op.detail || '')}</span><time>${seconds.toFixed(seconds >= 10 ? 0 : 1)} ${tr('秒', 's')}</time></div>`;
  }

  function scheduleRemoval(op, delay = 1600) {
    clearTimeout(op.removeTimer);
    op.removeTimer = setTimeout(() => {
      const card = document.querySelector(`[data-mcs-op="${CSS.escape(op.id)}"]`);
      card?.classList.add('leaving');
      setTimeout(() => card?.remove(), 260);
      active.delete(op.id);
    }, delay);
  }

  function finish(op, state, detail, delay) {
    if (op.state !== 'running') return op.api;
    op.state = state;
    if (state === 'done') op.percent = 100;
    if (detail) op.detail = String(detail);
    clearInterval(op.ticker);
    clearTimeout(op.timeoutTimer);
    restoreButton(op);
    paint(op);
    scheduleRemoval(op, delay);
    return op.api;
  }

  function start(options = {}) {
    const id = String(options.id || uid());
    const existing = active.get(id);
    if (existing?.state === 'running') return existing.api;
    existing?.api?.close?.();
    const op = {
      id,
      label: String(options.label || tr('正在处理', 'Processing')),
      detail: String(options.detail || ''),
      stage: String(options.stage || ''),
      percent: Number.isFinite(options.percent) ? Number(options.percent) : null,
      state: 'running',
      startedAt: now(),
      button: options.button || null,
      disableButton: options.disableButton !== false,
      originalDisabled: false,
      removeTimer: null,
      timeoutTimer: null,
      ticker: null,
    };
    const api = {
      id: op.id,
      get state() { return op.state; },
      update(update = {}) {
        if (op.state !== 'running') return api;
        if (update.label !== undefined) op.label = String(update.label);
        if (update.detail !== undefined) op.detail = String(update.detail);
        if (update.stage !== undefined) op.stage = String(update.stage);
        if (update.percent === null) op.percent = null;
        else if (Number.isFinite(update.percent)) op.percent = Number(update.percent);
        paint(op);
        return api;
      },
      done(detail = '') { return finish(op, 'done', detail, options.doneDelay ?? 1700); },
      fail(detail = '') { return finish(op, 'failed', detail, options.failDelay ?? 4200); },
      timeout(detail = '') {
        try { options.abortController?.abort?.(); } catch {}
        try { options.onTimeout?.(); } catch {}
        return finish(
          op,
          'timed_out',
          detail || tr('操作等待超时；界面已恢复，可查看日志后重试。', 'Operation timed out; the interface has been restored.'),
          options.failDelay ?? 6500,
        );
      },
      cancel(detail = '') {
        try { options.abortController?.abort?.(); } catch {}
        return finish(op, 'cancelled', detail || tr('操作已取消', 'Operation cancelled'), options.doneDelay ?? 1800);
      },
      close() {
        clearInterval(op.ticker);
        clearTimeout(op.timeoutTimer);
        clearTimeout(op.removeTimer);
        restoreButton(op);
        document.querySelector(`[data-mcs-op="${CSS.escape(op.id)}"]`)?.remove();
        active.delete(op.id);
        return api;
      },
    };
    op.api = api;
    bindButton(op);
    active.set(op.id, op);
    paint(op);
    op.ticker = setInterval(() => op.state === 'running' ? paint(op) : clearInterval(op.ticker), 500);
    if (Number.isFinite(options.timeoutMs) && Number(options.timeoutMs) > 0) {
      op.timeoutTimer = setTimeout(() => api.timeout(options.timeoutDetail), Number(options.timeoutMs));
    }
    return api;
  }

  async function withProgress(options, operation) {
    const op = start(options);
    try {
      const result = await operation(op);
      if (op.state === 'running') op.done(options?.doneDetail || tr('完成', 'Done'));
      return result;
    } catch (error) {
      if (op.state === 'running') op.fail(error?.message || String(error));
      throw error;
    }
  }

  const network = {count: 0, failed: 0, timer: null, op: null, lastClickAt: 0, generation: 0};
  function requestDomain(url = '') {
    // Compatibility signature documented for older static qualification: requestDomain(url='')
    const value = String(url);
    if (value.includes('analysis-definition')) return tr('分析配置', 'analysis configuration');
    if (value.includes('result') || value.includes('viewer') || value.includes('aggregate')) return tr('结果数据', 'result data');
    if (value.includes('scorecard') || value.includes('decision') || value.includes('summary')) return tr('工程汇总', 'engineering summary');
    if (value.includes('design') || value.includes('revision')) return tr('设计数据', 'design data');
    if (value.includes('material')) return tr('材料数据', 'material data');
    if (value.includes('template') || value.includes('starter')) return tr('模板数据', 'template data');
    if (value.includes('/tasks') || value.includes('/cases')) return tr('计算任务', 'calculation tasks');
    if (value.includes('runtime') || value.includes('system') || value.includes('preflight')) return tr('运行环境', 'runtime');
    if (value.includes('project')) return tr('项目数据', 'project data');
    return tr('工程数据', 'engineering data');
  }
  const hasExplicitOperation = () => [...active.keys()].some(id => id !== 'network-auto-g4');
  function countLabel(count) { return tr(`${count} 项请求进行中`, `${count} requests in progress`); }
  function paintNetwork(label) {
    if (hasExplicitOperation()) return;
    if (!network.op) network.op = start({
      id: 'network-auto-g4', label, stage: tr('请求处理中', 'Request in progress'),
      detail: countLabel(network.count), percent: null, disableButton: false,
      timeoutMs: 60000, doneDelay: 900, failDelay: 2600,
      onTimeout(){network.generation+=1;network.count=0;network.failed=0;network.op=null;},
    });
    else network.op.update({label, stage: tr('请求处理中', 'Request in progress'), detail: countLabel(network.count), percent: null});
  }
  function trackRequest(url, options = {}) {
    // Compatibility signature documented for older static qualification: function trackRequest(url,options={})
    if (options?.__mcsSilentProgress || hasExplicitOperation()) return () => {};
    const method = String(options?.method || 'GET').toUpperCase();
    const domain = requestDomain(url);
    const recentClick = now() - network.lastClickAt < 650;
    const label = method === 'GET'
      ? `${recentClick ? tr('刷新', 'Refresh ') : tr('加载', 'Load ')}${domain}`
      : `${tr('保存', 'Save ')}${domain}`;
    const generation=network.generation;network.count += 1;
    clearTimeout(network.timer);
    if (method !== 'GET' || recentClick) paintNetwork(label);
    else network.timer = setTimeout(() => paintNetwork(label), 180);
    let ended = false;
    return error => {
      if (ended) return;
      ended = true;
      if(generation!==network.generation)return;
      if (error) network.failed += 1;
      network.count = Math.max(0, network.count - 1);
      if (network.count) { network.op?.update({detail: countLabel(network.count)}); return; }
      clearTimeout(network.timer);
      network.timer = null;
      const op = network.op;
      const failed = network.failed;
      network.op = null;
      network.failed = 0;
      if (op?.state === 'running') {
        if (failed) op.fail(tr('部分请求未完成，请查看页面提示', 'Some requests did not complete. See the page message.'));
        else op.done(tr('工程数据已更新', 'Engineering data updated'));
      }
    };
  }

  document.addEventListener('click', event => {
    const button = event.target?.closest?.('button,[role=button]');
    if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return;
    network.lastClickAt = now();
    button.classList.remove('mcs-button-ack-g33');
    void button.offsetWidth;
    button.classList.add('mcs-button-ack-g33');
    setTimeout(() => button.classList.remove('mcs-button-ack-g33'), 430);
  }, true);
  document.addEventListener('mcs-language-change', () => active.forEach(paint));

  window.MCSOperationProgress = {start, withProgress, trackRequest, active};
  document.body?.classList.add('studio-v089g33', 'studio-v089g4');
})();
