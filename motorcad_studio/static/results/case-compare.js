/* MotorCAD Studio V0.79-B — same-Task ResultSet Aggregate comparison owner. */
(() => {
  const q=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=v=>typeof esc==='function'?esc(v??''):String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const fmt=(v,d=4)=>Number.isFinite(Number(v))?Number(v).toLocaleString(undefined,{maximumFractionDigits:d}):safe(v??'—');
  const ctl={host:null,project:null,route:null,ctx:null,taskId:null,task:null,selected:new Set(),comparison:null};
  const active=ctx=>!ctx||window.MCSPageRuntime?.isContextActive?.(ctx)!==false;
  const projectPath=suffix=>window.MCSResultsWorkbench?.projectPath?.(suffix)||'';
  const nav=path=>window.MCSResultsWorkbench?.navigate?.(path);
  const tasks=()=> (ctl.project?.tasks||[]).filter(row=>Number(row.result_bundle_cases||0)>=2);
  const resultReady=row=>Boolean(row?.result_bundle_id)&&['SUCCEEDED','CACHED'].includes(String(row.execution_status||''));
  const memberLabel=row=>String(row?.label||row?.case_id||row?.result_bundle_id||'Result');
  function scenarioText(row){const s=row?.scenario||{};const parts=[];if(s.shaft_speed_rpm!==undefined)parts.push(`${fmt(s.shaft_speed_rpm,0)} rpm`);if(s.peak_current_a!==undefined)parts.push(`${fmt(s.peak_current_a,2)} Apeak`);else if(s.rms_current_a!==undefined)parts.push(`${fmt(s.rms_current_a,2)} Arms`);if(s.phase_advance_deg!==undefined)parts.push(`${fmt(s.phase_advance_deg,1)}°`);return parts.join(' · ')||'固定工况';}
  function caseLabel(row){return `Case ${Number(row.case_index??0)+1}`;}
  function selectedIds(){return [...ctl.selected];}
  function exactRoute(ids=selectedIds()){const suffix=`case-compare/${encodeURIComponent(ctl.taskId)}`;return ids.length>=2?projectPath(`${suffix}/cases/${encodeURIComponent(ids.join(','))}`):projectPath(suffix);}
  function taskOptions(){return tasks().map(row=>`<option value="${safe(row.id)}" ${row.id===ctl.taskId?'selected':''}>${safe(row.name||row.id)} · ${safe(row.status||'—')} · ${Number(row.case_count||0)} Case</option>`).join('');}
  function renderLanding(){const host=ctl.host,rows=tasks();ctl.taskId=ctl.taskId||ctl.route?.caseCompareTaskId||rows[0]?.id||null;host.innerHTML=`<section class="case-compare-v069 panel">
    <div class="section-head"><div><span class="eyebrow">RESULTSET AGGREGATE</span><h2>Case 工程结果比较</h2><p>在同一个不可变 Task / Execution Plan 内选择 2–8 个 ResultBundle。比较 Gate、指标单位对齐、Trust、基准差异与 Pareto 统一由 ResultSet Aggregate 计算。</p></div></div>
    <div class="case-compare-picker-v069"><label>计算任务<select data-case-compare-task-v069>${taskOptions()}</select></label><button type="button" class="primary" data-case-compare-load-v069 ${rows.length?'':'disabled'}>选择 Case</button></div>
    <div data-case-compare-body-v069>${rows.length?'<div class="help-empty"><b>选择一个任务</b><span>规范比较只接受已经冻结为 ResultBundle 的 Case；历史兼容结果需要重新计算后进入正式比较。</span></div>':'<div class="help-empty"><b>没有可比较的任务</b><span>至少需要一个包含两个 ResultBundle Case 的计算任务。</span></div>'}</div>
  </section>`;
    q('[data-case-compare-task-v069]',host)?.addEventListener('change',event=>ctl.taskId=event.target.value);
    q('[data-case-compare-load-v069]',host)?.addEventListener('click',()=>{if(ctl.taskId)nav(exactRoute([]))});
  }
  async function loadTask(){const body=q('[data-case-compare-body-v069]',ctl.host);if(!ctl.taskId||!body)return;body.innerHTML='<div class="viewer-loading-v058"><span class="spinner-dot"></span><b>正在读取 Case 与 ResultBundle 身份…</b></div>';
    try{ctl.task=await api(`/api/tasks/${encodeURIComponent(ctl.taskId)}`,ctl.ctx?.signal?{signal:ctl.ctx.signal}:{});if(!active(ctl.ctx))return;const routeIds=(ctl.route?.caseCompareCaseIds||[]).filter(Boolean);ctl.selected=new Set(routeIds.filter(id=>(ctl.task?.cases||[]).some(row=>row.id===id&&resultReady(row))).slice(0,8));renderCases();if(ctl.route?.autoCaseCompare&&ctl.selected.size>=2)await compareSelected({updateRoute:false});}
    catch(error){if(window.MCSPageRuntime?.isAbortError?.(error))return;body.innerHTML=`<div class="help-empty"><b>Case 列表读取失败</b><span>${safe(error.message||error)}</span></div>`}}
  function renderCases(){const body=q('[data-case-compare-body-v069]',ctl.host),task=ctl.task||{},rows=task.cases||[],request=task.request||{};if(!body)return;const ready=rows.filter(resultReady).length;body.innerHTML=`<div class="case-compare-lineage-v069">
      <div><span>Task</span><b>${safe(task.name||task.id)}</b><small>${safe(task.id)}</small></div>
      <div><span>Motor Revision</span><b>${safe(task.design_revision_id||request.design_revision_id||'—')}</b><small>同一 Task 冻结</small></div>
      <div><span>Analysis Revision</span><b>${safe(request.analysis_definition_revision_id||'—')}</b><small>${safe(task.analysis||'—')} · ${safe(task.solver_mode||'—')}</small></div>
      <div><span>ResultBundle</span><b>${ready}/${rows.length}</b><small>规范比较成员</small></div>
    </div>
    <div class="section-head case-compare-case-head-v069"><div><h3>选择 2–8 个 Case</h3><p>选择顺序决定基准。没有 ResultBundle 的历史 Case 会保持禁用，避免旧 projection 混入正式比较。</p></div><div class="actions"><span class="badge" data-case-compare-count-v069>${ctl.selected.size} 已选</span><button type="button" data-case-compare-run-v069 ${ctl.selected.size<2?'disabled':''}>比较选中</button></div></div>
    <div class="case-selector-v069">${rows.map(row=>{const usable=resultReady(row),checked=ctl.selected.has(row.id);return `<label class="case-selector-card-v069 ${checked?'selected':''} ${usable?'':'disabled'}"><input type="checkbox" data-case-compare-case-v069="${safe(row.id)}" ${checked?'checked':''} ${usable?'':'disabled'}><span><b>${safe(caseLabel(row))}</b><small>${safe(scenarioText(row))}</small></span><span><em>${safe(row.quality_status||'NOT_ASSESSED')}</em><small>${usable?safe(String(row.result_bundle_id).slice(0,18)):row.result_bundle_id?'不可用':'历史结果 · 需重算'}</small></span></label>`}).join('')}</div>
    <div data-case-compare-result-v069></div>`;
    bindCases();
  }
  function bindCases(){const body=q('[data-case-compare-body-v069]',ctl.host);qa('[data-case-compare-case-v069]',body).forEach(input=>input.addEventListener('change',()=>{const id=input.dataset.caseCompareCaseV069;if(input.checked){if(ctl.selected.size>=8){input.checked=false;toast('一次最多比较 8 个 Case','WARNING');return}ctl.selected.add(id)}else ctl.selected.delete(id);input.closest('.case-selector-card-v069')?.classList.toggle('selected',input.checked);const n=ctl.selected.size;q('[data-case-compare-count-v069]',body).textContent=`${n} 已选`;q('[data-case-compare-run-v069]',body).disabled=n<2;}));q('[data-case-compare-run-v069]',body)?.addEventListener('click',()=>compareSelected({updateRoute:true}));}
  function deltaCell(value,index){const delta=Number(value?.relative_percent);const suffix=index&&Number.isFinite(delta)?`<small class="${delta>=0?'delta-up-v069':'delta-down-v069'}">${delta>=0?'+':''}${fmt(delta,2)}%</small>`:'';return `<td>${fmt(value?.value)}${suffix}</td>`;}
  function renderRows(rows,members,limit=24){return (rows||[]).slice(0,limit).map(row=>`<tr><td><b>${safe(row.label||row.id)}</b><small>${safe(row.unit||'')}</small></td>${(row.values||[]).map((value,index)=>deltaCell(value,index)).join('')}</tr>`).join('')||`<tr><td colspan="${members.length+1}">暂无可显示数据。</td></tr>`;}
  function changedDomainTable(c){const members=c.members||[],domains=c.inputs?.domains||{},labels={scenario:'工况',solver:'求解设置',materials:'材料'};const rows=[];['scenario','solver','materials'].forEach(domain=>(domains[domain]||[]).filter(row=>row.changed).forEach(row=>rows.push({label:`${labels[domain]} · ${row.id}`,values:row.values||[]})));if(!rows.length)return'<div class="comparison-note-v069 ok">工况、求解设置与材料在所选成员之间没有可见差异。</div>';return `<div class="comparison-table-scroll-v069"><table><thead><tr><th>变化输入</th>${members.map((row,index)=>`<th>${index===0?'基准 · ':''}${safe(memberLabel(row))}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,36).map(row=>`<tr><td><b>${safe(row.label)}</b></td>${row.values.map(v=>`<td>${safe(typeof v.value==='object'?JSON.stringify(v.value):v.value??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
  function gateText(gate){if(gate.status==='FORMAL')return '正式工程比较 Gate 通过';if(gate.status==='BLOCKED')return '比较 Gate 阻断';return '当前为审查性比较';}
  function renderComparison(c){
    const box=q('[data-case-compare-result-v069]',ctl.host);if(!box)return;
    const members=c.members||[],gate=c.comparability||{},metrics=(c.metrics?.rows||[]).filter(row=>row.comparable),params=(c.inputs?.domains?.design||[]).filter(row=>row.changed),decision=new Map((c.decision_summary||[]).map(row=>[row.result_bundle_id,row])),trace=new Map((c.traceability||[]).map(row=>[row.result_bundle_id,row]));
    const trustCards=members.map(row=>`<div><b>${safe(memberLabel(row))}</b>${window.MCSResultsTrust?.renderLadder?.(row.trust||{}, {compact:true})||''}</div>`).join('');
    const formal=Boolean(gate.formal_comparison_qualified),blocked=gate.status==='BLOCKED';
    const issues=[...(gate.blocking_issues||[]),...(gate.review_issues||[])];
    box.innerHTML=`<section class="case-comparison-result-v069">
      <div class="comparison-formal-gate-v073d ${formal?'ready':'pending'}"><b>${safe(gateText(gate))}</b> · ${formal?'ResultBundle、ExecutionPlan、Trust 与指标单位合同均满足正式比较。':blocked?'至少一项比较结构约束无法满足。':'数值可以审查，但当前上下文或 Trust 不满足正式推荐。'}</div>
      <div class="compare-trust-grid-v073d">${trustCards}</div>
      <div class="comparison-note-v069 ${blocked?'warn':'ok'}"><b>ResultSet Aggregate：</b>${safe(c.contract_version||'0.79-B')} · ${metrics.length} 个对齐标量指标 · ${safe(c.metrics?.unit_alignment_policy||'')}<br>${issues.length?`Gate: ${safe(issues.join(' · '))}`:'Gate 未发现额外问题。'}</div>
      <div class="comparison-table-scroll-v069"><table><thead><tr><th>证据</th>${members.map((row,index)=>`<th>${index===0?'基准 · ':''}${safe(memberLabel(row))}<small>${safe(row.case_id)}</small></th>`).join('')}</tr></thead><tbody>
        <tr><td><b>Result Trust</b></td>${members.map(row=>`<td>${window.MCSResultsTrust?.renderBadge?.(row.trust||{})||safe(row.engineering_status||'—')}<small>${row.formal_recommendation?'FORMAL':'REVIEW'}</small></td>`).join('')}</tr>
        <tr><td><b>质量状态</b></td>${members.map(row=>`<td>${safe(row.quality_status||'—')}<small>${safe(row.bundle_quality_status||'—')}</small></td>`).join('')}</tr>
        <tr><td><b>Pareto / 方向性</b></td>${members.map(row=>{const x=decision.get(row.result_bundle_id)||{};return `<td>${x.pareto?'Pareto':'—'}<small>改善 ${Number(x.improvements?.length||0)} · 退化 ${Number(x.regressions?.length||0)}</small></td>`}).join('')}</tr>
        <tr><td><b>Execution Plan</b></td>${members.map(row=>{const x=trace.get(row.result_bundle_id)||{};return `<td>${safe(x.execution_plan_id||'—')}<small>${safe(String(x.execution_plan_hash||'—').slice(0,18))}</small></td>`}).join('')}</tr>
        <tr><td><b>Result Bundle</b></td>${members.map(row=>`<td>${safe(row.result_bundle_id)}<small>${safe(String(row.result_bundle_hash||'—').slice(0,18))}</small></td>`).join('')}</tr>
      </tbody></table></div>
      <div class="section-head"><div><h3>对齐关键结果</h3><p>只有所有成员均存在且 canonical unit 完全一致的 scalar 指标才计算基准增减。</p></div></div><div class="comparison-table-scroll-v069"><table><thead><tr><th>结果</th>${members.map((row,index)=>`<th>${index===0?'基准 · ':''}${safe(memberLabel(row))}</th>`).join('')}</tr></thead><tbody>${renderRows(metrics,members)}</tbody></table></div>
      <div class="section-head"><div><h3>变化的设计参数</h3><p>输入差异来自 ResultBundle Aggregate 的冻结 inputs；斜率关系仅用于本候选集描述。</p></div></div><div class="comparison-table-scroll-v069"><table><thead><tr><th>参数</th>${members.map((row,index)=>`<th>${index===0?'基准 · ':''}${safe(memberLabel(row))}</th>`).join('')}</tr></thead><tbody>${renderRows(params,members)}</tbody></table></div>
      <div class="section-head"><div><h3>工况 / Solver / 材料差异</h3><p>这些差异由 Comparison Aggregate 明确记录，并参与正式可比性 Gate。</p></div></div>${changedDomainTable(c)}
      <div class="comparison-note-v069 warn"><b>解释边界：</b>${safe(c.interpretation_boundary||'')}</div>
      <div class="case-compare-open-actions-v069">${members.map(row=>`<button type="button" data-result-set-open-v079b="${safe(row.result_bundle_id)}">打开 ${safe(memberLabel(row))}</button>`).join('')}</div>
    </section>`;
    qa('[data-result-set-open-v079b]',box).forEach(button=>button.addEventListener('click',()=>nav(projectPath(`bundles/${encodeURIComponent(button.dataset.resultSetOpenV079b)}`))));
  }
  async function compareSelected({updateRoute=false}={}){const ids=selectedIds();if(ids.length<2)return;if(updateRoute){const path=exactRoute(ids);if(path&&location.pathname!==path){nav(path);return}}const box=q('[data-case-compare-result-v069]',ctl.host);if(box)box.innerHTML='<div class="viewer-loading-v058"><span class="spinner-dot"></span><b>正在构建 ResultSet Aggregate…</b></div>';try{const byId=new Map((ctl.task?.cases||[]).map(row=>[row.id,row])),bundleIds=ids.map(id=>byId.get(id)?.result_bundle_id).filter(Boolean);if(bundleIds.length!==ids.length)throw new Error('所选 Case 中存在没有 ResultBundle 的历史结果，请重新计算后再比较');const request={result_bundle_ids:bundleIds,baseline_result_bundle_id:bundleIds[0],scope:'same_task'};const payload=window.MCSResultSetAggregate?.compare?await window.MCSResultSetAggregate.compare(request,{signal:ctl.ctx?.signal}):await api('/api/result-set-aggregates/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request),signal:ctl.ctx?.signal});if(!active(ctl.ctx))return;ctl.comparison=payload?.aggregate||payload;renderComparison(ctl.comparison)}catch(error){if(window.MCSPageRuntime?.isAbortError?.(error))return;if(box)box.innerHTML=`<div class="issue ERROR">Case 比较失败：${safe(error.message||error)}</div>`}}
  async function mount(host,project,route,ctx){ctl.host=host;ctl.project=project;ctl.route=route||{};ctl.ctx=ctx;ctl.taskId=route?.caseCompareTaskId||null;ctl.task=null;ctl.comparison=null;ctl.selected=new Set();if(ctl.taskId&&window.MCSResultContext?.resolveTask){await window.MCSResultContext.resolveTask(ctl.taskId,ctx,{source:'results:case-compare'});if(!active(ctx))return;}renderLanding();if(ctl.taskId)await loadTask();}
  const controller=Object.freeze({mount,state:ctl,compareSelected});
  window.MCSCaseCompare=controller;
})();
