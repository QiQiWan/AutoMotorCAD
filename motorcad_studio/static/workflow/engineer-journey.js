/* V0.86-R visible engineering journey owner: Design -> Validate -> Decide. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>[...(r?.querySelectorAll?.(s)||[])];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={projectId:null,payload:null,loading:false,timer:null};
  const stageForTab=tab=>['workspace','solutions','templates','dashboard'].includes(tab)?'design':['analysisConfig','tasks','monitor'].includes(tab)?'validate':['resultViewer','dataFactory'].includes(tab)?'decide':null;
  const activeTab=()=>q('.tab.active')?.id||'';
  async function apiCall(path){if(window.api)return window.api(path);const r=await fetch(path,{cache:'no-store'});if(!r.ok){const error=new Error(await r.text());error.status=r.status;throw error}return r.json()}
  function bindNav(){qa('[data-engineer-stage]').forEach(btn=>{if(btn.dataset.journeyBound)return;btn.dataset.journeyBound='1';btn.addEventListener('click',()=>{const tab=btn.dataset.tab;if(tab&&window.showTab)window.showTab(tab)})})}
  function render(payload){
    if(!payload)return;state.payload=payload;bindNav();
    const byId=new Map((payload.stages||[]).map(x=>[x.id,x]));
    const current=stageForTab(activeTab())||payload.current_stage;
    qa('[data-engineer-stage]').forEach(btn=>{const row=byId.get(btn.dataset.engineerStage)||{};btn.classList.toggle('active',btn.dataset.engineerStage===current);btn.dataset.stageStatus=row.status||'PENDING';btn.title=`${row.label||''} · ${row.summary||''}`;let chip=q('.engineer-stage-chip-v086r',btn);if(!chip){chip=document.createElement('small');chip.className='engineer-stage-chip-v086r';btn.appendChild(chip)}chip.textContent={COMPLETE:'已完成',CURRENT:'当前',BLOCKED:'待解锁'}[row.status]||row.status||''});
    const cue=q('#engineerJourneyCueV086R');if(cue){const row=byId.get(payload.current_stage)||payload.stages?.[0],a=payload.primary_next_action||{};cue.classList.remove('hidden');cue.innerHTML=`<div><span class="eyebrow">当前工程步骤</span><b>${esc(row?.label||'设计')}</b><small>${esc(row?.summary||'')}</small></div><button type="button" class="primary" data-journey-primary>${esc(a.label||'继续')}</button>`;q('[data-journey-primary]',cue)?.addEventListener('click',()=>{if(a.route&&window.MCSRouter?.navigate)window.MCSRouter.navigate(a.route);else if(a.stage==='design')window.showTab?.('workspace');else if(a.stage==='validate')window.showTab?.('analysisConfig');else window.showTab?.('resultViewer')})}
  }
  async function refresh(projectId=null,{silent=false}={}){
    projectId=projectId||window.MCSAppState?.activeProjectId||window.MCSEngineeringContext?.get?.().projectId;
    if(!projectId||!window.MCSAppState?.bootstrapReady)return null;
    if(state.loading)return state.payload;
    state.loading=true;
    try{
      const payload=await apiCall(`/api/projects/${encodeURIComponent(projectId)}/engineer-journey`);
      state.projectId=projectId;render(payload);return payload;
    }catch(e){
      if(Number(e?.status)===404){
        const ctx=window.MCSEngineeringContext?.get?.();
        if(ctx?.projectId===projectId)window.MCSEngineeringContext?.invalidate?.('project',{source:'engineer-journey:stale-project'});
        const cue=q('#engineerJourneyCueV086R');if(cue){cue.classList.add('hidden');cue.replaceChildren()}
        state.projectId=null;state.payload=null;return null;
      }
      if(!silent)window.toast?.(`工程流程读取失败：${e.message||e}`,'WARNING',6000);
      return null;
    }finally{state.loading=false}
  }
  function schedule(){clearTimeout(state.timer);state.timer=setTimeout(()=>refresh(null,{silent:true}),80)}
  window.addEventListener('mcs:bootstrap-ready',schedule);
  window.addEventListener('mcs:engineering-context-changed',schedule);
  window.addEventListener('mcs:route-ready',schedule);
  window.addEventListener('mcs:canonical-page-mounted',schedule);
  window.MCSEngineerJourney={state,refresh,render};
})();
