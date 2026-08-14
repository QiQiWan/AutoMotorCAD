/* V0.17 end-to-end workflow integrity and project-centric task context */
state.projectRevisionIndex = state.projectRevisionIndex || new Map();
state.projectScenarioRevisionIndex = state.projectScenarioRevisionIndex || new Map();
state.taskScenarioRevisionId = state.taskScenarioRevisionId || null;
state.taskBaseRevision = state.taskBaseRevision || null;
state.workflowReadiness = null;

function workflowLocalKey(kind){return `motorcad-studio-${kind}:${state.activeProjectId||'none'}`}

function materialOverrideCount(){
  const base=state.taskBaseRevision?.materials||{};let current;try{current=collectMaterials()}catch(_){return 1}
  let changed=String(base.material_database_path||'')===String(current.material_database_path||'')?0:1;
  const compareMap=(a,b)=>{const keys=new Set([...Object.keys(a||{}),...Object.keys(b||{})]);let n=0;keys.forEach(k=>{if(String((a||{})[k]||'')!==String((b||{})[k]||''))n++});return n};
  changed+=compareMap(base.component_materials||base.components||{},current.component_materials||{});
  changed+=compareMap(base.cooling_fluids||{},current.cooling_fluids||{});
  return changed;
}

function taskOverrideCount(){
  const base=state.taskBaseRevision?.parameters||{};let changed=0;
  $$('[data-param]').forEach(input=>{const id=input.dataset.param;if(!(id in base))return;const raw=input.value;const value=raw!==''&&Number.isFinite(Number(raw))?Number(raw):raw;const b=base[id];const same=(typeof b==='number'&&typeof value==='number')?Math.abs(b-value)<=Math.max(1e-9,Math.abs(b)*1e-9):String(b)===String(value);if(!same)changed++});
  return changed+materialOverrideCount();
}


function updateTaskContextGate(){
  const ready=Boolean(state.activeProjectId&&state.taskDesignRevisionId&&state.projectRevisionIndex.has(state.taskDesignRevisionId));
  const box=$('#taskContextBlocker');if(box){box.classList.toggle('hidden',ready);box.innerHTML=ready?'':uiText('<b>还不能提交计算。</b> 请先在当前项目中创建并选择 Design Revision；模板、参数基线和结果血缘都会从设计版本继承。','<b>Task context is incomplete.</b> Create and select a Design Revision in the active project first. Template, parameter baseline and result lineage are inherited from it.')}
  const submit=$('#taskForm button[type="submit"]');if(submit)submit.disabled=!ready;const validate=$('#validateTask');if(validate)validate.disabled=!ready;const geometry=$('#geometryRuntimeCheck');if(geometry)geometry.disabled=!ready;
}

function updateTaskRevisionHint(){
  const hint=$('#taskDesignRevisionHint');const save=$('#saveTaskDesignRevision');const rec=state.projectRevisionIndex.get(state.taskDesignRevisionId);const overrides=rec?taskOverrideCount():0;
  if(save){save.disabled=!rec||overrides===0;save.textContent=overrides?uiText(`将 ${overrides} 项设计修改保存为新 Revision`,`Save ${overrides} design change(s) as new revision`):uiText('将当前设计修改保存为新 Revision','Save current design changes as new revision')}
  if(!hint)return;
  if(!rec){hint.textContent=uiText('必须先选择当前项目中的 Design Revision；模板和基线参数将由设计版本继承。','Select a Design Revision in the active project first; template and baseline parameters are inherited from it.');hint.classList.add('warning');updateTaskContextGate();return}
  hint.textContent=uiText(`${rec.design.name} · Rev.${rec.revision.revision} · ${rec.design.template_id}；当前任务相对该版本有 ${overrides} 项运行覆盖。`,`${rec.design.name} · Rev.${rec.revision.revision} · ${rec.design.template_id}; ${overrides} runtime overrides relative to this revision.`);
  hint.classList.remove('warning');updateTaskContextGate();
}

