/* V0.89-F Release Candidate Gate HMI. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const apiCall=path=>window.api?window.api(path):fetch(path,{cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error(await r.text());return r.json()});
  const gateLabel={automated_release_gate:'自动 Release Gate',licensed_windows_native:'Windows + Motor-CAD 实机',windows_ui_golden_journeys:'SPM/IPM/AFPM UI Golden Journey',native_100_500_soak:'Native 100/500 Case Soak',ui_100_500_fault_recovery:'UI 100/500 + 故障恢复',human_engineer_acceptance:'工程师人工验收'};
  function render(summary){
    const host=q('#releaseCandidateGateSummaryV089F');if(!host)return;
    const checks=summary.formal_checks||{};
    const ws=summary.workstation||{};
    host.innerHTML=`<div class="rc-gate-hero-v089f ${summary.formal_rc_qualified?'ready':summary.local_rc_ready?'pending':'blocked'}"><div><span>Release Candidate 状态</span><b>${esc(summary.label||summary.status)}</b><small>${esc(summary.next_action||'')}</small></div><strong>${summary.formal_rc_qualified?'RC READY':summary.local_rc_ready?'LOCAL RC':'BLOCKED'}</strong></div><div class="rc-gate-grid-v089f">${Object.entries(checks).map(([key,passed])=>`<div class="rc-gate-item-v089f ${passed?'pass':'pending'}"><span>${passed?'✓':'○'}</span><div><b>${esc(gateLabel[key]||key)}</b><small>${passed?'已通过':'待完成'}</small></div></div>`).join('')}</div><div class="rc-workstation-meter-v089f"><span>Native 实机 <b>${ws.native_percent||0}%</b></span><span>UI Golden Journey <b>${ws.golden_journey_percent||0}%</b></span><span>Native Soak <b>${ws.native_soak_percent||0}%</b></span><span>UI 韧性 <b>${ws.ui_resilience_percent||0}%</b></span></div>${summary.formal_blockers?.length?`<div class="rc-blockers-v089f"><b>正式 RC 尚缺 ${summary.formal_blockers.length} 项</b><span>${summary.formal_blockers.map(x=>esc(gateLabel[x]||x)).join(' · ')}</span></div>`:''}`;
    const badge=q('#releaseCandidateBadgeV089F');if(badge){badge.textContent=summary.formal_rc_qualified?'RC就绪':summary.local_rc_ready?'本地RC就绪':'RC阻断';badge.className=`badge ${summary.formal_rc_qualified?'PASS':summary.local_rc_ready?'WARNING':'FAIL'}`}
  }
  async function refresh(){
    const btn=q('#refreshReleaseCandidateGateV089F');if(btn)btn.disabled=true;
    try{const summary=await apiCall('/api/release-candidate-gate');render(summary);return summary}catch(e){window.toast?.(`RC Gate读取失败：${e.message||e}`,'ERROR',7000);return null}finally{if(btn)btn.disabled=false}
  }
  async function exportChecklist(){
    try{const spec=await apiCall('/api/release-candidate-gate/checklist');const blob=new Blob([JSON.stringify(spec,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`motorcad-rc-human-checklist-${Date.now()}.json`;document.body.appendChild(a);a.click();a.remove();requestAnimationFrame(()=>URL.revokeObjectURL(url));}catch(e){window.toast?.(`验收清单导出失败：${e.message||e}`,'ERROR',7000)}
  }
  q('#refreshReleaseCandidateGateV089F')?.addEventListener('click',refresh);
  q('#exportReleaseCandidateChecklistV089F')?.addEventListener('click',exportChecklist);
  window.addEventListener('mcs:bootstrap-ready',()=>refresh());
  window.MCSReleaseCandidateGate={refresh,render};
})();
