/* V0.92 Engineering Decision Cockpit — explicit evidence -> requirements -> conclusion flow. */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stateLocal={projectId:null,payload:null,loading:false,timer:null,requestToken:0,controller:null};
  const lang=()=>{const html=String(document.documentElement.lang||'').toLowerCase();if(html.startsWith('zh'))return'zh';if(html.startsWith('en'))return'en';return window.MCS_I18N?.language||'zh'};
  const txt=(zh,en)=>lang()==='en'?(en||zh):zh;
  const outcomeMeta=value=>({
    ACCEPTABLE:{label:txt('建议通过','Acceptable'),className:'ready'},
    ACCEPTABLE_WITH_WARNING:{label:txt('通过但有预警','Acceptable with warning'),className:'attention'},
    NOT_ACCEPTABLE:{label:txt('建议调整设计','Design changes required'),className:'blocked'},
    NOT_READY:{label:txt('暂不能判定','Not ready'),className:'attention'}
  }[String(value||'NOT_READY')]||{label:txt('暂不能判定','Not ready'),className:'attention'});
  const checkLabel=status=>({PASS:txt('已具备','Ready'),FAIL:txt('需要处理','Needs attention'),MISSING:txt('缺失','Missing')}[String(status||'').toUpperCase()]||String(status||'—'));
  const resultStatusLabel=value=>({VALID:txt('结果可用','Valid'),WARNING:txt('结果有提示','Warning'),INVALID:txt('结果不可用','Invalid'),UNVERIFIED:txt('待结果验证','Unverified'),NOT_ASSESSED:txt('待评估','Not assessed'),QUALIFIED:txt('正式资格通过','Qualified'),REVIEW_ONLY:txt('仅供复核','Review only'),BLOCKED:txt('资格阻断','Blocked')}[String(value||'').toUpperCase()]||String(value||'—'));
  function currentProjectId(){return window.MCSResultContext?.current?.()?.projectId||window.MCSEngineeringContext?.get?.()?.projectId||(typeof state!=='undefined'?state.activeProjectId:null)||null}
  async function apiCall(path,{signal}={}){if(window.api)return window.api(path,signal?{signal}:undefined);const r=await fetch(path,{cache:'no-store',signal});if(!r.ok){let d;try{d=await r.json()}catch{d={detail:await r.text()}}throw new Error(typeof d?.detail==='string'?d.detail:(d?.detail?.message||JSON.stringify(d?.detail||d)))}return r.json()}

  function renderLoading(){const host=q('#engineeringDecisionCockpitV086R');if(!host)return;host.classList.remove('hidden');host.dataset.state='loading';host.innerHTML=`<div class="decision-loading-v089g3"><span class="spinner-dot"></span><div><b>${txt('正在生成工程判断…','Building engineering decision…')}</b><span>${txt('读取结果证据、工程要求和判定完整性。','Reading result evidence, engineering requirements and decision completeness.')}</span></div></div>`}
  function renderFallback({title,message,projectId=null,retry=true}={}){const host=q('#engineeringDecisionCockpitV086R');if(!host)return;host.classList.remove('hidden');host.dataset.state='degraded';host.innerHTML=`<div class="decision-cockpit-head-v086r"><div><span class="eyebrow">${txt('工程判断','ENGINEERING DECISION')}</span><h2>${esc(title||txt('工程判断暂不可用','Engineering decision is temporarily unavailable'))}</h2><p>${esc(message||txt('可以继续查看计算结果，决策摘要恢复后再完成正式判断。','Results remain available; complete the formal decision after the summary recovers.'))}</p></div><span class="decision-state-v086r attention">${txt('信息不完整','Partial')}</span></div>${retry?`<div class="decision-primary-v086r"><span>${txt('结果查看不会被该问题阻塞。','Result viewing is not blocked by this issue.')}</span><button type="button" data-decision-retry>${txt('重新读取','Retry')}</button></div>`:''}`;q('[data-decision-retry]',host)?.addEventListener('click',()=>refresh(projectId,{silent:false,force:true}))}

  function render(p){
    const host=q('#engineeringDecisionCockpitV086R');if(!host||!p)return;host.classList.remove('hidden');stateLocal.payload=p;host.dataset.state=p.degraded?'degraded':'ready';
    const req=p.requirement_summary||{},result=p.latest_result||null,blockers=p.blockers||[],meta=outcomeMeta(p.decision_outcome);
    const checks=Object.fromEntries((p.checks||[]).map(row=>[row.id,row]));
    const reqMain=p.requirements_configured?txt(`${Number(req.pass||0)} 项满足 · ${Number(req.fail||0)} 项未满足`,`${Number(req.pass||0)} met · ${Number(req.fail||0)} failed`):txt('尚未定义工程要求','Requirements not defined');
    const reqSub=p.requirements_configured?txt(`必须指标 ${Number(req.hard_constraints||0)} 项 · 缺失 ${Number(req.missing||0)} 项 · 预警 ${Number(req.warning||0)} 项`,`Required ${Number(req.hard_constraints||0)} · missing ${Number(req.missing||0)} · warnings ${Number(req.warning||0)}`):txt('先定义项目必须达到的性能边界。','Define the project performance boundaries first.');
    const resultMain=result?txt('已有可追溯计算结果','Traceable result available'):txt('尚无计算结果','No result yet');
    const resultSub=result?`${esc(resultStatusLabel(result.quality_status))} · ${esc(resultStatusLabel(result.qualification_status))}`:txt('完成一次有效计算后生成。','Generated after a valid solve.');
    const blockerList=blockers.length?`<ul class="decision-blocker-list-v092">${blockers.slice(0,5).map(row=>`<li><span>${esc(row.message||row.code)}</span></li>`).join('')}</ul>`:`<div class="decision-no-blocker-v092">${txt('当前没有阻止正式判断的缺项。','No issue currently blocks a formal decision.')}</div>`;
    host.innerHTML=`<div class="decision-cockpit-head-v086r"><div><span class="eyebrow">${txt('工程判断','ENGINEERING DECISION')}</span><h2>${esc(p.decision_headline||txt('当前设计工程判断','Current design decision'))}</h2><p>${esc(p.decision_summary||'')}</p></div><span class="decision-state-v086r ${meta.className}">${esc(meta.label)}</span></div>
      <div class="decision-cockpit-grid-v086r decision-cockpit-grid-v092">
        <div class="${String(checks.result?.status||'').toLowerCase()}"><span>${txt('1 · 结果证据','1 · Result evidence')}</span><b>${resultMain}</b><small>${resultSub}</small><em>${esc(checkLabel(checks.result?.status))}</em></div>
        <div class="${String(checks.requirements?.status||'').toLowerCase()}"><span>${txt('2 · 工程要求','2 · Engineering requirements')}</span><b>${esc(reqMain)}</b><small>${esc(reqSub)}</small><em>${esc(checkLabel(checks.requirements?.status))}</em></div>
        <div class="${String(checks.evidence?.status||'').toLowerCase()}"><span>${txt('3 · 判定完整性','3 · Decision completeness')}</span><b>${esc(meta.label)}</b><small>${txt('只有结果证据和工程要求都具备时，才形成正式结论。','A formal conclusion requires both result evidence and engineering requirements.')}</small><em>${esc(checkLabel(checks.evidence?.status))}</em></div>
      </div>
      <div class="decision-attention-v092"><div><b>${blockers.length?txt('需要处理','Needs attention'):txt('判定依据完整','Decision basis complete')}</b>${blockerList}</div><button type="button" class="primary" data-decision-primary>${esc(p.primary_next_action?.label||txt('继续','Continue'))}</button></div>`;
    q('[data-decision-primary]',host)?.addEventListener('click',()=>handleAction(p.primary_next_action,p));
  }

  function handleAction(action,payload){
    const id=action?.id,projectId=payload?.project_id||currentProjectId();
    if(id==='DEFINE_REQUIREMENTS'&&projectId){window.MCSEngineeringRequirements?.openEditor?.(projectId,async()=>{await refresh(projectId,{silent:true,force:true});window.dispatchEvent(new CustomEvent('mcs:engineering-context-changed',{detail:{source:'requirements:saved'}}))});return}
    if(id==='REVIEW_REQUIREMENT_FAILURES'){q('#decisionRequirementsV092')?.scrollIntoView?.({behavior:'smooth',block:'start'});return}
    if(action?.route)window.MCSRouter?.navigate?.(action.route,{source:'decision-cockpit:primary'});
  }

  async function refresh(projectId=null,{silent=false,force=false}={}){
    projectId=projectId||currentProjectId();
    if(!projectId){stateLocal.payload=null;renderFallback({title:txt('尚未建立项目上下文','Project context is not ready'),message:txt('返回项目后再进入“决策”。','Return to a project and open Decision again.'),retry:false});return null}
    if(stateLocal.loading&&!force)return stateLocal.payload;
    stateLocal.controller?.abort();stateLocal.controller=new AbortController();const token=++stateLocal.requestToken;stateLocal.loading=true;renderLoading();const timeout=setTimeout(()=>stateLocal.controller?.abort('decision-summary-timeout'),7000);
    try{const p=await apiCall(`/api/projects/${encodeURIComponent(projectId)}/decision-cockpit`,{signal:stateLocal.controller.signal});if(token!==stateLocal.requestToken)return null;stateLocal.projectId=projectId;render(p);return p}
    catch(e){if(token!==stateLocal.requestToken)return null;const timeoutAbort=stateLocal.controller?.signal?.aborted;stateLocal.payload=null;renderFallback({projectId,title:timeoutAbort?txt('工程判断读取超时','Decision summary timed out'):txt('工程判断暂不可用','Decision summary temporarily unavailable'),message:timeoutAbort?txt('服务超过 7 秒未返回，已切换为降级显示。','The service did not return within 7 seconds; degraded display is shown.'):String(e?.message||e)});if(!silent&&!timeoutAbort)window.toast?.(`${txt('工程判断读取失败','Decision summary failed')}：${e.message||e}`,'WARNING',6000);return null}
    finally{clearTimeout(timeout);if(token===stateLocal.requestToken)stateLocal.loading=false}
  }
  function schedule(){if(!q('#resultViewer')?.classList.contains('active')||document.body.dataset.resultsMode!=='decision')return;clearTimeout(stateLocal.timer);stateLocal.timer=setTimeout(()=>refresh(null,{silent:true}),80)}
  window.addEventListener('mcs:route-ready',schedule);window.addEventListener('mcs:engineering-context-changed',schedule);document.addEventListener('mcs-language-change',()=>{if(document.body.dataset.resultsMode==='decision'){if(stateLocal.payload)render(stateLocal.payload);else schedule()}});document.addEventListener('DOMContentLoaded',schedule,{once:true});
  window.MCSDecisionCockpit={state:stateLocal,refresh,render,currentProjectId};
})();
