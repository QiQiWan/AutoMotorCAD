/* MotorCAD Studio V0.67 — engineer-facing Analysis lineage summary on the live monitor. */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const stageLabels={RUNNING:'运行中',RESULTS_AVAILABLE:'已有可用结果',ATTENTION:'需要处理',FINISHED:'运行结束'};
  const lifecycleLabels={SUBMITTED:'已提交',COMPUTE_MONITOR:'计算监控',CANCELLING:'取消中',RESULTS_READY:'结果就绪',OPTIMIZATION_READY:'优化结果就绪',ATTENTION:'需要处理',CANCELLED:'已取消'};
  let requestToken=0;
  async function decorate(taskId){
    const token=++requestToken,host=q('#monitorContent');if(!host||!taskId)return;
    let node=q('#analysisWorkflowMonitorV067',host);if(!node){node=document.createElement('article');node.id='analysisWorkflowMonitorV067';node.className='panel analysis-workflow-monitor-v067';host.prepend(node)}
    node.innerHTML='<div class="analysis-monitor-loading-v067"><span class="spinner-dot"></span>正在读取当前 Analysis / Design 版本关系…</div>';
    try{
      const row=await api(`/api/tasks/${encodeURIComponent(taskId)}/workflow-status`);if(token!==requestToken||state.monitorTask!==taskId)return;
      const progress=Math.max(0,Math.min(100,Math.round(Number(row.progress||0)*100)));
      node.innerHTML=`<div class="analysis-monitor-head-v067"><div><span class="eyebrow">Analysis / Compute</span><h3>${safe(row.analysis_name||row.task_name||'当前计算')}</h3><p>${safe(row.design_name||'电机设计')} · Design Rev.${safe(row.design_revision??'—')} · Analysis Rev.${safe(row.analysis_revision??'—')}</p></div><span class="analysis-monitor-state-v067 ${safe(String(row.stage||'').toLowerCase())}">${safe(lifecycleLabels[row.experiment_lifecycle_state]||stageLabels[row.stage]||row.task_status||row.stage)}</span></div><div class="analysis-monitor-progress-v067"><div><span style="width:${progress}%"></span></div><b>${progress}%</b></div><div class="analysis-monitor-metrics-v067"><div><span>Case</span><b>${row.case_count||0}</b><small>本次冻结工况</small></div><div><span>已完成</span><b>${row.succeeded_cases||0}</b><small>Motor-CAD 执行完成</small></div><div><span>可用结果</span><b>${row.usable_cases||0}</b><small>通过结果验证</small></div><div><span>Execution Plan</span><b>${row.execution_plan_id?'已冻结':'兼容模式'}</b><small>${safe(row.execution_plan_id||row.run_configuration_id||'等待创建')}</small></div></div><div class="analysis-monitor-actions-v067"><button type="button" data-analysis-monitor-back-v067>返回分析与计算</button><button type="button" data-analysis-monitor-task-v067>任务详情</button>${row.results_available?'<button type="button" class="primary" data-analysis-monitor-results-v067>查看工程结果 →</button>':''}</div>`;
      q('[data-analysis-monitor-back-v067]',node)?.addEventListener('click',()=>{const pid=row.project_id||state.activeProjectId;if(row.analysis_definition_id&&window.MCSRouter?.navigate&&pid)return window.MCSRouter.navigate(`/app/projects/${encodeURIComponent(pid)}/simulation/analyses/${encodeURIComponent(row.analysis_definition_id)}/execute/monitor`);if(row.analysis_definition_id&&window.MCSAnalysisExecution?.open)return window.MCSAnalysisExecution.open(row.analysis_definition_id,false,null,'monitor');window.showTab?.('analysisConfig')});
      q('[data-analysis-monitor-task-v067]',node)?.addEventListener('click',()=>{const pid=row.project_id||state.activeProjectId;if(window.MCSRouter?.navigate&&pid)return MCSRouter.navigate(`/app/projects/${encodeURIComponent(pid)}/simulation/tasks/${encodeURIComponent(taskId)}`);state.selectedTask=taskId;showTab('tasks');showTask?.(taskId)});
      q('[data-analysis-monitor-results-v067]',node)?.addEventListener('click',()=>{const pid=row.project_id||state.activeProjectId;if(window.MCSRouter?.navigate&&pid)return MCSRouter.navigate(row.results_route||`/app/projects/${encodeURIComponent(pid)}/results/tasks/${encodeURIComponent(taskId)}`);showTab('resultViewer')});
    }catch(error){if(token!==requestToken)return;node.innerHTML=`<div class="analysis-monitor-loading-v067 warning">当前任务的 Analysis 版本关系暂时无法读取：${safe(error.message)}</div>`}
  }
  const previous=window.openMonitorTask;
  if(typeof previous==='function')window.openMonitorTask=async function(id,reconnect=false,routeCtx=null){const result=await previous.apply(this,arguments);if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return result;await decorate(id);return result};
  const analysisMonitorController={decorate};
  window.MCSAnalysisMonitor=analysisMonitorController;
})();
