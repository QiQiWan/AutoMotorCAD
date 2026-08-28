/* V0.89-G3.1 Engineering Decision Summary state convergence. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stateLocal={projectId:null,payload:null,loading:false,timer:null,requestToken:0,controller:null};
  const lang=()=>window.MCS_I18N?.language||'zh';
  const txt=(zh,en)=>lang()==='en'?(en||zh):zh;
  function currentProjectId(){
    return window.MCSResultContext?.current?.()?.projectId
      || window.MCSEngineeringContext?.get?.()?.projectId
      || (typeof state!=='undefined'?state.activeProjectId:null)
      || window.localStorage?.getItem?.('motorcad-studio-active-project')
      || null;
  }
  async function apiCall(path,{signal}={}){
    if(window.api)return window.api(path,signal?{signal}:undefined);
    const r=await fetch(path,{cache:'no-store',signal});
    if(!r.ok){let d;try{d=await r.json()}catch{d={detail:await r.text()}}throw new Error(typeof d?.detail==='string'?d.detail:(d?.detail?.message||JSON.stringify(d?.detail||d)))}
    return r.json();
  }
  function renderLoading(){
    const host=q('#engineeringDecisionCockpitV086R');if(!host)return;
    host.dataset.state='loading';
    host.innerHTML=`<div class="decision-loading-v089g3"><span class="spinner-dot"></span><div><b>${txt('正在形成工程决策摘要…','Building engineering decision summary…')}</b><span>${txt('系统正在读取当前项目、最新结果和工程要求。','Reading the current project, latest results and engineering requirements.')}</span></div></div>`;
  }
  function renderFallback({title,message,projectId=null,retry=true}={}){
    const host=q('#engineeringDecisionCockpitV086R');if(!host)return;
    host.dataset.state='degraded';
    host.innerHTML=`<div class="decision-cockpit-head-v086r"><div><span class="eyebrow">${txt('工程决策','ENGINEERING DECISION')}</span><h2>${esc(title||txt('当前只能形成简化决策摘要','A reduced decision summary is available'))}</h2><p>${esc(message||txt('详细决策证据暂未就绪，已有结果仍可继续查看。','Detailed decision evidence is not ready; available results remain accessible.'))}</p></div><span class="decision-state-v086r attention">${txt('信息不完整','Partial')}</span></div><div class="decision-primary-v086r"><div><span>${txt('可继续查看当前计算结果；系统不会因摘要缺失阻塞结果浏览。','You can continue reviewing available results; a missing summary does not block result review.')}</span></div>${retry?`<button type="button" data-decision-retry>${txt('重新生成摘要','Retry summary')}</button>`:''}</div>`;
    q('[data-decision-retry]',host)?.addEventListener('click',()=>refresh(projectId,{silent:false,force:true}));
  }
  function render(p){
    const host=q('#engineeringDecisionCockpitV086R');if(!host||!p)return;
    stateLocal.payload=p;host.dataset.state=p.degraded?'degraded':'ready';
    const req=p.requirement_summary||{},result=p.latest_result||null,blockers=p.blockers||[];
    const status=!result?txt('等待结果','Waiting for results'):p.can_decide?(blockers.length?txt('可判断 · 有关注项','Decision-ready · attention items'):txt('可判断','Decision-ready')):txt('需要处理','Needs attention');
    const reqMain=req.configured!=null?txt(`${Number(req.pass||0)}/${Number(req.configured||0)} 满足`,`${Number(req.pass||0)}/${Number(req.configured||0)} met`):txt('未配置或待评估','Not configured / pending');
    const reqSub=req.fail?txt(`${req.fail} 项未满足`,`${req.fail} failed`):req.warning?txt(`${req.warning} 项接近边界`,`${req.warning} near limit`):'—';
    const blockersHtml=blockers.length?blockers.slice(0,3).map(x=>`<span>${esc(x.message)}</span>`).join(''):!result?`<span>${txt('完成一次有效分析后，这里会自动形成工程判断与下一步建议。','Run one valid analysis to generate an engineering decision and next-step recommendation.')}</span>`:`<span>${txt('已有结果可用于后续对比、参数扫描或优化决策。','Available results can support comparison, parameter studies or optimization decisions.')}</span>`;
    host.innerHTML=`<div class="decision-cockpit-head-v086r"><div><span class="eyebrow">${txt('工程决策','ENGINEERING DECISION')}</span><h2>${txt('当前设计能否做出判断？','Can the current design support a decision?')}</h2><p>${txt('先看结论、阻断项和下一步；详细证据按需展开。','Review the conclusion, blockers and next action first; expand detailed evidence as needed.')}</p></div><span class="decision-state-v086r ${p.can_decide?'ready':'attention'}">${esc(status)}</span></div><div class="decision-cockpit-grid-v086r"><div><span>${txt('最新结果','Latest result')}</span><b>${result?esc(String(result.id).slice(0,18)):txt('尚无','None')}</b><small>${result?`${esc(result.quality_status||'')} · ${esc(result.qualification_status||'')}`:txt('完成一次有效分析后生成','Generated after a valid analysis')}</small></div><div><span>${txt('工程要求','Engineering requirements')}</span><b>${esc(reqMain)}</b><small>${esc(reqSub)}</small></div><div><span>${txt('需要处理','Needs attention')}</span><b>${blockers.length}</b><small>${esc(blockers[0]?.message||txt('当前没有阻断项','No blocking issue'))}</small></div></div><div class="decision-primary-v086r"><div>${blockersHtml}</div><button type="button" class="primary" data-decision-primary>${esc(p.primary_next_action?.label||txt('继续','Continue'))}</button></div>`;
    q('[data-decision-primary]',host)?.addEventListener('click',()=>{const route=p.primary_next_action?.route;if(route)window.MCSRouter?.navigate?.(route)});
  }
  async function refresh(projectId=null,{silent=false,force=false}={}){
    projectId=projectId||currentProjectId();
    if(!projectId){
      stateLocal.payload=null;
      renderFallback({title:txt('尚未建立项目上下文','Project context is not ready'),message:txt('返回项目后再进入结果页，工程摘要会自动恢复。','Return to a project and reopen results; the summary will recover automatically.'),retry:false});
      return null;
    }
    if(stateLocal.loading&&!force)return stateLocal.payload;
    stateLocal.controller?.abort();
    stateLocal.controller=new AbortController();
    const token=++stateLocal.requestToken;
    stateLocal.loading=true;renderLoading();
    const timeout=setTimeout(()=>stateLocal.controller?.abort('decision-summary-timeout'),5000);
    try{
      const p=await apiCall(`/api/projects/${encodeURIComponent(projectId)}/decision-cockpit`,{signal:stateLocal.controller.signal});
      if(token!==stateLocal.requestToken)return null;
      stateLocal.projectId=projectId;render(p);window.MCSManufacturingRobustness?.refresh?.(projectId,{silent:true});return p;
    }catch(e){
      if(token!==stateLocal.requestToken)return null;
      const timeoutAbort=stateLocal.controller?.signal?.aborted;
      stateLocal.payload=null;
      renderFallback({projectId,title:timeoutAbort?txt('工程决策摘要生成超时','Decision summary timed out'):txt('工程决策摘要暂不可用','Decision summary temporarily unavailable'),message:timeoutAbort?txt('摘要服务超过 5 秒未返回，已切换为降级显示。','The summary did not return within 5 seconds; the page switched to degraded mode.'):String(e?.message||e)});
      if(!silent&&!timeoutAbort)window.toast?.(`${txt('设计结论读取失败','Decision summary failed')}: ${e.message||e}`,'WARNING',6000);
      return null;
    }finally{clearTimeout(timeout);if(token===stateLocal.requestToken)stateLocal.loading=false}
  }
  function schedule(){
    if(!q('#resultViewer')?.classList.contains('active'))return;
    clearTimeout(stateLocal.timer);stateLocal.timer=setTimeout(()=>refresh(null,{silent:true}),80);
  }
  window.addEventListener('mcs:route-ready',schedule);
  window.addEventListener('mcs:engineering-context-changed',schedule);
  document.addEventListener('mcs-language-change',()=>{if(stateLocal.payload)render(stateLocal.payload);else if(q('#resultViewer')?.classList.contains('active'))schedule()});
  document.addEventListener('DOMContentLoaded',schedule,{once:true});
  window.MCSDecisionCockpit={state:stateLocal,refresh,render,currentProjectId};
})();
