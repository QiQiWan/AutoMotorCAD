/* Current canonical engineering workflow cockpit, run center and failure center. */
(() => {
  const state={projectId:null,payload:null,loading:false,lastAt:0,timer:null,pollTimer:null};
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>[...(r?.querySelectorAll?.(s)||[])];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const route=p=>window.MCSRouter?.navigate?.(p)||null;
  const apiCall=(path,opts={})=>window.api?window.api(path,opts):fetch(path,{headers:{'Content-Type':'application/json'},...opts}).then(async r=>{if(!r.ok)throw new Error(await r.text());return r.json()});
  const label={COMPLETE:'已完成',CURRENT:'当前',RUNNING:'计算中',ATTENTION:'需处理',BLOCKED:'未解锁',PENDING:'待进行'};
  const stageTab={project:'dashboard',solution:'solutions',motor:'workspace',analysis:'analysisConfig',results:'resultViewer'};

  function currentContext(){return window.MCSEngineeringContext?.get?.()||{};}
  function contextLine(){
    const c=currentContext(),parts=[];
    if(c.solutionId)parts.push(`方案 ${String(c.solutionId).slice(0,10)}`);
    if(c.motorRevisionId)parts.push(`电机 ${String(c.motorRevisionId).slice(0,10)}`);
    if(c.analysisId)parts.push(`分析 ${String(c.analysisId).slice(0,10)}`);
    if(c.resultBundleId)parts.push(`结果 ${String(c.resultBundleId).slice(0,10)}`);
    return parts.join(' · ');
  }
  function actionButton(action,extra=''){
    if(!action)return '';
    return `<button type="button" class="${action.kind==='primary'?'primary':''} ${extra}" data-workflow-action-route="${esc(action.route||'')}" ${action.endpoint?`data-workflow-action-endpoint="${esc(action.endpoint)}" data-workflow-action-method="${esc(action.method||'POST')}" data-workflow-action-body="${esc(JSON.stringify(action.body||{}))}"`:''}>${esc(action.label||'继续')}</button>`;
  }
  function bindActions(root=document){
    qa('[data-workflow-action-route]',root).forEach(btn=>{if(btn.dataset.workflowBound)return;btn.dataset.workflowBound='1';btn.addEventListener('click',async()=>{
      const endpoint=btn.dataset.workflowActionEndpoint;
      try{
        if(endpoint){btn.disabled=true;const body=btn.dataset.workflowActionBody||'{}';await apiCall(endpoint,{method:btn.dataset.workflowActionMethod||'POST',body});window.toast?.('已提交恢复操作','SUCCESS',5000);await refresh(state.projectId,{force:true});}
        const target=btn.dataset.workflowActionRoute;if(target)route(target);
      }catch(error){btn.disabled=false;window.toast?.(`操作失败：${error.message||error}`,'ERROR',8000)}
    })});
  }
  function renderStageNav(payload){
    const byId=new Map((payload.stages||[]).map(row=>[row.id,row]));
    qa('[data-project-stage]').forEach(btn=>{
      const row=byId.get(btn.dataset.projectStage);if(!row)return;
      btn.dataset.stageStatus=row.status||'PENDING';btn.title=`${row.label} · ${label[row.status]||row.status}\n${row.summary||''}`;
      btn.classList.toggle('workflow-complete-v081a',row.status==='COMPLETE');
      btn.classList.toggle('workflow-current-v081a',['CURRENT','RUNNING','ATTENTION'].includes(row.status));
      let chip=q('.workflow-stage-chip-v081a',btn);if(!chip){chip=document.createElement('small');chip.className='workflow-stage-chip-v081a';btn.appendChild(chip)}chip.textContent=label[row.status]||row.status;
    });
  }
  function renderCue(payload){
    const host=q('#projectWorkflowCueV081A');if(!host)return;
    const current=(payload.stages||[]).find(x=>x.id===payload.current_stage)||payload.stages?.[0];
    const ctx=contextLine();
    host.classList.remove('hidden');
    host.innerHTML=`<div class="workflow-cue-main-v081a"><span class="workflow-progress-ring-v081a">${Number(payload.completion_percent||0)}%</span><div><b>当前：${esc(current?.label||'项目')}</b><small>${esc(current?.summary||'')}</small>${ctx?`<em>${esc(ctx)}</em>`:''}</div></div><div class="workflow-cue-actions-v081a"><span>${Number(payload.completed_stage_count||0)}/5 阶段完成</span>${actionButton(payload.next_action)}</div>`;
    bindActions(host);
  }
  function renderOverview(payload){
    const host=q('#engineeringWorkflowOverviewV081A');if(!host)return;
    host.innerHTML=`<div class="workflow-stage-grid-v081a">${(payload.stages||[]).map((row,index)=>`<button type="button" class="workflow-stage-card-v081a status-${esc(row.status)}" data-workflow-action-route="${esc(row.route)}"><span>${index+1}</span><div><b>${esc(row.label)}</b><small>${esc(label[row.status]||row.status)} · ${esc(row.summary||'')}</small>${row.blockers?.length?`<em>${esc(row.blockers[0])}</em>`:''}</div></button>`).join('')}</div><div class="workflow-primary-next-v081a"><div><b>${payload.completion_percent===100?'工程主流程已形成结果':'建议下一步'}</b><small>${esc((payload.stages||[]).find(x=>x.id===payload.current_stage)?.summary||'')}</small></div>${actionButton(payload.next_action)}</div>`;
    bindActions(host);
  }
  function taskCard(row,kind){
    const issue=(row.failed_cases||0)+(row.invalid_cases||0)+(row.unfinished_cases||0);
    return `<article class="run-item-v081a ${kind}"><div class="run-item-head-v081a"><div><b>${esc(row.name)}</b><small>${esc(row.id)}</small></div><span class="run-status-v081a">${esc(row.status)}</span></div><div class="run-progress-v081a"><i style="width:${Math.max(0,Math.min(100,Number(row.progress||0)))}%"></i></div><div class="run-meta-v081a"><span>${row.usable_cases||0}/${row.case_count||0} 可用 Case</span>${issue?`<span class="warn">${issue} 项需处理</span>`:''}${row.result_bundle_count?`<span>${row.result_bundle_count} 个结果</span>`:''}</div>${row.error?`<p>${esc(String(row.error).slice(0,180))}</p>`:''}<div class="actions">${actionButton(row.primary_action)}${actionButton(row.recovery_action)}</div></article>`;
  }
  function renderRunCenter(payload){
    const host=q('#runCenterV081A');if(!host)return;const run=payload.run_center||{},sum=run.summary||{};
    const groups=[['active','正在运行',run.active||[]],['attention','需要处理',run.attention||[]],['complete','最近完成',run.recent_completed||[]]];
    const nonEmpty=groups.filter(x=>x[2].length);
    host.innerHTML=`<div class="run-center-summary-v081a"><span><b>${sum.active||0}</b> 运行中</span><span><b>${sum.attention||0}</b> 需处理</span><span><b>${sum.completed||0}</b> 已完成</span></div>${nonEmpty.length?nonEmpty.map(([kind,title,rows])=>`<section class="run-group-v081a"><h4>${title}</h4><div class="run-items-v081a">${rows.slice(0,3).map(row=>taskCard(row,kind)).join('')}</div></section>`).join(''):`<div class="workflow-empty-v081a"><b>当前没有运行记录</b><span>从“分析配置”完成检查并提交后，任务会自动出现在这里。</span></div>`}`;
    bindActions(host);
  }
  function failureCard(row){
    const cases=(row.case_ids||[]).filter(Boolean);
    const caseText=cases.length?`Case ${cases.map(id=>esc(String(id).slice(0,10))).join('、')}`:'任务级故障';
    return `<article class="failure-item severity-${esc(String(row.severity||'ERROR').toLowerCase())}"><div class="failure-item-head"><div><span>${esc(row.category_label||'待诊断')}</span><b>${esc(row.task_name||row.task_id||'任务')}</b></div><small>${Number(row.case_count||0)} 项</small></div><div class="failure-evidence"><small>${esc(row.stage||'未标注阶段')} · ${caseText}</small><p>${esc(row.summary||'任务需要处理')}</p>${row.evidence&&row.evidence!==row.summary?`<pre>${esc(row.evidence)}</pre>`:''}</div><div class="actions">${actionButton(row.recommended_action)}${actionButton(row.recovery_action)}</div></article>`;
  }
  function renderFailureCenter(payload){
    const host=q('#failureCenter');if(!host)return;const center=payload.failure_center||{},sum=center.summary||{},items=center.items||[];
    const categories=(sum.categories||[]).map(row=>`<span><b>${Number(row.count||0)}</b> ${esc(row.label)}</span>`).join('');
    host.innerHTML=items.length?`<div class="failure-center-summary"><span><b>${Number(sum.affected_tasks||0)}</b> 个受影响任务</span><span><b>${Number(sum.open_issues||0)}</b> 个待处理项</span>${categories}</div><div class="failure-items">${items.slice(0,8).map(failureCard).join('')}</div>`:`<div class="workflow-empty-v081a failure-clear"><b>没有需要处理的失败项</b><span>失败、超时、取消和质量无效 Case 会在这里按根因自动聚合。</span></div>`;
    bindActions(host);
  }
  function render(payload){if(!payload)return;window.MCSGlobalWorkflowTruth?.ingest?.(payload);renderStageNav(payload);renderCue(payload);renderOverview(payload);renderRunCenter(payload);renderFailureCenter(payload);}
  async function refresh(projectId,{force=false,silent=false}={}){
    projectId=projectId||currentContext().projectId||window.state?.activeProjectId;if(!projectId)return null;
    if(state.loading)return state.payload;if(!force&&state.projectId===projectId&&Date.now()-state.lastAt<1200){render(state.payload);return state.payload}
    state.loading=true;
    try{const payload=await apiCall(`/api/projects/${encodeURIComponent(projectId)}/workflow-truth`);state.projectId=projectId;state.payload=payload;state.lastAt=Date.now();render(payload);clearTimeout(state.pollTimer);if((payload.run_center?.summary?.active||0)>0)state.pollTimer=setTimeout(()=>refresh(projectId,{force:true,silent:true}),5000);return payload}
    catch(error){if(!silent)window.toast?.(`工程流程状态读取失败：${error.message||error}`,'WARNING',6000);return null}
    finally{state.loading=false}
  }
  function schedule(){clearTimeout(state.timer);state.timer=setTimeout(()=>refresh(null,{force:true,silent:true}),120)}
  window.addEventListener('mcs:engineering-context-changed',schedule);
  window.addEventListener('mcs:canonical-page-mounted',schedule);
  window.MCSEngineeringWorkflow={state,refresh,render,renderFailureCenter,stageTab};
})();
