/* MotorCAD Studio V0.59.0 — compact engineer navigation and result-safe actions. */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const stageIndex={design:0,analysis:1,solve:2,result:3};
  const stageRows=[
    ['design','设计电机','保存可解的设计版本','workspace'],
    ['analysis','设置分析','工况、求解和输出通过检查','analysisWorkbench'],
    ['solve','运行计算','完成求解与结果提取','monitor'],
    ['result','分析结果','结果验证通过后形成工程结论','resultViewer'],
  ];
  let flowFrame=0;

  function activeStage(){
    const tab=q('.tab.active')?.id||'';
    if(['workspace','templates'].includes(tab))return'design';
    if(['analysisWorkbench','newTask','simulationAssets'].includes(tab))return'analysis';
    if(['monitor','tasks'].includes(tab))return'solve';
    if(tab==='resultViewer')return'result';
    return state.uiGuidanceV030?.current_step||'design';
  }
  function goTab(tab){
    if(typeof window.showTab==='function')window.showTab(tab);
  }
  function renderFlowDock(){
    const bar=q('#engineerFlowBarV030');
    if(!bar||!state.activeProjectId||q('#projectShell')?.classList.contains('hidden'))return;
    const guidance=state.uiGuidanceV030||{},current=guidance.current_step||'design',active=activeStage(),progress=stageIndex[current]??0;
    const status=guidance.status||'NEEDS_CHECK',statusMeta={READY:['可以设置计算','ready'],NEEDS_CHECK:['需要处理','attention'],BLOCKED:['当前被阻断','blocked'],RUNNING:['计算进行中','running'],COMPLETED:['已有可用结果','complete']}[status]||['状态待确认','attention'];
    const action=guidance.action||{},condition=stageRows.find(row=>row[0]===active)?.[2]||'完成当前工程阶段';
    const signature=[status,guidance.headline||'',current,active,action.label||'',action.route||''].join('|');if(bar.classList.contains('workflow-action-dock-v059')&&bar.dataset.v059Signature===signature)return;
    bar.className='workflow-action-dock-v059';
    bar.dataset.v059Signature=signature;
    bar.innerHTML=`<div class="flow-status-v059 ${statusMeta[1]}"><span></span><div><small>${safe(statusMeta[0])}</small><b>${safe(guidance.headline||'按四个工程阶段完成电机分析')}</b></div></div><div class="workflow-steps-v031 flow-steps-v059">${stageRows.map(([id,title,done,tab],index)=>`<button type="button" data-flow-tab-v059="${tab}" class="${id===active?'active ':''}${index<progress?'done':index===progress?'current':'pending'}"><span>${index<progress?'✓':index+1}</span><div><b>${title}</b><small>${done}</small></div></button>`).join('')}</div><div class="flow-action-v059"><span>当前完成条件</span><b>${safe(condition)}</b>${action.label?`<button type="button" class="primary" data-flow-action-v059="${safe(action.route||'')}">${safe(action.label)}</button>`:''}</div>`;
    qa('[data-flow-tab-v059]',bar).forEach(button=>button.addEventListener('click',()=>goTab(button.dataset.flowTabV059)));
    q('[data-flow-action-v059]',bar)?.addEventListener('click',event=>{const route=event.currentTarget.dataset.flowActionV059;if(route&&window.MCSRouter?.navigate)MCSRouter.navigate(route);else goTab(stageRows[Math.min(progress,3)][3])});
  }
  function scheduleFlowDock(){cancelAnimationFrame(flowFrame);flowFrame=requestAnimationFrame(renderFlowDock)}

  function decorateMonitor(snapshot){
    const toolbar=q('#monitor .monitor-toolbar');if(!toolbar||!snapshot)return;
    let outcome=q('#monitorOutcomeV059');if(!outcome){outcome=document.createElement('div');outcome.id='monitorOutcomeV059';outcome.className='monitor-outcome-v059';toolbar.insertAdjacentElement('afterend',outcome)}
    const status=String(snapshot.status||''),terminal=['COMPLETED','PARTIALLY_COMPLETED','FAILED','CANCELLED'].includes(status),usable=Number(snapshot.case_summary?.valid||0)+Number(snapshot.case_summary?.warning||0);
    if(!terminal){outcome.classList.add('hidden');return}
    const success=usable>0,title=success?`计算结束，${usable} 个工况结果可用`:'计算结束，尚无通过结果验证的工况',detail=success?'进入结果页查看性能、曲线和有限元空间场。':'进入计算记录查看失败、缺失输出或有限元场问题。';
    outcome.className=`monitor-outcome-v059 ${success?'success':'attention'}`;
    outcome.innerHTML=`<div><span>${success?'✓':'!'}</span><div><b>${title}</b><small>${detail}</small></div></div><button type="button" class="${success?'primary':''}" data-monitor-next-v059>${success?'查看工程结果':'查看计算问题'}</button>`;
    q('[data-monitor-next-v059]',outcome)?.addEventListener('click',()=>{const task=state.monitorTask;if(!task)return;if(window.MCSRouter?.navigate&&state.activeProjectId){const suffix=success?`results/tasks/${encodeURIComponent(task)}`:`simulation/tasks/${encodeURIComponent(task)}`;MCSRouter.navigate(`/app/projects/${encodeURIComponent(state.activeProjectId)}/${suffix}`)}else goTab(success?'resultViewer':'tasks')});
  }

  const previousMonitor=window.renderMonitorSnapshot;
  if(typeof previousMonitor==='function')window.renderMonitorSnapshot=function(snapshot){const result=previousMonitor.apply(this,arguments);decorateMonitor(snapshot);scheduleFlowDock();return result};

  function markDirty(event){const sheet=event.target.closest?.('#engineeringSheetV040');if(sheet?.querySelector('.parameter-table-v040'))sheet.dataset.unsavedV059='1'}
  document.addEventListener('input',markDirty,true);document.addEventListener('change',markDirty,true);
  document.addEventListener('click',event=>{
    const close=event.target.closest?.('#closeEngineeringSheetV040,.engineering-sheet-backdrop-v040,#cancelParameterCatalogV040'),sheet=close?.closest?.('#engineeringSheetV040')||q('#engineeringSheetV040');
    if(!close||sheet?.dataset.unsavedV059!=='1'||!sheet.querySelector('.parameter-table-v040'))return;
    event.preventDefault();event.stopImmediatePropagation();
    const confirm=window.StudioDialog?.confirm?StudioDialog.confirm({title:'放弃尚未保存的参数修改？',message:'关闭后，本次参数修改不会进入新的设计版本。',confirmText:'放弃修改',danger:true}):Promise.resolve(window.confirm('关闭后将丢失尚未保存的参数修改，确认继续？'));
    confirm.then(approved=>{if(approved)sheet.remove()});
  },true);
  window.addEventListener('beforeunload',event=>{if(q('#engineeringSheetV040[data-unsaved-v059="1"] .parameter-table-v040'))event.preventDefault()});

  function announceRoute(){
    let live=q('#routeStatusV059');if(!live){live=document.createElement('div');live.id='routeStatusV059';live.className='sr-only-v059';live.setAttribute('aria-live','polite');document.body.appendChild(live)}
    const section=q('.tab.active'),heading=q('h2',section);if(!heading)return;live.textContent=`已进入：${heading.textContent.trim()}`;heading.tabIndex=-1;heading.focus({preventScroll:true});
  }
  window.addEventListener('mcs:route-ready',()=>{scheduleFlowDock();queueMicrotask(announceRoute)});
  ['mcs:guidance-updated','mcs:workspace-rendered','mcs:analysis-rendered'].forEach(name=>window.addEventListener(name,scheduleFlowDock));
  document.body.classList.add('studio-v059');scheduleFlowDock();
  window.MCSV059={renderFlowDock,decorateMonitor};
})();
