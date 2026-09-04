/* MotorCAD Studio V0.73-E — authoritative Experiment lifecycle routing.
 *
 * Results creates studies; submitted studies live in Compute/Monitor; terminal studies
 * with usable ResultBundles hand back to Results/Optimization. Browser history and old
 * result URLs never become a second lifecycle authority.
 */
(() => {
  const TERMINAL = new Set(['COMPLETED','PARTIALLY_COMPLETED','FAILED','CANCELLED']);
  const ACTIVE_STATES = new Set(['SUBMITTED','COMPUTE_MONITOR','CANCELLING']);
  const inFlight = new Map();
  let transitionSerial = 0;

  async function fetchLifecycle(taskId, ctx=null) {
    if (!taskId) return null;
    const key=String(taskId);
    if (inFlight.has(key)) return inFlight.get(key);
    const promise=(async()=>{
      try {
        const options=ctx?.signal?{signal:ctx.signal}:{};
        const row=await api(`/api/tasks/${encodeURIComponent(key)}/experiment-lifecycle`,options);
        if(ctx&&!window.MCSPageRuntime?.isContextActive?.(ctx))return null;
        return row;
      } finally { inFlight.delete(key); }
    })();
    inFlight.set(key,promise);
    return promise;
  }

  function isMonitorRoute(route, taskId) {
    return route?.tab==='monitor' && String(route?.taskId||'')===String(taskId||'');
  }
  function isOptimizationResultRoute(route, taskId) {
    return route?.tab==='resultViewer' && route?.resultsMode==='optimization' && String(route?.optimizationTaskId||'')===String(taskId||'');
  }

  async function reconcile(taskId, {ctx=null, replace=true, source='route'}={}) {
    const serial=++transitionSerial;
    let row;
    try { row=await fetchLifecycle(taskId,ctx); }
    catch(error){ if(window.MCSPageRuntime?.isAbortError?.(error))return null; console.warn('experiment lifecycle read failed',error); return null; }
    if(!row||serial!==transitionSerial)return row;
    const route=ctx?.route||window.MCSPageRuntime?.current?.()?.route||window.state?.routeV025||{};
    const routes=row.routes||{};
    if(ACTIVE_STATES.has(row.state) && isOptimizationResultRoute(route,taskId) && routes.monitor){
      window.MCSPageRuntime?.report?.('EXPERIMENT_ROUTE_RECONCILED','INFO','运行中的参数研究已返回 Compute/Monitor',{task_id:taskId,source,state:row.state});
      await window.MCSRouter?.navigate?.(routes.monitor,{replace});
      return row;
    }
    if(row.terminal && row.results_available && isMonitorRoute(route,taskId) && routes.results){
      window.MCSPageRuntime?.report?.('EXPERIMENT_RESULTS_HANDOFF','INFO','参数研究计算完成，交还 Results/Optimization',{task_id:taskId,source,state:row.state});
      await window.MCSRouter?.navigate?.(routes.results,{replace});
      return row;
    }
    return row;
  }

  async function guardResultsTask(taskId, ctx=null){
    const row=await fetchLifecycle(taskId,ctx);
    if(!row)return {allow:true,lifecycle:null};
    if(ACTIVE_STATES.has(row.state)){
      const target=row.routes?.monitor;
      if(target)await window.MCSRouter?.navigate?.(target,{replace:true});
      return {allow:false,lifecycle:row};
    }
    return {allow:true,lifecycle:row};
  }

  window.addEventListener('mcs:route-ready',event=>{
    const route=event.detail?.route||window.state?.routeV025||{};
    const taskId=route.tab==='monitor'?route.taskId:(route.resultsMode==='optimization'?route.optimizationTaskId:null);
    if(taskId)queueMicrotask(()=>reconcile(taskId,{source:'route-ready'}));
  });
  window.addEventListener('mcs:task-snapshot',event=>{
    const snapshot=event.detail||{};
    if(TERMINAL.has(String(snapshot.status||'')) && snapshot.task_id){
      queueMicrotask(()=>reconcile(snapshot.task_id,{source:'task-terminal'}));
    }
  });

  window.MCSExperimentLifecycle=Object.freeze({fetch:fetchLifecycle,reconcile,guardResultsTask});
})();
