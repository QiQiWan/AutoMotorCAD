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
  const applying=new Set();
  const activateTab=showTab;

  function isRouting(){return applying.size>0}
  function projectPath(suffix='overview'){return state.activeProjectId?`/app/projects/${clean(state.activeProjectId)}/${suffix}`:'/app/projects'}
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
    if(!state.activeProjectId)return'/app/projects';
    if(tab==='dashboard')return projectPath('overview');
    if(tab==='templates')return templateDetailId?projectPath(`designs/templates/${clean(templateDetailId)}`):projectPath('designs/templates');
    if(tab==='workspace'){
      const d=state.workspaceDesign?.id,r=state.workspaceRevision?.id;
      if(!d)return projectPath('designs');
      if(!r)return projectPath(`designs/${clean(d)}`);
      return projectPath(`designs/${clean(d)}/revisions/${clean(r)}${revisionEditActive?'/edit':''}`);
    }
    if(tab==='simulationAssets'){const base=`simulation/assets/${clean(state.domainAssetKindV021||'scenarios')}`;return projectPath(state.domainAssetIdV021?`${base}/${clean(state.domainAssetIdV021)}`:base)}
    if(tab==='newTask')return projectPath(`simulation/setup/${stepSlugs[state.taskWizardStepV019||0]||'baseline'}`);
    if(tab==='tasks')return state.selectedTask?projectPath(`simulation/tasks/${clean(state.selectedTask)}`):projectPath('simulation/tasks');
    if(tab==='monitor')return state.monitorTask?projectPath(`simulation/monitor/${clean(state.monitorTask)}`):projectPath('simulation/monitor');
    if(tab==='resultViewer'){
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
    if(rest[0]==='designs'){
      if(rest[1]==='templates')return{tab:'templates',projectId,templateId:rest[2]?dec(rest[2]):null};
      return{tab:'workspace',projectId,designId:rest[1]?dec(rest[1]):null,revisionId:rest[2]==='revisions'&&rest[3]?dec(rest[3]):null,editRevision:rest[4]==='edit'};
    }
    if(rest[0]==='simulation'){
      if(rest[1]==='assets')return{tab:'simulationAssets',projectId,assetKind:rest[2]?dec(rest[2]):'scenarios',assetId:rest[3]?dec(rest[3]):null};
      if(rest[1]==='setup')return{tab:'newTask',projectId,step:Math.max(0,stepSlugs.indexOf(rest[2]||'baseline'))};
      if(rest[1]==='tasks')return{tab:'tasks',projectId,taskId:rest[2]?dec(rest[2]):null};
      if(rest[1]==='monitor')return{tab:'monitor',projectId,taskId:rest[2]?dec(rest[2]):null};
    }
    if(rest[0]==='results'){
      if(rest[1]==='tasks')return{tab:'resultViewer',projectId,taskId:rest[2]?dec(rest[2]):null,caseId:rest[3]==='cases'&&rest[4]?dec(rest[4]):null};
      return{tab:'resultViewer',projectId};
    }
    if(rest[0]==='data')return{tab:'dataFactory',projectId};
    return{tab:'dashboard',projectId};
  }

  function setUrl(path,replace=false){
    if(!path||location.pathname===path)return;
    history[replace?'replaceState':'pushState']({mcs:true},'',path);
    updateTitle(parse(path),path);
  }

  async function navigate(path,{replace=false}={}){
    if(!path)return false;
    if(location.pathname!==path)history[replace?'replaceState':'pushState']({mcs:true},'',path);
    return apply(path);
  }

  function updateTitle(route,path=location.pathname){
    const p=(state.workspaceProjects||[]).find(x=>x.id===(route?.projectId||state.activeProjectId));
    let label='MotorCAD Studio';
    if(path.includes('/simulation/assets/'))label='仿真配置资产';
    else if(path.includes('/simulation/setup/'))label=`仿真配置 · ${stepNames[route?.step??state.taskWizardStepV019??0]||''}`;
    else if(path.includes('/designs/templates/'))label='模板详情';
    else if(path.endsWith('/designs/templates'))label='模板库';
    else if(path.endsWith('/edit'))label='电机模型工作台';
    else if(path.includes('/designs'))label='模型';
    else if(path.includes('/simulation/tasks'))label='任务记录';
    else if(path.includes('/simulation/monitor'))label='仿真 · 实时求解';
    else if(path.includes('/results'))label='结果';
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

  function activateRouteTab(tab){
    state.routeOwnsLoadV025=true;
    try{activateTab(tab)}finally{state.routeOwnsLoadV025=false}
  }

  async function apply(path=location.pathname){
    const route=parse(path);if(!route.tab)return false;
    const ctx=window.MCSPageRuntime?.begin(route);if(!ctx)throw new Error('V0.25 page runtime not loaded');
    applying.add(ctx.id);
    revisionEditActive=Boolean(route.editRevision);templateDetailId=route.templateId||null;
    try{
      if(route.projectId&&Array.isArray(state.workspaceProjects)&&!state.workspaceProjects.some(p=>p.id===route.projectId)){
        setActiveProject(null);
        toast('路由中的项目已不存在或已移入回收站，已返回项目管理。','WARNING');
        return navigate('/app/projects',{replace:true});
      }
      if(route.projectId&&route.projectId!==state.activeProjectId){
        state.routeOwnsLoadV025=true;
        try{await changeActiveProject(route.projectId)}finally{state.routeOwnsLoadV025=false}
        ctx.assertActive();
      }
      if(route.step!==undefined)state.taskWizardStepV019=route.step;
      if(route.assetKind)state.domainAssetKindV021=route.assetKind;
      if(route.tab==='simulationAssets')state.domainAssetIdV021=route.assetId||null;
      if(route.tab==='tasks')state.selectedTask=route.taskId||null;
      if(route.tab==='monitor')state.monitorTask=route.taskId||null;
      if(route.tab==='projects'){
        state.projectManagerEditorId=route.projectSettingsId||null;
        state.projectManagerTrashMode=Boolean(route.trash);
      }
      activateRouteTab(route.tab);
      await window.MCSRouteControllersV025?.mount(route,ctx);
      ctx.assertActive();
      updateTitle(route,path);
      window.MCSPageRuntime.complete(ctx);
      return true;
    }catch(error){
      if(window.MCSPageRuntime?.isAbortError?.(error))return false;
      window.MCSPageRuntime?.fail(ctx,error);
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
  wrap('openRevisionEditorV020',()=>{revisionEditActive=true;setUrl(routeForTab('workspace'))});
  wrap('openRevisionEditorV024',()=>{revisionEditActive=true;setUrl(routeForTab('workspace'))});
  wrap('openCaseViewer',()=>setUrl(routeForTab('resultViewer')));

  const previousSelect=window.selectWorkspaceRevision;
  if(typeof previousSelect==='function')window.selectWorkspaceRevision=function(...args){revisionEditActive=false;const result=previousSelect.apply(this,args);if(started&&!isRouting())setUrl(routeForTab('workspace'),true);return result};

  document.addEventListener('click',event=>{
    if(event.target.closest('#projectEditorClose')&&started&&!isRouting())navigate('/app/projects');
    if(event.target.closest('#closeTemplateDetail')&&started&&!isRouting()){templateDetailId=null;navigate(projectPath('designs/templates'))}
    if(event.target.closest('#cancelRevisionEditV020')&&started&&!isRouting()){revisionEditActive=false;navigate(routeForTab('workspace'),{replace:true})}
  });

  function preferredRevisionEditor(){return window.openRevisionEditorV024||window.openRevisionEditorV020}

  function start(defaultTab='projects'){
    if(started)return;started=true;
    window.addEventListener('popstate',()=>apply(location.pathname));
    const path=location.pathname;
    if(path==='/app'||path.startsWith('/app/'))return apply(path==='/app'?'/app/projects':path);
    return navigate(routeForTab(defaultTab),{replace:true});
  }

  window.MCSRouter={start,apply,navigate,parse,routeForTab,setUrl,isRouting,preferredRevisionEditor,syncWizardStep(step){state.taskWizardStepV019=step;if(started&&!isRouting()&&document.querySelector('#newTask.tab.active'))navigate(routeForTab('newTask'))}};
})();
