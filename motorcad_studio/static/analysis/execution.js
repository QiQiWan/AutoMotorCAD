/* MotorCAD Studio V0.67 — one engineer path from Analysis Revision to immutable Task. */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const domainLabels={materials:'材料',cooling:'冷却边界',losses:'损耗输入',interfaces:'界面热阻',radiation:'辐射边界',convection:'对流边界',end_space:'端部空间',flow_circuit:'冷却流路'};
  const taskLabels={QUEUED:'排队中',RUNNING:'计算中',RECOVERING:'恢复中',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已取消',SUCCEEDED:'已完成'};
  const stateV067={analysisId:null,plan:null,fullCheck:null,busy:false,submissionKey:null,focus:'cases',requestToken:0};

  function close(){stateV067.requestToken+=1;q('#analysisExecutionV067')?.remove();document.body.classList.remove('analysis-execution-open-v067')}
  function closeToWorkbench(){const projectId=stateV067.plan?.project_id||window.state?.activeProjectId;if(window.MCSRouter?.navigate&&projectId&&/\/simulation\/analyses\/[^/]+\/execute(?:\/[^/]+)?\/?$/.test(location.pathname))return window.MCSRouter.navigate(`/app/projects/${encodeURIComponent(projectId)}/simulation/analyses`);close()}
  function formatValue(value,unit=''){
    if(value===null||value===undefined||value==='')return '—';
    if(typeof value==='boolean')return value?'启用':'关闭';
    if(typeof value==='number')return `${Number.isInteger(value)?value:Number(value.toFixed(4))}${unit?` ${unit}`:''}`;
    if(typeof value==='object')return Array.isArray(value)?value.join('、'):JSON.stringify(value);
    return `${value}${unit?` ${unit}`:''}`;
  }
  function recipeFields(plan,targetFilter=()=>true){
    const rows=[];
    for(const section of plan?.recipe?.sections||[]){
      for(const field of section.fields||[])if(targetFilter(field))rows.push({...field,sectionLabel:section.label});
    }
    return rows;
  }
  function valueForSolver(plan,field){
    const solver=plan?.solver_settings||{},target=String(field.target||'solver'),key=field.key||field.id;
    if(target==='experiment')return solver.experiment?.[key];
    if(target.startsWith('automation.'))return solver.automation?.[target.split('.',2)[1]]?.[key];
    return solver?.[key];
  }
  function fullCheckFresh(){
    const plan=stateV067.plan,check=stateV067.fullCheck;
    return Boolean(check?.valid&&check.analysisRevisionId===plan?.analysis_revision?.id&&check.designRevisionId===plan?.design_revision?.id);
  }
  function stageStatus(id){
    const plan=stateV067.plan;if(!plan)return 'LOCKED';
    if(id==='cases')return plan.case_count>0?'PASS':'FAIL';
    if(id==='inputs')return (plan.missing_required_input_domains||[]).length?'FAIL':'PASS';
    if(id==='solver')return plan.task_validation?.issues?.some(row=>row.severity==='BLOCKING'&&row.category==='solver')?'FAIL':'PASS';
    if(id==='precheck')return fullCheckFresh()?'PASS':plan.studio_precheck?.valid?'READY':'FAIL';
    if(id==='submit')return fullCheckFresh()&&plan.can_submit?'READY':'LOCKED';
    if(id==='monitor')return (plan.recent_tasks||[]).some(row=>['QUEUED','RUNNING','RECOVERING'].includes(row.status))?'RUNNING':(plan.recent_tasks||[]).length?'PASS':'READY';
    return 'READY';
  }
  function statusText(status){return ({PASS:'完成',READY:'待执行',FAIL:'需处理',LOCKED:'未解锁',RUNNING:'进行中'})[status]||status}
  function issueHtml(issue){
    const fields=(issue.field_labels||issue.parameter_ids||[]).join('、');
    return `<li class="${safe(String(issue.severity||'').toLowerCase())}"><b>${safe(issue.message||issue.code||'检查项')}</b>${fields?`<span>${safe(fields)}</span>`:''}${issue.suggestion?`<small>${safe(issue.suggestion)}</small>`:''}</li>`;
  }
  function caseTable(plan){
    const fields=recipeFields(plan,field=>field.target==='load_case');
    const keys=fields.length?fields.map(field=>field.key):[...new Set((plan.load_cases||[]).flatMap(row=>Object.keys(row||{})))];
    const fieldMap=new Map(fields.map(field=>[field.key,field]));
    if(!keys.length)return '<div class="analysis-empty-v067">当前配方不要求显式运行工况；计算将使用 Analysis Revision 中的模型设置。</div>';
    return `<div class="analysis-table-scroll-v067"><table class="analysis-case-table-v067"><thead><tr><th>Case</th>${keys.map(key=>`<th>${safe(fieldMap.get(key)?.label||key)}<small>${safe(fieldMap.get(key)?.unit||'')}</small></th>`).join('')}</tr></thead><tbody>${(plan.load_cases||[]).map((row,index)=>`<tr><td><b>${index+1}</b></td>${keys.map(key=>`<td>${safe(formatValue(row?.[key],fieldMap.get(key)?.unit||''))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function solverCards(plan){
    const fields=recipeFields(plan,field=>field.target!=='load_case'&&field.visibility!=='system');
    const rows=fields.filter(field=>valueForSolver(plan,field)!==undefined);
    if(!rows.length){
      const settings=Object.entries(plan.solver_settings||{}).filter(([key,value])=>key!=='input_domains'&&key!=='native_fea'&&typeof value!=='object');
      return settings.length?settings.map(([key,value])=>`<div><span>${safe(key)}</span><b>${safe(formatValue(value))}</b></div>`).join(''):'<div class="analysis-empty-v067">当前配方采用已验证默认求解设置。</div>';
    }
    return rows.map(field=>`<div><span>${safe(field.label||field.key)}</span><b>${safe(formatValue(valueForSolver(plan,field),field.unit||''))}</b><small>${safe(field.sectionLabel||'')}</small></div>`).join('');
  }
  function inputCards(plan){
    const required=new Set(plan.required_input_domains||[]),saved=plan.input_domains||{};
    const ids=[...new Set([...(plan.required_input_domains||[]),...Object.keys(saved)])];
    if(!ids.length)return '<div class="analysis-empty-v067">当前配方没有额外的物理输入模块。</div>';
    return ids.map(id=>{const values=saved[id]||{},configured=Object.prototype.hasOwnProperty.call(saved,id);return `<article class="analysis-domain-card-v067 ${configured?'ready':required.has(id)?'missing':''}"><div><b>${safe(domainLabels[id]||id)}</b><span>${required.has(id)?'必需':'可选'}</span></div><strong>${configured?'已确认':'待确认'}</strong><small>${configured?`${Object.keys(values).length} 个字段已冻结在 Analysis Revision`:'计算前需要明确保存该输入模块'}</small></article>`}).join('');
  }
  function precheckBlock(plan){
    const pre=plan.studio_precheck||{},issues=pre.issues||[],check=stateV067.fullCheck;
    const native=check?.result?.motorcad;
    return `<div class="analysis-check-summary-v067 ${pre.valid?'ready':'blocked'}"><span>${pre.valid?'✓':'!'}</span><div><b>${pre.valid?'Studio 静态检查已通过':'Studio 静态检查存在阻断项'}</b><small>${pre.blocking||0} 个阻断 · ${pre.warnings||0} 个提醒</small></div></div>${issues.length?`<ul class="analysis-issues-v067">${issues.slice(0,12).map(issueHtml).join('')}${issues.length>12?`<li><small>另有 ${issues.length-12} 项，完整记录保留在检查结果中。</small></li>`:''}</ul>`:''}${check?`<div class="analysis-native-check-v067 ${check.valid?'pass':'fail'}"><span>${check.valid?'✓':'!'}</span><div><b>Motor-CAD 模型检查：${safe(native?.status||check.result?.status||'UNKNOWN')}</b><p>${safe(native?.message||'')}</p><small>${safe(native?.suggestion||'')}</small></div></div>`:'<div class="analysis-native-check-v067 pending"><span>2</span><div><b>Motor-CAD 模型检查尚未执行</b><p>点击“运行完整计算前检查”后，Studio 会使用当前 Design Revision 在 Motor-CAD 中进行模型加载与参数回读验证。</p></div></div>'}`;
  }
  function recentTasks(plan){
    const rows=plan.recent_tasks||[];
    if(!rows.length)return '<div class="analysis-empty-v067">当前分析案例还没有计算记录。</div>';
    return rows.map(row=>`<button type="button" class="analysis-run-row-v067" data-open-run-v067="${safe(row.id)}"><span class="run-state ${safe(String(row.status||'').toLowerCase())}">${safe(taskLabels[row.status]||row.status)}</span><b>${safe(row.name||row.id)}</b><small>${Number(row.usable_cases||0)} / ${row.case_count||0} 个可用 Case</small><em>打开监控 →</em></button>`).join('');
  }
  function runtimeSummary(plan){
    const runtime=plan.runtime_readiness||{},checks=runtime.checks||[],bad=checks.filter(row=>String(row.status||'').toUpperCase()==='FAIL');
    return `<div class="analysis-runtime-v067 ${runtime.ok?'ready':'blocked'}"><b>${runtime.ok?'Motor-CAD 提交环境已就绪':'Motor-CAD 提交环境需要处理'}</b><span>${runtime.effective_motorcad_exe?`目标：${safe(runtime.effective_motorcad_exe)}`:'当前依赖 PyMotorCAD 注册安装'}</span>${bad.length?`<small>${safe(bad.map(row=>row.message).join('；'))}</small>`:'<small>真正的许可证、模型加载与求解仍由实际 Task Worker 作为最终权威。</small>'}</div>`;
  }
  function render(){
    const plan=stateV067.plan;if(!plan)return;
    let root=q('#analysisExecutionV067');
    if(!root){root=document.createElement('div');root.id='analysisExecutionV067';root.className='analysis-execution-overlay-v067';document.body.appendChild(root);document.body.classList.add('analysis-execution-open-v067')}
    const steps=[['cases','工况','定义要计算的运行点'],['inputs','物理输入','材料与边界条件'],['solver','求解设置','Motor-CAD 配方与输出'],['precheck','Precheck','Studio + Motor-CAD'],['submit','提交计算','冻结 Run Configuration'],['monitor','运行监控','Case 状态与结果']];
    const ready=fullCheckFresh()&&Boolean(plan.can_submit)&&!stateV067.busy;
    root.innerHTML=`<div class="analysis-execution-backdrop-v067"></div><section class="analysis-execution-dialog-v067" role="dialog" aria-modal="true" aria-label="分析与计算"><header class="analysis-execution-head-v067"><div><span class="eyebrow">Analysis / Compute Workflow</span><h2>${safe(plan.analysis_name||'分析与计算')}</h2><p>${safe(plan.design?.name||'电机')} · Design Rev.${safe(plan.design_revision?.revision??'—')} · Analysis Rev.${safe(plan.analysis_revision?.revision??'—')} · ${safe(plan.recipe?.label||plan.recipe_id)}</p></div><div><button type="button" data-refresh-v067>刷新</button><button type="button" data-close-v067 aria-label="关闭">×</button></div></header><div class="analysis-execution-body-v067"><nav class="analysis-step-rail-v067">${steps.map(([id,label,desc],index)=>{const status=stageStatus(id);return `<button type="button" data-step-v067="${id}" class="${stateV067.focus===id?'active':''} ${status.toLowerCase()}"><i>${status==='PASS'?'✓':index+1}</i><span><b>${safe(label)}</b><small>${safe(desc)}</small></span><em>${statusText(status)}</em></button>`}).join('')}</nav><main class="analysis-execution-main-v067"><section id="analysisV067-cases" data-section-v067="cases"><div class="section-head-v067"><div><span>01 · Operating Conditions</span><h3>工况</h3><p>每一行对应一个独立 Case。速度、电流、电压、相位等运行点冻结在当前 Analysis Revision 中。</p></div><button type="button" data-edit-analysis-v067>修改工况与分析设置</button></div>${caseTable(plan)}</section><section id="analysisV067-inputs" data-section-v067="inputs"><div class="section-head-v067"><div><span>02 · Physical Inputs</span><h3>物理输入</h3><p>这里显示会真正进入求解器的材料、损耗、冷却和边界输入。</p></div><button type="button" data-edit-inputs-v067>配置物理输入</button></div><div class="analysis-domain-grid-v067">${inputCards(plan)}</div></section><section id="analysisV067-solver" data-section-v067="solver"><div class="section-head-v067"><div><span>03 · Solver Contract</span><h3>求解设置与结果合同</h3><p>求解设置与请求输出均来自当前 Analysis Revision，Task 提交后形成不可变 Run Configuration。</p></div><button type="button" data-edit-analysis-v067>修改求解设置</button></div><div class="analysis-solver-grid-v067">${solverCards(plan)}</div><div class="analysis-output-contract-v067"><b>请求结果 · ${plan.requested_outputs?.length||0} 项</b><div>${(plan.requested_outputs||[]).map(item=>`<span>${safe(item)}</span>`).join('')||'<small>将采用配方默认结果集合</small>'}</div></div></section><section id="analysisV067-precheck" data-section-v067="precheck"><div class="section-head-v067"><div><span>04 · Precheck</span><h3>计算前检查</h3><p>先执行快速确定性检查；通过后再用 Motor-CAD 验证当前电机模型可加载、关键参数可写入并可回读。</p></div><button type="button" class="primary" data-run-check-v067 ${stateV067.busy?'disabled':''}>${stateV067.busy?'检查执行中…':'运行完整计算前检查'}</button></div>${precheckBlock(plan)}</section><section id="analysisV067-submit" data-section-v067="submit"><div class="section-head-v067"><div><span>05 · Immutable Submission</span><h3>提交计算</h3><p>提交时冻结 Design Revision、Analysis Revision、物理输入、工况、求解设置和结果合同。</p></div></div>${runtimeSummary(plan)}<div class="analysis-submit-grid-v067"><label><span>任务名称</span><input id="analysisTaskNameV067" maxlength="120" value="${safe(`${plan.analysis_name||'分析'} · 计算`)}"></label><label><span>质量配置</span><select id="analysisQualityV067"><option value="standard">标准</option><option value="high">高质量</option><option value="fast">快速验证</option></select></label><label class="analysis-toggle-v067"><input id="analysisReuseV067" type="checkbox" checked><span><b>复用已验证缓存</b><small>输入指纹一致且质量有效时复用历史 Case。</small></span></label></div><div class="analysis-freeze-v067"><div><span>Design Revision</span><b>Rev.${safe(plan.design_revision?.revision??'—')}</b><small>${safe(String(plan.design_revision?.content_hash||'').slice(0,12))}</small></div><div><span>Analysis Revision</span><b>Rev.${safe(plan.analysis_revision?.revision??'—')}</b><small>${safe(String(plan.analysis_revision?.content_hash||'').slice(0,12))}</small></div><div><span>Case 数</span><b>${plan.case_count}</b><small>${plan.case_count>1?'按工况矩阵提交':'单工况'}</small></div><div><span>结果项</span><b>${plan.requested_outputs?.length||0}</b><small>冻结结果合同</small></div></div><div id="analysisSubmitPipelineV067" class="analysis-submit-pipeline-v067 ${stateV067.busy?'running':''}">${stateV067.busy?'<span>Studio 检查</span><i>→</i><span>Motor-CAD 模型检查</span><i>→</i><span>冻结运行配置</span><i>→</i><span>提交 Task</span>':`<span>${fullCheckFresh()?'✓ 完整检查证据有效':'需要先完成完整检查'}</span><i>→</i><span>${fullCheckFresh()&&stateV067.fullCheck?.result?.evidence?.id?'复用当前预检查证据':'提交时重新确认原生检查'}</span><i>→</i><span>${plan.can_submit?'提交条件满足':'仍有提交阻断项'}</span>`}</div><div class="analysis-primary-action-v067"><div><b>${ready?'可以提交当前不可变配置':'提交尚未解锁'}</b><small>${ready?'提交后立即进入运行监控。':!plan.studio_precheck?.valid?'请先修复 Studio 阻断项。':!fullCheckFresh()?'请运行完整计算前检查。':!plan.runtime_readiness?.ok?'请先处理 Motor-CAD 运行环境。':'请处理 Task 校验阻断项。'}</small></div><button type="button" class="primary" data-submit-v067 ${ready?'':'disabled'}>${stateV067.busy?'正在提交…':'开始 Motor-CAD 计算 →'}</button></div></section><section id="analysisV067-monitor" data-section-v067="monitor"><div class="section-head-v067"><div><span>06 · Run Monitor</span><h3>运行监控</h3><p>提交后继续使用现有 SSE 任务监控；这里只保留与当前分析案例直接相关的运行记录。</p></div></div><div class="analysis-recent-runs-v067">${recentTasks(plan)}</div></section></main></div></section>`;
    bind(root);
  }
  function syncFocusRoute(step){const projectId=stateV067.plan?.project_id,analysisId=stateV067.analysisId;if(!projectId||!analysisId||!window.MCSRouter?.setUrl)return;window.MCSRouter.setUrl(`/app/projects/${encodeURIComponent(projectId)}/simulation/analyses/${encodeURIComponent(analysisId)}/execute/${encodeURIComponent(step)}`,true)}
  function bind(root){
    q('[data-close-v067]',root)?.addEventListener('click',closeToWorkbench);q('.analysis-execution-backdrop-v067',root)?.addEventListener('click',closeToWorkbench);
    q('[data-refresh-v067]',root)?.addEventListener('click',()=>load(stateV067.analysisId,true));
    qa('[data-step-v067]',root).forEach(button=>button.addEventListener('click',()=>{stateV067.focus=button.dataset.stepV067;syncFocusRoute(stateV067.focus);qa('[data-step-v067]',root).forEach(row=>row.classList.toggle('active',row===button));q(`#analysisV067-${button.dataset.stepV067}`,root)?.scrollIntoView({behavior:'smooth',block:'start'})}));
    qa('[data-edit-analysis-v067]',root).forEach(button=>button.addEventListener('click',openAnalysisEditor));
    q('[data-edit-inputs-v067]',root)?.addEventListener('click',async()=>{const id=stateV067.analysisId;await closeToWorkbench();window.MCSV060?.openInputCenter?.(id)});
    q('[data-run-check-v067]',root)?.addEventListener('click',runFullCheck);
    q('[data-submit-v067]',root)?.addEventListener('click',submit);
    qa('[data-open-run-v067]',root).forEach(button=>button.addEventListener('click',()=>openMonitor(button.dataset.openRunV067)));
  }
  async function openAnalysisEditor(){
    const id=stateV067.analysisId,projectId=stateV067.plan?.project_id,focus=stateV067.focus;if(!id||!projectId)return;
    try{
      const definitions=await api(`/api/projects/${encodeURIComponent(projectId)}/analysis-definitions`);if(window.MCSV040?.state)window.MCSV040.state.definitions=definitions;
      if(!window.MCSV046?.openRecipeRevisionEditor)return toast('分析设置编辑器尚未加载。','WARNING',7000);
      close();
      await window.MCSV046.openRecipeRevisionEditor(id,stateV067.plan?.design?.motor_type_id);
      if(location.pathname.includes(`/simulation/analyses/${encodeURIComponent(id)}/execute`))await load(id,true,null,focus);
    }catch(error){toast(error.message,'ERROR',9000);if(location.pathname.includes(`/simulation/analyses/${encodeURIComponent(id)}/execute`))await load(id,true,null,focus)}
  }
  async function recoverStalePlan(error,token){
    if(error?.status!==409||error?.detail?.code!=='ANALYSIS_EXECUTION_STALE'||token!==stateV067.requestToken)return false;
    stateV067.fullCheck=null;stateV067.submissionKey=null;
    toast(error.detail?.message||'分析设置或设计版本已经更新，正在重新装载执行计划。','WARNING',9000);
    await load(stateV067.analysisId,true);
    return true;
  }
  async function runFullCheck(){
    if(stateV067.busy||!stateV067.analysisId)return;
    const token=stateV067.requestToken,analysisRevisionId=stateV067.plan?.analysis_revision?.id,designRevisionId=stateV067.plan?.design_revision?.id;
    stateV067.busy=true;render();
    try{
      const result=await api(`/api/analysis-definitions/${encodeURIComponent(stateV067.analysisId)}/calculation-check`,{method:'POST',body:JSON.stringify({expected_analysis_revision_id:analysisRevisionId,expected_design_revision_id:designRevisionId})});
      if(token!==stateV067.requestToken)return;
      stateV067.fullCheck={valid:Boolean(result.valid),analysisRevisionId,designRevisionId,result};
      if(window.MCSV060?.state?.checks)window.MCSV060.state.checks.set(stateV067.analysisId,{valid:Boolean(result.valid),analysisRevisionId,designRevisionId,result});
      toast(result.valid?'完整计算前检查通过':'计算前检查存在阻断项',result.valid?'SUCCESS':'WARNING',8000);
    }catch(error){
      if(token!==stateV067.requestToken)return;
      if(await recoverStalePlan(error,token))return;
      stateV067.fullCheck={valid:false,analysisRevisionId,designRevisionId,result:{motorcad:{status:'FAIL',message:error.message}}};
      toast(error.message,'ERROR',9000);
    }finally{
      if(token!==stateV067.requestToken)return;
      stateV067.busy=false;render();requestAnimationFrame(()=>q('#analysisV067-precheck')?.scrollIntoView({block:'start'}));
    }
  }
  function makeSubmissionKey(){return `ANX-${globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(16).slice(2)}`}`.replace(/[^A-Za-z0-9-]/g,'').slice(0,120)}
  async function submit(){
    if(stateV067.busy||!stateV067.analysisId||!fullCheckFresh()||!stateV067.plan?.can_submit)return;
    const token=stateV067.requestToken,analysisRevisionId=stateV067.plan?.analysis_revision?.id,designRevisionId=stateV067.plan?.design_revision?.id;
    const root=q('#analysisExecutionV067'),name=q('#analysisTaskNameV067',root)?.value.trim(),quality=q('#analysisQualityV067',root)?.value||'standard',reuse=Boolean(q('#analysisReuseV067',root)?.checked);
    stateV067.busy=true;stateV067.submissionKey=stateV067.submissionKey||makeSubmissionKey();render();
    try{
      const result=await api(`/api/analysis-definitions/${encodeURIComponent(stateV067.analysisId)}/execute`,{method:'POST',body:JSON.stringify({name:name||undefined,quality_profile:quality,reuse_cache:reuse,submission_key:stateV067.submissionKey,precheck_evidence_id:stateV067.fullCheck?.result?.evidence?.id||undefined,run_native_precheck:true,expected_analysis_revision_id:analysisRevisionId,expected_design_revision_id:designRevisionId})});
      if(token!==stateV067.requestToken)return;
      toast(result.idempotent_replay?'已恢复同一次计算提交':'计算任务已创建','SUCCESS',7000);stateV067.submissionKey=null;
      await window.MCSV060?.fetchCases?.(true);
      if(token!==stateV067.requestToken)return;
      openMonitor(result.task_id);
    }catch(error){
      if(token!==stateV067.requestToken)return;
      stateV067.busy=false;
      if(await recoverStalePlan(error,token))return;
      toast(error.message,'ERROR',10000);render();
    }
  }
  function openMonitor(taskId){
    if(!taskId)return;close();if(window.state)window.state.monitorTask=taskId;
    const projectId=stateV067.plan?.project_id||window.state?.activeProjectId;
    if(window.MCSRouter?.navigate&&projectId)return window.MCSRouter.navigate(`/app/projects/${encodeURIComponent(projectId)}/simulation/monitor/${encodeURIComponent(taskId)}`);
    window.showTab?.('monitor');window.openMonitorTask?.(taskId);
  }
  async function load(id,force=false,routeCtx=null,initialFocus=null){
    if(!id)return;const token=++stateV067.requestToken;if(force||stateV067.analysisId!==id){stateV067.fullCheck=null;stateV067.submissionKey=null}
    stateV067.analysisId=id;stateV067.busy=false;if(['cases','inputs','solver','precheck','submit','monitor'].includes(initialFocus))stateV067.focus=initialFocus;
    let root=q('#analysisExecutionV067');if(!root){root=document.createElement('div');root.id='analysisExecutionV067';root.className='analysis-execution-overlay-v067';root.innerHTML='<div class="analysis-execution-backdrop-v067"></div><section class="analysis-execution-dialog-v067 loading"><div class="analysis-loading-v067"><span class="spinner-dot"></span><b>正在装载分析执行合同…</b><small>读取当前 Design Revision、Analysis Revision、工况、输入和求解设置。</small></div></section>';document.body.appendChild(root);document.body.classList.add('analysis-execution-open-v067')}
    try{const plan=await api(`/api/analysis-definitions/${encodeURIComponent(id)}/execution-plan`,routeCtx?.signal?{signal:routeCtx.signal}:{});if(token!==stateV067.requestToken||routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;stateV067.plan=plan;const oldGate=window.MCSV060?.state?.checks?.get?.(id);if(oldGate&&oldGate.valid&&oldGate.analysisRevisionId===stateV067.plan.analysis_revision?.id&&oldGate.designRevisionId===stateV067.plan.design_revision?.id)stateV067.fullCheck={...oldGate,result:oldGate.result};render()}catch(error){if(window.MCSPageRuntime?.isAbortError?.(error)||token!==stateV067.requestToken)return;close();toast(`分析执行合同加载失败：${error.message}`,'ERROR',10000);throw error}
  }
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&q('#analysisExecutionV067')&&!stateV067.busy)closeToWorkbench()});
  window.MCSAnalysisExecution={open:load,close,refresh:()=>load(stateV067.analysisId,true),state:stateV067};
})();
