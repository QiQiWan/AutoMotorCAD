/* MotorCAD Studio V0.41.0 — readability, model semantics and pre-solve repair. */
(() => {
  const q=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=v=>typeof window.esc==='function'?window.esc(v):String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const criticalIds=new Set(['slot_count','pole_count','slot_opening','tooth_width','slot_depth','stator_inner_diameter','stator_outer_diameter','turns_per_coil','parallel_paths','slot_fill_factor']);
  let repairQueued=false;

  function repairTaskModelPanel(){
    const context=state.taskWizardPanelsV019?.[0];if(!context)return;
    context.classList.add('task-model-panel-v041');
    const h=q('.section-head h2',context),p=q('.section-head p',context);
    if(h&&h.textContent!=='本次计算模型')h.textContent='本次计算模型';
    const purpose='选择已保存的 Design Revision，作为本次计算不可变的几何、绕组与材料基线。';
    if(p&&p.textContent!==purpose)p.textContent=purpose;
    const grid=q('.form-grid',context);if(grid&&!q('#taskModelMeaningV041',context)){
      const help=document.createElement('div');help.id='taskModelMeaningV041';help.className='task-model-meaning-v041 wide';
      help.innerHTML='<span>模型基线</span><div><b>这里决定“算哪台电机”</b><small>长期结构修改请回到“设计电机”创建新版本；本页临时覆盖只用于本次试算。</small></div>';
      grid.prepend(help);
    }
    const advanced=q('#simulationAdvancedV030 .simulation-advanced-grid-v030');
    const solver=q('.profile-binding-v021:not(.output)');
    if(advanced&&solver&&solver.parentElement!==advanced){solver.classList.add('solver-profile-advanced-v041');advanced.appendChild(solver)}
  }

  function compactRunTrace(){
    const old=q('#domainCompositionV021');if(!old||old.tagName==='DETAILS')return;
    const details=document.createElement('details');details.id=old.id;details.className=`${old.className} run-trace-v041`;
    const summary=document.createElement('summary');summary.innerHTML='<span><b>运行配置追溯</b><small>提交时冻结模型、工况、求解配置和输出配置</small></span><em>展开</em>';
    const body=document.createElement('div');body.className='run-trace-body-v041';while(old.firstChild)body.appendChild(old.firstChild);
    details.append(summary,body);old.replaceWith(details);
  }

  function refreshDomainTrace(){
    const select=q('#taskDesignRevisionSelect');
    if(select?.value&&state.taskDesignRevisionId!==select.value&&typeof window.applyTaskDesignRevision==='function')window.applyTaskDesignRevision(select.value,{silent:true});
    compactRunTrace();
  }

  async function requireNativeBeforeTaskSubmit(event){
    const form=event.target;if(form?.id!=='taskForm'||!criticalTaskChange()||nativeTaskEvidenceCurrent())return;
    event.preventDefault();event.stopImmediatePropagation();
    const message=q('#formMessage');if(message)message.textContent='关键几何/绕组参数已改变，正在先执行 Motor-CAD 模型检查…';
    const passed=await window.MCSModelGate?.runNativeCheck?.();
    if(passed&&nativeTaskEvidenceCurrent()){if(message)message.textContent='Motor-CAD 模型检查通过，正在提交计算…';form.requestSubmit()}
    else if(message)message.textContent='Motor-CAD 模型检查未通过，已停止提交。请根据几何/绕组诊断调整模型。';
  }

  async function createAnalysisDefinition(recipeId){
    if(window.MCSV046?.openRecipeEditor)return window.MCSV046.openRecipeEditor(recipeId);
    const catalog=window.MCSV040?.state?.catalog,recipe=(catalog?.recipes||[]).find(row=>row.id===recipeId),revisionId=q('#analysisDesignRevisionV040')?.value;
    if(!recipe||!revisionId)return toast('请先选择模型版本。','WARNING');
    const result=await window.StudioDialog?.sheet?.({title:`创建${recipe.label}`,width:'720px',html:`<div class="analysis-create-v041"><div class="analysis-create-intro-v041"><span>${safe(recipe.module_label||recipe.module)}</span><div><b>${safe(recipe.label)}</b><small>${safe((recipe.methods||[]).join(' → ')||'Motor-CAD 原生分析')}</small></div></div><div class="form-grid"><label class="wide">分析名称<input id="analysisNameV041" value="${safe(recipe.label)}" maxlength="120"></label><label>首个运行点转速 / rpm<input id="analysisSpeedV041" type="number" min="0" step="1" placeholder="可在计算设置中补充"></label><label>峰值电流 / A<input id="analysisCurrentV041" type="number" min="0" step="0.1" placeholder="可选"></label><label class="check-row wide"><input id="analysisNativeScreenV041" type="checkbox" checked> 保存 Motor-CAD 原生求解画面与 FEA 场证据</label></div><p class="hint">创建后会形成版本化 Analysis Definition；下一步进入“打开计算设置”补充工况矩阵、求解设置和输出。</p></div>`,actions:[{label:'取消',value:false},{label:'创建分析定义',primary:true,getValue:box=>({name:q('#analysisNameV041',box)?.value.trim(),speed:q('#analysisSpeedV041',box)?.value,current:q('#analysisCurrentV041',box)?.value,native:q('#analysisNativeScreenV041',box)?.checked})}]});
    if(!result)return;if(!result.name)return toast('请输入分析名称。','WARNING');
    const loadCase={};if(result.speed!=='')loadCase.shaft_speed_rpm=Number(result.speed);if(result.current!=='')loadCase.peak_current_a=Number(result.current);
    try{await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/analysis-definitions`,{method:'POST',body:JSON.stringify({design_revision_id:revisionId,name:result.name,module:recipe.module,recipe_id:recipe.id,load_cases:[loadCase],solver_settings:{native_screen_capture:{enabled:Boolean(result.native),screen:'E-Magnetics;FEA'}},requested_outputs:[]})});await window.MCSV040?.mountAnalysisWorkbench?.();toast('分析定义已创建，可继续打开计算设置。','SUCCESS')}
    catch(error){toast(error.message,'ERROR',8000)}
  }

  function interceptAnalysisPrompt(event){const button=event.target.closest?.('[data-create-analysis-v040]');if(!button)return;event.preventDefault();event.stopImmediatePropagation();createAnalysisDefinition(button.dataset.createAnalysisV040)}

  function repair(){repairQueued=false;repairTaskModelPanel();refreshDomainTrace();document.body.classList.add('studio-v041')}
  function queueRepair(){if(repairQueued)return;repairQueued=true;(window.requestAnimationFrame||window.setTimeout)(repair)}

  window.addEventListener('mcs:route-ready',queueRepair);window.addEventListener('mcs:route-start',queueRepair);['mcs:workspace-rendered','mcs:analysis-rendered','mcs:guidance-updated'].forEach(name=>window.addEventListener(name,queueRepair));
  document.addEventListener('change',event=>{if(event.target.closest?.('#taskForm'))queueRepair()},true);
  document.addEventListener('click',interceptAnalysisPrompt,true);document.addEventListener('submit',requireNativeBeforeTaskSubmit,true);
  window.MCSV041={repair,criticalTaskChange,createAnalysisDefinition};setTimeout(repair,60);
})();
