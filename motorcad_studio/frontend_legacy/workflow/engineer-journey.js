/* V0.86-R visible engineering journey owner: Design -> Validate -> Decide. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>[...(r?.querySelectorAll?.(s)||[])];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={projectId:null,payload:null,loading:false,timer:null};
  const stageForTab=tab=>['workspace','solutions','templates','dashboard'].includes(tab)?'design':['analysisConfig','tasks','monitor'].includes(tab)?'validate':tab==='resultViewer'?(document.body.dataset.resultsMode==='overview'?'decide':'results'):tab==='dataFactory'?'decide':null;
  const activeTab=()=>q('.tab.active')?.id||'';
  async function apiCall(path){if(window.api)return window.api(path);const r=await fetch(path,{cache:'no-store'});if(!r.ok){const error=new Error(await r.text());error.status=r.status;throw error}return r.json()}
  function bindNav(){qa('[data-engineer-stage]').forEach(btn=>{if(btn.dataset.journeyBound)return;btn.dataset.journeyBound='1';btn.addEventListener('click',event=>{const blocked=btn.disabled||btn.getAttribute('aria-disabled')==='true'||btn.dataset.workflowGate==='BLOCKED'||btn.dataset.stageStatus==='BLOCKED';if(blocked){event.preventDefault();event.stopPropagation();window.toast?.(btn.title||'当前步骤尚未解锁','INFO',3500);return}const destination=btn.dataset.resultsDestination,projectId=window.MCSEngineeringContext?.get?.()?.projectId||window.MCSAppState?.activeProjectId;if(destination&&projectId&&window.MCSRouter?.navigate){const suffix=destination==='decision'?'results':'results/tasks';window.MCSRouter.navigate(`/app/projects/${encodeURIComponent(projectId)}/${suffix}`);return}const tab=btn.dataset.tab;if(tab&&window.showTab)window.showTab(tab)})})}
  function render(payload){
    if(!payload)return;state.payload=payload;bindNav();
    const byId=new Map((payload.stages||[]).map(x=>[x.id,x]));
    const current=stageForTab(activeTab())||payload.current_stage;
    qa('[data-engineer-stage]').forEach(btn=>{const stage=btn.dataset.engineerStage,row=byId.get(stage)||(stage==='results'?byId.get('decide'):null)||{};btn.classList.toggle('active',stage===current);const status=stage==='results'&&row.status==='CURRENT'&&current!=='results'?'COMPLETE':row.status||'PENDING';btn.dataset.stageStatus=status;const labels=stage==='results'?{label:'结果查看',summary:'查看工况结果、曲线、场数据和原始证据'}:row;btn.title=`${labels.label||''} · ${labels.summary||''}`;if(status==='BLOCKED'){btn.disabled=true;btn.setAttribute('aria-disabled','true');btn.dataset.workflowGate='BLOCKED'}let chip=q('.engineer-stage-chip-v086r',btn);if(!chip){chip=document.createElement('small');chip.className='engineer-stage-chip-v086r';btn.appendChild(chip)}chip.textContent={COMPLETE:'已完成',CURRENT:'当前',BLOCKED:'待解锁',PENDING:'待进入'}[status]||status||''});
    // GlobalWorkflowTruth is the final gate authority. Re-apply it after the
    // journey labels so a visual "待解锁" state can never race back to clickable.
    window.MCSGlobalWorkflowTruth?.sync?.();
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
