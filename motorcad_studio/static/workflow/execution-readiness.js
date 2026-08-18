/* V0.70 stable module; migrated from historical v028.js. */
/* V0.28 model hydration and end-to-end execution flow clarity. */
(() => {
  const $q = (s, root=document) => root.querySelector(s);
  const escHtml = value => typeof window.esc === 'function' ? window.esc(value) : String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function ensureFlow(){
    const panel=$q('#taskForm .submit-panel'); if(!panel) return null;
    let box=$q('#executionFlowV028'); if(box) return box;
    box=document.createElement('div'); box.id='executionFlowV028'; box.className='execution-flow-v028';
    const preview=$q('#taskPreview');
    if(preview) preview.insertAdjacentElement('afterend',box); else panel.prepend(box);
    return box;
  }

  let runtimeReadinessLoading=null;

  async function loadRuntimeSubmissionReadinessV028(){
    if(runtimeReadinessLoading)return runtimeReadinessLoading;
    runtimeReadinessLoading=(async()=>{try{const r=await api('/api/runtime/submission-readiness');state.runtimeSubmissionReadyV028=Boolean(r.ok);state.runtimeSubmissionChecksV028=r.checks||[];}catch(e){state.runtimeSubmissionReadyV028=false;state.runtimeSubmissionChecksV028=[{status:'FAIL',message:e.message}]}finally{runtimeReadinessLoading=null;window.MCSModelGate?.render?.();renderExecutionFlowV028()}})();
    return runtimeReadinessLoading;
  }

  function renderExecutionFlowV028(){
    const box=ensureFlow(); if(!box) return;
    const s=typeof state!=='undefined'?state:{};
    const design=Boolean(s.taskDesignRevisionId);
    const gate=s.modelGateV020||{};
    const currentFingerprint=window.MCSModelGate?.fingerprint?.()||'';
    const fast=Boolean(design&&gate.validationValid===true&&gate.localStatus!=='BLOCKING'&&gate.fingerprint&&gate.fingerprint===currentFingerprint);
    const native=gate.runtimeStatus||'UNCHECKED';
    const runtime=s.runtimeSubmissionReadyV028;
    const rows=[
      {label:'当前电机',detail:design?'设计版本已选定':'请选择电机设计版本',state:design?'done':'current'},
      {label:'参数预检查',detail:fast?'几何、绕组与工况检查通过':'检查尺寸关系、绕组和物理边界',state:fast?'done':design?'current':'future'},
      {label:'计算环境',detail:runtime===true?'Motor-CAD 可以启动':runtime===false?'计算环境存在问题':'正在检查 Motor-CAD',state:runtime===true?'done':runtime===false?'blocked':'current'},
      {label:'进入计算',detail:'自动排队并分配可用计算资源',state:fast&&runtime===true?'current':'future'},
      {label:'模型检查',detail:'Motor-CAD 检查几何、绕组与材料',state:'future'},
      {label:'求解与结果验证',detail:'自动提取指标、曲线和有限元场',state:'future'},
    ];
    box.innerHTML=`<div class="execution-flow-title-v028"><div><span class="eyebrow">开始计算前</span><b>${fast?'可以开始计算':'还有问题需要处理'}</b></div><small>系统会按顺序完成参数预检查、Motor-CAD 模型检查、正式求解和结果提取。</small></div><div class="execution-flow-track-v028">${rows.map((row,i)=>`<div class="execution-flow-step-v028 ${row.state}"><span>${row.state==='done'?'✓':i+1}</span><div><b>${escHtml(row.label)}</b><small>${escHtml(row.detail)}</small></div></div>`).join('')}</div>${runtime===false?`<div class="execution-flow-advisory-v028"><b>计算环境尚未就绪：</b> ${escHtml((s.runtimeSubmissionChecksV028||[]).find(x=>String(x.status).toUpperCase()==='FAIL')?.message||'请检查 Motor-CAD 安装路径。')}</div>`:''}${native==='FAIL'?'<div class="execution-flow-advisory-v028">Motor-CAD 模型检查发现问题，请按提示修改几何、绕组或材料后重试。</div>':''}`;
  }

  window.renderExecutionFlowV028=renderExecutionFlowV028;window.loadRuntimeSubmissionReadinessV028=loadRuntimeSubmissionReadinessV028;
  document.addEventListener('input',e=>{if(e.target.closest('#taskForm'))queueMicrotask(renderExecutionFlowV028)},true);
  document.addEventListener('change',e=>{if(e.target.closest('#taskForm'))queueMicrotask(renderExecutionFlowV028)},true);
  document.addEventListener('mcs:model-runtime-check',()=>queueMicrotask(renderExecutionFlowV028));
  document.addEventListener('click',e=>{if(e.target.closest('[data-task-wizard-jump],[data-task-next],[data-task-prev],#runFullModelGateV020,#validateTask'))setTimeout(renderExecutionFlowV028,0)},true);
  renderExecutionFlowV028();loadRuntimeSubmissionReadinessV028();
})();
