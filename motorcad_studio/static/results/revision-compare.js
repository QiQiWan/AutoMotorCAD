/* MotorCAD Studio V0.69 — Design Revision horizontal comparison. */
(() => {
  const q=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=v=>typeof esc==='function'?esc(v??''):String(v??'');
  const fmt=(v,d=3)=>Number.isFinite(Number(v))?Number(v).toLocaleString(undefined,{maximumFractionDigits:d}):safe(v??'—');
  const controller={host:null,project:null,route:null,ctx:null,designId:null,selected:[]};
  const active=ctx=>!ctx||window.MCSPageRuntime?.isContextActive?.(ctx)!==false;
  function designOptions(){return (controller.project?.designs||[]).filter(row=>Number(row.revision_count||0)>=2)}
  function defaultDesign(){return controller.route?.designId||designOptions()[0]?.id||null}
  function selectedDesign(){return (controller.project?.designs||[]).find(row=>row.id===controller.designId)}
  function renderSetup(){
    const host=controller.host;if(!host)return;const designs=designOptions();controller.designId=controller.designId||defaultDesign();
    const design=selectedDesign();const revisions=design?.revisions||[];
    if(!controller.selected.length&&revisions.length>=2)controller.selected=revisions.slice(0,Math.min(3,revisions.length)).map(row=>row.id);
    host.innerHTML=`<section class="revision-compare-v069 panel">
      <div class="section-head"><div><span class="eyebrow">DESIGN REVISION COMPARISON</span><h2>设计版本横向比较</h2><p>参数与材料变化始终可比较；性能结果只有在分析类型、工况和求解设置一致时才计算增减。</p></div><button type="button" data-revision-run-v069 class="primary" ${controller.selected.length<2?'disabled':''}>比较选中版本</button></div>
      <div class="revision-compare-controls-v069">
        <label>电机设计<select data-revision-design-v069>${designs.map(row=>`<option value="${safe(row.id)}" ${row.id===controller.designId?'selected':''}>${safe(row.name)} · ${row.revision_count} revisions</option>`).join('')}</select></label>
        <div class="revision-pills-v069">${revisions.map(row=>`<label class="${controller.selected.includes(row.id)?'selected':''}"><input type="checkbox" data-revision-choice-v069 value="${safe(row.id)}" ${controller.selected.includes(row.id)?'checked':''}><span>Rev.${safe(row.revision)}</span><small>${safe((row.content_hash||'').slice(0,8))}</small></label>`).join('')}</div>
      </div>
      <div data-revision-result-v069 class="revision-compare-result-v069"><div class="help-empty"><b>选择 2–6 个 Revision</b><span>第一个选中的版本作为基准，性能比较仅在证据可比时启用。</span></div></div>
    </section>`;
    q('[data-revision-design-v069]',host)?.addEventListener('change',event=>{controller.designId=event.target.value;controller.selected=[];renderSetup()});
    qa('[data-revision-choice-v069]',host).forEach(input=>input.addEventListener('change',()=>{
      const checked=qa('[data-revision-choice-v069]:checked',host).map(el=>el.value);
      if(checked.length>6){input.checked=false;return toast('一次最多比较 6 个 Design Revision','WARNING')}
      controller.selected=qa('[data-revision-choice-v069]:checked',host).map(el=>el.value);
      qa('.revision-pills-v069 label',host).forEach(label=>label.classList.toggle('selected',label.querySelector('input')?.checked));
      const button=q('[data-revision-run-v069]',host);if(button)button.disabled=controller.selected.length<2;
    }));
    q('[data-revision-run-v069]',host)?.addEventListener('click',()=>{
      if(controller.selected.length<2)return;
      const suffix=`compare/${encodeURIComponent(controller.designId)}/revisions/${encodeURIComponent(controller.selected.join(','))}`;
      const target=window.MCSResultsWorkbenchV069?.projectPath?.(suffix);
      if(target&&location.pathname!==target)return window.MCSResultsWorkbenchV069?.navigate?.(target);
      return runCompare();
    });
    if(controller.route?.autoCompare&&controller.selected.length>=2)runCompare();
  }
  function headerCells(revisions){return revisions.map((row,index)=>`<th><span>${index===0?'基准 · ':''}Rev.${safe(row.revision)}</span><small>${safe((row.content_hash||'').slice(0,10))}</small></th>`).join('')}
  function valueCell(cell,index,unit=''){const rel=cell?.relative_percent;return `<td><b>${fmt(cell?.value)} ${safe(unit)}</b>${index&&Number.isFinite(Number(rel))?`<small class="${Number(rel)>=0?'delta-up-v069':'delta-down-v069'}">${Number(rel)>=0?'+':''}${fmt(rel,2)}%</small>`:''}</td>`}
  function renderResult(payload){
    const box=q('[data-revision-result-v069]',controller.host);if(!box)return;const revisions=payload.revisions||[];
    const params=payload.changed_parameters||[],materials=payload.changed_materials||[],results=payload.result_rows||[];
    const evidence=new Map((payload.result_evidence||[]).map(row=>[row.revision_id,row]));
    box.innerHTML=`<div class="revision-comparison-summary-v069">
      <div><span>参数变化</span><b>${params.length}</b></div><div><span>材料变化</span><b>${materials.length}</b></div><div><span>性能证据</span><b>${payload.results_comparable?'可直接比较':'仅展示'}</b></div>
    </div>
    <div class="comparison-note-v069 ${payload.results_comparable?'ok':'warn'}">${safe(payload.comparability_note)}</div>
    <section><h3>设计参数变化</h3><div class="comparison-table-scroll-v069"><table><thead><tr><th>参数</th>${headerCells(revisions)}</tr></thead><tbody>${params.map(row=>`<tr><td><b>${safe(row.label)}</b><small>${safe(row.category||row.id)}</small></td>${(row.values||[]).map((cell,i)=>valueCell(cell,i,row.unit)).join('')}</tr>`).join('')||'<tr><td colspan="99">所选版本的结构化参数没有差异。</td></tr>'}</tbody></table></div></section>
    <section><h3>材料变化</h3><div class="comparison-table-scroll-v069"><table><thead><tr><th>部件</th>${headerCells(revisions)}</tr></thead><tbody>${materials.map(row=>`<tr><td><b>${safe(row.component)}</b></td>${(row.values||[]).map(cell=>`<td>${safe(cell.value||'—')}</td>`).join('')}</tr>`).join('')||'<tr><td colspan="99">材料绑定没有差异。</td></tr>'}</tbody></table></div></section>
    <section><div class="section-head"><div><h3>最近可用结果证据</h3><p>每个 Revision 只取最近一次 COMPLETED/PARTIALLY_COMPLETED 任务中的首个 VALID/WARNING Case，避免自动拼接不同工况。</p></div></div><div class="comparison-table-scroll-v069"><table><thead><tr><th>证据</th>${headerCells(revisions)}</tr></thead><tbody>
      <tr><td>任务</td>${revisions.map(row=>`<td>${safe(evidence.get(row.id)?.task?.name||'—')}<small>${safe(evidence.get(row.id)?.task?.id||'')}</small></td>`).join('')}</tr>
      <tr><td>Case</td>${revisions.map(row=>`<td>${safe(evidence.get(row.id)?.case?.id||'—')}<small>${safe(evidence.get(row.id)?.case?.quality_status||'')}</small></td>`).join('')}</tr>
    </tbody></table></div></section>
    ${payload.results_comparable?`<section><h3>同条件性能变化</h3><div class="comparison-table-scroll-v069"><table><thead><tr><th>结果</th>${headerCells(revisions)}</tr></thead><tbody>${results.map(row=>`<tr><td><b>${safe(row.label)}</b><small>${safe(row.id)}</small></td>${(row.values||[]).map((cell,i)=>valueCell(cell,i,row.unit)).join('')}</tr>`).join('')||'<tr><td colspan="99">没有共同的数值标量结果。</td></tr>'}</tbody></table></div></section>`:''}
    <div class="revision-compare-actions-v069">${revisions.map(row=>`<button type="button" data-open-revision-v069="${safe(row.id)}">打开 Rev.${safe(row.revision)}</button>`).join('')}</div>`;
    qa('[data-open-revision-v069]',box).forEach(button=>button.addEventListener('click',()=>window.MCSResultsWorkbenchV069?.navigate?.(`/app/projects/${encodeURIComponent(state.activeProjectId)}/designs/${encodeURIComponent(payload.design.id)}/revisions/${encodeURIComponent(button.dataset.openRevisionV069)}/geometry/radial`)));
  }
  async function runCompare(){
    if(controller.selected.length<2)return;const box=q('[data-revision-result-v069]',controller.host);box.innerHTML='<div class="viewer-loading-v058"><span class="spinner-dot"></span><b>正在比较 Design Revision…</b></div>';
    try{const payload=await api(`/api/designs/${encodeURIComponent(controller.designId)}/revision-compare?revision_ids=${encodeURIComponent(controller.selected.join(','))}`,controller.ctx?.signal?{signal:controller.ctx.signal}:{});if(!active(controller.ctx))return;renderResult(payload)}catch(error){if(window.MCSPageRuntime?.isAbortError?.(error))return;box.innerHTML=`<div class="help-empty"><b>版本比较失败</b><span>${safe(error.message||error)}</span></div>`}
  }
  function mount(host,project,route,ctx){controller.host=host;controller.project=project;controller.route=route||{};controller.ctx=ctx;controller.designId=route?.designId||null;controller.selected=route?.revisionIds||[];renderSetup()}
  window.MCSRevisionCompareV069={mount,runCompare,state:controller};
})();
