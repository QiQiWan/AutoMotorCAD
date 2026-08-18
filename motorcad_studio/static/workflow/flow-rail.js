/* V0.65 stable engineering workflow rail.
 * Extracted from the historical V0.31 compatibility layer; no Design DOM ownership.
 */
(() => {
  const $q=(selector,root=document)=>root.querySelector(selector);
  const $$q=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'');
  const number=(value,fallback=0)=>{const parsed=Number(value);if(value!==null&&value!==''&&Number.isFinite(parsed))return parsed;const backup=Number(fallback);return Number.isFinite(backup)?backup:fallback};
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const fmt=(value,digits=3)=>{if(value===null||value===undefined||value==='')return'—';const n=Number(value);return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:digits}):String(value)};
  const feaState={caseId:null,fieldKey:null,mesh:false,outlines:true,vectors:false,legend:true,range:'auto'};
  function stepProgress(){
    const guidance=state.uiGuidanceV030||{},map={design:0,analysis:1,solve:2,result:3};let progress=map[guidance.current_step]??0;
    if(guidance.status==='COMPLETED')progress=3;if(guidance.status==='RUNNING')progress=2;
    return{guidance,progress};
  }
  function activeFlowStep(){const tab=$q('.tab.active')?.id||'';if(['workspace','templates'].includes(tab))return'design';if(['newTask','tasks','simulationAssets'].includes(tab))return'analysis';if(tab==='monitor')return'solve';if(tab==='resultViewer')return'result';return state.uiGuidanceV030?.current_step||'design'}
  function upgradeFlowBar(){
    const bar=$q('#engineerFlowBarV030');if(!bar||bar.dataset.v031Applying==='1')return;
    bar.dataset.v031Applying='1';bar.classList.add('workflow-state-rail-v031');document.body.classList.add('motorcad-visual-workflow-v031');
    const {guidance,progress}=stepProgress(),active=activeFlowStep(),status=guidance.status||'NEEDS_CHECK';
    const stateMeta={READY:['可以计算','ready'],NEEDS_CHECK:['需要检查','needs-check'],BLOCKED:['无法计算','blocked'],RUNNING:['计算中','running'],COMPLETED:['已有结果','completed']}[status]||[status,'needs-check'];
    const rows=[['design','1','设计电机','结构 · 几何 · 绕组','workspace'],['analysis','2','分析与计算','工况 · 求解 · Precheck','analysisWorkbench'],['solve','3','运行计算','提交 · 求解 · 证据',status==='RUNNING'?'monitor':'analysisWorkbench'],['result','4','分析结果','性能 · 拓扑 · FEA','resultViewer']];
    bar.innerHTML=`<div class="workflow-state-head-v031"><div class="workflow-project-state-v031 ${stateMeta[1]}"><span></span><div><small>${safe(stateMeta[0])}</small><b>${safe(guidance.headline||'按四个工程阶段完成电机分析')}</b></div></div><div class="workflow-utilities-v031"><button type="button" data-v031-flow-tab="dashboard">项目概览</button><button type="button" data-v031-flow-tab="dataFactory">数据资产</button></div></div><div class="workflow-steps-v031">${rows.map(([id,n,title,desc,tab],index)=>{let cls=index<progress?'done':index===progress?'current':'pending';if(id===active)cls+=' active';if(status==='BLOCKED'&&index===progress)cls+=' blocked';if(status==='RUNNING'&&id==='solve')cls+=' running';return`${index?'<i></i>':''}<button type="button" data-v031-flow-tab="${tab}" class="${cls}"><span>${index<progress?'✓':n}</span><div><b>${title}</b><small>${desc}</small></div></button>`}).join('')}</div>`;
    $$q('[data-v031-flow-tab]',bar).forEach(button=>button.addEventListener('click',()=>typeof window.showTab==='function'&&showTab(button.dataset.v031FlowTab)));
    bar.dataset.v031Applying='0';
  }


  window.addEventListener('mcs:route-ready',upgradeFlowBar);
  document.addEventListener('change',event=>{if(event.target.id==='userMode')upgradeFlowBar()},true);
  window.MCSWorkflowRail={upgrade:upgradeFlowBar};
  queueMicrotask(upgradeFlowBar);
})();
