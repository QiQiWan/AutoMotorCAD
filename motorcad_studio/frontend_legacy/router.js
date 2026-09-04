/* V0.25 route-first History API router.
 *
 * URL is the source of navigation truth.  A route transition owns page loading,
 * cancellation and disposal through MCSPageRuntime.  Legacy tabs are presentation
 * targets only; they no longer initiate route-owned data loading.
 */
(() => {
  const stepSlugs=['baseline','scenario','method','outputs','review'];
  const stepNames=['基线','工况','计算方式','输出','检查提交'];
  const enc=encodeURIComponent,dec=decodeURIComponent;
  const clean=value=>value==null?'':enc(String(value));
  let started=false,revisionEditActive=false,templateDetailId=null;
  let lastStablePath=location.pathname;
  const applying=new Set();
  const activateTab=showTab;
  const engineeringContext=()=>window.MCSEngineeringContext?.get?.()||{};

  function isRouting(){return applying.size>0}
  function projectPath(suffix='overview'){const projectId=engineeringContext().projectId||state.activeProjectId;return projectId?`/app/projects/${clean(projectId)}/${suffix}`:'/app/projects'}
  function selectedViewerCase(){return state.viewer?.case?.id||document.querySelector('#viewerCaseSelect')?.value||null}
  function selectedViewerTask(){return document.querySelector('#viewerTaskSelect')?.value||state.analytics?.task_id||null}

  function routeForTab(tab){
    if(tab==='setup')return'/app/runtime';
    if(tab==='projects'){
      if(state.projectManagerTrashMode)return'/app/projects/trash';
      if(state.projectManagerEditorId)return`/app/projects/${clean(state.projectManagerEditorId)}/settings`;
      return'/app/projects';
    }
    if(tab==='logs')return'/app/issues';
    if(tab==='system')return'/app/system';
    const context=engineeringContext();
    if(!(context.projectId||state.activeProjectId))return'/app/projects';
    if(tab==='dashboard')return projectPath('overview');
    if(tab==='solutions')return projectPath('solutions');
    if(tab==='templates')return templateDetailId?projectPath(`designs/templates/${clean(templateDetailId)}`):projectPath('designs/templates');
    if(tab==='workspace'){
      const d=context.solutionId||state.workspaceDesign?.id,r=context.motorRevisionId||state.workspaceRevision?.id;
      if(!d)return projectPath('designs');
      if(!r)return projectPath(`designs/${clean(d)}`);
      const view=window.MCSDesignStore?.currentView?.()||(revisionEditActive?window.MCSDesignEditor?.state?.view:null)||window.MCSDesignViewer?.state?.view||'radial';
      const segments=window.MCSAppCore?.routeSegmentsForView?.(view)||['geometry','radial'];
      const tail=segments.map(clean).join('/');
      return projectPath(`designs/${clean(d)}/revisions/${clean(r)}/${tail}${revisionEditActive?'/edit':''}`);
    }
    if(tab==='analysisConfig'||tab==='simulationAssets'||tab==='newTask'||tab==='analysisWorkbench'){
      const analysisId=context.analysisId||null;
      return analysisId?projectPath(`simulation/analyses/${clean(analysisId)}`):projectPath('simulation/analyses');
    }
    if(tab==='tasks'){const taskId=context.taskId||state.selectedTask;return taskId?projectPath(`simulation/tasks/${clean(taskId)}`):projectPath('simulation/tasks')}
    if(tab==='monitor'){const taskId=context.taskId||state.monitorTask;return taskId?projectPath(`simulation/monitor/${clean(taskId)}`):projectPath('simulation/monitor')}
    if(tab==='resultViewer'){
      const bundleId=context.resultBundleId||window.MCSResultContext?.current?.().resultBundleId||null;
      if(bundleId)return projectPath(`results/bundles/${clean(bundleId)}`);
      const owned=window.MCSResultsWorkbench?.routeForCurrent?.();
      if(owned&&owned!==projectPath('results'))return owned;
      const task=selectedViewerTask(),caseId=selectedViewerCase();
      if(task&&caseId)return projectPath(`results/tasks/${clean(task)}/cases/${clean(caseId)}`);
      if(task)return projectPath(`results/tasks/${clean(task)}`);
      return projectPath('results');
    }
    if(tab==='dataFactory')return projectPath('data');
    return'/app/projects';
  }

  function parse(path){
    const parts=path.split('/').filter(Boolean);
    if(parts[0]!=='app')return{tab:null};
    if(parts[1]==='runtime')return{tab:'setup'};
    if(parts[1]==='issues')return{tab:'logs'};
    if(parts[1]==='system')return{tab:'system'};
    if(parts[1]!=='projects')return{tab:'projects'};
    if(!parts[2])return{tab:'projects'};
    if(parts[2]==='trash')return{tab:'projects',trash:true};
    const projectId=dec(parts[2]),rest=parts.slice(3);
    if(rest[0]==='settings')return{tab:'projects',projectSettingsId:projectId};
    if(!rest.length||rest[0]==='overview')return{tab:'dashboard',projectId};
    if(rest[0]==='solutions')return{tab:'solutions',projectId};
    if(rest[0]==='designs'){
      if(rest[1]==='templates')return{tab:'templates',projectId,templateId:rest[2]?dec(rest[2]):null};
      const revisionId=rest[2]==='revisions'&&rest[3]?dec(rest[3]):null;
      const tail=revisionId?rest.slice(4):[];
      const legacyEdit=tail[0]==='edit';
      const editRevision=legacyEdit||tail.includes('edit');
      const designSection=legacyEdit?null:(tail[0]&&tail[0]!=='edit'?dec(tail[0]):null);
      const designSubview=legacyEdit?null:(tail[1]&&tail[1]!=='edit'?dec(tail[1]):null);
      const designView=window.MCSAppCore?.viewForRoute?.(designSection,designSubview)||null;
      return{tab:'workspace',projectId,designId:rest[1]?dec(rest[1]):null,revisionId,editRevision,designSection,designSubview,designView};
    }
    if(rest[0]==='simulation'){
      if(rest[1]==='analyses')return{tab:'analysisConfig',projectId,analysisId:rest[2]?dec(rest[2]):null,analysisAction:rest[3]?dec(rest[3]):null,analysisStep:rest[4]?dec(rest[4]):null};
      if(rest[1]==='assets')return{tab:'analysisConfig',projectId,analysisAction:'configure',analysisStep:'inputs',legacyRedirect:true,legacyKind:'assets'};
      if(rest[1]==='setup'){const legacyStep=Math.max(0,stepSlugs.indexOf(rest[2]||'baseline')),mapped=['definition','operating','solver','solver','check'][legacyStep]||'definition';return{tab:'analysisConfig',projectId,analysisAction:'configure',analysisStep:mapped,legacyRedirect:true,legacyKind:'setup',step:legacyStep}};
      if(rest[1]==='tasks')return{tab:'tasks',projectId,taskId:rest[2]?dec(rest[2]):null};
      if(rest[1]==='monitor')return{tab:'monitor',projectId,taskId:rest[2]?dec(rest[2]):null};
    }
    if(rest[0]==='decision')return{tab:'resultViewer',projectId,resultsMode:'decision'};
    if(rest[0]==='results'){
      if(rest[1]==='case-compare')return{tab:'resultViewer',projectId,resultsMode:'caseCompare',caseCompareTaskId:rest[2]?dec(rest[2]):null,caseCompareCaseIds:rest[3]==='cases'&&rest[4]?dec(rest[4]).split(',').filter(Boolean):[],autoCaseCompare:rest[3]==='cases'&&Boolean(rest[4])};
      if(rest[1]==='compare')return{tab:'resultViewer',projectId,resultsMode:'compare',designId:rest[2]?dec(rest[2]):null,revisionIds:rest[3]==='revisions'&&rest[4]?dec(rest[4]).split(',').filter(Boolean):[],autoCompare:rest[3]==='revisions'&&Boolean(rest[4])};
      if(rest[1]==='optimization'){
        if(rest[2]==='tasks')return{tab:'resultViewer',projectId,resultsMode:'optimization',optimizationTaskId:rest[3]?dec(rest[3]):null};
        if(rest[2]==='analyses')return{tab:'resultViewer',projectId,resultsMode:'optimization',analysisId:rest[3]?dec(rest[3]):null};
        return{tab:'resultViewer',projectId,resultsMode:'optimization'};
      }
      if(rest[1]==='viewer')return{tab:'resultViewer',projectId,resultsMode:'case'};
      if(rest[1]==='bundles')return{tab:'resultViewer',projectId,resultsMode:'case',resultBundleId:rest[2]?dec(rest[2]):null};
      if(rest[1]==='tasks')return{tab:'resultViewer',projectId,resultsMode:'case',taskId:rest[2]?dec(rest[2]):null,caseId:rest[3]==='cases'&&rest[4]?dec(rest[4]):null,legacyResultIdentity:true};
      return{tab:'resultViewer',projectId,resultsMode:'overview'};
    }
    if(rest[0]==='data')return{tab:'dataFactory',projectId};
    return{tab:'dashboard',projectId};
  }

  function setUrl(path,replace=false){
    if(!path||location.pathname===path)return;
    history[replace?'replaceState':'pushState']({mcs:true},'',path);
    updateTitle(parse(path),path);
  }

  async function allowRouteChange(route,meta={}){
    try{
      if(typeof window.MCSNavigationTransaction?.prepare==='function')return (await window.MCSNavigationTransaction.prepare(route,{...meta,source:meta.source||'router:guard'}))!==false;
      if(typeof window.MCSDesignEditor?.prepareRouteChange==='function')return (await window.MCSDesignEditor.prepareRouteChange(route))!==false;
      return true;
    }catch(error){console.error('route leave guard failed',error);toast(`页面跳转检查失败：${error.message||error}`,'ERROR',8000);return false}
  }

  async function navigate(path,{replace=false,source='router:navigate'}={}){
    if(!path)return false;
    const route=parse(path),from=location.pathname;
    const commit=async()=>{
      if(location.pathname!==path)history[replace?'replaceState':'pushState']({mcs:true},'',path);
      return apply(path,{skipGuard:true});
    };
    if(typeof window.MCSNavigationTransaction?.run!=='function'){
      if(!(await allowRouteChange(route,{source,from,path})))return false;
      return commit();
    }
    return window.MCSNavigationTransaction.run({
      target:path,key:`route:${path}`,source,meta:{route,replace,from},
      prepare:()=>allowRouteChange(route,{source,from,path}),commit,
      rollback:()=>{if(lastStablePath&&location.pathname!==lastStablePath){history.replaceState({mcs:true},'',lastStablePath);updateTitle(parse(lastStablePath),lastStablePath)}}
    });
  }

  function updateTitle(route,path=location.pathname){
    const p=(state.workspaceProjects||[]).find(x=>x.id===(route?.projectId||state.activeProjectId));
    let label='MotorCAD Studio';
    if(path.includes('/simulation/analyses'))label='分析配置';
    else if(path.includes('/simulation/assets/'))label='仿真配置资产';
    else if(path.includes('/simulation/setup/'))label=`仿真配置 · ${stepNames[route?.step??state.taskWizardStepV019??0]||''}`;
    else if(path.includes('/designs/templates/'))label='模板详情';
    else if(path.endsWith('/designs/templates'))label='模板库';
    else if(path.endsWith('/solutions'))label='方案';
    else if(route?.editRevision)label='电机配置草稿';
    else if(path.includes('/designs'))label='电机配置';
    else if(path.includes('/simulation/tasks'))label='任务记录';
    else if(path.includes('/simulation/monitor'))label='仿真 · 实时求解';
    else if(path.includes('/decision'))label='工程决策';
    else if(path.includes('/results'))label='工程结果';
    else if(path.includes('/data'))label='数据';
    else if(path.endsWith('/overview'))label='项目概览';
    else if(path.endsWith('/settings'))label='项目基本信息';
    else if(path==='/app/projects/trash')label='项目回收站';
    else if(path==='/app/projects')label='项目管理';
    else if(path==='/app/runtime')label='运行环境';
    else if(path==='/app/issues')label='问题与日志';
    else if(path==='/app/system')label='系统诊断';
    document.title=`${label}${p?` · ${p.name}`:''} · MotorCAD Studio`;
  }

  async function hydrateProjectRoute(route,ctx){
    if(!route?.projectId)return null;
    const projectId=String(route.projectId);
    let project=(state.workspaceProjects||[]).find(row=>String(row.id)===projectId)||null;
    if(state.workspaceProject?.id&&String(state.workspaceProject.id)===projectId)project=state.workspaceProject;
    // Project-list rows are identity/count summaries. The motor workspace needs the
    // full designs/scenarios/experiments payload, so hydrate it once here and let the
    // page controller reuse it instead of issuing list + detail + detail requests.
    const needsWorkspaceDetail=route.tab==='workspace'&&!Array.isArray(project?.designs);
    if(!project||needsWorkspaceDetail){
      project=await api(`/api/projects/${clean(projectId)}`,ctx?.signal?{signal:ctx.signal,__mcsSilentProgress:true}:{__mcsSilentProgress:true});
      ctx?.assertActive?.();
      if(project){
        const rows=Array.isArray(state.workspaceProjects)?state.workspaceProjects:[];
        const index=rows.findIndex(row=>String(row.id)===projectId);
        if(index>=0)rows[index]=project;else rows.push(project);
        state.workspaceProjects=rows;
        state.projectManagerRows=state.projectManagerTrashMode?state.projectManagerRows:rows;
      }
    }
    if(!project){const error=new Error(`项目 ${projectId} 不存在或不可访问。`);error.status=404;throw error}
    window.MCSEngineeringContext?.setProject?.(project,{source:'router:hydrate-project'});
    if(!window.MCSEngineeringContext)state.activeProjectId=projectId;
    state.workspaceProject=project;
    if(typeof updateProjectNavState==='function')updateProjectNavState();
    if(typeof syncProjectContextSelectors==='function')syncProjectContextSelectors();
    return project;
  }


  function syncResultStageNav(route){
    if(route?.tab!=='resultViewer')return;
    const destination=route.resultsMode==='decision'?'decision':'viewer';
    document.body.dataset.resultsMode=route.resultsMode||'overview';
    document.querySelectorAll('[data-tab="resultViewer"][data-results-destination]').forEach(node=>{
      node.classList.toggle('active',node.dataset.resultsDestination===destination);
    });
  }

  function activateRouteTab(tab){
    state.routeOwnsLoadV025=true;
    try{activateTab(tab)}finally{state.routeOwnsLoadV025=false}
  }

  function prime(path=location.pathname){
    const route=parse(path==='/app'?'/app/projects':path);
    if(!route?.tab)return false;
    // Hard refresh must reveal the URL-owned page immediately. Do not call the
    // legacy showTab guard here because project hydration is asynchronous and the
    // in-memory activeProjectId is intentionally empty at this instant.
    document.documentElement.dataset.routeBoot='hydrating';
    document.body.dataset.routePrimed=route.tab;
    document.querySelectorAll('.tab').forEach(node=>node.classList.toggle('active',node.id===route.tab));
    document.querySelectorAll('[data-tab]').forEach(node=>node.classList.toggle('active',node.dataset.tab===route.tab));
    syncResultStageNav(route);
    updateTitle(route,path);
    return true;
  }

  function primeCurrent(){
    const path=location.pathname;
    if(path==='/app'||path.startsWith('/app/'))return prime(path);
    return false;
  }

  async function apply(path=location.pathname,{skipGuard=false}={}){
    let route=parse(path);if(!route.tab)return false;
    window.MCSEngineeringContext?.reconcileRoute?.(route,{source:'router:apply'});
    if(route.legacyRedirect&&route.projectId){
      const context=engineeringContext(),base=`/app/projects/${clean(route.projectId)}/simulation/analyses`,analysisId=context.analysisId||null;
      path=analysisId?`${base}/${clean(analysisId)}/configure/${clean(route.analysisStep||'definition')}`:base;
      history.replaceState({mcs:true},'',path);route=parse(path);
      window.MCSEngineeringContext?.reconcileRoute?.(route,{source:'router:legacy-normalize'});
    }
    if(!skipGuard&&!(await allowRouteChange(route,{source:'router:apply',path}))){
      if(lastStablePath&&location.pathname!==lastStablePath)history.replaceState({mcs:true},'',lastStablePath);
      updateTitle(parse(lastStablePath),lastStablePath);
      return false;
    }
    const ctx=window.MCSPageRuntime?.begin(route);if(!ctx)throw new Error('page runtime not loaded');
    applying.add(ctx.id);
    revisionEditActive=Boolean(route.editRevision);templateDetailId=route.templateId||null;document.body.classList.toggle('design-editing-v062',route.tab==='workspace'&&revisionEditActive);if(route.tab==='workspace')window.MCSDesignStore?.setContext?.({projectId:route.projectId||null,designId:route.designId||null,revisionId:route.revisionId||null,mode:revisionEditActive?'edit':'read',view:route.designView||window.MCSDesignStore?.currentView?.()||'radial'},{source:'router-apply'});
    try{
      if(route.projectId){
        // A deep link is authoritative. Hydrate its project from the backend instead
        // of treating an empty/stale in-memory catalog as proof that it disappeared.
        await hydrateProjectRoute(route,ctx);
        ctx.assertActive();
        if(route.projectId!==state.activeProjectId){
          state.routeOwnsLoadV025=true;
          try{await changeActiveProject(route.projectId)}finally{state.routeOwnsLoadV025=false}
          ctx.assertActive();
        }
      }
      if(route.step!==undefined)state.taskWizardStepV019=route.step;
      if(route.assetKind)state.domainAssetKindV021=route.assetKind;
      if(route.tab==='projects'){
        state.projectManagerEditorId=route.projectSettingsId||null;
        state.projectManagerTrashMode=Boolean(route.trash);
      }
      activateRouteTab(route.tab);
      syncResultStageNav(route);
      await window.MCSRouteControllers?.mount(route,ctx);
      ctx.assertActive();
      if(route.tab==='resultViewer'&&route.resultsMode==='case'&&(route.resultBundleId||route.taskId||route.caseId)){
        // Only identity-bearing case routes are canonicalized. The stable
        // /results/viewer landing route must not be hijacked by a stale bundle
        // left in the in-memory result context from an earlier visit.
        const resultContext=window.MCSResultContext?.current?.()||{};
        const canonical=resultContext.lineage?.canonical_routes?.results||null;
        const bundleId=resultContext.resultBundleId||engineeringContext().resultBundleId||null;
        const authoritativeProject=resultContext.projectId||engineeringContext().projectId||route.projectId||null;
        const target=canonical||(bundleId&&authoritativeProject?`/app/projects/${clean(authoritativeProject)}/results/bundles/${clean(bundleId)}`:null);
        if(target&&path!==target){path=target;history.replaceState({mcs:true},'',path);route=parse(path);}
      }
      if(route.tab==='workspace'){
        window.MCSDesignViewer?.applyRouteView?.(route);
        if(route.editRevision)window.MCSDesignEditor?.applyRouteView?.(route);
      }
      updateTitle(route,path);
      window.MCSPageRuntime.complete(ctx);
      document.documentElement.dataset.routeBoot='ready';
      lastStablePath=path;
      return true;
    }catch(error){
      if(window.MCSPageRuntime?.isAbortError?.(error))return false;
      if(error?.status===404&&route.projectId){
        window.MCSEngineeringContext?.invalidate?.('project',{source:'router:404'});setActiveProject(null);state.workspaceProject=null;
        toast('链接中的项目或工程对象已失效，已返回项目管理并停止后续请求。','WARNING',7000);
        if(location.pathname!=='/app/projects')return navigate('/app/projects',{replace:true});
      }
      window.MCSPageRuntime?.fail(ctx,error);
      document.documentElement.dataset.routeBoot='failed';
      console.error('route apply failed',route,error);
      toast(`页面加载失败：${error.message||error}`,'ERROR',8000);
      return false;
    }finally{
      applying.delete(ctx.id);
      state.routeOwnsLoadV025=false;
    }
  }

  // Legacy call sites now navigate by URL.  During a route transition the router may
  // still activate a tab without starting a nested navigation.
  showTab=function(id){
    if(!started||isRouting()){activateRouteTab(id);return Promise.resolve(true)}
    if(id!=='workspace')revisionEditActive=false;
    if(id!=='templates')templateDetailId=null;
    return navigate(routeForTab(id));
  };

  function wrap(name,after){
    const fn=window[name];if(typeof fn!=='function')return;
    window[name]=async function(...args){const result=await fn.apply(this,args);if(started&&!isRouting())after(...args);return result}
  }
  wrap('openWorkspaceDesign',()=>{revisionEditActive=false;setUrl(routeForTab('workspace'))});
  wrap('showTask',()=>setUrl(routeForTab('tasks')));
  wrap('openMonitorTask',()=>setUrl(routeForTab('monitor')));
  wrap('openProjectEditor',id=>setUrl(`/app/projects/${clean(id)}/settings`));
  wrap('showTemplateDetail',id=>{templateDetailId=id;setUrl(routeForTab('templates'))});
  wrap('openCaseViewer',()=>setUrl(routeForTab('resultViewer')));

  const previousSelect=window.selectWorkspaceRevision;
  if(typeof previousSelect==='function')window.selectWorkspaceRevision=function(...args){revisionEditActive=false;const result=previousSelect.apply(this,args);if(started&&!isRouting())setUrl(routeForTab('workspace'),true);return result};

  document.addEventListener('click',event=>{
    if(event.target.closest('#projectEditorClose')&&started&&!isRouting())navigate('/app/projects',{source:'project-editor:close'});
    if(event.target.closest('#closeTemplateDetail')&&started&&!isRouting()){templateDetailId=null;navigate(projectPath('designs/templates'),{source:'template-detail:close'})}
  });

  function preferredRevisionEditor(){return window.MCSDesignEditor?.open}

  function start(defaultTab='projects'){
    if(started)return;started=true;
    primeCurrent();
    window.addEventListener('popstate',()=>{
      const target=location.pathname,route=parse(target),fallback=lastStablePath;
      if(typeof window.MCSNavigationTransaction?.run!=='function')return apply(target);
      window.MCSNavigationTransaction.run({
        target,key:`pop:${target}`,source:'browser:popstate',meta:{route,from:fallback},
        prepare:()=>allowRouteChange(route,{source:'browser:popstate',from:fallback,path:target}),
        commit:()=>apply(target,{skipGuard:true}),
        rollback:()=>{if(fallback&&location.pathname!==fallback){history.replaceState({mcs:true},'',fallback);updateTitle(parse(fallback),fallback)}}
      }).catch(error=>console.error('popstate transaction failed',error));
    });
    const path=location.pathname;
    if(path==='/app'||path.startsWith('/app/'))return apply(path==='/app'?'/app/projects':path);
    return navigate(routeForTab(defaultTab),{replace:true});
  }

  function syncDesignView(view,{replace=true}={}){
    const context=engineeringContext(),projectId=context.projectId||state.activeProjectId,designId=context.solutionId||state.workspaceDesign?.id,revisionId=context.motorRevisionId||state.workspaceRevision?.id;
    if(!started||isRouting()||!projectId||!designId||!revisionId)return;
    const segments=window.MCSAppCore?.routeSegmentsForView?.(view)||['geometry','radial'];
    const base=projectPath(`designs/${clean(designId)}/revisions/${clean(revisionId)}/${segments.map(clean).join('/')}`);
    setUrl(`${base}${revisionEditActive?'/edit':''}`,replace);
  }
  function setRevisionEditMode(active,{view=null,replace=true}={}){
    revisionEditActive=Boolean(active);
    if(!started||isRouting())return;
    const target=view||window.MCSDesignStore?.currentView?.()||(revisionEditActive?window.MCSDesignEditor?.state?.view:null)||window.MCSDesignViewer?.state?.view||'radial';
    syncDesignView(target,{replace});
  }
  window.MCSRouter={start,apply,navigate,parse,routeForTab,setUrl,isRouting,prime,primeCurrent,preferredRevisionEditor,syncDesignView,setRevisionEditMode,hydrateProjectRoute,syncWizardStep(step){state.taskWizardStepV019=step;if(started&&!isRouting())navigate(routeForTab('analysisConfig'))}};
  // Some retained classic features intentionally call window.showTab. Export the
  // route-owned implementation into the sealed compatibility proxy so these calls
  // cannot silently turn into no-ops.
  window.showTab=showTab;
})();
