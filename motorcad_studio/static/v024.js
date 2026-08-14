/* V0.24 Motor Model Workbench: continuous model editing, parameter dependency and evidence UX. */
(() => {
  const $q = (s, root=document) => root.querySelector(s);
  const $$q = (s, root=document) => [...root.querySelectorAll(s)];
  const escHtml = (value) => typeof window.esc === 'function'
    ? window.esc(value)
    : String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  const wb = {
    revisionId: null,
    data: null,
    values: {},
    changed: new Set(),
    selected: null,
    group: 'topology',
    view: 'radial',
    precheck: null,
    nativeCheck: null,
    precheckTimer: 0,
    precheckAbort: null,
    saveBusy: false,
    nativeBusy: false,
    windingText: null,
  };

  const categoryIcon = {topology:'◎', geometry:'◫', magnet:'N/S', winding:'∿'};

  function recordFor(id) {
    return (wb.data?.parameters || []).find(row => row.id === id) || null;
  }

  function valueFor(id) {
    return wb.values[id];
  }

  function changedIds() {
    return [...wb.changed];
  }

  function formatValue(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'number' && Number.isFinite(value)) return Number(value.toPrecision(8)).toString();
    return String(value);
  }

  function sameValue(a,b) {
    const na=Number(a), nb=Number(b);
    if (a !== '' && b !== '' && Number.isFinite(na) && Number.isFinite(nb)) return Math.abs(na-nb) <= Math.max(1e-9,Math.abs(nb)*1e-9);
    return String(a ?? '') === String(b ?? '');
  }

  function refreshChanged(id) {
    const row = recordFor(id); if (!row) return;
    if (sameValue(wb.values[id], row.value)) wb.changed.delete(id); else wb.changed.add(id);
  }

  function parameterLabel(id) {
    const row=recordFor(id); return row?.label || id;
  }

  function renderShell() {
    const d=wb.data, rev=d.revision;
    const canvas=$q('#workspaceCanvas'), inspector=$q('#workspaceInspector');
    if (!canvas) return;
    canvas.innerHTML = `<div class="workspace-object-header model-workbench-header-v024"><div><span class="eyebrow">Motor Model Workbench · 设计模型</span><h2>${escHtml(rev.design_name)} · Rev.${escHtml(rev.revision)}</h2><p>一个持续存在的电机模型：左侧定位参数，中央观察几何/绕组/原生证据，右侧处理约束与修复。保存后生成新的不可变 Revision。</p></div><div class="actions"><button id="workbenchCancelV024" type="button">退出编辑</button><button id="workbenchSaveV024" class="primary" type="button">保存为新 Revision</button></div></div>
    <div class="model-workbench-v024">
      <aside class="workbench-tree-v024">
        <div class="workbench-search-v024"><label for="workbenchSearchV024">参数 / Region</label><input id="workbenchSearchV024" placeholder="搜索名称、ID、Motor-CAD变量"></div>
        <div id="workbenchGroupsV024" class="workbench-groups-v024"></div>
        <div class="workbench-region-box-v024"><span class="eyebrow">模型区域</span><div id="workbenchRegionsV024"></div></div>
      </aside>
      <main class="workbench-main-v024">
        <section class="workbench-visual-v024">
          <div class="workbench-view-tabs-v024" role="tablist" aria-label="模型视图">
            <button type="button" data-workbench-view="radial" class="active">径向截面</button>
            <button type="button" data-workbench-view="axial">轴向截面</button>
            <button type="button" data-workbench-view="winding">绕组排布</button>
            <button type="button" data-workbench-view="slot">槽内定义</button>
            <button type="button" data-workbench-view="materials">材料</button>
            <button type="button" data-workbench-view="native">Motor-CAD 证据</button>
            <button type="button" data-workbench-view="compare">版本对比</button>
          </div>
          <div id="workbenchVisualStageV024" class="workbench-visual-stage-v024"></div>
        </section>
        <section class="workbench-parameter-editor-v024">
          <div class="workbench-editor-head-v024"><div><span class="eyebrow">参数编辑</span><h3 id="workbenchGroupTitleV024"></h3></div><div class="actions"><button id="restoreGroupPreviousV024" type="button">本组恢复上一可行值</button><button id="restoreGroupTemplateV024" type="button">本组恢复模板基线</button></div></div>
          <div id="workbenchParameterRowsV024" class="workbench-parameter-rows-v024"></div>
        </section>
      </main>
      <aside class="workbench-diagnostics-v024">
        <section id="workbenchStatusV024" class="workbench-diagnostic-card-v024"></section>
        <section id="workbenchSelectedV024" class="workbench-diagnostic-card-v024"></section>
        <section id="workbenchEvidenceV024" class="workbench-diagnostic-card-v024"></section>
      </aside>
    </div>`;
    if (inspector) inspector.innerHTML = `<div class="inspector-block"><span class="eyebrow">版本与证据</span><h3>${escHtml(rev.design_name)}</h3><div class="property-grid"><span>当前基线</span><b>Rev.${escHtml(rev.revision)}</b><span>已修改</span><b id="workbenchChangeCountV024">0 项</b><span>模板</span><b>${escHtml(rev.template_id)}</b><span>预览参数源</span><b>Rev.${escHtml(rev.revision)} 有效快照</b><span>快照签名</span><b><code>${escHtml(String(d.preview_signature||'').slice(0,10)||'—')}</code></b><span>当前静态检查</span><b id="workbenchInspectorStatusV024">—</b></div><div class="inspector-note">首次进入页面即使用 Design Revision 与模板默认值合并后的有效参数快照绘制快速几何；Motor-CAD 原生检查与历史 Case 证据独立显示。</div></div>`;

    renderGroups(); renderRegions(); renderParameters(); renderVisual(); renderSelected(); renderEvidence(); renderPrecheck(); bindShell();
  }

  function renderGroups(filter='') {
    const box=$q('#workbenchGroupsV024'); if(!box) return;
    const needle=String(filter||'').trim().toLowerCase();
    box.innerHTML=(wb.data.groups||[]).map(group=>{
      const rows=(wb.data.parameters||[]).filter(p=>p.category===group.id);
      const matches=!needle || rows.some(p=>`${p.label} ${p.id} ${(p.motorcad_candidates||[]).join(' ')}`.toLowerCase().includes(needle));
      if(!matches)return'';
      const changed=rows.filter(p=>wb.changed.has(p.id)).length;
      return `<button type="button" class="workbench-group-btn-v024 ${wb.group===group.id?'active':''}" data-workbench-group="${escHtml(group.id)}"><span class="group-icon-v024">${escHtml(categoryIcon[group.id]||'•')}</span><span><b>${escHtml(group.label)}</b><small>${rows.length} 个参数${changed?` · ${changed} 项已改`:''}</small></span></button>`;
    }).join('');
  }

  function renderRegions() {
    const box=$q('#workbenchRegionsV024'); if(!box)return;
    box.innerHTML=Object.entries(wb.data.regions||{}).map(([id,row])=>`<button type="button" data-workbench-region="${escHtml(id)}"><span>${escHtml(row.label||id)}</span><small>${(row.parameter_ids||[]).filter(pid=>recordFor(pid)).length} 参数</small></button>`).join('');
  }

  function renderParameters() {
    const box=$q('#workbenchParameterRowsV024'); if(!box)return;
    const group=(wb.data.groups||[]).find(g=>g.id===wb.group);
    const rows=(wb.data.parameters||[]).filter(row=>row.category===wb.group);
    const title=$q('#workbenchGroupTitleV024'); if(title) title.textContent=group?.label||wb.group;
    box.innerHTML=rows.map(row=>{
      const changed=wb.changed.has(row.id), selected=wb.selected===row.id;
      const candidate=(row.motorcad_candidates||[])[0]||'未映射';
      return `<article class="workbench-param-row-v024 ${changed?'changed':''} ${selected?'selected':''}" data-workbench-param-row="${escHtml(row.id)}"><button type="button" class="workbench-param-focus-v024" data-workbench-select="${escHtml(row.id)}"><span><b>${escHtml(row.label)}</b><small>${escHtml(row.id)}</small></span><em>${row.explicit?'设计意图':'继承基线'}</em></button><div class="workbench-param-control-v024"><input data-workbench-input="${escHtml(row.id)}" type="number" step="${row.type==='integer'?'1':'any'}" ${row.minimum!==null&&row.minimum!==undefined?`min="${escHtml(row.minimum)}"`:''} ${row.maximum!==null&&row.maximum!==undefined?`max="${escHtml(row.maximum)}"`:''} value="${escHtml(formatValue(valueFor(row.id)))}"><span>${escHtml(row.unit||'')}</span></div><div class="workbench-param-lineage-v024"><span>模板 ${escHtml(formatValue(row.template_default))}</span><span>上一可行 ${escHtml(formatValue(row.previous_feasible_value))}</span><code title="Motor-CAD Automation Name">${escHtml(candidate)}</code></div><div class="workbench-param-actions-v024"><button type="button" data-workbench-restore="previous" data-param-id="${escHtml(row.id)}" ${row.previous_feasible_value===undefined?'disabled':''}>上一可行</button><button type="button" data-workbench-restore="template" data-param-id="${escHtml(row.id)}" ${row.template_default===undefined?'disabled':''}>模板</button></div></article>`;
    }).join('') || '<div class="workspace-empty compact">当前分组没有可编辑设计参数。</div>';
    updateChangeCount();
  }

  function updateChangeCount(){
    const n=wb.changed.size;
    const count=$q('#workbenchChangeCountV024'); if(count)count.textContent=`${n} 项`;
    const save=$q('#workbenchSaveV024'); if(save)save.disabled=wb.saveBusy||n===0||Boolean(wb.precheck?.issues?.some(x=>x.severity==='BLOCKING'));
    renderGroups($q('#workbenchSearchV024')?.value||'');
  }

  function geometryHtml(){
    const template=state.templates?.find(t=>t.id===wb.data.revision.template_id)||state.selectedTemplate;
    const schematic=template?motorSchematic(template,true,wb.values):'<div class="workspace-empty compact">模板示意不可用。</div>';
    const derived=wb.precheck?.geometry?.derived||{};
    const dims=['pole_count','slot_count','stator_outer_diameter','stator_inner_diameter','air_gap','tooth_width','slot_depth','slot_opening','magnet_thickness'];
    return `<div class="workbench-geometry-view-v024"><div id="workbenchSchematicV024" class="workbench-schematic-v024">${schematic}</div><div class="workbench-dim-strip-v024">${dims.filter(id=>valueFor(id)!==undefined).map(id=>{const row=recordFor(id);return `<button type="button" data-workbench-select="${escHtml(id)}"><b>${escHtml(row?.label||id)}</b><span>${escHtml(formatValue(valueFor(id)))} ${escHtml(row?.unit||'')}</span></button>`}).join('')}</div><div class="workbench-derived-v024"><span>估算槽距 <b>${derived.slot_pitch_mm!=null?`${Number(derived.slot_pitch_mm).toFixed(3)} mm`:'—'}</b></span><span>定子径向厚度 <b>${derived.radial_build_mm!=null?`${Number(derived.radial_build_mm).toFixed(3)} mm`:'—'}</b></span><span>说明 <b>Studio 快速关系示意；Motor-CAD 原生几何仍为最终权威</b></span></div></div>`;
  }

  function windingHtml(){
    const w=wb.precheck?.winding?.derived||{};
    const slots=Math.max(1,Math.min(96,Math.round(Number(valueFor('slot_count')||w.slot_count||12))));
    const phases=Math.max(1,Math.min(9,Math.round(Number(w.phase_count||3))));
    const paths=Math.max(1,Math.round(Number(valueFor('parallel_paths')||w.parallel_paths||1)));
    const cx=180,cy=180,r=126;
    let marks='';
    for(let i=0;i<slots;i++){
      const a=-Math.PI/2+i*2*Math.PI/slots; const x=cx+r*Math.cos(a), y=cy+r*Math.sin(a);
      const phase=i%phases;
      marks+=`<g class="winding-slot-v024 phase-${phase%6}" data-slot-index="${i+1}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${slots>48?4.2:6.2}"/><text x="${x.toFixed(1)}" y="${(y+2.7).toFixed(1)}" text-anchor="middle">${slots<=36?i+1:''}</text></g>`;
    }
    const q=w.slots_per_phase_path;
    const valid=Number.isFinite(Number(q))&&Math.abs(Number(q)-Math.round(Number(q)))<1e-9;
    const artifact=wb.data.native_evidence?.winding_pattern_artifact;
    return `<div class="workbench-winding-view-v024"><div class="winding-diagram-wrap-v024"><svg viewBox="0 0 360 360" aria-label="槽相关系示意"><circle cx="180" cy="180" r="146" class="winding-stator-v024"/><circle cx="180" cy="180" r="92" class="winding-rotor-v024"/>${marks}<text x="180" y="174" text-anchor="middle" class="winding-main-label-v024">${slots} 槽 / ${escHtml(phases)} 相</text><text x="180" y="196" text-anchor="middle" class="winding-sub-label-v024">${paths} 并联支路</text></svg><p>彩色槽位仅用于表达相槽周期与整数约束，不能替代 Motor-CAD 的真实 coil go/return slot 定义。</p></div><div class="winding-facts-v024"><div class="metric"><span>每相每支路槽数</span><b class="${valid?'ok-text-v024':'bad-text-v024'}">${q!=null?Number(q).toPrecision(5):'—'}</b></div><div class="metric"><span>整数关系</span><b>${valid?'通过':'未通过'}</b></div><div class="metric"><span>槽满率输入</span><b>${escHtml(formatValue(valueFor('slot_fill_factor')))}</b></div><div class="native-winding-evidence-v024"><span class="eyebrow">Motor-CAD 原生绕组证据</span>${artifact?`<p>最近一次 Case 已通过 <code>save_winding_pattern()</code> 保存真实绕组定义。</p><div class="actions"><button id="loadNativeWindingV024" type="button">查看原生绕组文本</button><a class="button-like-v024" href="${escHtml(artifact.download_url)}">下载原生绕组</a></div><pre id="nativeWindingTextV024" class="hidden"></pre>`:'<p>当前 Revision 尚无原生绕组文件。执行真实模型检查/计算后可生成。</p>'}</div></div></div>`;
  }

  function nativeHtml(){
    const e=wb.data.native_evidence;
    if(!e)return `<div class="workbench-native-empty-v024"><b>尚无 Motor-CAD 原生 Case 证据</b><p>可以在右侧执行“Motor-CAD 原生检查”；完成真实 Task 后，这里还会关联 pre-solve MOT、原生绕组与 FEA 证据。</p></div>`;
    const mv=e.model_validation||{}, winding=mv.winding_validation||{};
    const geometry=mv.geometry_api_succeeded===false?'FAIL':mv.geometry_api_succeeded===true?'PASS':'—';
    const windingStatus=winding.status||'—';
    const files=(e.artifacts||[]).filter(a=>['model_validation.json','pre_solve_model.mot','winding_pattern.txt','native_fea_manifest.json','native_fea_raw.csv'].includes(a.name));
    return `<div class="workbench-native-view-v024"><div class="native-evidence-head-v024"><div><span class="eyebrow">最近一次真实 Case</span><h3>${escHtml(e.case_id)}</h3><p>${escHtml(e.task_id)} · ${escHtml(e.analysis||'')}</p></div><span class="badge ${e.execution_status==='SUCCEEDED'?'ok':e.execution_status==='FAILED'?'error':'warn'}">${escHtml(e.execution_status||e.task_status||'UNKNOWN')}</span></div><div class="native-evidence-grid-v024"><div><span>Geometry</span><b>${escHtml(geometry)}</b></div><div><span>Winding</span><b>${escHtml(windingStatus)}</b></div><div><span>Result Quality</span><b>${escHtml(e.quality_status||'—')}</b></div><div><span>完成时间</span><b>${escHtml(e.finished_at||'—')}</b></div></div>${e.error?`<div class="callout error"><b>Case 错误</b><br>${escHtml(String(e.error).slice(0,1200))}</div>`:''}<div class="native-artifact-list-v024">${files.map(a=>`<a href="${escHtml(a.download_url)}"><b>${escHtml(a.name)}</b><small>${Number(a.size_bytes||0).toLocaleString()} bytes</small></a>`).join('')||'<p class="hint">当前 Case 未登记模型证据文件。</p>'}</div></div>`;
  }

  function compareHtml(){
    const prev=wb.data.previous_feasible; if(!prev)return '<div class="workspace-empty compact">没有可用于比较的上一可行 Revision / 模板基线。</div>';
    const rows=(wb.data.parameters||[]).map(row=>({row,previous:prev.parameters?.[row.id],current:valueFor(row.id)})).filter(x=>x.previous!==undefined&&!sameValue(x.previous,x.current));
    const label=prev.source==='revision'?`Rev.${prev.revision}`:'模板基线';
    return `<div class="workbench-compare-v024"><div class="compare-head-v024"><div><span class="eyebrow">与上一可行模型对比</span><h3>${escHtml(label)} → 当前编辑</h3></div><span>${rows.length} 项差异</span></div>${rows.length?`<table><thead><tr><th>参数</th><th>${escHtml(label)}</th><th>当前</th><th>动作</th></tr></thead><tbody>${rows.map(({row,previous,current})=>`<tr><td><button type="button" class="link-button" data-workbench-select="${escHtml(row.id)}">${escHtml(row.label)}</button><small>${escHtml(row.id)}</small></td><td>${escHtml(formatValue(previous))} ${escHtml(row.unit||'')}</td><td><b>${escHtml(formatValue(current))} ${escHtml(row.unit||'')}</b></td><td><button type="button" data-workbench-set="${escHtml(row.id)}" data-workbench-value="${escHtml(previous)}">恢复</button></td></tr>`).join('')}</tbody></table>`:'<div class="callout success">当前编辑值与上一可行模型在可比参数上相同。</div>'}</div>`;
  }

  function renderVisual(){
    const box=$q('#workbenchVisualStageV024'); if(!box)return;
    $$q('[data-workbench-view]').forEach(b=>b.classList.toggle('active',b.dataset.workbenchView===wb.view));
    const motorCadView=window.MCSVisualV031?.renderWorkbenchView?.(wb.view,{data:wb.data,values:wb.values,precheck:wb.precheck,selected:wb.selected,editable:true});
    if(motorCadView!==undefined&&motorCadView!==null)box.innerHTML=motorCadView;
    else if(wb.view==='radial'||wb.view==='geometry')box.innerHTML=geometryHtml();
    else if(wb.view==='winding')box.innerHTML=windingHtml();
    else if(wb.view==='native')box.innerHTML=nativeHtml();
    else box.innerHTML=compareHtml();
    highlightSelectedRegion();
  }

  function selectedDependency(){return wb.selected?wb.data.dependencies?.[wb.selected]||{}:{};}

  function renderSelected(){
    const box=$q('#workbenchSelectedV024'); if(!box)return;
    const row=recordFor(wb.selected), dep=selectedDependency();
    if(!row){box.innerHTML='<span class="eyebrow">参数联动</span><h3>选择一个参数</h3><p>点击参数、几何 Region 或错误条目，这里会显示影响链和可恢复基线。</p>';return;}
    const related=(dep.related||[]).filter(id=>recordFor(id));
    box.innerHTML=`<span class="eyebrow">当前参数</span><h3>${escHtml(row.label)}</h3><p>${escHtml(row.description||dep.component||'')}</p><div class="selected-value-v024"><span>当前</span><b>${escHtml(formatValue(valueFor(row.id)))} ${escHtml(row.unit||'')}</b></div><div class="dependency-chain-v024"><b>${escHtml(dep.component||'工程影响')}</b>${(dep.affects||[]).map(x=>`<span>→ ${escHtml(x)}</span>`).join('')||'<span>暂无依赖元数据</span>'}</div><div class="property-grid"><span>Motor-CAD</span><b><code>${escHtml((row.motorcad_candidates||[]).join(' / ')||'未映射')}</code></b><span>模板基线</span><b>${escHtml(formatValue(row.template_default))}</b><span>上一可行</span><b>${escHtml(formatValue(row.previous_feasible_value))}</b></div>${related.length?`<div class="related-params-v024"><b>关联参数</b>${related.map(id=>`<button type="button" data-workbench-select="${escHtml(id)}">${escHtml(parameterLabel(id))}</button>`).join('')}</div>`:''}`;
  }

  function renderPrecheck(){
    const box=$q('#workbenchStatusV024'); if(!box)return;
    const p=wb.precheck||wb.data.precheck||{}; wb.precheck=p;
    const blocks=(p.issues||[]).filter(x=>x.severity==='BLOCKING'), warns=(p.issues||[]).filter(x=>x.severity!=='BLOCKING');
    const tone=blocks.length?'blocking':warns.length?'warning':'pass';
    box.className=`workbench-diagnostic-card-v024 workbench-status-${tone}-v024`;
    box.innerHTML=`<div class="diagnostic-title-v024"><div><span class="eyebrow">模型约束</span><h3>${blocks.length?'存在阻断':warns.length?'可继续但需关注':'静态检查通过'}</h3></div><span class="badge ${blocks.length?'error':warns.length?'warn':'ok'}">${blocks.length?`${blocks.length} 阻断`:warns.length?`${warns.length} 提示`:'PASS'}</span></div>${(p.issues||[]).length?`<div class="workbench-issue-list-v024">${(p.issues||[]).map((issue,i)=>`<button type="button" data-workbench-issue="${i}" class="${issue.severity==='BLOCKING'?'blocking':'warning'}"><b>${escHtml(issue.message||issue.code)}</b><small>${escHtml(issue.code||'')} · ${(issue.parameter_ids||[]).map(parameterLabel).join(' / ')||'模型级'}</small></button>`).join('')}</div>`:'<p>槽极、几何和绕组确定性关系未发现阻断。真实 Motor-CAD 几何与绕组检查仍需单独执行。</p>'}<div class="actions"><button id="runNativeModelCheckV024" type="button" class="${blocks.length?'':'primary'}" ${blocks.length||wb.nativeBusy?'disabled':''}>${wb.nativeBusy?'Motor-CAD 检查中…':'运行 Motor-CAD 原生检查'}</button></div>`;
    const inspector=$q('#workbenchInspectorStatusV024'); if(inspector)inspector.textContent=blocks.length?'BLOCKING':warns.length?'WARNING':'PASS';
    updateChangeCount();
  }

  function renderEvidence(){
    const box=$q('#workbenchEvidenceV024'); if(!box)return;
    const e=wb.data.native_evidence, n=wb.nativeCheck;
    const prev=wb.data.previous_feasible;
    let nativeHtmlPart='';
    if(n){const pass=n.status==='PASS';nativeHtmlPart=`<div class="native-check-result-v024 ${pass?'pass':'fail'}"><b>${pass?'✓ 当前编辑值通过 Motor-CAD 原生检查':'当前编辑值未通过 Motor-CAD 原生检查'}</b><small>${escHtml(n.work_dir||'')}</small>${!pass?nativeFailureSummary(n):''}</div>`;}
    else if(e){nativeHtmlPart=`<div class="native-check-result-v024 history"><b>历史原生证据：${escHtml(e.execution_status||e.task_status||'UNKNOWN')}</b><small>${escHtml(e.case_id)} · ${escHtml(e.finished_at||'')}</small></div>`;}
    else nativeHtmlPart='<p class="hint">当前 Revision 尚无 Motor-CAD 原生证据。</p>';
    box.innerHTML=`<span class="eyebrow">基线与原生证据</span><h3>${prev?.source==='revision'?`上一可行 Rev.${escHtml(prev.revision)}`:prev?'模板可行基线':'暂无可行基线'}</h3>${nativeHtmlPart}<div class="evidence-rule-v024"><b>证据层级</b><span>Studio 即时关系检查 → Motor-CAD 原生几何/绕组 → 真实求解 → FEA/结果质量</span></div>`;
  }

  function nativeFailureSummary(result){
    const g=result.geometry?.details||result.geometry||{}, w=result.winding?.details||result.winding||{};
    const causes=[...(w.causes||[]),...((g.geometry_diagnosis||{}).causes||[])];
    const codes=[...(w.codes||[]),...((g.geometry_diagnosis||{}).codes||[])];
    const binding=firstNativeBinding(codes);
    return `<div class="native-failure-summary-v024"><span>${escHtml(causes[0]||result.geometry?.message||result.winding?.message||'Motor-CAD 返回模型不可行')}</span>${binding.length?`<div>${binding.map(id=>`<button type="button" data-workbench-select="${escHtml(id)}">定位 ${escHtml(parameterLabel(id))}</button>`).join('')}</div>`:''}</div>`;
  }

  function firstNativeBinding(codes){
    for(const code of codes||[]){const ids=wb.data.issue_bindings?.[code]?.parameter_ids||[];if(ids.length)return ids.filter(id=>recordFor(id));}
    return [];
  }

  function highlightSelectedRegion(){
    const row=recordFor(wb.selected); const regions=row?.dependency?.region_ids||[];
    const stage=$q('#workbenchVisualStageV024'); if(!stage)return;
    $$q('[data-schematic-part]',stage).forEach(el=>{
      const tags=String(el.dataset.schematicPart||'').split(/\s+/);
      el.classList.toggle('workbench-part-selected-v024',regions.some(r=>tags.includes(r)));
    });
  }

  function selectParameter(id,{switchGroup=true}={}){
    const row=recordFor(id); if(!row)return;
    wb.selected=id;
    if(switchGroup&&row.category!==wb.group){wb.group=row.category;renderParameters();}
    else $$q('[data-workbench-param-row]').forEach(el=>el.classList.toggle('selected',el.dataset.workbenchParamRow===id));
    renderSelected(); highlightSelectedRegion();
    const input=$q(`[data-workbench-input="${CSS.escape(id)}"]`); input?.focus({preventScroll:true}); input?.closest('[data-workbench-param-row]')?.scrollIntoView({block:'nearest',behavior:'smooth'});
  }

  function selectRegion(regionId){
    const ids=(wb.data.regions?.[regionId]?.parameter_ids||[]).filter(id=>recordFor(id));
    if(ids.length)selectParameter(ids[0]);
  }

  function setValue(id,value,{schedule=true}={}){
    const row=recordFor(id); if(!row)return;
    let next=value;
    if(row.type==='integer') next=Math.round(Number(value)); else if(typeof value==='string'&&value.trim()!=='')next=Number(value);
    if(!Number.isFinite(Number(next)))return;
    wb.values[id]=Number(next); refreshChanged(id);
    const input=$q(`[data-workbench-input="${CSS.escape(id)}"]`); if(input&&String(input.value)!==String(next))input.value=String(next);
    renderParameters(); renderVisual(); renderSelected(); updateChangeCount();
    if(schedule)schedulePrecheck();
  }

  function restoreGroup(source){
    const rows=(wb.data.parameters||[]).filter(row=>row.category===wb.group);
    rows.forEach(row=>{const value=source==='previous'?row.previous_feasible_value:row.template_default;if(value!==undefined)setValue(row.id,value,{schedule:false});});
    schedulePrecheck(true);
  }

  function schedulePrecheck(immediate=false){
    if(wb.precheckTimer)clearTimeout(wb.precheckTimer);
    if(immediate){runPrecheck();return;}
    wb.precheckTimer=setTimeout(runPrecheck,220);
  }

  async function runPrecheck(){
    if(!wb.revisionId)return;
    wb.precheckAbort?.abort(); const controller=new AbortController(); wb.precheckAbort=controller;
    const box=$q('#workbenchStatusV024'); if(box)box.innerHTML='<span class="badge warn">检查中</span><p>正在更新槽极、几何和绕组关系…</p>';
    try{
      const response=await fetch(`/api/design-revisions/${encodeURIComponent(wb.revisionId)}/workbench/precheck`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parameters:wb.values,changed_parameter_ids:changedIds()}),signal:controller.signal,cache:'no-store'});
      if(!response.ok){let detail='';try{detail=JSON.stringify((await response.json()).detail||'')}catch{}throw new Error(detail||`HTTP ${response.status}`)}
      wb.precheck=await response.json(); wb.nativeCheck=null; renderPrecheck(); renderVisual(); renderSelected(); renderEvidence();
    }catch(error){if(error?.name==='AbortError')return; if(box)box.innerHTML=`<span class="badge error">预检查失败</span><p>${escHtml(error.message||error)}</p>`;}
  }

  async function runNativeCheck(){
    if(wb.nativeBusy || wb.precheck?.issues?.some(x=>x.severity==='BLOCKING'))return;
    wb.nativeBusy=true; renderPrecheck();
    try{
      const payload={parameters:wb.values,explicit_parameter_ids:[...new Set([...(state.workspaceRevision?.explicit_parameter_ids||[]),...changedIds()])],materials:state.workspaceRevision?.materials||{},timeout_s:180};
      const result=await api(`/api/templates/${encodeURIComponent(wb.data.revision.template_id)}/geometry-check`,{method:'POST',body:JSON.stringify(payload)});
      wb.nativeCheck=result; renderPrecheck(); renderEvidence(); if(result.status==='PASS')toast('当前编辑值已通过 Motor-CAD 原生几何与绕组检查。','SUCCESS',6500);else toast('Motor-CAD 原生模型检查未通过；已定位到工作台约束面板。','ERROR',7500);
    }catch(error){toast(`Motor-CAD 原生检查失败：${error.message}`,'ERROR',8000);}
    finally{wb.nativeBusy=false;renderPrecheck();renderEvidence();}
  }

  async function saveRevision(){
    if(wb.saveBusy||!wb.changed.size)return;
    if(wb.precheck?.issues?.some(x=>x.severity==='BLOCKING'))return toast('当前设计仍有模型阻断，不能保存为新的 Revision。','ERROR',7000);
    const notes=await revisionNotesSheet(); if(notes===null)return;
    wb.saveBusy=true; updateChangeCount(); const button=$q('#workbenchSaveV024'); if(button)button.textContent='正在创建 Revision…';
    try{
      const rev=state.workspaceRevision, design=state.workspaceDesign;
      const explicit=[...new Set([...(rev?.explicit_parameter_ids||[]),...changedIds()])];
      const created=await api(`/api/designs/${encodeURIComponent(design.id)}/revisions`,{method:'POST',body:JSON.stringify({parameters:wb.values,materials:rev?.materials||{},explicit_parameter_ids:explicit,notes:notes||`基于 Rev.${rev?.revision} 的模型工作台修改`})});
      state.workspaceProject=await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`);
      toast(`已创建 Rev.${created.revision}`,'SUCCESS',6500); await openWorkspaceDesign(design.id); if(created.id)selectWorkspaceRevision(created.id);
    }catch(error){toast(error.message,'ERROR',8500);wb.saveBusy=false;if(button)button.textContent='保存为新 Revision';updateChangeCount();}
  }

  async function revisionNotesSheet(){
    if(!window.StudioDialog?.sheet)return `基于 Rev.${state.workspaceRevision?.revision} 的模型工作台修改`;
    const value=await StudioDialog.sheet({
      title:'保存新的 Design Revision',
      html:`<div class="step-help-sheet"><p>将当前 ${wb.changed.size} 项修改冻结为新的不可变设计版本。历史 Task 继续指向原 Revision。</p><label>Revision 说明<textarea id="workbenchRevisionNotesV024" rows="4" placeholder="例如：调整槽口和齿宽以降低槽满率风险"></textarea></label></div>`,
      actions:[
        {label:'取消',value:null},
        {label:'确认保存',primary:true,getValue:box=>box.querySelector('#workbenchRevisionNotesV024')?.value.trim()||''},
      ],
    });
    return value===false?null:value;
  }

  async function loadNativeWinding(){
    const artifact=wb.data.native_evidence?.winding_pattern_artifact; if(!artifact)return;
    const pre=$q('#nativeWindingTextV024'); if(!pre)return;
    if(wb.windingText!==null){pre.textContent=wb.windingText;pre.classList.toggle('hidden');return;}
    try{const r=await fetch(artifact.download_url,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);wb.windingText=await r.text();pre.textContent=wb.windingText.slice(0,24000);pre.classList.remove('hidden');}
    catch(error){pre.textContent=`读取失败：${error.message}`;pre.classList.remove('hidden');}
  }

  function bindShell(){
    $q('#workbenchCancelV024')?.addEventListener('click',()=>openWorkspaceDesign(state.workspaceDesign.id));
    $q('#workbenchSaveV024')?.addEventListener('click',saveRevision);
    $q('#workbenchSearchV024')?.addEventListener('input',e=>renderGroups(e.target.value));
    $q('#restoreGroupPreviousV024')?.addEventListener('click',()=>restoreGroup('previous'));
    $q('#restoreGroupTemplateV024')?.addEventListener('click',()=>restoreGroup('template'));
    const canvas=$q('#workspaceCanvas');
    canvas?.addEventListener('click',event=>{
      const group=event.target.closest('[data-workbench-group]');if(group){wb.group=group.dataset.workbenchGroup;renderGroups($q('#workbenchSearchV024')?.value||'');renderParameters();return;}
      const region=event.target.closest('[data-workbench-region]');if(region){selectRegion(region.dataset.workbenchRegion);return;}
      const select=event.target.closest('[data-workbench-select]');if(select){selectParameter(select.dataset.workbenchSelect);return;}
      const restore=event.target.closest('[data-workbench-restore]');if(restore){const row=recordFor(restore.dataset.paramId);const v=restore.dataset.workbenchRestore==='previous'?row?.previous_feasible_value:row?.template_default;if(v!==undefined)setValue(row.id,v);return;}
      const set=event.target.closest('[data-workbench-set]');if(set){setValue(set.dataset.workbenchSet,Number(set.dataset.workbenchValue));return;}
      const view=event.target.closest('[data-workbench-view]');if(view){wb.view=view.dataset.workbenchView;renderVisual();return;}
      const issue=event.target.closest('[data-workbench-issue]');if(issue){const row=wb.precheck?.issues?.[Number(issue.dataset.workbenchIssue)];const id=(row?.parameter_ids||[]).find(pid=>recordFor(pid));if(id)selectParameter(id);return;}
      if(event.target.closest('#runNativeModelCheckV024')){runNativeCheck();return;}
      if(event.target.closest('#loadNativeWindingV024')){loadNativeWinding();return;}
      const schematic=event.target.closest('[data-schematic-part]');if(schematic){const tags=String(schematic.dataset.schematicPart||'').split(/\s+/);const regionId=tags.find(tag=>wb.data.regions?.[tag]);if(regionId)selectRegion(regionId);}
    });
    canvas?.addEventListener('input',event=>{const input=event.target.closest('[data-workbench-input]');if(!input)return;const id=input.dataset.workbenchInput;const number=Number(input.value);if(!Number.isFinite(number))return;wb.values[id]=recordFor(id)?.type==='integer'?Math.round(number):number;refreshChanged(id);wb.selected=id;renderSelected();renderVisual();updateChangeCount();schedulePrecheck();});
    canvas?.addEventListener('focusin',event=>{const input=event.target.closest('[data-workbench-input]');if(input){wb.selected=input.dataset.workbenchInput;renderSelected();highlightSelectedRegion();}});
  }

  async function openRevisionEditorV024(routeCtx=null){
    const design=state.workspaceDesign, rev=state.workspaceRevision;
    if(!design||!rev)return toast('请先选择 Design Revision','WARNING');
    const canvas=$q('#workspaceCanvas'); if(canvas)canvas.innerHTML='<div class="workspace-empty"><span class="connection-pulse"></span><b>正在加载 Motor Model Workbench…</b><p>读取设计参数、依赖关系、上一可行基线和 Motor-CAD 原生证据。</p></div>';
    try{
      const data=await api(`/api/design-revisions/${encodeURIComponent(rev.id)}/workbench`,routeCtx?.signal?{signal:routeCtx.signal}:{});if(routeCtx&&!routeCtx.active())return;
      wb.revisionId=rev.id;wb.data=data;wb.values={...(data.effective_parameters||{})};(data.parameters||[]).forEach(row=>{if(!(row.id in wb.values))wb.values[row.id]=row.value});wb.changed=new Set();wb.selected=(data.parameters||[])[0]?.id||null;wb.group=recordFor(wb.selected)?.category||data.groups?.[0]?.id||'topology';wb.view=(data.design_views||[]).find(row=>row.preferred)?.id||'radial';wb.precheck=data.precheck;wb.nativeCheck=null;wb.windingText=null;renderShell();
    }catch(error){if(window.MCSPageRuntime?.isAbortError?.(error))return;if(canvas)canvas.innerHTML=`<div class="workspace-empty"><b>模型工作台加载失败</b><p>${escHtml(error.message||error)}</p></div>`;toast(error.message,'ERROR',8000);}
  }

  async function openWorkbenchView(view='radial',parameterId=null){
    await openRevisionEditorV024();
    if(view)wb.view=view;
    if(parameterId&&recordFor(parameterId)){wb.selected=parameterId;wb.group=recordFor(parameterId)?.category||wb.group;renderParameters();renderSelected();}
    renderVisual();
  }

  window.openRevisionEditorV024=openRevisionEditorV024;
  window.MCSModelWorkbench={open:openRevisionEditorV024,openView:openWorkbenchView,selectParameter,setValue,state:wb};
})();
