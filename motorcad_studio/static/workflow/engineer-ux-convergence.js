/* V0.89-F Engineer UX Convergence.
 * Keeps the default engineer view centered on four questions:
 * where am I, what is the state, what needs attention, and what do I do next.
 * Technical authority names remain available in Expert/Developer views.
 */
(() => {
  const AUTHORITY='EngineerUXConvergenceV1';
  const CONTRACT_VERSION='0.89-G1';
  const state={workflow:null,rc:null,lastRenderedAt:0};
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ctx=()=>window.MCSEngineeringContext?.get?.()||{};
  const mode=()=>document.body?.dataset?.userMode||'operator';
  const activeTab=()=>q('.tab.active')?.id||'projects';
  const pageLabels={projects:'项目管理',setup:'运行环境',dashboard:'项目概览',solutions:'方案',workspace:'设计 · 电机配置',analysisConfig:'验证 · 分析配置',monitor:'验证 · 运行监控',tasks:'验证 · 计算任务',resultViewer:'决策 · 工程结果',dataFactory:'决策 · 数据与试验',logs:'问题与诊断',system:'高级工具'};
  const objectLabel=(ref,id,fallback)=>ref?.name||ref?.label||ref?.display_name||(id?String(id).slice(0,10):fallback);
  function contextSummary(){
    const c=ctx(),parts=[];
    if(c.solutionId)parts.push(objectLabel(c.solution,c.solutionId,'方案'));
    if(c.motorRevisionId)parts.push(c.motorRevision?.revision!=null?`电机版本 Rev.${c.motorRevision.revision}`:`电机版本 ${String(c.motorRevisionId).slice(0,8)}`);
    if(c.analysisId)parts.push(objectLabel(c.analysis,c.analysisId,'分析'));
    if(c.resultBundleId)parts.push(`结果 ${String(c.resultBundleId).slice(0,8)}`);
    return parts.join(' · ')||'尚未选择方案或电机版本';
  }
  function derive(){
    const workflow=state.workflow||window.MCSEngineeringWorkflow?.state?.payload||window.MCSGlobalWorkflowTruth?.snapshot?.()?.payload||null;
    const c=ctx(),inspection=window.MCSEngineeringContext?.inspect?.()||{valid:true,issues:[]};
    const tab=activeTab();
    const current=workflow?.stages?.find?.(row=>row.id===workflow.current_stage)||null;
    const failures=workflow?.failure_center?.items||[];
    const active=Number(workflow?.run_center?.summary?.active||0);
    let status='准备就绪',statusDetail=current?.summary||'可以继续当前工程步骤';
    if(!c.projectId){status='等待进入项目';statusDetail='从项目管理新建或进入一个项目';}
    else if(!inspection.valid){status='工程上下文异常';statusDetail='当前对象链需要重新验证';}
    else if(active>0){status='正在计算';statusDetail=`${active} 个任务正在运行，可继续查看进度`;}
    else if(failures.length){status='需要处理';statusDetail=failures[0]?.summary||'存在需要处理的计算问题';}
    else if(current?.status==='BLOCKED'){status='前置条件未完成';statusDetail=(current.blockers||[])[0]||current.summary||'请先完成上一阶段';}
    const issue=!inspection.valid?`上下文：${(inspection.issues||[]).join('、')}`:failures.length?(failures[0]?.summary||'存在待处理问题'):'当前无阻断项';
    const action=workflow?.next_action||workflow?.primary_next_action||null;
    let next=action?.label||(!c.projectId?'进入项目':tab==='workspace'?'保存电机版本并进入验证':tab==='analysisConfig'?'完成检查并开始计算':tab==='resultViewer'?'查看结论并决定下一步':'继续当前步骤');
    return {where:pageLabels[tab]||'MotorCAD Studio',context:contextSummary(),status,statusDetail,issue,next,action,inspection};
  }
  function navigate(action){
    if(!action)return;
    if(action.route&&window.MCSRouter?.navigate)return window.MCSRouter.navigate(action.route);
    if(action.stage==='design')return window.showTab?.('workspace');
    if(action.stage==='validate')return window.showTab?.('analysisConfig');
    if(action.stage==='decide')return window.showTab?.('resultViewer');
  }
  function render(){
    const host=q('#engineerFocusBarV089F');if(!host)return null;
    const d=derive(),technical=['expert','developer'].includes(mode());
    const attention=d.issue!=='当前无阻断项'||d.status==='需要处理'||d.status.includes('异常')||d.status==='前置条件未完成';
    host.innerHTML=`<div class="engineer-focus-cell-v089f current"><span>当前</span><b>${esc(d.where)}</b><small>${esc(d.context)}</small></div><div class="engineer-focus-cell-v089f status ${attention?'attention':'clear'}"><span>${attention?'需要处理':'状态'}</span><b>${esc(attention?d.issue:d.status)}</b><small>${esc(attention?d.statusDetail:'当前流程无阻断项')}</small></div><div class="engineer-focus-cell-v089f next"><span>下一步</span><b>${esc(d.next)}</b><small>${technical?'技术证据可在高级视图查看':'完成当前动作后继续工程流程'}</small>${d.action?'<button type="button" class="primary" data-hmi-action="ENGINEER_FOCUS_NEXT">继续 →</button>':''}</div>`;
    q('[data-hmi-action="ENGINEER_FOCUS_NEXT"]',host)?.addEventListener('click',()=>navigate(d.action));
    state.lastRenderedAt=Date.now();
    return {authority:AUTHORITY,contract_version:CONTRACT_VERSION,...d};
  }
  function ingest(workflow){state.workflow=workflow||state.workflow;return render()}
  function schedule(){requestAnimationFrame(render)}
  window.addEventListener('mcs:workflow-truth-updated',event=>ingest(event.detail?.payload));
  window.addEventListener('mcs:engineering-context-changed',schedule);
  window.addEventListener('mcs:route-ready',schedule);
  window.addEventListener('mcs:canonical-page-mounted',schedule);
  q('#userMode')?.addEventListener('change',()=>setTimeout(render,0));
  document.addEventListener('DOMContentLoaded',schedule,{once:true});
  window.MCSEngineerUX={authority:AUTHORITY,contractVersion:CONTRACT_VERSION,state,render,derive,ingest};
})();
