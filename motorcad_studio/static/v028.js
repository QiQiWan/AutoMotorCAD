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
      {label:'Design 快照',detail:design?'已绑定不可变 Revision':'选择 Design Revision',state:design?'done':'current'},
      {label:'快速提交检查',detail:fast?'Studio + 确定性约束通过':'自动检查参数、工况与模型关系',state:fast?'done':design?'current':'future'},
      {label:'运行环境',detail:runtime===true?'PyMotorCAD / 有效EXE静态就绪':runtime===false?'运行环境存在阻断':'正在读取静态就绪状态',state:runtime===true?'done':runtime===false?'blocked':'current'},
      {label:'Task + 资源租约',detail:'幂等创建 + Worker / 许可证 / 内存原子调度',state:fast&&runtime===true?'current':'future'},
      {label:'Motor-CAD 原生校验',detail:'同一 Worker / Session 参数回读、Geometry、Winding',state:'future'},
      {label:'求解与结果',detail:'PASS 后直接 FEA → 结果 → Evidence',state:'future'},
    ];
    box.innerHTML=`<div class="execution-flow-title-v028"><div><span class="eyebrow">本次计算将如何执行</span><b>${fast?'可以提交':'尚未满足提交条件'}</b></div><small>日常流程不再要求先启动一个独立 Motor-CAD 实例。提交后原生校验与正式求解连续完成。</small></div><div class="execution-flow-track-v028">${rows.map((row,i)=>`<div class="execution-flow-step-v028 ${row.state}"><span>${row.state==='done'?'✓':i+1}</span><div><b>${escHtml(row.label)}</b><small>${escHtml(row.detail)}</small></div></div>`).join('')}</div>${runtime===false?`<div class="execution-flow-advisory-v028"><b>运行环境阻断：</b> ${escHtml((s.runtimeSubmissionChecksV028||[]).find(x=>String(x.status).toUpperCase()==='FAIL')?.message||'请检查PyMotorCAD与Motor-CAD.exe路径。')}</div>`:''}${native==='FAIL'?'<div class="execution-flow-advisory-v028">独立 Motor-CAD 预检发现问题。该结果作为附加诊断显示，不会冒充正式 Task 的同会话 Validation Evidence。</div>':''}`;
  }

  window.renderExecutionFlowV028=renderExecutionFlowV028;window.loadRuntimeSubmissionReadinessV028=loadRuntimeSubmissionReadinessV028;
  document.addEventListener('input',e=>{if(e.target.closest('#taskForm'))queueMicrotask(renderExecutionFlowV028)},true);
  document.addEventListener('change',e=>{if(e.target.closest('#taskForm'))queueMicrotask(renderExecutionFlowV028)},true);
  document.addEventListener('mcs:model-runtime-check',()=>queueMicrotask(renderExecutionFlowV028));
  document.addEventListener('click',e=>{if(e.target.closest('[data-task-wizard-jump],[data-task-next],[data-task-prev],#runFullModelGateV020,#validateTask'))setTimeout(renderExecutionFlowV028,0)},true);
  renderExecutionFlowV028();loadRuntimeSubmissionReadinessV028();
})();
