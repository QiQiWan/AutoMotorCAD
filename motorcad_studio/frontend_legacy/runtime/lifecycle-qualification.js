/* V0.87-F-A: local runtime lifecycle qualification. */
(() => {
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function badge(status) {
    const el = $('#runtimeLifecycleBadgeV087FA');
    if (!el) return;
    el.textContent = status === 'PASS' ? '本地生命周期通过' : status === 'FAIL' ? '需要处理' : '读取中';
    el.className = `badge ${status === 'PASS' ? 'VALID' : status === 'FAIL' ? 'INVALID' : ''}`;
  }

  function render(payload) {
    const host = $('#runtimeLifecycleSummaryV087FA');
    if (!host) return;
    const checks = Array.isArray(payload?.checks) ? payload.checks : [];
    const failed = checks.filter((row) => !row.passed);
    const runtime = payload?.runtime || {};
    const db = payload?.database || {};
    const scheduler = runtime?.scheduler?.lifecycle || {};
    const pool = runtime?.worker_pool || {};
    const poolLifecycle = pool?.lifecycle || {};
    const ok = payload?.local_qualified === true;
    badge(ok ? 'PASS' : 'FAIL');
    host.innerHTML = `
      <div class="summary-grid">
        <div><span class="eyebrow">Studio状态</span><b>${esc(runtime.state || '-')}</b><small>生命周期代次 ${esc(runtime.generation ?? '-')}</small></div>
        <div><span class="eyebrow">任务线程</span><b>${esc(runtime.active_task_thread_count ?? 0)}</b><small>Case线程 ${esc(runtime.active_case_thread_count ?? 0)}</small></div>
        <div><span class="eyebrow">资源调度器</span><b>${esc(scheduler.state || '-')}</b><small>活动租约 ${esc((runtime?.scheduler?.active_leases || []).length)}</small></div>
        <div><span class="eyebrow">Worker池</span><b>${esc(poolLifecycle.state || (pool.mode === 'isolated' ? 'ISOLATED' : '-'))}</b><small>活动Worker ${esc((pool.workers || []).length)}</small></div>
        <div><span class="eyebrow">SQLite</span><b>${db.idle ? '空闲' : `${esc(db.active_connections || 0)} 个连接`}</b><small>峰值 ${esc(db.peak_connections ?? 0)}</small></div>
      </div>
      <div class="callout ${ok ? 'success' : 'warning'} compact"><b>${ok ? '本地生命周期资格通过' : `发现 ${failed.length} 项生命周期问题`}</b><br>${ok ? 'Studio当前线程、调度、Worker与数据库所有权状态一致。' : failed.map((row) => esc(row.message || row.code)).join('；')}</div>
      <p class="hint">生产资格保持 ${payload?.production_qualified ? '通过' : '未通过'}：${esc(payload?.production_boundary || '')}</p>`;
  }

  async function refresh() {
    badge('LOADING');
    try {
      const response = await fetch('/api/runtime/lifecycle/qualification');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      badge('FAIL');
      const host = $('#runtimeLifecycleSummaryV087FA');
      if (host) host.innerHTML = `<div class="callout warning compact"><b>生命周期证据读取失败</b><br>${esc(error?.message || error)}</div>`;
    }
  }

  $('#refreshRuntimeLifecycleV087FA')?.addEventListener('click', refresh);
  window.addEventListener('mcs:route-changed', (event) => {
    if (event?.detail?.tab === 'setup') refresh();
  });
  window.MCSRuntimeLifecycleQualification = Object.freeze({refresh, render});
  refresh();
})();
