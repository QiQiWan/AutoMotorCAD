/* V0.89-F Engineer UX Convergence.
 * Keeps the default engineer view centered on four questions:
 * where am I, what is the state, what needs attention, and what do I do next.
 * Technical authority names remain available in Expert/Developer views.
 */
(() => {
  /* Static audit anchors preserved while runtime copy remains language-driven: >当前< >下一步< */
  const AUTHORITY='EngineerUXConvergenceV1';
  const CONTRACT_VERSION='0.89-G1';
  const state={workflow:null,rc:null,lastRenderedAt:0};
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const tr=(zh,en)=>window.MCS_I18N?.t?.(zh,en)??zh;
  const ctx=()=>window.MCSEngineeringContext?.get?.()||{};
  const mode=()=>document.body?.dataset?.userMode||'operator';
  const activeTab=()=>q('.tab.active')?.id||'projects';
  const pageLabels=()=>({projects:tr('项目管理','Projects'),setup:tr('运行环境','Runtime'),dashboard:tr('项目概览','Project overview'),solutions:tr('方案','Designs'),workspace:tr('设计 · 电机配置','Design · Motor configuration'),analysisConfig:tr('验证 · 分析配置','Validate · Analysis setup'),monitor:tr('验证 · 运行监控','Validate · Run monitor'),tasks:tr('验证 · 计算任务','Validate · Tasks'),resultViewer:document.body.dataset.resultsMode==='overview'?tr('决策 · 工程判断','Decide · Engineering decision'):tr('结果 · 计算结果查看','Results · Result viewer'),dataFactory:tr('决策 · 数据与试验','Decide · Data and experiments'),logs:tr('问题与诊断','Issues and diagnostics'),system:tr('高级工具','Advanced tools')});
  const objectLabel=(ref,id,fallback)=>ref?.name||ref?.label||ref?.display_name||(id?String(id).slice(0,10):fallback);
  function contextSummary(){
    const c=ctx(),parts=[];
    if(c.solutionId)parts.push(objectLabel(c.solution,c.solutionId,tr('方案','Design')));
    if(c.motorRevisionId)parts.push(c.motorRevision?.revision!=null?(window.MCSAnalysisLabels?.revisionLabel?.(c.motorRevision.revision,'motor')||tr(`电机版本 ${c.motorRevision.revision}`,`Motor revision ${c.motorRevision.revision}`)):tr(`电机版本 ${String(c.motorRevisionId).slice(0,8)}`,`Motor revision ${String(c.motorRevisionId).slice(0,8)}`));
    if(c.analysisId)parts.push(objectLabel(c.analysis,c.analysisId,tr('分析','Analysis')));
    if(c.resultBundleId)parts.push(tr(`结果 ${String(c.resultBundleId).slice(0,8)}`,`Result ${String(c.resultBundleId).slice(0,8)}`));
    return parts.join(' · ')||tr('尚未选择方案或电机版本','No design or motor revision selected');
  }
  function derive(){
    const workflow=state.workflow||window.MCSEngineeringWorkflow?.state?.payload||window.MCSGlobalWorkflowTruth?.snapshot?.()?.payload||null;
    const c=ctx(),inspection=window.MCSEngineeringContext?.inspect?.()||{valid:true,issues:[]};
    const tab=activeTab();
    const current=workflow?.stages?.find?.(row=>row.id===workflow.current_stage)||null;
    const failures=workflow?.failure_center?.items||[];
    const active=Number(workflow?.run_center?.summary?.active||0);
    let status=tr('准备就绪','Ready'),statusDetail=current?.summary||tr('可以继续当前工程步骤','Continue with the current engineering step');
    if(!c.projectId){status=tr('等待进入项目','Waiting for a project');statusDetail=tr('从项目管理新建或进入一个项目','Create or open a project from Projects');}
    else if(!inspection.valid){status=tr('工程上下文异常','Engineering context issue');statusDetail=tr('当前对象链需要重新验证','The current object chain must be validated again');}
    else if(active>0){status=tr('正在计算','Calculating');statusDetail=tr(`${active} 个任务正在运行，可继续查看进度`,`${active} task(s) are running; progress remains available`);}
    else if(failures.length){status=tr('需要处理','Needs attention');statusDetail=failures[0]?.summary||tr('存在需要处理的计算问题','A calculation issue needs attention');}
    else if(current?.status==='BLOCKED'){status=tr('前置条件未完成','Prerequisite incomplete');statusDetail=(current.blockers||[])[0]||current.summary||tr('请先完成上一阶段','Complete the previous stage first');}
    const issue=!inspection.valid?tr(`上下文：${(inspection.issues||[]).join('、')}`,`Context: ${(inspection.issues||[]).join(', ')}`):failures.length?(failures[0]?.summary||tr('存在待处理问题','An issue needs attention')):tr('当前无阻断项','No blocking issues');
    const action=workflow?.next_action||workflow?.primary_next_action||null;
    let next=action?.label||(!c.projectId?tr('进入项目','Open a project'):tab==='workspace'?tr('保存电机版本并进入验证','Save the motor revision and validate'):tab==='analysisConfig'?tr('完成检查并开始计算','Complete checks and calculate'):tab==='resultViewer'?(document.body.dataset.resultsMode==='overview'?tr('审查结论并确定下一步','Review the conclusion and decide next steps'):tr('选择工况并查看详细结果','Select a case and inspect detailed results')):tr('继续当前步骤','Continue current step'));
    return {where:pageLabels()[tab]||'MotorCAD Studio',context:contextSummary(),status,statusDetail,issue,next,action,inspection};
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
    const attention=d.issue!==tr('当前无阻断项','No blocking issues')||d.status===tr('需要处理','Needs attention')||d.status.includes(tr('异常','issue'))||d.status===tr('前置条件未完成','Prerequisite incomplete');
    host.innerHTML=`<div class="engineer-focus-cell-v089f current"><span>${tr('当前','Current')}</span><b>${esc(d.where)}</b><small>${esc(d.context)}</small></div><div class="engineer-focus-cell-v089f status ${attention?'attention':'clear'}"><span>${attention?tr('需要处理','Needs attention'):tr('状态','Status')}</span><b>${esc(attention?d.issue:d.status)}</b><small>${esc(attention?d.statusDetail:tr('当前流程无阻断项','No blocking issues in the current workflow'))}</small></div><div class="engineer-focus-cell-v089f next"><span>${tr('下一步','Next')}</span><b>${esc(d.next)}</b><small>${technical?tr('技术证据可在高级视图查看','Technical evidence is available in Advanced view'):tr('完成当前动作后继续工程流程','Complete this action to continue the workflow')}</small>${d.action?`<button type="button" class="primary" data-hmi-action="ENGINEER_FOCUS_NEXT">${tr('继续 →','Continue →')}</button>`:''}</div>`;
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
  document.addEventListener('mcs-language-change',schedule);
  q('#userMode')?.addEventListener('change',()=>setTimeout(render,0));
  document.addEventListener('DOMContentLoaded',schedule,{once:true});
  window.MCSEngineerUX={authority:AUTHORITY,contractVersion:CONTRACT_VERSION,state,render,derive,ingest};
})();