function applyMaterialRevision(materials){
  const m=materials||{};
  if($('#materialDb'))$('#materialDb').value=m.material_database_path||'';
  const comp=m.component_materials||m.components||{};const fluids=m.cooling_fluids||{};
  if($('#componentMaterials'))$('#componentMaterials').value=Object.entries(comp).map(([k,v])=>`${k}=${v}`).join('\n');
  if($('#coolingFluids'))$('#coolingFluids').value=Object.entries(fluids).map(([k,v])=>`${k}=${v}`).join('\n');
  $$('[data-material-slot]').forEach(sel=>{const v=comp[sel.dataset.materialSlot]||'';if([...sel.options].some(o=>o.value===v))sel.value=v});
  $$('[data-fluid-slot]').forEach(sel=>{const v=fluids[sel.dataset.fluidSlot]||'';if([...sel.options].some(o=>o.value===v))sel.value=v});
}

async function applyTaskDesignRevision(revisionId,{silent=false}={}){
  const rec=state.projectRevisionIndex.get(revisionId);if(!rec)return;
  const t=state.templates.find(x=>x.id===rec.design.template_id);if(!t){toast(uiText('该设计版本对应的模板未加载。','The template for this design revision is not loaded.'),'ERROR');return}
  state.taskDesignRevisionId=revisionId;state.taskBaseRevision=rec.revision;localStorage.setItem(workflowLocalKey('design-revision'),revisionId);
  state.selectedTemplate=t;renderTemplateSelect();if($('#templateSelect')){$('#templateSelect').value=t.id;$('#templateSelect').disabled=true}onTemplateChange();
  Object.entries(rec.revision.parameters||{}).forEach(([k,v])=>{const input=document.querySelector(`[data-param="${CSS.escape(k)}"]`);if(input)input.value=v});
  // Rebase the task editor after Revision hydration.  Template defaults are only
  // construction defaults; once a Design Revision is selected, its effective
  // values are the task baseline.  This keeps the first preview, change badges
  // and explicit task overrides aligned with the same immutable revision.
  $$('[data-param-field]').forEach(field=>{
    const input=field.querySelector('[data-param]');if(!input)return;
    field.dataset.default=input.value;
    field.dataset.revisionBaseline=input.value;
    field.classList.remove('changed');
  });
  applyMaterialRevision(rec.revision.materials||{});
  if($('#taskName')&&!$('#taskName').dataset.userEdited)$('#taskName').value=`${rec.design.name} Rev.${rec.revision.revision}`;
  updateParameterInspector();renderLiveDesignPreview();updateTaskPreview();updateTaskRevisionHint();refreshWorkflowReadiness();
  if(!silent)toast(uiText(`已载入 ${rec.design.name} Rev.${rec.revision.revision}`,`Loaded ${rec.design.name} Rev.${rec.revision.revision}`),'SUCCESS');
}

