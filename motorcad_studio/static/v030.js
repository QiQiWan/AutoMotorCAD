/* MotorCAD Studio V0.30.0 UX convergence.
   Engineering-first presentation layer: current motor -> analysis -> solve -> result.
   Internal traceability objects remain available under advanced details. */
(() => {
  const $q=(s,r=document)=>r.querySelector(s), $$q=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=v=>typeof window.esc==='function'?window.esc(v):String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const text=(v,f='—')=>v===null||v===undefined||v===''?f:String(v);
  const STATUS={
    READY:{label:'可以计算',tone:'ready',icon:'✓'},
    NEEDS_CHECK:{label:'需要检查',tone:'needs-check',icon:'•'},
    BLOCKED:{label:'无法计算',tone:'blocked',icon:'!'},
    RUNNING:{label:'计算中',tone:'running',icon:'●'},
    COMPLETED:{label:'已完成',tone:'completed',icon:'✓'},
  };
  const taskStatus={QUEUED:'等待计算',RUNNING:'计算中',RECOVERING:'正在恢复',COMPLETED:'已完成',PARTIALLY_COMPLETED:'部分完成',FAILED:'计算失败',CANCELLED:'已取消'};
  const qualityStatus={VALID:'结果完整',WARNING:'有结果提示',INVALID:'结果不可用',UNVERIFIED:'结果待验证'};
  state.uiLexiconV030=state.uiLexiconV030||null;
  state.uiGuidanceV030=state.uiGuidanceV030||null;
  state.uiGuidancePromiseV030=null;

  function isEngineering(){return (document.body.dataset.userMode||'engineering')==='engineering'}
  function isGuided(){return document.body.dataset.userMode==='operator'}
  function routeGo(tab){if(typeof window.showTab==='function')window.showTab(tab)}
  function directRoute(route){if(window.MCSRouter?.navigate)return window.MCSRouter.navigate(route);return null}
  function activeTab(){return $q('.tab.active')?.id||''}
  function selectedDesignLabel(){
    const rec=state.projectRevisionIndex?.get?.(state.taskDesignRevisionId);
    if(rec)return `${rec.design?.name||'电机'} · 设计版本 ${rec.revision?.revision??'-'}`;
    if(state.workspaceDesign&&state.workspaceRevision)return `${state.workspaceDesign.name||'电机'} · 设计版本 ${state.workspaceRevision.revision??'-'}`;
    if(state.workspaceDesign)return state.workspaceDesign.name||'当前电机';
    return '尚未选择电机';
  }
  function operatingPointLabel(){
    const rec=state.projectScenarioRevisionIndex?.get?.(state.taskScenarioRevisionId);
    if(rec){const s=rec.revision?.scenario||{};const pieces=[];if(Number.isFinite(Number(s.shaft_speed_rpm)))pieces.push(`${Number(s.shaft_speed_rpm)} rpm`);if(Number.isFinite(Number(s.peak_current_a)))pieces.push(`${Number(s.peak_current_a)} A`);return `${rec.scenario?.name||'工况'}${pieces.length?' · '+pieces.join(' / '):''}`}
    const speed=Number($q('#scenarioSpeedV021')?.value),current=Number($q('#scenarioPeakCurrentV021')?.value),voltage=Number($q('#scenarioDcVoltageV021')?.value);
    const parts=[];if(Number.isFinite(speed))parts.push(`${speed} rpm`);if(Number.isFinite(current))parts.push(`${current} A`);if(Number.isFinite(voltage))parts.push(`${voltage} V`);
    return parts.length?parts.join(' / '):'使用当前工况';
  }
  function analysisLabel(){return $q('#analysis')?.selectedOptions?.[0]?.textContent||$q('#analysis')?.value||'尚未选择分析'}

  async function loadLexicon(){
    if(state.uiLexiconV030)return state.uiLexiconV030;
    try{state.uiLexiconV030=await api('/api/ui/lexicon')}catch{state.uiLexiconV030={}}
    return state.uiLexiconV030;
  }

  function issueCopy(issue={}){
    const row=state.uiLexiconV030?.issues?.[issue.code]||null;
    const fallback=typeof window.MCSIssueText==='function'?window.MCSIssueText(issue):{title:'当前配置需要处理',message:issue.message||'',suggestion:issue.suggestion||''};
    const message=issue.message||fallback.message||'';
    return {
      title:row?.title||fallback.title||'当前配置需要处理',
      what:message||row?.reason||fallback.explain||'',
      reason:row?.reason||fallback.explain||message,
      impact:row?.impact||(String(issue.severity).toUpperCase()==='BLOCKING'?'当前问题会阻止计算。':'当前问题不会立即阻止配置，但建议在计算前确认。'),
      action:row?.action||issue.suggestion||fallback.suggestion||'根据提示检查相关模型参数。',
      code:issue.code||'CHECK_MESSAGE',
      severity:String(issue.severity||'WARNING').toUpperCase(),
    };
  }

  function humanIssueCard(issue={}){
    const c=issueCopy(issue);const blocking=c.severity==='BLOCKING'||c.severity==='ERROR';
    return `<article class="engineer-issue-v030 ${blocking?'blocking':'warning'}" data-issue-code-v030="${safe(c.code)}">
      <div class="engineer-issue-head-v030"><span>${blocking?'!':'i'}</span><div><b>${safe(c.title)}</b><small>${blocking?'需要先解决':'需要确认'}</small></div></div>
      <div class="engineer-issue-body-v030"><p>${safe(c.what)}</p><dl><div><dt>为什么</dt><dd>${safe(c.reason)}</dd></div><div><dt>影响</dt><dd>${safe(c.impact)}</dd></div><div><dt>怎么处理</dt><dd>${safe(c.action)}</dd></div></dl></div>
      <details><summary>技术详情</summary><div class="engineer-technical-v030"><code>${safe(c.code)}</code>${issue.message?`<p>${safe(issue.message)}</p>`:''}${issue.suggestion?`<p>${safe(issue.suggestion)}</p>`:''}</div></details>
    </article>`;
  }

  function overrideValidationRendering(){
    if(window.__v030ValidationWrapped)return;window.__v030ValidationWrapped=true;
    const previous=window.renderValidation;
    if(typeof previous!=='function')return;
    window.renderValidation=function(v){
      previous(v);
      const summary=$q('#validationSummary');if(summary){summary.textContent=v.valid?(v.warnings?`基础检查通过，还有 ${v.warnings} 项需要确认`:'基础检查通过'):`发现 ${v.blocking} 个必须先解决的问题`;summary.classList.add('engineer-validation-summary-v030')}
      const box=$q('#validationIssues');if(box)box.innerHTML=(v.issues||[]).map(humanIssueCard).join('');
      queueMicrotask(renderCalculationSummary);
    };
  }

  async function fetchProjectGuidance(force=false){
    if(!state.activeProjectId)return null;
    if(state.uiGuidancePromiseV030&&!force)return state.uiGuidancePromiseV030;
    const promise=(async()=>{try{const r=await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/ui-guidance`);state.uiGuidanceV030=r;window.MCSAppCoreV062?.emit?.('mcs:guidance-updated',{guidance:r});return r}catch(e){console.warn('ui guidance',e);return null}finally{state.uiGuidancePromiseV030=null}})();
    state.uiGuidancePromiseV030=promise;return promise;
  }

  function flowCurrentStep(){
    const tab=activeTab();
    if(['workspace','templates'].includes(tab))return'design';
    if(['newTask','tasks','simulationAssets'].includes(tab))return'analysis';
    if(tab==='monitor')return'solve';
    if(tab==='resultViewer')return'result';
    return state.uiGuidanceV030?.current_step||'design';
  }
  function ensureFlowBar(){
    const shell=$q('#projectShell');if(!shell)return null;
    let bar=$q('#engineerFlowBarV030');if(bar)return bar;
    bar=document.createElement('div');bar.id='engineerFlowBarV030';bar.className='engineer-flow-v030';
    const anchor=$q('#projectSecondaryNav');if(anchor)anchor.insertAdjacentElement('afterend',bar);else shell.appendChild(bar);
    return bar;
  }
  function renderFlowBar(){
    const bar=ensureFlowBar();if(!bar)return;
    if(!state.activeProjectId||$q('#projectShell')?.classList.contains('hidden')){bar.classList.add('hidden');return}
    bar.classList.remove('hidden');const current=flowCurrentStep();
    const running=state.uiGuidanceV030?.status==='RUNNING';
    const rows=[
      ['design','1','设计电机','确定结构、几何和绕组','workspace'],
      ['analysis','2','分析与计算','工况、求解设置、Precheck 与提交','analysisWorkbench'],
      ['solve','3','运行计算',running?'Motor-CAD 正在计算':'Precheck 通过后提交计算',running?'monitor':'analysisWorkbench'],
      ['result','4','分析结果','查看性能并决定下一轮设计','resultViewer'],
    ];
    bar.innerHTML=`<div class="engineer-flow-label-v030"><b>当前工程流程</b><span>按工程任务理解页面，内部版本与运行对象放到高级信息。</span></div><div class="engineer-flow-steps-v030">${rows.map(([id,n,title,desc,tab])=>`<button type="button" data-flow-step-v030="${id}" data-flow-tab-v030="${tab}" class="${id===current?'active':''}"><span>${n}</span><div><b>${title}</b><small>${desc}</small></div></button>`).join('<i>→</i>')}</div>`;
    $$q('[data-flow-tab-v030]',bar).forEach(btn=>btn.addEventListener('click',()=>routeGo(btn.dataset.flowTabV030)));
  }

  function simplifyGlobalNavigation(){
    const labels={projects:'项目',setup:'运行环境',logs:'问题',system:'高级工具'};
    $$q('.global-nav [data-tab]').forEach(btn=>{if(labels[btn.dataset.tab])btn.textContent=labels[btn.dataset.tab]});
    const projectLabels={dashboard:'概览',workspace:'设计电机',analysisWorkbench:'分析与计算',newTask:'高级任务配置',resultViewer:'分析结果',dataFactory:'数据资产'};
    $$q('.project-stage-nav [data-tab]').forEach(btn=>{const span=btn.querySelector('span')?.outerHTML||'';const label=projectLabels[btn.dataset.tab];if(label)btn.innerHTML=`${span}${label}`});
  }

  function simplifySetup(){
    const setup=$q('#setup');if(!setup)return;
    const hero=setup.querySelector('.startup-hero');if(hero){const h=hero.querySelector('h2'),p=hero.querySelector('p');if(h)h.textContent='确认这台电脑可以运行 Motor-CAD';if(p)p.textContent='通常只需要首次配置一次。绑定 Motor-CAD.exe 后执行检查，项目计算会自动使用这里的配置。'}
    if($q('#runtimeAdvancedV030'))return;
    const worker=setup.querySelector('.worker-pool-panel-v026'),scheduler=setup.querySelector('.runtime-scheduler-panel-v027');if(!worker&&!scheduler)return;
    const details=document.createElement('details');details.id='runtimeAdvancedV030';details.className='panel runtime-advanced-v030';
    details.innerHTML='<summary><span><b>高级运行信息</b><small>Worker、许可证容量、内存调度和运行时稳定性证据。普通计算无需操作。</small></span><span>高级</span></summary><div class="runtime-advanced-body-v030"></div>';
    const body=details.querySelector('.runtime-advanced-body-v030');
    if(worker){worker.classList.remove('panel');body.appendChild(worker)}if(scheduler){scheduler.classList.remove('panel');body.appendChild(scheduler)}
    const next=setup.querySelector('.startup-next-panel');if(next)next.insertAdjacentElement('beforebegin',details);else setup.appendChild(details);
  }

  function simplifyOverviewReadiness(){
    const box=$q('#workflowRibbon');if(!box)return;
    const mappings={
      project:['项目已进入','当前项目是所有电机、计算和结果的工作边界。'],
      design:['电机模型','至少需要一个可以用于计算的设计版本。'],
      motorcad:['运行环境','Motor-CAD.exe 与 PyMotorCAD 需要满足基础启动条件。'],
      qualification:['首次实机验证','首次使用某模板/分析时会建立真实计算证据。'],
      results:['计算结果','完成一次计算后即可进入结果分析。'],
    };
    $$q('[data-workflow-step]',box).forEach(el=>{const row=mappings[el.dataset.workflowStep];if(!row)return;const b=el.querySelector('b'),s=el.querySelector('small');if(b)b.textContent=row[0];if(s&&!s.textContent.trim())s.textContent=row[1]});
    const q=box.querySelector('[data-workflow-step="qualification"]');if(q&&!q.classList.contains('attention'))q.classList.add('engineer-secondary-check-v030');
  }

  function renderOverviewGuidance(g){
    if(!g)return;const st=STATUS[g.status]||STATUS.NEEDS_CHECK;
    const card=$q('#projectNextActionCard');if(card)card.innerHTML=`<div class="next-action-card-v030 ${st.tone}"><div class="next-action-state-v030"><span>${st.icon}</span><div><small>${safe(g.status_label||st.label)}</small><h3>${safe(g.headline)}</h3></div></div><p>${safe(g.reason)}</p><button type="button" class="primary" data-guidance-route-v030="${safe(g.action?.route||'')}">${safe(g.action?.label||'继续')}</button></div>`;
    const primary=$q('#overviewPrimaryAction');if(primary)primary.innerHTML=`<button type="button" class="primary overview-cta" data-guidance-route-v030="${safe(g.action?.route||'')}">${safe(g.action?.label||'继续')}</button><small>${safe(g.headline)}</small>`;
    $$q('[data-guidance-route-v030]').forEach(b=>b.addEventListener('click',()=>directRoute(b.dataset.guidanceRouteV030)));
    const metrics=$q('#dashboardMetrics');if(metrics){$$q('.metric-card span',metrics).forEach(el=>{const map={Design:'电机方案',Scenario:'已保存工况','仿真任务':'计算记录','失败/部分完成':'需要处理'};const k=el.textContent.trim();if(map[k])el.textContent=map[k]})}
  }

  async function refreshGuidance(){const g=await fetchProjectGuidance();renderOverviewGuidance(g);renderFlowBar();simplifyOverviewReadiness();return g}

  function labelFor(el,textValue){const label=el?.closest('label');if(label){const nodes=[...label.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim());if(nodes[0])nodes[0].textContent=textValue;else label.insertAdjacentText('afterbegin',textValue)}return label}
  function panelByHeading(fragment){return $$q('#taskForm article.panel').find(p=>(p.querySelector('h2')?.textContent||'').includes(fragment))||null}

  function simplifySimulationForm(){
    const form=$q('#taskForm');if(!form)return;
    form.classList.add('simulation-converged-v030');
    const header=$q('#taskWizardHeader');if(header){header.classList.add('simulation-header-v030');const eyebrow=header.querySelector('.eyebrow'),h=header.querySelector('h2'),p=header.querySelector('p');if(eyebrow)eyebrow.textContent='本次分析';if(h)h.textContent='设置本次分析并开始计算';if(p)p.textContent=isGuided()?'按步骤完成电机、工况、分析和结果配置；系统会告诉你什么时候可以开始计算。':'在一个页面中确认电机、运行工况、分析类型和需要的结果。内部版本、任务和执行信息默认收起。'}
    const panels=state.taskWizardPanelsV019||[];const context=panels[0],scenario=panels[1],method=panels[2],outputs=panels[3],submit=panels[4];
    if(context){const h=context.querySelector('h2'),p=context.querySelector('.section-head p');if(h)h.textContent='电机模型';if(p)p.textContent='确认这次要计算哪一个已保存的电机设计版本。'}
    if(scenario){const h=scenario.querySelector('h2'),p=scenario.querySelector('.section-head p');if(h)h.textContent='运行工况';if(p)p.textContent='设置转速、电流、电压、温度和冷却条件。'}
    if(method){const h=method.querySelector('h2'),p=method.querySelector('.section-head p');if(h)h.textContent='分析与计算方式';if(p)p.textContent='选择分析类型，以及单点、扫描、DOE 或优化。'}
    if(outputs){const h=outputs.querySelector('h2'),p=outputs.querySelector('.section-head p');if(h)h.textContent='需要的结果';if(p)p.textContent='常用结果会自动恢复；只勾选这次真正需要查看的输出。'}
    if(submit){const h=submit.querySelector('h2'),p=submit.querySelector('.section-head p');if(h)h.textContent='检查并开始计算';if(p)p.textContent='系统只显示一个最终状态：需要检查、无法计算或可以计算。'}
    const analysis=$q('#analysis')?.closest('label');if(analysis&&method&&!method.contains(analysis)){analysis.dataset.v030Moved='1';const target=method.querySelector('.mode-tabs')||method.querySelector('.section-head');target?.insertAdjacentElement(target.classList?.contains('mode-tabs')?'beforebegin':'afterend',analysis);labelFor($q('#analysis'),'分析类型')}
    labelFor($q('#taskDesignRevisionSelect'),'电机设计版本');
    const drawer=$q('#taskOverrideDrawer');if(drawer){const b=drawer.querySelector('summary b'),small=drawer.querySelector('summary small');if(b)b.textContent='临时修改电机参数（可选）';if(small)small.textContent='只影响这一次计算。需要长期保留的修改请回“设计电机”保存为新版本。'}
    const rec=$q('.revision-save-row');if(rec)rec.classList.add('engineer-technical-row-v030');
    const templateLabel=$q('#templateSelect')?.closest('label'),solverLabel=$q('#solverMode')?.closest('label'),taskNameLabel=$q('#taskName')?.closest('label'),qualityLabel=$q('#qualityProfile')?.closest('label');
    [templateLabel,solverLabel,taskNameLabel,qualityLabel].forEach(el=>el?.classList.add('engineer-advanced-field-v030'));
    if(method&&!$q('#simulationAdvancedV030')){
      const details=document.createElement('details');details.id='simulationAdvancedV030';details.className='advanced-fold simulation-advanced-v030';details.innerHTML='<summary><b>高级计算设置</b><span>任务名称、模板来源、质量配置和底层求解设置</span></summary><div class="simulation-advanced-grid-v030"></div>';const body=details.querySelector('div');
      [taskNameLabel,templateLabel,solverLabel,qualityLabel].forEach(el=>{if(el)body.appendChild(el)});method.appendChild(details);
    }
    const nativeBtn=$q('#geometryRuntimeCheck');if(nativeBtn)nativeBtn.textContent='独立 Motor-CAD 检查（排障用）';
    const quickBtn=$q('#validateTask');if(quickBtn)quickBtn.textContent='重新检查当前配置';
    const submitBtn=form.querySelector('button[type="submit"]');if(submitBtn)submitBtn.textContent='开始计算';
    if(isEngineering())panels.forEach(p=>p.classList.remove('task-wizard-hidden'));
    renderCalculationSummary();
  }

  function calculationState(){
    const gate=state.modelGateV020||{};
    if(state.taskSubmitBusyV022)return{status:'RUNNING',title:'正在创建计算',reason:'系统正在冻结本次配置并创建 Motor-CAD 计算。',action:'查看状态'};
    if(!state.taskDesignRevisionId)return{status:'NEEDS_CHECK',title:'先选择要计算的电机',reason:'本次分析必须基于一个已保存的电机设计版本。',action:'选择电机'};
    if(state.runtimeSubmissionReadyV028===false){const fail=(state.runtimeSubmissionChecksV028||[]).find(x=>String(x.status).toUpperCase()==='FAIL');return{status:'BLOCKED',title:'这台电脑暂时不能开始计算',reason:fail?.message||'Motor-CAD 运行环境需要先处理。',action:'修复运行环境',target:'setup'}}
    if(gate.validationValid===false||gate.localStatus==='BLOCKING'){
      const first=$q('#validationIssues [data-issue-code-v030],#geometryGuardDetails .model-failure-card');return{status:'BLOCKED',title:first?.querySelector('b')?.textContent||'当前模型有必须先解决的问题',reason:'修复下方标出的模型或配置问题后，再重新检查。',action:'定位问题',target:'issue'};
    }
    if(window.MCSModelGate?.ready?.())return{status:'READY',title:'当前配置可以开始计算',reason:'电机、工况和基础模型关系已经检查通过。正式计算会在同一个 Motor-CAD 会话中完成原生检查后直接求解。',action:'开始计算',target:'submit'};
    return{status:'NEEDS_CHECK',title:'需要检查当前配置',reason:'完成基础检查后，系统会明确告诉你是否可以开始计算。',action:'检查当前配置',target:'check'};
  }

  function calculationRows(){
    let outputCount=$$q('[data-output]:checked').length;let method='单点计算';const mode=$q('input[name="experimentMode"]:checked')?.value||'single';
    const map={single:'单点计算',sweep:'参数扫描',csv:'CSV 批量',full_factorial:'全因子 DOE',latin_hypercube:'拉丁超立方 DOE',random:'随机 DOE',pareto_search:'Pareto 筛选',nsga2:'NSGA-II 优化'};method=map[mode]||mode;
    return [['电机',selectedDesignLabel()],['运行工况',operatingPointLabel()],['分析',analysisLabel()],['计算方式',method],['需要结果',`${outputCount} 项`]];
  }

  function renderCalculationSummary(){
    const box=$q('#engineerRunSummaryV029');if(!box)return;const s=calculationState(),meta=STATUS[s.status]||STATUS.NEEDS_CHECK;
    box.classList.add('engineer-run-summary-v030');
    box.innerHTML=`<div class="calc-summary-head-v030"><span class="eyebrow">本次计算</span><h3>确认即将计算的内容</h3><p>如果这里的信息正确，只需完成检查并开始计算。</p></div>
      <div class="calc-summary-rows-v030">${calculationRows().map(([k,v])=>`<div><span>${safe(k)}</span><b>${safe(v)}</b></div>`).join('')}</div>
      <div class="calc-state-v030 ${meta.tone}"><div class="calc-state-title-v030"><span>${meta.icon}</span><div><small>${meta.label}</small><b>${safe(s.title)}</b></div></div><p>${safe(s.reason)}</p></div>
      <button type="button" id="engineerPrimaryActionV030" class="primary calc-primary-v030">${safe(s.action)}</button>
      <div class="calc-secondary-v030"><button type="button" data-v030-model>修改电机</button><button type="button" data-v030-results>查看结果</button></div>
      <details class="calc-technical-v030"><summary>高级：查看内部计算信息</summary><div><span>设计对象</span><code>${safe(state.taskDesignRevisionId||'-')}</code><span>运行环境</span><code>${safe(state.runtimeSubmissionReadyV028===true?'READY':state.runtimeSubmissionReadyV028===false?'BLOCKED':'CHECKING')}</code><span>检查状态</span><code>${safe((state.modelGateV020||{}).localStatus||'UNCHECKED')}</code></div></details>`;
    $q('#engineerPrimaryActionV030')?.addEventListener('click',()=>handlePrimaryAction(s));
    $q('[data-v030-model]',box)?.addEventListener('click',()=>routeGo('workspace'));$q('[data-v030-results]',box)?.addEventListener('click',()=>routeGo('resultViewer'));
    renderSimpleCalculationStatus(s);
  }

  async function handlePrimaryAction(s){
    if(!state.taskDesignRevisionId)return routeGo('workspace');
    if(s.target==='setup')return routeGo('setup');
    if(s.target==='issue'){const el=$q('#validationIssues .engineer-issue-v030,#geometryGuardDetails .model-failure-card,#geometryGuard');el?.scrollIntoView({behavior:'smooth',block:'center'});return}
    if(s.target==='submit')return $q('#taskForm')?.requestSubmit();
    if(s.target==='check'||s.status==='NEEDS_CHECK'){const btn=$q('#engineerPrimaryActionV030');if(btn){btn.disabled=true;btn.textContent='正在检查…'}try{await window.MCSModelGate?.runFullCheck?.()}finally{renderCalculationSummary()}return}
  }

  function renderSimpleCalculationStatus(s){
    const submit=$q('#taskForm .submit-panel');if(!submit)return;let box=$q('#userCalculationStatusV030');if(!box){box=document.createElement('div');box.id='userCalculationStatusV030';box.className='user-calc-status-v030';submit.prepend(box)}
    const meta=STATUS[s.status]||STATUS.NEEDS_CHECK;
    box.innerHTML=`<div class="user-calc-state-v030 ${meta.tone}"><span>${meta.icon}</span><div><small>当前状态 · ${meta.label}</small><h3>${safe(s.title)}</h3><p>${safe(s.reason)}</p></div></div>`;
  }

  function simplifyTechnicalStatus(){
    if(!isEngineering())return;
    $q('#submissionGateV020')?.classList.add('engineer-hidden-technical-v030');
    $q('#geometryGuard')?.classList.add('engineer-technical-fold-v030');
    const monitor=$q('#monitorContent');if(monitor){const worker=[...monitor.querySelectorAll('article.panel')].find(p=>(p.querySelector('h2')?.textContent||'').includes('活动 Worker'));worker?.classList.add('engineer-hidden-technical-v030');$q('#runtimeResourceEvidenceV027')?.classList.add('engineer-hidden-technical-v030');$q('#executionLeaseEvidenceV026')?.classList.add('engineer-hidden-technical-v030')}
  }

  function simplifyMonitor(){
    const top=$q('#monitor .monitor-toolbar');if(top){const h=top.querySelector('h2'),p=top.querySelector('p');if(h)h.textContent='计算进度';if(p)p.textContent='这里显示当前 Motor-CAD 计算到哪一步，以及是否需要你处理问题。'}
    const stage=$q('#monitorStageText');if(stage&&stage.textContent){stage.textContent=stage.textContent.replace(/VALIDATED_FOR_RUN/gi,'模型检查通过').replace(/SOLVING/gi,'正在求解').replace(/EXPORTING_FEA/gi,'正在整理有限元结果').replace(/EXTRACTING/gi,'正在整理结果')}
    simplifyTechnicalStatus();
  }

  function resultJudgement(viewer){
    const c=viewer?.case||{},flags=viewer?.quality||[],warnings=viewer?.warnings||[],scalars=viewer?.results?.scalars||{},schema=viewer?.output_schema||{};
    const exec=String(c.execution_status||'');const quality=String(c.quality_status||'');
    let title='结果已生成',detail='可以查看关键性能并决定下一轮设计。',tone='completed';
    if(exec!=='SUCCEEDED'&&exec!=='SUCCESS'&&exec!=='COMPLETED'){title='这次计算没有得到完整结果';detail='先查看计算问题，再决定是否修改模型或重新计算。';tone='blocked'}
    else if(quality==='WARNING'){title='计算完成，但有结果提示需要确认';detail=`当前有 ${flags.length||warnings.length} 项结果完整性或质量提示。主要计算结果仍可查看，但做设计决策前建议确认提示。`;tone='needs-check'}
    else if(quality==='INVALID'){title='结果不适合作为有效工程结论';detail='当前结果被质量检查判定为不可用，请先处理问题。';tone='blocked'}
    const preferred=['shaft_torque_nm','efficiency_percent','output_power_w','total_loss_w','winding_max_temperature_c','magnet_loss_w'];
    const metrics=preferred.filter(k=>scalars[k]!==null&&scalars[k]!==undefined).slice(0,6).map(k=>({id:k,label:schema[k]?.label||k,unit:schema[k]?.unit||schema[k]?.canonical_unit||'',value:scalars[k]}));
    return{title,detail,tone,metrics,flags,warnings};
  }

  function renderResultSummary(){
    const viewer=state.viewer,content=$q('#viewerCaseMode');if(!viewer||!content)return;
    let box=$q('#engineeringResultSummaryV030');if(!box){box=document.createElement('article');box.id='engineeringResultSummaryV030';box.className='panel engineering-result-summary-v030';const toolbar=$q('#viewerCaseMode .viewer-case-toolbar');toolbar?.insertAdjacentElement('afterend',box)}
    const j=resultJudgement(viewer);const meta={completed:{icon:'✓',label:'已完成'},'needs-check':{icon:'i',label:'需要确认'},blocked:{icon:'!',label:'需要处理'}}[j.tone]||{icon:'✓',label:'已完成'};
    box.innerHTML=`<div class="result-judgement-v030 ${j.tone}"><div class="result-judgement-title-v030"><span>${meta.icon}</span><div><small>${meta.label}</small><h2>${safe(j.title)}</h2><p>${safe(j.detail)}</p></div></div><div class="result-actions-v030"><button type="button" data-v030-edit-motor>修改电机</button><button type="button" data-v030-batch>与其他结果比较</button></div></div>
      <div class="result-key-metrics-v030">${j.metrics.length?j.metrics.map(m=>`<div><span>${safe(m.label)}</span><b>${safe(typeof m.value==='number'?Number(m.value).toLocaleString(undefined,{maximumFractionDigits:3}):m.value)}${m.unit?' <em>'+safe(m.unit)+'</em>':''}</b></div>`).join(''):'<div class="muted">当前结果没有可展示的关键标量指标。</div>'}</div>
      ${(j.flags.length||j.warnings.length)?`<details class="result-quality-details-v030"><summary>查看 ${j.flags.length||j.warnings.length} 项结果提示</summary><div>${j.flags.slice(0,8).map(f=>humanIssueCard({code:f.code||'RESULT_WARNING',severity:f.severity||'WARNING',message:f.message||'',suggestion:f.suggestion||''})).join('')||j.warnings.slice(0,8).map(w=>`<div class="engineer-issue-v030 warning"><p>${safe(typeof w==='string'?w:(w.message||JSON.stringify(w)))}</p></div>`).join('')}</div></details>`:''}`;
    $q('[data-v030-edit-motor]',box)?.addEventListener('click',()=>routeGo('workspace'));$q('[data-v030-batch]',box)?.addEventListener('click',()=>{const b=$q('[data-viewer-mode="batch"]');b?.click()});
  }

  function wrapResultViewer(){
    if(window.__v030ViewerWrapped)return;window.__v030ViewerWrapped=true;
    const previous=window.openCaseViewer;if(typeof previous!=='function')return;
    window.openCaseViewer=async function(...args){const r=await previous.apply(this,args);renderResultSummary();localizeResultViewer();return r};
  }
  function localizeResultViewer(){
    const head=$q('.result-viewer-header');if(head){const h=head.querySelector('h2'),p=head.querySelector('p');if(h)h.textContent='分析计算结果';if(p)p.textContent='先看关键性能和结果质量，再按需要进入曲线、有限元场或批量对比。'}
    labelFor($q('#viewerTaskSelect'),'计算记录');labelFor($q('#viewerCaseSelect'),'算例');
    const empty=$q('#viewerEmpty');if(empty&&!state.viewer)empty.textContent='选择一条已完成计算，查看关键性能和完整结果。';
  }

  function localizeWorkspace(){
    const h=$q('#workspace .workspace-toolbar h2'),p=$q('#workspace .workspace-toolbar p');if(h&&h.textContent.trim()==='设计')h.textContent='设计电机';if(p)p.textContent='在这里修改电机结构、几何、绕组和材料。长期修改保存为新的设计版本。';
    const treeHead=$q('#workspace .workspace-tree h3'),treeP=$q('#workspace .workspace-tree p');if(treeHead)treeHead.textContent='电机方案';if(treeP)treeP.textContent='选择电机和设计版本';
    $$q('#workspaceProjectTree .tree-group-label').forEach(el=>el.textContent=el.textContent.replace(/^DESIGN/i,'电机方案'));
    const edit=$q('#workspaceEditRevision');if(edit)edit.textContent='修改电机并保存为新版本';const use=$q('#workspaceUseRevision');if(use)use.textContent='使用这个版本进行计算';const clone=$q('#workspaceCreateRevision');if(clone)clone.textContent='复制为新设计版本';
  }

  function localizeTemplates(){
    const h=$q('#templates .template-stage-header h2'),p=$q('#templates .template-stage-header p');if(h)h.textContent='从模板创建电机';if(p)p.textContent='选择一个接近目标的 Motor-CAD 模板作为起点，然后在“设计电机”中继续修改。';
  }

  function localizeTaskRecords(){
    const section=$q('#tasks');if(!section)return;let heading=section.querySelector('.v030-task-title');if(!heading){heading=document.createElement('article');heading.className='panel v030-task-title';heading.innerHTML='<div><span class="eyebrow">计算记录</span><h2>历史计算</h2><p>查看每次计算的状态、结果和失败原因。内部 Task/Case 标识只在详情中使用。</p></div>';section.prepend(heading)}
  }

  function relabelDynamicStatus(){
    $$q('.status').forEach(el=>{const raw=el.textContent.trim();if(taskStatus[raw]){el.title=raw;el.textContent=taskStatus[raw]}else if(qualityStatus[raw]){el.title=raw;el.textContent=qualityStatus[raw]}});
    $$q('.case-head .status').forEach(el=>{el.textContent=el.textContent.replace(/^执行:/,'计算：').replace(/^质量:/,'结果：')});
  }

  function simplifyProjectLanguage(){
    const listP=$q('.project-list-panel .section-head p');if(listP)listP.textContent='每个项目包含自己的电机方案、运行工况、计算记录和结果。';
    const objects=$q('#dashboard .project-overview-lower article:first-child .section-head h2');if(objects)objects.textContent='电机与运行工况';
    const recent=$q('#dashboard .project-overview-lower article:last-child .section-head h2');if(recent)recent.textContent='最近计算';
  }

  async function refreshV030({guidance=true}={}){
    await loadLexicon();simplifyGlobalNavigation();simplifySetup();simplifySimulationForm();localizeWorkspace();localizeTemplates();localizeTaskRecords();localizeResultViewer();simplifyMonitor();simplifyProjectLanguage();simplifyOverviewReadiness();relabelDynamicStatus();renderCalculationSummary();renderResultSummary();renderFlowBar();if(guidance&&state.activeProjectId)refreshGuidance();
  }

  // The V0.29 layer schedules its own post-render microtasks. Register later and
  // use another microtask so the user-facing layer always wins without removing
  // traceability behavior underneath.
  window.addEventListener('mcs:route-ready',()=>queueMicrotask(()=>refreshV030({guidance:true})));
  window.addEventListener('mcs:route-start',()=>queueMicrotask(renderFlowBar));
  document.addEventListener('input',e=>{if(e.target.closest('#taskForm'))queueMicrotask(()=>{simplifySimulationForm();renderCalculationSummary()})},true);
  document.addEventListener('change',e=>{if(e.target.closest('#taskForm')||e.target.id==='userMode')queueMicrotask(()=>refreshV030({guidance:false}))},true);
  document.addEventListener('click',e=>{if(e.target.closest('#validateTask,#runFullModelGateV020,#restoreTaskBaselineV020,[data-task-wizard-jump],[data-task-next],[data-task-prev]'))setTimeout(()=>renderCalculationSummary(),0)},true);

  wrapResultViewer();overrideValidationRendering();
  window.MCSUXV030={refresh:refreshV030,refreshGuidance,calculationState,renderCalculationSummary,issueCopy,renderResultSummary};
  let tries=0;const init=()=>{tries++;refreshV030({guidance:true});if((!$q('#taskWizardHeader')||!$q('#projectShell'))&&tries<30)setTimeout(init,100)};setTimeout(init,30);
})();
