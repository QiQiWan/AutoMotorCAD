/* MotorCAD Studio V0.89-G5 — standard validation lives inside the final
 * "Check and calculate" step. The module never changes pages automatically;
 * task monitoring opens only after an explicit engineer action.
 */
(() => {
  const q = (selector, root = document) => root?.querySelector?.(selector) || null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const tr = (zh, en) => window.MCS_I18N?.t?.(zh, en) ?? zh;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const state = {
    payload:null,
    refreshPromise:null,
    timer:null,
    lastKey:null,
    running:false,
    runPromise:null,
    runKey:null,
    submissionKey:null,
    currentJobId:null,
    lastTask:null,
  };
  const ctx = () => window.MCSEngineeringContext?.get?.() || {};
  const host = () => q('#analysisStandardValidationDockV090');

  async function apiCall(path, options = {}) {
    const timeoutMs = Number(options.timeoutMs ?? 45000);
    const controller = new AbortController();
    const requestOptions = {...options};
    delete requestOptions.timeoutMs;
    const timer = setTimeout(() => controller.abort('REQUEST_TIMEOUT'), timeoutMs);
    requestOptions.signal = controller.signal;
    try {
      if (window.api) return await window.api(path, requestOptions);
      const response = await fetch(path, {
        cache:'no-store',
        headers:{'Content-Type':'application/json'},
        ...requestOptions,
      });
      if (!response.ok) {
        let data;
        try { data = await response.json(); }
        catch { data = {detail: await response.text()}; }
        throw new Error(typeof data?.detail === 'string'
          ? data.detail
          : (data?.detail?.message || JSON.stringify(data?.detail || data)));
      }
      return response.json();
    } catch (error) {
      if (controller.signal.aborted) {
        const timeoutError = new Error(tr(
          `请求超过 ${Math.round(timeoutMs / 1000)} 秒，已停止等待。`,
          `Request exceeded ${Math.round(timeoutMs / 1000)} seconds and was stopped.`,
        ));
        timeoutError.code = 'REQUEST_TIMEOUT';
        throw timeoutError;
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  const statusLabel = status => ({
    READY:tr('就绪','Ready'),
    NEEDS_INPUT:tr('需要确认','Needs input'),
    UNAVAILABLE:tr('不可用','Unavailable'),
  })[status] || status || '—';
  const moduleLabel = value => window.MCSAnalysisLabels?.moduleLabel?.(value) || value || '—';
  const newSubmissionKey = () => {
    try { return `svp-${crypto.randomUUID()}`; }
    catch { return `svp-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
  };
  const progress = options => window.MCSOperationProgress?.start?.(options) || {
    state:'running', update(){return this;}, done(){this.state='done';return this;},
    fail(){this.state='failed';return this;}, close(){this.state='closed';return this;},
  };

  function exportLogs() {
    const anchor = document.createElement('a');
    anchor.href = '/api/logs/export.zip?current_session=true&minutes=240';
    anchor.download = 'motorcad-studio-current-session-logs.zip';
    anchor.rel = 'noopener';
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.toast?.(tr(
      '正在导出当前运行日志；项目根目录 logs/ 中的实时日志会继续写入。',
      'Exporting current-session logs. Live logs continue to be written under project-root logs/.',
    ), 'INFO', 5000);
  }

  function taskId(task = state.lastTask) {
    return task?.task_id || task?.id || null;
  }

  function openTask(task = state.lastTask) {
    const context = ctx();
    const id = taskId(task);
    if (!context.projectId || !id) return false;
    window.MCSEngineeringContext?.setExecution?.(task || {task_id:id}, {
      taskId:id,
      source:'standard-validation:explicit-open',
    });
    return window.MCSRouter?.navigate?.(
      `/app/projects/${encodeURIComponent(context.projectId)}/simulation/monitor/${encodeURIComponent(id)}`,
      {source:'standard-validation:explicit-open'},
    );
  }

  function syncRunButton(target = host()) {
    if (!target) return;
    const button = q('[data-svp-run]', target);
    if (!button) return;
    const ready = Boolean(state.payload?.ready_to_materialize);
    button.disabled = state.running || !ready;
    button.textContent = state.running ? tr('检查中…','Checking…') : tr('运行标准设计验证','Run standard validation');
    button.setAttribute('aria-busy', state.running ? 'true' : 'false');
  }

  function render(payload = state.payload) {
    state.payload = payload || null;
    const target = host();
    if (!target) return;
    if (!payload) {
      target.innerHTML = `<div class="analysis-inline-status-v076">${tr('当前电机版本尚无标准验证计划。','No standard validation plan is available for the current motor revision.')}</div>`;
      return;
    }

    const steps = payload.steps || [];
    const ready = Boolean(payload.ready_to_materialize);
    const blockedCount = steps.filter(step => !step.ready).length;
    const revision = window.MCSAnalysisLabels?.revisionLabel?.(payload.design_revision, 'motor')
      || tr(`电机版本 ${payload.design_revision ?? '—'}`, `Motor revision ${payload.design_revision ?? '—'}`);
    const monitorAction = taskId()
      ? `<button type="button" data-svp-open-task>${tr('打开任务监控','Open task monitor')} →</button>`
      : '';

    target.innerHTML = `<section class="panel standard-validation-v087d">
      <div class="standard-validation-head-v087d">
        <div>
          <span class="eyebrow">${tr('可选批量流程','Optional batch flow')}</span>
          <h2>${esc(payload.label || tr('标准设计验证','Standard design validation'))}</h2>
          <p>${esc(payload.starter?.label || tr('预制设计','Starter design'))} · ${esc(revision)} · ${tr(`${steps.length} 个验证步骤`,`${steps.length} validation steps`)}</p>
        </div>
        <span class="status-chip ${ready?'success':'warning'}">${ready
          ? tr('可以运行','Ready to run')
          : tr(`${blockedCount || 1} 项待确认`,`${blockedCount || 1} items need review`)}</span>
      </div>
      <details class="standard-validation-details-v089g33">
        <summary><span>${ready?tr('验证链已准备完成','Validation chain is ready'):tr('验证链存在待处理项','Validation chain needs attention')}</span><small>${tr(`查看 ${steps.length} 个标准验证步骤`,`View ${steps.length} standard steps`)}</small></summary>
        <div class="standard-validation-steps-v087d">${steps.map(step => `<div class="standard-validation-step-v087d ${step.ready?'ready':'blocked'}" title="${esc(step.when_to_use || '')}">
          <i>${esc(step.sequence)}</i><div><b>${esc(step.short_label || step.label)}</b><small>${esc(step.engineering_question || '')}</small><em>${esc(moduleLabel(step.module))} · ${esc(statusLabel(step.status))}${step.expected_runtime?` · ${esc(step.expected_runtime)}`:''}</em></div><span>${step.ready?'✓':'!'}</span>
        </div>`).join('')}</div>
      </details>
      <div class="standard-validation-footer-v087d">
        <div><b>${tr('结果输出','Result output')}</b><span>${tr(
          `工程指标 ${payload.scorecard_coverage?.covered_count || 0}/${payload.scorecard_coverage?.metric_count || 0} 已覆盖${payload.scorecard_coverage?.complete?'。':'，仍有缺口。'}`,
          `Engineering metrics ${payload.scorecard_coverage?.covered_count || 0}/${payload.scorecard_coverage?.metric_count || 0} covered${payload.scorecard_coverage?.complete?'.':'; gaps remain.'}`,
        )}</span></div>
        <div class="actions standard-validation-task-action-v090">
          <button type="button" data-svp-export-logs>${tr('导出当前运行日志','Export current logs')}</button>
          <button type="button" data-svp-preview ${state.running?'disabled':''}>${tr('刷新验证计划','Refresh plan')}</button>
          ${monitorAction}
          <button class="primary" type="button" data-svp-run ${(ready&&!state.running)?'':'disabled'}>${state.running?tr('检查中…','Checking…'):tr('运行标准设计验证','Run standard validation')}</button>
        </div>
      </div>
      <div class="analysis-inline-status-v076" data-svp-log-location>${tr(
        '实时离线日志位于项目根目录 logs/；标准验证不会自动切换当前页面。',
        'Live offline logs are stored under project-root logs/. Standard validation never changes the current page automatically.',
      )}</div>
      <div data-svp-status class="analysis-inline-status-v076 ${state.running?'running':''}">${state.running
        ? tr('后台验证正在运行；进度来自实际作业阶段，请勿重复提交。','Validation is running in the background; progress follows the actual job stage.')
        : taskId()
          ? tr('标准分析任务已提交。请点击“打开任务监控”查看进度。','Standard analysis tasks were submitted. Select Open task monitor to view progress.')
          : ready
            ? tr('当前设计已具备标准验证计划。','The design has a standard validation plan.')
            : tr('请先处理不可用或待确认的分析步骤。','Resolve unavailable or unconfirmed analysis steps first.')}</div>
    </section>`;

    q('[data-svp-export-logs]', target)?.addEventListener('click', exportLogs);
    q('[data-svp-preview]', target)?.addEventListener('click', () => refresh({force:true}));
    q('[data-svp-run]', target)?.addEventListener('click', run);
    q('[data-svp-open-task]', target)?.addEventListener('click', () => openTask());
    syncRunButton(target);
    window.MCS_I18N?.apply?.(target);
  }

  function run() {
    if (state.runPromise) return state.runPromise;
    const context = ctx();
    if (!context.projectId || !context.motorRevisionId || !state.payload) return Promise.resolve(null);

    const runKey = `${context.projectId}:${context.motorRevisionId}`;
    state.running = true;
    state.runKey = runKey;
    state.submissionKey = newSubmissionKey();
    state.lastTask = null;
    render();
    window.MCSActionReadiness?.scheduleRefresh?.();

    const target = host();
    const operation = progress({
      id:`standard-validation-${context.motorRevisionId}`,
      label:tr('运行标准设计验证','Run standard validation'),
      stage:tr('创建后台作业','Create background job'),
      detail:tr('冻结标准分析并准备计算前检查','Freeze standard analyses and prepare preflight checks'),
      percent:3,
      button:q('[data-svp-run]', target),
      timeoutMs:1020000,
      timeoutDetail:tr(
        '标准验证超过 17 分钟，界面已恢复；请检查 Motor-CAD 进程与项目根目录 logs/。',
        'Standard validation exceeded 17 minutes. Check the Motor-CAD process and project-root logs/.',
      ),
      failDelay:7000,
    });

    const promise = (async () => {
      const statusNode = () => q('[data-svp-status]', host());
      try {
        const startPath = `/api/projects/${encodeURIComponent(context.projectId)}/design-revisions/${encodeURIComponent(context.motorRevisionId)}/standard-validation-package/jobs`;
        let job = await apiCall(startPath, {
          method:'POST',
          body:JSON.stringify({
            decisions_by_analysis:{},
            run_native_precheck:true,
            reuse_cache:true,
            quality_profile:'standard',
            submission_key:state.submissionKey,
          }),
        });
        if (!job?.id) throw new Error(tr('标准验证后台作业未返回任务标识','The validation job did not return an ID'));
        state.currentJobId = job.id;
        const deadline = Date.now() + 1020000;

        while (['QUEUED','RUNNING'].includes(String(job.status || '').toUpperCase())) {
          if (Date.now() > deadline) throw new Error(tr(
            '标准验证等待超时，请查看项目根目录 logs/ 或导出当前运行日志后重试。',
            'Standard validation timed out. Check project-root logs/ or export current logs, then retry.',
          ));
          const percent = Number.isFinite(job.progress_percent) ? Number(job.progress_percent) : null;
          const detail = job.message || tr('后台验证正在运行…','Validation is running…');
          operation.update({
            percent,
            stage:detail,
            detail:job.coalesced
              ? tr('已合并重复提交，继续跟踪同一作业','Duplicate submission merged; tracking the same job')
              : detail,
          });
          const node = statusNode();
          if (node) { node.textContent = detail; node.className = 'analysis-inline-status-v076 running'; }
          await wait(700);
          job = await apiCall(`${startPath}/${encodeURIComponent(state.currentJobId)}`);
        }

        if (['FAILED','TIMED_OUT'].includes(String(job.status || '').toUpperCase())) {
          throw new Error(job.error || job.message || tr('标准验证后台作业失败','Standard validation job failed'));
        }
        const result = job.result;
        if (!result) throw new Error(tr('标准验证完成但未返回结果','Standard validation completed without a result'));

        if (result.execution_status === 'BLOCKED') {
          const blocked = (result.executions || []).find(item => item.execution_status === 'BLOCKED');
          const message = blocked?.blocker?.message || blocked?.blocker?.code
            || tr('标准验证被计算前检查阻断','Standard validation was blocked by preflight checks');
          const node = statusNode();
          if (node) {
            node.textContent = `${message} ${tr('可直接导出当前运行日志继续诊断。','Export current logs here for diagnosis.')}`;
            node.className = 'analysis-inline-status-v076 error';
          }
          operation.fail(message);
          window.toast?.(message, 'WARNING', 9000);
          return result;
        }

        const tasks = (result.executions || []).filter(item => taskId(item));
        state.lastTask = tasks[0] || null;
        const success = tr(
          `已提交 ${tasks.length} 个标准分析任务，将按 Worker / 许可证容量排队。`,
          `${tasks.length} standard analyses submitted and queued by worker/license capacity.`,
        );
        operation.done(success);
        window.toast?.(success, 'SUCCESS', 7000);
        render();
        const node = statusNode();
        if (node) {
          node.textContent = state.lastTask
            ? tr(`${success} 点击“打开任务监控”查看进度。`,`${success} Select Open task monitor to view progress.`)
            : success;
          node.className = 'analysis-inline-status-v076 success';
        }
        return result;
      } catch (error) {
        const node = statusNode();
        if (node) {
          node.textContent = `${error.message || String(error)} ${tr('可导出当前运行日志并检查项目根目录 logs/。','Export current logs and inspect project-root logs/.')}`;
          node.className = 'analysis-inline-status-v076 error';
        }
        if (operation.state === 'running') operation.fail(error.message || String(error));
        window.toast?.(error.message || String(error), 'ERROR', 9000);
        return null;
      } finally {
        if (state.runKey === runKey) {
          state.running = false;
          state.runKey = null;
          state.submissionKey = null;
          state.currentJobId = null;
        }
        state.runPromise = null;
        syncRunButton();
        const preview = q('[data-svp-preview]', host());
        if (preview) preview.disabled = false;
        window.MCSActionReadiness?.scheduleRefresh?.();
      }
    })();
    state.runPromise = promise;
    return promise;
  }

  function refresh({force=false, silent=false} = {}) {
    if (state.refreshPromise) return state.refreshPromise;
    const context = ctx();
    if (!context.projectId || !context.motorRevisionId) {
      state.payload = null;
      state.lastTask = null;
      render(null);
      return Promise.resolve(null);
    }
    const key = `${context.projectId}:${context.motorRevisionId}`;
    if (state.lastKey && state.lastKey !== key) state.lastTask = null;
    if (!force && state.lastKey === key && state.payload) {
      render();
      return Promise.resolve(state.payload);
    }

    const target = host();
    const operation = (!silent || force) ? progress({
      id:`standard-validation-refresh-${context.motorRevisionId}`,
      label:tr('刷新标准验证计划','Refresh standard validation plan'),
      stage:tr('读取验证合同','Load validation contract'),
      detail:tr('同步电机版本、标准分析步骤与结果覆盖度','Sync motor revision, validation steps, and result coverage'),
      percent:16,
      button:q('[data-svp-preview]', target),
      timeoutMs:45000,
    }) : null;

    const promise = (async () => {
      try {
        operation?.update?.({
          percent:52,
          stage:tr('汇总验证步骤','Summarize validation steps'),
          detail:tr('检查各分析模块的可用性与必要输入','Check module availability and required inputs'),
        });
        const payload = await apiCall(`/api/projects/${encodeURIComponent(context.projectId)}/design-revisions/${encodeURIComponent(context.motorRevisionId)}/standard-validation-package`);
        state.lastKey = key;
        render(payload);
        operation?.done?.(tr('标准验证计划已同步','Validation plan synchronized'));
        return payload;
      } catch (error) {
        state.lastKey = key;
        state.payload = null;
        render(null);
        if (operation?.state === 'running') operation.fail(error.message || String(error));
        if (!silent && error?.status !== 422) window.toast?.(tr(
          `标准验证计划读取失败：${error.message || error}`,
          `Failed to load validation plan: ${error.message || error}`,
        ), 'WARNING', 6000);
        return null;
      } finally {
        state.refreshPromise = null;
      }
    })();
    state.refreshPromise = promise;
    return promise;
  }

  function schedule() {
    if (!q('#analysisConfig')?.classList.contains('active')) return;
    if (window.MCSUnifiedAnalysis?.state?.step !== 'check' && !host()) return;
    clearTimeout(state.timer);
    state.timer = setTimeout(() => refresh({silent:true}), 100);
  }

  function mountDock() {
    render();
    schedule();
  }

  window.addEventListener('mcs:engineering-context-changed', schedule);
  window.addEventListener('mcs:route-ready', schedule);
  document.addEventListener('mcs:analysis-check-mounted', mountDock);
  document.addEventListener('mcs-language-change', () => render());
  document.addEventListener('DOMContentLoaded', schedule, {once:true});
  window.MCSStandardValidation = {state, refresh, render, run, exportLogs, openTask, mountDock};
})();
