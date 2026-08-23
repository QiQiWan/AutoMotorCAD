(function(global){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]));
  const yes=value=>value===true;
  async function load(options={}){
    const request=options.api||global.api;
    const box=document.querySelector('#productionSoakSummaryV087FC');
    const badge=document.querySelector('#productionSoakBadgeV087FC');
    if(!box||typeof request!=='function')return null;
    try{
      const payload=await request('/api/production-soak-qualification');
      const formal=Boolean(payload.formal_production_hardened);
      const local=Boolean(payload.local_control_plane_qualified);
      const latest=payload.latest_run||payload.latest_formal_run||payload.latest_local_run||null;
      const evidence=latest?.evidence||{};
      const coverage=latest?.coverage||evidence.coverage||{};
      const blockers=latest?.qualification_blockers||evidence.qualification_blockers||[];
      const tierSpec=payload.matrix?.tiers||[];
      const tiers=evidence.tiers||[];
      if(badge){
        badge.textContent=formal?'生产加固通过':(local?'本地Soak通过':'待100/500实机Soak');
        badge.className=`badge ${formal?'VALID':(local?'WARNING':'UNVERIFIED')}`;
      }
      const tierRows=tierSpec.map(spec=>{
        const row=tiers.find(item=>item.id===spec.id)||{};
        const native=Boolean(row.native_motorcad);
        const completed=Number(row.completed_cases??row.completed_operations??0);
        const required=Number(spec.required_cases||0);
        const rss=Number(row.studio_rss_growth_mb||0);
        const recycle=Number(row.worker_recycle_count||0);
        const ok=row.status==='PASS'&&(latest?.mode==='LOCAL_CONTROL_PLANE'||(native&&completed===required));
        const detail=latest?.mode==='LOCAL_CONTROL_PLANE'
          ?`${completed}/${required} operations · RSS +${rss.toFixed(1)} MB`
          :`${completed}/${required} cases · recycle ${recycle} · RSS +${rss.toFixed(1)} MB`;
        return `<div class="workstation-matrix-row ${ok?'ready':'pending'}"><b>${esc(spec.id)}</b><span>${esc(detail)}</span><small>${ok?'PASS':'PENDING'}</small></div>`;
      }).join('');
      const probes=evidence.recovery_probes||{};
      const probeRows=[
        ['Cancel → Retry',yes(probes.cancel_retry_pass)],
        ['Worker Crash → Recovery',yes(probes.crash_restart_pass)],
        ['Studio Restart → Reopen',yes(probes.restart_reopen_pass)],
        ['Windows Qualification Retention',yes(probes.qualification_retention_pass)],
      ];
      box.innerHTML=`<div class="workstation-acceptance-overview ${formal?'qualified':'pending'}"><div><span class="eyebrow">PRODUCTION SOAK & HARDENING</span><h3>${formal?'100 / 500 Case 生产加固已通过':local?'本地控制面 Soak 已通过，等待 Native Soak':'等待 100 / 500 Case Native Soak'}</h3><p>${formal?'当前证据同时满足 Windows 工作站资格、100/500 Native Case、资源稳定性、恢复探针和不可变证据包。':local?'本地结果只证明 Studio 控制面在持续访问下没有明显资源累积；不能替代 licensed Motor-CAD Native Case。':'正式 PASS 需要在已通过 Windows + Motor-CAD 2026R1 工作站完成两个长时 Case Campaign。'}</p></div><div class="workstation-qualification-score"><b>${payload.formal_qualification_percent||0}%</b><small>Production hardening</small><span>${Number(payload.evidence_coverage_percent||0).toFixed(0)}% evidence</span></div></div><div class="workstation-matrix"><div class="workstation-matrix-head"><b>100 / 500 Case Soak Matrix</b><span>ResultBundle · RSS · Worker recycle · shutdown</span></div>${tierRows||'<div class="workspace-empty compact"><b>尚无 Soak 证据</b><span>先运行本地控制面 Soak，再在正式 Windows 工作站运行 Native Soak。</span></div>'}</div><div class="workstation-onboarding-grid">${probeRows.map(([label,ok])=>`<div class="workstation-onboarding-step ${ok?'ready':'pending'}"><span>${esc(label)}</span><b>${ok?'PASS':'待证据'}</b></div>`).join('')}</div>${blockers.length?`<div class="workstation-acceptance-blockers"><b>当前生产加固阻断</b>${blockers.slice(0,12).map(item=>`<span>${esc(item)}</span>`).join('')}</div>`:''}<div class="workstation-acceptance-command">motorcad-studio-production-soak --phase execute --formal --licensed-evidence <span>· restart → --phase resume</span></div>`;
      return payload;
    }catch(error){
      box.innerHTML=`<div class="issue WARNING">Soak 资格读取失败：${esc(error.message||error)}</div>`;
      return null;
    }
  }
  global.MCSProductionSoak=Object.freeze({load});
})(window);
