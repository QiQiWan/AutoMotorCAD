/* V0.89-G5 Workflow Action Readiness + Dead-end Elimination.
 *
 * Every engineer-facing primary action resolves to one of:
 * READY / BLOCKED / IDLE / BUSY. BLOCKED actions must expose a concrete,
 * executable recovery action. A blocked action without an executable recovery
 * is a release-gate dead end.
 */
(() => {
  const AUTHORITY = 'WorkflowActionReadinessAuthorityV1';
  const CONTRACT_VERSION = '0.89-G5';
  const managed = new WeakMap();
  const rowsByControl = new Map();
  let mutationObserver = null;
  let refreshTimer = null;

  const q=(s,r=document)=>{try{return r?.querySelector?.(s)||null}catch{return null}};
  const qa=(s,r=document)=>{try{return [...(r?.querySelectorAll?.(s)||[])]}catch{return []}};
  const app=()=>window.MCSAppState||window.state||{};
  const ctx=()=>window.MCSEngineeringContext?.get?.()||{};
  const analysis=()=>window.MCSUnifiedAnalysis?.state||{};
  const editor=()=>window.MCSDesignEditor||null;
  const svp=()=>window.MCSStandardValidation?.state||{};
  const optimization=()=>window.MCSOptimizationWorkbench?.state||{};
  const optimizationDecision=()=>window.MCSOptimizationDecisionWorkbench?.state||{};
  const qualificationCampaign=()=>window.MCSQualificationCampaign?.state||{};
  const decisionCockpit=()=>window.MCSDecisionCockpit?.state||{};
  const engineerJourney=()=>window.MCSEngineerJourney?.state||{};
  const engineerScorecard=()=>window.MCSEngineeringScorecard?.state||{};
  const materialLibrary=()=>window.MCSMaterialLibrary?.state||{};
  const text=v=>String(v??'').replace(/\s+/g,' ').trim();
  const safe=v=>text(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const visible=el=>Boolean(el?.isConnected && el.getClientRects?.().length);
  const controlId=el=>el?.dataset?.hmiControlId||el?.id||el?.dataset?.actionReadinessId||el?.dataset?.hmiActionId||text(el?.textContent).slice(0,48)||'action';
  const result=(status,{blocker='',detail='',recovery=null,reason_code='',owns_disabled=true}={})=>({status,blocker,detail,recovery,reason_code,owns_disabled});
  const ready=(detail='')=>result('READY',{detail});
  const idle=(detail)=>result('IDLE',{detail,owns_disabled:true});
  const busy=(detail='操作进行中，请稍候。')=>result('BUSY',{detail,owns_disabled:false});
  const blocked=(blocker,recovery,reason_code='PREREQUISITE_NOT_READY')=>result('BLOCKED',{blocker,recovery,reason_code,owns_disabled:true});

  const recovery = {
    focus:(selector,label)=>({kind:'focus',selector,label}),
    click:(selector,label)=>({kind:'click',selector,label}),
    tab:(tab,label)=>({kind:'tab',tab,label}),
    invoke:(label,fn)=>({kind:'invoke',label,fn}),
    scroll:(selector,label)=>({kind:'scroll',selector,label}),
  };

  function projectEditorState(){
    return window.MCSProjectEditorReadinessV089G2?.inspect?.()||{active:false,dirty:false,name:''};
  }
  function designEditorState(){
    try{return editor()?.inspectTransaction?.()||{active:false,dirty_count:0,save_busy:false,conflict:null}}catch{return {active:false,dirty_count:0,save_busy:false,conflict:null}}
  }
  function designVerification(){
    try{return editor()?.verification?.snapshot?.()||{}}catch{return {}}
  }
  function selectedCount(selector){return qa(selector).filter(el=>el.checked).length}
  function hasProject(){return Boolean(ctx().projectId||app().activeProjectId)}
  function hasRevision(){return Boolean(ctx().motorRevisionId||app().workspaceRevision?.id||app().taskDesignRevisionId)}

  const RULES = [
    {
      id:'PROJECT_CREATE', selector:'#projectCreate',
      evaluate:()=> text(q('#projectCreateName')?.value) ? ready('项目名称已填写。') : blocked('请先填写项目名称。', recovery.focus('#projectCreateName','填写项目名称'),'PROJECT_NAME_REQUIRED')
    },
    {
      id:'PROJECT_EDITOR_SAVE', selector:'#projectEditorSave',
      evaluate:()=>{const s=projectEditorState();if(!s.active)return idle('项目编辑器未打开。');if(!text(s.name))return blocked('项目名称不能为空。',recovery.focus('#projectEditorName','填写项目名称'),'PROJECT_NAME_REQUIRED');if(!s.dirty)return idle('当前项目基本信息没有需要保存的修改。');return ready('当前修改可以保存。')}
    },
    {
      id:'SOLUTION_CREATE', selector:'#createSolutionCanonical,[data-canonical-create-solution]',
      evaluate:()=>hasProject()?ready():blocked('请先进入一个项目，再创建方案。',recovery.tab('projects','进入项目管理'),'PROJECT_REQUIRED')
    },
    {
      id:'SOLUTION_ANALYSIS', selector:'[data-canonical-analysis]',
      evaluate:el=>{if(!hasProject())return blocked('请先进入项目。',recovery.tab('projects','进入项目管理'),'PROJECT_REQUIRED');if(el.disabled){const id=el.dataset.canonicalAnalysis;return blocked('当前方案还没有可用于分析的电机版本。',recovery.click(`[data-canonical-motor="${CSS.escape(id||'')}"]`,'先配置电机'),'MOTOR_REVISION_REQUIRED')}return ready()}
    },
    {
      id:'WORKSPACE_TO_ANALYSIS', selector:'#workspaceToAnalysisCanonical',
      evaluate:()=>{if(!hasProject())return blocked('请先进入项目。',recovery.tab('projects','进入项目管理'),'PROJECT_REQUIRED');if(!ctx().solutionId&&!app().workspaceDesign?.id)return blocked('请先选择一个方案。',recovery.tab('solutions','进入方案管理'),'SOLUTION_REQUIRED');if(!hasRevision())return blocked('当前方案还没有已保存的电机版本。',recovery.tab('workspace','返回电机配置'),'MOTOR_REVISION_REQUIRED');return ready('当前电机版本可以进入分析配置。')}
    },
    {
      id:'WORKSPACE_CONFIRM_DESIGN', selector:'#workspaceConfirmDesign',
      evaluate:()=>{if(app().workspaceCreateBusy)return busy('正在创建首个电机版本…');return text(q('#workspaceDesignName')?.value)?ready():blocked('请填写设计名称。',recovery.focus('#workspaceDesignName','填写设计名称'),'DESIGN_NAME_REQUIRED')}
    },
    {
      id:'WORKSPACE_CONFIRM_REVISION', selector:'#workspaceConfirmRevision',
      evaluate:()=>hasRevision()?ready():blocked('请先选择一个基准电机版本。',recovery.tab('workspace','返回电机版本'),'MOTOR_REVISION_REQUIRED')
    },
    {
      id:'DESIGN_SAVE', selector:'#workbenchSaveV024,#workbenchQuickSaveV088',
      evaluate:()=>{const s=designEditorState();if(s.save_busy)return busy('正在保存设计，请稍候。');if(s.conflict)return blocked('检测到草稿版本冲突，需要先重新加载最新草稿。',recovery.invoke('重新加载最新草稿',()=>editor()?.open?.()),'DRAFT_CONFLICT');if(!Number(s.dirty_count||0))return idle('当前没有未保存的设计修改。');return ready('当前设计修改可以保存。')}
    },
    {
      id:'DESIGN_NATIVE_CHECK', selector:'[data-workbench-run-native-check-v065]',
      evaluate:()=>{const v=designVerification();if(v.nativeBusy)return busy('Motor-CAD 原生检查正在运行。');if(v.precheckBusy)return busy('Studio 设计检查正在运行。');if(!v.precheckCurrent)return blocked('当前草稿还没有对应的 Studio 设计检查。',recovery.click('[data-workbench-run-studio-check-v065]','先运行 Studio 检查'),'STUDIO_CHECK_REQUIRED');const issues=v.precheck?.issues||[],blocking=issues.filter(row=>String(row.severity||'').toUpperCase()==='BLOCKING');if(blocking.length)return blocked(`Studio 检查仍有 ${blocking.length} 个阻断项。`,q('[data-workbench-issue="0"]')?recovery.click('[data-workbench-issue="0"]','定位第一个问题'):recovery.click('[data-workbench-run-studio-check-v065]','重新运行 Studio 检查'),'STUDIO_CHECK_BLOCKED');return ready('Studio 检查已通过；系统会自动补齐必要的编辑事务证据后运行 Motor-CAD 检查。')}
    },
    {
      id:'ANALYSIS_CREATE', selector:'#analysisCreateV076',
      evaluate:()=>{if(!hasProject())return blocked('请先进入项目。',recovery.tab('projects','进入项目管理'),'PROJECT_REQUIRED');if(!hasRevision())return blocked('分析配置必须引用一个已保存的电机版本。',recovery.tab('workspace','返回电机配置'),'MOTOR_REVISION_REQUIRED');return ready()}
    },
    {
      id:'ANALYSIS_SAVE_CASES', selector:'[data-save-cases-v076]',
      evaluate:()=>analysis().active?ready():blocked('请先创建或选择分析配置。',recovery.click('#analysisCreateV076','新建分析配置'),'ANALYSIS_REQUIRED')
    },
    {
      id:'ANALYSIS_SAVE_INPUT', selector:'#analysisSaveDomainV076',
      evaluate:()=>analysis().active?ready():blocked('请先创建或选择分析配置。',recovery.click('#analysisCreateV076','新建分析配置'),'ANALYSIS_REQUIRED')
    },
    {
      id:'ANALYSIS_SAVE_SOLVER', selector:'[data-save-solver-v076]',
      evaluate:()=>analysis().active?ready():blocked('请先创建或选择分析配置。',recovery.click('#analysisCreateV076','新建分析配置'),'ANALYSIS_REQUIRED')
    },
    {
      id:'ANALYSIS_FULL_CHECK', selector:'#analysisFullCheckV076',
      evaluate:()=>{const a=analysis(),plan=a.executionPlan;if(!a.active)return blocked('请先创建或选择分析配置。',recovery.click('#analysisCreateV076','新建分析配置'),'ANALYSIS_REQUIRED');if(a.fullCheck?.running)return busy('Motor-CAD 完整计算前检查正在运行。');if(!plan)return blocked('完整计算前检查需要先加载执行计划。',q('#analysisInitialPlanV076')?recovery.click('#analysisInitialPlanV076','加载执行计划'):recovery.click('#analysisRefreshPlanV076','刷新执行计划'),'EXECUTION_PLAN_REQUIRED');if(!plan.can_submit)return blocked('配置检查仍有阻断项，请先查看固定在当前页面的处理建议。',recovery.scroll('#analysisIssueActionsV090','查看处理建议'),'ANALYSIS_BLOCKED');return ready('可以运行完整计算前检查。')}
    },
    {
      id:'ANALYSIS_SUBMIT', selector:'#analysisSubmitV076',
      evaluate:()=>{const a=analysis(),plan=a.executionPlan,full=a.fullCheck;if(!a.active)return blocked('请先创建或选择分析配置。',recovery.click('#analysisCreateV076','新建分析配置'),'ANALYSIS_REQUIRED');if(full?.running)return busy('Motor-CAD 完整计算前检查正在运行。');if(!plan)return blocked('尚未加载当前分析的执行计划。',q('#analysisInitialPlanV076')?recovery.click('#analysisInitialPlanV076','加载执行计划'):recovery.click('#analysisRefreshPlanV076','刷新执行计划'),'EXECUTION_PLAN_REQUIRED');if(!plan.can_submit)return blocked('当前分析仍有阻断项，尚不能提交计算。',recovery.scroll('#analysisIssueActionsV090','查看处理建议'),'ANALYSIS_BLOCKED');if(!full?.valid)return blocked('Studio 配置已就绪，还需要完成 Motor-CAD 完整计算前检查。',recovery.click('#analysisFullCheckV076','运行完整计算前检查'),'FULL_NATIVE_CHECK_REQUIRED');return ready('当前执行计划和 Motor-CAD 检查证据均已就绪。')}
    },
    {
      id:'STANDARD_VALIDATION_RUN', selector:'[data-svp-run]',
      evaluate:()=>{const s=svp(),p=s.payload;if(s.running)return busy('标准设计验证正在执行 Motor-CAD 计算前检查，请勿重复提交。');if(!ctx().motorRevisionId)return blocked('标准验证需要一个已保存的电机版本。',recovery.tab('workspace','返回电机配置'),'MOTOR_REVISION_REQUIRED');if(!p)return blocked('标准验证计划尚未加载。',recovery.click('[data-svp-preview]','刷新验证计划'),'VALIDATION_PLAN_REQUIRED');if(!p.ready_to_materialize)return blocked('标准验证仍有不可用或待确认步骤。',recovery.tab('analysisConfig','打开分析配置'),'VALIDATION_STEP_BLOCKED');return ready()}
    },
    {
      id:'RESULT_OPEN_CASE', selector:'#loadCaseViewer',
      evaluate:()=>{if(!text(q('#viewerTaskSelect')?.value))return blocked('请先选择一个计算任务。',recovery.focus('#viewerTaskSelect','选择计算任务'),'TASK_REQUIRED');if(!text(q('#viewerCaseSelect')?.value))return blocked('请先选择一个可用计算工况。',recovery.focus('#viewerCaseSelect','选择计算工况'),'CASE_REQUIRED');return ready()}
    },
    {
      id:'RESULT_LOAD_ANALYTICS', selector:'#loadAnalytics',
      evaluate:()=>text(q('#analyticsTaskSelect')?.value)?ready():blocked('请先选择一个计算任务。',recovery.focus('#analyticsTaskSelect','选择计算任务'),'TASK_REQUIRED')
    },
    {
      id:'RESULT_COMPARE_SELECTED', selector:'#compareSelectedCases',
      evaluate:()=>{const n=app().compareCaseIds?.size??selectedCount('[data-compare-case]:checked');if(n<2)return blocked('至少选择 2 个可用计算工况才能比较。',recovery.scroll('#analyticsTable','选择至少两个计算工况'),'TWO_CASES_REQUIRED');if(n>8)return blocked('一次最多比较 8 个计算工况。',recovery.scroll('#analyticsTable','调整计算工况选择'),'TOO_MANY_CASES');return ready()}
    },
    {
      id:'REVISION_COMPARE', selector:'[data-revision-run-v069]',
      evaluate:()=>selectedCount('[data-revision-choice-v069]:checked')>=2?ready():blocked('至少选择 2 个电机版本才能比较。',recovery.scroll('.revision-pills-v069','选择至少两个电机版本'),'TWO_REVISIONS_REQUIRED')
    },
    {
      id:'CASE_COMPARE_LOAD', selector:'[data-case-compare-load-v069]',
      evaluate:()=>{const sel=q('[data-case-compare-task-v069]');return text(sel?.value)?ready():blocked('请先选择一个包含结果的计算任务。',recovery.focus('[data-case-compare-task-v069]','选择计算任务'),'TASK_REQUIRED')}
    },
    {
      id:'CASE_COMPARE_RUN', selector:'[data-case-compare-run-v069]',
      evaluate:()=>selectedCount('[data-case-compare-case-v069]:checked')>=2?ready():blocked('至少选择 2 个具有正式计算结果的工况。',recovery.scroll('.case-selector-v069','选择至少两个计算工况'),'TWO_CASES_REQUIRED')
    },
    {
      id:'MATERIAL_ASSIGN', selector:'[data-material-choose-v062]',
      evaluate:()=>ready('当前材料可以赋值给目标部件。')
    },
    {
      id:'QUALIFICATION_RUN', selector:'#runQualification',
      evaluate:()=>text(q('#qualificationTemplate')?.value)?ready():blocked('请先选择需要检查的电机模板。',recovery.focus('#qualificationTemplate','选择电机模板'),'TEMPLATE_REQUIRED')
    },
    {
      id:'RESULT_PROBE', selector:'#probeResults',
      evaluate:()=>{if(!text(q('#resultCalibrationTemplate')?.value))return blocked('请先选择用于结果探测的模板。',recovery.focus('#resultCalibrationTemplate','选择模板'),'TEMPLATE_REQUIRED');if(!(app().resultProbes||[]).length)return blocked('请先载入推荐 Graph，再执行探测。',recovery.click('#loadRecommendedProbes','载入推荐 Graph'),'PROBE_LIST_REQUIRED');return ready()}
    },
    {
      id:'DATASET_BUILD', selector:'#buildDataset',
      evaluate:()=>{const total=['#factorySplitDev','#factorySplitVal','#factorySplitHold'].reduce((sum,s)=>sum+Number(q(s)?.value||0),0);if(total<=0)return blocked('数据分区权重之和必须大于 0。',recovery.focus('#factorySplitDev','设置数据分区'),'PARTITION_REQUIRED');return ready()}
    },
    {
      id:'NATIVE_QUALIFICATION_SUITE', selector:'#runNativeParitySuiteClosure', evaluate:()=>ready()
    },
    { id:'SYSTEM_BROWSE_MOTORCAD', selector:'#browseMotorcadExe', evaluate:()=>ready('\u5f53\u524d\u7cfb\u7edf\u8bca\u65ad\u53ef\u4ee5\u6267\u884c\u3002') },
    { id:'SYSTEM_DEEP_PREFLIGHT', selector:'#deepPreflight', evaluate:el=>el.disabled&&el.dataset.actionReadiness==='READY'?busy():ready('\u5f53\u524d\u7cfb\u7edf\u8bca\u65ad\u53ef\u4ee5\u6267\u884c\u3002') },
    { id:'SETUP_CONTINUE_PROJECTS', selector:'#setupContinueProjects,[data-go="setup"]', evaluate:()=>ready() },
    { id:'PROJECT_ENTER_RESTORE', selector:'[data-project-enter],[data-project-restore]', evaluate:()=>ready() },
    {
      id:'AUTOMATION_REGISTRY_IMPORT', selector:'#importAutomationRegistry',
      evaluate:()=>text(q('#automationText')?.value)?ready():blocked('\u5f53\u524d\u6ca1\u6709\u53ef\u5bfc\u5165\u7684 Automation \u53c2\u6570\u6587\u672c\u3002',recovery.focus('#automationText','\u586b\u5199\u53c2\u6570\u5217\u8868\u6587\u672c'),'AUTOMATION_TEXT_REQUIRED')
    },
    { id:'RC_REFRESH', selector:'#refreshReleaseCandidateGateV089F', evaluate:()=>ready('\u5f53\u524d\u8d44\u683c\u5de5\u5177\u53ef\u4ee5\u6267\u884c\u3002') },
    { id:'HMI_QUALIFICATION_SCAN', selector:'#runHmiQualificationV089B', evaluate:()=>ready('\u5f53\u524d\u8d44\u683c\u5de5\u5177\u53ef\u4ee5\u6267\u884c\u3002') },
    { id:'NATIVE_PARITY_PROFILE', selector:'[data-native-parity-run]', evaluate:()=>ready('\u5f53\u524d\u539f\u751f\u9010\u9879\u5bf9\u7167\u53ef\u4ee5\u6267\u884c\u3002') },
    {
      id:'WORKSPACE_NEW_DESIGN', selector:'#workspaceNewDesign',
      evaluate:()=>hasProject()?ready('\u5f53\u524d\u5de5\u4f5c\u533a\u53ef\u4ee5\u521b\u5efa\u65b0\u7684\u9884\u5236\u8bbe\u8ba1\u3002'):blocked('\u8bf7\u5148\u8fdb\u5165\u9879\u76ee\u3002',recovery.tab('projects','\u8fdb\u5165\u9879\u76ee\u7ba1\u7406'),'PROJECT_REQUIRED')
    },
    {
      id:'TEMPLATE_USE', selector:'[data-use-template],[data-starter-use]',
      evaluate:()=>hasProject()?ready('\u4f7f\u7528\u5f53\u524d\u6a21\u677f\u521b\u5efa\u8bbe\u8ba1\u3002'):blocked('\u8bf7\u5148\u8fdb\u5165\u9879\u76ee\u3002',recovery.tab('projects','\u8fdb\u5165\u9879\u76ee\u7ba1\u7406'),'PROJECT_REQUIRED')
    },
    {
      id:'GOLDEN_STARTER_CONFIRM', selector:'#goldenStarterConfirmV087',
      evaluate:()=>{if(!hasProject())return blocked('\u8bf7\u5148\u8fdb\u5165\u9879\u76ee\u3002',recovery.tab('projects','\u8fdb\u5165\u9879\u76ee\u7ba1\u7406'),'PROJECT_REQUIRED');if(!text(q('#goldenStarterNameV087')?.value))return blocked('\u8bf7\u586b\u5199\u8bbe\u8ba1\u540d\u79f0\u3002',recovery.focus('#goldenStarterNameV087','\u586b\u5199\u8bbe\u8ba1\u540d\u79f0'),'DESIGN_NAME_REQUIRED');return ready()}
    },
    {
      id:'CANONICAL_MOTOR_OPEN', selector:'[data-canonical-motor]',
      evaluate:()=>hasProject()?ready('\u5f53\u524d\u65b9\u6848\u53ef\u4ee5\u8fdb\u5165\u7535\u673a\u914d\u7f6e\u3002'):blocked('\u8bf7\u5148\u8fdb\u5165\u9879\u76ee\u3002',recovery.tab('projects','\u8fdb\u5165\u9879\u76ee\u7ba1\u7406'),'PROJECT_REQUIRED')
    },
    { id:'DIALOG_PRIMARY', selector:'[data-dialog-action].primary', evaluate:el=>el.disabled?blocked('\u5f53\u524d\u5bf9\u8bdd\u6846\u786e\u8ba4\u64cd\u4f5c\u5c1a\u4e0d\u53ef\u6267\u884c\u3002',recovery.click('[data-dialog-action]:not(.primary):not(:disabled)','\u53d6\u6d88\u5e76\u8fd4\u56de\u4fee\u6539'),'DIALOG_CONFIRM_BLOCKED'):ready() },
    {
      id:'LEGACY_REVISION_SAVE', selector:'#saveDesignRevision',
      evaluate:()=>qa('[data-design-base].changed').length?ready():idle('\u5f53\u524d\u6ca1\u6709\u53c2\u6570\u4fee\u6539\uff0c\u65e0\u9700\u521b\u5efa\u65b0\u7248\u672c\u3002')
    },
    { id:'DESIGN_FLOW_NEXT', selector:'[data-design-next-v061],[data-workbench-next-v063]', evaluate:()=>ready() },
    { id:'DESIGN_SAFE_REPAIR', selector:'[data-workbench-native-safe-repair-v088c]', evaluate:()=>ready() },
    {
      id:'DESIGN_EDIT_VIEW', selector:'[data-edit-view-v031]',
      evaluate:el=>el.disabled?idle('\u5f53\u524d\u7535\u673a\u7248\u672c\u6ca1\u6709\u8fd9\u4e2a\u53ef\u7f16\u8f91\u53c2\u6570\u5206\u7ec4\u3002'):ready()
    },
    {
      id:'ANALYSIS_CONFIRM_CREATE', selector:'#analysisConfirmCreateV076',
      evaluate:el=>{const a=analysis();if(a.templatePreviewLoading)return busy('\u5206\u6790\u6a21\u677f\u63a8\u8350\u4ecd\u5728\u751f\u6210\uff0c\u8bf7\u7a0d\u5019\u3002');if(a.hmiMode==='advanced'){if(!a.createRecipeId)return blocked('\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u53ef\u7528\u7684\u5206\u6790\u914d\u65b9\u3002',recovery.click('[data-recipe-v076]:not(:disabled)','\u9009\u62e9\u5206\u6790\u914d\u65b9'),'ANALYSIS_RECIPE_REQUIRED');return ready()}if(!a.createTemplateId)return blocked('\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u53ef\u7528\u7684\u5206\u6790\u6a21\u677f\u3002',recovery.click('[data-analysis-template]:not(:disabled)','\u9009\u62e9\u5206\u6790\u6a21\u677f'),'ANALYSIS_TEMPLATE_REQUIRED');if(!a.templatePreview?.ready_to_create)return blocked('\u6a21\u677f\u4ecd\u6709\u5173\u952e\u5de5\u7a0b\u51b3\u7b56\u9700\u8981\u786e\u8ba4\u3002',recovery.scroll('.analysis-guidance-panel','\u5b8c\u6210\u5173\u952e\u5de5\u7a0b\u51b3\u7b56'),'ANALYSIS_TEMPLATE_DECISIONS_REQUIRED');return ready()}
    },
    {
      id:'ANALYSIS_NEXT', selector:'[data-next-v076]',
      evaluate:()=>analysis().active?ready('\u5f53\u524d\u5206\u6790\u53ef\u4ee5\u8fdb\u5165\u4e0b\u4e00\u6b65\u3002'):blocked('\u8bf7\u5148\u521b\u5efa\u6216\u9009\u62e9\u5206\u6790\u914d\u7f6e\u3002',recovery.click('#analysisCreateV076','\u65b0\u5efa\u5206\u6790\u914d\u7f6e'),'ANALYSIS_REQUIRED')
    },
    {
      id:'ANALYSIS_INITIAL_PLAN', selector:'#analysisInitialPlanV076',
      evaluate:()=>analysis().active?ready('\u53ef\u4ee5\u52a0\u8f7d\u5f53\u524d\u6267\u884c\u8ba1\u5212\u3002'):blocked('\u8bf7\u5148\u521b\u5efa\u6216\u9009\u62e9\u5206\u6790\u914d\u7f6e\u3002',recovery.click('#analysisCreateV076','\u65b0\u5efa\u5206\u6790\u914d\u7f6e'),'ANALYSIS_REQUIRED')
    },
    { id:'ANALYSIS_RETRY', selector:'[data-analysis-retry-v076]', evaluate:()=>ready('\u5f53\u524d\u5931\u8d25\u72b6\u6001\u53ef\u4ee5\u91cd\u65b0\u52a0\u8f7d\u3002') },
    { id:'ANALYSIS_MONITOR_RESULTS', selector:'[data-analysis-monitor-results-v067]', evaluate:()=>ready('\u5f53\u524d\u7ed3\u679c\u5df2\u53ef\u6253\u5f00\u3002') },
    {
      id:'TASK_OPEN_RESULTS', selector:'#openTaskResults',
      evaluate:()=>{const t=app().currentTaskDetail||{};const usable=Number(t.usable_cases||0)||((t.cases||[]).filter(r=>r.result_bundle_id||r.result?.scalars&&Object.keys(r.result.scalars).length).length);if(usable>0)return ready();if(q('#retryTask'))return blocked('\u5f53\u524d\u4efb\u52a1\u5b58\u5728\u5931\u8d25\u5de5\u51b5\uff0c\u53ef\u5148\u91cd\u8bd5\u3002',recovery.click('#retryTask','\u91cd\u8bd5\u5931\u8d25\u5de5\u51b5'),'TASK_RESULTS_NOT_READY');return blocked('\u5f53\u524d\u4efb\u52a1\u8fd8\u6ca1\u6709\u53ef\u7528\u5de5\u7a0b\u7ed3\u679c\u3002',recovery.click('#refreshTasks','\u5237\u65b0\u4efb\u52a1\u72b6\u6001'),'TASK_RESULTS_NOT_READY')}
    },
    { id:'TASK_RETRY', selector:'#retryTask', evaluate:()=>ready() },
    {
      id:'OPT_LOAD_ANALYSIS', selector:'[data-opt-load-analysis-v069]',
      evaluate:el=>el.disabled?blocked('\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684\u57fa\u51c6\u5206\u6790\u3002',recovery.tab('analysisConfig','\u5148\u521b\u5efa\u5206\u6790\u914d\u7f6e'),'OPT_ANALYSIS_REQUIRED'):ready()
    },
    { id:'OPT_WIZARD_NEXT', selector:'[data-opt-wizard-next-v081a],[data-opt-study-preset-v087e="multi"]', evaluate:()=>ready() },
    {
      id:'OPT_SUBMIT', selector:'[data-opt-submit-v069]',
      evaluate:()=>{const o=optimization();if(!o.preview)return blocked('\u8bf7\u5148\u751f\u6210\u53c2\u6570\u7814\u7a76\u8ba1\u5212\u5e76\u68c0\u67e5\u3002',recovery.click('[data-opt-preview-v069]','\u751f\u6210\u8ba1\u5212\u5e76\u68c0\u67e5'),'OPT_PREVIEW_REQUIRED');if(!o.preview.can_submit)return blocked('\u5f53\u524d\u53c2\u6570\u7814\u7a76\u8ba1\u5212\u4ecd\u6709\u963b\u65ad\u9879\u3002',recovery.scroll('[data-opt-preview-result-v069]','\u67e5\u770b\u8ba1\u5212\u963b\u65ad\u9879'),'OPT_PREVIEW_BLOCKED');return ready()}
    },
    { id:'OPT_GUIDANCE_ACTION', selector:'[data-guidance-validate],[data-guidance-promote],[data-opt-new-v069],[data-opt-ledger-capture-v080d]', evaluate:()=>ready('\u5f53\u524d\u4f18\u5316\u64cd\u4f5c\u53ef\u4ee5\u6267\u884c\u3002') },
    {
      id:'OPT_PROMOTE', selector:'[data-opt-inspector-promote-v087e]',
      evaluate:el=>{if(!el.disabled)return ready();const d=optimizationDecision(),rows=d.data?.candidates||[],row=rows.find(r=>String(r.candidate_id||r.case_id)===String(d.selectedCandidateId));if(row?.is_baseline)return idle('\u57fa\u51c6\u5019\u9009\u65e0\u9700\u751f\u6210\u65b0\u8bbe\u8ba1\u7248\u672c\u3002');if(q('[data-opt-inspector-validate-v087e]:not(:disabled)'))return blocked('\u5019\u9009\u5c1a\u672a\u901a\u8fc7\u9a8c\u8bc1\uff0c\u6682\u4e0d\u80fd\u4fdd\u5b58\u4e3a\u65b0\u8bbe\u8ba1\u7248\u672c\u3002',recovery.click('[data-opt-inspector-validate-v087e]','\u5148\u9a8c\u8bc1\u5019\u9009'),'CANDIDATE_VALIDATION_REQUIRED');return blocked('\u5019\u9009\u5c1a\u672a\u901a\u8fc7\u9a8c\u8bc1\uff0c\u6682\u4e0d\u80fd\u4fdd\u5b58\u4e3a\u65b0\u8bbe\u8ba1\u7248\u672c\u3002',recovery.scroll('.candidate-inspector-status-v087e','\u67e5\u770b\u5019\u9009\u72b6\u6001'),'CANDIDATE_VALIDATION_REQUIRED')}
    },
    {
      id:'QUALIFICATION_MATERIALIZE', selector:'[data-qc-materialize]',
      evaluate:()=>selectedCount('[data-qc-item]:checked')>0?ready():blocked('\u8bf7\u81f3\u5c11\u52fe\u9009\u4e00\u4e2a\u9700\u8981\u51bb\u7ed3\u7684\u9a8c\u8bc1\u9879\u76ee\u3002',recovery.scroll('.qualification-plan-list','\u9009\u62e9\u9a8c\u8bc1\u9879\u76ee'),'QUALIFICATION_ITEM_REQUIRED')
    },
    { id:'ENGINEERING_REQUIREMENTS_EDIT', selector:'[data-edit-engineering-requirements]', evaluate:()=>ready('\u5f53\u524d\u5de5\u7a0b\u8981\u6c42\u53ef\u4ee5\u7f16\u8f91\u3002') },
    {
      id:'ENGINEERING_REQUIREMENTS_SAVE', selector:'[data-save-requirements]',
      evaluate:()=>qa('[data-requirement-row]').length?ready('\u5f53\u524d\u5de5\u7a0b\u8981\u6c42\u53ef\u4ee5\u4fdd\u5b58\u3002'):blocked('\u8bf7\u81f3\u5c11\u6dfb\u52a0\u4e00\u9879\u5de5\u7a0b\u8981\u6c42\u3002',recovery.click('[data-add-requirement]','\u6dfb\u52a0\u5de5\u7a0b\u8981\u6c42'),'REQUIREMENT_RULE_REQUIRED')
    },
    { id:'SET_PROJECT_BASELINE', selector:'[data-set-project-baseline]', evaluate:()=>ready('\u5f53\u524d\u7ed3\u679c\u53ef\u4ee5\u8bbe\u4e3a\u9879\u76ee\u57fa\u51c6\u3002') },
    {
      id:'DECISION_PRIMARY', selector:'[data-decision-primary]',
      evaluate:()=>{const a=decisionCockpit().payload?.primary_next_action||null;return a&&(a.route||a.stage)?ready('\u5f53\u524d\u52a8\u4f5c\u7531\u5de5\u7a0b\u6d41\u7a0b\u751f\u6210\uff0c\u53ef\u4ee5\u7ee7\u7eed\u3002'):blocked('\u5f53\u524d\u5c1a\u672a\u5f62\u6210\u53ef\u6267\u884c\u7684\u5de5\u7a0b\u51b3\u7b56\u52a8\u4f5c\u3002',recovery.tab('analysisConfig','\u8fd4\u56de\u5206\u6790\u914d\u7f6e'),'DECISION_ACTION_REQUIRED')}
    },
    { id:'SCORECARD_NEXT', selector:'[data-scorecard-next]', evaluate:()=>ready('\u5f53\u524d\u52a8\u4f5c\u7531\u5de5\u7a0b\u6d41\u7a0b\u751f\u6210\uff0c\u53ef\u4ee5\u7ee7\u7eed\u3002') },
    { id:'JOURNEY_PRIMARY', selector:'[data-journey-primary],[data-hmi-action="ENGINEER_FOCUS_NEXT"],[data-next-go]', evaluate:()=>ready('\u5f53\u524d\u52a8\u4f5c\u7531\u5de5\u7a0b\u6d41\u7a0b\u751f\u6210\uff0c\u53ef\u4ee5\u7ee7\u7eed\u3002') },
    {
      id:'MATERIAL_SAVE', selector:'[data-material-save-v089g2]',
      evaluate:()=>text(q('#materialNameV061')?.value)?ready():blocked('\u6750\u6599\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a\u3002',recovery.focus('#materialNameV061','\u586b\u5199\u6750\u6599\u540d\u79f0'),'MATERIAL_NAME_REQUIRED')
    },
    { id:'MATERIAL_SCAN', selector:'[data-material-scan-v061]', evaluate:()=>ready('\u5f53\u524d\u6750\u6599\u6570\u636e\u5e93\u53ef\u4ee5\u91cd\u65b0\u626b\u63cf\u3002') },
  ];

  // High-value primary action inventory. Any visible primary action not matched
  // here is reported as UNMANAGED and blocks the G2 release gate until owned.
  const PRIMARY_FAMILY_SELECTORS = [
    '#browseMotorcadExe','#deepPreflight','#setupContinueProjects','[data-go="setup"]',
    '#projectCreate','#projectEditorSave','[data-project-enter]','[data-project-restore]',
    '#createSolutionCanonical','[data-canonical-create-solution]','[data-canonical-motor]','[data-canonical-analysis]',
    '#workspaceNewDesign','#workspaceToAnalysisCanonical','#workspaceConfirmDesign','#workspaceConfirmRevision',
    '[data-use-template]','[data-starter-use]','#goldenStarterConfirmV087',
    '#saveDesignRevision','#workbenchSaveV024','#workbenchQuickSaveV088','[data-design-next-v061]','[data-workbench-next-v063]',
    '[data-workbench-run-native-check-v065]','[data-workbench-native-safe-repair-v088c]','[data-edit-view-v031]',
    '#analysisCreateV076','#analysisConfirmCreateV076','[data-next-v076]','[data-save-cases-v076]','#analysisSaveDomainV076','[data-save-solver-v076]',
    '#analysisInitialPlanV076','#analysisFullCheckV076','#analysisSubmitV076','[data-analysis-retry-v076]','[data-analysis-monitor-results-v067]','[data-svp-run]',
    '#openTaskResults','#retryTask','#loadCaseViewer','#loadAnalytics','#compareSelectedCases',
    '[data-revision-run-v069]','[data-case-compare-load-v069]','[data-case-compare-run-v069]',
    '[data-opt-load-analysis-v069]','[data-opt-wizard-next-v081a]','[data-opt-study-preset-v087e="multi"]','[data-opt-submit-v069]',
    '[data-guidance-validate]','[data-guidance-promote]','[data-opt-new-v069]','[data-opt-ledger-capture-v080d]','[data-opt-inspector-promote-v087e]',
    '[data-qc-materialize]','[data-edit-engineering-requirements]','[data-save-requirements]','[data-set-project-baseline]',
    '[data-decision-primary]','[data-scorecard-next]','[data-journey-primary]','[data-hmi-action="ENGINEER_FOCUS_NEXT"]','[data-next-go]',
    '[data-material-save-v089g2]','[data-material-choose-v062]','[data-material-scan-v061]',
    '[data-native-parity-run]','#buildDataset','#runNativeParitySuiteClosure','#runQualification','#probeResults',
    '#refreshReleaseCandidateGateV089F','#runHmiQualificationV089B','#importAutomationRegistry','[data-dialog-action].primary'
  ];

  function ruleFor(el){return RULES.find(rule=>{try{return el.matches(rule.selector)}catch{return false}})||null}
  function isPrimary(el){return Boolean(el?.matches?.('.primary')||PRIMARY_FAMILY_SELECTORS.some(selector=>{try{return el.matches(selector)}catch{return false}}))}
  function canRecovery(rec){
    if(!rec)return false;
    if(rec.kind==='focus'||rec.kind==='scroll'){const target=q(rec.selector);return Boolean(target&&!target.disabled)}
    if(rec.kind==='click'){const target=q(rec.selector);return Boolean(target&&!target.disabled)}
    if(rec.kind==='tab'){const target=q(`[data-tab="${CSS.escape(rec.tab||'')}"]`);return Boolean((target&&!target.disabled)||typeof window.showTab==='function')}
    if(rec.kind==='invoke')return typeof rec.fn==='function';
    return false;
  }
  function serializeRecovery(rec){return rec?{kind:rec.kind,label:rec.label||'',selector:rec.selector||null,tab:rec.tab||null,available:canRecovery(rec)}:null}
  function executeRecovery(rec){
    if(!rec)return false;
    if(rec.kind==='focus'){const target=q(rec.selector);if(!target)return false;target.scrollIntoView?.({block:'center',behavior:'smooth'});target.focus?.();return true}
    if(rec.kind==='scroll'){const target=q(rec.selector);if(!target)return false;target.scrollIntoView?.({block:'center',behavior:'smooth'});target.querySelector?.('input,select,button:not(:disabled)')?.focus?.();return true}
    if(rec.kind==='click'){const target=q(rec.selector);if(!target||target.disabled)return false;target.scrollIntoView?.({block:'center',behavior:'smooth'});target.click();return true}
    if(rec.kind==='tab'){
      const target=q(`[data-tab="${CSS.escape(rec.tab||'')}"]`);if(target&&!target.disabled){target.click();return true}
      if(typeof window.showTab==='function'){window.showTab(rec.tab);return true}
      return false;
    }
    if(rec.kind==='invoke'&&typeof rec.fn==='function'){rec.fn();return true}
    return false;
  }

  function evaluate(el){
    const rule=ruleFor(el);
    if(!rule){
      if(isPrimary(el)){
        if(el.disabled)return result('UNMANAGED',{blocker:'该主操作处于禁用状态，但尚未注册明确的阻断原因和恢复动作。',reason_code:'UNMANAGED_DISABLED_PRIMARY',owns_disabled:false});
        return result('UNMANAGED',{detail:'可点击，但尚未纳入 G2 Action Readiness 规则。',owns_disabled:false});
      }
      return null;
    }
    let row;
    try{row=rule.evaluate(el)}catch(error){row=result('BLOCKED',{blocker:`动作状态解析失败：${error.message||error}`,reason_code:'READINESS_EVALUATION_ERROR',owns_disabled:false})}
    if(row.status==='READY'&&el.disabled&&el.dataset.actionReadiness==='READY'&&el.dataset.actionReadinessOwnsDisabled!=='true')row=busy();
    return {...row,rule_id:rule.id};
  }

  function helperHost(el){
    if(el.matches?.('[data-engineer-stage]'))return null;
    const group=el.closest?.('.analysis-check-actions-v076,.standard-validation-footer-v087d,.actions,.material-picker-assign-footer-v088,.section-head,footer');
    return group||el.parentElement;
  }
  function removeHelper(el){const id=controlId(el);q(`[data-action-readiness-helper-for="${CSS.escape(id)}"]`)?.remove()}
  function renderHelper(el,row){
    const id=controlId(el),existing=q(`[data-action-readiness-helper-for="${CSS.escape(id)}"]`);
    if(row.status!=='BLOCKED'||!visible(el)){existing?.remove();return}
    const host=helperHost(el);if(!host){existing?.remove();return}
    const available=canRecovery(row.recovery),signature=[row.blocker||'',row.recovery?.label||'',available?'1':'0'].join('|');
    if(existing?.dataset?.actionReadinessSignature===signature)return;
    existing?.remove();
    const note=document.createElement('div');note.className='action-readiness-note-v089g2';note.dataset.actionReadinessHelperFor=id;note.dataset.actionReadinessSignature=signature;
    note.innerHTML=`<div><b>\u6682\u65f6\u4e0d\u80fd\u6267\u884c</b><span>${safe(row.blocker||'\u5f53\u524d\u524d\u7f6e\u6761\u4ef6\u672a\u6ee1\u8db3\u3002')}</span></div>${row.recovery?`<button type="button" class="action-recovery-button-v089g2" data-action-recovery-for="${safe(id)}" ${available?'':'disabled'}>${safe(row.recovery.label||'\u5904\u7406\u963b\u65ad\u9879')}</button>`:''}`;
    if(host.classList?.contains('actions'))host.parentElement?.insertBefore(note,host.nextSibling);else host.appendChild(note);
    q('[data-action-recovery-for]',note)?.addEventListener('click',()=>{executeRecovery(row.recovery);scheduleRefresh('recovery')});
  }

  function applyElement(el,{render=true}={}){
    if(!(el instanceof HTMLButtonElement))return null;
    const row=evaluate(el);if(!row)return null;
    const id=controlId(el);
    if(row.owns_disabled){
      el.disabled=row.status!=='READY';
      if(row.status==='BLOCKED'||row.status==='IDLE')el.dataset.actionReadinessOwnsDisabled='true';
      else delete el.dataset.actionReadinessOwnsDisabled;
    }
    el.dataset.actionReadiness=row.status;el.dataset.actionReadinessRule=row.rule_id||'UNMANAGED';
    if(row.blocker){el.dataset.actionBlocker=row.blocker;el.setAttribute('aria-disabled','true');el.title=row.blocker}else{delete el.dataset.actionBlocker;el.setAttribute('aria-disabled',el.disabled?'true':'false');if(el.dataset.actionReadinessTitleOwned==='true'){el.removeAttribute('title');delete el.dataset.actionReadinessTitleOwned}}
    if(row.blocker)el.dataset.actionReadinessTitleOwned='true';
    const recoveryRow=serializeRecovery(row.recovery);if(recoveryRow?.label)el.dataset.actionRecovery=recoveryRow.label;else delete el.dataset.actionRecovery;
    el.classList.toggle('action-blocked-v089g2',row.status==='BLOCKED');el.classList.toggle('action-idle-v089g2',row.status==='IDLE');el.classList.toggle('action-busy-v089g2',row.status==='BUSY');
    const output={control_id:id,action_id:el.dataset.hmiActionId||el.id||row.rule_id||'',label:text(el.textContent),primary:isPrimary(el),visible:visible(el),enabled:!el.disabled,status:row.status,rule_id:row.rule_id||null,blocker:row.blocker||'',reason_code:row.reason_code||'',recovery:recoveryRow,dead_end:row.status==='BLOCKED'&&!recoveryRow?.available};
    rowsByControl.set(id,output);managed.set(el,output);if(render)renderHelper(el,row);return output;
  }

  function scan(root=document,{render=true}={}){const buttons=root instanceof HTMLButtonElement?[root]:qa('button',root);buttons.forEach(el=>{if(isPrimary(el)||ruleFor(el))applyElement(el,{render})});return buttons}
  function qualify(root=document,{render=false,skipScan=false}={}){
    if(!skipScan)scan(root,{render});
    const rows=qa('button',root).filter(el=>visible(el)&&isPrimary(el)).map(el=>managed.get(el)||applyElement(el,{render})||{control_id:controlId(el),label:text(el.textContent),primary:true,visible:true,status:'UNMANAGED',dead_end:Boolean(el.disabled),recovery:null});
    const blockedRows=rows.filter(row=>row.status==='BLOCKED'),deadEnds=rows.filter(row=>row.dead_end),unmanaged=rows.filter(row=>row.status==='UNMANAGED');
    return {authority:AUTHORITY,contract_version:CONTRACT_VERSION,generated_at:new Date().toISOString(),visible_primary_actions:rows.length,managed_primary_actions:rows.length-unmanaged.length,ready_count:rows.filter(r=>r.status==='READY').length,blocked_count:blockedRows.length,idle_count:rows.filter(r=>r.status==='IDLE').length,busy_count:rows.filter(r=>r.status==='BUSY').length,unmanaged_count:unmanaged.length,dead_end_count:deadEnds.length,qualified:deadEnds.length===0&&unmanaged.length===0,dead_ends:deadEnds,unmanaged,actions:rows};
  }
  function emitQualification(){window.dispatchEvent(new CustomEvent('mcs:action-readiness-updated',{detail:qualify(document,{render:false,skipScan:true})}))}
  function refreshNow(){clearTimeout(refreshTimer);refreshTimer=null;scan(document,{render:true});emitQualification()}
  function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refreshNow,40)}
  function readinessOnlyMutation(node){
    if(!(node instanceof Element))return true;
    if(node.matches?.('[data-action-readiness-helper-for],.action-readiness-note-v089g2'))return true;
    return Boolean(node.closest?.('[data-action-readiness-helper-for],.action-readiness-note-v089g2'));
  }
  function mutationNeedsRefresh(records){
    return records.some(record=>[...record.addedNodes,...record.removedNodes].some(node=>node instanceof Element&&!readinessOnlyMutation(node)));
  }

  const EVENTS=['mcs:engineering-context-changed','mcs:route-ready','mcs:workflow-truth-updated','mcs:design-draft-status','mcs:model-runtime-check','mcs:bootstrap-ready'];
  EVENTS.forEach(name=>window.addEventListener(name,scheduleRefresh));
  // A bounded 40 ms debounce stays below the short but real dead window that users
  // can perceive, while avoiding complete-document rescans twice per keystroke. The
  // old path could also trigger itself again through helper DOM mutations on dense pages.
  document.addEventListener('input',event=>{if(event.target?.matches?.('input,select,textarea'))scheduleRefresh()});
  document.addEventListener('change',event=>{if(event.target?.matches?.('input,select,textarea'))scheduleRefresh();else scheduleRefresh()});
  document.addEventListener('click',event=>{if(event.target?.closest?.('button,input,select'))setTimeout(scheduleRefresh,0)},true);
  if(document.body&&window.MutationObserver){mutationObserver=new MutationObserver(records=>{if(mutationNeedsRefresh(records))scheduleRefresh()});mutationObserver.observe(document.body,{childList:true,subtree:true})}
  document.addEventListener('DOMContentLoaded',()=>scheduleRefresh(),{once:true});window.addEventListener('load',()=>scheduleRefresh(),{once:true});

  window.MCSActionReadiness={authority:AUTHORITY,contractVersion:CONTRACT_VERSION,RULES,PRIMARY_FAMILY_SELECTORS,evaluate,applyElement,scan,qualify,executeRecovery,scheduleRefresh,refreshNow,rows:rowsByControl};
})();
