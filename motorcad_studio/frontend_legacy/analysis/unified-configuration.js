/* V0.89-G5 Unified Analysis Configuration HMI.
 * Retains the V0.81-C analysis-template API compatibility boundary.
 *
 * Canonical ownership boundary:
 * motor revision -> analysis definition -> immutable analysis revision -> execution plan.
 * Legacy task-setup and engineering-sheet analysis surfaces are compatibility only.
 */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const tr=(zh,en)=>window.MCS_I18N?.t?.(zh,en)??zh;
  const text={
    get noProject(){return tr('请先进入项目。','Open a project first.')},
    get noRevision(){return tr('当前项目还没有可用的电机版本，请先完成电机配置。','This project has no motor revision yet. Complete motor configuration first.')},
    get loadFailed(){return tr('分析配置加载失败','Failed to load analysis configuration')},
    get saved(){return tr('已保存并生成新的分析版本','Saved as a new analysis revision')},
    get create(){return tr('新建分析配置','Create analysis configuration')},
  };
  const moduleLabel=value=>window.MCSAnalysisLabels?.moduleLabel?.(value)||String(value||tr('分析','Analysis'));
  const recipeLabel=value=>window.MCSAnalysisLabels?.recipeLabel?.(value)||String(value||tr('分析配方','Analysis recipe'));
  const revisionLabel=(value,kind='analysis')=>window.MCSAnalysisLabels?.revisionLabel?.(value,kind)||tr(`${kind==='motor'?'电机':'分析'}版本 ${value??'—'}`,`${kind==='motor'?'Motor':'Analysis'} revision ${value??'—'}`);
  const moduleLabels=new Proxy({}, {get:(_,key)=>moduleLabel(key)});
  const steps=['definition','operating','inputs','solver','check'];
  const stepLabels=new Proxy({}, {get:(_,key)=>({definition:tr('分析定义','Analysis definition'),operating:tr('工况','Operating points'),inputs:tr('物理输入','Physical inputs'),solver:tr('求解与输出','Solver and outputs'),check:tr('检查并计算','Check and calculate')})[key]||String(key)});
  const commonOperatingFields=()=>[
    {id:'shaft_speed_rpm',label:tr('转速','Speed'),unit:'rpm'},
    {id:'peak_current_a',label:tr('峰值电流','Peak current'),unit:'A'},
    {id:'rms_current_a',label:tr('有效值电流','RMS current'),unit:'A'},
    {id:'dc_bus_voltage_v',label:tr('直流母线电压','DC bus voltage'),unit:'V'},
    {id:'phase_advance_deg',label:tr('超前角','Phase advance'),unit:'deg'},
    {id:'ambient_temperature_c',label:tr('环境温度','Ambient temperature'),unit:'\u00b0C'},
  ];
  const unitLabel=value=>window.MCSDesignRenderUtils?.unitLabel?.(value)||String(value||'');
  const ctl={
    ctx:null,route:null,project:null,designs:[],revisionIndex:new Map(),definitions:[],catalog:null,
    activeId:null,active:null,inputCatalog:null,step:'definition',domainId:null,executionPlan:null,fullCheck:null,
    selectedRevisionId:null,createRecipeId:null,createTemplateId:null,templateCatalog:null,templatePreview:null,templatePreviewLoading:false,guidance:null,qualityProfile:'standard',reuseCache:true,busy:false,requestToken:0,
    catalogRevisionId:null,templateCatalogRevisionId:null,templatePreviewCache:new Map(),
    submissionKey:null,submissionFingerprint:null,transitionBusy:false,mountPromise:null,mountOwner:null,refreshPromise:null,definitionsProjectId:null,workspaceClient:null,guidanceRequestToken:0,guidanceTimer:null,
    hmiMode:localStorage.getItem('mcs-analysis-hmi-mode')||localStorage.getItem('mcs-analysis-hmi-mode-v081a')||'common',returnToCheck:null,
  };
  const contextStore=()=>window.MCSEngineeringContext;
  const currentContext=()=>contextStore()?.get?.()||{};
  const activeDefinition=()=>ctl.active?.revisions?.[0]?.definition||{};
  const activeAnalysisRevision=()=>ctl.active?.revisions?.[0]||null;
  const activeRevisionRecord=()=>ctl.revisionIndex.get(ctl.active?.design_revision_id||ctl.selectedRevisionId)||null;
  const encode=value=>encodeURIComponent(String(value??''));
  const notify=(message,level='INFO',duration=6500)=>typeof window.toast==='function'&&window.toast(message,level,duration);
  async function apiCall(url,options={}){
    const timeoutMs=Number(options.timeoutMs??60000),requestOptions={...options};delete requestOptions.timeoutMs;
    if(!Number.isFinite(timeoutMs)||timeoutMs<=0)return ctl.ctx?.api?ctl.ctx.api(url,requestOptions):api(url,requestOptions);
    const controller=new AbortController(),parent=ctl.ctx?.signal,abortFromParent=()=>controller.abort(parent?.reason);
    if(parent?.aborted)abortFromParent();else parent?.addEventListener?.('abort',abortFromParent,{once:true});
    const timer=setTimeout(()=>controller.abort('REQUEST_TIMEOUT'),timeoutMs);requestOptions.signal=controller.signal;
    try{return await (ctl.ctx?.api?ctl.ctx.api(url,requestOptions):api(url,requestOptions))}
    catch(error){if(controller.signal.aborted&&!parent?.aborted){const timeoutError=new Error(`请求超过 ${Math.round(timeoutMs/1000)} 秒，已停止等待。`);timeoutError.code='REQUEST_TIMEOUT';throw timeoutError}throw error}
    finally{clearTimeout(timer);parent?.removeEventListener?.('abort',abortFromParent)}
  }
  const routeActive=()=>!ctl.ctx||window.MCSPageRuntime?.isContextActive?.(ctl.ctx)!==false;
  const latestRevision=design=>(design?.revisions||[]).slice().sort((a,b)=>Number(b.revision||0)-Number(a.revision||0))[0]||null;
  const recipeById=id=>(ctl.catalog?.recipes||[]).find(row=>String(row.id)===String(id))||null;
  const guidanceClient=()=>window.MCSAnalysisGuidance;
  const workspaceClient=()=>ctl.workspaceClient||(ctl.workspaceClient=window.MCSAnalysisWorkspaceClient?.create?.(apiCall)||null);
  const templateById=id=>(ctl.templateCatalog?.templates||[]).find(row=>String(row.id)===String(id))||null;
  const analysisPath=(analysisId=null,step=null)=>{
    const base=`/app/projects/${encode(state.activeProjectId)}/simulation/analyses`;
    if(!analysisId)return base;
    return step?`${base}/${encode(analysisId)}/configure/${encode(step)}`:`${base}/${encode(analysisId)}`;
  };

  function fieldLabel(id){return ({shaft_speed_rpm:tr('转速','Speed'),peak_current_a:tr('峰值电流','Peak current'),rms_current_a:tr('有效值电流','RMS current'),dc_bus_voltage_v:tr('直流母线电压','DC bus voltage'),phase_advance_deg:tr('超前角','Phase advance'),ambient_temperature_c:tr('环境温度','Ambient temperature')})[id]||id.replaceAll('_',' ')}
  function designLabel(record){return record?`${record.design?.name||record.design?.id||'-'} \u00b7 ${window.MCSAnalysisLabels?.revisionLabel?.(record.revision?.revision??'-','motor')||tr(`电机版本 ${record.revision?.revision??'-'}`,`Motor revision ${record.revision?.revision??'-'}`)}`:'-'}
  function statusClass(ok,warn=false){return ok?'pass':warn?'warn':'fail'}
  function normalizeBool(value){return value===true||value==='true'||value===1||value==='1'}
  function scalarFromInput(input,field){
    if(field?.type==='boolean'||input.type==='checkbox')return Boolean(input.checked);
    if(['number','float','integer'].includes(field?.type)||input.type==='number')return input.value===''?null:Number(input.value);
    return input.value;
  }
  function outputMeta(id){const spec=state.registry?.outputs?.[id]||{};return {label:spec.label||spec.name||id,unit:spec.unit||'',description:spec.description||''}}
  function canonical(value){if(Array.isArray(value))return value.map(canonical);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));return value}
  function sameValue(a,b){return JSON.stringify(canonical(a))===JSON.stringify(canonical(b))}
  function actionLock(key,operation){return window.MCSNavigationTransaction?.withActionLock?.(key,operation)??Promise.resolve().then(operation)}
  const operationProgress=options=>window.MCSOperationProgress?.start?.(options)||{update(){return this},done(){return this},fail(){return this},close(){return this}};
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function collectDomainValues(){const domain=(ctl.inputCatalog?.domains||[]).find(row=>row.id===ctl.domainId);if(!domain)return null;const values={};qa('[data-domain-field-v076]').forEach(input=>{const field=(domain.fields||[]).find(row=>String(row.id)===String(input.dataset.domainFieldV076));if(input.tagName==='SELECT'&&input.dataset.fieldTypeV076==='boolean')values[input.dataset.domainFieldV076]=input.value==='true';else values[input.dataset.domainFieldV076]=scalarFromInput(input,field)});return {domain,values}}
  function collectSolverDraft(){let solver={...(activeDefinition().solver_settings||{})};const raw=q('#analysisSolverJsonV076');if(raw)solver=JSON.parse(raw.value||'{}');const capture=q('#analysisNativeCaptureV076');if(capture)solver={...solver,native_screen_capture:{...(solver.native_screen_capture||{}),enabled:Boolean(capture.checked),screen:solver.native_screen_capture?.screen||'E-Magnetics;FEA'}};const required=new Set(recipeById(ctl.active?.recipe_id)?.required_outputs||[]),selected=qa('[data-output-v076]:checked').map(input=>input.dataset.outputV076),outputs=[...new Set([...required,...selected])].sort();return {solver_settings:solver,requested_outputs:outputs}}
  function currentStepDirty(){
    if(!ctl.active)return false;
    try{
      if(ctl.step==='operating'&&q('[data-case-v076]'))return !sameValue(collectCases(),activeDefinition().load_cases||[{}]);
      if(ctl.step==='inputs'&&q('[data-domain-field-v076]')){const collected=collectDomainValues();if(!collected)return false;const baseline={};for(const field of collected.domain.fields||[]){const saved=collected.domain.values?.[field.id];if(saved!==undefined&&saved!==null){baseline[field.id]=saved;continue}const options=field.options||field.allowed||field.values;if(field.type==='boolean')baseline[field.id]=false;else if(Array.isArray(options)&&options.length){const first=options[0];baseline[field.id]=typeof first==='object'?(first.id??first.value):first}else if(['number','float','integer'].includes(field.type))baseline[field.id]=null;else baseline[field.id]=''}return !sameValue(collected.values,baseline)}
      if(ctl.step==='solver'&&q('#analysisNativeCaptureV076')){const draft=collectSolverDraft(),definition=activeDefinition(),savedOutputs=[...new Set(definition.requested_outputs||[])].sort(),rawSolver={...(definition.solver_settings||{})},savedSolver={...rawSolver,native_screen_capture:{...(rawSolver.native_screen_capture||{}),enabled:rawSolver.native_screen_capture?.enabled!==false,screen:rawSolver.native_screen_capture?.screen||'E-Magnetics;FEA'}};return !sameValue(draft.solver_settings,savedSolver)||!sameValue(draft.requested_outputs,savedOutputs)}
    }catch{return true}
    return false;
  }
  async function flushCurrentAnalysisEditor({reason='transition',notifyOnSave=false}={}){
    if(!ctl.active||!currentStepDirty())return true;
    if(ctl.transitionBusy)return false;
    ctl.transitionBusy=true;
    try{
      let ok=true;
      if(ctl.step==='operating')ok=await saveOperatingCases({auto:true});
      else if(ctl.step==='inputs')ok=await saveInputDomain({auto:true});
      else if(ctl.step==='solver')ok=await saveSolver({auto:true});
      if(ok&&notifyOnSave)notify(`已自动保存当前配置后继续（${reason}）`,'INFO',4200);
      return ok!==false;
    }finally{ctl.transitionBusy=false}
  }
  function resetSubmissionKey(){ctl.submissionKey=null;ctl.submissionFingerprint=null}
  function stableSubmissionKey(plan,{quality,reuse,name}){const fingerprint=JSON.stringify([ctl.active?.id||'',plan?.analysis_revision?.id||'',plan?.design_revision?.id||'',plan?.execution_plan_hash||'',quality,Boolean(reuse),name]);if(!ctl.submissionKey||ctl.submissionFingerprint!==fingerprint){ctl.submissionKey=newSubmissionKey();ctl.submissionFingerprint=fingerprint}return ctl.submissionKey}

  async function fetchProjectGraph(op=null){
    // Retired G3 compatibility path: /api/solutions/${encode(row.id)}.  G4 uses
    // one analysis-workspace bootstrap so project load is no longer N+1.
    const projectId=state.activeProjectId;if(!projectId)throw new Error(text.noProject);
    op?.update?.({percent:12,stage:'读取项目',detail:'加载项目与方案索引'});
    const selectedHint=currentContext().motorRevisionId||state.workspaceRevision?.id||state.taskDesignRevisionId||localStorage.getItem(`motorcad-studio-design-revision:${projectId}`)||null;
    const bootstrap=workspaceClient()?await workspaceClient().bootstrap(projectId,selectedHint):await apiCall(`/api/projects/${encode(projectId)}/analysis-workspace${selectedHint?`?selected_revision_id=${encode(selectedHint)}`:''}`);if(!routeActive())return;
    const project=bootstrap.project||{};
    ctl.project=project;contextStore()?.setProject?.(project,{source:'analysis:project'});if(!contextStore())state.workspaceProject=project;
    ctl.designs=bootstrap.designs||[];
    ctl.definitions=bootstrap.analysis_definitions||[];
    ctl.definitionsProjectId=String(projectId);
    op?.update?.({percent:28,stage:'读取方案',detail:`已批量加载 ${ctl.designs.length} 个设计与版本`});
    ctl.revisionIndex=new Map();
    ctl.designs.forEach(design=>(design.revisions||[]).forEach(revision=>ctl.revisionIndex.set(String(revision.id),{design,revision})));
    const stored=currentContext().motorRevisionId;
    const legacy=state.workspaceRevision?.id||state.taskDesignRevisionId||localStorage.getItem(`motorcad-studio-design-revision:${projectId}`)||null;
    let selected=[stored,legacy].find(id=>id&&ctl.revisionIndex.has(String(id)))||null;
    if(!selected){for(const design of ctl.designs){const rev=latestRevision(design);if(rev){selected=rev.id;break}}}
    ctl.selectedRevisionId=selected?String(selected):null;
    const record=ctl.revisionIndex.get(ctl.selectedRevisionId)||null;
    if(record)contextStore()?.setMotorRevision?.(record.revision,{solution:record.design,source:'analysis:initial-revision'});
    op?.update?.({percent:38,stage:'方案就绪',detail:`已读取 ${ctl.designs.length} 个设计、${ctl.revisionIndex.size} 个电机版本`});
  }

  async function fetchCatalogForRevision(revisionId=ctl.selectedRevisionId,{force=false}={}){
    const revisionKey=String(revisionId||'');
    if(!force&&revisionKey&&ctl.catalogRevisionId===revisionKey&&ctl.catalog)return ctl.catalog;
    const record=ctl.revisionIndex.get(revisionKey);
    if(!record){ctl.catalog={recipes:[],modules:[]};ctl.catalogRevisionId=revisionKey;return ctl.catalog}
    const motorType=record.design?.motor_type_id||record.design?.motor_family||record.design?.motor_type||'BPM';
    try{
      ctl.catalog=await apiCall(`/api/analysis-catalog?motor_type_id=${encode(motorType)}${record.design?.template_id?`&template_id=${encode(record.design.template_id)}`:''}`);
    }catch(error){
      ctl.catalog={recipes:[],modules:[],error:error.message};
      console.warn('[analysis] optional analysis catalog unavailable',error);
    }
    ctl.catalogRevisionId=revisionKey;
    return ctl.catalog;
  }

  async function fetchTemplateCatalogForRevision(revisionId=ctl.selectedRevisionId,{force=false}={}){
    const revisionKey=String(revisionId||'');
    if(!force&&revisionKey&&ctl.templateCatalogRevisionId===revisionKey&&ctl.templateCatalog)return ctl.templateCatalog;
    if(!revisionId||!guidanceClient()){ctl.templateCatalog={templates:[],policy:{common_mode_max_decisions:3}};ctl.templateCatalogRevisionId=revisionKey;return ctl.templateCatalog}
    try{
      ctl.templateCatalog=await guidanceClient().listTemplates(apiCall,revisionId);
    }catch(error){
      ctl.templateCatalog={templates:[],policy:{common_mode_max_decisions:3},error:error.message};
      console.warn('[analysis] optional template catalog unavailable',error);
    }
    const available=ctl.templateCatalog?.templates?.filter(row=>row.available)||[];
    if(!ctl.createTemplateId||!available.some(row=>String(row.id)===String(ctl.createTemplateId)))ctl.createTemplateId=available[0]?.id||null;
    ctl.templateCatalogRevisionId=revisionKey;
    return ctl.templateCatalog;
  }

  async function refreshGuidance({render=false}={}){
    const activeId=ctl.active?.id||null,token=++ctl.guidanceRequestToken;
    if(!activeId||!guidanceClient()){ctl.guidance=null;return null}
    let guidance;
    try{guidance=await guidanceClient().guidance(apiCall,activeId)}catch(error){guidance={error:error.message,auto_fix_actions:[],recommendations:[]}}
    if(token!==ctl.guidanceRequestToken||String(ctl.active?.id||'')!==String(activeId)||!routeActive())return null;
    ctl.guidance=guidance;
    if(render)renderEditorBody();
    renderSummary();
    return ctl.guidance;
  }
  function scheduleGuidanceRefresh({delay=140}={}){
    clearTimeout(ctl.guidanceTimer);
    ctl.guidanceTimer=setTimeout(()=>{ctl.guidanceTimer=null;refreshGuidance({render:true}).catch(()=>{})},delay);
  }

  async function fetchDefinitions(){
    if(ctl.definitionsProjectId===String(state.activeProjectId))return ctl.definitions;
    ctl.definitions=await apiCall(`/api/projects/${encode(state.activeProjectId)}/analysis-definitions`)||[];
    ctl.definitionsProjectId=String(state.activeProjectId);
    return ctl.definitions;
  }

  async function hydrateActive(id,{render=true,op=null}={}){
    if(!id){ctl.activeId=null;ctl.active=null;ctl.inputCatalog=null;ctl.executionPlan=null;ctl.fullCheck=null;if(render)renderAll();return null}
    const token=++ctl.requestToken;
    op?.update?.({percent:62,stage:'加载分析配置',detail:'读取分析版本与物理输入'});
    const bundle=workspaceClient()?await workspaceClient().editor(id):null;
    const analysis=bundle?.analysis_definition||await apiCall(`/api/analysis-definitions/${encode(id)}`);
    const inputCatalog=bundle?.input_catalog||await apiCall(`/api/analysis-definitions/${encode(id)}/input-domains`);
    if(token!==ctl.requestToken||!routeActive())return null;
    ctl.activeId=analysis.id;ctl.active=analysis;ctl.inputCatalog=inputCatalog;ctl.executionPlan=null;ctl.fullCheck=null;ctl.guidance=null;
    const record=ctl.revisionIndex.get(String(analysis.design_revision_id));
    if(record){ctl.selectedRevisionId=String(record.revision.id);contextStore()?.setMotorRevision?.(record.revision,{solution:record.design,source:'analysis:hydrate-revision'})}
    contextStore()?.setAnalysis?.(analysis,{motorRevision:record?.revision||analysis.design_revision_id,analysisRevisionId:analysis.revisions?.[0]?.id||null,source:'analysis:hydrate'});
    if(!ctl.domainId||!inputCatalog.domains?.some(row=>row.id===ctl.domainId))ctl.domainId=inputCatalog.domains?.[0]?.id||null;
    op?.update?.({percent:78,stage:'加载工程模板',detail:'读取配方、专家模板与工程建议'});
    await Promise.all([fetchCatalogForRevision(analysis.design_revision_id),fetchTemplateCatalogForRevision(analysis.design_revision_id)]);
    scheduleGuidanceRefresh();
    op?.update?.({percent:92,stage:'汇总界面',detail:'生成工程上下文与分析摘要'});
    if(render)renderAll();
    return analysis;
  }

  function chooseInitialAnalysis(route){
    const candidates=[route?.analysisId,currentContext().analysisId,localStorage.getItem('motorcad-studio-analysis-case')].filter(Boolean).map(String);
    for(const id of candidates)if(ctl.definitions.some(row=>String(row.id)===id))return id;
    const sameRevision=ctl.definitions.find(row=>String(row.design_revision_id)===String(ctl.selectedRevisionId));
    return sameRevision?.id||null;
  }

  function resolveStep(route){
    const requested=route?.analysisStep||((route?.analysisAction==='execute'||route?.analysisAction==='precheck')?'check':null);
    return steps.includes(requested)?requested:'definition';
  }

  function renderContext(){
    const root=q('#analysisContextV076');if(!root)return;
    const selected=ctl.revisionIndex.get(String(ctl.selectedRevisionId||''));
    const activeRecord=activeRevisionRecord()||selected;
    const options=ctl.designs.map(design=>{
      const rows=(design.revisions||[]).slice().sort((a,b)=>Number(b.revision||0)-Number(a.revision||0));
      return rows.length?`<optgroup label="${safe(design.name||design.id)}">${rows.map(rev=>`<option value="${safe(rev.id)}" ${String(rev.id)===String(ctl.selectedRevisionId)?'selected':''}>${safe(window.MCSAnalysisLabels?.revisionLabel?.(rev.revision,'motor')||tr(`电机版本 ${rev.revision}`,`Motor revision ${rev.revision}`))} \u00b7 ${safe(rev.id)}</option>`).join('')}</optgroup>`:'';
    }).join('');
    root.innerHTML=`<div class="analysis-context-chain-v076">
      <div class="analysis-context-node-v076"><span>${tr('项目','Project')}</span><b>${safe(ctl.project?.name||state.activeProjectId||'-')}</b></div><i class="analysis-context-arrow-v076">\u203a</i>
      <div class="analysis-context-node-v076"><span>${tr('方案','Design')}</span><b>${safe(activeRecord?.design?.name||'-')}</b></div><i class="analysis-context-arrow-v076">\u203a</i>
      <div class="analysis-context-node-v076"><span>${tr('电机版本','Motor revision')}</span><b>${activeRecord?`${safe(window.MCSAnalysisLabels?.revisionLabel?.(activeRecord.revision?.revision,'motor')||tr(`电机版本 ${activeRecord.revision?.revision}`,`Motor revision ${activeRecord.revision?.revision}`))} \u00b7 ${safe(activeRecord.revision?.id)}`:'-'}</b></div><i class="analysis-context-arrow-v076">\u203a</i>
      <div class="analysis-context-node-v076"><span>${tr('分析配置','Analysis configuration')}</span><b>${safe(ctl.active?.name||tr('尚未选择','Not selected'))}</b></div>
    </div><div class="analysis-context-selector-v076"><label>${tr('新建分析时使用的电机版本','Motor revision for a new analysis')}<select id="analysisMotorRevisionV076" ${ctl.active?'disabled':''}><option value="">${tr('请选择','Select')}</option>${options}</select></label>${ctl.active?`<small class="hint">${tr('已有分析的电机版本请在“分析定义”中切换同方案版本。','Change the motor revision of an existing analysis in Analysis definition.')}</small>`:''}</div>`;
    q('#analysisMotorRevisionV076',root)?.addEventListener('change',async event=>{
      const id=event.target.value;if(!id)return;ctl.selectedRevisionId=id;const record=ctl.revisionIndex.get(id);contextStore()?.setMotorRevision?.(record?.revision||id,{solution:record?.design||null,source:'analysis:revision-select'});ctl.templatePreview=null;await Promise.all([fetchCatalogForRevision(id),fetchTemplateCatalogForRevision(id)]);renderContext();renderList();if(!ctl.active)renderCreateForm();renderSummary();
    });
  }

  function renderList(){
    const root=q('#analysisListV076');if(!root)return;
    if(!ctl.definitions.length){root.innerHTML='<div class="analysis-list-empty-v076">\u5f53\u524d\u9879\u76ee\u8fd8\u6ca1\u6709\u5206\u6790\u914d\u7f6e\u3002</div>';return}
    root.innerHTML=ctl.definitions.map(row=>{
      const rec=ctl.revisionIndex.get(String(row.design_revision_id));const latest=row.revisions?.[0];
      return `<button type="button" class="analysis-list-card-v076 ${String(row.id)===String(ctl.activeId)?'active':''}" data-analysis-id-v076="${safe(row.id)}"><header><b>${safe(row.name||row.id)}</b><span class="chip">${safe(moduleLabel(row.module))}</span></header><small>${safe(designLabel(rec))}</small><div class="analysis-list-meta-v076"><span class="chip">${safe(recipeLabel(row.recipe_id))}</span><span class="chip">${safe(window.MCSAnalysisLabels?.revisionLabel?.(latest?.revision??'-')||tr(`分析版本 ${latest?.revision??'-'}`,`Analysis revision ${latest?.revision??'-'}`))}</span></div></button>`;
    }).join('');
    qa('[data-analysis-id-v076]',root).forEach(button=>button.addEventListener('click',()=>window.MCSRouter?.navigate?.(analysisPath(button.dataset.analysisIdV076))));
  }

  function renderSteps(){
    qa('[data-analysis-step-v076]').forEach((button,index)=>{const current=steps.indexOf(ctl.step);button.classList.toggle('active',button.dataset.analysisStepV076===ctl.step);button.classList.toggle('done',index<current);button.onclick=()=>setStep(button.dataset.analysisStepV076)});
  }

  async function setStep(step,{replace=true,preserveReturn=false}={}){
    if(!steps.includes(step)||!ctl.active)return false;if(step===ctl.step)return true;
    if(!(await flushCurrentAnalysisEditor({reason:'step-change',notifyOnSave:true})))return false;
    if(!preserveReturn||step==='check')ctl.returnToCheck=null;
    ctl.step=step;renderSteps();renderEditorBody();renderSummary();
    if(window.MCSRouter?.setUrl)window.MCSRouter.setUrl(analysisPath(ctl.active.id,step),replace);
    if(step==='check'&&!ctl.executionPlan)loadExecutionPlan().catch(error=>notify(error.message,'WARNING'));
    return true;
  }

  function renderEmpty(){
    q('#analysisEmptyV076')?.classList.remove('hidden');q('#analysisEditorV076')?.classList.add('hidden');
  }
  function showEditor(){q('#analysisEmptyV076')?.classList.add('hidden');q('#analysisEditorV076')?.classList.remove('hidden')}

  function collectGuidanceDecisions(){
    const values={};
    qa('[data-guidance-value]').forEach(input=>{if(input.value!=='')values[input.dataset.guidanceValue]=Number(input.value)});
    return values;
  }

  async function loadTemplatePreview(templateId,decisions={}){
    if(!templateId||!ctl.selectedRevisionId||!guidanceClient()||ctl.templatePreviewLoading)return null;
    const previewKey=JSON.stringify([String(ctl.selectedRevisionId),String(templateId),canonical(decisions)]);
    const cached=ctl.templatePreviewCache.get(previewKey);
    if(cached){ctl.templatePreview=cached;if(!ctl.active&&routeActive())renderCreateForm();return cached}
    ctl.templatePreviewLoading=true;
    try{
      const preview=await guidanceClient().preview(apiCall,templateId,ctl.selectedRevisionId,decisions);
      ctl.templatePreviewCache.set(previewKey,preview);
      if(ctl.templatePreviewCache.size>24)ctl.templatePreviewCache.delete(ctl.templatePreviewCache.keys().next().value);
      if(String(ctl.createTemplateId)===String(templateId))ctl.templatePreview=preview;
      return preview;
    }catch(error){
      ctl.templatePreview={template:{id:templateId},error:error.message,common_decisions:[],recommendations:[],ready_to_create:false};
      notify(error.message,'ERROR',9000);
      return null;
    }finally{
      ctl.templatePreviewLoading=false;
      if(!ctl.active&&routeActive())renderCreateForm();
    }
  }

  function renderCreateForm(){
    ctl.activeId=null;ctl.active=null;ctl.inputCatalog=null;ctl.executionPlan=null;ctl.fullCheck=null;ctl.guidance=null;ctl.returnToCheck=null;contextStore()?.setAnalysis?.(null,{source:'analysis:create-mode'});renderContext();renderList();showEditor();
    const body=q('#analysisEditorBodyV076');if(!body)return;
    const record=ctl.revisionIndex.get(String(ctl.selectedRevisionId||''));
    if(!record){body.innerHTML=`<div class="analysis-empty-v076"><h3>${safe(text.noRevision)}</h3><button type="button" data-back-motor-v076>返回电机配置</button></div>`;q('[data-back-motor-v076]',body)?.addEventListener('click',goMotor);return}
    const recipes=(ctl.catalog?.recipes||[]);
    if(!ctl.createRecipeId||!recipes.some(row=>String(row.id)===String(ctl.createRecipeId)&&row.available))ctl.createRecipeId=recipes.find(row=>row.available)?.id||null;
    const templates=(ctl.templateCatalog?.templates||[]);
    if(!ctl.createTemplateId||!templates.some(row=>String(row.id)===String(ctl.createTemplateId)&&row.available))ctl.createTemplateId=templates.find(row=>row.available)?.id||null;

    if(ctl.hmiMode==='advanced'){
      body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">${safe(text.create)} · 高级模式</span><h3>${safe(record.design.name||record.design.id)} · ${safe(revisionLabel(record.revision.revision,'motor'))}</h3><p>直接选择底层 Analysis Recipe。适用于需要完整控制求解配方、实验参数和扩展字段的专家工作流。</p></div></header><div class="analysis-create-grid-v076"><div class="analysis-create-form-v076"><label>分析配置名称<input id="analysisCreateNameV076" value="${safe((record.design.name||'电机')+' - '+(recipeById(ctl.createRecipeId)?.label||'分析'))}"></label><div class="analysis-definition-card-v076"><span>电机对象</span><b>${safe(designLabel(record))}</b><small>方案 ${safe(record.design.id)}</small></div><button id="analysisConfirmCreateV076" type="button" class="primary" ${ctl.createRecipeId?'':'disabled'}>创建并继续</button><div id="analysisCreateStatusV076" class="analysis-inline-status-v076"></div></div><div><div class="section-head"><div><h3>Analysis Recipe</h3><p>${recipes.filter(row=>row.available).length} 个当前机型可用配方</p></div></div><div class="analysis-recipe-grid-v076">${recipes.map(row=>`<button type="button" class="analysis-recipe-v076 ${String(row.id)===String(ctl.createRecipeId)?'active':''} ${row.available?'':'unavailable'}" data-recipe-v076="${safe(row.id)}" ${row.available?'':'disabled'}><span class="chip">${safe(moduleLabels[row.module]||row.module)}</span><b>${safe(row.label||row.id)}</b><p>${safe(row.description||row.engineering_output||'')}</p><footer><span>${safe(row.solve_mode||'')}</span><span>${row.production_ready?'Production':'Candidate'}</span></footer></button>`).join('')}</div></div></div></section>`;
      qa('[data-recipe-v076]',body).forEach(button=>button.addEventListener('click',()=>{ctl.createRecipeId=button.dataset.recipeV076;renderCreateForm()}));
      q('#analysisConfirmCreateV076',body)?.addEventListener('click',createAnalysis);
      return;
    }

    const selected=templateById(ctl.createTemplateId);
    const preview=ctl.templatePreview&&String(ctl.templatePreview?.template?.id)===String(ctl.createTemplateId)?ctl.templatePreview:null;
    const decisions=preview?.common_decisions||[];
    const fixed=(preview?.recommendations||[]).filter(row=>!row.common_decision&&row.value!==null&&row.value!==undefined).slice(0,6);
    const domainDefaults=preview?.input_domain_defaults||[];
    const ready=Boolean(preview?.ready_to_create&&!preview?.error);
    const limit=ctl.templateCatalog?.policy?.common_mode_max_decisions??3;
    const nameDefault=`${record.design.name||'电机'} - ${selected?.short_label||selected?.label||'工程分析'}`;
    body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">${safe(text.create)} · 工程模板</span><h3>${safe(record.design.name||record.design.id)} · ${safe(revisionLabel(record.revision.revision,'motor'))}</h3><p>选择工程意图后，Studio 从当前 电机版本、模板和配方生成可追溯 推荐设置。常用模式最多只要求 ${safe(limit)} 个关键工程决策。</p></div></header>
      <div class="analysis-template-toolbar"><div><b>${tr('分析模板','Analysis template')}</b><span>${templates.filter(row=>row.available).length} 个当前机型可用</span></div><small>${tr('推荐值不会覆盖历史版本；创建时冻结为分析版本 1。','Recommendations never overwrite history; creation freezes analysis revision 1.')}</small></div>
      <div class="analysis-template-grid">${templates.map(row=>guidanceClient()?.templateCard(row,String(row.id)===String(ctl.createTemplateId))||'').join('')||'<div class="analysis-list-empty-v076">当前机型没有可用工程分析模板，请切换高级模式检查底层配方。</div>'}</div>
      <div class="analysis-guidance-preview">
        <div class="analysis-create-form-v076"><label>分析配置名称<input id="analysisCreateNameV076" value="${safe(nameDefault)}"></label><div class="analysis-definition-card-v076"><span>电机对象</span><b>${safe(designLabel(record))}</b><small>电机版本 是 推荐设置 的首要设计证据</small></div><button id="analysisConfirmCreateV076" type="button" class="primary" ${ready?'':'disabled'}>${ctl.templatePreviewLoading?'正在生成推荐…':tr('创建分析版本 1','Create analysis revision 1')}</button><div id="analysisCreateStatusV076" class="analysis-inline-status-v076">${preview?.error?safe(preview.error):preview&&!ready?'仍有关键工程决策需要确认。':''}</div></div>
        <div class="analysis-guidance-panel"><header><div><span class="chip">${safe(selected?.module||'')}</span><h4>${safe(selected?.label||'请选择分析模板')}</h4><p>${safe(selected?.intent||'模板会把工程目标映射到底层 Motor-CAD 配方。')}</p></div>${preview?`<span class="analysis-confidence ${ready?'high':'medium'}">${ready?'可创建':'待确认'}</span>`:''}</header>
          ${ctl.templatePreviewLoading?'<div class="analysis-list-empty-v076">正在根据当前 电机版本 生成推荐值与来源证据…</div>':preview?`<div class="analysis-guidance-decisions">${decisions.map(row=>guidanceClient()?.decisionControl(row)||'').join('')||'<p class="muted">该模板不需要额外关键决策。</p>'}</div>${fixed.length?`<div class="analysis-guidance-recs"><h5>自动配置</h5>${fixed.map(row=>guidanceClient()?.recommendationRow(row)||'').join('')}</div>`:''}${domainDefaults.length?`<div class="analysis-guidance-domain-defaults"><h5>创建时预填的物理输入</h5><p>这些值来自物理输入域默认值，创建后应结合真实材料与冷却边界确认。</p>${domainDefaults.map(row=>`<div><b>${safe(row.label||row.domain_id)}</b><span>${safe(row.field_count)} 个字段 · ${safe(row.confidence_label)}置信度</span><small>${safe(row.reason||'')}</small></div>`).join('')}</div>`:''}`:'<div class="analysis-list-empty-v076">选择模板后生成 推荐设置。</div>'}
        </div>
      </div></section>`;
    qa('[data-analysis-template]',body).forEach(button=>button.addEventListener('click',()=>{ctl.createTemplateId=button.dataset.analysisTemplate;ctl.templatePreview=null;renderCreateForm()}));
    qa('[data-guidance-value]',body).forEach(input=>input.addEventListener('change',()=>loadTemplatePreview(ctl.createTemplateId,collectGuidanceDecisions())));
    q('#analysisConfirmCreateV076',body)?.addEventListener('click',createAnalysis);
    if(ctl.createTemplateId&&!preview&&!ctl.templatePreviewLoading)loadTemplatePreview(ctl.createTemplateId).catch(()=>{});
  }

  async function createAnalysis(){
    const record=ctl.revisionIndex.get(String(ctl.selectedRevisionId||'')),status=q('#analysisCreateStatusV076'),button=q('#analysisConfirmCreateV076');if(!record)return;
    if(ctl.hmiMode==='common'){
      const template=templateById(ctl.createTemplateId);if(!template)return;
      const name=q('#analysisCreateNameV076')?.value.trim()||`${record.design.name||'Motor'} - ${template.short_label||template.label||template.id}`;
      const decisions=collectGuidanceDecisions();
      try{button.disabled=true;if(status)status.textContent=tr('正在冻结模板推荐并创建不可变分析版本 1…','Freezing recommendations and creating immutable analysis revision 1…');const result=await apiCall(`/api/projects/${encode(state.activeProjectId)}/analysis-definitions/from-template`,{method:'POST',body:JSON.stringify({design_revision_id:record.revision.id,template_id:template.id,name,decisions,notes:tr('由分析模板与推荐设置创建','Created from analysis template and recommendations')})});const created=result.analysis_definition;await fetchDefinitions();contextStore()?.setAnalysis?.(created,{motorRevision:record.revision,analysisRevisionId:created.revisions?.[0]?.id||null,source:'analysis:template-create'});notify(`已按 ${template.short_label||template.label} 创建分析配置`,'SUCCESS');return window.MCSRouter?.navigate?.(analysisPath(created.id,'definition'))}catch(error){button.disabled=false;if(status){status.textContent=error.message;status.classList.add('error')}notify(error.message,'ERROR',9000)}
      return;
    }
    const recipe=recipeById(ctl.createRecipeId);if(!recipe)return;
    const name=q('#analysisCreateNameV076')?.value.trim()||`${record.design.name||'Motor'} - ${recipe.label||recipe.id}`;
    try{button.disabled=true;if(status)status.textContent=tr('正在创建不可变分析版本 1…','Creating immutable analysis revision 1…');const created=await apiCall(`/api/projects/${encode(state.activeProjectId)}/analysis-definitions`,{method:'POST',body:JSON.stringify({design_revision_id:record.revision.id,name,module:recipe.module,recipe_id:recipe.id,load_cases:[{}],solver_settings:{native_screen_capture:{enabled:false,screen:'E-Magnetics;FEA'}},input_domains:{},requested_outputs:[...(recipe.required_outputs||[])],notes:tr('由高级分析配方创建','Created from advanced analysis recipe')})});await fetchDefinitions();contextStore()?.setAnalysis?.(created,{motorRevision:record.revision,analysisRevisionId:created.revisions?.[0]?.id||null,source:'analysis:create'});notify('已创建分析配置','SUCCESS');return window.MCSRouter?.navigate?.(analysisPath(created.id,'definition'))}catch(error){button.disabled=false;if(status){status.textContent=error.message;status.classList.add('error')}notify(error.message,'ERROR',9000)}
  }

  function guidanceOverviewHtml({actions=false}={}){
    const guidance=ctl.guidance;if(!guidance||guidance.error)return guidance?.error?`<div class="analysis-guidance-panel"><header><div><h4>分析建议</h4><p>${safe(guidance.error)}</p></div></header></div>`:'';
    const template=guidance.template,summary=guidance.summary||{},common=guidance.common_decisions||[],fixes=(guidance.auto_fix_actions||[]).filter(row=>row.changes||!row.can_apply);
    if(!template&&!common.length&&!fixes.length)return '';
    return `<div class="analysis-guidance-panel"><header><div><span class="chip">分析建议</span><h4>${safe(template?.label||'当前分析建议')}</h4><p>${safe(template?.intent||'根据当前 电机版本 与 分析版本 生成可追溯建议。')}</p></div><span class="analysis-confidence high">${safe(revisionLabel(guidance.analysis_revision??'-'))}</span></header><div class="analysis-guidance-summary"><div><span>关键决策已确认</span><b>${safe(summary.configured_common_decisions??0)}</b></div><div><span>可推荐</span><b>${safe(summary.recommended_common_decisions??0)}</b></div><div><span>待人工确认</span><b>${safe(summary.needs_input_common_decisions??0)}</b></div><div><span>可自动修复</span><b>${safe(summary.applicable_auto_fixes??0)}</b></div></div>${common.length?`<div class="analysis-guidance-recs">${common.map(row=>guidanceClient()?.recommendationRow(row)||'').join('')}</div>`:''}${actions&&fixes.length?`<div class="analysis-guidance-actions"><h5>可执行修复</h5>${fixes.map(row=>guidanceClient()?.actionCard(row)||'').join('')}</div>`:''}</div>`;
  }

  function bindAutoFixActions(root){
    qa('[data-analysis-autofix]',root).forEach(button=>button.addEventListener('click',()=>applyAutoFix(button.dataset.analysisAutofix)));
  }

  async function applyAutoFix(actionId){
    if(!ctl.active||!ctl.guidance||!guidanceClient())return;
    const action=(ctl.guidance.auto_fix_actions||[]).find(row=>String(row.id)===String(actionId));if(!action||!action.can_apply)return;
    const paths=(action.touched_paths||[]).join('\n');
    const confirmed=window.StudioDialog?await StudioDialog.confirm({key:`analysis-autofix:${ctl.active.id}:${action.id}`,title:action.label,html:`<p>${safe(action.reason)}</p>${paths?`<pre>${safe(paths)}</pre>`:''}<p>确认后会生成新的 分析版本。</p>`,confirmText:'应用并生成新版本'}):false;if(!confirmed)return;
    const expected=ctl.guidance.analysis_revision_id||activeAnalysisRevision()?.id;
    try{
      const result=await guidanceClient().applyAutoFix(apiCall,ctl.active.id,action.id,expected);
      ctl.active=result.analysis_definition;ctl.definitions=ctl.definitions.map(row=>row.id===ctl.active.id?ctl.active:row);
      ctl.inputCatalog=await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/input-domains`);ctl.executionPlan=null;ctl.fullCheck=null;
      await refreshGuidance();
      contextStore()?.setAnalysis?.(ctl.active,{analysisRevisionId:ctl.active.revisions?.[0]?.id||null,motorRevision:ctl.active.design_revision_id,source:'analysis:auto-fix'});
      renderAll();
      notify(result.idempotent_replay?'已恢复先前完成的 自动修复':'自动修复 已生成新的 分析版本','SUCCESS',7500);
    }catch(error){
      if(error?.status===409||String(error.message||'').includes('ANALYSIS_REVISION_STALE'))await hydrateActive(ctl.active.id);
      notify(error.message,'ERROR',9000);
    }
  }

  function renderDefinition(){
    const body=q('#analysisEditorBodyV076'),record=activeRevisionRecord(),latest=activeAnalysisRevision(),sameDesign=(record?.design?.revisions||[]).slice().sort((a,b)=>Number(b.revision||0)-Number(a.revision||0));if(!body)return;
    body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">1 \u00b7 ${safe(stepLabels.definition)}</span><h3>${safe(ctl.active.name)}</h3><p>\u5206\u6790\u7c7b\u578b\u4e0e\u914d\u65b9\u4f5c\u4e3a\u5206\u6790\u8eab\u4efd\u4fdd\u6301\u7a33\u5b9a\uff1b\u53ef\u4ee5\u5728\u540c\u4e00\u65b9\u6848\u5185\u5207\u6362\u7535\u673a\u7248\u672c\u3002</p></div><div class="actions"><button type="button" data-go-motor-v076>\u67e5\u770b\u7535\u673a\u914d\u7f6e</button><button type="button" class="primary" data-next-v076="operating">\u7ee7\u7eed\u914d\u7f6e \u2192</button></div></header><div class="analysis-definition-grid-v076"><div class="analysis-definition-card-v076"><span>项目</span><b>${safe(ctl.project?.name||state.activeProjectId)}</b><small>${safe(state.activeProjectId)}</small></div><div class="analysis-definition-card-v076"><span>方案</span><b>${safe(record?.design?.name||'-')}</b><small>${safe(record?.design?.id||'-')}</small></div><div class="analysis-definition-card-v076"><span>电机版本</span><b>${safe(revisionLabel(record?.revision?.revision??'-','motor'))}</b><small>${safe(record?.revision?.id||'-')} \u00b7 ${safe(record?.revision?.content_hash||'')}</small></div><div class="analysis-definition-card-v076"><span>分析版本</span><b>${safe(revisionLabel(latest?.revision??'-'))}</b><small>${safe(latest?.id||'-')} \u00b7 ${safe(latest?.content_hash||'')}</small></div><div class="analysis-definition-card-v076"><span>\u5206\u6790\u6a21\u5757</span><b>${safe(moduleLabels[ctl.active.module]||ctl.active.module)}</b><small>${safe(ctl.active.module)}</small></div><div class="analysis-definition-card-v076"><span>\u8ba1\u7b97\u914d\u65b9</span><b>${safe(recipeById(ctl.active.recipe_id)?.label||ctl.active.recipe_id)}</b><small>${safe(ctl.active.recipe_id)}</small></div></div><div class="subpanel"><div class="section-head"><div><h3>\u5207\u6362\u540c\u65b9\u6848\u7684\u7535\u673a\u7248\u672c</h3><p>\u5207\u6362\u540e\u5206\u6790\u5b9a\u4e49\u4fdd\u6301\u4e0d\u53d8\uff0c\u6267\u884c\u8ba1\u5212\u4f1a\u7ed1\u5b9a\u65b0\u7684 电机版本\u3002\u8de8\u65b9\u6848\u8bf7\u65b0\u5efa\u5206\u6790\u914d\u7f6e\u3002</p></div></div><div class="form-grid"><label>电机版本<select id="analysisDefinitionRevisionV076">${sameDesign.map(rev=>`<option value="${safe(rev.id)}" ${String(rev.id)===String(ctl.active.design_revision_id)?'selected':''}>${safe(revisionLabel(rev.revision,'motor'))} \u00b7 ${safe(rev.id)}</option>`).join('')}</select></label><div class="actions"><button id="analysisApplyRevisionV076" type="button">\u66f4\u65b0\u5f15\u7528</button></div></div><div id="analysisDefinitionStatusV076" class="analysis-inline-status-v076"></div></div></section>`;
    const definitionSubpanel=q('.subpanel',body);if(definitionSubpanel){const guidanceHtml=guidanceOverviewHtml();if(guidanceHtml)definitionSubpanel.insertAdjacentHTML('beforebegin',guidanceHtml)}
    q('[data-go-motor-v076]',body)?.addEventListener('click',goMotor);q('[data-next-v076]',body)?.addEventListener('click',()=>setStep('operating', {replace:false}));q('#analysisApplyRevisionV076',body)?.addEventListener('click',applyAnalysisRevisionReference);
  }

  async function applyAnalysisRevisionReference(){
    const revisionId=q('#analysisDefinitionRevisionV076')?.value,status=q('#analysisDefinitionStatusV076'),button=q('#analysisApplyRevisionV076');if(!revisionId||revisionId===ctl.active?.design_revision_id)return;
    try{button.disabled=true;if(status)status.textContent='\u6b63\u5728\u66f4\u65b0\u7535\u673a Revision \u5f15\u7528\u2026';await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/design-revision`,{method:'PUT',body:JSON.stringify({design_revision_id:revisionId})});await fetchDefinitions();await hydrateActive(ctl.active.id);notify('\u5206\u6790\u5df2\u5207\u6362\u5230\u65b0\u7684\u7535\u673a Revision','SUCCESS')}catch(error){button.disabled=false;if(status){status.textContent=error.message;status.classList.add('error')}notify(error.message,'ERROR',9000)}
  }

  function operatingFields(){
    const recipe=recipeById(ctl.active?.recipe_id),found=[];
    for(const section of recipe?.sections||[])for(const field of section.fields||[]){const id=field.id||field.parameter_id;if(id&&['load_case','operating_point','scenario'].includes(field.target||section.target))found.push({id,label:field.label||fieldLabel(id),unit:field.unit||''})}
    const dedupe=new Map([...commonOperatingFields(),...found].map(row=>[row.id,row]));return [...dedupe.values()].slice(0,10);
  }

  function renderOperating(){
    const body=q('#analysisEditorBodyV076'),cases=activeDefinition().load_cases||[{}],fields=operatingFields();if(!body)return;
    body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">2 \u00b7 ${safe(stepLabels.operating)}</span><h3>\u8fd0\u884c\u5de5\u51b5</h3><p>\u6bcf\u4e00\u884c\u5bf9\u5e94\u4e00\u4e2a\u8ba1\u7b97\u5de5\u51b5\u3002\u4fdd\u5b58\u4f1a\u751f\u6210\u65b0\u7684 分析版本\uff0c\u4e0d\u8986\u76d6\u5386\u53f2\u8bbe\u7f6e\u3002</p></div><div class="actions"><button type="button" data-add-case-v076>\uff0b \u6dfb\u52a0\u5de5\u51b5</button><button type="button" class="primary" data-save-cases-v076>\u4fdd\u5b58\u5de5\u51b5</button></div></header><div class="analysis-op-wrap-v076"><table class="analysis-op-table-v076"><thead><tr><th>#</th>${fields.map(field=>`<th>${safe(field.label)}${field.unit?` / ${safe(unitLabel(field.unit))}`:''}</th>`).join('')}<th></th></tr></thead><tbody id="analysisCasesBodyV076">${cases.map((row,index)=>caseRowHtml(row,index,fields)).join('')}</tbody></table></div><div class="analysis-op-actions-v076"><small>${cases.length} \u4e2a\u5de5\u51b5 \u00b7 \u4e0a\u9650 5000</small><div><button type="button" data-next-v076="inputs">\u4e0b\u4e00\u6b65\uff1a\u7269\u7406\u8f93\u5165 \u2192</button></div></div><div id="analysisOperatingStatusV076" class="analysis-inline-status-v076"></div></section>`;
    q('[data-add-case-v076]',body)?.addEventListener('click',()=>{const tbody=q('#analysisCasesBodyV076');if(!tbody)return;const index=qa('tr',tbody).length;tbody.insertAdjacentHTML('beforeend',caseRowHtml({},index,fields));bindCaseRemove(tbody)});bindCaseRemove(body);q('[data-save-cases-v076]',body)?.addEventListener('click',saveOperatingCases);q('[data-next-v076]',body)?.addEventListener('click',()=>setStep('inputs',{replace:false}));
  }
  function caseRowHtml(row,index,fields){return `<tr data-case-v076><td>${index+1}</td>${fields.map(field=>`<td><input data-case-field-v076="${safe(field.id)}" type="number" step="any" value="${row[field.id]??''}"></td>`).join('')}<td><button type="button" data-remove-case-v076 title="Remove">\u00d7</button></td></tr>`}
  function bindCaseRemove(root){qa('[data-remove-case-v076]',root).forEach(button=>button.onclick=()=>{const rows=qa('[data-case-v076]',q('#analysisCasesBodyV076'));if(rows.length<=1)return notify('\u81f3\u5c11\u4fdd\u7559\u4e00\u4e2a\u5de5\u51b5','WARNING');button.closest('tr')?.remove();qa('[data-case-v076]',q('#analysisCasesBodyV076')).forEach((row,index)=>{const cell=row.querySelector('td');if(cell)cell.textContent=String(index+1)})})}
  function collectCases(){return qa('[data-case-v076]').map(row=>{const obj={};qa('[data-case-field-v076]',row).forEach(input=>{if(input.value!=='')obj[input.dataset.caseFieldV076]=Number(input.value)});return obj})}
  async function saveOperatingCases({auto=false}={}){const status=q('#analysisOperatingStatusV076'),analysisId=ctl.active?.id;if(!analysisId)return false;const button=q('[data-save-cases-v076]'),op=operationProgress({id:`analysis-save-cases-${analysisId}`,label:auto?'自动保存运行工况':'保存运行工况',detail:'正在创建新的分析版本',percent:8,button});return actionLock(`analysis-operating-save:${analysisId}`,async()=>{try{if(status)status.textContent='正在保存工况并生成新的分析版本…';op.update({percent:28,stage:'固化工况',detail:`保存 ${collectCases().length} 个运行工况`});await saveAnalysisRevision({load_cases:collectCases(),notes:'Updated operating points from unified analysis configuration'});op.update({percent:86,stage:'刷新上下文',detail:'重新读取物理输入与工程建议'});if(status){status.textContent=text.saved;status.className='analysis-inline-status-v076 success'}op.done(text.saved);if(!auto)notify(text.saved,'SUCCESS');return true}catch(error){op.fail(error.message);if(status){status.textContent=error.message;status.className='analysis-inline-status-v076 error'}notify(error.message,'ERROR',9000);return false}})}

  function dependencySatisfied(field,values={}){
    const rule=field?.enabled_when;if(!rule?.field)return true;
    const actual=values?.[rule.field],expected=rule.equals;
    return expected===undefined?Boolean(actual):actual===expected;
  }
  function currentDomain(){return (ctl.inputCatalog?.domains||[]).find(row=>row.id===ctl.domainId)||null}
  function inputControl(field,value){
    const domainValues=currentDomain()?.values||{},id=safe(field.id),label=safe(field.label||field.name||field.id),description=safe(field.description||field.help||''),type=field.type||'number',unit=field.unit?` / ${safe(unitLabel(field.unit))}`:'';
    const rule=field.enabled_when||{},enabled=dependencySatisfied(field,domainValues),dependency=rule.field?` data-enabled-when-field-v089g4="${safe(rule.field)}" data-enabled-when-value-v089g4="${safe(String(rule.equals))}"`:'';
    const wrapper=`class="analysis-input-field-v089g4${enabled?'':' inactive'}"${dependency}`,disabled=enabled?'':' disabled aria-disabled="true"',help=description?`<small>${description}</small>`:'',inactive=rule.field?`<small class="analysis-input-dependency-v089g4" data-dependency-note-v089g4>${enabled?'':tr('启用辐射换热后可编辑','Editable after radiation heat transfer is enabled')}</small>`:'';
    if(type==='boolean')return `<label ${wrapper}>${label}${unit}<select data-domain-field-v076="${id}" data-field-type-v076="boolean"${disabled}><option value="true" ${normalizeBool(value)?'selected':''}>${tr('启用','Enabled')}</option><option value="false" ${normalizeBool(value)?'':'selected'}>${tr('未启用','Disabled')}</option></select>${help}${inactive}</label>`;
    const options=field.options||field.allowed||field.values;if(Array.isArray(options)&&options.length)return `<label ${wrapper}>${label}${unit}<select data-domain-field-v076="${id}" data-field-type-v076="enum"${disabled}>${options.map(option=>{const optionValue=typeof option==='object'?(option.id??option.value):option,optionLabel=typeof option==='object'?(option.label??optionValue):option;return `<option value="${safe(optionValue)}" ${String(optionValue)===String(value)?'selected':''}>${safe(optionLabel)}</option>`}).join('')}</select>${help}${inactive}</label>`;
    const numeric=['number','float','integer'].includes(type)||typeof value==='number';return `<label ${wrapper}>${label}${unit}<input data-domain-field-v076="${id}" data-field-type-v076="${safe(type)}" type="${numeric?'number':'text'}" ${numeric?'step="any"':''} value="${safe(value??'')}"${disabled}>${help}${inactive}</label>`;
  }
  function syncConditionalInputs(root=document){
    const domain=currentDomain();if(!domain)return;
    const values={};qa('[data-domain-field-v076]',root).forEach(input=>{values[input.dataset.domainFieldV076]=input.dataset.fieldTypeV076==='boolean'?input.value==='true':input.value});
    (domain.fields||[]).forEach(field=>{if(!field.enabled_when?.field)return;const control=q(`[data-domain-field-v076="${CSS.escape(String(field.id))}"]`,root),wrapper=control?.closest?.('[data-enabled-when-field-v089g4]');if(!control||!wrapper)return;const enabled=dependencySatisfied(field,values);control.disabled=!enabled;control.setAttribute('aria-disabled',enabled?'false':'true');wrapper.classList.toggle('inactive',!enabled);const note=q('[data-dependency-note-v089g4]',wrapper);if(note)note.textContent=enabled?'':tr('启用辐射换热后可编辑','Editable after radiation heat transfer is enabled')});
  }

  function syncHmiModeButtons(){
    const common=q('#analysisCommonModeV081A'),advanced=q('#analysisAdvancedModeV081A');
    common?.classList.toggle('active',ctl.hmiMode==='common');advanced?.classList.toggle('active',ctl.hmiMode==='advanced');
  }
  async function setHmiMode(mode){
    const next=mode==='advanced'?'advanced':'common';if(next===ctl.hmiMode)return true;if(ctl.active&&['inputs','solver'].includes(ctl.step)&&!(await flushCurrentAnalysisEditor({reason:'hmi-mode-change',notifyOnSave:true})))return false;
    ctl.hmiMode=next;localStorage.setItem('mcs-analysis-hmi-mode',ctl.hmiMode);localStorage.removeItem('mcs-analysis-hmi-mode-v081a');syncHmiModeButtons();if(!ctl.active){renderCreateForm();return true}if(['definition','inputs','solver','check'].includes(ctl.step))renderEditorBody();return true;
  }

  function renderInputs(){
    const body=q('#analysisEditorBodyV076'),allDomains=ctl.inputCatalog?.domains||[];if(!body)return;
    const domains=ctl.hmiMode==='common'?allDomains.filter(row=>row.required||row.configured):allDomains;
    const visible=domains.length?domains:allDomains.slice(0,1);
    if(!ctl.domainId||!visible.some(row=>row.id===ctl.domainId))ctl.domainId=visible[0]?.id||null;const domain=allDomains.find(row=>row.id===ctl.domainId)||null;
    const optionalHidden=Math.max(0,allDomains.length-visible.length);
    body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">3 · ${safe(stepLabels.inputs)}</span><h3>物理输入</h3><p>优先完成当前分析真正需要的物理输入；可选模型与专家边界条件放在高级模式。</p></div><div class="actions"><button type="button" data-refresh-input-v076>重新读取</button><button type="button" data-next-v076="solver">下一步：求解与输出 →</button></div></header>${ctl.hmiMode==='common'?`<div class="analysis-common-note-v081a"><b>常用模式</b> · 当前只显示必填或已经配置的输入。${optionalHidden?` 另有 ${optionalHidden} 个可选输入可在“高级”模式查看。`:''}</div>`:''}${visible.length?`<div class="analysis-input-layout-v076"><nav class="analysis-domain-nav-v076">${visible.map(row=>`<button type="button" data-domain-v076="${safe(row.id)}" class="${row.id===ctl.domainId?'active':''}"><span>${safe(row.label||row.id)}</span><em class="${row.configured?'saved':row.required?'required':''}">${row.configured?'✓':row.required?'必填':'可选'}</em></button>`).join('')}${optionalHidden?`<button type="button" data-show-advanced-input-v081a><span>更多物理输入</span><em>${optionalHidden}</em></button>`:''}</nav><div id="analysisDomainEditorV076" class="analysis-domain-editor-v076">${domain?`<header><h4>${safe(domain.label||domain.id)} ${domain.required?'<span class="chip warning">必填</span>':''}</h4><p>${safe(domain.purpose||domain.description||'')}</p></header><div class="analysis-input-fields-v076">${(domain.fields||[]).map(field=>inputControl(field,domain.values?.[field.id])).join('')||'<p class="muted">该输入模块没有可编辑字段。</p>'}</div><div class="analysis-domain-actions-v076"><button id="analysisSaveDomainV076" type="button" class="primary">保存${safe(domain.label||domain.id)}</button></div><div id="analysisDomainStatusV076" class="analysis-inline-status-v076"></div>`:''}</div></div>`:'<div class="analysis-list-empty-v076">当前分析没有已注册的物理输入模块。</div>'}</section>`;
    qa('[data-domain-v076]',body).forEach(button=>button.addEventListener('click',async()=>{const next=button.dataset.domainV076;if(next===ctl.domainId)return;if(!(await flushCurrentAnalysisEditor({reason:'input-domain-switch',notifyOnSave:true})))return;ctl.domainId=next;renderInputs()}));q('#analysisSaveDomainV076',body)?.addEventListener('click',()=>saveInputDomain());q('[data-refresh-input-v076]',body)?.addEventListener('click',refreshInputs);q('[data-next-v076]',body)?.addEventListener('click',()=>setStep('solver',{replace:false}));q('[data-show-advanced-input-v081a]',body)?.addEventListener('click',()=>setHmiMode('advanced'));
  }
  async function refreshInputs(){const button=q('[data-refresh-input-v076]'),op=operationProgress({id:`analysis-refresh-inputs-${ctl.active?.id||'none'}`,label:'重新读取物理输入',detail:'同步当前分析版本的输入域',percent:10,button});try{if(!(await flushCurrentAnalysisEditor({reason:'input-refresh',notifyOnSave:true}))){op.fail('当前编辑内容未能保存');return false}op.update({percent:52,stage:'读取输入域',detail:'加载配置状态与字段定义'});const bundle=workspaceClient()?await workspaceClient().editor(ctl.active.id):null;if(bundle?.analysis_definition)ctl.active=bundle.analysis_definition;ctl.inputCatalog=bundle?.input_catalog||await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/input-domains`);renderInputs();renderSummary();op.done('物理输入已同步');return true}catch(error){op.fail(error.message);throw error}}
  async function saveInputDomain({auto=false}={}){
    const collected=collectDomainValues(),status=q('#analysisDomainStatusV076'),button=q('#analysisSaveDomainV076');if(!collected)return true;const {domain,values}=collected,op=operationProgress({id:`analysis-save-domain-${ctl.active.id}-${domain.id}`,label:`保存${domain.label||domain.id}`,detail:'正在写入物理输入并生成分析版本',percent:8,button});
    return actionLock(`analysis-input-save:${ctl.active.id}:${domain.id}`,async()=>{try{if(status)status.textContent='正在保存并刷新输入状态…';op.update({percent:32,stage:'保存物理输入',detail:'校验字段并生成新的分析版本'});const payload={values,notes:tr(`从统一分析配置更新${domain.label||domain.id}`,`Updated ${domain.label||domain.id} from unified analysis configuration`)};const saved=workspaceClient()?await workspaceClient().updateInputDomain(ctl.active.id,domain.id,payload):await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/input-domains/${encode(domain.id)}`,{method:'PUT',body:JSON.stringify(payload)});ctl.active=saved.analysis_definition;ctl.inputCatalog=saved.catalog;ctl.definitions=ctl.definitions.map(row=>row.id===ctl.active.id?ctl.active:row);contextStore()?.setAnalysis?.(ctl.active,{analysisRevisionId:ctl.active.revisions?.[0]?.id||null,motorRevision:ctl.active.design_revision_id,source:'analysis:input-save'});ctl.executionPlan=null;ctl.fullCheck=null;resetSubmissionKey();op.update({percent:82,stage:'界面就绪',detail:'工程建议将在后台刷新'});renderInputs();renderList();renderSummary();scheduleGuidanceRefresh();op.done(text.saved);if(!auto)notify(text.saved,'SUCCESS');return true}catch(error){op.fail(error.message);if(status){status.textContent=error.message;status.className='analysis-inline-status-v076 error'}notify(error.message,'ERROR',9000);return false}})
  }

  function allOutputIds(){
    const recipe=recipeById(ctl.active?.recipe_id)||{},required=recipe.required_outputs||[],optional=recipe.optional_outputs||[],current=activeDefinition().requested_outputs||[];const known=Object.keys(state.registry?.outputs||{});const combined=[...required,...optional,...current,...known.filter(id=>required.includes(id)||optional.includes(id))];return [...new Set(combined)].filter(Boolean)
  }
  function renderSolver(){
    const body=q('#analysisEditorBodyV076'),definition=activeDefinition(),recipe=recipeById(ctl.active?.recipe_id)||{},required=new Set(recipe.required_outputs||[]),selected=new Set(definition.requested_outputs||[]),allOutputs=allOutputIds(),solver={...(definition.solver_settings||{})};if(!body)return;
    const outputs=ctl.hmiMode==='common'?allOutputs.filter(id=>required.has(id)||selected.has(id)):allOutputs;const hidden=Math.max(0,allOutputs.length-outputs.length);
    body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">4 · ${safe(stepLabels.solver)}</span><h3>求解与输出</h3><p>${ctl.hmiMode==='common'?'保留配方默认求解设置，只选择工程上需要的结果。':'查看并编辑完整 Solver JSON 与全部可选输出。'}</p></div><div class="actions"><button type="button" class="primary" data-save-solver-v076>保存求解与输出</button><button type="button" data-next-v076="check">检查并计算 →</button></div></header>${ctl.hmiMode==='common'?'<div class="analysis-common-note-v081a"><b>常用模式</b> · 当前求解器高级参数沿用已保存配置，不会因切换界面被重置。</div>':''}<div class="analysis-solver-grid-v076"><div class="analysis-solver-card-v076"><h4>请求输出</h4><p>配方必需输出已锁定；当前已选择的可选输出会继续保留。</p><div class="analysis-output-grid-v076">${outputs.map(id=>{const meta=outputMeta(id),must=required.has(id),checked=must||selected.has(id);return `<label><input type="checkbox" data-output-v076="${safe(id)}" ${checked?'checked':''} ${must?'disabled':''}><span><b>${safe(meta.label)}${meta.unit?` / ${safe(unitLabel(meta.unit))}`:''}</b><small>${safe(id)}${must?' · 必需':''}</small></span></label>`}).join('')||'<p class="muted">当前配方没有已注册输出。</p>'}</div>${hidden?`<button type="button" data-show-advanced-output-v081a>查看另外 ${hidden} 个可选输出</button>`:''}</div><div class="analysis-solver-card-v076"><h4>求解器设置</h4><label class="check-row"><input id="analysisNativeCaptureV076" type="checkbox" ${solver.native_screen_capture?.enabled===true?'checked':''}>保留 Motor-CAD 原生屏幕截图（可选，可能增加等待时间）</label>${ctl.hmiMode==='advanced'?`<label>Solver Settings JSON<textarea id="analysisSolverJsonV076" class="analysis-solver-json-v076" data-i18n-skip translate="no" spellcheck="false">${safe(JSON.stringify(solver,null,2))}</textarea></label>`:`<div class="analysis-common-note-v081a">当前使用已保存的 Solver 设置。需要调整网格、迭代器或插件扩展参数时切换到“高级”。</div>`}</div></div><div id="analysisSolverStatusV076" class="analysis-inline-status-v076"></div></section>`;
    q('[data-save-solver-v076]',body)?.addEventListener('click',saveSolver);q('[data-next-v076]',body)?.addEventListener('click',()=>setStep('check',{replace:false}));q('[data-show-advanced-output-v081a]',body)?.addEventListener('click',()=>setHmiMode('advanced'));
  }
  async function saveSolver({auto=false}={}){
    const status=q('#analysisSolverStatusV076'),button=q('[data-save-solver-v076]'),op=operationProgress({id:`analysis-save-solver-${ctl.active?.id||'none'}`,label:auto?'自动保存求解设置':'保存求解与输出',detail:'校验 Solver 设置与结果清单',percent:7,button});try{const draft=collectSolverDraft();if(status)status.textContent='正在保存求解设置与请求输出…';op.update({percent:28,stage:'冻结求解设置',detail:`准备 ${draft.requested_outputs.length} 项结果输出`});await saveAnalysisRevision({...draft,notes:'Updated solver settings and outputs from unified analysis configuration'});op.update({percent:86,stage:'刷新执行状态',detail:'同步新的分析版本与输入摘要'});if(status){status.textContent=text.saved;status.className='analysis-inline-status-v076 success'}op.done(text.saved);if(!auto)notify(text.saved,'SUCCESS');return true}catch(error){const message=error instanceof SyntaxError?'Solver Settings JSON 格式无效':error.message;op.fail(message);if(status){status.textContent=message;status.className='analysis-inline-status-v076 error'}notify(status?.textContent||error.message,'ERROR',9000);return false}}


  async function loadExecutionPlan({render=true,progressOp=null}={}){
    if(!ctl.active)return null;const own=!progressOp,op=progressOp||operationProgress({id:`analysis-plan-${ctl.active.id}`,label:'刷新执行计划',detail:'冻结当前 Design / Analysis Revision',percent:12,button:q('#analysisRefreshPlanV076')||q('#analysisInitialPlanV076')});try{const previousHash=ctl.executionPlan?.execution_plan_hash||null,quality=q('#analysisQualityV076')?.value||ctl.qualityProfile||'standard',reuse=q('#analysisReuseV076')?q('#analysisReuseV076').checked:ctl.reuseCache;ctl.qualityProfile=quality;ctl.reuseCache=Boolean(reuse);op.update({percent:42,stage:'生成执行合同',detail:'检查工况、物理输入与运行环境'});ctl.executionPlan=await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/execution-plan?quality_profile=${encode(quality)}&reuse_cache=${reuse?'true':'false'}`);if(previousHash&&previousHash!==ctl.executionPlan?.execution_plan_hash)resetSubmissionKey();contextStore()?.setAnalysis?.(ctl.active,{analysisRevisionId:ctl.executionPlan.analysis_revision?.id||activeAnalysisRevision()?.id||null,motorRevision:ctl.executionPlan.design_revision?.id||ctl.active.design_revision_id,source:'analysis:execution-plan'});op.update({percent:90,stage:'执行计划就绪',detail:ctl.executionPlan.can_submit?'基础检查已通过':'存在需要处理的阻断项'});if(render){renderCheck();renderSummary()}if(own)op.done('执行计划已刷新');return ctl.executionPlan}catch(error){if(own)op.fail(error.message);throw error}
  }
  function dedupeIssues(rows){const seen=new Set();return (rows||[]).filter(row=>{const key=`${row.code||''}|${row.severity||''}|${row.message||row.reason||''}`;if(seen.has(key))return false;seen.add(key);return true})}
  function gateCard(label,ok,detail,warn=false,pending=false){
    const cls=pending?'pending':statusClass(ok,warn),text=pending?tr('待检查','Pending'):ok?tr('已通过','Passed'):warn?tr('需关注','Attention'):tr('未通过','Failed');
    return `<div class="analysis-check-card-v076 ${cls}"><span>${safe(label)}</span><b>${safe(text)}</b><small>${safe(detail||'-')}</small></div>`
  }
  function blockingIssue(row){return ['BLOCKING','ERROR','FAILED','FAIL'].includes(String(row?.severity||row?.status||'').toUpperCase())}
  function issueDestination(row={}){
    if(row.target)return row.target;
    const haystack=`${row.code||''} ${row.path||''} ${row.field||''} ${row.message||row.reason||''}`.toLowerCase();
    if(/runtime|motor[- ]?cad|license|worker|installation|executable|环境|许可证|安装|运行时/.test(haystack))return 'runtime';
    if(/geometry|winding|material|design_revision|motor_revision|几何|绕组|材料|电机版本/.test(haystack))return 'motor';
    if(/speed|current|voltage|load[_ -]?case|operating|转速|电流|电压|工况/.test(haystack))return 'operating';
    if(/solver|output|mesh|iteration|time[_ -]?step|求解|输出|网格|迭代|时间步/.test(haystack))return 'solver';
    return 'inputs';
  }
  function issueActionLabel(target){return ({operating:tr('检查工况','Review operating points'),inputs:tr('检查物理输入','Review physical inputs'),solver:tr('检查求解与输出','Review solver and outputs'),runtime:tr('打开运行环境','Open runtime setup'),motor:tr('返回电机配置','Return to motor configuration'),native:tr('重新运行计算就绪检查','Run full check again')})[target]||tr('查看处理位置','Open resolution step')}
  async function openIssueTarget(target,reason=''){
    if(target==='native')return runFullCheck();
    if(target==='runtime')return window.MCSRouter?.navigate?.('/app/runtime',{source:'analysis:explicit-runtime-fix'});
    if(target==='motor')return goMotor();
    const next=steps.includes(target)?target:'inputs';
    ctl.returnToCheck={target:next,reason:String(reason||tr('从计算就绪检查进入此步骤处理阻断项。','Opened from the calculation check to resolve a blocker.'))};
    return setStep(next,{replace:false,preserveReturn:true});
  }
  function renderReturnToCheckBanner(){
    const context=ctl.returnToCheck,body=q('#analysisEditorBodyV076');if(!context||!body||ctl.step==='check')return;
    const section=q('.analysis-editor-section-v076',body);if(!section)return;
    const banner=document.createElement('div');banner.className='analysis-return-check-v090';banner.innerHTML=`<div><b>${tr('正在处理计算就绪检查项','Resolving a calculation-check item')}</b><small>${safe(context.reason||'')}</small></div><button type="button" data-return-analysis-check-v090>${tr('返回“检查并计算”','Return to Check and calculate')} →</button>`;
    const header=q(':scope > header',section);if(header)header.insertAdjacentElement('afterend',banner);else section.prepend(banner);
    q('[data-return-analysis-check-v090]',banner)?.addEventListener('click',()=>setStep('check',{replace:false}));
  }
  function flowStep(number,label,detail,state){return `<li class="${safe(state)}"><i>${number}</i><span><b>${safe(label)}</b><small>${safe(detail)}</small></span></li>`}
  function renderCheck(){
    const body=q('#analysisEditorBodyV076');if(!body)return;ctl.returnToCheck=null;
    const plan=ctl.executionPlan,studio=plan?.studio_precheck||{},task=plan?.task_validation||{},runtime=plan?.runtime_readiness||{},full=ctl.fullCheck;
    const fullRunning=Boolean(full?.running),fullPercent=Number.isFinite(full?.progressPercent)?Math.max(0,Math.min(100,Number(full.progressPercent))):null;
    const qualityOptions=Object.entries(state.registry?.quality_profiles||{}).map(([id,row])=>`<option value="${safe(id)}" ${id===ctl.qualityProfile?'selected':''}>${safe(row.label||id)}</option>`).join('')||`<option value="standard" ${ctl.qualityProfile==='standard'?'selected':''}>${tr('标准','Standard')}</option>`;
    const baseIssues=dedupeIssues([...(studio.issues||[]),...(task.issues||[])]);
    const missing=plan?.missing_required_input_domains||[];
    const actionable=[];
    missing.forEach(domain=>actionable.push({severity:'BLOCKING',code:'MISSING_INPUT_DOMAIN',message:tr(`缺少必需物理输入：${domain}`,`Required physical input is missing: ${domain}`),detail:String(domain),target:'inputs'}));
    if(plan&&!runtime.ok)actionable.push({severity:'BLOCKING',code:'RUNTIME_NOT_READY',message:runtime.message||runtime.reason||tr('Motor-CAD 运行环境尚未就绪','The Motor-CAD runtime is not ready'),detail:tr('检查安装路径、许可证、Worker 与服务状态。','Check the executable path, license, worker, and service status.'),target:'runtime'});
    baseIssues.forEach(row=>actionable.push({...row,target:issueDestination(row)}));
    if(full?.result&&!full?.valid&&!fullRunning){const message=full?.result?.motorcad?.message||full?.result?.message||full?.message; if(message)actionable.push({severity:'BLOCKING',code:'NATIVE_CHECK_FAILED',message,detail:tr('修正配置或运行环境后重新执行完整检查。','Correct the configuration or runtime, then run the full check again.'),target:'native'})}
    const issues=dedupeIssues(actionable);
    const hardIssues=issues.filter(blockingIssue);
    const planReady=Boolean(plan?.execution_plan_hash);
    const configReady=Boolean(plan?.can_submit&&studio.valid&&task.valid&&!missing.length&&runtime.ok);
    const ready=Boolean(configReady&&full?.valid&&!fullRunning);
    const needsNative=Boolean(configReady&&!full?.valid&&!fullRunning);
    const nativeDetail=fullRunning?(full?.message||tr('Motor-CAD 原生计算链路检查正在执行…','The native Motor-CAD calculation check is running…')):(full?.valid?tr('当前版本的计算就绪证据已固化','Calculation-readiness evidence was recorded for the current revision'):full?.result?.motorcad?.message||full?.result?.message||tr('尚未确认；系统优先复用设计资格，必要时才启动 Motor-CAD 刷新原生证据。','Not confirmed yet. Design qualification is reused first; Motor-CAD starts only when native evidence must be refreshed.'));
    const flowHtml=[
      flowStep(1,tr('执行计划','Execution plan'),planReady?tr('已冻结当前电机与分析版本','Current motor and analysis revisions are frozen'):tr('等待加载当前执行合同','Waiting to load the execution contract'),planReady?'done':'active'),
      flowStep(2,tr('配置检查','Configuration checks'),configReady?tr('工况、输入、输出与运行环境已就绪','Operating points, inputs, outputs, and runtime are ready'):plan?tr(`${Math.max(1,hardIssues.length)} 项需要处理`,`${Math.max(1,hardIssues.length)} item(s) need attention`):tr('等待执行计划','Waiting for the execution plan'),configReady?'done':plan?'blocked':'pending'),
      flowStep(3,tr('原生资格确认','Native qualification refresh'),full?.valid?tr('原生检查证据已固化','Native check evidence is recorded'):fullRunning?tr('后台检查正在运行','Background check is running'):needsNative?tr('可以确认原生资格','Ready to confirm native qualification'):tr('等待分析配置就绪','Waiting for analysis configuration'),full?.valid?'done':fullRunning||needsNative?'active':'pending'),
      flowStep(4,tr('确认并提交','Confirm and submit'),ready?tr('可以创建计算任务','Ready to create the calculation task'):tr('完成前三步后开放提交','Submission unlocks after the first three stages'),ready?'active':'pending'),
    ].join('');
    const primaryState=ready?'ready':fullRunning?'checking':'blocked';
    const primaryTitle=ready?tr('可以提交 Motor-CAD 计算','Ready to submit the Motor-CAD calculation'):fullRunning?tr('计算就绪检查正在执行','The calculation-readiness check is running'):needsNative?tr('配置检查已通过，请执行 原生资格确认','Analysis configuration is ready. Confirm calculation readiness'):plan?tr(`还需处理 ${Math.max(1,hardIssues.length)} 项`,`Resolve ${Math.max(1,hardIssues.length)} item(s) before submission`):tr('先加载执行计划','Load the execution plan first');
    const primaryDetail=ready?tr('当前版本、工况、输入、输出与原生检查证据一致。','The current revisions, operating points, inputs, outputs, and native-check evidence are consistent.'):fullRunning?safe(full.message||tr('正在等待 Motor-CAD 返回检查结果。','Waiting for Motor-CAD to return the check result.')):needsNative?tr('该操作会在后台启动 Motor-CAD，并在当前面板持续显示实际进度。','This starts Motor-CAD in the background and keeps the live progress in this panel.'):tr('下方逐项给出处理位置；只有点击对应按钮时才会切换步骤。','Resolution locations are listed below. A step changes only after you select its action.');
    const primaryAction=!plan?`<button type="button" class="primary" id="analysisInitialPlanV076">${tr('加载执行计划','Load execution plan')}</button>`:needsNative?`<button type="button" class="primary" data-primary-full-check-v090>${tr('运行计算就绪检查','Run calculation-readiness check')}</button>`:(!ready&&!fullRunning&&hardIssues.length)?`<button type="button" data-review-analysis-issues-v090>${tr('查看处理建议','Review resolution actions')}</button>`:'';
    const issueRows=hardIssues.length?`<section id="analysisIssueActionsV090" class="analysis-issue-actions-v090" tabindex="-1"><header><h4>${tr('待处理项','Items to resolve')}</h4><span class="status-chip warning">${hardIssues.length}</span></header>${hardIssues.slice(0,16).map((row,index)=>{const target=issueDestination(row),severity=String(row.severity||'BLOCKING').toUpperCase(),severityClass=severity==='WARNING'?'warning':severity==='INFO'?'info':'blocking';return `<div class="analysis-issue-action-v090 ${severityClass}"><span>${safe(row.code||severity)}</span><div><b>${safe(row.message||row.reason||tr('未命名检查项','Unnamed check item'))}</b><small>${safe(row.detail||row.path||tr('选择右侧操作后前往对应配置位置。','Use the action on the right to open the relevant configuration location.'))}</small></div><button type="button" data-analysis-issue-v090="${index}" data-analysis-issue-target-v090="${safe(target)}">${safe(issueActionLabel(target))}</button></div>`}).join('')}</section>`:'';
    body.innerHTML=`<section class="analysis-editor-section-v076"><header><div><span class="eyebrow">5 · ${safe(stepLabels.check)}</span><h3>${tr('计算就绪检查与提交','Calculation readiness and submission')}</h3><p>${tr('本阶段只检查计算相关条件：工况、物理输入、求解与输出合同、运行环境，并复用当前设计资格；设计指纹失效时才刷新 Motor-CAD 原生资格。系统不会在检查过程中自动切换页面。','This stage checks calculation-specific conditions and reuses the current design qualification. Native Motor-CAD qualification is refreshed only when design evidence is stale. The page does not navigate automatically during checks.')}</p></div><div class="actions"><button id="analysisRefreshPlanV076" type="button" ${fullRunning?'disabled':''}>${tr('刷新执行计划','Refresh execution plan')}</button><button id="analysisFullCheckV076" type="button" ${(!plan||fullRunning||!configReady)?'disabled':''}>${fullRunning?tr('检查进行中…','Check in progress…'):tr('运行计算就绪检查','Run calculation-readiness check')}</button></div></header>
      <ol class="analysis-check-flow-v090" aria-label="${tr('计算就绪检查流程','Calculation-check flow')}">${flowHtml}</ol>
      <div class="analysis-check-primary-v090 ${primaryState}"><div><b>${safe(primaryTitle)}</b><small>${primaryDetail}</small></div><div class="actions">${primaryAction}</div></div>
      ${issueRows}
      ${plan?`<div class="analysis-check-grid-v076">${gateCard(tr('设计资格（复用）','Design qualification (reused)'),Boolean(full?.result?.motorcad?.valid??full?.valid),full?.result?.motorcad?.cache_hit?tr('已复用与当前设计指纹一致的 Motor-CAD 原生资格证据','Reused Motor-CAD qualification evidence matching the current design fingerprint'):full?.valid?tr('原生资格已确认；只有设计证据失效时才重新运行 Motor-CAD','Native qualification is confirmed; Motor-CAD reruns only when design evidence is stale'):tr('等待计算就绪检查确认设计资格证据','Waiting for the calculation-readiness check to confirm design qualification'),false,!full)}${gateCard(tr('分析配置检查','Analysis configuration check'),Boolean(studio.valid),studio.valid?tr('工况、输入、求解与输出合同检查通过','Operating points, inputs, solver settings, and output contracts passed'):tr(`${studio.blocking??(studio.issues||[]).length} 个阻断项`,`${studio.blocking??(studio.issues||[]).length} blocking item(s)`))}${gateCard(tr('任务合同','Task contract'),Boolean(task.valid),task.valid?tr('任务请求结构可执行','The task request is executable'):tr(`${task.blocking||0} 个阻断，${task.warnings||0} 个提示`,`${task.blocking||0} blockers, ${task.warnings||0} notices`),Boolean(task.valid&&task.warnings))}${gateCard(tr('Motor-CAD 运行环境','Motor-CAD runtime'),Boolean(runtime.ok),runtime.ok?tr('Motor-CAD 提交环境可用','The Motor-CAD submission environment is available'):runtime.message||runtime.reason||tr('运行环境未就绪','The runtime is not ready'))}${gateCard(tr('原生资格确认','Native qualification refresh'),Boolean(full?.valid),nativeDetail,false,!full||fullRunning)}${gateCard(tr('物理输入','Physical inputs'),!missing.length,missing.length?tr(`缺少：${missing.join(', ')}`,`Missing: ${missing.join(', ')}`):tr('必需物理输入已配置','Required physical inputs are configured'))}${gateCard(tr('执行标识','Execution identity'),Boolean(plan.execution_plan_hash),plan.execution_plan_hash?`Plan ${String(plan.execution_plan_hash).slice(0,12)}…`:tr('尚未冻结执行计划','Execution plan has not been frozen'))}</div>
      ${fullRunning?`<div class="analysis-native-precheck-progress-v089g33" data-native-precheck-progress><div><b data-native-precheck-stage>${safe(full.stageLabel||tr('启动 Motor-CAD 检查','Start Motor-CAD check'))}</b><span data-native-precheck-percent>${fullPercent===null?tr('运行中','Running'):`${Math.round(fullPercent)}%`}</span></div><div class="analysis-native-precheck-track-v089g33 ${fullPercent===null?'indeterminate':''}"><i data-native-precheck-bar style="${fullPercent===null?'':`width:${fullPercent}%`}"></i></div><p data-native-precheck-message>${safe(full.message||tr('后台检查已启动，当前页面会持续显示进度。','The background check has started. Progress remains visible on this page.'))}</p></div>`:''}
      <div class="analysis-check-actions-v076"><div class="analysis-submit-controls-v076"><label>${tr('任务名称','Task name')}<input id="analysisTaskNameV076" value="${safe(ctl.active.name)}" ${fullRunning?'disabled':''}></label><label>${tr('结果验证级别','Result validation level')}<select id="analysisQualityV076" ${fullRunning?'disabled':''}>${qualityOptions}</select></label><label class="check-row"><input id="analysisReuseV076" type="checkbox" ${ctl.reuseCache?'checked':''} ${fullRunning?'disabled':''}>${tr('复用已验证缓存','Reuse validated cache')}</label></div><button id="analysisSubmitV076" type="button" class="primary" ${ready?'':'disabled'}>${fullRunning?tr('等待计算就绪检查…','Waiting for calculation-readiness check…'):tr('提交 Motor-CAD 计算','Submit Motor-CAD calculation')}</button></div>
      <div class="analysis-run-history-v076"><h4>${tr('最近执行','Recent runs')}</h4>${(plan.recent_tasks||[]).map(row=>`<div class="analysis-run-row-v076"><div><b>${safe(row.name||row.id)}</b><small>${safe(row.status||'')} · ${safe(row.created_at||'')}</small></div><button type="button" data-open-task-v076="${safe(row.id)}">${tr('查看','View')}</button></div>`).join('')||`<p class="muted">${tr('该分析尚无执行记录。','This analysis has no execution history.')}</p>`}</div>`:`<div class="analysis-empty-v076"><h3>${tr('执行计划尚未加载','Execution plan has not been loaded')}</h3><p>${tr('读取当前分析版本的执行合同，再运行计算就绪检查。','Load the execution contract for the current analysis revision, then run the calculation-readiness check.')}</p></div>`}
      <details class="analysis-standard-validation-dock-v090"><summary><span>${tr('标准设计验证（可选）','Standard design validation (optional)')}</span><small>${tr('批量运行预设验证链；不会自动离开当前页面','Run the preset validation chain in batch without leaving this page automatically')}</small></summary><div id="analysisStandardValidationDockV090"></div></details>
      <div id="analysisCheckStatusV076" class="analysis-inline-status-v076 ${fullRunning?'running':''}">${fullRunning?safe(full.message||tr('计算就绪检查正在运行…','The calculation-readiness check is running…')):(full?.valid?tr('计算就绪检查已通过，可以提交 Motor-CAD 计算。','The calculation-readiness check passed. The Motor-CAD calculation can be submitted.'):full?.result?.message?safe(full.result.message):'')}</div>
    </section>`;
    const checkHeader=q('.analysis-editor-section-v076 > header',body),guidanceHtml=guidanceOverviewHtml({actions:true});if(checkHeader&&guidanceHtml)checkHeader.insertAdjacentHTML('afterend',guidanceHtml);bindAutoFixActions(body);
    q('#analysisInitialPlanV076',body)?.addEventListener('click',()=>loadExecutionPlan());
    q('#analysisRefreshPlanV076',body)?.addEventListener('click',async()=>{if(ctl.fullCheck?.running)return;ctl.fullCheck=null;await loadExecutionPlan()});
    q('#analysisFullCheckV076',body)?.addEventListener('click',runFullCheck);
    q('[data-primary-full-check-v090]',body)?.addEventListener('click',runFullCheck);
    q('[data-review-analysis-issues-v090]',body)?.addEventListener('click',()=>{const target=q('#analysisIssueActionsV090',body);target?.focus?.({preventScroll:true});target?.scrollIntoView?.({behavior:'smooth',block:'nearest'})});
    qa('[data-analysis-issue-v090]',body).forEach((button,index)=>button.addEventListener('click',()=>{const row=hardIssues[index]||{};openIssueTarget(button.dataset.analysisIssueTargetV090||issueDestination(row),row.message||row.reason||'')}));
    q('#analysisSubmitV076',body)?.addEventListener('click',submitExecution);
    qa('[data-open-task-v076]',body).forEach(button=>button.addEventListener('click',()=>window.MCSRouter?.navigate?.(`/app/projects/${encode(state.activeProjectId)}/simulation/tasks/${encode(button.dataset.openTaskV076)}`)));
    q('#analysisQualityV076',body)?.addEventListener('change',async event=>{ctl.qualityProfile=event.target.value;ctl.fullCheck=null;await loadExecutionPlan()});
    q('#analysisReuseV076',body)?.addEventListener('change',async event=>{ctl.reuseCache=event.target.checked;ctl.fullCheck=null;await loadExecutionPlan()});
    window.MCS_I18N?.apply?.(body);
    document.dispatchEvent(new CustomEvent('mcs:analysis-check-mounted',{detail:{analysisId:ctl.active?.id||null,designRevisionId:ctl.active?.design_revision_id||null}}));
  }
  function patchFullCheckProgress(){
    const full=ctl.fullCheck;if(!full?.running)return;
    const percent=Number.isFinite(full.progressPercent)?Math.max(0,Math.min(100,Number(full.progressPercent))):null;
    const status=q('#analysisCheckStatusV076'),stage=q('[data-native-precheck-stage]'),percentNode=q('[data-native-precheck-percent]'),message=q('[data-native-precheck-message]'),track=q('.analysis-native-precheck-track-v089g33'),bar=q('[data-native-precheck-bar]');
    if(status){status.textContent=full.message||'计算就绪检查正在运行…';status.className='analysis-inline-status-v076 running'}
    if(stage)stage.textContent=full.stageLabel||full.stage||'Motor-CAD 检查';
    if(percentNode)percentNode.textContent=percent===null?'运行中':`${Math.round(percent)}%`;
    if(message)message.textContent=full.message||'';
    track?.classList.toggle('indeterminate',percent===null);
    if(bar&&percent!==null)bar.style.width=`${percent}%`;
  }
  async function runFullCheck(){
    if(!ctl.active)return false;
    if(!ctl.executionPlan){await loadExecutionPlan();if(!ctl.executionPlan)return false}
    if(ctl.fullCheck?.running)return false;
    const capturedPlan=ctl.executionPlan,capturedAnalysisRevisionId=capturedPlan.analysis_revision?.id,capturedDesignRevisionId=capturedPlan.design_revision?.id;
    const firstButton=q('#analysisFullCheckV076');
    const op=operationProgress({id:`analysis-full-precheck-${ctl.active.id}`,label:'计算就绪检查',stage:'创建后台检查任务',detail:'将立即返回任务标识，Motor-CAD 检查在后台执行',percent:3,button:firstButton,failDelay:6000,timeoutMs:270000,timeoutDetail:'计算就绪检查超过 4 分 30 秒，界面已恢复；请查看 Motor-CAD 进程与服务日志。'});
    ctl.fullCheck={valid:false,running:true,analysisRevisionId:capturedAnalysisRevisionId,designRevisionId:capturedDesignRevisionId,stage:'queued',stageLabel:'创建后台检查任务',progressPercent:3,message:'正在创建计算就绪检查任务…',result:null};
    renderCheck();renderSummary();
    const stageLabels={queued:'进入检查队列',capture:'冻结当前版本',studio:'Studio 预检查',motorcad:'Motor-CAD 原生检查',identity:'版本身份确认',evidence:'固化检查证据',done:'检查完成',failed:'检查失败'};
    try{
      const job=await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/calculation-check/jobs`,{method:'POST',body:JSON.stringify({expected_analysis_revision_id:capturedAnalysisRevisionId,expected_design_revision_id:capturedDesignRevisionId})});
      if(!job?.id)throw new Error('计算就绪检查任务未返回任务标识');
      ctl.fullCheck.jobId=job.id;ctl.fullCheck.stage=job.stage||'queued';ctl.fullCheck.stageLabel=stageLabels[job.stage]||'计算就绪检查';ctl.fullCheck.progressPercent=Number.isFinite(job.progress_percent)?job.progress_percent:null;ctl.fullCheck.message=job.message||'计算就绪检查任务已创建。';patchFullCheckProgress();
      let current=job,attempt=0,deadline=Date.now()+265000;
      while(['QUEUED','RUNNING'].includes(String(current.status||'').toUpperCase())){
        if(Date.now()>deadline)throw new Error('计算就绪检查等待超时；界面已恢复，请查看 Motor-CAD 运行日志后重试。');
        attempt+=1;
        const percent=current.indeterminate?null:(Number.isFinite(current.progress_percent)?Number(current.progress_percent):null),stageId=current.stage||'motorcad',stageLabel=stageLabels[stageId]||'计算就绪检查',detail=current.message||'Motor-CAD 正在执行检查…';
        ctl.fullCheck.stage=stageId;ctl.fullCheck.stageLabel=stageLabel;ctl.fullCheck.progressPercent=percent;ctl.fullCheck.message=detail;
        op.update({percent,stage:stageLabel,detail});patchFullCheckProgress();
        await wait(attempt<3?350:700);
        current=await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/calculation-check/jobs/${encode(job.id)}`);
      }
      if(String(current.status||'').toUpperCase()==='FAILED')throw new Error(current.error||current.message||'计算就绪检查执行失败');
      const result=current.result;if(!result)throw new Error('计算就绪检查完成，但未返回检查结果');
      ctl.fullCheck={valid:Boolean(result.valid),running:false,analysisRevisionId:capturedAnalysisRevisionId,designRevisionId:capturedDesignRevisionId,jobId:job.id,stage:'done',stageLabel:'检查完成',progressPercent:100,message:result.valid?'计算就绪检查通过。':(result.motorcad?.message||'计算就绪检查存在阻断项。'),result};
      if(result.valid)op.done('计算就绪检查通过（已复用/刷新设计资格）');else op.fail(result.motorcad?.message||'计算就绪检查存在阻断项');
      notify(result.valid?'计算就绪检查通过':'计算就绪检查存在阻断项',result.valid?'SUCCESS':'WARNING',8000);renderCheck();renderSummary();return Boolean(result.valid);
    }catch(error){
      ctl.fullCheck={valid:false,running:false,analysisRevisionId:capturedAnalysisRevisionId,designRevisionId:capturedDesignRevisionId,result:{message:error.message},message:error.message};op.fail(error.message);notify(error.message,'ERROR',9000);renderCheck();renderSummary();return false;
    }
  }
  function newSubmissionKey(){return `ANX-${globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(16).slice(2)}`}`.replace(/[^A-Za-z0-9-]/g,'').slice(0,120)}
  async function submitExecution(){
    if(!ctl.active||!ctl.fullCheck?.valid||ctl.fullCheck?.running)return false;
    return actionLock(`analysis-submit:${ctl.active.id}`,async()=>{
      const status=q('#analysisCheckStatusV076'),button=q('#analysisSubmitV076');
      const op=operationProgress({id:`analysis-submit-${ctl.active.id}`,label:'提交 Motor-CAD 计算',stage:'冻结执行计划',detail:'确认当前 Revision 与完整检查证据仍一致',percent:8,button,failDelay:6000});
      try{
        if(status){status.textContent='正在重新冻结执行计划并提交…';status.className='analysis-inline-status-v076 running'}
        op.update({percent:24,stage:'复核执行合同',detail:'重新读取工况、输入、求解设置与运行时状态'});
        const plan=await loadExecutionPlan({render:false,progressOp:op});
        if(!plan?.can_submit){resetSubmissionKey();throw new Error('执行计划已变更或存在阻断项，请重新检查。')}
        if(ctl.fullCheck.analysisRevisionId!==plan.analysis_revision?.id||ctl.fullCheck.designRevisionId!==plan.design_revision?.id){resetSubmissionKey();throw new Error('Revision 已变更，请重新运行计算就绪检查。')}
        const quality=q('#analysisQualityV076')?.value||ctl.qualityProfile||'standard',reuse=q('#analysisReuseV076')?q('#analysisReuseV076').checked:ctl.reuseCache,name=q('#analysisTaskNameV076')?.value.trim()||ctl.active.name;ctl.qualityProfile=quality;ctl.reuseCache=Boolean(reuse);
        const submissionKey=stableSubmissionKey(plan,{quality,reuse,name});
        op.update({percent:93,stage:'提交运行任务',detail:'向 Motor-CAD Worker 队列提交不可变执行合同'});
        const created=await apiCall(`/api/analysis-definitions/${encode(ctl.active.id)}/execute`,{method:'POST',timeoutMs:270000,body:JSON.stringify({name,quality_profile:quality,reuse_cache:reuse,submission_key:submissionKey,precheck_evidence_id:ctl.fullCheck?.result?.evidence?.id||undefined,run_native_precheck:true,expected_analysis_revision_id:plan.analysis_revision?.id,expected_design_revision_id:plan.design_revision?.id,expected_execution_plan_hash:plan.execution_plan_hash})});
        resetSubmissionKey();contextStore()?.setExecution?.(created,{taskId:created.task_id,source:'analysis:execute'});op.done(created.idempotent_replay?'已恢复同一次计算提交':'计算任务已创建');notify(created.idempotent_replay?'已恢复同一次计算提交':'计算任务已创建','SUCCESS',7000);
        const next=created.next_route||`/app/projects/${encode(state.activeProjectId)}/simulation/monitor/${encode(created.task_id)}`;return (await window.MCSRouter?.navigate?.(next,{source:'analysis:submit-success'}))!==false;
      }catch(error){op.fail(error.message);if(button)button.disabled=false;if(status){status.textContent=error.message;status.className='analysis-inline-status-v076 error'}notify(error.message,'ERROR',10000);return false}
    })
  }

  async function saveAnalysisRevision(patch={}){
    if(!ctl.active)throw new Error(tr('没有当前分析配置','No active analysis configuration'));const analysisId=ctl.active.id;return actionLock(`analysis-revision-save:${analysisId}`,async()=>{const current=activeDefinition();const payload={load_cases:patch.load_cases??current.load_cases??[{}],solver_settings:patch.solver_settings??current.solver_settings??{},input_domains:patch.input_domains??current.input_domains??{},requested_outputs:patch.requested_outputs??current.requested_outputs??[],notes:patch.notes||tr('从统一分析配置更新','Updated from unified analysis configuration')};const bundle=workspaceClient()?await workspaceClient().createRevision(analysisId,payload):null;const updated=bundle?.analysis_definition||await apiCall(`/api/analysis-definitions/${encode(analysisId)}/revisions`,{method:'POST',body:JSON.stringify(payload)});ctl.active=updated;ctl.definitions=ctl.definitions.map(row=>row.id===updated.id?updated:row);ctl.inputCatalog=bundle?.input_catalog||await apiCall(`/api/analysis-definitions/${encode(updated.id)}/input-domains`);ctl.executionPlan=null;ctl.fullCheck=null;resetSubmissionKey();contextStore()?.setAnalysis?.(updated,{analysisRevisionId:updated.revisions?.[0]?.id||null,motorRevision:updated.design_revision_id,source:'analysis:save-revision'});renderList();renderSummary();scheduleGuidanceRefresh();return updated})
  }

  function renderSummary(){
    const root=q('#analysisSummaryV076');if(!root)return;const context=currentContext(),record=activeRevisionRecord()||ctl.revisionIndex.get(String(ctl.selectedRevisionId||'')),definition=activeDefinition(),input=ctl.inputCatalog,plan=ctl.executionPlan;const cases=(definition.load_cases||[]).length,outputs=(definition.requested_outputs||[]).length,configured=(input?.domains||[]).filter(row=>row.configured).length,required=(input?.required_domain_ids||[]).length,missing=(input?.missing_required_domain_ids||[]).length;root.innerHTML=`<div class="analysis-summary-chain-v076"><div class="analysis-summary-node-v076 active"><span>项目</span><b>${safe(ctl.project?.name||context.projectId||'-')}</b></div><div class="analysis-summary-node-v076 ${record?'active':''}"><span>方案</span><b>${safe(record?.design?.name||context.solutionId||'-')}</b></div><div class="analysis-summary-node-v076 ${record?'active':''}"><span>电机版本</span><b>${record?`${safe(revisionLabel(record.revision?.revision,'motor'))} \u00b7 ${safe(record.revision?.id)}`:safe(context.motorRevisionId||'-')}</b></div><div class="analysis-summary-node-v076 ${ctl.active?'active':''}"><span>分析配置</span><b>${safe(ctl.active?.name||context.analysisId||'-')}</b></div><div class="analysis-summary-node-v076 ${activeAnalysisRevision()?'active':''}"><span>分析版本</span><b>${activeAnalysisRevision()?`${safe(revisionLabel(activeAnalysisRevision().revision))} \u00b7 ${safe(activeAnalysisRevision().id)}`:'-'}</b></div><div class="analysis-summary-node-v076 ${context.taskId?'active':''}"><span>计算任务</span><b>${safe(context.taskId||'\u5c1a\u672a\u63d0\u4ea4')}</b></div></div><div class="analysis-readiness-v076"><div><span>\u5de5\u51b5</span><b>${cases}</b></div><div><span>\u8bf7\u6c42\u8f93\u51fa</span><b>${outputs}</b></div><div><span>\u7269\u7406\u8f93\u5165</span><b>${configured}${required?`/${required}`:''}</b></div><div><span>\u5fc5\u586b\u7f3a\u5931</span><b>${missing}</b></div></div><div class="analysis-summary-note-v076">${plan?`执行计划 ${safe(String(plan.execution_plan_hash||'').slice(0,12))}\u2026 \u00b7 ${plan.can_submit?'\u5de5\u7a0b\u5408\u540c\u5c31\u7eea':'\u5b58\u5728\u5f85\u5904\u7406\u9879'}`:tr('分析配置页不再另行维护任务向导状态；当前对象链由工程上下文存储统一管理。','The analysis page no longer owns task-wizard state; the engineering context store owns the object chain.')}</div>`;
    const guidanceTemplate=ctl.guidance?.template;if(guidanceTemplate){q('.analysis-readiness-v076',root)?.insertAdjacentHTML('beforeend',`<div><span>工程模板</span><b>${safe(guidanceTemplate.short_label||guidanceTemplate.label||guidanceTemplate.id)}</b></div>`)}
  }

  function renderEditorBody(){if(!ctl.active){renderCreateForm();return}showEditor();renderSteps();if(ctl.step==='definition')renderDefinition();else if(ctl.step==='operating')renderOperating();else if(ctl.step==='inputs')renderInputs();else if(ctl.step==='solver')renderSolver();else if(ctl.step==='check')renderCheck();if(ctl.step!=='check')renderReturnToCheckBanner()}
  function renderAll(){renderContext();renderList();renderSummary();if(ctl.active)renderEditorBody();else renderEmpty()}

  async function refreshImpl({skipFlush=false}={}){
    if(!state.activeProjectId)return false;
    if(!skipFlush&&!(await flushCurrentAnalysisEditor({reason:'analysis-refresh',notifyOnSave:true})))return false;
    const activeId=ctl.active?.id||ctl.activeId,button=q('#analysisRefreshV076'),op=operationProgress({id:`analysis-refresh-${state.activeProjectId}`,label:'刷新分析工作区',stage:'读取项目',detail:'同步设计、分析配置、模板与工程摘要',percent:5,button,timeoutMs:60000,timeoutDetail:'分析工作区加载超过 60 秒，界面已恢复；请重试或查看服务日志。'});
    try{
      await fetchProjectGraph(op);op.update({percent:44,stage:'读取分析索引',detail:'加载分析定义、配方与工程模板'});
      await Promise.all([fetchDefinitions(),fetchCatalogForRevision(ctl.selectedRevisionId,{force:true}),fetchTemplateCatalogForRevision(ctl.selectedRevisionId,{force:true})]);
      if(activeId&&ctl.definitions.some(row=>row.id===activeId))await hydrateActive(activeId,{op});else{ctl.active=null;ctl.activeId=null;ctl.inputCatalog=null;renderAll()}
      op.done('分析工作区已同步');return true;
    }catch(error){op.fail(error.message);throw error}
  }

  function refresh(options={}){
    // Refresh has a different lifecycle from route mounting. Sharing one promise for
    // both allowed a stale/disposed route to suppress the next mount entirely.
    if(ctl.refreshPromise)return ctl.refreshPromise;
    const promise=refreshImpl(options);ctl.refreshPromise=promise;
    return promise.finally(()=>{if(ctl.refreshPromise===promise)ctl.refreshPromise=null});
  }

  function goMotor(){
    const record=activeRevisionRecord()||ctl.revisionIndex.get(String(ctl.selectedRevisionId||''));if(!record)return window.showTab?.('workspace');contextStore()?.setMotorRevision?.(record.revision,{solution:record.design,source:'analysis:back-to-motor'});const path=`/app/projects/${encode(state.activeProjectId)}/designs/${encode(record.design.id)}/revisions/${encode(record.revision.id)}/geometry/radial`;return window.MCSRouter?.navigate?.(path)
  }

  async function openCreateFromToolbar(button){
    // First paint immediately so the primary action always gives visible feedback.
    ctl.active=null;ctl.activeId=null;ctl.inputCatalog=null;ctl.executionPlan=null;ctl.fullCheck=null;
    renderContext();renderList();renderSummary();renderCreateForm();
    if(ctl.catalog&&ctl.templateCatalog)return true;
    const op=operationProgress({id:`analysis-create-catalog-${state.activeProjectId||'none'}`,label:'加载分析模板',detail:'读取可用配方与工程模板',percent:18,button});
    try{
      op.update({percent:55,stage:'读取模板',detail:'同步当前电机版本可用分析能力'});
      await Promise.all([fetchCatalogForRevision(),fetchTemplateCatalogForRevision()]);
      if(!ctl.active&&q('#analysisConfig')?.classList.contains('active'))renderCreateForm();
      op.done('分析模板已就绪');return true;
    }catch(error){op.fail(error.message);notify(error.message,'ERROR');return false}
  }

  // Stable ownership for the persistent analysis toolbar. This listener survives
  // PageRuntime context disposal and therefore cannot become unbound after a route
  // abort/remount cycle.
  document.addEventListener('click',event=>{
    const button=event.target?.closest?.('#analysisCommonModeV081A,#analysisAdvancedModeV081A,#analysisBackToMotorV076,#analysisRefreshV076,#analysisCreateV076');
    if(!button||!q('#analysisConfig')?.classList.contains('active'))return;
    if(button.disabled||button.getAttribute('aria-disabled')==='true')return;
    if(button.id==='analysisCommonModeV081A'){setHmiMode('common').catch(error=>notify(error.message,'ERROR'));return}
    if(button.id==='analysisAdvancedModeV081A'){setHmiMode('advanced').catch(error=>notify(error.message,'ERROR'));return}
    if(button.id==='analysisBackToMotorV076'){goMotor();return}
    if(button.id==='analysisRefreshV076'){refresh().catch(error=>notify(error.message,'ERROR'));return}
    if(button.id==='analysisCreateV076')openCreateFromToolbar(button);
  });

  async function mount(route,ctx){
    ctl.ctx=ctx||null;ctl.route=route||{};ctl.step=resolveStep(route);ctl.executionPlan=null;ctl.fullCheck=null;ctl.returnToCheck=null;resetSubmissionKey();contextStore()?.setStage?.('analysis',{source:'analysis:mount'});
    // Header controls use one stable delegated owner installed below. Route-scoped
    // ctx.listen handlers were disposed during navigation and, when a stale shared
    // load promise skipped the next mount, left visibly enabled buttons with no effect.
    syncHmiModeButtons();
    const loadOp=operationProgress({id:`analysis-mount-${state.activeProjectId||'none'}`,label:'加载分析工作区',stage:'读取项目',detail:'正在加载设计、分析配置与工程汇总',percent:5,timeoutMs:60000,timeoutDetail:'分析工作区加载超过 60 秒，界面已恢复；请重试或查看服务日志。'});
    try{
      await fetchProjectGraph(loadOp);ctx?.assertActive?.();
      if(!ctl.selectedRevisionId){renderAll();renderCreateForm();loadOp.done('项目尚无可用电机版本');return}
      loadOp.update({percent:44,stage:'加载分析索引',detail:'读取分析定义、配方与工程模板'});
      await Promise.all([fetchDefinitions(),fetchCatalogForRevision(),fetchTemplateCatalogForRevision()]);ctx?.assertActive?.();
      const activeId=chooseInitialAnalysis(route);
      if(activeId){ctl.step=resolveStep(route);await hydrateActive(activeId,{render:false,op:loadOp});ctx?.assertActive?.();renderAll();if(ctl.step==='check'){loadOp.update({percent:95,stage:'生成执行计划',detail:'检查当前计算准备状态'});await loadExecutionPlan({progressOp:loadOp})}}
      else{ctl.active=null;ctl.activeId=null;renderAll();renderCreateForm()}
      ctl.loadError=null;loadOp.done('分析工作区加载完成');
    }
    catch(error){
      loadOp.fail(error.message);
      if(window.MCSPageRuntime?.isAbortError?.(error))return;
      ctl.loadError=error;
      const body=q('#analysisEditorBodyV076');showEditor();
      if(body)body.innerHTML=`<div class="analysis-empty-v076 analysis-load-error-v089g1r"><h3>${safe(text.loadFailed)}</h3><p>${safe(error.message)}</p><div class="actions"><button type="button" class="primary" data-analysis-retry-v076>重新加载</button><button type="button" data-analysis-back-v089g1r>返回电机配置</button></div><small>页面操作仍可用；重新加载只重试数据，不会销毁当前导航状态。</small></div>`;
      q('[data-analysis-retry-v076]',body)?.addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;try{await refresh({skipFlush:true});ctl.loadError=null}catch(next){notify(`分析配置仍无法加载：${next.message}`,'ERROR',6500)}finally{button.disabled=false}});
      q('[data-analysis-back-v089g1r]',body)?.addEventListener('click',goMotor);
      return false;
    }
  }

  function mountSingleFlight(route,ctx){
    const owner=ctx||null;
    if(ctl.mountPromise&&ctl.mountOwner===owner)return ctl.mountPromise;
    const previous=ctl.mountPromise;
    const promise=(async()=>{
      // A new route context must always execute its own mount. Wait for the disposed
      // predecessor to observe its AbortSignal, then bind/render against the new ctx.
      if(previous){try{await previous}catch(error){if(!window.MCSPageRuntime?.isAbortError?.(error))console.warn('[analysis] previous mount ended with error',error)}}
      if(ctx?.active&&!ctx.active())return false;
      return mount(route,ctx);
    })();
    ctl.mountPromise=promise;ctl.mountOwner=owner;
    return promise.finally(()=>{if(ctl.mountPromise===promise){ctl.mountPromise=null;ctl.mountOwner=null}});
  }

  function analysisGuardState(){return {active:Boolean(ctl.active&&q('#analysisEditorV076')&&!q('#analysisEditorV076')?.classList.contains('hidden')),dirty:currentStepDirty(),analysis_id:ctl.active?.id||null,step:ctl.step,domain_id:ctl.domainId||null}}
  async function prepareAnalysisRouteChange(route){const stateNow=analysisGuardState();if(!stateNow.active)return true;const same=route?.tab==='analysisConfig'&&String(route?.analysisId||'')===String(ctl.active?.id||'')&&(!route?.analysisStep||route.analysisStep===ctl.step);if(same)return true;return flushCurrentAnalysisEditor({reason:'route-change',notifyOnSave:true})}
  window.MCSNavigationTransaction?.registerGuard?.({id:'analysis-editor',priority:90,isActive:()=>analysisGuardState().active,unsafe:currentStepDirty,inspect:analysisGuardState,prepare:prepareAnalysisRouteChange});
  function unmount(){ctl.requestToken+=1;clearTimeout(ctl.guidanceTimer);ctl.guidanceTimer=null;ctl.ctx=null;ctl.route=null;ctl.busy=false;ctl.transitionBusy=false}

  document.addEventListener('change',event=>{if(event.target?.matches?.('[data-domain-field-v076]'))syncConditionalInputs(q('#analysisEditorBodyV076')||document)});
  document.addEventListener('mcs-language-change',()=>{if(q('#analysisConfig')?.classList.contains('active'))renderAll()});

  window.MCSUnifiedAnalysis={mount:mountSingleFlight,unmount,refresh,openCreate:renderCreateForm,setStep,inspectTransaction:analysisGuardState,flushCurrentEditor:flushCurrentAnalysisEditor,state:ctl};
})();
