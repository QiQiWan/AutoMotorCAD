/* V0.77 Engineering Context Store
 *
 * Canonical engineering identity:
 * Project -> Solution -> Motor Revision -> Analysis -> Analysis Revision ->
 * ExecutionPlan -> Task -> Case -> ResultBundle.
 *
 * New code writes only through this store. Historical state.* fields are a one-way
 * compatibility projection and must never be treated as identity authorities.
 */
(() => {
  const STORAGE_PREFIX='motorcad-studio-engineering-context:';
  const ACTIVE_PROJECT_KEY='motorcad-studio-active-project';
  const SCHEMA_VERSION='2.0';
  const listeners=new Set(),transitionHistory=[];
  const restoredProjects=new Set();
  let sequence=0,batchDepth=0,pendingChanged=new Set(),pendingSource=null;
  const hierarchy=['projectId','solutionId','motorRevisionId','analysisId','analysisRevisionId','executionPlanId','taskId','caseId','resultBundleId'];
  const stageForTab={dashboard:'project',solutions:'solution',templates:'solution',workspace:'motor',analysisConfig:'analysis',analysisWorkbench:'analysis',tasks:'analysis',monitor:'analysis',resultViewer:'results',dataFactory:'results'};
  const refs={project:null,solution:null,motorRevision:null,analysis:null,analysisRevision:null,executionPlan:null,task:null,case:null,resultBundle:null};
  let lineage=null;
  let context={
    schemaVersion:SCHEMA_VERSION,
    projectId:state.activeProjectId||null,
    solutionId:state.workspaceDesign?.id||null,
    motorRevisionId:state.workspaceRevision?.id||state.taskDesignRevisionId||null,
    analysisId:null,analysisRevisionId:null,executionPlanId:null,taskId:null,caseId:null,resultBundleId:null,
    stage:'project',source:'bootstrap',revision:0,updatedAt:new Date().toISOString(),
  };

  const idOf=value=>value&&typeof value==='object'?(value.id||null):(value||null);
  const clone=value=>value==null?value:JSON.parse(JSON.stringify(value));
  const storageKey=projectId=>`${STORAGE_PREFIX}${projectId||'none'}`;
  const executionAlias=()=>context.executionPlanId||context.taskId||null;
  const resultAlias=()=>context.resultBundleId||context.caseId||null;

  function serializable(){return {...context,executionId:executionAlias(),resultId:resultAlias()}}
  function publicSnapshot(){return {...serializable(),project:refs.project,solution:refs.solution,motorRevision:refs.motorRevision,analysis:refs.analysis,analysisRevision:refs.analysisRevision,executionPlan:refs.executionPlan,task:refs.task,case:refs.case,resultBundle:refs.resultBundle,lineage}}
  function persist(){if(!context.projectId)return;try{localStorage.setItem(storageKey(context.projectId),JSON.stringify(serializable()))}catch{}}
  function restore(projectId){
    if(!projectId||restoredProjects.has(projectId))return false;restoredProjects.add(projectId);
    try{const parsed=JSON.parse(localStorage.getItem(storageKey(projectId))||'null');if(!parsed||parsed.schemaVersion!==SCHEMA_VERSION||parsed.projectId!==projectId)return false;for(const key of hierarchy)context[key]=parsed[key]||null;context.stage=parsed.stage||context.stage;sequence=Math.max(sequence,Number(parsed.revision)||0);return true}catch{return false}
  }
  function syncLegacy(){
    state.activeProjectId=context.projectId;
    try{if(context.projectId)localStorage.setItem(ACTIVE_PROJECT_KEY,context.projectId);else localStorage.removeItem(ACTIVE_PROJECT_KEY)}catch{}
    state.workspaceProject=refs.project||(state.workspaceProject?.id===context.projectId?state.workspaceProject:null);
    state.workspaceDesign=refs.solution||(state.workspaceDesign?.id===context.solutionId?state.workspaceDesign:null);
    state.workspaceRevision=refs.motorRevision||(state.workspaceRevision?.id===context.motorRevisionId?state.workspaceRevision:null);
    state.taskDesignRevisionId=context.motorRevisionId||null;
    state.selectedTask=context.taskId||null;state.monitorTask=context.taskId||null;
    state.engineeringContext=publicSnapshot();
  }
  function emit(changed,source){
    if(batchDepth>0){changed.forEach(key=>pendingChanged.add(key));pendingSource=source||pendingSource||'batch';return publicSnapshot()}
    sequence+=1;context.revision=sequence;context.source=source||'unknown';context.updatedAt=new Date().toISOString();syncLegacy();persist();
    const detail={context:publicSnapshot(),changed:[...changed],source:context.source};transitionHistory.push({sequence,source:detail.source,changed:detail.changed,context:serializable()});if(transitionHistory.length>100)transitionHistory.splice(0,transitionHistory.length-100);
    window.dispatchEvent(new CustomEvent('mcs:engineering-context-changed',{detail}));listeners.forEach(listener=>{try{listener(detail.context,detail)}catch(error){console.warn('engineering context listener failed',error)}});return detail.context;
  }
  function batch(source,operation){batchDepth+=1;try{return operation()}finally{batchDepth-=1;if(batchDepth===0&&pendingChanged.size){const changed=pendingChanged,resolved=source||pendingSource||'batch';pendingChanged=new Set();pendingSource=null;emit(changed,resolved)}}}
  function resetRefFor(key){const map={projectId:'project',solutionId:'solution',motorRevisionId:'motorRevision',analysisId:'analysis',analysisRevisionId:'analysisRevision',executionPlanId:'executionPlan',taskId:'task',caseId:'case',resultBundleId:'resultBundle'};if(map[key])refs[map[key]]=null}
  function clearBelow(key,changed){const index=hierarchy.indexOf(key);if(index<0)return;for(const child of hierarchy.slice(index+1)){if(context[child]!=null)changed.add(child);context[child]=null;resetRefFor(child)}lineage=null}
  function assign(key,value,changed){const id=idOf(value);if(id!==context[key]){context[key]=id;changed.add(key);clearBelow(key,changed)}if(value&&typeof value==='object'){const refKey={projectId:'project',solutionId:'solution',motorRevisionId:'motorRevision',analysisId:'analysis'}[key];if(refKey){refs[refKey]=value;changed.add(refKey)}}else if(!id)resetRefFor(key)}

  function setProject(value,options={}){const changed=new Set();const id=idOf(value);if(id!==context.projectId){context.projectId=id;changed.add('projectId');clearBelow('projectId',changed);refs.project=value&&typeof value==='object'?value:null;if(id)restore(id)}else if(value&&typeof value==='object'){refs.project=value;changed.add('project')}return changed.size?emit(changed,options.source||'set-project'):publicSnapshot()}
  function setSolution(value,options={}){const changed=new Set();assign('solutionId',value,changed);if(value&&typeof value==='object')refs.solution=value;return changed.size?emit(changed,options.source||'set-solution'):publicSnapshot()}
  function setMotorRevision(value,options={}){const changed=new Set();if(options.solution){const sid=idOf(options.solution);if(sid!==context.solutionId){context.solutionId=sid;changed.add('solutionId');clearBelow('solutionId',changed)}if(typeof options.solution==='object')refs.solution=options.solution}assign('motorRevisionId',value,changed);if(value&&typeof value==='object')refs.motorRevision=value;return changed.size?emit(changed,options.source||'set-motor-revision'):publicSnapshot()}
  function setAnalysis(value,options={}){const changed=new Set();if(options.motorRevision){const rid=idOf(options.motorRevision);if(rid!==context.motorRevisionId){context.motorRevisionId=rid;changed.add('motorRevisionId');clearBelow('motorRevisionId',changed)}if(typeof options.motorRevision==='object')refs.motorRevision=options.motorRevision}assign('analysisId',value,changed);if(value&&typeof value==='object')refs.analysis=value;const revisionId=options.analysisRevisionId||(value&&typeof value==='object'?value.revisions?.[0]?.id:null)||null;if(revisionId!==context.analysisRevisionId){context.analysisRevisionId=revisionId;changed.add('analysisRevisionId');clearBelow('analysisRevisionId',changed)}return changed.size?emit(changed,options.source||'set-analysis'):publicSnapshot()}
  function setExecution(value,options={}){const changed=new Set();const planId=options.executionPlanId||options.executionId||(value&&typeof value==='object'?(value.execution_plan_id||value.executionPlanId):null)||((options.kind!=='task'&&typeof value==='string')?value:null);const taskId=options.taskId||(value&&typeof value==='object'?(value.task_id||value.taskId||((value.status||value.request)?value.id:null)):null)||(options.kind==='task'?idOf(value):null);if((planId||null)!==context.executionPlanId){context.executionPlanId=planId||null;changed.add('executionPlanId');clearBelow('executionPlanId',changed)}if((taskId||null)!==context.taskId){context.taskId=taskId||null;changed.add('taskId');clearBelow('taskId',changed)}if(value&&typeof value==='object'){if(planId)refs.executionPlan=value;if(taskId)refs.task=value}return changed.size?emit(changed,options.source||'set-execution'):publicSnapshot()}
  function setResult(value,options={}){const changed=new Set();const caseId=options.caseId||(value&&typeof value==='object'?(value.case_id||value.caseId):null)||(!options.resultBundleId&&typeof value==='string'?value:null);const bundleId=options.resultBundleId||(value&&typeof value==='object'?(value.result_bundle_id||value.resultBundleId||((value.provenance&&value.results)?value.id:null)):null);if((caseId||null)!==context.caseId){context.caseId=caseId||null;changed.add('caseId');clearBelow('caseId',changed)}if((bundleId||null)!==context.resultBundleId){context.resultBundleId=bundleId||null;changed.add('resultBundleId')}if(value&&typeof value==='object'){if(caseId)refs.case=value;if(bundleId)refs.resultBundle=value}return changed.size?emit(changed,options.source||'set-result'):publicSnapshot()}
  function setStage(stage,options={}){if(!stage||stage===context.stage)return publicSnapshot();context.stage=stage;return emit(new Set(['stage']),options.source||'set-stage')}

  function applyLineage(payload,options={}){
    if(!payload?.identity)throw new Error('EngineeringLineage.identity is required');
    if(payload.integrity?.valid===false){const error=new Error(`Engineering lineage rejected: ${(payload.integrity.issues||[]).join('; ')}`);error.code='ENGINEERING_LINEAGE_INVALID';window.dispatchEvent(new CustomEvent('mcs:engineering-lineage-rejected',{detail:{lineage:payload,error}}));throw error}
    const identity=payload.identity,changed=new Set();
    batch(options.source||'apply-lineage',()=>{
      for(const [field,key] of Object.entries({project_id:'projectId',solution_id:'solutionId',motor_revision_id:'motorRevisionId',analysis_id:'analysisId',analysis_revision_id:'analysisRevisionId',execution_plan_id:'executionPlanId',task_id:'taskId',case_id:'caseId',result_bundle_id:'resultBundleId'})){
        const next=identity[field]||null;if(context[key]!==next){context[key]=next;changed.add(key)}
      }
      Object.assign(refs,{project:payload.project||null,solution:payload.solution||null,motorRevision:payload.motor_revision||null,analysis:payload.analysis||null,analysisRevision:payload.analysis_revision||null,executionPlan:payload.execution_plan||null,task:payload.task||null,case:payload.case||null,resultBundle:payload.result_bundle||null});
      lineage=clone(payload);['project','solution','motorRevision','analysis','analysisRevision','executionPlan','task','case','resultBundle','lineage'].forEach(key=>changed.add(key));
      emit(changed,options.source||'apply-lineage');
    });
    return publicSnapshot();
  }

  function reconcileRoute(route,options={}){
    if(!route)return publicSnapshot();const source=options.source||'router';
    batch(source,()=>{
      if(route.projectId!==undefined&&route.projectId!==context.projectId)setProject(route.projectId||null,{source});
      const stage=stageForTab[route.tab];if(stage)setStage(stage,{source});
      if(route.designId)setSolution(route.designId,{source});if(route.revisionId)setMotorRevision(route.revisionId,{source});if(route.analysisId)setAnalysis(route.analysisId,{source});
      // Deep task/result URLs carry incomplete ancestry. Never commit their leaf IDs
      // before the backend EngineeringLineage has passed integrity checks. Only clear
      // stale downstream identity; MCSResultContext later applies the whole chain atomically.
      if(route.taskId){const changed=new Set();for(const key of ['executionPlanId','taskId','caseId','resultBundleId']){if(context[key]){context[key]=null;changed.add(key)}}if(changed.size)emit(changed,source)}
      if(route.caseId){const changed=new Set();for(const key of ['caseId','resultBundleId']){if(context[key]){context[key]=null;changed.add(key)}}if(changed.size)emit(changed,source)}
    });return publicSnapshot();
  }
  function invalidate(level,options={}){const changed=new Set();const key={project:'projectId',solution:'solutionId',motor:'motorRevisionId',analysis:'analysisId',execution:'executionPlanId',results:'caseId'}[level];if(!key)return publicSnapshot();if(context[key]!=null){context[key]=null;changed.add(key)}clearBelow(key,changed);resetRefFor(key);return changed.size?emit(changed,options.source||'invalidate'):publicSnapshot()}
  function inspect(){const s=publicSnapshot(),issues=[];if(s.solutionId&&!s.projectId)issues.push('solution_without_project');if(s.motorRevisionId&&!s.solutionId)issues.push('motor_revision_without_solution');if(s.analysisId&&!s.motorRevisionId)issues.push('analysis_without_motor_revision');if(s.analysisRevisionId&&!s.analysisId)issues.push('analysis_revision_without_analysis');if(s.executionPlanId&&!s.motorRevisionId)issues.push('execution_plan_without_motor_revision');if(s.taskId&&!s.executionPlanId)issues.push('task_without_execution_plan');if(s.caseId&&!s.taskId)issues.push('case_without_task');if(s.resultBundleId&&!s.caseId)issues.push('result_bundle_without_case');return{context:s,valid:issues.length===0,issues,transitions:transitionHistory.map(clone)}}
  function subscribe(listener,{immediate=false}={}){if(typeof listener!=='function')return()=>{};listeners.add(listener);if(immediate)listener(publicSnapshot(),{changed:[],source:'subscribe'});return()=>listeners.delete(listener)}

  if(context.projectId)restore(context.projectId);syncLegacy();
  window.MCSEngineeringContext={schemaVersion:SCHEMA_VERSION,get:publicSnapshot,setProject,setSolution,setMotorRevision,setAnalysis,setExecution,setResult,setStage,applyLineage,reconcileRoute,inspect,invalidate,restore,subscribe,stageForTab:tab=>stageForTab[tab]||null};
})();
