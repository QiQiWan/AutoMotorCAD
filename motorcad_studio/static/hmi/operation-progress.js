/* MotorCAD Studio V0.89-G3.3 — global operation progress / busy feedback. */
(() => {
  const active=new Map();
  const now=()=>performance?.now?.()??Date.now();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const uid=()=>`op-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,8)}`;
  function dock(){let root=document.querySelector('#mcsOperationProgressDock');if(root)return root;root=document.createElement('aside');root.id='mcsOperationProgressDock';root.className='mcs-operation-progress-dock';root.setAttribute('aria-live','polite');root.setAttribute('aria-label','后台操作进度');document.body.appendChild(root);return root}
  function restoreButton(op){const button=op.button;if(!button)return;button.classList.remove('mcs-button-busy-g33');button.removeAttribute('aria-busy');if(op.disableButton&&button.dataset.mcsOpOwner===op.id){button.disabled=Boolean(op.originalDisabled);delete button.dataset.mcsOpOwner}}
  function bindButton(op){const button=op.button;if(!button)return;op.originalDisabled=button.disabled;button.dataset.mcsOpOwner=op.id;button.setAttribute('aria-busy','true');button.classList.add('mcs-button-busy-g33');if(op.disableButton)button.disabled=true}
  function elapsed(op){return Math.max(0,(now()-op.startedAt)/1000)}
  function paint(op){const root=dock(),percent=Number.isFinite(op.percent)?Math.max(0,Math.min(100,Number(op.percent))):null,finished=['done','failed'].includes(op.state);let card=root.querySelector(`[data-mcs-op="${CSS.escape(op.id)}"]`);if(!card){card=document.createElement('article');card.dataset.mcsOp=op.id;card.className='mcs-operation-progress-card';root.prepend(card)}card.className=`mcs-operation-progress-card ${op.state} ${percent===null?'indeterminate':'determinate'}`;card.innerHTML=`<div class="mcs-operation-progress-head"><span class="mcs-operation-progress-orbit" aria-hidden="true"><i></i></span><div><b>${esc(op.label)}</b><small>${esc(op.stage||op.detail||'处理中')}</small></div><em>${finished?(op.state==='done'?'完成':'失败'):(percent===null?'运行中':`${Math.round(percent)}%`)}</em></div><div class="mcs-operation-progress-track"><i style="${percent===null?'':`width:${percent}%`}"></i></div><div class="mcs-operation-progress-foot"><span>${esc(op.detail||'')}</span><time>${elapsed(op).toFixed(elapsed(op)>=10?0:1)} s</time></div>`}
  function scheduleRemoval(op,delay=1600){clearTimeout(op.removeTimer);op.removeTimer=setTimeout(()=>{const card=document.querySelector(`[data-mcs-op="${CSS.escape(op.id)}"]`);card?.classList.add('leaving');setTimeout(()=>card?.remove(),260);active.delete(op.id)},delay)}
  function start(options={}){const op={id:String(options.id||uid()),label:String(options.label||'正在处理'),detail:String(options.detail||''),stage:String(options.stage||''),percent:Number.isFinite(options.percent)?Number(options.percent):null,state:'running',startedAt:now(),button:options.button||null,disableButton:options.disableButton!==false,originalDisabled:false,removeTimer:null};const existing=active.get(op.id);if(existing)return existing.api;bindButton(op);active.set(op.id,op);paint(op);const ticker=setInterval(()=>{if(op.state==='running')paint(op);else clearInterval(ticker)},500);op.ticker=ticker;const api={id:op.id,update(update={}){if(op.state!=='running')return api;if(update.label!==undefined)op.label=String(update.label);if(update.detail!==undefined)op.detail=String(update.detail);if(update.stage!==undefined)op.stage=String(update.stage);if(update.percent===null)op.percent=null;else if(Number.isFinite(update.percent))op.percent=Number(update.percent);paint(op);return api},done(detail=''){if(op.state!=='running')return api;op.state='done';op.percent=100;if(detail)op.detail=String(detail);restoreButton(op);clearInterval(op.ticker);paint(op);scheduleRemoval(op,options.doneDelay??1700);return api},fail(detail=''){if(op.state!=='running')return api;op.state='failed';if(detail)op.detail=String(detail);restoreButton(op);clearInterval(op.ticker);paint(op);scheduleRemoval(op,options.failDelay??4200);return api},close(){restoreButton(op);clearInterval(op.ticker);document.querySelector(`[data-mcs-op="${CSS.escape(op.id)}"]`)?.remove();active.delete(op.id);return api}};op.api=api;return api}
  async function withProgress(options,operation){const op=start(options);try{const result=await operation(op);op.done(options?.doneDetail||'完成');return result}catch(error){op.fail(error?.message||String(error));throw error}}

  // Global latency fallback. Explicit operations keep their richer stage/percent model;
  // this tracker covers older buttons and route/background loads that still call api() directly.
  const network={count:0,failed:0,timer:null,op:null,lastClickAt:0,lastButton:null};
  function requestDomain(url=''){const u=String(url);if(u.includes('analysis-definition'))return'分析配置';if(u.includes('result')||u.includes('viewer')||u.includes('aggregate'))return'结果数据';if(u.includes('scorecard')||u.includes('decision')||u.includes('summary'))return'工程汇总';if(u.includes('design')||u.includes('revision'))return'设计数据';if(u.includes('material'))return'材料数据';if(u.includes('template')||u.includes('starter'))return'模板数据';if(u.includes('/tasks')||u.includes('/cases'))return'计算任务';if(u.includes('runtime')||u.includes('system')||u.includes('preflight'))return'运行环境';if(u.includes('project'))return'项目数据';return'工程数据'}
  function hasExplicitOperation(){return [...active.keys()].some(id=>id!=='network-auto-g33')}
  function paintNetwork(label){
    if(hasExplicitOperation())return;
    if(!network.op)network.op=start({id:'network-auto-g33',label,stage:'请求处理中',detail:`${network.count} 项请求进行中`,percent:null,disableButton:false,doneDelay:900,failDelay:2600});
    else network.op.update({label,stage:'请求处理中',detail:`${network.count} 项请求进行中`,percent:null});
  }
  function trackRequest(url,options={}){
    if(options?.__mcsSilentProgress)return()=>{};
    if(hasExplicitOperation())return()=>{};
    const method=String(options?.method||'GET').toUpperCase(),domain=requestDomain(url),recentClick=(now()-network.lastClickAt)<650;
    const label=method==='GET'?`${recentClick?'刷新':'加载'}${domain}`:`保存${domain}`;
    network.count+=1;
    clearTimeout(network.timer);
    if(method!=='GET'||recentClick)paintNetwork(label);
    else network.timer=setTimeout(()=>paintNetwork(label),180);
    let ended=false;
    return error=>{
      if(ended)return;ended=true;if(error)network.failed+=1;network.count=Math.max(0,network.count-1);
      if(network.count){network.op?.update({detail:`${network.count} 项请求进行中`});return}
      clearTimeout(network.timer);network.timer=null;
      const op=network.op,failed=network.failed;network.op=null;network.failed=0;
      if(op){if(failed)op.fail('部分请求未完成，请查看页面提示');else op.done('工程数据已更新')}
    }
  }
  document.addEventListener('click',event=>{const button=event.target?.closest?.('button,[role=button]');if(!button||button.disabled||button.getAttribute('aria-disabled')==='true')return;network.lastClickAt=now();network.lastButton=button;button.classList.remove('mcs-button-ack-g33');void button.offsetWidth;button.classList.add('mcs-button-ack-g33');setTimeout(()=>button.classList.remove('mcs-button-ack-g33'),430)},true);

  window.MCSOperationProgress={start,withProgress,trackRequest,active};
  document.body?.classList.add('studio-v089g33');
})();
