/* V0.81-D Engineering Result Interpretation + Baseline UX authority. */
(() => {
  const safe=value=>typeof esc==='function'?esc(value??''):String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const fmt=(value,unit='')=>{const n=Number(value);const text=Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:3}):safe(value??'—');return `${text}${unit?` ${safe(unit)}`:''}`};
  const statusLabel=status=>({FORMAL:'正式可用',REVIEW_ONLY:'需复核',BLOCKED:'已阻断',IMPROVED:'改善',ATTENTION:'关注',OBSERVED:'已观察'}[String(status||'').toUpperCase()]||String(status||'—'));
  const statusClass=status=>String(status||'review').toLowerCase().replace(/_/g,'-');
  const trendText=row=>{const delta=row?.baseline_delta||{};if(delta.absolute==null)return'';const abs=Number(delta.absolute),rel=Number(delta.relative_percent);return `<span class="interpretation-delta ${statusClass(row.trend)}"><b>${abs>0?'+':''}${fmt(abs,row.unit)}</b>${Number.isFinite(rel)?`<small>${rel>0?'+':''}${rel.toFixed(2)}%</small>`:''}<em>${statusLabel(row.trend)}</em></span>`};

  function renderBaseline(overview,reference){
    const baseline=overview?.baseline_reference||null,history=overview?.baseline_history||[],integrity=overview?.baseline_integrity||null;
    const currentBundle=reference?.result_bundle_id||null,candidateStatus=String(overview?.reference_interpretation?.status||'REVIEW_ONLY').toUpperCase();
    const same=Boolean(baseline&&currentBundle&&String(baseline.result_bundle_id)===String(currentBundle));
    const candidateBlocked=candidateStatus==='BLOCKED';
    const baselineAction=currentBundle?(candidateBlocked?'<button type="button" disabled>当前结果存在阻断</button>':`<button type="button" class="primary" data-set-project-baseline="${safe(currentBundle)}">${candidateStatus==='FORMAL'?'将当前结果设为 Baseline':'设为复核 Baseline'}</button>`):'';
    const historyHtml=history.length?`<details class="baseline-history"><summary>Baseline 历史 ${history.length}</summary><div>${history.map(row=>`<span><b>${safe(row.label)}</b><small>${safe(row.state)} · Case ${safe(row.case_id)} · ${safe(row.eligibility_status)}</small></span>`).join('')}</div></details>`:'';
    if(!baseline)return `<article class="panel baseline-reference-card empty"><div class="section-head"><div><span class="eyebrow">PROJECT BASELINE</span><h3>尚未建立项目工程 Baseline</h3><p>Baseline 必须明确指向一个不可变 ResultBundle。建立后，后续结果只在 Comparability Gate 通过时显示正式 delta。</p></div>${baselineAction}</div>${candidateStatus==='REVIEW_ONLY'&&currentBundle?'<p class="baseline-review-note">当前结果可作为参考基准，但正式比较仍取决于 Trust 与语义指纹资格。</p>':''}${historyHtml}</article>`;
    const fp=baseline.fingerprint||{},integrityOk=!integrity||integrity.valid===true;
    const replaceAction=same?`<span class="status ${integrityOk?'formal':'blocked'}">${integrityOk?'当前结果即 Baseline':'Baseline 完整性异常'}</span>`:(candidateBlocked?'<button type="button" disabled>当前结果存在阻断</button>':currentBundle?`<button type="button" data-set-project-baseline="${safe(currentBundle)}">${candidateStatus==='FORMAL'?'将当前结果替换为 Baseline':'替换为复核 Baseline'}</button>`:'');
    return `<article class="panel baseline-reference-card ${same?'current':''} ${integrityOk?'':'blocked'}"><div class="section-head"><div><span class="eyebrow">PROJECT BASELINE · ${safe(baseline.eligibility_status)}</span><h3>${safe(baseline.label)}</h3><p>Case ${safe(baseline.case_id)} · ResultBundle ${safe(String(baseline.result_bundle_hash||'').slice(0,12))} · ${safe(fp.analysis_recipe_id||'analysis')} · ${safe(fp.target_motorcad_version||'Motor-CAD version n/a')}</p></div><div class="actions">${replaceAction}</div></div>${integrity&&!integrityOk?`<div class="baseline-integrity-alert"><b>Baseline integrity BLOCKED</b><span>${safe((integrity.issues||[]).join(' · '))}</span></div>`:''}<div class="baseline-fingerprint-grid"><div><span>Solution / Topology</span><b>${safe(fp.solution_id||'—')} · ${safe(fp.topology_id||fp.motor_family||'—')}</b></div><div><span>Analysis intent</span><b>${safe(fp.analysis_guidance_template_id||fp.analysis_recipe_id||'—')}</b></div><div><span>Operating point</span><b>${safe(String(fp.scenario_hash||'').slice(0,12))}</b></div><div><span>Solver context</span><b>${safe(String(fp.solver_hash||'').slice(0,12))}</b></div></div>${historyHtml}</article>`;
  }

  function renderInterpretation(payload){
    if(!payload)return `<article class="panel engineering-interpretation-card empty"><div class="section-head"><div><span class="eyebrow">ENGINEERING INTERPRETATION</span><h3>等待可解释的 ResultBundle</h3><p>完成一次结果提取后显示工程结论、Baseline 可比性、限制和下一动作。</p></div></div></article>`;
    const cmp=payload.comparability||null;
    const gate=cmp?.result_set_gate||{};
    const domains=(payload.domains||[]).map(domain=>`<article class="interpretation-domain ${statusClass(domain.status)}"><header><div><span>${safe(domain.label)}</span><b>${statusLabel(domain.status)}</b></div><p>${safe(domain.summary)}</p></header><div>${(domain.metrics||[]).slice(0,4).map(row=>`<div class="interpretation-metric"><span><b>${safe(row.label)}</b><small>${fmt(row.value,row.unit)}</small></span>${trendText(row)}</div>`).join('')}</div></article>`).join('');
    const limitations=(payload.limitations||[]).slice(0,6).map(row=>`<li class="${statusClass(row.severity)}"><b>${safe(row.code)}</b><span>${safe(row.message)}</span></li>`).join('');
    const findings=(payload.key_findings||[]).slice(0,6).map(row=>`<div class="interpretation-finding ${statusClass(row.trend)}"><span><b>${safe(row.label)}</b><small>${safe(row.domain)} · ${fmt(row.value,row.unit)}</small></span>${trendText(row)}</div>`).join('');
    const gateHtml=cmp?`<div class="comparability-gate ${statusClass(cmp.status)}"><div><span>Comparability Gate</span><b>${statusLabel(cmp.status)}</b></div><div><span>语义上下文</span><b>${gate.same_analysis_context===true?'一致':gate.same_analysis_context===false?'不一致':'待确认'}</b></div><div><span>运行工况</span><b>${gate.same_operating_point===true?'一致':'存在差异'}</b></div><div><span>求解设置</span><b>${gate.same_solver_settings===true?'一致':'存在差异'}</b></div></div>`:'';
    return `<article class="panel engineering-interpretation-card ${statusClass(payload.status)}"><div class="section-head"><div><span class="eyebrow">ENGINEERING INTERPRETATION · ${statusLabel(payload.status)}</span><h3>${safe(payload.headline)}</h3><p>${safe(payload.summary)}</p></div><div class="actions"><button type="button" data-open-interpreted-result="${safe(payload.result_bundle_id)}">查看 ResultBundle 证据</button></div></div>${gateHtml}${findings?`<section class="interpretation-findings"><h4>关键变化</h4>${findings}</section>`:''}${domains?`<section class="interpretation-domains">${domains}</section>`:''}${limitations?`<details class="interpretation-limitations" ${payload.status!=='FORMAL'?'open':''}><summary>限制与复核项 ${payload.limitations.length}</summary><ul>${limitations}</ul></details>`:''}<footer><small>${safe(payload.evidence?.interpretation_boundary||'')}</small></footer></article>`;
  }

  function render(overview,reference){const evaluation=overview?.reference_interpretation?.requirements_evaluation||null;const requirements=window.MCSEngineeringRequirements?.render?.(overview?.requirement_set||null,evaluation)||'';return `${requirements}${renderBaseline(overview,reference)}${renderInterpretation(overview?.reference_interpretation||null)}`}

  function bind(host,{projectId,reference,onRefresh,onOpenResult}){
    window.MCSEngineeringRequirements?.bind?.(host,{projectId,onRefresh});
    host?.querySelectorAll('[data-set-project-baseline]').forEach(button=>button.addEventListener('click',async()=>{
      const bundleId=button.dataset.setProjectBaseline;if(!bundleId||!projectId)return;
      const prior=button.textContent;button.disabled=true;button.textContent='正在冻结 Baseline…';
      try{
        await api(`/api/projects/${encodeURIComponent(projectId)}/baseline`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({result_bundle_id:bundleId,label:`工程 Baseline · Case ${reference?.id||''}`})});
        if(typeof notify==='function')notify('项目工程 Baseline 已更新','SUCCESS');
        await onRefresh?.();
      }catch(error){button.disabled=false;button.textContent=prior;if(typeof notify==='function')notify(error.message||String(error),'ERROR',9000)}
    }));
    host?.querySelectorAll('[data-open-interpreted-result]').forEach(button=>button.addEventListener('click',()=>onOpenResult?.(button.dataset.openInterpretedResult)));
  }

  window.MCSEngineeringInterpretation=Object.freeze({render,renderBaseline,renderInterpretation,bind,statusLabel});
})();
