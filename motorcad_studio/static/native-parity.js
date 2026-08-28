/* V0.88-C Validation Fault Tree & Native Repair Orchestration. DOM names stay compatibility-stable. */
(function(){
  const q=(s,r=document)=>r.querySelector(s);
  const statusLabel=(s)=>({PASS:'已通过',FAIL:'未通过',NOT_RUN:'未执行',STALE:'已过期',BINDING_ERROR:'绑定错误',WARN:'需关注',QUALIFIED:'已固化',MATCH:'一致',DRIFT:'有漂移',PARTIAL:'证据不完整',UNAVAILABLE:'不可用',UNRESOLVED:'未解析',MISSING:'待采集',CLEAN:'干净',READY:'可安全修复',AWAITING_CONFIRMATION:'待确认',MANUAL:'需人工处理',BLOCKED:'已阻断',REPAIRED:'已修复'}[s]||s||'未执行');
  const statusClass=(s)=>String(s||'NOT_RUN').toLowerCase();
  let catalog=[];
  let bindingCatalog={};
  let busy=false;

  function checkTable(evidence){
    const checks=evidence?.checks||[];
    if(!checks.length)return '<div class="native-parity-empty-closure">尚无本机证据。</div>';
    return `<div class="native-parity-checks-closure">${checks.map(c=>`<div class="native-parity-check-closure ${statusClass(c.status)}"><span>${esc(statusLabel(c.status))}</span><div><b>${esc(c.id||'')}</b><small>${esc(c.message||'')}</small></div></div>`).join('')}</div>`;
  }

  function semanticProfile(templateId){
    return (bindingCatalog.semantic_authority?.profiles||[]).find(row=>row.template_id===templateId)||{status:'MISSING'};
  }

  function renderProfiles(){
    const box=q('#nativeParityProfilesClosure');if(!box)return;
    box.innerHTML=catalog.map(p=>{const latest=p.latest||{},score=latest.score||{},semantic=semanticProfile(p.template_id);return `<article class="native-parity-profile-closure ${latest.qualified?'qualified':''}">
      <div class="native-parity-profile-head-closure"><div><span class="eyebrow">${esc(String(p.id||'').toUpperCase())}</span><h3>${esc(p.label||p.id)}</h3><p>${esc(p.description||'')}</p></div><span class="native-parity-state-closure ${statusClass(latest.status)}">${esc(statusLabel(latest.status))}</span></div>
      <div class="native-parity-profile-meta-closure"><span>模板 <b>${esc(p.template_id||'-')}</b></span><span>Motor-CAD <b>${esc(p.target_motorcad_version||'-')}</b></span><span>PyMotorCAD <b>${esc(p.required_pymotorcad_version||'-')}</b></span><span>Native Binding <b>${esc(bindingCatalog.binding_version||'-')}</b></span><span>语义绑定 <b>${esc(statusLabel(semantic.status))}</b></span><span>原生模型回读 <b class="${statusClass(latest.native_model_readback_status)}">${esc(statusLabel(latest.native_model_readback_status||'UNAVAILABLE'))}</b></span><span>故障树/修复 <b class="${statusClass(latest.native_repair_plan_status)}">${esc(statusLabel(latest.native_repair_plan_status||'UNAVAILABLE'))}</b></span><span>Scope <b>${esc(String(latest.qualification_key||'-').slice(0,12))}</b></span><span>得分 <b>${score.percent??0}%</b></span></div>
      <div class="actions"><button type="button" class="primary" data-native-parity-run="${esc(p.id)}">运行原生逐项对照</button>${latest.run_id?`<button type="button" data-native-parity-detail="${esc(latest.run_id)}">查看证据</button>`:''}</div>
    </article>`}).join('')||'<div class="native-parity-empty-closure">未配置 Native Parity Profile。</div>';
  }

  function renderMatrix(matrix){
    const box=q('#nativeParityMatrixClosure');if(!box)return;
    const rows=matrix?.profiles||[];
    q('#nativeParityPercentClosure').textContent=`${Number(matrix?.native_workstation_qualification_percent||0).toFixed(1)}%`;
    const sem=bindingCatalog.semantic_authority||{};
    const readbackQualified=rows.filter(r=>r.native_model_readback_status==='QUALIFIED').length;
    const repairClean=rows.filter(r=>r.native_repair_orchestration_clean===true).length;
    const semText=`V0.88-A 精确语义绑定 ${sem.qualified_count||0}/${sem.golden_template_count||3} 个 Golden 模板已固化；V0.88-B 原生模型回读 ${readbackQualified}/${rows.length} 个 Profile 为 QUALIFIED；V0.88-C 故障树/修复编排 ${repairClean}/${rows.length} 个 Profile 为 CLEAN。`;
    q('#nativeParitySummaryClosure').textContent=(matrix?.complete?'当前资格 Profile 已全部通过语义绑定、原生模型回读、V0.88-C 故障树/修复编排和求解证据门禁。':`已通过 ${matrix?.qualified_profiles||0}/${matrix?.total_profiles||rows.length} 个 Profile；原生模型回读存在漂移/缺口，或 V0.88-C RepairPlan 非 CLEAN 时不会获得正式资格。`)+` ${semText}`;
    box.innerHTML=`<div class="table-wrap native-parity-table-closure"><table><thead><tr><th>Profile</th><th>模板</th><th>资格</th><th>原生模型回读</th><th>故障树 / RepairPlan</th><th>得分</th><th>最近证据</th><th>阻断项</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${esc(r.label||r.profile_id)}</b><small>${esc(r.profile_id)}</small></td><td>${esc(r.template_id||'-')}</td><td><span class="native-parity-state-closure ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span></td><td><span class="native-parity-state-closure ${statusClass(r.native_model_readback_status)}">${esc(statusLabel(r.native_model_readback_status||'UNAVAILABLE'))}</span><small>State ${r.native_model_design_state_hash?esc(String(r.native_model_design_state_hash).slice(0,12)):'-'} · ${esc(r.native_model_snapshot_phase||'-')}</small></td><td><span class="native-parity-state-closure ${statusClass(r.native_repair_plan_status)}">${esc(statusLabel(r.native_repair_plan_status||'UNAVAILABLE'))}</span><small>${esc(String(r.native_typed_fault_count??r.native_model_fault_count??0))} fault · ${esc(String(r.native_repair_attempt_count||0))} repair</small></td><td>${esc((r.score||{}).percent??0)}%</td><td>${r.run_id?`<button type="button" class="link-button" data-native-parity-detail="${esc(r.run_id)}">${esc(r.run_id)}</button>`:'-'}</td><td>${esc((r.blocking_checks||[]).join(', ')||'—')}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function refresh(){
    try{
      const [profiles,matrix,binding]=await Promise.all([api('/api/native-closure/profiles'),api('/api/native-closure/status'),api('/api/motorcad-native-binding/catalog')]);
      catalog=profiles.profiles||[];bindingCatalog=binding||{};renderProfiles();renderMatrix(matrix);
    }catch(e){const box=q('#nativeParityMatrixClosure');if(box)box.innerHTML=`<div class="issue ERROR">${esc(e.message)}</div>`}
  }

  async function runProfile(profileId){
    if(busy)return;busy=true;
    const out=q('#nativeParityRunStatusClosure');
    if(out)out.innerHTML=`<div class="preflight-running"><span class="spinner-dot"></span><b>正在目标 Motor-CAD 工作站执行 ${esc(profileId)} 原生逐项对照…</b><small>会启动真实 Motor-CAD、保存原生几何画面、绕组文件、MOT 与结果 CSV，并执行一次 EMag 求解。</small></div>`;
    try{
      const result=await api('/api/native-closure/run?timeout_s=1200',{method:'POST',body:JSON.stringify({profile_id:profileId})});
      if(out)out.innerHTML=`<div class="native-parity-result-closure ${result.qualified?'pass':'fail'}"><div><span class="native-parity-state-closure ${statusClass(result.status)}">${esc(statusLabel(result.status))}</span><h3>${esc(result.profile_label||profileId)} · ${(result.score||{}).percent||0}%</h3><p>${result.qualified?'当前 Profile 已满足语义绑定、原生模型回读、CLEAN RepairPlan 和求解证据门禁。':'仍有原生偏差或证据缺口；优先查看 V0.88-C typed fault tree 与 RepairPlan。'}</p></div>${checkTable(result)}</div>`;
      toast(result.qualified?'Native Closure 已通过':'Native Closure 存在阻断项',result.qualified?'SUCCESS':'WARNING',7000);
      await refresh();
    }catch(e){if(out)out.innerHTML=`<div class="issue ERROR">${esc(e.message)}</div>`;toast(e.message,'ERROR',9000)}finally{busy=false}
  }

  async function runSuite(){
    if(busy)return;busy=true;
    const out=q('#nativeParityRunStatusClosure');
    if(out)out.innerHTML='<div class="preflight-running"><span class="spinner-dot"></span><b>正在顺序执行 BPM / SPM / IPM / AFPM 原生资格套件…</b><small>每个 Profile 都在独立 Motor-CAD 子进程中运行，失败不会污染 Studio 主进程。</small></div>';
    try{
      const response=await api('/api/native-closure/run-suite?timeout_s=1200',{method:'POST',body:JSON.stringify({profile_ids:[],stop_on_failure:false})});
      const results=response.results||[];
      if(out)out.innerHTML=`<div class="native-parity-suite-result-closure"><h3>套件完成 · ${response.matrix?.qualified_profiles||0}/${response.matrix?.total_profiles||0} 通过</h3>${results.map(r=>`<div><span class="native-parity-state-closure ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span><b>${esc(r.profile_label||r.profile_id)}</b><span>${esc((r.blocking_checks||[]).join(', ')||'无阻断')}</span></div>`).join('')}</div>`;
      await refresh();toast(response.complete?'Native Closure 四模型全部通过':'原生一致性套件完成，仍有阻断项',response.complete?'SUCCESS':'WARNING',8000);
    }catch(e){if(out)out.innerHTML=`<div class="issue ERROR">${esc(e.message)}</div>`;toast(e.message,'ERROR',9000)}finally{busy=false}
  }

  async function openDetail(runId){
    try{
      const row=await api(`/api/native-closure/runs/${encodeURIComponent(runId)}`),evidence=row.evidence||{};
      const html=`<div class="native-parity-detail-closure"><div class="native-parity-detail-summary-closure"><span class="native-parity-state-closure ${statusClass(evidence.status)}">${esc(statusLabel(evidence.status))}</span><div><h3>${esc(evidence.profile_label||evidence.profile_id||'Native Closure')}</h3><p>${esc(runId)} · ${(evidence.score||{}).percent||0}% · ${esc(evidence.motorcad_target_version||'')}</p></div></div><div class="native-parity-evidence-actions-closure"><a class="button-like" target="_blank" rel="noopener" href="/api/native-closure/runs/${encodeURIComponent(runId)}/report">查看验收报告</a><a class="button-like" target="_blank" rel="noopener" href="/api/native-closure/runs/${encodeURIComponent(runId)}/native-model-snapshot">查看原生模型快照</a><a class="button-like" target="_blank" rel="noopener" href="/api/native-closure/runs/${encodeURIComponent(runId)}/native-repair-plan">查看故障树 / RepairPlan</a><a class="button-like primary" href="/api/native-closure/runs/${encodeURIComponent(runId)}/artifacts.zip">下载完整证据包</a></div>${checkTable(evidence)}<div class="definition-grid"><div><small>Evidence SHA-256</small><b>${esc(evidence.evidence_sha256||'-')}</b></div><div><small>Artifact directory</small><b>${esc(evidence.artifact_dir||row.artifact_dir||'-')}</b></div><div><small>PyMotorCAD</small><b>${esc(evidence.pymotorcad_version||'-')}</b></div><div><small>Native Binding</small><b>${esc(evidence.native_binding_plan?.identity?.binding_version||bindingCatalog.binding_version||'-')}</b></div><div><small>Binding Plan SHA-256</small><b>${esc(evidence.native_binding_plan_hash||'-')}</b></div><div><small>V0.88-B 原生模型回读</small><b>${esc(statusLabel(evidence.native_model_snapshot?.status||'UNAVAILABLE'))}</b></div><div><small>NativeModelSnapshot SHA-256</small><b>${esc(evidence.native_model_snapshot_hash||'-')}</b></div><div><small>Design-state SHA-256</small><b>${esc(evidence.native_model_design_state_hash||evidence.native_model_snapshot?.metadata?.design_state_hash||'-')}</b></div><div><small>Readback phase</small><b>${esc(evidence.native_model_snapshot_phase||evidence.native_model_snapshot?.phase||'-')}</b></div><div><small>V0.88-C typed fault tree</small><b>${esc(String(evidence.native_model_snapshot?.fault_records?.length||0))} 项</b></div><div><small>RepairPlan</small><b>${esc(statusLabel(evidence.native_model_snapshot?.repair_plan?.status||'UNAVAILABLE'))}</b></div><div><small>RepairPlan SHA-256</small><b>${esc(evidence.native_repair_plan_hash||evidence.native_model_snapshot?.metadata?.native_repair_plan_hash||'-')}</b></div><div><small>Fault-tree SHA-256</small><b>${esc(evidence.native_fault_tree_hash||evidence.native_model_snapshot?.repair_plan?.fault_tree_hash||'-')}</b></div><div><small>Repair attempts</small><b>${esc(String(evidence.native_repair_attempt_count??evidence.native_model_snapshot?.repair_history?.length??0))}</b></div><div><small>Model source</small><b>${esc(evidence.model_load?.type||'-')}</b></div><div><small>验收 MOT</small><b>${esc(evidence.verified_model_baseline?.artifact||'-')}</b></div><div><small>原生画面</small><b>${esc(String((evidence.checks||[]).find(c=>c.id==='native_geometry_screens')?.rows?.filter(r=>r.status==='PASS').length||0))} 张</b></div></div></div>`;
      if(window.StudioDialog?.sheet)await StudioDialog.sheet({title:'Native Closure 证据',html:html,width:'980px',actions:[{label:'关闭',value:false}]});
      else toast(`证据 ${runId}：${(evidence.blocking_checks||[]).join(', ')||'无阻断项'}`,'INFO',8000);
    }catch(e){toast(e.message,'ERROR')}
  }

  document.addEventListener('click',e=>{const run=e.target.closest('[data-native-parity-run]');if(run){runProfile(run.dataset.nativeParityRun);return}const detail=e.target.closest('[data-native-parity-detail]');if(detail){openDetail(detail.dataset.nativeParityDetail)}});
  q('#runNativeParitySuiteClosure')?.addEventListener('click',runSuite);
  q('#refreshNativeParityClosure')?.addEventListener('click',refresh);
  window.MCSNativeClosure={refresh,runProfile,runSuite};
  refresh();
})();
