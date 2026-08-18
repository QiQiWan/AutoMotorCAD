/* V0.21 engineering-domain model: Design / Scenario / Solver Profile / Output Profile / Run Configuration. */
(() => {
  const DESIGN_CATEGORIES=new Set(['topology','geometry','magnet','winding']);
  const scenarioFieldMap={
    shaft_speed_rpm:'scenarioSpeedV021',peak_current_a:'scenarioPeakCurrentV021',rms_current_a:'scenarioRmsCurrentV021',
    dc_bus_voltage_v:'scenarioDcBusV021',phase_advance_deg:'scenarioPhaseAdvanceV021',ambient_temperature_c:'ambientTemp',
    radiation_temperature_c:'radiationTemp',initial_temperature_c:'initialTemp',initial_condition_mode:'initialCondition',cooling_type:'coolingType',
    coolant_inlet_temperature_c:'coolantTemp',coolant_flow_rate_lpm:'coolantFlow',external_air_speed_mps:'airSpeed',altitude_m:'altitude',fixed_temperature_c:'fixedTemp'
  };
  state.simAssetsV021=state.simAssetsV021||{solver_profiles:[],output_profiles:[],run_configurations:[]};
  state.solverProfileRevisionIdV021=state.solverProfileRevisionIdV021||null;
  state.outputProfileRevisionIdV021=state.outputProfileRevisionIdV021||null;
  state.domainAssetKindV021=state.domainAssetKindV021||'scenarios';
  state.domainAssetIdV021=state.domainAssetIdV021||null;
  state.domainIntegrityV021=state.domainIntegrityV021||null;
  state.scenarioDirtyV021=false;state.solverProfileDirtyV021=false;state.outputProfileDirtyV021=false;state.solverProfileSaveBusyV022=false;state.outputProfileSaveBusyV022=false;

  function key(kind){return `motorcad-studio-v021-${kind}:${state.activeProjectId||'none'}`}
  function latest(profile){return (profile?.revisions||[]).slice().sort((a,b)=>Number(b.revision)-Number(a.revision))[0]||null}
  function findProfileRevision(collection,id){for(const p of collection||[])for(const r of p.revisions||[])if(r.id===id)return{profile:p,revision:r};return null}
  function textHash(v){return String(v||'').slice(0,12)}
  function parameterLabelV021(id){const label=state.registry?.parameters?.[id]?.label;return label?`${label}（${id}）`:id}
  function selectedOutputs(){return $$('[data-output]:checked').map(x=>x.dataset.output)}

  function ensureOperatingScenarioFields(){
    const panel=state.taskWizardPanelsV019?.[1]||[...document.querySelectorAll('#taskForm article.panel')].find(p=>(p.querySelector('h2')?.textContent||'').includes('工况'));
    const grid=panel?.querySelector('.form-grid');if(!grid||$('#scenarioSpeedV021'))return;
    const block=document.createElement('div');block.className='scenario-operating-block-v021 wide';block.innerHTML=`<div class="scenario-operating-head-v021"><div><span class="eyebrow">运行点 / Operating Point</span><b>电磁运行量属于 Scenario</b><small>转速、电流、电压和相位角不再写入 Design Revision。</small></div></div><div class="form-grid compact">
      <label>转速 / rpm<input id="scenarioSpeedV021" type="number" min="0" step="1" placeholder="由模板默认值初始化"></label>
      <label>峰值电流 / A<input id="scenarioPeakCurrentV021" type="number" min="0" step="any" placeholder="按运行点填写"></label>
      <label>RMS 电流 / A<input id="scenarioRmsCurrentV021" type="number" min="0" step="any" placeholder="可选"></label>
      <label>母线电压 / V<input id="scenarioDcBusV021" type="number" min="0" step="any" placeholder="按驱动器填写"></label>
      <label>电流超前角 / °<input id="scenarioPhaseAdvanceV021" type="number" min="-90" max="90" step="any" value="0"></label>
    </div>`;
    grid.before(block);
  }


  function ensureLegacyScenarioBannerV021(){
    const panel=state.taskWizardPanelsV019?.[1];if(!panel||$('#legacyScenarioSeedV021'))return;
    const bar=panel.querySelector('.scenario-context-bar');if(!bar)return;
    const node=document.createElement('div');node.id='legacyScenarioSeedV021';node.className='callout warning hidden';bar.insertAdjacentElement('afterend',node);
  }

  function renderLegacyScenarioBannerV021(){
    const box=$('#legacyScenarioSeedV021');if(!box)return;const seed=state.legacyScenarioSeedV021;
    if(!seed||state.taskScenarioRevisionId){box.classList.add('hidden');box.innerHTML='';return}
    const labels=Object.keys(seed.fields||{}).map(parameterLabelV021);
    box.classList.remove('hidden');box.innerHTML=`<b>已从 V0.20 及以前的 Design Revision 提取旧工况字段</b><span>${esc(labels.join('、'))} 已作为当前临时工况恢复。请确认后保存为 Scenario Revision；历史 Design Revision 不会被修改。</span>`;
  }

  function seedLegacyScenarioFromDesignV021(revisionId){
    ensureLegacyScenarioBannerV021();if(state.taskScenarioRevisionId){state.legacyScenarioSeedV021=null;renderLegacyScenarioBannerV021();return}
    const rec=state.projectRevisionIndex?.get(revisionId);const params=rec?.revision?.parameters||{};const fields={};
    Object.entries(scenarioFieldMap).forEach(([k,id])=>{if(!(k in params)||params[k]===null||params[k]===undefined)return;const el=$(`#${id}`);if(!el)return;el.value=params[k];fields[k]=params[k]});
    state.legacyScenarioSeedV021=Object.keys(fields).length?{revisionId,fields}:null;renderLegacyScenarioBannerV021();
  }

  const oldCollectScenario=collectScenario;
  collectScenario=function(){
    const s=oldCollectScenario();
    const read=id=>{const el=$(`#${id}`);if(!el||el.value==='')return null;const n=Number(el.value);return Number.isFinite(n)?n:null};
    return {...s,shaft_speed_rpm:read('scenarioSpeedV021'),peak_current_a:read('scenarioPeakCurrentV021'),rms_current_a:read('scenarioRmsCurrentV021'),dc_bus_voltage_v:read('scenarioDcBusV021'),phase_advance_deg:read('scenarioPhaseAdvanceV021')};
  };

  applyScenarioRevision=function(revisionId){
    const rec=state.projectScenarioRevisionIndex.get(revisionId);if(!rec)return;const s=rec.revision.scenario||{};state.scenarioDirtyV021=false;
    Object.entries(scenarioFieldMap).forEach(([k,id])=>{const el=$(`#${id}`);if(el&&s[k]!==undefined&&s[k]!==null)el.value=s[k]});
    updateScenarioHint();updateDomainCompositionV021();window.MCSModelGate?.invalidate?.('工况版本已改变');
  };

  function applyTemplateScenarioDefaultsV021(force=false){
    const d=state.selectedTemplate?.defaults||{};if(state.taskScenarioRevisionId&&!force)return;
    const map={shaft_speed_rpm:'scenarioSpeedV021',peak_current_a:'scenarioPeakCurrentV021',rms_current_a:'scenarioRmsCurrentV021',dc_bus_voltage_v:'scenarioDcBusV021',phase_advance_deg:'scenarioPhaseAdvanceV021'};
    Object.entries(map).forEach(([k,id])=>{const el=$(`#${id}`);if(!el||d[k]===undefined)return;if(force||el.value==='')el.value=d[k]});
  }

  function ensureDomainCompositionStripV021(){
    const context=state.taskWizardPanelsV019?.[0];if(!context||$('#domainCompositionV021'))return;
    const node=document.createElement('div');node.id='domainCompositionV021';node.className='domain-composition-v021';node.innerHTML=`<div class="domain-composition-title-v021"><div><span class="eyebrow">V0.21 工程对象组合</span><b>Task 将执行一个不可变 Run Configuration</b><small>Design、Scenario、Solver Profile、Output Profile 分别版本化，提交时冻结组合。</small></div><button type="button" id="openSimulationAssetsV021">管理配置资产</button></div><div class="domain-composition-grid-v021" id="domainCompositionGridV021"></div>`;
    const notice=context.querySelector('#projectContextNotice');(notice||context.querySelector('.form-grid'))?.insertAdjacentElement(notice?'beforebegin':'afterend',node);
    $('#openSimulationAssetsV021')?.addEventListener('click',()=>showTab('simulationAssets'));
  }

  function ensureScenarioVersionActionsV021(){
    const save=$('#saveScenarioRevision');if(!save)return;save.textContent='保存为当前工况的新版本';
    if(!$('#forkScenarioV021')){const fork=document.createElement('button');fork.id='forkScenarioV021';fork.type='button';fork.textContent='另存为新工况';save.insertAdjacentElement('afterend',fork);fork.addEventListener('click',forkScenarioV021)}
  }

  async function forkScenarioV021(){
    if(!state.activeProjectId)return toast('请先进入项目','WARNING');const name=$('#scenarioSaveName')?.value.trim();if(!name)return toast('请输入新工况名称','WARNING');
    try{const bundle=await api('/api/scenarios/with-revision',{method:'POST',body:JSON.stringify({project_id:state.activeProjectId,name,revision:{scenario:collectScenario(),notes:'V0.21 由仿真配置向导另存为新工况'}})});const rev=bundle.revision;state.taskScenarioRevisionId=rev.id;state.scenarioDirtyV021=false;state.legacyScenarioSeedV021=null;localStorage.setItem(workflowLocalKey('scenario-revision'),rev.id);await refreshScenarioContext();if($('#taskScenarioRevisionSelect'))$('#taskScenarioRevisionSelect').value=rev.id;updateScenarioHint();updateDomainCompositionV021();toast(`已创建工况 ${name} · Rev.${rev.revision}`,'SUCCESS')}catch(e){toast(e.message,'ERROR',7000)}
  }

  function ensureProfileControlsV021(){
    const context=state.taskWizardPanelsV019?.[0];if(context&&!$('#solverProfileRevisionSelectV021')){
      const form=context.querySelector('.form-grid');form?.insertAdjacentHTML('beforeend',`<div class="profile-binding-v021 wide"><div><span class="eyebrow">求解配置 / Solver Profile</span><label>版本<select id="solverProfileRevisionSelectV021"></select></label></div><div><label>配置名称<input id="solverProfileNameV021" value="Motor-CAD 电磁标准"></label><div class="actions"><button type="button" id="saveSolverProfileV021">保存为当前配置的新版本</button><button type="button" id="forkSolverProfileV021">另存为新求解配置</button></div><small>配置名称用于“另存为新配置”。</small><small id="solverProfileStatusV021"></small></div></div>`);
    }
    const output=state.taskWizardPanelsV019?.[3];if(output&&!$('#outputProfileRevisionSelectV021')){
      output.querySelector('.section-head')?.insertAdjacentHTML('afterend',`<div class="profile-binding-v021 output"><div><span class="eyebrow">输出配置 / Output Profile</span><label>版本<select id="outputProfileRevisionSelectV021"></select></label></div><div><label>配置名称<input id="outputProfileNameV021" value="标准结果集"></label><div class="actions"><button type="button" id="saveOutputProfileV021">保存为当前配置的新版本</button><button type="button" id="forkOutputProfileV021">另存为新输出配置</button></div><small>配置名称用于“另存为新配置”。</small><small id="outputProfileStatusV021"></small></div></div>`);
    }
    $('#solverProfileRevisionSelectV021')?.addEventListener('change',e=>applySolverProfileV021(e.target.value));
    $('#outputProfileRevisionSelectV021')?.addEventListener('change',e=>applyOutputProfileV021(e.target.value));
    $('#saveSolverProfileV021')?.addEventListener('click',saveSolverProfileV021);
    $('#forkSolverProfileV021')?.addEventListener('click',()=>saveSolverProfileV021({fork:true}));
    $('#saveOutputProfileV021')?.addEventListener('click',saveOutputProfileV021);
    $('#forkOutputProfileV021')?.addEventListener('click',()=>saveOutputProfileV021({fork:true}));
  }

  async function loadSimulationAssetsV021({applyDefaults=true,routeCtx=null}={}){
    if(!state.activeProjectId)return;
    try{
      const options=routeCtx?.signal?{signal:routeCtx.signal}:{};const [assets,integrity]=await Promise.all([api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/simulation-assets`,options),api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/domain-integrity`,options)]);
      if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;state.simAssetsV021=assets;state.domainIntegrityV021=integrity;renderDomainIntegrityV021();
      renderProfileSelectorsV021(applyDefaults);if(document.querySelector('#simulationAssets.tab.active'))await renderDomainAssetsPageV021();
    }catch(e){if(window.MCSPageRuntime?.isAbortError?.(e))return;console.warn('V0.21 simulation assets',e);toast(`仿真配置资产加载失败：${e.message}`,'WARNING',6500)}
  }

  function renderProfileSelectorsV021(applyDefaults=true){
    const s=$('#solverProfileRevisionSelectV021'),o=$('#outputProfileRevisionSelectV021');
    if(s){const rows=[];(state.simAssetsV021.solver_profiles||[]).forEach(p=>(p.revisions||[]).forEach(r=>rows.push({p,r})));s.innerHTML=rows.map(({p,r})=>`<option value="${esc(r.id)}">${esc(p.name)} · Rev.${esc(r.revision)} · ${esc(r.analysis)}</option>`).join('');let wanted=state.solverProfileRevisionIdV021||localStorage.getItem(key('solver-profile'))||rows[0]?.r.id||'';if(!rows.some(x=>x.r.id===wanted))wanted=rows[0]?.r.id||'';s.value=wanted;if(applyDefaults&&wanted&&!state.solverProfileRevisionIdV021)applySolverProfileV021(wanted,{silent:true})}
    if(o){const rows=[];(state.simAssetsV021.output_profiles||[]).forEach(p=>(p.revisions||[]).forEach(r=>rows.push({p,r})));o.innerHTML=rows.map(({p,r})=>`<option value="${esc(r.id)}">${esc(p.name)} · Rev.${esc(r.revision)} · ${(r.requested_outputs||[]).length||'推荐'} 项</option>`).join('');let wanted=state.outputProfileRevisionIdV021||localStorage.getItem(key('output-profile'))||rows[0]?.r.id||'';if(!rows.some(x=>x.r.id===wanted))wanted=rows[0]?.r.id||'';o.value=wanted;if(applyDefaults&&wanted&&!state.outputProfileRevisionIdV021)applyOutputProfileV021(wanted,{silent:true})}
  }

  function applySolverProfileV021(id,{silent=false}={}){
    const rec=findProfileRevision(state.simAssetsV021.solver_profiles,id);if(!rec)return;
    state.solverProfileRevisionIdV021=id;state.solverProfileDirtyV021=false;localStorage.setItem(key('solver-profile'),id);
    const r=rec.revision;if($('#analysis'))$('#analysis').value=r.analysis||'emag';if($('#qualityProfile'))$('#qualityProfile').value=r.quality_profile||'standard';
    state.solverSettings=JSON.parse(JSON.stringify(r.solver_settings||{}));state.expertOverrides=JSON.parse(JSON.stringify(r.automation_overrides||{}));
    try{renderSolverControls();renderExpertParameters()}catch{}
    const st=$('#solverProfileStatusV021');if(st)st.textContent=`已绑定 ${rec.profile.name} · Rev.${r.revision} · ${textHash(r.content_hash)}`;
    updateDomainCompositionV021();window.MCSModelGate?.invalidate?.('求解配置已改变');if(!silent)toast(`已载入求解配置 ${rec.profile.name} Rev.${r.revision}`,'INFO',4500);
  }

  function applyOutputProfileV021(id,{silent=false}={}){
    const rec=findProfileRevision(state.simAssetsV021.output_profiles,id);if(!rec)return;
    state.outputProfileRevisionIdV021=id;state.outputProfileDirtyV021=false;localStorage.setItem(key('output-profile'),id);
    const outputs=rec.revision.requested_outputs||[];if(outputs.length)$$('[data-output]').forEach(x=>x.checked=outputs.includes(x.dataset.output));else if(typeof applyDefaultOutputs==='function')applyDefaultOutputs();
    const st=$('#outputProfileStatusV021');if(st)st.textContent=`已绑定 ${rec.profile.name} · Rev.${rec.revision.revision} · ${outputs.length?outputs.length+' 项输出':'模板推荐输出'}`;
    updateTaskPreview();updateDomainCompositionV021();window.MCSModelGate?.invalidate?.('输出配置已改变');if(!silent)toast(`已载入输出配置 ${rec.profile.name} Rev.${rec.revision.revision}`,'INFO',4500);
  }

  async function saveSolverProfileV021({fork=false}={}){
    if(state.solverProfileSaveBusyV022)return;if(!state.activeProjectId)return toast('请先进入项目','WARNING');const selected=findProfileRevision(state.simAssetsV021.solver_profiles,state.solverProfileRevisionIdV021);const p=collectPayload();const button=fork?$('#forkSolverProfileV021'):$('#saveSolverProfileV021');
    state.solverProfileSaveBusyV022=true;if(button)button.disabled=true;
    try{
      let r;if(fork||!selected){const name=$('#solverProfileNameV021')?.value.trim()||'Motor-CAD 求解配置';const bundle=await api('/api/solver-profiles/with-revision',{method:'POST',body:JSON.stringify({project_id:state.activeProjectId,name,revision:{analysis:p.analysis,quality_profile:p.quality_profile,solver_settings:p.solver_settings,automation_overrides:p.automation_overrides,solver_timeout_s:p.solver_timeout_s||null,notes:'由仿真配置向导创建'}})});r=bundle.revision}
      else r=await api(`/api/solver-profiles/${encodeURIComponent(selected.profile.id)}/revisions`,{method:'POST',body:JSON.stringify({analysis:p.analysis,quality_profile:p.quality_profile,solver_settings:p.solver_settings,automation_overrides:p.automation_overrides,solver_timeout_s:p.solver_timeout_s||null,notes:'由仿真配置向导保存'})});
      state.solverProfileRevisionIdV021=r.id;state.solverProfileDirtyV021=false;await loadSimulationAssetsV021({applyDefaults:false});$('#solverProfileRevisionSelectV021').value=r.id;updateDomainCompositionV021();toast(`求解配置已保存为 Rev.${r.revision}`,'SUCCESS');
    }catch(e){toast(e.message,'ERROR',7000)}finally{state.solverProfileSaveBusyV022=false;if(button)button.disabled=false}
  }

  async function saveOutputProfileV021({fork=false}={}){
    if(state.outputProfileSaveBusyV022)return;if(!state.activeProjectId)return toast('请先进入项目','WARNING');const selected=findProfileRevision(state.simAssetsV021.output_profiles,state.outputProfileRevisionIdV021);const button=fork?$('#forkOutputProfileV021'):$('#saveOutputProfileV021');
    state.outputProfileSaveBusyV022=true;if(button)button.disabled=true;
    try{
      let r;if(fork||!selected){const name=$('#outputProfileNameV021')?.value.trim()||'结果输出配置';const bundle=await api('/api/output-profiles/with-revision',{method:'POST',body:JSON.stringify({project_id:state.activeProjectId,name,revision:{requested_outputs:selectedOutputs(),notes:'由仿真配置向导创建'}})});r=bundle.revision}
      else r=await api(`/api/output-profiles/${encodeURIComponent(selected.profile.id)}/revisions`,{method:'POST',body:JSON.stringify({requested_outputs:selectedOutputs(),notes:'由仿真配置向导保存'})});
      state.outputProfileRevisionIdV021=r.id;state.outputProfileDirtyV021=false;await loadSimulationAssetsV021({applyDefaults:false});$('#outputProfileRevisionSelectV021').value=r.id;updateDomainCompositionV021();toast(`输出配置已保存为 Rev.${r.revision}`,'SUCCESS');
    }catch(e){toast(e.message,'ERROR',7000)}finally{state.outputProfileSaveBusyV022=false;if(button)button.disabled=false}
  }

  function renderDomainIntegrityV021(){
    const box=$('#domainIntegrityV021');if(!box)return;const d=state.domainIntegrityV021;if(!d){box.classList.add('hidden');return}
    const legacy=Number(d.legacy_design_revision_count||0),tasks=Number(d.legacy_task_count||0);box.classList.remove('hidden');box.classList.toggle('clean',d.status==='CLEAN');
    box.innerHTML=d.status==='CLEAN'?`<div><b>领域数据检查通过</b><span>新 Design、Scenario、求解配置、输出配置与 Run Configuration 的边界一致。</span></div>`:`<div><b>检测到 V0.21 之前的历史对象</b><span>${legacy} 个旧 Design Revision 仍包含运行点字段；${tasks} 个历史 Task 尚无 Run Configuration。历史对象保持不可变，继续设计时创建新 Revision 即可完成自然迁移。</span></div><button type="button" id="showLegacyDomainRowsV021">查看历史对象</button>`;
    $('#showLegacyDomainRowsV021')?.addEventListener('click',()=>StudioDialog.sheet({title:'V0.21 历史领域数据',html:`<p>${esc(d.guidance||'')}</p><div class="revision-stack-v021">${(d.legacy_design_revisions||[]).map(x=>`<div class="revision-card-v021"><b>${esc(x.design_name)} · Rev.${esc(x.revision)}</b><small>${esc(x.revision_id)}</small><p>旧 Design 中的工况字段：${esc((x.misplaced_scenario_fields||[]).map(parameterLabelV021).join('、'))}</p></div>`).join('')||'<p>没有旧 Design Revision。</p>'}</div><p>无 Run Configuration 的历史 Task：<b>${esc(tasks)}</b></p>`,actions:[{label:'关闭',value:true,primary:true}],width:'680px'}));
  }

  function designOverrideCountV021(){return typeof taskOverrideCount==='function'?taskOverrideCount():$$('[data-param-field].changed [data-param]').length}

  function updateDomainCompositionV021(){
    renderLegacyScenarioBannerV021();
    const saveScenario=$('#saveScenarioRevision');if(saveScenario)saveScenario.textContent=state.taskScenarioRevisionId?'保存为当前工况的新版本':'保存为项目工况';
    const grid=$('#domainCompositionGridV021');if(!grid)return;const d=state.projectRevisionIndex?.get(state.taskDesignRevisionId),s=state.projectScenarioRevisionIndex?.get(state.taskScenarioRevisionId),sp=findProfileRevision(state.simAssetsV021.solver_profiles,state.solverProfileRevisionIdV021),op=findProfileRevision(state.simAssetsV021.output_profiles,state.outputProfileRevisionIdV021);
    const cards=[
      ['Design Revision',d?`${d.design.name} · Rev.${d.revision.revision}${designOverrideCountV021()?` · ${designOverrideCountV021()} 项临时覆盖`:''}`:'未选择',d?'locked':'missing'],
      ['Scenario Revision',s?`${s.scenario.name} · Rev.${s.revision.revision}${state.scenarioDirtyV021?' · 当前页有临时覆盖':''}`:'临时工况（建议保存）',s?'locked':'warning'],
      ['Solver Profile 基线',sp?`${sp.profile.name} · Rev.${sp.revision.revision}${state.solverProfileDirtyV021?' · 当前页有临时覆盖':''}`:'未绑定',sp?'locked':'missing'],
      ['Output Profile 基线',op?`${op.profile.name} · Rev.${op.revision.revision}${state.outputProfileDirtyV021?' · 当前页有临时覆盖':''}`:'未绑定',op?'locked':'missing'],
    ];grid.innerHTML=cards.map(([k,v,t])=>`<div class="domain-object-card-v021 ${t}"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')+`<div class="domain-arrow-v021">→</div><div class="domain-object-card-v021 run"><span>Run Configuration</span><b>提交时冻结</b><small>Task 只引用该不可变快照</small></div>`;
  }

  const oldCollectPayload=collectPayload;
  collectPayload=function(){const p=oldCollectPayload();p.solver_profile_revision_id=state.solverProfileRevisionIdV021||null;p.output_profile_revision_id=state.outputProfileRevisionIdV021||null;p.run_configuration_id=null;return p};

  function markSolverDirtyV021(){if(!state.solverProfileRevisionIdV021)return;state.solverProfileDirtyV021=true;const el=$('#solverProfileStatusV021');if(el)el.textContent='当前设置已偏离已保存版本；提交前建议保存为新的 Solver Profile Revision。';updateDomainCompositionV021();}
  function markOutputDirtyV021(){if(!state.outputProfileRevisionIdV021)return;state.outputProfileDirtyV021=true;const el=$('#outputProfileStatusV021');if(el)el.textContent='输出选择已偏离已保存版本；建议保存为新的 Output Profile Revision。';updateDomainCompositionV021();}

  async function renderDomainAssetsPageV021(routeCtx=null){
    if(!state.activeProjectId)return;const options=routeCtx?.signal?{signal:routeCtx.signal}:{};const project=await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`,options);if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;const scenarios=await Promise.all((project.scenarios||[]).map(x=>api(`/api/scenarios/${encodeURIComponent(x.id)}`,options)));if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;const assets=state.simAssetsV021||{};const kind=state.domainAssetKindV021||'scenarios';
    const tabs=$$('#domainAssetTabsV021 [data-domain-asset]');tabs.forEach(b=>b.classList.toggle('active',b.dataset.domainAsset===kind));
    const metrics=$('#domainAssetMetricsV021');if(metrics)metrics.innerHTML=[['工况',scenarios.length],['求解配置',(assets.solver_profiles||[]).length],['输出配置',(assets.output_profiles||[]).length],['运行配置',(assets.run_configurations||[]).length]].map(([k,v])=>`<div class="metric-card"><span>${k}</span><b>${v}</b></div>`).join('');
    const list=$('#domainAssetListV021');const detail=$('#domainAssetDetailV021');if(!list||!detail)return;
    let rows=[];
    if(kind==='scenarios')rows=scenarios.map(x=>({id:x.id,title:x.name,meta:`${(x.revisions||[]).length} 个版本`,data:x,type:'scenario'}));
    if(kind==='solver-profiles')rows=(assets.solver_profiles||[]).map(x=>({id:x.id,title:x.name,meta:`${(x.revisions||[]).length} 个版本`,data:x,type:'solver'}));
    if(kind==='output-profiles')rows=(assets.output_profiles||[]).map(x=>({id:x.id,title:x.name,meta:`${(x.revisions||[]).length} 个版本`,data:x,type:'output'}));
    if(kind==='run-configurations')rows=(assets.run_configurations||[]).map(x=>({id:x.id,title:x.name,meta:`${x.task_count||0} 个 Task · ${textHash(x.content_hash)}`,data:x,type:'run'}));
    list.innerHTML=rows.length?rows.map(r=>`<button type="button" class="domain-asset-row-v021" data-domain-row="${esc(r.id)}"><div><b>${esc(r.title)}</b><small>${esc(r.id)}</small></div><span>${esc(r.meta)}</span></button>`).join(''):`<div class="workspace-empty compact"><b>暂无资产</b><span>可在“配置计算”向导中保存工况、求解配置和输出配置。</span></div>`;
    $$('[data-domain-row]').forEach(b=>b.addEventListener('click',()=>{const row=rows.find(x=>x.id===b.dataset.domainRow);if(row){state.domainAssetIdV021=row.id;renderDomainAssetDetailV021(row,detail);if(window.MCSRouter&&!MCSRouter.isRouting())MCSRouter.setUrl(MCSRouter.routeForTab('simulationAssets'))}}));const selected=rows.find(x=>x.id===state.domainAssetIdV021)||rows[0];if(selected){state.domainAssetIdV021=selected.id;renderDomainAssetDetailV021(selected,detail)}else state.domainAssetIdV021=null;
  }

  async function replayRunConfigurationV021(run){
    const ok=await StudioDialog.confirm({title:'重新执行不可变运行配置',html:`<p>将创建新的 Task，并严格复用 <b>${esc(run.id)}</b> 的冻结参数、工况、求解配置和输出配置。</p><p>运行配置本身不会被修改。</p>`,confirmText:'创建重算任务',cancelText:'取消'});if(!ok)return;
    try{const r=await api(`/api/run-configurations/${encodeURIComponent(run.id)}/tasks`,{method:'POST',body:JSON.stringify({name:`${run.name||'运行配置'} · 重算`})});toast(`已创建重算任务 ${r.task_id}`,'SUCCESS');state.monitorTask=r.task_id;if(window.MCSRouter?.navigate)MCSRouter.navigate(`/app/projects/${encodeURIComponent(state.activeProjectId)}/simulation/monitor/${encodeURIComponent(r.task_id)}`);else{showTab('monitor');openMonitorTask(r.task_id)}}catch(e){toast(`重算任务创建失败：${e.message}`,'ERROR',8000)}
  }

  function renderDomainAssetDetailV021(row,box){
    if(row.type==='run'){const s=row.data.snapshot||{},c=s.domain_contract||{},b=s.bindings||{};box.innerHTML=`<span class="eyebrow">不可变运行配置</span><h3>${esc(row.data.name)}</h3><div class="traceability-badge-v021 ${esc(String(row.data.traceability_status||'').toLowerCase())}">${esc(row.data.traceability_status||c.traceability_status||'PARTIAL_INLINE')} · ${esc(c.override_count||0)} 项运行覆盖</div><div class="property-grid"><span>ID</span><b>${esc(row.data.id)}</b><span>内容哈希</span><b>${esc(row.data.content_hash)}</b><span>Design Revision</span><b>${esc(s.design_revision_id||'-')}</b><span>Scenario Revision</span><b>${esc(s.scenario_revision_id||'临时快照')}</b><span>Solver Profile 基线</span><b>${esc(s.solver_profile_revision_id||'临时快照')}</b><span>Output Profile 基线</span><b>${esc(s.output_profile_revision_id||'临时快照')}</b><span>分析</span><b>${esc(s.analysis||'-')}</b><span>Task 引用</span><b>${esc(row.data.task_count||0)}</b></div><div class="actions"><button type="button" id="replayRunConfigV021" class="primary">按此冻结配置重新计算</button></div><details open><summary>基线与运行覆盖</summary><pre class="code-block">${esc(JSON.stringify(b,null,2))}</pre></details><details><summary>完整冻结快照</summary><pre class="code-block">${esc(JSON.stringify(s,null,2))}</pre></details>`;$('#replayRunConfigV021')?.addEventListener('click',()=>replayRunConfigurationV021(row.data));return}
    const revisions=(row.data.revisions||[]);box.innerHTML=`<span class="eyebrow">版本化配置资产</span><h3>${esc(row.data.name)}</h3><p>${esc(row.data.id)}</p><div class="revision-stack-v021">${revisions.map(r=>`<div class="revision-card-v021"><div><b>Rev.${esc(r.revision)}</b><small>${esc(r.id)} · ${esc(formatDate(r.created_at)||'')}</small></div><code>${esc(textHash(r.content_hash))}</code>${row.type==='scenario'?`<p>${esc([r.scenario?.shaft_speed_rpm!=null?`转速 ${r.scenario.shaft_speed_rpm} rpm`:'',r.scenario?.peak_current_a!=null?`峰值电流 ${r.scenario.peak_current_a} A`:'',`环境 ${r.scenario?.ambient_temperature_c??25} °C`,r.scenario?.cooling_type||''].filter(Boolean).join(' · '))}</p>`:row.type==='solver'?`<p>${esc(`${r.analysis} · ${r.quality_profile} · ${Object.keys(r.solver_settings||{}).length} 项求解设置`)}</p>`:`<p>${esc(`${(r.requested_outputs||[]).length} 项输出`)}</p>`}</div>`).join('')}</div>`;
  }

  function bindDomainAssetTabsV021(){
    $$('#domainAssetTabsV021 [data-domain-asset]').forEach(b=>b.addEventListener('click',async()=>{state.domainAssetKindV021=b.dataset.domainAsset;state.domainAssetIdV021=null;await renderDomainAssetsPageV021();if(window.MCSRouter&&!MCSRouter.isRouting())MCSRouter.setUrl(`/app/projects/${encodeURIComponent(state.activeProjectId)}/simulation/assets/${encodeURIComponent(state.domainAssetKindV021)}`)}));
  }

  function upgradeCopyV021(){
    const drawer=$('#taskOverrideDrawer');if(drawer){const summary=drawer.querySelector('summary b');if(summary)summary.textContent='高级：本次运行临时覆盖 Design Revision';const small=drawer.querySelector('summary small');if(small)small.textContent='这里只做临时试算。长期槽极、几何、绕组和材料修改应回“设计”生成新 Revision。'}
    const h=$('#taskWizardHeader p');if(h)h.textContent='计算由 Design Revision + Scenario Revision + Solver Profile Revision + Output Profile Revision 组成；提交时冻结为不可变 Run Configuration。';
    const scenario=state.taskWizardPanelsV019?.[1];if(scenario){const p=scenario.querySelector('.section-head p');if(p)p.textContent='保存运行点、环境和冷却边界。转速、电流、电压等运行量属于 Scenario，不进入 Design Revision。'}
  }

  function initV021(){
    if(!state.taskWizardPanelsV019?.length){setTimeout(initV021,100);return}
    ensureOperatingScenarioFields();ensureScenarioVersionActionsV021();ensureDomainCompositionStripV021();ensureProfileControlsV021();ensureLegacyScenarioBannerV021();upgradeCopyV021();bindDomainAssetTabsV021();applyTemplateScenarioDefaultsV021();
    const previousApplyTaskDesignRevisionV021=applyTaskDesignRevision;applyTaskDesignRevision=async function(revisionId,opts={}){const out=await previousApplyTaskDesignRevisionV021(revisionId,opts);seedLegacyScenarioFromDesignV021(revisionId);updateDomainCompositionV021();return out};
    if(state.taskDesignRevisionId)seedLegacyScenarioFromDesignV021(state.taskDesignRevisionId);
    loadSimulationAssetsV021();updateDomainCompositionV021();
    $('#analysis')?.addEventListener('change',markSolverDirtyV021);$('#qualityProfile')?.addEventListener('change',markSolverDirtyV021);
    $('#expertParamFields')?.addEventListener('change',markSolverDirtyV021);$('#solverControlFields')?.addEventListener('change',markSolverDirtyV021);$('#solverSettings')?.addEventListener('change',markSolverDirtyV021);
    $('#outputFields')?.addEventListener('change',markOutputDirtyV021);
    $('#taskDesignRevisionSelect')?.addEventListener('change',()=>setTimeout(()=>{applyTemplateScenarioDefaultsV021();updateDomainCompositionV021()},0));
    $('#taskScenarioRevisionSelect')?.addEventListener('change',()=>{if(state.taskScenarioRevisionId)state.legacyScenarioSeedV021=null;setTimeout(updateDomainCompositionV021,0)});
    $('#clearScenarioRevision')?.addEventListener('click',()=>{state.scenarioDirtyV021=false;setTimeout(updateDomainCompositionV021,0)});
    Object.values(scenarioFieldMap).forEach(id=>$(`#${id}`)?.addEventListener('input',()=>{if(state.taskScenarioRevisionId)state.scenarioDirtyV021=true;updateDomainCompositionV021();window.MCSModelGate?.invalidate?.('工况参数已改变')}));
    $('#parameterGroups')?.addEventListener('input',()=>updateDomainCompositionV021());
    const oldShowTab=showTab;showTab=function(id){oldShowTab(id);if(state.routeOwnsLoadV025)return;if(id==='simulationAssets')loadSimulationAssetsV021({applyDefaults:false}).then(renderDomainAssetsPageV021);if(id==='newTask'){ensureOperatingScenarioFields();loadSimulationAssetsV021();updateDomainCompositionV021()}};
    const oldChange=changeActiveProject;changeActiveProject=async function(id){state.solverProfileRevisionIdV021=null;state.outputProfileRevisionIdV021=null;state.domainAssetIdV021=null;state.scenarioDirtyV021=false;await oldChange(id);if(state.routeOwnsLoadV025)return;await loadSimulationAssetsV021();updateDomainCompositionV021()};
    // Re-run project context after operating fields exist so legacy Scenario revisions can populate them.
    if(state.activeProjectId)refreshProjectTaskContext({autoLoad:true});
  }
  window.MCSDomainV025={
    async mountAssets(routeCtx=null){ensureOperatingScenarioFields();await loadSimulationAssetsV021({applyDefaults:false,routeCtx});if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;await renderDomainAssetsPageV021(routeCtx)},
    async mountTaskSetup(routeCtx=null){ensureOperatingScenarioFields();await loadSimulationAssetsV021({routeCtx});if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;updateDomainCompositionV021()},
    renderAssets:renderDomainAssetsPageV021,
    updateComposition:updateDomainCompositionV021,
  };
  setTimeout(initV021,260);
})();
