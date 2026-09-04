/* V0.89-A Global Workflow Truth.
 *
 * Owns the engineer-visible relationship between the three-stage journey and
 * the canonical engineering object chain. It never invents object identity;
 * MCSEngineeringContext remains the browser identity authority and backend
 * EngineeringWorkflowService remains the persisted workflow truth.
 */
(() => {
  const AUTHORITY='GlobalWorkflowTruthV1';
  const CONTRACT_VERSION='0.89-A';
  const state={payload:null,projectId:null,lastAt:0};
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>[...(r?.querySelectorAll?.(s)||[])];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const tr=(zh,en)=>window.MCS_I18N?.t?.(zh,en)??zh;
  const ctx=()=>window.MCSEngineeringContext?.get?.()||{};

  const labelOf=(ref,id,kind)=>{
    if(ref){
      if(kind==='motorRevision')return window.MCSAnalysisLabels?.revisionLabel?.(ref.revision??String(id||'').slice(0,8),'motor')||tr(`电机版本 ${ref.revision??String(id||'').slice(0,8)}`,`Motor revision ${ref.revision??String(id||'').slice(0,8)}`);
      return ref.name||ref.label||ref.id||id||'—';
    }
    return id?String(id).slice(0,10):tr('未选择','Not selected');
  };
  function renderBreadcrumb(){
    const host=q('#engineeringContextBreadcrumbV089A');if(!host)return;
    const c=ctx(),p=state.payload?.project||c.project;
    const segments=[
      [tr('项目','Project'),p?.name||labelOf(c.project,c.projectId,'project'),Boolean(c.projectId)],
      [tr('方案','Design'),labelOf(c.solution,c.solutionId,'solution'),Boolean(c.solutionId)],
      [tr('电机版本','Motor revision'),labelOf(c.motorRevision,c.motorRevisionId,'motorRevision'),Boolean(c.motorRevisionId)],
      [tr('分析','Analysis'),labelOf(c.analysis,c.analysisId,'analysis'),Boolean(c.analysisId)],
      [tr('任务','Task'),c.task?.name||labelOf(c.task,c.taskId,'task'),Boolean(c.taskId)],
      [tr('结果','Result'),labelOf(c.resultBundle,c.resultBundleId,'resultBundle'),Boolean(c.resultBundleId)],
    ];
    const inspection=window.MCSEngineeringContext?.inspect?.()||{valid:true,issues:[]};
    host.innerHTML=`<div class="engineering-context-breadcrumb-track-v089a">${segments.map(([k,v,active],i)=>`<div class="engineering-context-node-v089a ${active?'active':'empty'}"><span>${esc(k)}</span><b>${esc(v)}</b></div>${i<segments.length-1?'<i>›</i>':''}`).join('')}</div><div class="engineering-context-integrity-v089a ${inspection.valid?'ready':'blocked'}"><b>${inspection.valid?tr('上下文一致','Context consistent'):tr('上下文异常','Context issue')}</b><small>${inspection.valid?tr('当前页面只使用已验证的工程身份链','This page uses the verified engineering identity chain only'):tr('检测到：','Detected: ')+esc((inspection.issues||[]).join(tr('、',', ')))}</small></div>`;
  }
  function stageRows(){return state.payload?.stages||[]}
  function objectStage(id){return stageRows().find(row=>row.id===id)||null}
  function applyStageGates(){
    const c=ctx();
    const hasProject=Boolean(c.projectId);
    const designReady=Boolean(c.motorRevisionId)||Boolean(objectStage('motor')?.completed);
    const resultReady=Boolean(c.resultBundleId)||Boolean(objectStage('results')?.completed)||Boolean((state.payload?.run_center?.summary?.total||0)>0);
    const resultGate={enabled:hasProject&&resultReady,reason:resultReady?'':tr('完成一次分析后查看结果','Complete an analysis before opening results')};
    const gates={design:{enabled:hasProject,reason:hasProject?'':tr('请先进入项目','Open a project first')},validate:{enabled:hasProject&&designReady,reason:designReady?'':tr('请先保存一个电机版本','Save a motor revision first')},results:resultGate,decide:{enabled:resultGate.enabled,reason:resultGate.enabled?'':tr('先形成可用结果，再进入工程决策','Create a usable result before engineering decisions')}};
    qa('[data-engineer-stage]').forEach(button=>{
      const gate=gates[button.dataset.engineerStage];if(!gate)return;
      button.disabled=!gate.enabled;button.setAttribute('aria-disabled',String(!gate.enabled));
      button.dataset.workflowGate=gate.enabled?'OPEN':'BLOCKED';
      if(!gate.enabled)button.title=gate.reason;
      else if(button.title===gate.reason||/请先|完成一次分析/.test(button.title||''))button.removeAttribute('title');
    });
    return gates;
  }
  function ingest(payload){
    if(!payload)return null;state.payload=payload;state.projectId=payload.project?.id||ctx().projectId||null;state.lastAt=Date.now();renderBreadcrumb();applyStageGates();
    window.dispatchEvent(new CustomEvent('mcs:workflow-truth-updated',{detail:{authority:AUTHORITY,contract_version:CONTRACT_VERSION,payload}}));
    return snapshot();
  }
  function snapshot(){return {authority:AUTHORITY,contract_version:CONTRACT_VERSION,project_id:state.projectId,payload:state.payload,gates:applyStageGates(),context:ctx()}}
  function sync(){renderBreadcrumb();applyStageGates()}
  window.addEventListener('mcs:engineering-context-changed',sync);
  window.addEventListener('mcs:route-ready',sync);
  document.addEventListener('mcs-language-change',sync);
  document.addEventListener('DOMContentLoaded',sync,{once:true});
  window.MCSGlobalWorkflowTruth={authority:AUTHORITY,contractVersion:CONTRACT_VERSION,ingest,snapshot,sync,renderBreadcrumb,applyStageGates};
})();
