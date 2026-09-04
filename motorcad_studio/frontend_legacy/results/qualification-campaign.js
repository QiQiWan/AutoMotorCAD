/* MotorCAD Studio V0.84 — Requirement-Aware Qualification Campaign + Adaptive Planning. */
(() => {
  const safe=value=>typeof esc==='function'?esc(value??''):String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>r?[...r.querySelectorAll(s)]:[];
  const pct=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(0)}%`:'—';
  const coverageLabel=s=>({SATISFIED:'已覆盖',AT_RISK:'裕度偏低',VIOLATED:'已违反',MISSING:'缺少证据',UNIT_MISMATCH:'单位冲突',REVIEW_ONLY:'仅供复核',UNMAPPED_EVIDENCE:'缺少验证映射',NOT_APPLICABLE:'不适用'}[s]||s||'—');
  const priorityClass=p=>String(p||'P2').toLowerCase();
  const state={overview:null,optimization:null};

  function shell(title='Qualification Campaign'){
    return `<article class="panel qualification-campaign-card"><div class="viewer-loading-v058"><span class="spinner-dot"></span><b>正在构建 ${safe(title)}…</b></div></article>`;
  }

  async function requestPreview(projectId,designRevisionId,candidateTaskId=null,candidateId=null){
    const body={design_revision_id:designRevisionId,include_satisfied:false,max_items:12};
    if(candidateTaskId&&candidateId){body.candidate_task_id=candidateTaskId;body.candidate_id=candidateId}
    const r=await api(`/api/projects/${encodeURIComponent(projectId)}/qualification-campaign/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    return r.proposal||r;
  }

  function coverageRows(proposal){
    const rows=proposal?.coverage?.requirements||[];
    return rows.filter(r=>r.coverage_status!=='SATISFIED').slice(0,8).map(r=>`<div class="qualification-gap-row ${String(r.coverage_status||'').toLowerCase()}"><span><b>${safe(r.label||r.metric_id)}</b><small>${safe(r.requirement_id)} · ${safe(r.kind)}</small></span><em>${safe(coverageLabel(r.coverage_status))}</em><small>${r.best_evidence?.margin_percent!=null?`margin ${Number(r.best_evidence.margin_percent).toFixed(2)}%`:'尚无正式裕度证据'}</small></div>`).join('');
  }

  function campaignItems(proposal,{interactive=true}={}){
    const rows=proposal?.items||[];
    if(!rows.length)return '<div class="help-empty compact"><b>当前没有需要新增的验证 Analysis</b><span>工程要求证据已覆盖，或缺少可自动映射的 Analysis Template。</span></div>';
    return rows.map((r,i)=>`<label class="qualification-plan-row ${priorityClass(r.priority)}"><input type="checkbox" data-qc-item="${safe(r.item_id)}" ${interactive&&i<4?'checked':''} ${interactive?'':'disabled'}><span><b>${safe(r.short_label||r.template_label)}</b><small>${safe(r.module)} · ${safe(r.recipe_id)} · 覆盖 ${(r.requirement_ids||[]).length} 项要求</small><small>${(r.metrics||[]).map(safe).join(' · ')}</small></span><em>${safe(r.priority)} · ${Number(r.priority_score||0).toFixed(1)}</em><small>${r.analysis_preview?.ready_to_create?'Smart Defaults 已可创建':'仍有关键输入需要工程师确认'}${r.analysis_preview?.physical_input_review_required?' · 物理边界需复核':''}</small></label>`).join('');
  }

  function adaptiveHtml(plan){
    if(!plan||plan.status==='NO_OPTIMIZATION_CONTEXT')return '<div class="qualification-adaptive-empty"><b>Adaptive Planning</b><span>选择 Optimization Candidate 后，系统会结合 Sensitivity 与 Requirement pressure 给出下一轮变量和预算建议。</span></div>';
    const focus=plan.focus_variables||[];
    return `<div class="qualification-adaptive"><div><span class="eyebrow">ADAPTIVE EXPERIMENT PLAN</span><b>${safe(plan.status)}</b><small>建议新增 ${safe(plan.budget?.recommended_additional_cases||0)} 个 Case · ${safe(plan.budget?.mode||'qualification_only')}</small></div><div class="qualification-focus-vars">${focus.slice(0,5).map(v=>`<span><b>${safe(v.variable_id)}</b><small>score ${Number(v.score||0).toFixed(1)}${v.low!=null&&v.high!=null?` · [${safe(v.low)}, ${safe(v.high)}] ${safe(v.unit||'')}`:''}</small></span>`).join('')||'<small>当前没有可用 SensitivityStudy；先补齐资格证据或运行敏感性分析。</small>'}</div></div>`;
  }

  function render(host,proposal,{title='工程资格证据与验证计划',interactive=true,activeCampaign=null}={}){
    const c=proposal?.coverage?.summary||{};
    const req=proposal?.requirement_set||{};
    const unmapped=proposal?.unmapped_requirements||[];
    host.innerHTML=`<article class="panel qualification-campaign-card ${proposal?.status==='COMPLETE'?'complete':'attention'}"><div class="section-head"><div><span class="eyebrow">QUALIFICATION CAMPAIGN · REQUIREMENT-AWARE</span><h3>${safe(title)}</h3><p>从当前 Engineering Requirement Revision 反推缺失证据；系统只提出验证计划，未经确认不会自动提交 Motor-CAD 任务。</p></div><div class="actions"><span class="status ${proposal?.status==='COMPLETE'?'formal':'review'}">${proposal?.status==='COMPLETE'?'证据覆盖完成':'需要验证'}</span></div></div><div class="qualification-kpis"><div><span>正式覆盖率</span><b>${pct(c.formal_coverage_percent)}</b></div><div><span>证据缺口</span><b>${safe(c.gap_count||0)}</b></div><div><span>硬性违反</span><b>${safe(c.violated_count||0)}</b></div><div><span>待复核</span><b>${safe((c.review_only_count||0)+(c.at_risk_count||0))}</b></div></div><div class="qualification-grid"><section><h4>Evidence Coverage Matrix</h4>${coverageRows(proposal)||'<div class="help-empty compact"><b>当前适用要求已正式覆盖</b><span>继续保持 Requirement Revision 与运行证据一致。</span></div>'}</section><section><h4>Qualification Plan</h4><div class="qualification-plan-list">${campaignItems(proposal,{interactive})}</div></section></div>${unmapped.length?`<div class="qualification-unmapped"><b>需要人工定义验证方法</b><span>${unmapped.map(r=>`${safe(r.label||r.metric_id)} (${safe(r.requirement_id)})`).join(' · ')}</span></div>`:''}${adaptiveHtml(proposal?.adaptive_experiment_plan)}<footer class="qualification-footer"><small>Requirement Rev.${safe(req.revision||'—')} · ${safe(String(req.content_hash||'').slice(0,12))} · Proposal ${safe(String(proposal?.proposal_hash||'').slice(0,12))}</small>${activeCampaign?`<small>当前 Campaign Rev.${safe(activeCampaign.revision)} · ${safe(String(activeCampaign.content_hash||'').slice(0,12))}</small>`:''}${interactive&&proposal?.items?.length?`<div class="qualification-materialize-controls"><label><input type="checkbox" data-qc-create-analyses> 同时创建已确认的 Analysis Revision</label><button type="button" class="primary" data-qc-materialize>冻结 Qualification Campaign</button></div>`:''}</footer><div data-qc-status></div></article>`;
  }

  function bindMaterialize(host,ctx){
    const button=q('[data-qc-materialize]',host);if(!button)return;
    button.addEventListener('click',async()=>{
      const selected=qa('[data-qc-item]:checked',host).map(x=>x.dataset.qcItem).filter(Boolean);
      if(!selected.length)return toast('至少选择一个 Qualification Plan 条目','WARNING');
      const p=ctx.proposal,req=p.requirement_set||{},status=q('[data-qc-status]',host),create=Boolean(q('[data-qc-create-analyses]',host)?.checked);
      button.disabled=true;if(status)status.textContent=create?'正在冻结 Campaign 并创建 Analysis Revision…':'正在冻结 Qualification Campaign…';
      try{
        const r=await api(`/api/projects/${encodeURIComponent(ctx.projectId)}/qualification-campaign`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({design_revision_id:ctx.designRevisionId,expected_requirement_revision_id:req.revision_id,expected_requirement_content_hash:req.content_hash,expected_proposal_hash:p.proposal_hash,selected_item_ids:selected,candidate_task_id:ctx.candidateTaskId||null,candidate_id:ctx.candidateId||null,create_analysis_revisions:create,name:'Requirement qualification campaign',notes:'Accepted from Qualification Campaign preview'})});
        toast(`Qualification Campaign Rev.${r.campaign?.revision||''} 已冻结`,'SUCCESS');
        await ctx.reload();
      }catch(error){if(status)status.textContent=`Campaign 创建失败：${error.message||error}`;toast(`Qualification Campaign 创建失败：${error.message||error}`,'ERROR',9000)}finally{button.disabled=false}
    });
  }

  async function mountOverview(host,{projectId,designRevisionId}){
    if(!host)return;if(!designRevisionId){host.innerHTML='<article class="panel help-empty"><b>Qualification Campaign 等待 Design Revision</b><span>完成一次 ResultBundle-backed 计算后，系统会从对应 Design Revision 规划资格验证。</span></article>';return}
    host.innerHTML=shell();
    const reload=async()=>{
      try{
        const [proposal,active]=await Promise.all([requestPreview(projectId,designRevisionId),api(`/api/projects/${encodeURIComponent(projectId)}/qualification-campaign`)]);
        state.overview={proposal,active:active.campaign||null};render(host,proposal,{activeCampaign:active.campaign||null});bindMaterialize(host,{projectId,designRevisionId,proposal,reload});
      }catch(error){host.innerHTML=`<article class="panel help-empty"><b>Qualification Campaign 读取失败</b><span>${safe(error.message||error)}</span></article>`}
    };await reload();
  }

  async function mountOptimization(host,{projectId,designRevisionId,taskId,candidates=[]}){
    if(!host||!designRevisionId||!taskId)return;
    const selectable=candidates.filter(c=>c.candidate_id);
    let candidateId=selectable.find(c=>c.requirement_evaluation?.formal_requirement_qualified===false)?.candidate_id||selectable[0]?.candidate_id||null;
    const wrapper=document.createElement('article');wrapper.className='panel qualification-campaign-optimization';host.replaceChildren(wrapper);
    const reload=async()=>{
      if(!candidateId){wrapper.innerHTML='<div class="help-empty compact"><b>尚无 CandidateResultSet</b><span>形成候选后再规划 Requirement-aware Qualification。</span></div>';return}
      wrapper.innerHTML=shell('Candidate Qualification');
      try{
        const proposal=await requestPreview(projectId,designRevisionId,taskId,candidateId);state.optimization={proposal,candidateId};
        render(wrapper,proposal,{title:`候选 ${candidateId} · Qualification Campaign`,interactive:true});
        const card=q('.qualification-campaign-card',wrapper);if(card&&selectable.length>1){const selector=document.createElement('label');selector.className='qualification-candidate-selector';selector.innerHTML=`候选<select data-qc-candidate>${selectable.map(c=>`<option value="${safe(c.candidate_id)}" ${String(c.candidate_id)===String(candidateId)?'selected':''}>${safe(c.candidate_id)} · ${c.requirement_evaluation?.formal_requirement_qualified?'Requirement PASS':'需要补证据'}</option>`).join('')}</select>`;q('.section-head',card)?.appendChild(selector);q('[data-qc-candidate]',selector)?.addEventListener('change',async e=>{candidateId=e.target.value;await reload()})}
        bindMaterialize(wrapper,{projectId,designRevisionId,candidateTaskId:taskId,candidateId,proposal,reload});
      }catch(error){wrapper.innerHTML=`<div class="help-empty"><b>Candidate Qualification Planning 失败</b><span>${safe(error.message||error)}</span></div>`}
    };await reload();
  }

  window.MCSQualificationCampaign=Object.freeze({mountOverview,mountOptimization,requestPreview,state});
})();
