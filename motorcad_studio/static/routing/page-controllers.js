/* V0.76 canonical routed page controllers.
 *
 * Five visible stage owners have one lifecycle each. Supporting pages such as task
 * history, monitor, logs, runtime and data tools remain secondary capabilities.
 */
(() => {
  const runtime = () => window.MCSPageRuntime;
  const store = () => window.MCSEngineeringContext;
  let activeStage = null;

  function activeProjectPath(suffix='overview') {
    const projectId=store()?.get?.().projectId||state.activeProjectId;
    return projectId ? `/app/projects/${encodeURIComponent(projectId)}/${suffix}` : '/app/projects';
  }

  async function mountProjects(route, ctx) {
    await loadProjectManager(ctx); ctx.assertActive();
    if (route.trash) await showProjectTrash(true, ctx);
    ctx.assertActive();
    if (route.projectSettingsId) await openProjectEditor(route.projectSettingsId, ctx);
  }

  async function mountMotor(route, ctx) {
    await loadWorkspace(ctx); ctx.assertActive();
    if (!route.designId) return;
    await openWorkspaceDesign(route.designId, ctx); ctx.assertActive();
    if (route.revisionId) {
      selectWorkspaceRevision(route.revisionId);
      ctx.assertActive();
    }
    const design=state.workspaceDesign||null,revision=state.workspaceRevision||null;
    if(design)store()?.setSolution?.(design,{source:'page:motor'});
    if(revision)store()?.setMotorRevision?.(revision,{solution:design,source:'page:motor'});
    if (route.editRevision) {
      const opener = window.MCSRouter?.preferredRevisionEditor?.() || window.MCSDesignEditor?.open;
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

  async function hydrateExecutionLineage(taskOrId, ctx) {
    const taskId=taskOrId&&typeof taskOrId==='object'?taskOrId.id:taskOrId;
    if(!taskId)return null;
    await window.MCSResultContext?.resolveTask?.(taskId,ctx,{source:'page:task-lineage'});ctx.assertActive();
    return taskOrId&&typeof taskOrId==='object'?taskOrId:null;
  }

  async function mountTasks(route, ctx) {
    await loadTasks(ctx); ctx.assertActive();
    if (route.taskId) {
      const task=await showTask(route.taskId, ctx);ctx.assertActive();
      if(task)await hydrateExecutionLineage(task,ctx);
    }
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
    let taskId = route.taskId || store()?.get?.().taskId || state.monitorTask || document.querySelector('#monitorTaskSelect')?.value || null;
    if (!taskId) taskId = rows.find(row => ['RUNNING','QUEUED','RECOVERING'].includes(row.status))?.id || null;
    if (!taskId) {
      closeTaskStream();
      const empty=document.querySelector('#monitorEmpty');
      if(empty) empty.textContent='\u5f53\u524d\u9879\u76ee\u6ca1\u6709\u9700\u8981\u76d1\u63a7\u7684\u4efb\u52a1\u3002\u63d0\u4ea4\u8ba1\u7b97\u540e\u4f1a\u81ea\u52a8\u8fdb\u5165\u8fd9\u91cc\u3002';
      return;
    }
    await hydrateExecutionLineage(taskId,ctx);ctx.assertActive();
    const select=document.querySelector('#monitorTaskSelect');if(select)select.value=taskId;
    await openMonitorTask(taskId, false, ctx);
  }

  async function mountResults(route, ctx) {
    if(route.resultBundleId){await window.MCSResultContext?.resolveBundle?.(route.resultBundleId,ctx,{source:'page:results-bundle'});ctx.assertActive();}
    else if(route.caseId){await window.MCSResultContext?.resolveCase?.(route.caseId,ctx,{source:'page:results-case'});ctx.assertActive();}
    else if(route.taskId){await window.MCSResultContext?.resolveTask?.(route.taskId,ctx,{source:'page:results-task'});ctx.assertActive();}
    const resultIdentity=window.MCSResultContext?.current?.()||{};
    if(route.resultBundleId){route.taskId=route.taskId||resultIdentity.taskId||null;route.caseId=route.caseId||resultIdentity.caseId||null;}
    await window.MCSResultsWorkbench?.mount?.(route,ctx);
    ctx.assertActive();
  }

  const fiveStageControllers={
    project:{
      tabs:['dashboard'],
      async enter(){store()?.setStage?.('project',{source:'page:enter'});},
      async mount(route,ctx){await loadDashboard(ctx);ctx.assertActive();},
      leave(){},
    },
    solution:{
      tabs:['solutions'],
      async enter(){store()?.setStage?.('solution',{source:'page:enter'});},
      async mount(route,ctx){await window.MCSCanonicalFlow?.mountSolutions?.(ctx);ctx.assertActive();},
      leave(){},
    },
    motor:{
      tabs:['workspace'],
      async enter(){store()?.setStage?.('motor',{source:'page:enter'});},
      mount:mountMotor,
      leave(){window.MCSDesignViewer?.dispose?.();},
    },
    analysis:{
      tabs:['analysisConfig'],
      async enter(){store()?.setStage?.('analysis',{source:'page:enter'});},
      async mount(route,ctx){await window.MCSUnifiedAnalysis?.mount?.(route,ctx);ctx.assertActive();},
      leave(){window.MCSUnifiedAnalysis?.unmount?.();},
    },
    results:{
      tabs:['resultViewer'],
      async enter(){store()?.setStage?.('results',{source:'page:enter'});},
      mount:mountResults,
      leave(){},
    },
  };
  const stageByTab=Object.fromEntries(Object.entries(fiveStageControllers).flatMap(([stage,controller])=>controller.tabs.map(tab=>[tab,stage])));

  async function mountCanonical(stage,route,ctx){
    const controller=fiveStageControllers[stage];if(!controller)return;
    activeStage=stage;document.body.dataset.canonicalStage=stage;
    window.dispatchEvent(new CustomEvent('mcs:canonical-page-enter',{detail:{stage,tab:route.tab,route}}));
    await controller.enter?.(route,ctx);ctx.assertActive();
    ctx.onDispose(()=>{try{controller.leave?.(route,ctx)}finally{window.dispatchEvent(new CustomEvent('mcs:canonical-page-leave',{detail:{stage,tab:route.tab,route}}));if(activeStage===stage)activeStage=null;if(document.body.dataset.canonicalStage===stage)delete document.body.dataset.canonicalStage}});
    await controller.mount?.(route,ctx);ctx.assertActive();
    window.dispatchEvent(new CustomEvent('mcs:canonical-page-mounted',{detail:{stage,tab:route.tab,route}}));
  }

  async function mountSupport(route,ctx){
    const parentStage=store()?.stageForTab?.(route.tab);if(parentStage)store()?.setStage?.(parentStage,{source:'page:support'});
    switch(route.tab){
      case 'setup': await loadStartupSetup(false); break;
      case 'projects': await mountProjects(route,ctx); break;
      case 'templates': await mountTemplates(route,ctx); break;
      case 'tasks': await mountTasks(route,ctx); break;
      case 'monitor': await mountMonitor(route,ctx); break;
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
  }

  async function mount(route, ctx) {
    if (!ctx?.active()) return;
    const stage=stageByTab[route.tab]||null;
    if(stage)await mountCanonical(stage,route,ctx);else await mountSupport(route,ctx);
    // Readiness is supplemental shell state. Waiting for it here made otherwise
    // rendered routes appear 2+ seconds slower in the uploaded runtime logs.
    // Refresh in the background and re-sync the shell only if this route is still
    // active; canonical page content no longer blocks on overview readiness.
    if (ctx.active()) window.MCSOperatorFlow?.syncProjectShell?.(route.tab);
    if (ctx.active() && route.projectId && window.MCSEngineeringWorkflow?.refresh) {
      Promise.resolve(window.MCSEngineeringWorkflow.refresh(route.projectId,{silent:true}))
        .then(()=>{if(ctx.active())window.MCSOperatorFlow?.syncProjectShell?.(route.tab)})
        .catch(error=>{if(ctx.active())console.warn('workflow readiness background refresh failed',error)});
    }
  }

  const routeControllers={mount};
  window.MCSFiveStagePageControllers={controllers:fiveStageControllers,stageForTab:tab=>stageByTab[tab]||null,get activeStage(){return activeStage}};
  window.MCSRouteControllers=routeControllers;

  // Keep direct object links route-owned; avoid the old showTab + delayed-open pattern.
  document.addEventListener('click',event=>{
    const design=event.target.closest('[data-workspace-design]');
    if(design&&window.MCSRouter?.navigate&&state.activeProjectId){
      event.preventDefault();event.stopImmediatePropagation();
      window.MCSRouter.navigate(activeProjectPath(`designs/${encodeURIComponent(design.dataset.workspaceDesign)}`));
    }
  },true);
})();
