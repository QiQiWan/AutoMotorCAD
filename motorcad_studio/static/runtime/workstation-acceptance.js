(function(global){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]));
  const pass=row=>row&&row.status==='PASS'&&row.native_motorcad===true;
  async function load(options={}){
    const request=options.api||global.api;
    const box=document.querySelector('#workstationAcceptanceSummary');
    const badge=document.querySelector('#workstationAcceptanceBadge');
    if(!box||typeof request!=='function')return null;
    try{
      let payload;
      try{payload=await request('/api/windows-production-qualification');}
      catch(_){payload=await request('/api/workstation-acceptance');}
      const qualified=Boolean(payload.formal_qualified);
      const isV2=String(payload.authority||'')==='WindowsMotorCADProductionQualificationV2';
      const latest=payload.latest_run||payload.latest_qualified_run||(payload.runs||[])[0]||null;
      const evidence=latest?.evidence||{};
      const onboarding=evidence.onboarding||{};
      const env=evidence.environment||{};
      const runtime=evidence.runtime_lifecycle||{};
      const coverage=latest?.coverage||evidence.coverage||{};
      const scenarios=evidence.representative_scenarios||[];
      const passed=scenarios.filter(pass).length;
      const required=scenarios.filter(x=>x.required!==false).length;
      const faults=evidence.failure_injections||[];
      const faultRequired=faults.filter(x=>x.required!==false).length;
      const faultPassed=faults.filter(x=>x.status==='PASS'&&Boolean(x.evidence?.sha256||x.evidence?.formal_observation)).length;
      const blockers=latest?.qualification_blockers||evidence.qualification_blockers||[];
      const evidenceCoverage=Number(payload.evidence_coverage_percent??coverage.evidence_coverage_percent??0);
      const host=evidence.host_fingerprint||{};
      const binaryReady=!isV2||(host.motorcad_normalized_version==='2026R1'&&host.motorcad_binary_probe_status==='PASS'&&host.pymotorcad_version==='0.8.8');
      if(badge){
        badge.textContent=qualified?'正式通过':'待工作站验收';
        badge.className=`badge ${qualified?'VALID':'UNVERIFIED'}`;
      }
      const steps=[
        ['1 · 环境检测',env.deep_preflight_pass&&binaryReady?`${host.motorcad_normalized_version||'2026R1'} · PyMotorCAD ${host.pymotorcad_version||'-'}`:'待真实深度检查 / 二进制版本证据',Boolean(env.deep_preflight_pass&&binaryReady)],
        ['2 · Motor-CAD / License',evidence.licensed_motorcad_evidence?'已有证据':'待 Licensed 证据',Boolean(evidence.licensed_motorcad_evidence)],
        ['3 · 真实示例计算',required?`${passed}/${required} 代表场景`:'0/4 代表场景',Boolean((required||4)&&passed===(required||4))],
        ['4 · 故障恢复矩阵',faultRequired?`${faultPassed}/${faultRequired} 故障证据`:'0/17 故障证据',Boolean(faultRequired&&faultPassed===faultRequired)],
        ['5 · Runtime生命周期',runtime.local_qualified&&runtime.shutdown_clean?'关闭干净':'待关闭证据',Boolean(runtime.local_qualified&&runtime.shutdown_clean)],
        ['6 · 第一份结果 / 重启',onboarding.first_native_result_bundle&&onboarding.restart_reopen_pass?'可重开':'待 ResultBundle + 重启',Boolean(onboarding.first_native_result_bundle&&onboarding.restart_reopen_pass)],
      ];
      const scenarioRows=(payload.matrix?.representative_scenarios||scenarios||[]).map(spec=>{
        const sid=spec.id||''; const row=scenarios.find(x=>x.id===sid)||{};
        const requiredGates=Array.isArray(spec.required_gates)?spec.required_gates:[];
        const v2GatesReady=!isV2||requiredGates.every(key=>row[key]===true);
        const ok=pass(row)&&v2GatesReady&&(isV2?Boolean(row.result_bundle_id&&row.result_bundle_hash&&row.native_binding_plan_hash):row.native_closure_qualified!==false&&row.restart_reopen_pass!==false);
        const detail=row.status?`${row.status}${row.native_closure_qualified===true?' · Closure':''}${row.restart_reopen_pass===true?' · Reopen':''}`:'待实机';
        return `<div class="workstation-matrix-row ${ok?'ready':'pending'}"><b>${esc(sid)}</b><span>${esc(spec.template_id||row.template_id||'')}</span><small>${esc(detail)}</small></div>`;
      }).join('');
      box.innerHTML=`<div class="workstation-acceptance-overview ${qualified?'qualified':'pending'}"><div><span class="eyebrow">WINDOWS MOTOR-CAD PRODUCTION QUALIFICATION</span><h3>${qualified?'正式工作站资格已通过':'正式工作站资格尚未完成'}</h3><p>${qualified?'当前资格来自完整 licensed Windows + Motor-CAD 2026R1 evidence package。':'Studio 本地功能与生命周期资格不会自动提升 Native 生产资格；必须完成 4/4 Native 场景、17/17 故障证据与重启恢复。'}</p></div><div class="workstation-qualification-score"><b>${payload.qualification_percent||0}%</b><small>Formal qualification</small><span>${evidenceCoverage.toFixed(0)}% evidence</span></div></div><div class="workstation-onboarding-grid">${steps.map(([label,value,ok])=>`<div class="workstation-onboarding-step ${ok?'ready':'pending'}"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}</div>${scenarioRows?`<div class="workstation-matrix"><div class="workstation-matrix-head"><b>4 类代表机型 Native Matrix</b><span>SPM / IPM / AFPM / IM</span></div>${scenarioRows}</div>`:''}${blockers.length?`<div class="workstation-acceptance-blockers"><b>当前资格阻断</b>${blockers.slice(0,10).map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:''}<div class="workstation-acceptance-command">run_windows_production_qualification.bat</div>`;
      return payload;
    }catch(error){
      box.innerHTML=`<div class="issue WARNING">工作站资格读取失败：${esc(error.message||error)}</div>`;
      return null;
    }
  }
  global.MCSWorkstationAcceptance=Object.freeze({load});
})(window);
