/* V0.70 stable module; migrated from historical v026.js. */
/* V0.26 Persistent Motor-CAD worker pool + Validate-and-Run execution lease UX. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  let lastLeaseCase = null;
  let lastLeaseFetch = 0;

  function workerStateLabel(row) {
    if (!row?.alive) return ['已退出','error'];
    if (row.busy) return ['执行中','running'];
    return ['就绪','ok'];
  }

  async function refreshWorkerPool(ctx = null) {
    const box = document.querySelector('#workerPoolSummaryV026');
    const badge = document.querySelector('#workerPoolBadgeV026');
    if (!box && !badge) return null;
    try {
      const payload = ctx?.api ? await ctx.api('/api/runtime/motorcad-worker-pool', {cache:'no-store'}) : await api('/api/runtime/motorcad-worker-pool');
      if (ctx?.assertActive) ctx.assertActive();
      const mode = payload.mode || 'isolated';
      if (mode !== 'persistent') {
        if (badge) { badge.textContent='隔离模式'; badge.className='badge warning'; }
        if (box) box.innerHTML='<div class="callout warning compact"><b>当前使用每 Case 隔离进程</b><br>该模式适合排障，但会重复启动 Motor-CAD。可在环境配置中启用 persistent Worker 模式。</div>';
        return payload;
      }
      if (!payload.started) {
        if (badge) { badge.textContent='按需启动'; badge.className='badge'; }
        if (box) box.innerHTML=`<div class="worker-pool-metrics-v026"><div><span>配置 Worker</span><b>${esc(payload.configured_size ?? '-')}</b></div><div><span>自动回收</span><b>${esc(payload.recycle_jobs ?? '-')} Case</b></div><div><span>内存阈值</span><b>${esc(payload.recycle_rss_mb ?? '-')} MB</b></div></div><p class="hint">Worker 池尚未启动。首次真实 Motor-CAD Case 提交后按需创建；打开 Studio 不会主动占用 Motor-CAD。</p>`;
        return payload;
      }
      if (badge) { badge.textContent=payload.busy ? `${payload.busy} 执行中` : `${payload.ready || 0} 就绪`; badge.className=`badge ${payload.busy?'running':'ok'}`; }
      const workers = payload.workers || [];
      const cards = workers.map(row => {
        const [label, cls] = workerStateLabel(row);
        return `<div class="worker-card-v026"><div class="worker-card-head-v026"><b>${esc(row.worker_id)}</b><span class="badge ${cls}">${label}</span></div><div class="worker-card-grid-v026"><span>PID <b>${esc(row.pid ?? '-')}</b></span><span>世代 <b>G${esc(row.generation ?? 1)}</b></span><span>已完成 <b>${esc(row.jobs_completed ?? 0)}</b></span><span>内存 <b>${esc(row.rss_mb ?? 0)} MB</b></span></div>${row.current_case_id ? `<small>当前 Case：${esc(row.current_case_id)}<br>租约：${esc(row.execution_lease_id || '-')}</small>` : '<small>等待新的 Motor-CAD Case</small>'}${row.last_recycle_reason ? `<small class="muted">上次回收：${esc(row.last_recycle_reason)}</small>` : ''}</div>`;
      }).join('');
      if (box) box.innerHTML=`<div class="worker-pool-metrics-v026"><div><span>Worker</span><b>${esc(payload.configured_size)}</b></div><div><span>执行中</span><b>${esc(payload.busy || 0)}</b></div><div><span>累计 Case</span><b>${esc(payload.total_jobs || 0)}</b></div><div><span>自动重建</span><b>${esc(payload.total_restarts || 0)}</b></div></div><div class="worker-card-list-v026">${cards}</div><p class="hint">单个 Worker 内串行执行 Case。异常、超时或取消会回收整个 Worker 进程树并创建新世代，避免继续复用状态未知的 Motor-CAD。</p>`;
      return payload;
    } catch (error) {
      if (window.MCSPageRuntime?.isAbortError?.(error)) return null;
      if (badge) { badge.textContent='状态读取失败'; badge.className='badge error'; }
      if (box) box.innerHTML=`<div class="callout warning compact">Worker 池状态读取失败：${esc(error.message || error)}</div>`;
      return null;
    }
  }

  async function recycleWorkerPool() {
    const confirmRecycle = window.StudioDialog?.confirm
      ? await window.StudioDialog.confirm({
          title:'回收空闲 Motor-CAD Worker',
          message:'空闲 Worker 会立即重建；正在执行 Case 的 Worker 会在当前 Case 完成后再回收，不会中断正在运行的计算。',
          confirmText:'确认回收',
          cancelText:'取消'
        })
      : true;
    if (!confirmRecycle) return;
    const button = document.querySelector('#recycleWorkerPoolV026');
    if (button) button.disabled = true;
    try {
      const result = await api('/api/runtime/motorcad-worker-pool/recycle', {method:'POST'});
      const recycled = (result.recycled || []).length;
      const deferred = (result.deferred || []).length;
      toast(`Worker 回收请求已处理：立即 ${recycled}，待当前 Case 完成 ${deferred}`, 'INFO', 5000);
      await refreshWorkerPool(null);
    } catch (error) {
      toast(`Worker 回收失败：${error.message || error}`, 'ERROR', 8000);
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.querySelector('#recycleWorkerPoolV026')?.addEventListener('click', recycleWorkerPool);

  async function refreshExecutionLease(caseId, force = false) {
    const box = document.querySelector('#executionLeaseEvidenceV026');
    if (!box || !caseId) return;
    const now = Date.now();
    if (!force && caseId === lastLeaseCase && now - lastLeaseFetch < 1800) return;
    lastLeaseCase = caseId; lastLeaseFetch = now;
    try {
      const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/execution-lease`, {cache:'no-store'});
      if (response.status === 404) {
        box.innerHTML='<span class="eyebrow">Validate-and-Run 执行租约</span><p class="hint">当前 Case 正在建立租约，或属于缺少执行租约的历史任务。</p>';
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if(payload.pending){box.innerHTML=`<span class="eyebrow">Validate-and-Run 执行租约</span><p class="hint">${esc(payload.reason||'当前 Case 正在建立执行租约。')}</p>`;return}
      const lease = payload.lease || {};
      const same = Boolean(lease.same_session_validation_and_solve);
      const state = lease.state || 'UNKNOWN';
      const hash = lease.validation_evidence_hash ? String(lease.validation_evidence_hash).slice(0,16) : '-';
      box.innerHTML=`<span class="eyebrow">Validate-and-Run 执行租约</span><div class="lease-head-v026"><b>${esc(lease.lease_id || '-')}</b><span class="badge ${same?'ok':state==='FAILED'?'error':'warning'}">${same?'同会话校验+求解':esc(state)}</span></div><div class="lease-grid-v026"><div><span>Worker</span><b>${esc(lease.pool_worker_id || '隔离Worker')}${lease.pool_worker_generation ? ` · G${esc(lease.pool_worker_generation)}` : ''}</b></div><div><span>状态</span><b>${esc(state)}</b></div><div><span>RunConfig</span><b>${esc(lease.run_configuration_id || '-')}</b></div><div><span>校验证据</span><b>${esc(hash)}</b></div></div><small>${same ? '每个 Case 会先重载 canonical 模型，再在同一个 Motor-CAD 会话中完成参数回读、几何/绕组原生校验并直接求解，减少“检查通过后换实例再失败”的状态漂移。' : '当前证据尚未确认校验与求解使用同一会话；运行中或历史 Case 可能出现此状态。'}</small>`;
    } catch (error) {
      box.innerHTML=`<span class="eyebrow">Validate-and-Run 执行租约</span><p class="hint">执行租约读取失败：${esc(error.message || error)}</p>`;
    }
  }

  // Extend route-owned lifecycle rather than introducing another permanent poller.
  const routeControllers = window.MCSRouteControllers || window.MCSRouteControllers;
  if (routeControllers?.mount) {
    const previousMount = routeControllers.mount;
    routeControllers.mount = async function(route, ctx) {
      const result = await previousMount(route, ctx);
      if (!ctx?.active?.()) return result;
      if (route.tab === 'setup') {
        await refreshWorkerPool(ctx);
        ctx.interval(() => refreshWorkerPool(ctx), 2500);
      }
      if (route.tab === 'monitor') {
        ctx.interval(() => refreshWorkerPool(ctx), 2500);
      }
      return result;
    };
  }

  if (typeof window.renderMonitorSnapshot === 'function') {
    const previousRender = window.renderMonitorSnapshot;
    window.renderMonitorSnapshot = function(snapshot) {
      previousRender(snapshot);
      const caseId = snapshot?.visualization?.case_id || null;
      if (caseId) refreshExecutionLease(caseId, snapshot?.status === 'COMPLETED');
      refreshWorkerPool();
    };
  }

  window.MCSExecutionLease = {refreshWorkerPool, refreshExecutionLease, recycleWorkerPool};
})();
