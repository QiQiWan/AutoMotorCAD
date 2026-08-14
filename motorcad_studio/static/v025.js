/* V0.25 page controllers + idempotent task submission UX. */
(() => {
  const runtime = () => window.MCSPageRuntime;

  function activeProjectPath(suffix='overview') {
    return state.activeProjectId ? `/app/projects/${encodeURIComponent(state.activeProjectId)}/${suffix}` : '/app/projects';
  }

  async function mountProjects(route, ctx) {
    await loadProjectManager(ctx); ctx.assertActive();
    if (route.trash) await showProjectTrash(true, ctx);
    ctx.assertActive();
    if (route.projectSettingsId) await openProjectEditor(route.projectSettingsId, ctx);
  }

  async function mountWorkspace(route, ctx) {
    await loadWorkspace(ctx); ctx.assertActive();
    if (!route.designId) return;
    await openWorkspaceDesign(route.designId, ctx); ctx.assertActive();
    if (route.revisionId) {
      selectWorkspaceRevision(route.revisionId);
      ctx.assertActive();
    }
    if (route.editRevision) {
      const opener = window.MCSRouter?.preferredRevisionEditor?.() || window.openRevisionEditorV024 || window.openRevisionEditorV020;
      if (typeof opener === 'function') await opener(ctx);
    }
  }

  async function mountTemplates(route, ctx) {
    renderTemplates();
    if (route.templateId) {
      const result = showTemplateDetail(route.templateId);
      if (result?.then) await result;
      ctx.assertActive();
    }
  }

  async function mountTaskSetup(route, ctx) {
    if (window.MCSDomainV025?.mountTaskSetup) await window.MCSDomainV025.mountTaskSetup(ctx);
    ctx.assertActive();
    window.MCSOperatorFlowV025?.activateTaskStep?.(route.step ?? 0);
    window.MCSModelGate?.render?.();
  }

  async function mountTasks(route, ctx) {
    await loadTasks(ctx); ctx.assertActive();
    if (route.taskId) await showTask(route.taskId, ctx);
    ctx.assertActive();
    ctx.interval(async () => {
      try {
        await loadTasks(ctx);
        if (route.taskId && ctx.active()) await showTask(route.taskId, ctx);
      } catch (error) {
        if (!runtime()?.isAbortError(error)) console.warn('task route refresh failed', error);
      }
    }, 5000);
  }

  async function mountMonitor(route, ctx) {
    const rows = await populateTaskSelectors(ctx); ctx.assertActive();
    let taskId = route.taskId || state.monitorTask || document.querySelector('#monitorTaskSelect')?.value || null;
    if (!taskId) taskId = rows.find(row => ['RUNNING','QUEUED','RECOVERING'].includes(row.status))?.id || null;
    if (!taskId) {
      closeTaskStream();
      const empty=document.querySelector('#monitorEmpty');
      if(empty) empty.textContent='当前项目没有需要监控的任务。提交计算后会自动进入这里。';
      return;
    }
    const select=document.querySelector('#monitorTaskSelect');if(select)select.value=taskId;
    await openMonitorTask(taskId, false, ctx);
  }

  async function mountResults(route, ctx) {
    setResultViewerMode('case');
    await loadResultViewerLanding(ctx); ctx.assertActive();
    if (!route.taskId) return;
    const taskSelect=document.querySelector('#viewerTaskSelect');if(taskSelect)taskSelect.value=route.taskId;
    await loadViewerCases(route.taskId, ctx); ctx.assertActive();
    if (!route.caseId) return;
    const caseSelect=document.querySelector('#viewerCaseSelect');if(caseSelect)caseSelect.value=route.caseId;
    await openCaseViewer(ctx);
  }

  async function mountAssets(route, ctx) {
    if (route.assetKind) state.domainAssetKindV021=route.assetKind;
    state.domainAssetIdV021=route.assetId||null;
    if (window.MCSDomainV025?.mountAssets) await window.MCSDomainV025.mountAssets(ctx);
  }

  async function mount(route, ctx) {
    if (!ctx?.active()) return;
    switch (route.tab) {
      case 'setup': await loadStartupSetup(false); break;
      case 'projects': await mountProjects(route,ctx); break;
      case 'dashboard': await loadDashboard(ctx); break;
      case 'templates': await mountTemplates(route,ctx); break;
      case 'workspace': await mountWorkspace(route,ctx); break;
      case 'simulationAssets': await mountAssets(route,ctx); break;
      case 'newTask': await mountTaskSetup(route,ctx); break;
      case 'tasks': await mountTasks(route,ctx); break;
      case 'monitor': await mountMonitor(route,ctx); break;
      case 'resultViewer': await mountResults(route,ctx); if(ctx.active())await loadAnalyticsLanding(); break;
      case 'dataFactory': await loadDataFactory(); break;
      case 'logs':
        await loadLogs(ctx);
        ctx.onDispose(()=>{
          if(state.realtime?.logs){state.realtime.logs.stop();state.realtime.logs=null}
          if(state.logStream){try{state.logStream.close()}catch{}state.logStream=null}
        });
        break;
      case 'system': await loadSystemOverview(); break;
      default: break;
    }
    if (ctx.active()) window.MCSOperatorFlowV025?.syncProjectShell?.(route.tab);
  }

  window.MCSRouteControllersV025={mount};

  // --- Task submit idempotency -------------------------------------------------
  // A single click creates a client submission key.  Network retries reuse it until
  // the task form changes.  The server persists the key and returns the original task
  // when the same request is retried after a lost response.
  state.taskSubmissionKeyV025 = state.taskSubmissionKeyV025 || null;
  function newSubmissionKey() {
    if (window.crypto?.randomUUID) return `SUB-${window.crypto.randomUUID()}`;
    return `SUB-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  function submissionKey() {
    if (!state.taskSubmissionKeyV025) state.taskSubmissionKeyV025=newSubmissionKey();
    return state.taskSubmissionKeyV025;
  }
  function invalidateSubmissionKey() { state.taskSubmissionKeyV025=null; }
  document.addEventListener('input',event=>{if(event.target.closest('#taskForm'))invalidateSubmissionKey()});
  document.addEventListener('change',event=>{if(event.target.closest('#taskForm'))invalidateSubmissionKey()});

  const previousCollectPayload=collectPayload;
  collectPayload=function(){const payload=previousCollectPayload();payload.submission_key=submissionKey();return payload};
  window.MCSSubmissionV025={current:submissionKey,invalidate:invalidateSubmissionKey};

  // Keep direct object links route-owned; avoid the old showTab + delayed-open pattern.
  document.addEventListener('click',event=>{
    const design=event.target.closest('[data-workspace-design]');
    if(design&&window.MCSRouter?.navigate&&state.activeProjectId){
      event.preventDefault();event.stopImmediatePropagation();
      window.MCSRouter.navigate(activeProjectPath(`designs/${encodeURIComponent(design.dataset.workspaceDesign)}`));
    }
  },true);
})();
