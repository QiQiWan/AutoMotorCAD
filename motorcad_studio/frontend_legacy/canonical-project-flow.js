/* Canonical information architecture owner.
 * The visible project workflow has exactly five stages:
 * Project -> Solution -> Motor Configuration -> Analysis Configuration -> Results.
 */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stageLabels={project:['1','项目'],solution:['2','方案'],motor:['3','电机配置'],analysis:['4','分析配置'],results:['5','结果查看']};
  let renderToken=0;

  function removeLegacyFlowControls(){
    ['#projectSecondaryNav','#motorcadContextNavV046','#engineeringContextBarV029','#engineerFlowBarV030'].forEach(selector=>q(selector)?.remove());
  }

  function syncShell(){
    removeLegacyFlowControls();
    qa('#dashboard .operator-overview-grid,#dashboard .project-overview-lower').forEach(node=>node.classList.remove('engineer-hidden-v060'));
    qa('#projectShell [data-project-stage]').forEach(button=>{
      const row=stageLabels[button.dataset.projectStage];
      if(!row)return;
      const number=button.querySelector('span');if(number)number.textContent=row[0];
      let label=button.querySelector('b');
      if(!label){label=document.createElement('b');button.appendChild(label)}
      label.textContent=row[1];
      [...button.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE&&node.textContent.trim()).forEach(node=>node.remove());
    });
  }

  function latestRevision(design){return (design?.revisions||[]).slice().sort((a,b)=>Number(b.revision||0)-Number(a.revision||0))[0]||null}
  function typeLabel(design){return design?.motor_type_id||design?.motor_family||design?.family_id||'Motor'}

  async function openSolutionCreator(){
    const projectId=window.MCSEngineeringContext?.get?.().projectId||state.activeProjectId||null;
    if(!projectId)return typeof toast==='function'&&toast('请先进入一个项目。','WARNING');
    const path=`/app/projects/${encodeURIComponent(projectId)}/designs/templates`;
    if(window.MCSRouter?.navigate)return window.MCSRouter.navigate(path,{source:'solution:create'});
    if(typeof showTab==='function')return showTab('templates');
    if(typeof window.showTab==='function')return window.showTab('templates');
    window.MCSPageRuntime?.report?.('FRONTEND_ACTION_UNAVAILABLE','ERROR','新建方案缺少可用导航处理器。',{action:'create-solution',project_id:projectId});
    return false;
  }

  async function openMotorConfiguration(design){
    if(!design?.id||!state.activeProjectId)return;
    const revision=latestRevision(design);
    window.MCSEngineeringContext?.setSolution?.(design,{source:'canonical:motor'});
    if(revision)window.MCSEngineeringContext?.setMotorRevision?.(revision,{solution:design,source:'canonical:motor'});
    else if(!window.MCSEngineeringContext){state.workspaceDesign=design;state.workspaceRevision=null}
    const path=`/app/projects/${encodeURIComponent(state.activeProjectId)}/designs/${encodeURIComponent(design.id)}`;
    if(window.MCSRouter?.navigate)return window.MCSRouter.navigate(path);
    if(typeof window.showTab==='function'){window.showTab('workspace');return window.openWorkspaceDesign?.(design.id)}
  }

  async function openAnalysisConfiguration(design){
    if(!design?.id||!state.activeProjectId)return;
    const revision=latestRevision(design);
    window.MCSEngineeringContext?.setSolution?.(design,{source:'canonical:analysis'});
    if(revision)window.MCSEngineeringContext?.setMotorRevision?.(revision,{solution:design,source:'canonical:analysis'});
    else if(!window.MCSEngineeringContext){state.workspaceDesign=design;state.workspaceRevision=null}
    const current=window.MCSEngineeringContext?.get?.()||{};
    const path=current.analysisId?`/app/projects/${encodeURIComponent(state.activeProjectId)}/simulation/analyses/${encodeURIComponent(current.analysisId)}`:`/app/projects/${encodeURIComponent(state.activeProjectId)}/simulation/analyses`;
    if(window.MCSRouter?.navigate)return window.MCSRouter.navigate(path);
    return window.showTab?.('analysisConfig');
  }

  async function deleteSolution(design){
    const projectId=window.MCSEngineeringContext?.get?.().projectId||state.activeProjectId||null;
    if(!projectId||!design?.id)return false;
    const approved=window.StudioDialog?.confirm?await StudioDialog.confirm({
      key:`canonical-solution-delete:${design.id}`,title:'删除方案？',
      message:`将删除“${design.name||design.id}”及其未被分析、任务或工程证据引用的电机版本。存在引用时系统会阻止删除。`,
      confirmText:'删除方案',danger:true,
    }):false;
    if(!approved)return false;
    const button=q(`[data-canonical-delete="${CSS.escape(design.id)}"]`);
    try{
      if(button){button.disabled=true;button.textContent='删除中…'}
      await api(`/api/projects/${encodeURIComponent(projectId)}/solutions/${encodeURIComponent(design.id)}`,{method:'DELETE'});
      const current=window.MCSEngineeringContext?.get?.()||{};
      if(current.solutionId===design.id)window.MCSEngineeringContext?.setSolution?.(null,{source:'canonical:delete'});
      if(state.workspaceDesign?.id===design.id){state.workspaceDesign=null;state.workspaceRevision=null}
      toast?.('方案已删除。','SUCCESS',4500);
      await mountSolutions();
      return true;
    }catch(error){
      const detail=error?.detail?.message||error?.message||String(error);
      toast?.(`方案删除失败：${detail}`,'ERROR',8500);
      if(button){button.disabled=false;button.textContent='删除方案'}
      return false;
    }
  }

  function renderSolutions(project,designs){
    const metrics=q('#solutionMetricsCanonical'),list=q('#solutionListCanonical');if(!metrics||!list)return;
    const revisions=designs.reduce((n,row)=>n+(row.revisions||[]).length,0);
    const families=new Set(designs.map(typeLabel).filter(Boolean));
    metrics.innerHTML=[['方案',designs.length],['电机配置版本',revisions],['电机类型',families.size],['当前项目',project?.name||'—']].map(([label,value])=>`<div class="metric-card"><span>${safe(label)}</span><b>${safe(value)}</b></div>`).join('');
    if(!designs.length){
      list.innerHTML=`<article class="panel canonical-empty-solution"><span class="eyebrow">从方案开始</span><h3>当前项目还没有方案</h3><p>先建立一个方案，再进入电机配置维护几何、绕组和材料。分析配置只引用已保存的电机版本。</p><button type="button" class="primary" data-canonical-create-solution>＋ 新建第一个方案</button></article>`;
    }else{
      list.innerHTML=designs.map(design=>{const rev=latestRevision(design),count=(design.revisions||[]).length;return `<article class="panel canonical-solution-card" data-solution-id="${safe(design.id)}"><header><div><span class="eyebrow">方案</span><h3>${safe(design.name||design.id)}</h3><small>${safe(design.id)}</small></div><span class="solution-type">${safe(typeLabel(design))}</span></header><div class="solution-facts"><div><span>模板 / 来源</span><b>${safe(design.template_id||design.source_kind||'默认模型')}</b></div><div><span>配置版本</span><b>${count?`${count} 个电机版本`:'尚无电机版本'}</b></div><div><span>当前版本</span><b>${rev?`Rev.${safe(rev.revision)}`:'—'}</b></div></div><footer><button type="button" class="danger-quiet" data-canonical-delete="${safe(design.id)}">删除方案</button><span class="canonical-solution-actions-v0916"><button type="button" data-canonical-analysis="${safe(design.id)}" ${rev?'':'disabled'}>分析配置</button><button type="button" class="primary" data-canonical-motor="${safe(design.id)}">电机配置</button></span></footer></article>`}).join('');
    }
    qa('[data-canonical-create-solution]',list).forEach(button=>button.addEventListener('click',openSolutionCreator));
    qa('[data-canonical-motor]',list).forEach(button=>button.addEventListener('click',()=>openMotorConfiguration(designs.find(row=>row.id===button.dataset.canonicalMotor))));
    qa('[data-canonical-analysis]',list).forEach(button=>button.addEventListener('click',()=>openAnalysisConfiguration(designs.find(row=>row.id===button.dataset.canonicalAnalysis))));
    qa('[data-canonical-delete]',list).forEach(button=>button.addEventListener('click',()=>deleteSolution(designs.find(row=>row.id===button.dataset.canonicalDelete))));
  }

  async function mountSolutions(ctx=null){
    syncShell();
    if(!state.activeProjectId){window.showTab?.('projects');return []}
    const token=++renderToken;
    const options=ctx?.signal?{signal:ctx.signal}:{};
    const project=await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`,options);
    if(ctx&&!window.MCSPageRuntime?.isContextActive?.(ctx))return [];
    if(token!==renderToken)return [];
    if(window.MCSEngineeringContext)window.MCSEngineeringContext.setProject(project,{source:'canonical:solutions'});else state.workspaceProject=project;
    const summaries=project.designs||[];
    const settled=await Promise.allSettled(summaries.map(row=>api(`/api/solutions/${encodeURIComponent(row.id)}`,options)));
    if(ctx&&!window.MCSPageRuntime?.isContextActive?.(ctx))return [];
    if(token!==renderToken)return [];
    const designs=settled.map((entry,index)=>entry.status==='fulfilled'?entry.value:{...summaries[index],revisions:[]});
    state.canonicalSolutions=designs;
    renderSolutions(project,designs);
    if(typeof syncProjectContextSelectors==='function')syncProjectContextSelectors();
    if(typeof updateProjectNavState==='function')updateProjectNavState();
    window.MCSOperatorFlow?.syncProjectShell?.('solutions');
    syncShell();
    return designs;
  }

  q('#createSolutionCanonical')?.addEventListener('click',openSolutionCreator);
  q('#refreshSolutionsCanonical')?.addEventListener('click',()=>mountSolutions());
  q('#workspaceToAnalysisCanonical')?.addEventListener('click',()=>{
    const design=state.workspaceDesign,revision=state.workspaceRevision;
    if(!design||!revision)return typeof toast==='function'&&toast('请先选择方案及已保存的电机版本。','WARNING');
    window.MCSEngineeringContext?.setMotorRevision?.(revision,{solution:design,source:'canonical:workspace-to-analysis'});
    openAnalysisConfiguration(design);
  });
  window.addEventListener('mcs:route-start',syncShell);
  window.addEventListener('mcs:route-ready',()=>queueMicrotask(syncShell));
  document.addEventListener('DOMContentLoaded',syncShell,{once:true});
  syncShell();
  window.MCSCanonicalFlow={mountSolutions,syncShell,openSolutionCreator,deleteSolution};
})();
