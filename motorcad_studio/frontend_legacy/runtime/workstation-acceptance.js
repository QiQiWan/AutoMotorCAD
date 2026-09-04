(function(global){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]));
  const nativePass=row=>row&&row.status==='PASS'&&row.native_motorcad===true;
  const portable=e=>Boolean(e&&e.packaged_path&&e.sha256&&Number(e.size||0)>0);

  function nativeSnapshot(payload){
    const latest=payload?.latest_run||payload?.latest_qualified_run||(payload?.runs||[])[0]||null;
    const evidence=latest?.evidence||{};
    const scenarios=evidence.representative_scenarios||[];
    const faults=evidence.failure_injections||[];
    const required=scenarios.filter(x=>x.required!==false).length||4;
    const passed=scenarios.filter(nativePass).length;
    const faultRequired=faults.filter(x=>x.required!==false).length||17;
    const faultPassed=faults.filter(x=>x.status==='PASS'&&Boolean(x.evidence?.sha256||x.evidence?.formal_observation)).length;
    return {payload,latest,evidence,scenarios,faults,required,passed,faultRequired,faultPassed};
  }

  function renderLegacy(payload,box,badge){
    const qualified=Boolean(payload.formal_qualified);
    const isV2=String(payload.authority||'')==='WindowsMotorCADProductionQualificationV2';
    const snap=nativeSnapshot(payload), latest=snap.latest, evidence=snap.evidence;
    const onboarding=evidence.onboarding||{},env=evidence.environment||{},runtime=evidence.runtime_lifecycle||{},coverage=latest?.coverage||evidence.coverage||{};
    const blockers=latest?.qualification_blockers||evidence.qualification_blockers||[];
    const evidenceCoverage=Number(payload.evidence_coverage_percent??coverage.evidence_coverage_percent??0),host=evidence.host_fingerprint||{};
    const pymotorcadRecorded=Boolean(host.pymotorcad_version&&!['unresolved','unknown','n/a','none'].includes(String(host.pymotorcad_version).toLowerCase()));
    const binaryReady=!isV2||(host.motorcad_normalized_version==='2026R1'&&host.motorcad_binary_probe_status==='PASS'&&pymotorcadRecorded);
    if(badge){badge.textContent=qualified?'正式通过':'待工作站验收';badge.className=`badge ${qualified?'VALID':'UNVERIFIED'}`}
    const steps=[
      ['1 · 环境检测',env.deep_preflight_pass&&binaryReady?`${host.motorcad_normalized_version||'2026R1'} · PyMotorCAD ${host.pymotorcad_version||'-'}`:'待真实深度检查 / 二进制版本证据',Boolean(env.deep_preflight_pass&&binaryReady)],
      ['2 · Motor-CAD / License',evidence.licensed_motorcad_evidence?'已有证据':'待 Licensed 证据',Boolean(evidence.licensed_motorcad_evidence)],
      ['3 · 真实示例计算',`${snap.passed}/${snap.required} 代表场景`,snap.passed===snap.required],
      ['4 · 故障恢复矩阵',`${snap.faultPassed}/${snap.faultRequired} 故障证据`,snap.faultPassed===snap.faultRequired],
      ['5 · Runtime生命周期',runtime.local_qualified&&runtime.shutdown_clean?'关闭干净':'待关闭证据',Boolean(runtime.local_qualified&&runtime.shutdown_clean)],
      ['6 · 第一份结果 / 重启',onboarding.first_native_result_bundle&&onboarding.restart_reopen_pass?'可重开':'待 ResultBundle + 重启',Boolean(onboarding.first_native_result_bundle&&onboarding.restart_reopen_pass)],
    ];
    const scenarioRows=(payload.matrix?.representative_scenarios||snap.scenarios||[]).map(spec=>{
      const sid=spec.id||'',row=snap.scenarios.find(x=>x.id===sid)||{},requiredGates=Array.isArray(spec.required_gates)?spec.required_gates:[];
      const gatesReady=!isV2||requiredGates.every(key=>row[key]===true);
      const ok=nativePass(row)&&gatesReady&&(isV2?Boolean(row.result_bundle_id&&row.result_bundle_hash&&row.native_binding_plan_hash):row.native_closure_qualified!==false&&row.restart_reopen_pass!==false);
      const detail=row.status?`${row.status}${row.native_closure_qualified===true?' · Closure':''}${row.restart_reopen_pass===true?' · Reopen':''}`:'待实机';
      return `<div class="workstation-matrix-row ${ok?'ready':'pending'}"><b>${esc(sid)}</b><span>${esc(spec.template_id||row.template_id||'')}</span><small>${esc(detail)}</small></div>`;
    }).join('');
    box.innerHTML=`<div class="workstation-acceptance-overview ${qualified?'qualified':'pending'}"><div><span class="eyebrow">WINDOWS MOTOR-CAD PRODUCTION QUALIFICATION</span><h3>${qualified?'正式工作站资格已通过':'正式工作站资格尚未完成'}</h3><p>${qualified?'当前资格来自完整 licensed Windows + Motor-CAD 2026R1 evidence package。':'Studio 本地功能与生命周期资格不会自动提升 Native 生产资格；必须完成 4/4 Native 场景、17/17 故障证据与重启恢复。'}</p></div><div class="workstation-qualification-score"><b>${payload.qualification_percent||0}%</b><small>Formal qualification</small><span>${evidenceCoverage.toFixed(0)}% evidence</span></div></div><div class="workstation-onboarding-grid">${steps.map(([label,value,ok])=>`<div class="workstation-onboarding-step ${ok?'ready':'pending'}"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}</div>${scenarioRows?`<div class="workstation-matrix"><div class="workstation-matrix-head"><b>4 类代表机型 Native Matrix</b><span>SPM / IPM / AFPM / IM</span></div>${scenarioRows}</div>`:''}${blockers.length?`<div class="workstation-acceptance-blockers"><b>当前资格阻断</b>${blockers.slice(0,10).map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:''}<div class="workstation-acceptance-command">run_windows_production_qualification.bat</div>`;
    return payload;
  }

  function renderV089D(payload,nativePayload,box,badge){
    const qualified=Boolean(payload.formal_qualified),latest=payload.latest_run||payload.latest_qualified_run||(payload.runs||[])[0]||null;
    const evidence=latest?.evidence||{},coverage=latest?.coverage||evidence.coverage||{},blockers=latest?.qualification_blockers||evidence.qualification_blockers||[];
    const journeys=evidence.golden_journeys||[],matrix=payload.matrix?.golden_journeys||[];
    const native=nativeSnapshot(nativePayload||{}),nativeQualified=Boolean(nativePayload?.formal_qualified);
    const journeyPass=journeys.filter(row=>String(row.status||'').toUpperCase()==='PASS').length;
    const journeyRequired=matrix.length||3;
    const evidenceCoverage=Number(payload.evidence_coverage_percent??coverage.evidence_coverage_percent??0);
    if(badge){badge.textContent=qualified?'正式通过':(nativeQualified?'Native通过 · 待UI旅程':'待工作站验收');badge.className=`badge ${qualified?'VALID':'UNVERIFIED'}`}
    const journeyRows=matrix.map(spec=>{
      const sid=String(spec.id||'').toUpperCase(),row=journeys.find(x=>String(x.id||'').toUpperCase()===sid)||{};
      const gates=Array.isArray(spec.required_gates)?spec.required_gates:[];
      const gateReady=gates.every(key=>row[key]===true);
      const ev=row.evidence||{},evidenceReady=['summary','design_screenshot','precheck_screenshot','result_screenshot','playwright_trace'].every(key=>portable(ev[key]));
      const ok=String(row.status||'').toUpperCase()==='PASS'&&gateReady&&evidenceReady;
      return `<div class="workstation-matrix-row ${ok?'ready':'pending'}"><b>${esc(sid)}</b><span>${esc(spec.starter_id||row.starter_id||'')}</span><small>${ok?'PASS · UI→Native→Result':'待完整 UI Golden Journey'}</small></div>`;
    }).join('');
    const steps=[
      ['1 · Native 底座',nativeQualified?`${native.passed}/${native.required} Native · ${native.faultPassed}/${native.faultRequired} 故障`:'待 4/4 Native + 17/17 故障',nativeQualified],
      ['2 · SPM/IPM/AFPM UI旅程',`${journeyPass}/${journeyRequired} Golden Journeys`,journeyPass===journeyRequired],
      ['3 · 工程对象Lineage',journeys.length&&journeys.every(x=>x.lineage_consistent===true)?'3/3 一致':'待完整链路证据',journeys.length===journeyRequired&&journeys.every(x=>x.lineage_consistent===true)],
      ['4 · Browser错误',journeys.length&&journeys.every(x=>x.no_page_errors===true&&x.no_console_errors===true)?'0 page / console errors':'待浏览器零错误证据',journeys.length===journeyRequired&&journeys.every(x=>x.no_page_errors===true&&x.no_console_errors===true)],
      ['5 · 截图与Trace',journeys.length&&journeys.every(x=>x.screenshot_evidence===true&&x.trace_evidence===true)?'证据完整':'待截图 / Playwright trace',journeys.length===journeyRequired&&journeys.every(x=>x.screenshot_evidence===true&&x.trace_evidence===true)],
      ['6 · 发布门禁',coverage.release_gate_passed===coverage.release_gate_required?`${coverage.release_gate_passed||0}/${coverage.release_gate_required||3}`:'待完整发布门禁',coverage.release_gate_required>0&&coverage.release_gate_passed===coverage.release_gate_required],
    ];
    box.innerHTML=`<div class="workstation-acceptance-overview ${qualified?'qualified':'pending'}"><div><span class="eyebrow">WINDOWS NATIVE GOLDEN JOURNEY</span><h3>${qualified?'真实工作站与 UI Golden Journey 已正式通过':'正式工作站资格尚未完成'}</h3><p>${qualified?'SPM、IPM、AFPM 已在真实 Windows + licensed Motor-CAD 2026R1 上经完整 Studio UI 创建、预检、求解并重新打开结果。':'正式资格要求先完成 Native 底座，再完成 3/3 真实界面 Golden Journey；模拟 E2E 不能提升正式资格。'}</p></div><div class="workstation-qualification-score"><b>${payload.qualification_percent||0}%</b><small>Formal qualification</small><span>${evidenceCoverage.toFixed(0)}% evidence</span></div></div><div class="workstation-onboarding-grid">${steps.map(([label,value,ok])=>`<div class="workstation-onboarding-step ${ok?'ready':'pending'}"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}</div><div class="workstation-matrix"><div class="workstation-matrix-head"><b>3 条真实 UI Golden Journey</b><span>SPM / IPM / AFPM</span></div>${journeyRows||'<div class="workstation-matrix-row pending"><b>Pending</b><span>尚无真实 UI Journey evidence</span></div>'}</div>${blockers.length?`<div class="workstation-acceptance-blockers"><b>当前资格阻断</b>${blockers.slice(0,12).map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:''}<div class="workstation-acceptance-command">run_windows_production_qualification.bat</div>`;
    return payload;
  }

  async function load(options={}){
    const request=options.api||global.api,box=document.querySelector('#workstationAcceptanceSummary'),badge=document.querySelector('#workstationAcceptanceBadge');
    if(!box||typeof request!=='function')return null;
    try{
      let payload=null,nativePayload=null;
      try{payload=await request('/api/windows-golden-journey-qualification')}catch(_){payload=null}
      if(String(payload?.authority||'')==='WindowsNativeGoldenJourneyQualificationV1'){
        try{nativePayload=await request('/api/windows-production-qualification')}catch(_){nativePayload=null}
        return renderV089D(payload,nativePayload,box,badge);
      }
      try{nativePayload=payload&&String(payload.authority||'').includes('WindowsMotorCADProductionQualification')?payload:await request('/api/windows-production-qualification')}
      catch(_){nativePayload=await request('/api/workstation-acceptance')}
      return renderLegacy(nativePayload,box,badge);
    }catch(error){
      box.innerHTML=`<div class="issue WARNING">工作站资格读取失败：${esc(error.message||error)}</div>`;
      return null;
    }
  }
  global.MCSWorkstationAcceptance=Object.freeze({load});
})(window);