async function refreshProjectTaskContext({autoLoad=true}={}){
  const select=$('#taskDesignRevisionSelect');if(!select)return;
  state.projectRevisionIndex=new Map();state.projectScenarioRevisionIndex=new Map();
  if(!state.activeProjectId){select.innerHTML=`<option value="">${uiText('请先选择项目','Select a project first')}</option>`;state.taskDesignRevisionId=null;state.taskBaseRevision=null;await refreshScenarioContext();updateTaskRevisionHint();updateTaskContextGate();return}
  try{
    const project=await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`);state.workspaceProject=project;
    const designDetails=await Promise.all((project.designs||[]).map(d=>api(`/api/designs/${encodeURIComponent(d.id)}`)));
    const options=[];
    designDetails.forEach(d=>(d.revisions||[]).forEach(r=>{const rec={design:d,revision:r};state.projectRevisionIndex.set(r.id,rec);options.push(rec)}));
    options.sort((a,b)=>(b.revision.created_at||'').localeCompare(a.revision.created_at||''));
    select.innerHTML=`<option value="">${uiText('请选择 Design Revision','Select Design Revision')}</option>`+options.map(rec=>`<option value="${esc(rec.revision.id)}">${esc(rec.design.name)} · Rev.${esc(rec.revision.revision)} · ${esc(rec.design.template_id)}</option>`).join('');
    let wanted=state.taskDesignRevisionId||localStorage.getItem(workflowLocalKey('design-revision'))||'';
    if(!state.projectRevisionIndex.has(wanted))wanted=options.length===1?options[0].revision.id:'';
    if(wanted){select.value=wanted;if(autoLoad&&state.taskDesignRevisionId!==wanted)await applyTaskDesignRevision(wanted,{silent:true})}
    else{state.taskDesignRevisionId=null;state.taskBaseRevision=null;updateTaskRevisionHint()}
    await refreshScenarioContext(project);
  }catch(e){select.innerHTML=`<option value="">${uiText('设计版本加载失败','Failed to load design revisions')}</option>`;toast(e.message,'ERROR')}
}

async function saveTaskDesignRevision(){
  const rec=state.projectRevisionIndex.get(state.taskDesignRevisionId);if(!rec)return toast(uiText('请先选择 Design Revision','Select a Design Revision first'),'WARNING');
  const overrides=taskOverrideCount();if(!overrides)return toast(uiText('当前没有需要保存的设计修改','There are no design changes to save'),'INFO');
  try{
    const current=collectPayload();const explicit=[...new Set([...(rec.revision.explicit_parameter_ids||[]),...(current.explicit_parameter_ids||[])])];const created=await api(`/api/designs/${encodeURIComponent(rec.design.id)}/revisions`,{method:'POST',body:JSON.stringify({parameters:collectParameters(),materials:collectMaterials(),explicit_parameter_ids:explicit,notes:uiText(`由任务编辑器保存，基于 Rev.${rec.revision.revision}`,`Saved from task builder, based on Rev.${rec.revision.revision}`)})});
    state.taskDesignRevisionId=created.id;localStorage.setItem(workflowLocalKey('design-revision'),created.id);await refreshProjectTaskContext({autoLoad:true});if($('#taskDesignRevisionSelect'))$('#taskDesignRevisionSelect').value=created.id;toast(uiText(`已创建 Rev.${created.revision}，后续任务将以该版本为设计基线。`,`Created Rev.${created.revision}; subsequent tasks use it as the design baseline.`),'SUCCESS',6500)
  }catch(e){toast(e.message,'ERROR')}
}

async function refreshScenarioContext(project=null){
  const select=$('#taskScenarioRevisionSelect');if(!select)return;
  state.projectScenarioRevisionIndex=new Map();
  if(!state.activeProjectId){select.innerHTML=`<option value="">${uiText('临时工况（仅本任务）','Temporary scenario')}</option>`;state.taskScenarioRevisionId=null;return}
  try{
    project=project||await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`);
    const details=await Promise.all((project.scenarios||[]).map(s=>api(`/api/scenarios/${encodeURIComponent(s.id)}`)));
    const rows=[];details.forEach(s=>(s.revisions||[]).forEach(r=>{const rec={scenario:s,revision:r};state.projectScenarioRevisionIndex.set(r.id,rec);rows.push(rec)}));
    rows.sort((a,b)=>(b.revision.created_at||'').localeCompare(a.revision.created_at||''));
    select.innerHTML=`<option value="">${uiText('临时工况（仅本任务）','Temporary scenario for this task')}</option>`+rows.map(rec=>`<option value="${esc(rec.revision.id)}">${esc(rec.scenario.name)} · Rev.${esc(rec.revision.revision)}</option>`).join('');
    const wanted=state.taskScenarioRevisionId||localStorage.getItem(workflowLocalKey('scenario-revision'))||'';
    if(state.projectScenarioRevisionIndex.has(wanted)){select.value=wanted;state.taskScenarioRevisionId=wanted;applyScenarioRevision(wanted)}else{state.taskScenarioRevisionId=null}
    updateScenarioHint();
  }catch(e){console.warn('scenario context',e)}
}

