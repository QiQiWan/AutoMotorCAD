(function(global){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]));
  async function load(options={}){
    const request=options.api||global.api;
    const box=document.querySelector('#uiSoakSummaryV089E');
    const badge=document.querySelector('#uiSoakBadgeV089E');
    if(!box||typeof request!=='function')return null;
    try{
      const payload=await request('/api/ui-soak-qualification');
      const formal=Boolean(payload.formal_qualified);
      const local=Boolean(payload.local_browser_qualified);
      const latest=payload.latest_run||payload.latest_qualified_run||payload.latest_local_run||null;
      const evidence=latest?.evidence||{};
      const coverage=latest?.coverage||evidence.coverage||{};
      const blockers=latest?.qualification_blockers||evidence.qualification_blockers||[];
      const matrix=payload.matrix||{};
      const tiers=evidence.tiers||[];
      const faults=evidence.fault_injections||[];
      if(badge){
        badge.textContent=formal?'UI韧性通过':(local?'本地UI Soak通过':'待UI Soak');
        badge.className=`badge ${formal?'VALID':(local?'WARNING':'UNVERIFIED')}`;
      }
      const tierRows=(matrix.tiers||[]).map(spec=>{
        const row=tiers.find(item=>item.id===spec.id)||{};
        const complete=Number(row.completed_cycles||0),required=Number(spec.required_cycles||0);
        const ok=row.status==='PASS'&&complete===required;
        const heap=Number(row.js_heap_growth_mb||0),dom=Number(row.dom_node_growth||0);
        return `<div class="workstation-matrix-row ${ok?'ready':'pending'}"><b>${esc(spec.id)}</b><span>${complete}/${required} cycles · ${Number(row.interaction_count||0)} interactions · heap +${heap.toFixed(1)} MB · DOM +${dom}</span><small>${ok?'PASS':'PENDING'}</small></div>`;
      }).join('');
      const faultSpec=matrix.fault_scenarios||[];
      const faultPassed=faultSpec.filter(spec=>faults.find(row=>row.id===spec.id&&row.status==='PASS')).length;
      const faultRows=faultSpec.map(spec=>{
        const row=faults.find(item=>item.id===spec.id)||{};const ok=row.status==='PASS';
        return `<div class="workstation-onboarding-step ${ok?'ready':'pending'}"><span>${esc(spec.id)}</span><b>${ok?'PASS':'待证据'}</b></div>`;
      }).join('');
      const inherited=coverage.inherited_native_fault_results||{};
      const inheritedPassed=Object.values(inherited).filter(row=>row?.passed).length;
      const inheritedRequired=Object.keys(inherited).length||Number((matrix.inherited_native_faults||[]).length||0);
      box.innerHTML=`<div class="workstation-acceptance-overview ${formal?'qualified':'pending'}"><div><span class="eyebrow">UI RESILIENCE</span><h3>${formal?'UI Soak / Recovery / Fault Injection 正式资格已通过':local?'本地浏览器稳定性已通过，等待Windows正式证据':'等待UI稳定性与故障恢复资格'}</h3><p>${formal?'当前工作站同时具备真实 Golden Journey、Native 100/500 Case Soak、UI 100/500 循环和完整故障恢复证据。':local?'本地结果只验证Chromium控制面和交易恢复；正式PASS仍要求licensed Windows + Motor-CAD前置证据。':'正式验收将连续执行100/500轮工程师操作，并主动注入导航、响应丢失、409/500、断网、刷新和Worker回收故障。'}</p></div><div class="workstation-qualification-score"><b>${payload.formal_qualification_percent||0}%</b><small>UI resilience</small><span>${Number(payload.evidence_coverage_percent||0).toFixed(0)}% evidence</span></div></div><div class="workstation-matrix"><div class="workstation-matrix-head"><b>UI Soak Matrix</b><span>cycles · context · dialogs · heap · DOM</span></div>${tierRows||'<div class="workspace-empty compact"><b>尚无UI Soak证据</b><span>先运行本地Chromium资格，再在正式Windows工作站运行完整100/500轮。</span></div>'}</div><div class="subsection"><div class="workstation-matrix-head"><b>故障恢复矩阵</b><span>${faultPassed}/${faultSpec.length} UI faults · ${inheritedPassed}/${inheritedRequired} inherited native faults</span></div><div class="workstation-onboarding-grid">${faultRows}</div></div>${blockers.length?`<div class="workstation-acceptance-blockers"><b>当前UI韧性阻断</b>${blockers.slice(0,16).map(item=>`<span>${esc(item)}</span>`).join('')}</div>`:''}<div class="workstation-acceptance-command">motorcad-studio-ui-soak --artifact-dir acceptance_evidence/ui-resilience --formal <span>· Chromium live full-shell</span></div>`;
      return payload;
    }catch(error){
      box.innerHTML=`<div class="issue WARNING">UI Soak资格读取失败：${esc(error.message||error)}</div>`;
      return null;
    }
  }
  global.MCSUISoakQualification=Object.freeze({load});
})(window);
