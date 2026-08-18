/* V0.68 Motor-CAD Native Parity Qualification */
(function(){
  const q=(s,r=document)=>r.querySelector(s);
  const statusLabel=(s)=>({PASS:'已通过',FAIL:'未通过',NOT_RUN:'未执行',WARN:'需关注'}[s]||s||'未执行');
  const statusClass=(s)=>String(s||'NOT_RUN').toLowerCase();
  let catalog=[];
  let busy=false;

  function checkTable(evidence){
    const checks=evidence?.checks||[];
    if(!checks.length)return '<div class="native-parity-empty-v068">尚无本机证据。</div>';
    return `<div class="native-parity-checks-v068">${checks.map(c=>`<div class="native-parity-check-v068 ${statusClass(c.status)}"><span>${esc(statusLabel(c.status))}</span><div><b>${esc(c.id||'')}</b><small>${esc(c.message||'')}</small></div></div>`).join('')}</div>`;
  }

  function renderProfiles(){
    const box=q('#nativeParityProfilesV068');if(!box)return;
    box.innerHTML=catalog.map(p=>{const latest=p.latest||{},score=latest.score||{};return `<article class="native-parity-profile-v068 ${latest.qualified?'qualified':''}">
      <div class="native-parity-profile-head-v068"><div><span class="eyebrow">${esc(String(p.id||'').toUpperCase())}</span><h3>${esc(p.label||p.id)}</h3><p>${esc(p.description||'')}</p></div><span class="native-parity-state-v068 ${statusClass(latest.status)}">${esc(statusLabel(latest.status))}</span></div>
      <div class="native-parity-profile-meta-v068"><span>模板 <b>${esc(p.template_id||'-')}</b></span><span>Motor-CAD <b>${esc(p.target_motorcad_version||'-')}</b></span><span>PyMotorCAD <b>${esc(p.required_pymotorcad_version||'-')}</b></span><span>得分 <b>${score.percent??0}%</b></span></div>
      <div class="actions"><button type="button" class="primary" data-native-parity-run="${esc(p.id)}">运行原生逐项对照</button>${latest.run_id?`<button type="button" data-native-parity-detail="${esc(latest.run_id)}">查看证据</button>`:''}</div>
    </article>`}).join('')||'<div class="native-parity-empty-v068">未配置 Native Parity Profile。</div>';
  }

  function renderMatrix(matrix){
    const box=q('#nativeParityMatrixV068');if(!box)return;
    const rows=matrix?.profiles||[];
    q('#nativeParityPercentV068').textContent=`${Number(matrix?.native_workstation_qualification_percent||0).toFixed(1)}%`;
    q('#nativeParitySummaryV068').textContent=matrix?.complete?'BPM / SPM / IPM / AFPM 已全部在当前工作站通过原生一致性门禁。':`已通过 ${matrix?.qualified_profiles||0}/${matrix?.total_profiles||rows.length} 个 Profile；未通过项不会标记 NATIVE_QUALIFIED。`;
    box.innerHTML=`<div class="table-wrap native-parity-table-v068"><table><thead><tr><th>Profile</th><th>模板</th><th>状态</th><th>得分</th><th>最近证据</th><th>阻断项</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${esc(r.label||r.profile_id)}</b><small>${esc(r.profile_id)}</small></td><td>${esc(r.template_id||'-')}</td><td><span class="native-parity-state-v068 ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span></td><td>${esc((r.score||{}).percent??0)}%</td><td>${r.run_id?`<button type="button" class="link-button" data-native-parity-detail="${esc(r.run_id)}">${esc(r.run_id)}</button>`:'-'}</td><td>${esc((r.blocking_checks||[]).join(', ')||'—')}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function refresh(){
    try{
      const [profiles,matrix]=await Promise.all([api('/api/native-parity/profiles'),api('/api/native-parity/matrix')]);
      catalog=profiles.profiles||[];renderProfiles();renderMatrix(matrix);
    }catch(e){const box=q('#nativeParityMatrixV068');if(box)box.innerHTML=`<div class="issue ERROR">${esc(e.message)}</div>`}
  }

  async function runProfile(profileId){
    if(busy)return;busy=true;
    const out=q('#nativeParityRunStatusV068');
    if(out)out.innerHTML=`<div class="preflight-running"><span class="spinner-dot"></span><b>正在目标 Motor-CAD 工作站执行 ${esc(profileId)} 原生逐项对照…</b><small>会启动真实 Motor-CAD、保存原生几何画面、绕组文件、MOT 与结果 CSV，并执行一次 EMag 求解。</small></div>`;
    try{
      const result=await api('/api/native-parity/run?timeout_s=1200',{method:'POST',body:JSON.stringify({profile_id:profileId})});
      if(out)out.innerHTML=`<div class="native-parity-result-v068 ${result.qualified?'pass':'fail'}"><div><span class="native-parity-state-v068 ${statusClass(result.status)}">${esc(statusLabel(result.status))}</span><h3>${esc(result.profile_label||profileId)} · ${(result.score||{}).percent||0}%</h3><p>${result.qualified?'当前 Profile 已满足 V0.68 NATIVE_QUALIFIED 门禁。':'仍有原生偏差或证据缺口；请根据阻断项继续校准。'}</p></div>${checkTable(result)}</div>`;
      toast(result.qualified?'Native parity 已通过':'Native parity 存在阻断项',result.qualified?'SUCCESS':'WARNING',7000);
      await refresh();
    }catch(e){if(out)out.innerHTML=`<div class="issue ERROR">${esc(e.message)}</div>`;toast(e.message,'ERROR',9000)}finally{busy=false}
  }

  async function runSuite(){
    if(busy)return;busy=true;
    const out=q('#nativeParityRunStatusV068');
    if(out)out.innerHTML='<div class="preflight-running"><span class="spinner-dot"></span><b>正在顺序执行 BPM / SPM / IPM / AFPM 原生资格套件…</b><small>每个 Profile 都在独立 Motor-CAD 子进程中运行，失败不会污染 Studio 主进程。</small></div>';
    try{
      const response=await api('/api/native-parity/run-suite?timeout_s=1200',{method:'POST',body:JSON.stringify({profile_ids:[],stop_on_failure:false})});
      const results=response.results||[];
      if(out)out.innerHTML=`<div class="native-parity-suite-result-v068"><h3>套件完成 · ${response.matrix?.qualified_profiles||0}/${response.matrix?.total_profiles||0} 通过</h3>${results.map(r=>`<div><span class="native-parity-state-v068 ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span><b>${esc(r.profile_label||r.profile_id)}</b><span>${esc((r.blocking_checks||[]).join(', ')||'无阻断')}</span></div>`).join('')}</div>`;
      await refresh();toast(response.complete?'V0.68 原生一致性套件全部通过':'原生一致性套件完成，仍有阻断项',response.complete?'SUCCESS':'WARNING',8000);
    }catch(e){if(out)out.innerHTML=`<div class="issue ERROR">${esc(e.message)}</div>`;toast(e.message,'ERROR',9000)}finally{busy=false}
  }

  async function openDetail(runId){
    try{
      const row=await api(`/api/native-parity/runs/${encodeURIComponent(runId)}`),evidence=row.evidence||{};
      const html=`<div class="native-parity-detail-v068"><div class="native-parity-detail-summary-v068"><span class="native-parity-state-v068 ${statusClass(evidence.status)}">${esc(statusLabel(evidence.status))}</span><div><h3>${esc(evidence.profile_label||evidence.profile_id||'Native Parity')}</h3><p>${esc(runId)} · ${(evidence.score||{}).percent||0}% · ${esc(evidence.motorcad_target_version||'')}</p></div></div><div class="native-parity-evidence-actions-v068"><a class="button-like" target="_blank" rel="noopener" href="/api/native-parity/runs/${encodeURIComponent(runId)}/report">查看验收报告</a><a class="button-like primary" href="/api/native-parity/runs/${encodeURIComponent(runId)}/artifacts.zip">下载完整证据包</a></div>${checkTable(evidence)}<div class="definition-grid"><div><small>Evidence SHA-256</small><b>${esc(evidence.evidence_sha256||'-')}</b></div><div><small>Artifact directory</small><b>${esc(evidence.artifact_dir||row.artifact_dir||'-')}</b></div><div><small>PyMotorCAD</small><b>${esc(evidence.pymotorcad_version||'-')}</b></div><div><small>Model source</small><b>${esc(evidence.model_load?.type||'-')}</b></div><div><small>验收 MOT</small><b>${esc(evidence.verified_model_baseline?.artifact||'-')}</b></div><div><small>原生画面</small><b>${esc(String((evidence.checks||[]).find(c=>c.id==='native_geometry_screens')?.rows?.filter(r=>r.status==='PASS').length||0))} 张</b></div></div></div>`;
      if(window.StudioDialog?.sheet)await StudioDialog.sheet({title:'Motor-CAD 原生一致性证据',html:html,width:'980px',actions:[{label:'关闭',value:false}]});
      else toast(`证据 ${runId}：${(evidence.blocking_checks||[]).join(', ')||'无阻断项'}`,'INFO',8000);
    }catch(e){toast(e.message,'ERROR')}
  }

  document.addEventListener('click',e=>{const run=e.target.closest('[data-native-parity-run]');if(run){runProfile(run.dataset.nativeParityRun);return}const detail=e.target.closest('[data-native-parity-detail]');if(detail){openDetail(detail.dataset.nativeParityDetail)}});
  q('#runNativeParitySuiteV068')?.addEventListener('click',runSuite);
  q('#refreshNativeParityV068')?.addEventListener('click',refresh);
  window.MCSNativeParityV068={refresh,runProfile,runSuite};
  refresh();
})();