function applyScenarioRevision(revisionId){
  const rec=state.projectScenarioRevisionIndex.get(revisionId);if(!rec)return;const s=rec.revision.scenario||{};
  const fields={ambient_temperature_c:'ambientTemp',radiation_temperature_c:'radiationTemp',initial_temperature_c:'initialTemp',initial_condition_mode:'initialCondition',cooling_type:'coolingType',coolant_inlet_temperature_c:'coolantTemp',coolant_flow_rate_lpm:'coolantFlow',external_air_speed_mps:'airSpeed',altitude_m:'altitude',fixed_temperature_c:'fixedTemp'};
  Object.entries(fields).forEach(([k,id])=>{const el=$(`#${id}`);if(el&&s[k]!==undefined&&s[k]!==null)el.value=s[k]});
  updateScenarioHint();
}
function updateScenarioHint(){const el=$('#taskScenarioHint');if(!el)return;const rec=state.projectScenarioRevisionIndex.get(state.taskScenarioRevisionId);el.textContent=rec?uiText(`已绑定 ${rec.scenario.name} · Rev.${rec.revision.revision}；当前页面修改将作为运行覆盖。`,`Bound to ${rec.scenario.name} · Rev.${rec.revision.revision}; page edits are runtime overrides.`):uiText('未绑定项目工况版本；当前边界条件只保存在本次任务快照中。','No project scenario revision is bound; current boundary conditions are stored only in this task snapshot.')}

async function saveCurrentScenarioRevision(){
  if(!state.activeProjectId)return toast(uiText('请先选择项目','Select a project first'),'WARNING');
  const name=$('#scenarioSaveName')?.value.trim();const current=state.projectScenarioRevisionIndex.get(state.taskScenarioRevisionId);try{
    let rev;if(current?.scenario?.id){rev=await api(`/api/scenarios/${encodeURIComponent(current.scenario.id)}/revisions`,{method:'POST',body:JSON.stringify({scenario:collectScenario(),notes:uiText('由任务编辑器保存','Saved from task builder')})})}
    else{if(!name)return toast(uiText('请输入工况名称','Enter a scenario name'),'WARNING');const bundle=await api('/api/scenarios/with-revision',{method:'POST',body:JSON.stringify({project_id:state.activeProjectId,name,revision:{scenario:collectScenario(),notes:uiText('由任务编辑器创建','Created from task builder')}})});rev=bundle.revision}
    state.taskScenarioRevisionId=rev.id;localStorage.setItem(workflowLocalKey('scenario-revision'),rev.id);await refreshScenarioContext();if($('#taskScenarioRevisionSelect'))$('#taskScenarioRevisionSelect').value=rev.id;updateScenarioHint();toast(uiText('项目工况版本已保存','Project scenario revision saved'),'SUCCESS');
  }catch(e){toast(e.message,'ERROR')}
}

async function refreshWorkflowReadiness(prefetched=null){
  const box=$('#workflowRibbon');if(!box)return;const q=new URLSearchParams();if(state.activeProjectId)q.set('project_id',state.activeProjectId);if(state.taskDesignRevisionId)q.set('design_revision_id',state.taskDesignRevisionId);q.set('analysis',$('#analysis')?.value||'emag');
  try{const r=prefetched||await api(`/api/workflow/readiness?${q.toString()}`);state.workflowReadiness=r;(r.steps||[]).forEach(step=>{const el=box.querySelector(`[data-workflow-step="${CSS.escape(step.id)}"]`);if(!el)return;el.classList.toggle('ready',Boolean(step.ready));el.classList.toggle('attention',Boolean(step.attention&&!step.ready));el.classList.toggle('pending',!step.ready&&!step.attention);const small=el.querySelector('small');if(small)small.textContent=step.detail||'';el.title=step.detail||''});box.dataset.submitReady=r.ready_to_submit?'true':'false'}catch(e){box.dataset.submitReady='false'}
}

const _collectPayloadV017=collectPayload;
collectPayload=function(){const p=_collectPayloadV017();p.project_id=state.activeProjectId||null;p.design_revision_id=state.taskDesignRevisionId||null;p.scenario_revision_id=state.taskScenarioRevisionId||null;p.solver_mode='motorcad';return p};

validateCurrent=async function(){
  const p=collectPayload();
  const v=await api('/api/validate',{method:'POST',body:JSON.stringify({project_id:p.project_id,design_revision_id:p.design_revision_id,scenario_revision_id:p.scenario_revision_id,template_id:p.template_id,solver_mode:p.solver_mode,analysis:p.analysis,parameters:p.parameters,explicit_parameter_ids:p.explicit_parameter_ids,automation_overrides:p.automation_overrides,materials:p.materials,solver_settings:p.solver_settings,scenario:p.scenario,requested_outputs:p.requested_outputs,experiment:p.experiment})});renderValidation(v);return v
};

