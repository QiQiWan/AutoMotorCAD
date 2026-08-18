/* MotorCAD Studio V0.29.0 engineer-centered workflow.
   Keeps traceability objects in the data model while presenting a continuous
   engineer mental model: current motor -> operating point -> analysis -> solve -> result. */
(() => {
  const $q=(s,r=document)=>r.querySelector(s), $$q=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=v=>typeof window.esc==='function'?window.esc(v):String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text=(v,f='—')=>v===null||v===undefined||v===''?f:String(v);
  // V0.19-V0.28 shipped with Guided/Operator selected by default, so most
  // existing browsers carry an implicit `operator` preference. Migrate that
  // historical default once to the engineer-first workspace; users can switch
  // back to Guided mode afterwards and the explicit choice is preserved.
  try{
    if(!localStorage.getItem('motorcad-studio-v029-mode-migrated')){
      if(localStorage.getItem('motorcad-studio-user-mode')==='operator'){
        localStorage.setItem('motorcad-studio-user-mode','engineering');
        const el=$q('#userMode');if(el)el.value='engineering';document.body.dataset.userMode='engineering';
      }
      localStorage.setItem('motorcad-studio-v029-mode-migrated','1');
    }
  }catch{}

  function routeGo(tab){
    if(typeof window.showTab==='function') window.showTab(tab);
  }

  function ensureProjectContextBar(){
    const shell=$q('#projectShell'); if(!shell) return null;
    let bar=$q('#engineeringContextBarV029'); if(bar) return bar;
    bar=document.createElement('div');
    bar.id='engineeringContextBarV029';
    bar.className='engineering-context-v029';
    const secondary=$q('#projectSecondaryNav');
    if(secondary) secondary.insertAdjacentElement('afterend',bar); else shell.appendChild(bar);
    return bar;
  }

  function designContext(){
    const rec=state.projectRevisionIndex?.get?.(state.taskDesignRevisionId);
    if(rec) return {label:`${rec.design?.name||'Design'} · Rev.${rec.revision?.revision??'-'}`, id:rec.revision?.id||state.taskDesignRevisionId};
    if(state.workspaceDesign&&state.workspaceRevision) return {label:`${state.workspaceDesign.name||'Design'} · Rev.${state.workspaceRevision.revision??'-'}`,id:state.workspaceRevision.id};
    if(state.workspaceDesign) return {label:state.workspaceDesign.name||'Design',id:state.workspaceDesign.id};
    return {label:'尚未选择模型',id:null};
  }
  function scenarioContext(){
    const rec=state.projectScenarioRevisionIndex?.get?.(state.taskScenarioRevisionId);
    if(rec) return `${rec.scenario?.name||'Scenario'} · Rev.${rec.revision?.revision??'-'}`;
    const speed=Number($q('#scenarioSpeedV021')?.value), current=Number($q('#scenarioPeakCurrentV021')?.value);
    if(Number.isFinite(speed)||Number.isFinite(current)) return `临时工况${Number.isFinite(speed)?` · ${speed} rpm`:''}${Number.isFinite(current)?` · ${current} A(pk)`:''}`;
    return '临时工况';
  }
  function taskContext(){
    const id=state.monitorTask?.id||state.monitorTask||state.selectedTask?.id||state.selectedTask||$q('#monitorTaskSelect')?.value||'';
    return id?String(id):'尚无活动任务';
  }
  function runtimeContext(){
    if(state.runtimeSubmissionReadyV028===true) return {label:'运行环境就绪',tone:'ok'};
    if(state.runtimeSubmissionReadyV028===false) return {label:'运行环境阻断',tone:'error'};
    return {label:'运行环境检查中',tone:'pending'};
  }

  function renderProjectContext(){
    const bar=ensureProjectContextBar(); if(!bar) return;
    const project=state.workspaceProject||state.workspaceProjects?.find?.(p=>p.id===state.activeProjectId);
    if(!project||$q('#projectShell')?.classList.contains('hidden')){bar.classList.add('hidden');return}
    bar.classList.remove('hidden');
    const d=designContext(), sc=scenarioContext(), rt=runtimeContext();
    const analysis=$q('#analysis')?.selectedOptions?.[0]?.textContent||$q('#analysis')?.value||'尚未选择分析';
    const activeTab=$q('.tab.active')?.id||'';
    bar.innerHTML=`<div class="engineering-context-main-v029"><span class="eyebrow">工程上下文</span><div class="engineering-context-items-v029">
      <button type="button" data-engineer-go="workspace"><small>当前模型</small><b>${safe(d.label)}</b></button>
      <button type="button" data-engineer-go="analysisWorkbench"><small>工况</small><b>${safe(sc)}</b></button>
      <button type="button" data-engineer-go="analysisWorkbench"><small>分析</small><b>${safe(analysis)}</b></button>
      <button type="button" data-engineer-go="setup" class="${rt.tone}"><small>Motor-CAD</small><b>${safe(rt.label)}</b></button>
      <button type="button" data-engineer-go="monitor"><small>当前任务</small><b>${safe(taskContext())}</b></button>
    </div></div><div class="engineering-context-actions-v029">
      <button type="button" data-engineer-go="workspace" class="${activeTab==='workspace'?'active':''}">模型</button>
      <button type="button" data-engineer-go="analysisWorkbench" class="${['analysisWorkbench','newTask','tasks','monitor','simulationAssets'].includes(activeTab)?'primary':''}">分析与计算</button>
      <button type="button" data-engineer-go="resultViewer">结果</button>
    </div>`;
    $$q('[data-engineer-go]',bar).forEach(btn=>btn.addEventListener('click',()=>routeGo(btn.dataset.engineerGo)));
  }

  function ensureEngineerTaskLayout(){
    const form=$q('#taskForm'); if(!form||$q('#engineerTaskGridV029')) return;
    if(!$q('#taskWizardHeader')) return;
    const grid=document.createElement('div'); grid.id='engineerTaskGridV029'; grid.className='engineer-task-grid-v029';
    const main=document.createElement('div'); main.id='engineerTaskMainV029'; main.className='engineer-task-main-v029';
    const aside=document.createElement('aside'); aside.id='engineerRunSummaryV029'; aside.className='engineer-run-summary-v029'; aside.setAttribute('aria-label','本次仿真工程摘要');
    [...form.children].forEach(el=>main.appendChild(el));
    grid.append(main,aside); form.appendChild(grid);
    renderRunSummary();
  }

  function experimentMode(){return $q('input[name="experimentMode"]:checked')?.value||'single'}
  function methodLabel(mode){return ({single:'单次计算',sweep:'一维扫描',csv:'CSV矩阵',full_factorial:'全因子',latin_hypercube:'拉丁超立方',random:'随机 DOE',pareto_search:'Pareto 筛选',nsga2:'NSGA-II'})[mode]||mode}
  function currentStep(){return Number(state.taskWizardStepV019)||0}
  function issueSummary(){
    const gate=state.modelGateV020||{};
    if(state.runtimeSubmissionReadyV028===false){const row=(state.runtimeSubmissionChecksV028||[]).find(x=>String(x.status).toUpperCase()==='FAIL');return {tone:'error',title:'运行环境需要处理',detail:row?.message||'检查 Motor-CAD.exe 与 PyMotorCAD。'}}
    if(gate.localStatus==='BLOCKING') return {tone:'error',title:'模型关系阻断',detail:'先修复几何/绕组确定性约束，再提交。'};
    if(gate.validationValid===false) return {tone:'error',title:'配置检查未通过',detail:'查看检查提交页中的第一条阻断原因。'};
    if(state.taskDesignRevisionId&&gate.validationValid===true&&state.runtimeSubmissionReadyV028===true) return {tone:'ok',title:'可以开始计算',detail:'系统将继续完成 Motor-CAD 模型检查、求解和结果提取。'};
    return {tone:'pending',title:'配置尚未完整',detail:'完成当前步骤后，系统会更新可执行性。'};
  }
  function runSummaryRows(){
    const d=designContext(); const sc=scenarioContext(); const outs=$$q('[data-output]:checked').length;
    let overrides=0; try{overrides=typeof window.taskOverrideCount==='function'?window.taskOverrideCount():$$q('[data-param-field].changed').length}catch{}
    return [
      ['模型',d.label],['工况',sc],['分析',$q('#analysis')?.selectedOptions?.[0]?.textContent||$q('#analysis')?.value||'—'],
      ['计算方式',methodLabel(experimentMode())],['Case',($q('#taskPreview')?.textContent.match(/([0-9]+) Case/)||[])[1]||'1'],
      ['临时覆盖',`${overrides} 项`],['输出',`${outs} 项`]
    ];
  }
  function renderRunSummary(){
    const box=$q('#engineerRunSummaryV029'); if(!box) return;
    const issue=issueSummary(), step=currentStep();
    const labels=state.taskWizardLabelsV019||['基线','工况','计算方式','输出','检查提交'];
    box.innerHTML=`<div class="engineer-summary-head-v029"><span class="eyebrow">本次仿真</span><b>运行摘要</b><small>始终显示即将提交给 Motor-CAD 的工程上下文。</small></div>
      <div class="engineer-summary-grid-v029">${runSummaryRows().map(([k,v])=>`<div><span>${safe(k)}</span><b>${safe(v)}</b></div>`).join('')}</div>
      <div class="engineer-step-jumps-v029"><span>配置步骤</span>${labels.map((label,i)=>`<button type="button" data-engineer-step="${i}" class="${i===step?'active':''} ${i<step?'done':''}"><span>${i+1}</span>${safe(label)}</button>`).join('')}</div>
      <div class="engineer-gate-v029 ${issue.tone}"><b>${safe(issue.title)}</b><span>${safe(issue.detail)}</span>${issue.tone==='error'?'<button type="button" data-engineer-fix>定位问题</button>':''}</div>
      <div class="engineer-summary-actions-v029"><button type="button" data-engineer-open-model>返回模型工作台</button><button type="button" data-engineer-open-review class="primary">检查提交</button></div>`;
    $$q('[data-engineer-step]',box).forEach(btn=>btn.addEventListener('click',()=>window.MCSOperatorFlowV025?.activateTaskStep?.(Number(btn.dataset.engineerStep))));
    $q('[data-engineer-open-model]',box)?.addEventListener('click',()=>routeGo('workspace'));
    $q('[data-engineer-open-review]',box)?.addEventListener('click',()=>window.MCSOperatorFlowV025?.activateTaskStep?.(4));
    $q('[data-engineer-fix]',box)?.addEventListener('click',()=>{
      if((state.modelGateV020||{}).localStatus==='BLOCKING') window.MCSOperatorFlowV025?.activateTaskStep?.(0);
      else window.MCSOperatorFlowV025?.activateTaskStep?.(4);
      setTimeout(()=>$q('#validationIssues .issue,#geometryGuardDetails .issue')?.scrollIntoView({behavior:'smooth',block:'center'}),60);
    });
  }

  function outputPresetKey(){return `motorcad-studio-output-preset-v029:${state.activeProjectId||'global'}:${$q('#analysis')?.value||'emag'}`}
  function saveOutputPreset(){
    if(!$q('#outputFields'))return;
    const ids=$$q('[data-output]:checked').map(el=>el.dataset.output);
    if(ids.length) localStorage.setItem(outputPresetKey(),JSON.stringify(ids));
    renderRunSummary();
  }
  function applyOutputPreset(){
    const raw=localStorage.getItem(outputPresetKey()); if(!raw)return false;
    try{
      const wanted=new Set(JSON.parse(raw)); let matched=0;
      $$q('[data-output]').forEach(el=>{const required=Boolean(state.registry?.outputs?.[el.dataset.output]?.required);el.checked=required||wanted.has(el.dataset.output);if(el.checked)matched++});
      return matched>0;
    }catch{return false}
  }
  if(typeof window.renderOutputs==='function'){
    const previousRenderOutputs=window.renderOutputs;
    window.renderOutputs=function(){previousRenderOutputs();applyOutputPreset();renderRunSummary()};
  }

  function ensureNativeCheckControls(){
    const btn=$q('#geometryRuntimeCheck');if(!btn||$q('#forceGeometryRuntimeCheckV029'))return;
    btn.textContent='Motor-CAD 原生检查';
    btn.title='相同模型快照 5 分钟内复用原生检查证据，参数改变后自动失效。';
    const force=document.createElement('button');force.id='forceGeometryRuntimeCheckV029';force.type='button';force.className='subtle';force.textContent='强制重新检查';force.title='忽略相同模型快照的短时缓存，重新启动 Motor-CAD 原生检查。';
    btn.insertAdjacentElement('afterend',force);
    force.addEventListener('click',()=>window.MCSGeometry?.runRuntime?.({force:true}));
  }

  function tuneWizardCopy(){
    const head=$q('#taskWizardHeader'); if(!head)return;
    const p=head.querySelector('p'); const mode=document.body.dataset.userMode;
    if(p)p.textContent=mode==='operator'?'引导模式按“基线 → 工况 → 计算方式 → 输出 → 检查提交”推进；每一步都会保留当前工程上下文。':'工程模式支持直接跳转任一步骤；右侧运行摘要持续显示模型、工况、分析、输出和可执行状态。长期设计修改仍在“模型”中形成新 Revision。';
  }

  function refreshEngineerUX(){
    ensureProjectContextBar(); ensureEngineerTaskLayout(); ensureNativeCheckControls(); tuneWizardCopy();
    renderProjectContext(); renderRunSummary();
  }

  window.addEventListener('mcs:route-ready',()=>queueMicrotask(refreshEngineerUX));
  window.addEventListener('mcs:route-start',()=>queueMicrotask(renderProjectContext));
  window.addEventListener('mcs:model-runtime-check',()=>queueMicrotask(()=>{renderRunSummary();renderProjectContext()}));
  document.addEventListener('input',e=>{if(e.target.closest('#taskForm'))queueMicrotask(()=>{renderRunSummary();renderProjectContext()})},true);
  document.addEventListener('change',e=>{
    if(e.target.matches('[data-output]'))saveOutputPreset();
    if(e.target.closest('#taskForm')||e.target.id==='userMode')queueMicrotask(()=>{tuneWizardCopy();renderRunSummary();renderProjectContext()});
  },true);
  document.addEventListener('click',e=>{if(e.target.closest('#selectRecommendedOutputs'))setTimeout(saveOutputPreset,0)},true);

  window.MCSEngineerUXV029={render:refreshEngineerUX,renderProjectContext,renderRunSummary,applyOutputPreset,saveOutputPreset};
  let tries=0; const init=()=>{tries++;refreshEngineerUX();if((!$q('#taskWizardHeader')||!$q('#engineerTaskGridV029'))&&tries<20)setTimeout(init,120)}; setTimeout(init,40);
})();
