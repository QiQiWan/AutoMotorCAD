/* MotorCAD Studio V0.81-D — Engineering Result Interpretation + Baseline-first Results owner. */
(() => {
  const q=(s,r=document)=>r.querySelector(s);
  const qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=value=>typeof esc==='function'?esc(value??''):String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const wb={project:null,route:null,ctx:null,mode:'overview'};
  const currentProjectId=()=>window.MCSResultContext?.current?.().projectId||window.MCSEngineeringContext?.get?.().projectId||state.activeProjectId;
  const projectPath=suffix=>`/app/projects/${encodeURIComponent(currentProjectId())}/results${suffix?`/${suffix}`:''}`;
  const navigate=path=>window.MCSRouter?.navigate?MCSRouter.navigate(path):false;
  const active=ctx=>!ctx||window.MCSPageRuntime?.isContextActive?.(ctx)!==false;

  function hideLegacyHeader(){q('#resultsLegacyHeaderV069')?.classList.add('hidden');q('#viewerBatchMode')?.classList.add('hidden')}
  function setLegacyCase(visible){q('#viewerCaseMode')?.classList.toggle('hidden',!visible)}
  function modeForRoute(route){
    if(route?.resultsMode==='caseCompare')return'caseCompare';
    if(route?.resultsMode==='compare')return'compare';
    if(route?.resultsMode==='optimization')return'optimization';
    if(route?.resultBundleId||route?.taskId||route?.caseId)return'case';
    return'overview';
  }
  function nativeBadge(payload){const n=payload?.native_closure||payload?.native_parity||{};const pct=Number(n.native_workstation_qualification_percent||0);const complete=Boolean(n.complete);return `<span class="results-native-v069 ${complete?'ready':'pending'}">Motor-CAD 原生资格 ${complete?'已完成':`${pct.toFixed(0)}%`}</span>`}
  function renderShell(){
    const host=q('#resultsWorkbenchV069');if(!host||!wb.project)return;
    const mode=wb.mode;
    document.body.dataset.resultsMode=mode;
    ['#engineeringDecisionCockpitV086R','#engineeringScorecardV087D','#engineeringEvidenceAdvancedV086R'].forEach(selector=>q(selector)?.classList.toggle('hidden',mode!=='overview'));
    host.innerHTML=`<section class="results-shell-v069 panel">
      <div class="results-title-v069"><div><span class="eyebrow">工程结果</span><h2>结果与工程判断</h2><p>优先展示关键工程指标、可信度和下一步工程动作。</p></div>${nativeBadge(wb.project)}</div>
      <nav class="results-nav-v069" aria-label="结果与优化工作台">
        <button type="button" data-results-mode-v069="overview" class="${mode==='overview'?'active':''}"><b>工程决策</b><small>结论 · 要求 · 下一步</small></button>
        <button type="button" data-results-mode-v069="case" class="${mode==='case'?'active':''}"><b>结果查看</b><small>工况 · 曲线 · 场数据</small></button>
        <button type="button" data-results-mode-v069="caseCompare" class="${mode==='caseCompare'?'active':''}"><b>工况比较</b><small>同一任务内结果对照</small></button>
        <button type="button" data-results-mode-v069="compare" class="${mode==='compare'?'active':''}"><b>版本比较</b><small>电机版本横向对照</small></button>
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
  function metricById(metrics,id){return (metrics||[]).find(row=>String(row.id)===String(id))||null}
  function fmtMetric(row){if(!row||row.value==null)return '—';const n=Number(row.value);return `${Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:3}):safe(row.value)}${row.unit?` ${safe(row.unit)}`:''}`}
  function motorRouteForReference(ref){if(!ref?.design_revision_id)return null;for(const design of wb.project?.designs||[]){const rev=(design.revisions||[]).find(row=>String(row.id)===String(ref.design_revision_id));if(rev)return `/app/projects/${encodeURIComponent(currentProjectId())}/designs/${encodeURIComponent(design.id)}/revisions/${encodeURIComponent(rev.id)}/geometry/radial`}return null}
  function engineeringInsight(ref,metrics,summary,comparison){
    if(!ref)return `<article class="panel engineering-insight-v081a"><div class="section-head"><div><span class="eyebrow">工程判断</span><h3>还没有可解释的工程结果</h3><p>完成一次计算后，这里会先给出工程结论，再进入波形和场数据。</p></div></div></article>`;
    const trust=ref.trust||{},levels=trust.levels||[],blocking=levels.filter(row=>row.blocking&&String(row.status||'').toUpperCase()!=='PASS');
    const formal=trust.formal_recommendation===true||String(trust.engineering_status||'').toUpperCase()==='QUALIFIED';
    const title=formal?'可用于正式工程判断':blocking.length?'结果需要处理后再用于决策':'结果可查看，当前资格建议复核';
    const facts=[['shaft_torque_nm','轴端转矩'],['efficiency_percent','效率'],['torque_ripple_percent','转矩脉动'],['winding_max_temperature_c','绕组最高温度']].map(([id,label])=>{const row=metricById(metrics,id);return row?`<div><span>${label}</span><b>${fmtMetric(row)}</b></div>`:''}).filter(Boolean);
    const losses=[['copper_loss_w','铜耗'],['stator_iron_loss_w','定子铁耗'],['magnet_loss_w','磁体损耗']].map(([id,label])=>({row:metricById(metrics,id),label})).filter(x=>Number.isFinite(Number(x.row?.value)));losses.sort((a,b)=>Number(b.row.value)-Number(a.row.value));if(losses[0])facts.push(`<div><span>当前主要损耗项</span><b>${safe(losses[0].label)} · ${fmtMetric(losses[0].row)}</b></div>`);
    const blockers=blocking.slice(0,2).map(row=>`<li>${safe(row.message||row.label||row.id)}</li>`).join('');const motorRoute=motorRouteForReference(ref);
    const deltaRows=(comparison?.metrics||[]).filter(row=>row?.absolute!=null).slice(0,4);
    const deltaHtml=deltaRows.length?`<div class="engineering-insight-delta-v081a"><div><b>${safe(comparison?.label||'相对可比结果')}</b><small>仅在结果可比性检查通过后显示，不跨工况直接做数值结论。</small></div><div class="engineering-insight-delta-grid-v081a">${deltaRows.map(row=>{const abs=Number(row.absolute),rel=Number(row.relative_percent);const sign=abs>0?'+':'';return `<span><small>${safe(row.label||row.id)}</small><b>${sign}${Number.isFinite(abs)?abs.toLocaleString(undefined,{maximumFractionDigits:3}):safe(row.absolute)}${row.unit?` ${safe(row.unit)}`:''}</b>${Number.isFinite(rel)?`<em>${rel>0?'+':''}${rel.toFixed(2)}%</em>`:''}</span>`}).join('')}</div></div>`:'';
    return `<article class="panel engineering-insight-v081a ${formal?'formal':'attention'}"><div class="section-head"><div><span class="eyebrow">工程判断</span><h3>${title}</h3><p>${formal?'当前计算结果和可信度证据允许进入版本比较或优化判断。':blocking.length?'先处理下面的可信度问题，再用于正式版本结论。':'结果数据已经形成，建议结合可信度和 Motor-CAD 证据继续确认。'}</p></div><div class="actions"><button type="button" data-insight-open-result-v081a>查看详细结果</button>${motorRoute?`<button type="button" data-insight-motor-v081a data-route="${safe(motorRoute)}">返回对应电机配置</button>`:''}</div></div><div class="engineering-insight-facts-v081a">${facts.join('')||'<div><span>关键指标</span><b>当前计算结果未提供常用标量</b></div>'}</div>${deltaHtml}${blockers?`<ul class="engineering-insight-blockers-v081a">${blockers}</ul>`:''}</article>`;
  }
  function renderOverview(){
    const host=q('#resultsWorkbenchBodyV069');if(!host)return;const p=wb.project,s=p.summary||{},e=p.engineering_overview||{};
    setLegacyCase(false);
    const recent=e.recent_results||[],ref=e.reference_case||null,metrics=e.primary_metrics||[],comparison=e.reference_comparison||null;
    const metricCards=window.MCSResultsTrust?.renderMetricCards?.(metrics,{limit:8})||'';
    const trust=ref?.trust||null;
    const trustPanel=window.MCSResultsTrust?.renderLadder?.(trust)||'<div class="result-trust-empty-v073d">尚无可用计算工况，完成一次计算后建立结果可信度。</div>';
    const refMeta=ref?`<div class="results-reference-meta-v073d"><span>工况 ${safe(ref.id)}</span><span>${safe(ref.analysis||'—')}</span><span>${safe(ref.solver_mode||'—')}</span><span>计算结果 ${safe(String(ref.result_bundle_hash||'').slice(0,12))}</span><span>执行计划 ${safe(String(ref.execution_plan_hash||'').slice(0,12))}</span></div>`:'';
    const interpretationHtml=window.MCSEngineeringInterpretation?.render?.(e,ref)||engineeringInsight(ref,metrics,s,comparison);
    host.innerHTML=`<section class="results-overview-v069">
      ${interpretationHtml}
      <div data-qualification-campaign-overview></div>
      <article class="panel"><div class="section-head"><div><span class="eyebrow">关键工程指标</span><h3>参考工况关键工程指标</h3><p>${ref?'以下指标来自同一计算工况，不跨工况拼接。':'当前项目还没有可作为参考的计算结果。'}</p></div>${ref?`<button type="button" data-open-reference-v073d>打开参考工况</button>`:''}</div>
        <div class="results-engineering-kpis-v073d">${metricCards||'<div class="help-empty"><b>暂无工程指标</b><span>完成一次计算后显示转矩、效率、损耗、温度等指标。</span></div>'}</div>${refMeta}
      </article>
      <div class="results-reference-v073d"><article class="panel"><div class="section-head"><div><h3>结果可信度</h3><p>单工况、工况比较和版本比较使用同一套可信度评价。</p></div></div>${trustPanel}</article>
        <article class="panel"><div class="section-head"><div><h3>运行上下文</h3><p>这些数量用于说明当前结果规模。</p></div></div><div class="results-operational-stats-v073d">
          <div><span>完成任务</span><b>${safe(s.completed_tasks||0)}</b><small>任务</small></div><div><span>有结果工况</span><b>${safe(e.result_bundle_case_count||0)}</b><small>近期范围</small></div><div><span>正式资格工况</span><b>${safe(e.qualified_case_count||0)}</b><small>当前范围</small></div><div><span>电机版本</span><b>${safe(s.design_revisions||0)}</b><small>版本</small></div>
        </div></article></div>
      <div class="results-overview-grid-v069">
        <article class="panel"><div class="section-head"><div><h3>最近工程结果</h3><p>每一项都显示工程指标与统一可信度状态。</p></div></div>
          <div class="results-task-list-v069">${recent.map(row=>{const badge=window.MCSResultsTrust?.renderBadge?.(row.trust)||'';const chips=(row.primary_metrics||[]).slice(0,3).map(m=>`<small>${safe(m.label||m.id)} ${safe(m.value??'—')} ${safe(m.unit||'')}</small>`).join('');return `<button type="button" class="recent-result-card-v073d" data-result-case-v073d="${safe(row.id)}" data-result-task-v073d="${safe(row.task_id)}"><span><b>${safe(row.task_name||row.task_id)} · ${safe(row.id)}</b><span class="recent-result-metrics-v073d">${chips||'<small>无标量指标</small>'}</span></span><span>${badge}</span></button>`}).join('')||'<div class="help-empty">当前项目尚无已完成工程结果。</div>'}</div>
        </article>
        <article class="panel"><div class="section-head"><div><h3>下一步工程动作</h3><p>比较和优化会保留结果来源，避免将不同工况或未通过可信度检查的结果混合作为正式结论。</p></div></div>
          <div class="results-actions-v069">
            <button type="button" data-result-action-v069="case-compare" ${s.usable_cases<2?'disabled':''}><b>比较计算工况</b><span>${s.usable_cases>=2?'同一任务内比较指标、输入与可信度':'至少需要两个可用工况'}</span></button>
            <button type="button" data-result-action-v069="compare" ${s.design_revisions<2?'disabled':''}><b>比较电机版本</b><span>${s.design_revisions>=2?'同时检查结果可比性与可信度':'至少需要两个电机版本'}</span></button>
            <button type="button" data-result-action-v069="optimization" ${s.analyses<1?'disabled':''}><b>开展参数研究 / 优化</b><span>${s.analyses?'基于当前分析设置生成候选':'先创建分析'}</span></button>
          </div>
        </article>
      </div>
    </section>`;
    window.MCSEngineeringInterpretation?.bind?.(host,{projectId:currentProjectId(),reference:ref,onRefresh:async()=>{wb.project=await api(`/api/projects/${encodeURIComponent(currentProjectId())}/results-workbench`);renderShell();renderOverview()},onOpenResult:bundleId=>navigate(projectPath(`bundles/${encodeURIComponent(bundleId)}`))});
    window.MCSQualificationCampaign?.mountOverview?.(q('[data-qualification-campaign-overview]',host),{projectId:currentProjectId(),designRevisionId:ref?.design_revision_id||null});
    q('[data-insight-open-result-v081a]',host)?.addEventListener('click',()=>{if(ref)navigate(ref.result_bundle_id?projectPath(`bundles/${encodeURIComponent(ref.result_bundle_id)}`):projectPath(`tasks/${encodeURIComponent(ref.task_id)}/cases/${encodeURIComponent(ref.id)}`))});
    q('[data-insight-motor-v081a]',host)?.addEventListener('click',event=>navigate(event.currentTarget.dataset.route));
    q('[data-open-reference-v073d]',host)?.addEventListener('click',()=>{if(ref)navigate(ref.result_bundle_id?projectPath(`bundles/${encodeURIComponent(ref.result_bundle_id)}`):projectPath(`tasks/${encodeURIComponent(ref.task_id)}/cases/${encodeURIComponent(ref.id)}`))});
    qa('[data-result-case-v073d]',host).forEach(button=>button.addEventListener('click',()=>{const row=recent.find(item=>String(item.id)===String(button.dataset.resultCaseV073d));navigate(row?.result_bundle_id?projectPath(`bundles/${encodeURIComponent(row.result_bundle_id)}`):projectPath(`tasks/${encodeURIComponent(button.dataset.resultTaskV073d)}/cases/${encodeURIComponent(button.dataset.resultCaseV073d)}`))}));
    qa('[data-result-action-v069]',host).forEach(button=>button.addEventListener('click',()=>navigate(projectPath(button.dataset.resultActionV069))));
  }
  async function renderMode(route,ctx){
    const body=q('#resultsWorkbenchBodyV069');if(body)body.innerHTML='';
    setLegacyCase(wb.mode==='case');
    if(wb.mode==='overview')return renderOverview();
    if(wb.mode==='caseCompare')return window.MCSCaseCompare?.mount?.(body,wb.project,route,ctx);
    if(wb.mode==='compare')return window.MCSRevisionCompare?.mount?.(body,wb.project,route,ctx);
    if(wb.mode==='optimization')return window.MCSOptimizationWorkbench?.mount?.(body,wb.project,route,ctx);
    if(wb.mode==='case')return window.MCSCaseViewer?.mount?.(route,ctx);
  }
  async function mount(route,ctx){
    hideLegacyHeader();wb.route=route;wb.ctx=ctx;wb.mode=modeForRoute(route);document.body.dataset.resultsMode=wb.mode;
    const projectId=route?.projectId||currentProjectId();if(!projectId)return{legacyCase:false};
    try{
      const projectPromise=api(`/api/projects/${encodeURIComponent(projectId)}/results-workbench`,ctx?.signal?{signal:ctx.signal}:{});
      /* A direct ResultBundle route previously waited for the complete project
         workbench before starting the independent bundle/FEA index request.
         Start both branches together so first useful result paint is bounded by
         the slower branch instead of their sum. */
      const directCasePromise=wb.mode==='case'&&route?.resultBundleId
        ?(setLegacyCase(true),window.MCSCaseViewer?.mount?.(route,ctx))
        :null;
      wb.project=await projectPromise;
      if(!active(ctx))return{legacyCase:false,aborted:true};
      renderShell();if(directCasePromise)await directCasePromise;else await renderMode(route,ctx);
      return{legacyCase:false,mode:wb.mode};
    }catch(error){
      if(window.MCSPageRuntime?.isAbortError?.(error))return{legacyCase:false,aborted:true};
      const host=q('#resultsWorkbenchBodyV069');if(host)host.innerHTML=`<div class="panel help-empty"><b>结果工作台加载失败</b><span>${safe(error.message||error)}</span></div>`;
      throw error;
    }
  }
  function routeForCurrent(){
    if(wb.mode==='caseCompare'){
      const compare=window.MCSCaseCompare?.state;
      if(compare?.taskId&&compare?.selected?.size>=2)return projectPath(`case-compare/${encodeURIComponent(compare.taskId)}/cases/${encodeURIComponent([...compare.selected].join(','))}`);
      if(compare?.taskId)return projectPath(`case-compare/${encodeURIComponent(compare.taskId)}`);
      return projectPath('case-compare');
    }
    if(wb.mode==='compare'){
      const compare=window.MCSRevisionCompare?.state;
      if(compare?.designId&&compare?.selected?.length>=2)return projectPath(`compare/${encodeURIComponent(compare.designId)}/revisions/${encodeURIComponent(compare.selected.join(','))}`);
      if(compare?.designId)return projectPath(`compare/${encodeURIComponent(compare.designId)}`);
      return projectPath('compare');
    }
    if(wb.mode==='optimization')return projectPath('optimization');
    if(wb.mode==='case')return window.MCSCaseViewer?.routeForCurrent?.()||projectPath('tasks');
    return projectPath('');
  }
  const controller=Object.freeze({mount,state:wb,routeForCurrent,projectPath,navigate,renderShell});
  window.MCSResultsWorkbench=controller;
})();
