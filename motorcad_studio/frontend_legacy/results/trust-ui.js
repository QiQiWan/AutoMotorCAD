/* MotorCAD Studio V0.73-D — shared Results trust presentation authority. */
(() => {
  const safe=value=>typeof esc==='function'?esc(value??''):String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const statusLabel=value=>({PASS:'通过',FAIL:'失败',PENDING:'待完成',STALE:'已过期',UNQUALIFIED:'未资格',LEGACY:'历史兼容',NOT_APPLICABLE:'不适用'})[String(value||'').toUpperCase()]||String(value||'待确认');
  const engineeringLabel=value=>({QUALIFIED:'工程资格通过',DEVELOPMENT_ONLY:'仅开发验证',BLOCKED:'工程判断阻断',UNQUALIFIED:'原生资格未闭环',STALE_QUALIFICATION:'资格已过期',LEGACY_COMPATIBILITY:'历史兼容结果',REVIEW_REQUIRED:'需要工程审查'})[String(value||'')]||String(value||'待确认');
  const engineeringShort=value=>({QUALIFIED:'工程可用',DEVELOPMENT_ONLY:'开发验证',BLOCKED:'已阻断',UNQUALIFIED:'待资格',STALE_QUALIFICATION:'资格过期',LEGACY_COMPATIBILITY:'历史兼容',REVIEW_REQUIRED:'待审查'})[String(value||'')]||String(value||'待确认');
  const tone=value=>{const s=String(value||'').toUpperCase();if(s==='PASS'||s==='QUALIFIED')return'ready';if(s==='FAIL'||s==='BLOCKED')return'blocked';if(s==='NOT_APPLICABLE')return'neutral';return'pending'};
  function renderLadder(trust,{compact=false}={}){
    if(!trust)return `<div class="result-trust-empty-v073d">当前结果没有统一 Trust Snapshot。</div>`;
    const levels=(trust.levels||[]).map(row=>`<div class="result-trust-level-v073d ${tone(row.status)}" title="${safe(row.message||'')}"><span>L${Number(row.level||0)}</span><div><b>${safe(row.label||row.id)}</b>${compact?'':`<small>${safe(row.authority||'')}</small>`}</div><em>${safe(statusLabel(row.status))}</em></div>`).join('');
    return `<section class="result-trust-v073d ${compact?'compact':''}" data-result-trust-authority="ResultTrustSnapshotV1"><div class="result-trust-head-v073d"><div><span class="eyebrow">L1–L4 RESULT TRUST</span><b>${safe(engineeringLabel(trust.engineering_status))}</b>${compact?'':`<small>${trust.formal_recommendation?'当前证据可用于正式工程推荐':'当前证据仅可查看/审查，不应标记为正式工程推荐'}</small>`}</div><span class="result-trust-badge-v073d ${tone(trust.engineering_status)}">${safe(engineeringShort(trust.formal_recommendation?'QUALIFIED':trust.engineering_status||'REVIEW_REQUIRED'))}</span></div><div class="result-trust-levels-v073d">${levels}</div></section>`;
  }
  function renderBadge(trust){return trust?`<span class="result-trust-inline-v073d ${tone(trust.engineering_status)}">${safe(engineeringLabel(trust.engineering_status))}</span>`:'<span class="result-trust-inline-v073d pending">Trust 待确认</span>'}
  function metricValue(row){const value=row?.value;if(value===null||value===undefined||value==='')return'—';if(typeof value==='number'&&Number.isFinite(value)){const abs=Math.abs(value);return abs>=1000?value.toLocaleString(undefined,{maximumFractionDigits:1}):value.toLocaleString(undefined,{maximumFractionDigits:3})}return String(value)}
  function renderMetricCards(rows,{limit=8}={}){return (rows||[]).slice(0,limit).map(row=>`<article class="engineering-metric-v073d ${safe(row.group||'other')}"><span>${safe(row.label||row.id)}</span><b>${safe(metricValue(row))}</b><small>${safe(row.unit||'')}${row.status&&row.status!=='EXTRACTED'?` · ${safe(row.status)}`:''}</small></article>`).join('')}
  window.MCSResultsTrust=Object.freeze({renderLadder,renderBadge,renderMetricCards,statusLabel,engineeringLabel,engineeringShort});
})();