const _changeActiveProjectV017=changeActiveProject;
changeActiveProject=async function(id){
  if(state.taskStream){try{state.taskStream.close()}catch{}state.taskStream=null}
  state.monitorTask=null;state.selectedTask=null;state.viewer=null;state.analytics=null;state.optimization=null;state.overlay=null;state.taskScenarioRevisionId=null;state.taskBaseRevision=null;state.taskDesignRevisionId=null;
  await _changeActiveProjectV017(id);
  if(state.routeOwnsLoadV025){updateTaskContextGate();return}
  await refreshProjectTaskContext();await refreshWorkflowReadiness();
};

const _useWorkspaceRevisionAsTaskV017=useWorkspaceRevisionAsTask;
useWorkspaceRevisionAsTask=async function(){await _useWorkspaceRevisionAsTaskV017();if(state.taskDesignRevisionId){localStorage.setItem(workflowLocalKey('design-revision'),state.taskDesignRevisionId);await refreshProjectTaskContext({autoLoad:false});if($('#taskDesignRevisionSelect'))$('#taskDesignRevisionSelect').value=state.taskDesignRevisionId}updateTaskRevisionHint();refreshWorkflowReadiness()};

const _showTabV017=showTab;
showTab=function(id){_showTabV017(id);if(id==='newTask')refreshProjectTaskContext();refreshWorkflowReadiness();updateTaskContextGate()};

$('#taskDesignRevisionSelect')?.addEventListener('change',async e=>{if(!e.target.value){state.taskDesignRevisionId=null;state.taskBaseRevision=null;localStorage.removeItem(workflowLocalKey('design-revision'));updateTaskRevisionHint();return refreshWorkflowReadiness()}await applyTaskDesignRevision(e.target.value)});
$('#taskScenarioRevisionSelect')?.addEventListener('change',e=>{state.taskScenarioRevisionId=e.target.value||null;if(state.taskScenarioRevisionId){localStorage.setItem(workflowLocalKey('scenario-revision'),state.taskScenarioRevisionId);applyScenarioRevision(state.taskScenarioRevisionId)}else{localStorage.removeItem(workflowLocalKey('scenario-revision'));updateScenarioHint()}});
$('#saveTaskDesignRevision')?.addEventListener('click',saveTaskDesignRevision);
$('#saveScenarioRevision')?.addEventListener('click',saveCurrentScenarioRevision);
$('#clearScenarioRevision')?.addEventListener('click',()=>{state.taskScenarioRevisionId=null;if($('#taskScenarioRevisionSelect'))$('#taskScenarioRevisionSelect').value='';localStorage.removeItem(workflowLocalKey('scenario-revision'));updateScenarioHint()});
$('#analysis')?.addEventListener('change',refreshWorkflowReadiness);
$('#taskName')?.addEventListener('input',e=>e.target.dataset.userEdited='1',{once:true});
$('#parameterGroups')?.addEventListener('input',updateTaskRevisionHint);$('#parameterGroups')?.addEventListener('change',updateTaskRevisionHint);$('#materialDb')?.addEventListener('input',updateTaskRevisionHint);$('#materialQuickGrid')?.addEventListener('change',()=>{updateTaskRevisionHint();if(typeof updateDomainCompositionV021==='function')updateDomainCompositionV021()});

// The task template is a derived property of Design Revision in production UI.
if($('#templateSelect'))$('#templateSelect').disabled=true;

function bindWorkflowRibbonNavigation(){
  const routes={motorcad:'setup',project:'projects',design:'workspace',qualification:'system',results:'resultViewer'};
  $$('#workflowRibbon [data-workflow-step]').forEach(el=>{el.tabIndex=0;el.setAttribute('role','button');const go=()=>showTab(routes[el.dataset.workflowStep]||'workspace');el.addEventListener('click',go);el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})});
}
function initWorkflowV017(){
  if(!state.health||!state.workspaceProjects){setTimeout(initWorkflowV017,120);return}
  bindWorkflowRibbonNavigation();refreshProjectTaskContext();refreshWorkflowReadiness();updateTaskContextGate();
  if(!state.workflowBootRouted){state.workflowBootRouted=true} // V0.18 always keeps Startup Configuration as the first page; project entry is explicit in Project Management.
}
setTimeout(initWorkflowV017,180);
