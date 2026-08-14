/* V0.27 atomic Motor-CAD runtime scheduler + runtime contract UX. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = (value, digits = 0) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '-';
  let latestScheduler = null;
  let latestContract = null;
  let lastMonitorCaseId = null;

  const REASON = {
    WORKER_CAPACITY: '等待空闲 Motor-CAD Worker',
    MEMORY_ADMISSION: '内存安全余量不足',
    LICENSE_EMAG_BUSY: '电磁许可证本地配额已占满',
    LICENSE_THERMAL_BUSY: '热分析许可证本地配额已占满',
    LICENSE_LAB_BUSY: 'Lab 许可证本地配额已占满',
    LICENSE_MECHANICAL_BUSY: '机械许可证本地配额已占满',
    LICENSE_EMAG_UNCONFIGURED: '电磁许可证容量配置为 0',
    LICENSE_THERMAL_UNCONFIGURED: '热分析许可证容量配置为 0',
    LICENSE_LAB_UNCONFIGURED: 'Lab 许可证容量配置为 0',
    LICENSE_MECHANICAL_UNCONFIGURED: '机械许可证容量配置为 0',
  };

  function reasonLabel(code) { return REASON[code] || code || '等待资源释放'; }
  function contractClass(status) {
    if (['ENDURANCE_OBSERVED','STABLE_OBSERVED'].includes(status)) return 'ok';
    if (['WARMING','EARLY_EVIDENCE'].includes(status)) return 'warning';
    if (status === 'ENVIRONMENT_CHANGED') return 'error';
    return '';
  }
  function concurrencyLabel(key) {
    return ({emag:'电磁',thermal_steady:'稳态热',thermal_transient:'瞬态热',emag_thermal:'电磁+稳态热',emag_thermal_coupled:'电磁-热耦合',mechanical:'机械',lab_magnetic:'Lab电磁',lab_operating_point:'Lab工作点'})[key] || key;
  }

  function renderRuntimeResourceEvidence() {
    const box = document.querySelector('#runtimeResourceEvidenceV027');
    if (!box) return;
    if (!lastMonitorCaseId) {
      box.innerHTML = '<span class="eyebrow">运行时资源租约</span><p class="hint">等待当前 Case 进入 Worker / 许可证 / 内存联合调度。</p>';
      return;
    }
    const queue = (latestScheduler?.queue || []).find(row => row.case_id === lastMonitorCaseId);
    const active = (latestScheduler?.active_leases || []).find(row => row.case_id === lastMonitorCaseId);
    if (active) {
      box.innerHTML = `<span class="eyebrow">运行时资源租约</span><div class="lease-head-v026"><b>${esc(active.lease_id)}</b><span class="badge ok">资源已原子授予</span></div><div class="lease-grid-v026"><div><span>Worker Token</span><b>${esc(active.worker_token || '-')}</b></div><div><span>许可证</span><b>${esc((active.licenses || []).join(' + ') || '无需模块许可')}</b></div><div><span>排队等待</span><b>${fmt(active.wait_ms,0)} ms</b></div><div><span>内存预留</span><b>${fmt(active.memory_reservation_mb,0)} MB</b></div></div><small>该租约只表示 Studio 已同时预留本地 Worker、许可证容量和内存预算。真正的许可证 checkout 仍由当前 Motor-CAD 会话内的 get_licence() 结果作为权威证据。</small>`;
      return;
    }
    if (queue) {
      const reasons = (queue.blocking_reasons || []).map(reasonLabel);
      box.innerHTML = `<span class="eyebrow">运行时资源租约</span><div class="lease-head-v026"><b>${esc(queue.request_id || lastMonitorCaseId)}</b><span class="badge warning">等待资源</span></div><div class="lease-grid-v026"><div><span>已等待</span><b>${fmt((queue.wait_ms || 0)/1000,1)} s</b></div><div><span>所需许可证</span><b>${esc((queue.licenses || []).join(' + ') || '-')}</b></div></div><div class="runtime-blockers-v027">${reasons.map(value => `<span>${esc(value)}</span>`).join('')}</div><small>资源释放后会自动进入执行；无需重复点击“提交任务”。</small>`;
      return;
    }
    box.innerHTML = '<span class="eyebrow">运行时资源租约</span><p class="hint">当前 Case 尚未排入运行时资源队列，或已经完成资源释放。</p>';
  }

  function renderScheduler(payload) {
    latestScheduler = payload;
    const box = document.querySelector('#runtimeSchedulerSummaryV027');
    const badge = document.querySelector('#runtimeSchedulerBadgeV027');
    if (!box && !badge) return;
    const readiness = payload?.readiness || {};
    const queueDepth = Number(payload?.queue_depth || 0);
    const worker = payload?.worker || {};
    const memory = payload?.memory || {};
    const metrics = payload?.metrics || {};
    const licenses = payload?.licenses || {};
    if (badge) {
      const blocked = (readiness.issues || []).some(row => row.severity === 'BLOCKING');
      badge.textContent = blocked ? '运行时未就绪' : queueDepth ? `${queueDepth} 个Case等待` : '资源调度就绪';
      badge.className = `badge ${blocked ? 'error' : queueDepth ? 'warning' : 'ok'}`;
    }
    if (!box) return;
    const licenseRows = Object.entries(licenses).map(([name,row]) => `<div class="runtime-license-row-v027"><b>${esc(name)}</b><span>${esc(row.in_use ?? 0)} / ${esc(row.capacity ?? 0)} 使用</span><small>${esc(row.waiting ?? 0)} 等待</small></div>`).join('');
    const conc = Object.entries(payload?.effective_concurrency || {}).filter(([key]) => ['emag','thermal_steady','emag_thermal','mechanical'].includes(key)).map(([key,value]) => `<span><b>${esc(concurrencyLabel(key))}</b>${esc(value)}</span>`).join('');
    const queueRows = (payload?.queue || []).slice(0,6).map(row => `<div class="runtime-queue-row-v027"><div><b>${esc(row.case_id || row.request_id)}</b><small>${esc(concurrencyLabel(row.analysis))} · 已等待 ${fmt((row.wait_ms || 0)/1000,1)} s</small></div><div class="runtime-blockers-v027">${(row.blocking_reasons || []).map(reason => `<span>${esc(reasonLabel(reason))}</span>`).join('') || '<span>即将获得资源</span>'}</div></div>`).join('');
    const issues = (readiness.issues || []).map(row => `<div class="runtime-readiness-issue-v027 ${String(row.severity || '').toLowerCase()}"><b>${esc(row.code)}</b><span>${esc(row.message)}</span></div>`).join('');
    box.innerHTML = `<div class="runtime-scheduler-metrics-v027"><div><span>Worker Token</span><b>${esc(worker.in_use ?? 0)} / ${esc(worker.capacity ?? 0)}</b><small>${esc(worker.available ?? 0)} 可用</small></div><div><span>资源队列</span><b>${esc(queueDepth)}</b><small>P95 ${fmt(metrics.p95_wait_ms,0)} ms</small></div><div><span>主机可用内存</span><b>${fmt(memory.host_available_mb,0)} MB</b><small>单Case预留 ${fmt(memory.case_reservation_mb,0)} MB</small></div><div><span>已授予租约</span><b>${esc(metrics.grants ?? 0)}</b><small>超时 ${esc(metrics.timeouts ?? 0)} · 取消 ${esc(metrics.cancellations ?? 0)}</small></div></div><div class="runtime-scheduler-grid-v027"><div><h4>许可证本地容量</h4><div class="runtime-license-list-v027">${licenseRows || '<span class="hint">没有许可证容量配置</span>'}</div></div><div><h4>当前有效并发上限</h4><div class="runtime-concurrency-v027">${conc}</div></div></div>${issues ? `<div class="runtime-readiness-list-v027">${issues}</div>` : ''}${queueRows ? `<div class="runtime-queue-v027"><h4>等待中的 Case</h4>${queueRows}</div>` : '<p class="hint">当前没有 Case 在等待运行时资源。</p>'}`;
    renderRuntimeResourceEvidence();
  }

  function renderContract(payload) {
    latestContract = payload;
    const stateNode = document.querySelector('#runtimeContractStateV027');
    const detail = document.querySelector('#runtimeContractDetailV027');
    const summary = payload?.status_summary || {};
    const status = summary.status || 'UNVERIFIED';
    if (stateNode) {
      stateNode.textContent = summary.label || status;
      stateNode.className = `runtime-contract-state-v027 ${contractClass(status)}`;
    }
    if (detail) {
      const total = payload?.totals || {};
      const formal = summary.formal_windows_contract_passed ? ' · Windows Contract PASS' : '';
      const stale = summary.stale ? ' · 证据超过有效期' : '';
      detail.textContent = `真实 Case：成功 ${total.succeeded || 0} / 失败 ${total.failed || 0}；最长连续成功 ${summary.max_success_streak || 0}${formal}${stale}`;
    }
  }

  function renderWorkerCompatibility(pool) {
    const box = document.querySelector('#runtimeSchedulerSummaryV027');
    if (!box || !pool?.started) return;
    const workers = pool.workers || [];
    const compatible = workers.filter(row => (row.capabilities || {}).compatible).length;
    const incompatible = workers.length - compatible;
    let node = box.querySelector('.runtime-worker-capability-v027');
    if (!node) {
      node = document.createElement('div');
      node.className = 'runtime-worker-capability-v027';
      box.prepend(node);
    }
    const first = workers[0]?.capabilities || {};
    node.innerHTML = `<div><span>Worker能力握手</span><b>${compatible}/${workers.length || 0} 兼容</b></div><div><span>PyMotorCAD</span><b>${esc(first.pymotorcad_version || (first.pymotorcad_available ? '已安装' : '不可用'))}</b></div><div><span>有效 Motor-CAD.exe</span><b title="${esc(first.configured_motorcad_exe || '')}">${first.configured_motorcad_exe_exists === false ? '路径不存在' : esc((first.configured_motorcad_exe || '注册版本').split(/[\\/]/).pop())}</b></div>${incompatible ? `<div class="error"><span>不兼容 Worker</span><b>${incompatible}</b></div>` : ''}`;
  }

  async function refreshRuntimeScheduler(ctx = null) {
    try {
      const get = path => ctx?.api ? ctx.api(path, {cache:'no-store'}) : api(path, {cache:'no-store'});
      const [scheduler, contract, pool] = await Promise.all([
        get('/api/runtime/resource-scheduler'),
        get('/api/runtime/contract'),
        get('/api/runtime/motorcad-worker-pool'),
      ]);
      if (ctx?.assertActive) ctx.assertActive();
      renderScheduler(scheduler);
      renderContract(contract);
      renderWorkerCompatibility(pool);
      return {scheduler, contract, pool};
    } catch (error) {
      if (window.MCSPageRuntime?.isAbortError?.(error)) return null;
      const badge = document.querySelector('#runtimeSchedulerBadgeV027');
      if (badge) { badge.textContent='调度状态读取失败'; badge.className='badge error'; }
      return null;
    }
  }

  async function probeWorkerCapabilities() {
    const button = document.querySelector('#probeWorkerCapabilitiesV027');
    if (button) { button.disabled = true; button.textContent = '探测中…'; }
    try {
      const result = await api('/api/runtime/motorcad-worker-pool/probe', {method:'POST'});
      const probe = result.capability_probe || {};
      const level = Number(probe.incompatible || 0) ? 'WARNING' : 'SUCCESS';
      toast(`Worker能力探测完成：${probe.compatible || 0} 兼容，${probe.incompatible || 0} 不兼容；未主动启动 Motor-CAD。`, level, 6500);
      await refreshRuntimeScheduler();
    } catch (error) {
      toast(`Worker能力探测失败：${error.message || error}`, 'ERROR', 8000);
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Worker能力探测'; }
    }
  }

  document.querySelector('#refreshRuntimeSchedulerV027')?.addEventListener('click', () => refreshRuntimeScheduler());
  document.querySelector('#probeWorkerCapabilitiesV027')?.addEventListener('click', probeWorkerCapabilities);

  if (window.MCSRouteControllersV025?.mount) {
    const previousMount = window.MCSRouteControllersV025.mount;
    window.MCSRouteControllersV025.mount = async function(route, ctx) {
      const result = await previousMount(route, ctx);
      if (!ctx?.active?.()) return result;
      if (route.tab === 'setup' || route.tab === 'monitor') {
        await refreshRuntimeScheduler(ctx);
        ctx.interval(() => refreshRuntimeScheduler(ctx), 3000);
      }
      return result;
    };
  }

  if (typeof window.renderMonitorSnapshot === 'function') {
    const previousRender = window.renderMonitorSnapshot;
    window.renderMonitorSnapshot = function(snapshot) {
      previousRender(snapshot);
      lastMonitorCaseId = snapshot?.visualization?.case_id || snapshot?.active_workers?.[0]?.case_id || null;
      renderRuntimeResourceEvidence();
    };
  }

  // System SSE already contains the scheduler snapshot. Reuse it instead of adding
  // another global polling channel outside the route lifecycle.
  if (typeof window.renderSystemSnapshot === 'function') {
    const previousSystemRender = window.renderSystemSnapshot;
    window.renderSystemSnapshot = function(snapshot) {
      previousSystemRender(snapshot);
      if (snapshot?.runtime_scheduler) renderScheduler(snapshot.runtime_scheduler);
      if (snapshot?.motorcad_worker_pool) renderWorkerCompatibility(snapshot.motorcad_worker_pool);
    };
  }

  window.MCSV027 = {refreshRuntimeScheduler, renderScheduler, renderContract, probeWorkerCapabilities};
})();
