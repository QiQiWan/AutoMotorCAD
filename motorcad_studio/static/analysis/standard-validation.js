/* V0.87-D Golden Motor standard validation package.
 * V0.89-G2.1 adds client-side single-flight execution so a slow Motor-CAD precheck
 * cannot be submitted repeatedly by rapid clicks or a render that replaces the button.
 */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={payload:null,loading:false,timer:null,lastKey:null,running:false,runPromise:null,runKey:null,submissionKey:null};
  const ctx=()=>window.MCSEngineeringContext?.get?.()||{};
  async function apiCall(path,opts={}){if(window.api)return window.api(path,opts);const r=await fetch(path,{cache:'no-store',headers:{'Content-Type':'application/json'},...opts});if(!r.ok){let d;try{d=await r.json()}catch{d={detail:await r.text()}}throw new Error(typeof d?.detail==='string'?d.detail:(d?.detail?.message||JSON.stringify(d?.detail||d)))}return r.json()}
  const statusLabel=s=>({READY:'就绪',NEEDS_INPUT:'需要确认',UNAVAILABLE:'不可用'}[s]||s||'—');
  const newSubmissionKey=()=>{try{return `svp-${crypto.randomUUID()}`}catch{return `svp-${Date.now()}-${Math.random().toString(16).slice(2)}`}};
  const progress=options=>window.MCSOperationProgress?.start?.(options)||{update(){return this},done(){return this},fail(){return this},close(){return this}};
  function syncRunButton(host=q('#standardValidationPackageV087D')){
    if(!host)return;
    const button=q('[data-svp-run]',host),ready=Boolean(state.payload?.ready_to_materialize);
    if(!button)return;
    button.disabled=state.running||!ready;
    button.textContent=state.running?'检查中…':'运行标准设计验证';
    button.setAttribute('aria-busy',state.running?'true':'false');
  }
  function render(p){const host=q('#standardValidationPackageV087D');if(!host)return;state.payload=p;if(!p){host.classList.add('hidden');host.innerHTML='';return}host.classList.remove('hidden');const steps=p.steps||[],ready=Boolean(p.ready_to_materialize),blockedCount=steps.filter(s=>!s.ready).length;host.innerHTML=`
    <div class="standard-validation-head-v087d"><div><span class="eyebrow">标准验证</span><h2>${esc(p.label||'标准设计验证')}</h2><p>${esc(p.starter?.label||'预制设计')} · Rev.${esc(p.design_revision||'—')} · ${steps.length} 个验证步骤</p></div><span class="status-chip ${ready?'success':'warning'}">${ready?'可以运行':`${blockedCount||1} 项待确认`}</span></div>
    <details class="standard-validation-details-v089g33"><summary><span>${ready?'验证链已准备完成':'验证链存在待处理项'}</span><small>展开查看 ${steps.length} 个标准验证步骤</small></summary><div class="standard-validation-steps-v087d">${steps.map(s=>`<div class="standard-validation-step-v087d ${s.ready?'ready':'blocked'}" title="${esc(s.when_to_use||'')}"><i>${s.sequence}</i><div><b>${esc(s.short_label||s.label)}</b><small>${esc(s.engineering_question||'')}</small><em>${esc(s.module||'')} · ${esc(statusLabel(s.status))}${s.expected_runtime?` · ${esc(s.expected_runtime)}`:''}</em></div><span>${s.ready?'✓':'!'}</span></div>`).join('')}</div></details>
    <div class="standard-validation-footer-v087d"><div><b>结果输出</b><span>工程指标 ${(p.scorecard_coverage?.covered_count||0)}/${(p.scorecard_coverage?.metric_count||0)} 已覆盖${p.scorecard_coverage?.complete?'。':'，仍有缺口。'}</span></div><div class="actions"><button type="button" data-svp-preview ${state.running?'disabled':''}>刷新验证计划</button><button class="primary" type="button" data-svp-run ${(ready&&!state.running)?'':'disabled'}>${state.running?'检查中…':'运行标准设计验证'}</button></div></div>
    <div data-svp-status class="analysis-inline-status-v076 ${state.running?'running':''}">${state.running?'正在执行 Studio + Motor-CAD 计算前检查，请勿重复提交…':(ready?'当前设计已具备标准验证计划。':'存在不可用或待确认的分析步骤，请先处理。')}</div>`;
    q('[data-svp-preview]',host)?.addEventListener('click',()=>refresh({force:true}));
    q('[data-svp-run]',host)?.addEventListener('click',run);
    syncRunButton(host);
  }
  function run(){
    if(state.runPromise)return state.runPromise;
    const c=ctx();
    if(!c.projectId||!c.motorRevisionId||!state.payload)return Promise.resolve(null);
    const runKey=`${c.projectId}:${c.motorRevisionId}`;
    state.running=true;state.runKey=runKey;state.submissionKey=newSubmissionKey();
    render(state.payload);
    window.MCSActionReadiness?.scheduleRefresh?.();
    const host=q('#standardValidationPackageV087D'),button=q('[data-svp-run]',host),op=progress({id:`standard-validation-${c.motorRevisionId}`,label:'运行标准设计验证',stage:'冻结标准分析',detail:'准备 Studio + Motor-CAD 计算前检查',percent:6,button,failDelay:6000});
    const promise=(async()=>{
      const status=q('[data-svp-status]',q('#standardValidationPackageV087D'));
      try{
        if(status){status.textContent='正在冻结标准分析配置并执行 Studio + Motor-CAD 计算前检查…';status.className='analysis-inline-status-v076 running'}
        op.update({percent:null,stage:'Motor-CAD 原生检查',detail:'正在检查标准验证链；耗时取决于 Motor-CAD 启动与模型载入'});
        const result=await apiCall(`/api/projects/${encodeURIComponent(c.projectId)}/design-revisions/${encodeURIComponent(c.motorRevisionId)}/standard-validation-package/execute`,{method:'POST',body:JSON.stringify({decisions_by_analysis:{},run_native_precheck:true,reuse_cache:true,quality_profile:'standard',submission_key:state.submissionKey})});
        if(result.execution_status==='BLOCKED'){
          const blocked=(result.executions||[]).find(x=>x.execution_status==='BLOCKED');
          const message=blocked?.blocker?.message||blocked?.blocker?.code||'标准验证被计算前检查阻断';
          if(status){status.textContent=message;status.className='analysis-inline-status-v076 error'}
          op.fail(message);window.toast?.(message,'WARNING',9000);return result;
        }
        const tasks=(result.executions||[]).filter(x=>x.task_id);
        if(status){status.textContent=`已提交 ${tasks.length} 个标准分析任务；Motor-CAD 将按 Worker / 许可证容量排队执行。`;status.className='analysis-inline-status-v076 success'}
        op.done(`已提交 ${tasks.length} 个标准分析任务`);window.toast?.(`标准设计验证已提交：${tasks.length} 个任务，将按运行时容量排队`,'SUCCESS',7000);
        if(tasks[0]?.task_id){window.MCSEngineeringContext?.setExecution?.(tasks[0],{taskId:tasks[0].task_id,source:'standard-validation'});window.MCSRouter?.navigate?.(`/app/projects/${encodeURIComponent(c.projectId)}/simulation/monitor/${encodeURIComponent(tasks[0].task_id)}`)}
        return result;
      }catch(e){
        const currentHost=q('#standardValidationPackageV087D'),currentStatus=q('[data-svp-status]',currentHost);
        if(currentStatus){currentStatus.textContent=e.message||String(e);currentStatus.className='analysis-inline-status-v076 error'}
        op.fail(e.message||String(e));window.toast?.(e.message||String(e),'ERROR',9000);throw e;
      }finally{
        if(state.runKey===runKey){state.running=false;state.runKey=null;state.submissionKey=null}
        state.runPromise=null;syncRunButton();const preview=q('[data-svp-preview]');if(preview)preview.disabled=false;window.MCSActionReadiness?.scheduleRefresh?.();
      }
    })();
    state.runPromise=promise;return promise;
  }
  async function refresh({force=false,silent=false}={}){const c=ctx(),host=q('#standardValidationPackageV087D');if(!host)return null;if(!c.projectId||!c.motorRevisionId){host.classList.add('hidden');host.innerHTML='';state.payload=null;return null}const key=`${c.projectId}:${c.motorRevisionId}`;if(state.loading)return state.payload;if(!force&&state.lastKey===key&&state.payload)return state.payload;state.loading=true;const button=q('[data-svp-preview]',host),op=(!silent||force)?progress({id:`standard-validation-refresh-${c.motorRevisionId}`,label:'刷新标准验证计划',stage:'读取验证合同',detail:'同步设计版本、标准分析步骤与结果覆盖度',percent:16,button}):null;try{op?.update?.({percent:52,stage:'汇总验证步骤',detail:'检查各分析模块的可用性与必要输入'});const p=await apiCall(`/api/projects/${encodeURIComponent(c.projectId)}/design-revisions/${encodeURIComponent(c.motorRevisionId)}/standard-validation-package`);state.lastKey=key;render(p);op?.done?.('标准验证计划已同步');return p}catch(e){state.lastKey=key;state.payload=null;host.classList.add('hidden');host.innerHTML='';op?.fail?.(e.message||String(e));if(!silent&&e?.status!==422)window.toast?.(`标准验证计划读取失败：${e.message||e}`,'WARNING',6000);return null}finally{state.loading=false}}
  function schedule(){if(!q('#analysisConfig')?.classList.contains('active'))return;clearTimeout(state.timer);state.timer=setTimeout(()=>refresh({silent:true}),100)}
  window.addEventListener('mcs:engineering-context-changed',schedule);window.addEventListener('mcs:route-ready',schedule);document.addEventListener('DOMContentLoaded',schedule,{once:true});
  window.MCSStandardValidation={state,refresh,render,run};
})();
