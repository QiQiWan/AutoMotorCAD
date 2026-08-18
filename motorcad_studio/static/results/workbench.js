/* MotorCAD Studio V0.69 — route-owned Results & Optimization Workbench shell. */
(() => {
  const q=(s,r=document)=>r.querySelector(s);
  const qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=value=>typeof esc==='function'?esc(value??''):String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const wb={project:null,route:null,ctx:null,mode:'overview'};
  const projectPath=suffix=>`/app/projects/${encodeURIComponent(state.activeProjectId)}/results${suffix?`/${suffix}`:''}`;
  const navigate=path=>window.MCSRouter?.navigate?MCSRouter.navigate(path):false;
  const active=ctx=>!ctx||window.MCSPageRuntime?.isContextActive?.(ctx)!==false;

  function hideLegacyHeader(){q('#resultsLegacyHeaderV069')?.classList.add('hidden');q('#viewerBatchMode')?.classList.add('hidden')}
  function setLegacyCase(visible){q('#viewerCaseMode')?.classList.toggle('hidden',!visible)}
  function modeForRoute(route){
    if(route?.resultsMode==='caseCompare')return'caseCompare';
    if(route?.resultsMode==='compare')return'compare';
    if(route?.resultsMode==='optimization')return'optimization';
    if(route?.taskId||route?.caseId)return'case';
    return'overview';
  }
  function nativeBadge(payload){const n=payload?.native_parity||{};const pct=Number(n.native_workstation_qualification_percent||0);const complete=Boolean(n.complete);return `<span class="results-native-v069 ${complete?'ready':'pending'}">Motor-CAD 原生资格 ${complete?'已完成':`${pct.toFixed(0)}%`}</span>`}
  function renderShell(){
    const host=q('#resultsWorkbenchV069');if(!host||!wb.project)return;
    const mode=wb.mode;
    host.innerHTML=`<section class="results-shell-v069 panel">
      <div class="results-title-v069"><div><span class="eyebrow">V0.69 · RESULTS & OPTIMIZATION</span><h2>结果与优化工作台</h2><p>从可信结果审查、Design Revision 横向比较，到参数研究、Pareto/NSGA-II 与候选方案固化使用同一条工程血缘。</p></div>${nativeBadge(wb.project)}</div>
      <nav class="results-nav-v069" aria-label="结果与优化工作台">
        <button type="button" data-results-mode-v069="overview" class="${mode==='overview'?'active':''}"><b>结果总览</b><small>任务与可信结果</small></button>
        <button type="button" data-results-mode-v069="case" class="${mode==='case'?'active':''}"><b>单 Case</b><small>原生结果与 FEA</small></button>
        <button type="button" data-results-mode-v069="caseCompare" class="${mode==='caseCompare'?'active':''}"><b>Case 比较</b><small>同一 Task 工程结果对照</small></button>
        <button type="button" data-results-mode-v069="compare" class="${mode==='compare'?'active':''}"><b>版本比较</b><small>Design Revision 横向对照</small></button>
        <button type="button" data-results-mode-v069="optimization" class="${mode==='optimization'?'active':''}"><b>参数研究与优化</b><small>Sweep · DOE · Pareto · NSGA-II</small></button>
      </nav>
    </section>`;
    qa('[data-results-mode-v069]',host).forEach(button=>button.addEventListener('click',()=>{
      const mode=button.dataset.resultsModeV069;
      if(mode==='overview')navigate(projectPath(''));
      else if(mode==='case')navigate(projectPath('tasks'));
      else if(mode==='caseCompare')navigate(projectPath('case-compare'));
      else if(mode==='compare')navigate(projectPath('compare'));
      else navigate(projectPath('optimization'));
    }));
  }
  function taskStatus(row){const usable=Number(row.usable_cases||0);const total=Number(row.case_count||0);const kind=row.optimization?` · ${safe(row.experiment_mode)}`:'';return `${safe(row.status||'—')} · 可用 ${usable}/${total}${kind}`}
  function renderOverview(){
    const host=q('#resultsWorkbenchBodyV069');if(!host)return;const p=wb.project,s=p.summary||{};
    setLegacyCase(false);
    const recent=(p.tasks||[]).slice(0,8);
    host.innerHTML=`<section class="results-overview-v069">
      <div class="results-metrics-v069">
        ${[['已完成任务',s.completed_tasks||0],['可用 Case',s.usable_cases||0],['Design Revision',s.design_revisions||0],['参数研究/优化',s.optimization_tasks||0]].map(([k,v])=>`<div><span>${safe(k)}</span><b>${safe(v)}</b></div>`).join('')}
      </div>
      <div class="results-overview-grid-v069">
        <article class="panel"><div class="section-head"><div><h3>最近计算结果</h3><p>质量状态优先于任务完成状态；正式工程判断应使用 VALID/WARNING 且原生资格适用的结果。</p></div></div>
          <div class="results-task-list-v069">${recent.map(row=>`<button type="button" data-result-task-v069="${safe(row.id)}" data-result-optimization-v069="${row.optimization?'1':'0'}"><span><b>${safe(row.name||row.id)}</b><small>${taskStatus(row)}</small></span><span>打开 →</span></button>`).join('')||'<div class="help-empty">当前项目尚无计算结果。</div>'}</div>
        </article>
        <article class="panel"><div class="section-head"><div><h3>下一步工程动作</h3><p>结果工作台只提供具备明确血缘的动作，不从不同工况的结果推导伪比较。</p></div></div>
          <div class="results-actions-v069">
            <button type="button" data-result-action-v069="case-compare" ${s.usable_cases<2?'disabled':''}><b>比较计算 Case</b><span>${s.usable_cases>=2?'在同一 Task 内比较结果、参数与工况差异':'至少需要两个可用 Case'}</span></button>
            <button type="button" data-result-action-v069="compare" ${s.design_revisions<2?'disabled':''}><b>比较 Design Revision</b><span>${s.design_revisions>=2?'检查尺寸、材料和同工况性能变化':'至少需要两个 Revision'}</span></button>
            <button type="button" data-result-action-v069="optimization" ${s.analyses<1?'disabled':''}><b>开展参数研究 / 优化</b><span>${s.analyses?'从已有 Analysis Revision 冻结工况、求解器与输出':'先创建 Analysis'}</span></button>
          </div>
        </article>
      </div>
    </section>`;
    qa('[data-result-task-v069]',host).forEach(button=>button.addEventListener('click',()=>{
      const id=button.dataset.resultTaskV069;
      navigate(button.dataset.resultOptimizationV069==='1'?projectPath(`optimization/tasks/${encodeURIComponent(id)}`):projectPath(`tasks/${encodeURIComponent(id)}`));
    }));
    qa('[data-result-action-v069]',host).forEach(button=>button.addEventListener('click',()=>navigate(projectPath(button.dataset.resultActionV069))));
  }
  async function renderMode(route,ctx){
    const body=q('#resultsWorkbenchBodyV069');if(body)body.innerHTML='';
    setLegacyCase(wb.mode==='case');
    if(wb.mode==='overview')return renderOverview();
    if(wb.mode==='caseCompare')return window.MCSCaseCompareV069?.mount?.(body,wb.project,route,ctx);
    if(wb.mode==='compare')return window.MCSRevisionCompareV069?.mount?.(body,wb.project,route,ctx);
    if(wb.mode==='optimization')return window.MCSOptimizationWorkbenchV069?.mount?.(body,wb.project,route,ctx);
    if(wb.mode==='case')return window.MCSCaseViewerV070?.mount?.(route,ctx);
  }
  async function mount(route,ctx){
    hideLegacyHeader();wb.route=route;wb.ctx=ctx;wb.mode=modeForRoute(route);
    const projectId=route?.projectId||state.activeProjectId;if(!projectId)return{legacyCase:false};
    try{
      wb.project=await api(`/api/projects/${encodeURIComponent(projectId)}/results-workbench`,ctx?.signal?{signal:ctx.signal}:{});
      if(!active(ctx))return{legacyCase:false,aborted:true};
      renderShell();await renderMode(route,ctx);
      return{legacyCase:false,mode:wb.mode};
    }catch(error){
      if(window.MCSPageRuntime?.isAbortError?.(error))return{legacyCase:false,aborted:true};
      const host=q('#resultsWorkbenchBodyV069');if(host)host.innerHTML=`<div class="panel help-empty"><b>结果工作台加载失败</b><span>${safe(error.message||error)}</span></div>`;
      throw error;
    }
  }
  function routeForCurrent(){
    if(wb.mode==='caseCompare'){
      const compare=window.MCSCaseCompareV069?.state;
      if(compare?.taskId&&compare?.selected?.size>=2)return projectPath(`case-compare/${encodeURIComponent(compare.taskId)}/cases/${encodeURIComponent([...compare.selected].join(','))}`);
      if(compare?.taskId)return projectPath(`case-compare/${encodeURIComponent(compare.taskId)}`);
      return projectPath('case-compare');
    }
    if(wb.mode==='compare'){
      const compare=window.MCSRevisionCompareV069?.state;
      if(compare?.designId&&compare?.selected?.length>=2)return projectPath(`compare/${encodeURIComponent(compare.designId)}/revisions/${encodeURIComponent(compare.selected.join(','))}`);
      if(compare?.designId)return projectPath(`compare/${encodeURIComponent(compare.designId)}`);
      return projectPath('compare');
    }
    if(wb.mode==='optimization')return projectPath('optimization');
    if(wb.mode==='case')return window.MCSCaseViewerV070?.routeForCurrent?.()||projectPath('tasks');
    return projectPath('');
  }
  window.MCSResultsWorkbenchV069={mount,state:wb,routeForCurrent,projectPath,navigate,renderShell};
})();
