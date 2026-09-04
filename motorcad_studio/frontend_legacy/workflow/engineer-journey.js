/* V0.92 visible engineering journey owner: Design -> Compute -> Results -> Decision. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>[...(r?.querySelectorAll?.(s)||[])];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={projectId:null,payload:null,loading:false,timer:null};
  const stageForTab=tab=>{
    if(['workspace','solutions','templates','dashboard'].includes(tab))return'design';
    if(['analysisConfig','tasks','monitor'].includes(tab))return'validate';
    if(tab==='resultViewer')return document.body.dataset.resultsMode==='decision'?'decide':'results';
    if(tab==='dataFactory')return'decide';
    return null;
  };
  const activeTab=()=>q('.tab.active')?.id||'';
  async function apiCall(path){if(window.api)return window.api(path);const r=await fetch(path,{cache:'no-store'});if(!r.ok){const error=new Error(await r.text());error.status=r.status;throw error}return r.json()}

  function stageRoute(btn,projectId){
    const destination=btn.dataset.resultsDestination;
    if(destination==='viewer')return `/app/projects/${encodeURIComponent(projectId)}/results`;
    if(destination==='decision')return `/app/projects/${encodeURIComponent(projectId)}/decision`;
    return null;
  }

  function bindNav(){
    qa('[data-engineer-stage]').forEach(btn=>{
      if(btn.dataset.journeyBound)return;
      btn.dataset.journeyBound='1';
      btn.addEventListener('click',event=>{
        const blocked=btn.disabled||btn.getAttribute('aria-disabled')==='true'||btn.dataset.workflowGate==='BLOCKED'||btn.dataset.stageStatus==='BLOCKED';
        if(blocked){event.preventDefault();event.stopPropagation();window.toast?.(btn.title||'当前步骤尚未解锁','INFO',3500);return}
        const projectId=window.MCSEngineeringContext?.get?.()?.projectId||window.MCSAppState?.activeProjectId;
        const route=projectId?stageRoute(btn,projectId):null;
        if(route&&window.MCSRouter?.navigate){event.preventDefault();window.MCSRouter.navigate(route,{source:'engineer-journey:stage'});return}
        const tab=btn.dataset.tab;if(tab&&window.showTab)window.showTab(tab);
      });
    });
  }

  function displayStatus(stage,row,current){
    if(row?.status==='BLOCKED')return'BLOCKED';
    if(stage===current)return'CURRENT';
    if(current==='decide'&&stage==='results')return'COMPLETE';
    if(current==='results'&&stage==='decide')return row?.status==='COMPLETE'?'COMPLETE':'PENDING';
    return row?.status||'PENDING';
  }

  function render(payload){
    if(!payload)return;state.payload=payload;bindNav();
    const byId=new Map((payload.stages||[]).map(x=>[x.id,x]));
    const current=stageForTab(activeTab())||payload.current_stage;
    qa('[data-engineer-stage]').forEach(btn=>{
      const stage=btn.dataset.engineerStage,row=byId.get(stage)||{};
      btn.classList.toggle('active',stage===current);
      const status=displayStatus(stage,row,current);btn.dataset.stageStatus=status;
      btn.title=`${row.label||''} · ${row.summary||''}`;
      if(status==='BLOCKED'){
        btn.disabled=true;btn.setAttribute('aria-disabled','true');btn.dataset.workflowGate='BLOCKED';
      }else{
        btn.disabled=false;btn.removeAttribute('aria-disabled');delete btn.dataset.workflowGate;
      }
      let chip=q('.engineer-stage-chip-v086r',btn);
      if(!chip){chip=document.createElement('small');chip.className='engineer-stage-chip-v086r';btn.appendChild(chip)}
      chip.textContent={COMPLETE:'已完成',CURRENT:'当前',BLOCKED:'待解锁',PENDING:'待进入'}[status]||status||'';
    });
    // GlobalWorkflowTruth remains the final gate authority. Re-apply after local
    // labels so a visually blocked stage can never stay clickable.
    window.MCSGlobalWorkflowTruth?.sync?.();
    const cue=q('#engineerJourneyCueV086R');
    if(cue){
      const row=byId.get(current)||byId.get(payload.current_stage)||payload.stages?.[0],a=payload.primary_next_action||{};
      cue.classList.remove('hidden');
      cue.innerHTML=`<div><span class="eyebrow">当前工程步骤</span><b>${esc(row?.label||'设计')}</b><small>${esc(row?.summary||'')}</small></div><button type="button" class="primary" data-journey-primary>${esc(a.label||'继续')}</button>`;
      q('[data-journey-primary]',cue)?.addEventListener('click',()=>{
        if(a.route&&window.MCSRouter?.navigate)window.MCSRouter.navigate(a.route,{source:'engineer-journey:primary'});
        else if(a.stage==='design')window.showTab?.('workspace');
        else if(a.stage==='validate')window.showTab?.('analysisConfig');
        else if(a.stage==='decide'&&state.projectId)window.MCSRouter?.navigate?.(`/app/projects/${encodeURIComponent(state.projectId)}/decision`);
        else if(state.projectId)window.MCSRouter?.navigate?.(`/app/projects/${encodeURIComponent(state.projectId)}/results`);
      });
    }
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
