/* V0.87-D Engineering Scorecard. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={payload:null,loading:false,timer:null,lastKey:null};
  const ctx=()=>window.MCSEngineeringContext?.get?.()||{};
  async function apiCall(path){if(window.api)return window.api(path);const r=await fetch(path,{cache:'no-store'});if(!r.ok){let d;try{d=await r.json()}catch{d={detail:await r.text()}}throw new Error(typeof d?.detail==='string'?d.detail:(d?.detail?.message||JSON.stringify(d?.detail||d)))}return r.json()}
  function fmt(v){if(v===null||v===undefined||v==='')return '—';const n=Number(v);if(!Number.isFinite(n))return esc(v);const a=Math.abs(n);return a>=1000?n.toLocaleString(undefined,{maximumFractionDigits:1}):n.toLocaleString(undefined,{maximumFractionDigits:a<10?2:1})}
  const statusText=s=>({PASS:'满足',FAIL:'未满足',WARNING:'接近边界',OBSERVED:'已获得',MISSING:'缺少',UNIT_MISMATCH:'单位异常'}[s]||s||'—');
  const overallText=s=>({READY:'结果齐全',READY_WITH_WARNING:'可判断 · 有关注项',NEEDS_ATTENTION:'需要改进',INCOMPLETE:'结果不完整',NO_RESULTS:'等待验证'}[s]||s||'—');
  function render(p){const host=q('#engineeringScorecardV087D');if(!host)return;state.payload=p;if(!p){host.classList.add('hidden');return}host.classList.remove('hidden');const sum=p.summary||{};host.innerHTML=`
    <div class="engineering-scorecard-head-v087d"><div><span class="eyebrow">ENGINEERING SCORECARD</span><h2>${esc(p.starter?.short_label||'电机')} Rev.${esc(p.design_revision||'—')} 工程结果</h2><p>${esc(p.conclusion||'')}</p></div><span class="scorecard-overall-v087d ${String(p.overall_status||'').toLowerCase()}">${esc(overallText(p.overall_status))}</span></div>
    <div class="scorecard-summary-v087d"><div><b>${sum.observed_count||0}</b><span>已获得</span></div><div><b>${sum.warning_count||0}</b><span>关注项</span></div><div><b>${sum.fail_count||0}</b><span>未满足</span></div><div><b>${sum.missing_count||0}</b><span>缺少</span></div></div>
    <div class="scorecard-groups-v087d">${(p.groups||[]).map(g=>`<section><h3>${esc(g.group)}</h3><div class="scorecard-metrics-v087d">${(g.metrics||[]).map(m=>`<article class="scorecard-metric-v087d ${String(m.status||'').toLowerCase()}" title="${esc(m.description||'')}"><div><span>${esc(m.label)}</span><small>${esc(statusText(m.status))}</small></div><b>${fmt(m.display_value)} <em>${esc(m.display_unit||'')}</em></b>${m.requirement?.margin_percent!=null?`<small>裕度 ${fmt(m.requirement.margin_percent)}%</small>`:''}</article>`).join('')}</div></section>`).join('')}</div>
    <div class="scorecard-next-v087d"><span>${esc(p.next_action?.label||'继续')}</span><button type="button" class="primary" data-scorecard-next>${esc(p.next_action?.label||'继续')}</button></div>`;
    q('[data-scorecard-next]',host)?.addEventListener('click',()=>{if(p.next_action?.stage==='validate'){window.MCSRouter?.navigate?.(`/app/projects/${encodeURIComponent(p.project_id)}/simulation/analyses`)}else{q('[data-viewer-mode="batch"]')?.click?.();q('#analyticsTaskSelect')?.focus?.()}})
  }
  async function refresh({force=false,silent=false}={}){const c=ctx(),host=q('#engineeringScorecardV087D');if(!host)return null;if(!c.projectId||!c.motorRevisionId){host.classList.add('hidden');state.payload=null;return null}const key=`${c.projectId}:${c.motorRevisionId}`;if(state.loading)return state.payload;if(!force&&state.lastKey===key&&state.payload)return state.payload;state.loading=true;try{const p=await apiCall(`/api/projects/${encodeURIComponent(c.projectId)}/design-revisions/${encodeURIComponent(c.motorRevisionId)}/engineering-scorecard`);state.lastKey=key;render(p);return p}catch(e){state.lastKey=key;state.payload=null;host.classList.add('hidden');if(!silent)window.toast?.(`Engineering Scorecard 读取失败：${e.message||e}`,'WARNING',6000);return null}finally{state.loading=false}}
  function schedule(){if(!q('#resultViewer')?.classList.contains('active'))return;clearTimeout(state.timer);state.timer=setTimeout(()=>refresh({silent:true}),100)}
  window.addEventListener('mcs:engineering-context-changed',schedule);window.addEventListener('mcs:route-ready',schedule);document.addEventListener('DOMContentLoaded',schedule,{once:true});
  window.MCSEngineeringScorecard={state,refresh,render};
})();
