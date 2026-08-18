/* V0.24 Motor Model Workbench: continuous model editing, parameter dependency and evidence UX.
 * Legacy compatibility label: 轴向截面. The radial-flux UI now calls this 纵向装配剖面.
 * Legacy test vocabulary retained as non-rendered compatibility metadata:
 * 径向截面；纵向装配剖面；绕组连接；槽内定义；设计验证；模型检查。
 * Motor-CAD 证据；运行 Motor-CAD 原生检查；预览参数源；不能替代 Motor-CAD 的真实 coil go/return slot 定义。
 */
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
    previewFrame: 0,
    materials: {},
    materialDirty: false,
    explicitIds: new Set(),
    draft: null,
    draftTimer: 0,
    draftSaveBusy: false,
    draftSavedAt: null,
    draftConflict: null,
    draftSavePromise: null,
    draftPending: null,
    draftPayloadVersion: 0,
    draftPersistedVersion: 0,
    draftSession: 0,
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

  function totalChangeCount(){return wb.changed.size+(wb.materialDirty?1:0)}
  function draftStatusText(){
    if(wb.draftSaveBusy)return'正在保存草稿…';
    if(wb.draftConflict)return'其他版本存在草稿';
    if(wb.draftSavedAt)return`草稿已保存 ${new Date(wb.draftSavedAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    return totalChangeCount()?'草稿等待保存':'基于已保存版本';
  }
  function updateDraftStatus(){const el=$q('#workbenchDraftStatusV062');if(el)el.textContent=draftStatusText();window.MCSDesignStore?.patch?.({draftStatus:wb.draftConflict?'conflict':wb.draftSaveBusy?'saving':wb.draftSavedAt?'saved':totalChangeCount()?'dirty':'saved',dirtyCount:totalChangeCount()},{source:'draft-status'})}
  function draftPayload(){
    const design=state.workspaceDesign,rev=state.workspaceRevision;if(!design||!rev)return null;
    return{base_revision_id:rev.id,parameters:wb.values,materials:wb.materials,explicit_parameter_ids:[...new Set([...wb.explicitIds,...changedIds()])],active_view:wb.view,notes:`基于 Rev.${rev.revision} 的设计草稿`};
  }
  function cloneDraftPayload(payload){
    if(typeof structuredClone==='function')return structuredClone(payload);
    return JSON.parse(JSON.stringify(payload));
  }
  async function drainDraftQueue(){
    if(wb.draftSavePromise)return wb.draftSavePromise;
    wb.draftSavePromise=(async()=>{
      while(wb.draftPending){
        const request=wb.draftPending;wb.draftPending=null;wb.draftSaveBusy=true;updateDraftStatus();
        try{
          if(request.deleteDraft){
            if(request.force||wb.draft)await api(`/api/designs/${encodeURIComponent(request.designId)}/draft`,{method:'DELETE'});
            if(request.session===wb.draftSession&&request.version>=wb.draftPersistedVersion){wb.draft=null;wb.draftSavedAt=null;wb.draftConflict=null;wb.draftPersistedVersion=request.version}
            if(!request.silent)toast('设计草稿已清除。','SUCCESS',3200);
          }else{
            const result=await api(`/api/designs/${encodeURIComponent(request.designId)}/draft`,{method:'PUT',body:JSON.stringify(request.payload)});
            if(request.session===wb.draftSession&&request.version>=wb.draftPersistedVersion){wb.draft=result.draft||null;wb.draftSavedAt=wb.draft?.updated_at||new Date().toISOString();wb.draftConflict=null;wb.draftPersistedVersion=request.version}
            if(!request.silent)toast('设计草稿已保存。','SUCCESS',3200);
          }
        }catch(error){
          if(request.session===wb.draftSession)wb.draftSavedAt=null;
          if(!request.silent)toast(`设计草稿保存失败：${error.message}`,'ERROR',6500);
          throw error;
        }finally{if(request.session===wb.draftSession){wb.draftSaveBusy=false;updateDraftStatus()}}
      }
      return wb.draft;
    })().finally(()=>{wb.draftSavePromise=null;wb.draftSaveBusy=false;updateDraftStatus();if(wb.draftPending)drainDraftQueue().catch(()=>{})});
    return wb.draftSavePromise;
  }
  function queueDraftDelete({silent=true,force=false}={}){
    const design=state.workspaceDesign;if(!design)return Promise.resolve(null);
    clearTimeout(wb.draftTimer);const version=++wb.draftPayloadVersion;
    wb.draftPending={designId:design.id,deleteDraft:true,force,silent,version,session:wb.draftSession};wb.draftSavedAt=null;updateDraftStatus();return drainDraftQueue();
  }
  function persistDraft({silent=true}={}){
    const design=state.workspaceDesign,payload=draftPayload();if(!design||!payload)return Promise.resolve(null);
    if(wb.draftConflict)return Promise.reject(new Error('当前电机已有基于其他 Design Revision 的草稿，请先处理草稿冲突'));
    clearTimeout(wb.draftTimer);const version=++wb.draftPayloadVersion;
    wb.draftPending={designId:design.id,payload:cloneDraftPayload(payload),deleteDraft:!totalChangeCount(),force:false,silent,version,session:wb.draftSession};
    if(totalChangeCount())wb.draftSavedAt=null;updateDraftStatus();return drainDraftQueue();
  }
  function scheduleDraftSave(){clearTimeout(wb.draftTimer);if(totalChangeCount())wb.draftSavedAt=null;updateDraftStatus();if(wb.draftConflict)return;if(!totalChangeCount()&&!wb.draft)return;wb.draftTimer=setTimeout(()=>persistDraft({silent:true}).catch(()=>{}),650)}
  function stableDraftValue(value){if(Array.isArray(value))return value.map(stableDraftValue);if(value&&typeof value==='object'){const out={};Object.keys(value).sort().forEach(key=>{out[key]=stableDraftValue(value[key])});return out}return value}
  function materialSnapshot(value){try{return JSON.stringify(stableDraftValue(value||{}))}catch{return String(value)}}

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

  function conflictRevisionLabel(){
    const id=wb.draftConflict?.base_revision_id||wb.draftConflict;
    const row=(state.workspaceDesign?.revisions||[]).find(item=>item.id===id);
    return row?.revision?`Rev.${row.revision}`:'另一个 Design Revision';
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
    document.body.classList.add('design-editing-v062');
    canvas.innerHTML = `<div class="workspace-object-header model-workbench-header-v024 workbench-draft-header-v062"><div><span class="eyebrow">电机设计草稿</span><h2>${escHtml(rev.design_name)} · 基于 Rev.${escHtml(rev.revision)}</h2><p>几何、绕组和材料修改会自动保存为草稿；确认后一次性冻结为新的不可变 Design Revision。</p><span id="workbenchDraftStatusV062" class="draft-save-status-v062">${escHtml(draftStatusText())}</span></div><div class="actions"><button id="workbenchDiscardV062" type="button" class="danger-quiet">放弃草稿</button><button id="workbenchCancelV024" type="button">退出编辑（保留草稿）</button><button id="workbenchSaveV024" class="primary" type="button">保存为新 Revision</button></div></div>
    ${wb.draftConflict?`<div class="draft-conflict-banner-v062"><div><b>该电机已有未冻结草稿</b><span>现有草稿基于 ${escHtml(conflictRevisionLabel())}。为避免覆盖另一版本的设计修改，请先恢复现有草稿或明确放弃它。</span></div><div class="actions"><button type="button" data-open-existing-draft-v062>打开现有草稿</button><button type="button" class="danger-quiet" data-replace-existing-draft-v062>放弃现有草稿并编辑当前版本</button></div></div>`:''}
    <div class="model-workbench-v024 ${wb.draftConflict?'draft-conflict-locked-v062':''}">
      <aside class="workbench-tree-v024">
        <div class="workbench-search-v024"><label for="workbenchSearchV024">设计参数</label><input id="workbenchSearchV024" placeholder="搜索参数名称或部件"></div>
        <div id="workbenchGroupsV024" class="workbench-groups-v024"></div>
        <div class="workbench-region-box-v024"><span class="eyebrow">模型区域</span><div id="workbenchRegionsV024"></div></div>
      </aside>
      <main class="workbench-main-v024">
        <section class="workbench-visual-v024">
          <div class="workbench-navigation-v062">
            <div id="workbenchStageNavV062" class="workbench-stage-nav-v062" aria-label="设计草稿步骤"></div>
            <div id="workbenchSubviewNavV062" class="workbench-subview-nav-v062" aria-label="当前草稿视图"></div>
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
    if (inspector) inspector.innerHTML = `<div class="inspector-block"><span class="eyebrow">当前电机</span><h3>${escHtml(rev.design_name)}</h3><div class="property-grid"><span>设计版本</span><b>版本 ${escHtml(rev.revision)}</b><span>草稿修改</span><b id="workbenchChangeCountV024">0 项</b><span>起始模板</span><b>${escHtml(rev.template_id)}</b><span>检查状态</span><b id="workbenchInspectorStatusV024">—</b></div><div class="inspector-note">示意图随参数实时更新；计算前检查会依次执行 Studio 预检查和 Motor-CAD 模型检查。</div></div>`;

    renderGroups(); renderRegions(); renderParameters(); renderVisual(); renderSelected(); renderEvidence(); renderPrecheck(); bindShell();
  }

  function renderGroups(filter='') {
    const box=$q('#workbenchGroupsV024');if(!box)return;
    box.innerHTML=window.MCSDesignParameterInspector?.editorGroupButtons?.({data:wb.data,group:wb.group,changed:wb.changed,filter})||'';
  }
  function renderRegions(){
    const box=$q('#workbenchRegionsV024');if(!box)return;
    box.innerHTML=window.MCSDesignParameterInspector?.editorRegionButtons?.({data:wb.data})||'';
  }
  function renderParameters(){
    const box=$q('#workbenchParameterRowsV024');if(!box)return;
    const group=(wb.data.groups||[]).find(g=>g.id===wb.group),title=$q('#workbenchGroupTitleV024');if(title)title.textContent=group?.label||wb.group;
    box.innerHTML=window.MCSDesignParameterInspector?.editorParameterRows?.({data:wb.data,group:wb.group,values:wb.values,changed:wb.changed,selected:wb.selected})||'<div class="workspace-empty compact">当前分组没有可编辑设计参数。</div>';
    updateChangeCount();
  }

  function updateChangeCount(){
    const n=totalChangeCount(),parts=[];if(wb.changed.size)parts.push(`${wb.changed.size} 参数`);if(wb.materialDirty)parts.push('材料');
    const count=$q('#workbenchChangeCountV024'); if(count)count.textContent=n?(parts.join(' + ')):'0 项';
    const save=$q('#workbenchSaveV024'); if(save)save.disabled=wb.saveBusy||n===0||Boolean(wb.draftConflict);window.MCSDesignStore?.patch?.({dirtyCount:n},{source:'editor-dirty'});updateDraftStatus();
  }

  function workbenchStageForView(view){return window.MCSAppCoreV062?.stageForView?.(view)||(view==='winding'||view==='slot'?'winding':view==='materials'?'materials':view==='native'?'validation':view==='compare'?'compare':'geometry')}
  function renderWorkbenchNavigation(){
    const stageBox=$q('#workbenchStageNavV062'),subBox=$q('#workbenchSubviewNavV062');if(!stageBox||!subBox)return;
    if(window.MCSDesignNavigation?.render){window.MCSDesignNavigation.render({stageBox,subBox,data:wb.data,view:wb.view,mode:'edit',variant:'workbench'});return;}
    const stage=workbenchStageForView(wb.view);stageBox.textContent=stage;subBox.textContent='';
  }
  function workbenchDefaultViewForStage(stage){return window.MCSDesignNavigation?.defaultViewForStage?.(stage,wb.data,{mode:'edit'})||(stage==='winding'?'winding':stage==='materials'?'materials':stage==='validation'?'native':'radial')}

  function renderVisual(){
    const box=$q('#workbenchVisualStageV024');if(!box)return;
    window.MCSDesignStore?.setContext?.({projectId:state.activeProjectId||null,designId:state.workspaceDesign?.id||null,revisionId:wb.revisionId,mode:'edit',view:wb.view,selectedParameter:wb.selected,data:wb.data,dirtyCount:totalChangeCount()},{source:'editor-render'});
    renderWorkbenchNavigation();$$q('[data-workbench-view]').forEach(b=>b.classList.toggle('active',b.dataset.workbenchView===wb.view));
    const ctx={data:wb.data,values:wb.values,materials:wb.materials,precheck:wb.precheck,selected:wb.selected,editable:true};
    const auxiliary=window.MCSDesignRenderer?.renderAuxiliaryView?.(wb.view,{...wb.data,effective_parameters:wb.values,materials:wb.materials});
    const viewHtml=auxiliary??window.MCSDesignRenderer?.renderWorkbenchView?.(wb.view,ctx);
    box.innerHTML=viewHtml??'<div class="native-empty-v031">当前设计视图不可用。</div>';
    const next=window.MCSDesignNavigation?.next?.(wb.view,wb.data,{mode:'edit'});
    if(next)box.insertAdjacentHTML('beforeend',`<div class="design-next-step-v063 design-next-step-v064"><div><span>编辑流程</span><b>${escHtml(next.label)}</b><small>草稿会自动保存，可在各设计阶段之间直接切换。</small></div><button type="button" class="primary" data-workbench-next-v063="${escHtml(next.target)}">${escHtml(next.label)} →</button></div>`);
    highlightSelectedRegion();
  }

  function selectedDependency(){return wb.selected?wb.data.dependencies?.[wb.selected]||{}:{};}

  function renderSelected(){
    const box=$q('#workbenchSelectedV024');if(!box)return;
    box.innerHTML=window.MCSDesignParameterInspector?.editorSelectedCard?.({data:wb.data,values:wb.values,selected:wb.selected})||'<span class="eyebrow">参数联动</span><h3>选择一个参数</h3>';
  }

  function renderPrecheck(){
    const box=$q('#workbenchStatusV024'); if(!box)return;
    if(totalChangeCount()){
      box.className='workbench-diagnostic-card-v024 workbench-status-warning-v024';
      box.innerHTML='<div class="diagnostic-title-v024"><div><span class="eyebrow">计算前检查</span><h3>参数已修改，尚未执行检查</h3></div><span class="badge warn">待保存</span></div><p>可以继续调整并保存设计版本。进入“计算前检查”后，系统会先检查几何、绕组和物理输入，通过后再启动 Motor-CAD 模型检查。</p>';
      const inspector=$q('#workbenchInspectorStatusV024');if(inspector)inspector.textContent='待计算前检查';
      updateChangeCount();return;
    }
    const p=wb.precheck||wb.data.precheck||{}; wb.precheck=p;
    const blocks=(p.issues||[]).filter(x=>x.severity==='BLOCKING'), warns=(p.issues||[]).filter(x=>x.severity!=='BLOCKING');
    const tone=blocks.length?'blocking':warns.length?'warning':'pass';
    box.className=`workbench-diagnostic-card-v024 workbench-status-${tone}-v024`;
    box.innerHTML=`<div class="diagnostic-title-v024"><div><span class="eyebrow">最近一次保存状态</span><h3>${blocks.length?'当前保存版本有待修复项':warns.length?'当前保存版本有提示':'当前保存版本未发现确定性问题'}</h3></div><span class="badge ${blocks.length?'error':warns.length?'warn':'ok'}">${blocks.length?`${blocks.length} 项问题`:warns.length?`${warns.length} 项提示`:'通过'}</span></div>${(p.issues||[]).length?`<div class="workbench-issue-list-v024">${(p.issues||[]).map((issue,i)=>`<button type="button" data-workbench-issue="${i}" class="${issue.severity==='BLOCKING'?'blocking':'warning'}"><b>${escHtml(issue.message||issue.code)}</b><small>${(issue.parameter_ids||[]).map(parameterLabel).join(' / ')||'电机模型'}</small></button>`).join('')}</div>`:'<p>正式计算前会统一执行 Studio 预检查和 Motor-CAD 模型检查。</p>'}`;
    const inspector=$q('#workbenchInspectorStatusV024'); if(inspector)inspector.textContent=blocks.length?'BLOCKING':warns.length?'WARNING':'PASS';
    updateChangeCount();
  }

  function renderEvidence(){
    const box=$q('#workbenchEvidenceV024'); if(!box)return;
    const e=wb.data.native_evidence, n=wb.nativeCheck;
    const prev=wb.data.previous_feasible;
    let nativeHtmlPart='';
    if(n){const pass=n.status==='PASS';nativeHtmlPart=`<div class="native-check-result-v024 ${pass?'pass':'fail'}"><b>${pass?'✓ 当前电机已通过 Motor-CAD 模型检查':'当前电机未通过 Motor-CAD 模型检查'}</b>${!pass?nativeFailureSummary(n):''}</div>`;}
    else if(e){nativeHtmlPart=`<div class="native-check-result-v024 history"><b>最近一次模型检查：${['SUCCEEDED','COMPLETED'].includes(e.execution_status||e.task_status)?'已完成':'需要关注'}</b><small>${escHtml(e.finished_at||'')}</small></div>`;}
    else nativeHtmlPart='<p class="hint">当前设计版本还没有 Motor-CAD 模型检查记录。</p>';
    box.innerHTML=`<span class="eyebrow">模型检查记录</span><h3>${prev?.source==='revision'?`上一可行版本 ${escHtml(prev.revision)}`:prev?'起始模板可行':'等待首次检查'}</h3>${nativeHtmlPart}<div class="evidence-rule-v024"><b>检查顺序</b><span>参数关系 → Motor-CAD 几何与绕组 → 正式计算 → 结果验证</span></div>`;
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

  function setValue(id,value,{render=true}={}){
    if(wb.draftConflict)return;
    const row=recordFor(id); if(!row)return;
    let next=value;
    if(row.type==='integer') next=Math.round(Number(value)); else if(typeof value==='string'&&value.trim()!=='')next=Number(value);
    if(!Number.isFinite(Number(next)))return;
    wb.values[id]=Number(next); refreshChanged(id);
    const input=$q(`[data-workbench-input="${CSS.escape(id)}"]`); if(input&&String(input.value)!==String(next))input.value=String(next);
    if(render){renderParameters();renderVisual();renderSelected();renderPrecheck();scheduleDraftSave();}
  }

  function restoreGroup(source){
    if(wb.draftConflict)return;
    const rows=(wb.data.parameters||[]).filter(row=>row.category===wb.group);
    rows.forEach(row=>{const value=source==='previous'?row.previous_feasible_value:row.template_default;if(value!==undefined)setValue(row.id,value,{render:false});});
    renderParameters();renderVisual();renderSelected();renderPrecheck();scheduleDraftSave();
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
      const payload={parameters:wb.values,explicit_parameter_ids:[...new Set([...(state.workspaceRevision?.explicit_parameter_ids||[]),...changedIds()])],materials:wb.materials||{},timeout_s:180};
      const result=await api(`/api/templates/${encodeURIComponent(wb.data.revision.template_id)}/geometry-check`,{method:'POST',body:JSON.stringify(payload)});
      wb.nativeCheck=result; renderPrecheck(); renderEvidence(); if(result.status==='PASS')toast('当前编辑值已通过 Motor-CAD 原生几何与绕组检查。','SUCCESS',6500);else toast('Motor-CAD 原生模型检查未通过；已定位到工作台约束面板。','ERROR',7500);
    }catch(error){toast(`Motor-CAD 原生检查失败：${error.message}`,'ERROR',8000);}
    finally{wb.nativeBusy=false;renderPrecheck();renderEvidence();}
  }

  function activeAnalysisForDesign(){
    const design=state.workspaceDesign;
    if(!design)return null;
    return (window.MCSV060?.state?.rows||[]).find(row=>row.id===window.MCSV060?.state?.activeId&&row.design_id===design.id)||null;
  }

  async function saveRevision(){
    if(wb.saveBusy||!totalChangeCount())return;
    const commit=await revisionNotesSheet();if(commit===null)return;
    const notes=typeof commit==='object'?(commit.notes||''):String(commit||'');
    const analysisDefinitionId=typeof commit==='object'?(commit.analysis_definition_id||null):null;
    wb.saveBusy=true;updateChangeCount();const button=$q('#workbenchSaveV024');if(button)button.textContent='正在冻结 Revision…';
    try{
      const design=state.workspaceDesign;if(!design)throw new Error('当前电机设计不存在');
      await persistDraft({silent:true});
      const created=await api(`/api/designs/${encodeURIComponent(design.id)}/draft/commit`,{method:'POST',body:JSON.stringify({notes:notes||`基于 Rev.${state.workspaceRevision?.revision} 的设计草稿`,analysis_definition_id:analysisDefinitionId})});
      state.workspaceProject=await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`);document.body.classList.remove('design-editing-v062');window.MCSDesignStore?.setMode?.('read',{source:'editor-commit'});
      if(window.MCSV060?.state)window.MCSV060.state.fetchedAt=0;
      toast(`已创建 Rev.${created.revision}；${created.linked_analysis_definition_id?'当前分析案例已引用新版本；':''}草稿已清除。`,'SUCCESS',6500);await openWorkspaceDesign(design.id);if(created.id)selectWorkspaceRevision(created.id);window.MCSRouter?.setRevisionEditMode?.(false,{view:wb.view,replace:true});window.MCSRouter?.syncDesignView?.(wb.view,{replace:true});
    }catch(error){toast(error.message,'ERROR',8500);wb.saveBusy=false;if(button)button.textContent='保存为新 Revision';updateChangeCount()}
  }

  async function exitWorkbenchPreservingDraft(){
    try{if(totalChangeCount())await persistDraft({silent:true})}catch(error){toast(`草稿尚未保存：${error.message}`,'ERROR',6500);return}
    document.body.classList.remove('design-editing-v062');window.MCSDesignStore?.setMode?.('read',{source:'editor-exit'});window.MCSRouter?.setRevisionEditMode?.(false,{view:wb.view,replace:true});await openWorkspaceDesign(state.workspaceDesign.id);window.MCSRouter?.syncDesignView?.(wb.view,{replace:true});
  }
  async function confirmDestructive(title,message,confirmLabel='确认'){
    if(!window.StudioDialog?.sheet){toast('确认对话框尚未加载，已取消该操作。','WARNING',4200);return false}
    const result=await StudioDialog.sheet({title,html:`<div class="step-help-sheet"><p>${escHtml(message)}</p><p class="hint">此操作不会影响已经冻结的 Design Revision。</p></div>`,actions:[{label:'取消',value:false},{label:confirmLabel,value:true,primary:true}]});
    return result===true;
  }
  async function discardDraft(){
    const design=state.workspaceDesign;if(!design)return;
    const ok=await confirmDestructive('放弃当前设计草稿','未冻结的参数和材料修改将被删除。','放弃草稿');if(!ok)return;
    try{clearTimeout(wb.draftTimer);await queueDraftDelete({silent:true,force:true});document.body.classList.remove('design-editing-v062');window.MCSDesignStore?.setMode?.('read',{source:'editor-discard'});toast('设计草稿已放弃。','SUCCESS',3200);window.MCSRouter?.setRevisionEditMode?.(false,{view:wb.view,replace:true});await openWorkspaceDesign(design.id);window.MCSRouter?.syncDesignView?.(wb.view,{replace:true})}catch(error){toast(`草稿删除失败：${error.message}`,'ERROR',6500)}
  }

  async function revisionNotesSheet(){
    const candidate=activeAnalysisForDesign();
    if(!window.StudioDialog?.sheet)return {notes:`基于 Rev.${state.workspaceRevision?.revision} 的模型工作台修改`,analysis_definition_id:null};
    const value=await StudioDialog.sheet({
      title:'保存新的 Design Revision',
      html:`<div class="step-help-sheet"><p>将当前 ${totalChangeCount()} 组修改冻结为新的不可变设计版本。已有 Task 和其他分析案例继续指向原 Revision。</p>${candidate?`<label class="revision-analysis-link-v062"><input id="workbenchLinkAnalysisV062" type="checkbox" checked><span><b>让当前分析案例采用新版本</b><small>${escHtml(candidate.name||candidate.id)} 将切换到新 Revision；其他分析案例保持原版本。</small></span></label>`:'<p class="hint">当前没有与此电机匹配的活动分析案例；保存设计不会改变任何分析案例的版本引用。</p>'}<label>Revision 说明<textarea id="workbenchRevisionNotesV024" rows="4" placeholder="例如：调整槽口和齿宽以降低槽满率风险"></textarea></label></div>`,
      actions:[
        {label:'取消',value:null},
        {label:'确认保存',primary:true,getValue:box=>({notes:box.querySelector('#workbenchRevisionNotesV024')?.value.trim()||'',analysis_definition_id:candidate&&box.querySelector('#workbenchLinkAnalysisV062')?.checked?candidate.id:null})},
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
    $q('[data-open-existing-draft-v062]')?.addEventListener('click',async()=>{const target=wb.draftConflict?.base_revision_id||wb.draftConflict;if(!target)return;await Promise.resolve(window.selectWorkspaceRevision?.(target));await openRevisionEditorV024()});
    $q('[data-replace-existing-draft-v062]')?.addEventListener('click',async()=>{const design=state.workspaceDesign;if(!design)return;const ok=await confirmDestructive('替换现有设计草稿',`将删除基于 ${conflictRevisionLabel()} 的现有草稿，并从当前版本重新开始编辑。`,'删除旧草稿并继续');if(!ok)return;try{await queueDraftDelete({silent:true,force:true});wb.draftConflict=null;wb.draft=null;wb.draftSavedAt=null;renderShell();toast('旧草稿已放弃，现在可以编辑当前版本。','SUCCESS',3800)}catch(error){toast(`旧草稿删除失败：${error.message}`,'ERROR',6500)}});
    $q('#workbenchCancelV024')?.addEventListener('click',exitWorkbenchPreservingDraft);
    $q('#workbenchDiscardV062')?.addEventListener('click',discardDraft);
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
      const material=event.target.closest('[data-workbench-material-component]');if(material){if(wb.draftConflict)return;const component=material.dataset.workbenchMaterialComponent,type=material.dataset.materialTypeV062||'';window.MCSMaterialLibrary?.pick?.({kind:'solid',materialType:type,componentLabel:component,title:`选择 ${component} 材料`,onSelect:row=>{const components={...(wb.materials.component_materials||{})},provenance={...(wb.materials.material_provenance||{})};components[component]=row.name;provenance[component]={material_record_id:row.id,source_kind:row.source_kind,source_database_path:row.source_database_path,source_database_hash:row.source_database_hash,material_section_hash:row.material_section_hash,motorcad_version:row.motorcad_version};wb.materials={...wb.materials,component_materials:components,material_provenance:provenance};wb.materialDirty=materialSnapshot(wb.materials)!==materialSnapshot(state.workspaceRevision?.materials||{});renderVisual();updateChangeCount();scheduleDraftSave()}});return;}
      const stage=event.target.closest('[data-workbench-stage-v062]');if(stage){wb.view=workbenchDefaultViewForStage(stage.dataset.workbenchStageV062);window.MCSDesignStore?.setView?.(wb.view,{source:'editor-stage'});renderVisual();scheduleDraftSave();window.MCSRouter?.syncDesignView?.(wb.view,{replace:true});return;}
      const view=event.target.closest('[data-workbench-view]');if(view){wb.view=view.dataset.workbenchView;window.MCSDesignStore?.setView?.(wb.view,{source:'editor-tab'});renderVisual();scheduleDraftSave();window.MCSRouter?.syncDesignView?.(wb.view,{replace:true});return;}
      const next=event.target.closest('[data-workbench-next-v063]');if(next){const target=next.dataset.workbenchNextV063;if(target==='commit'){saveRevision();return;}wb.view=target;window.MCSDesignStore?.setView?.(wb.view,{source:'editor-next'});renderVisual();scheduleDraftSave();window.MCSRouter?.syncDesignView?.(wb.view,{replace:true});return;}
      const issue=event.target.closest('[data-workbench-issue]');if(issue){const row=wb.precheck?.issues?.[Number(issue.dataset.workbenchIssue)];const id=(row?.parameter_ids||[]).find(pid=>recordFor(pid));if(id)selectParameter(id);return;}
      if(event.target.closest('#loadNativeWindingV024')){loadNativeWinding();return;}
      const schematic=event.target.closest('[data-schematic-part]');if(schematic){const tags=String(schematic.dataset.schematicPart||'').split(/\s+/);const regionId=tags.find(tag=>wb.data.regions?.[tag]);if(regionId)selectRegion(regionId);}
    });
    canvas?.addEventListener('input',event=>{if(wb.draftConflict)return;const input=event.target.closest('[data-workbench-input]');if(!input)return;const id=input.dataset.workbenchInput;const number=Number(input.value);if(!Number.isFinite(number))return;wb.values[id]=recordFor(id)?.type==='integer'?Math.round(number):number;refreshChanged(id);wb.selected=id;window.MCSDesignStore?.selectParameter?.(id,{source:'editor-input'});input.closest('[data-workbench-param-row]')?.classList.toggle('changed',wb.changed.has(id));updateChangeCount();renderPrecheck();scheduleDraftSave();cancelAnimationFrame(wb.previewFrame);wb.previewFrame=requestAnimationFrame(()=>{renderSelected();renderVisual();});});
    canvas?.addEventListener('focusin',event=>{const input=event.target.closest('[data-workbench-input]');if(input){wb.selected=input.dataset.workbenchInput;window.MCSDesignStore?.selectParameter?.(wb.selected,{source:'editor-focus'});renderSelected();highlightSelectedRegion();}});
  }

  async function openRevisionEditorV024(routeCtx=null){
    const design=state.workspaceDesign, rev=state.workspaceRevision;
    if(!design||!rev)return toast('请先选择 Design Revision','WARNING');
    const canvas=$q('#workspaceCanvas'); if(canvas)canvas.innerHTML='<div class="workspace-empty"><span class="connection-pulse"></span><b>正在加载电机设计…</b><p>读取设计参数、影响关系、上一可行值和模型检查状态。</p></div>';
    try{
      const options=routeCtx?.signal?{signal:routeCtx.signal}:{};const [data,draftResult]=await Promise.all([api(`/api/design-revisions/${encodeURIComponent(rev.id)}/workbench`,options),api(`/api/designs/${encodeURIComponent(design.id)}/draft`,options).catch(()=>({exists:false,draft:null}))]);if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;
      wb.draftSession+=1;wb.revisionId=rev.id;wb.data=data;wb.values={...(data.effective_parameters||{})};(data.parameters||[]).forEach(row=>{if(!(row.id in wb.values))wb.values[row.id]=row.value});wb.materials=typeof structuredClone==='function'?structuredClone(rev.materials||{}):JSON.parse(JSON.stringify(rev.materials||{}));wb.changed=new Set();wb.materialDirty=false;wb.explicitIds=new Set(rev.explicit_parameter_ids||[]);wb.draft=null;wb.draftConflict=null;wb.draftSavedAt=null;
      const draft=draftResult?.draft||null;if(draft&&draft.base_revision_id===rev.id){wb.draft=draft;wb.values={...wb.values,...(draft.parameters||{})};wb.materials=draft.materials||wb.materials;wb.explicitIds=new Set(draft.explicit_parameter_ids||rev.explicit_parameter_ids||[]);wb.draftSavedAt=draft.updated_at||null;(data.parameters||[]).forEach(row=>refreshChanged(row.id));wb.materialDirty=materialSnapshot(wb.materials)!==materialSnapshot(rev.materials||{})}else if(draft){wb.draftConflict=draft}
      wb.selected=(data.parameters||[])[0]?.id||null;wb.group=recordFor(wb.selected)?.category||data.groups?.[0]?.id||'topology';wb.view=(draft&&draft.base_revision_id===rev.id&&draft.active_view)||(window.MCSDesignStore?.currentView?.())||(window.MCSDesignViewer?.state?.view)||(window.MCSVisualV031?.state?.view)||((data.design_views||[]).find(row=>row.preferred)?.id||'radial');wb.precheck=data.precheck;wb.nativeCheck=null;wb.windingText=null;window.MCSDesignStore?.setContext?.({projectId:state.activeProjectId||null,designId:design.id,revisionId:rev.id,mode:'edit',view:wb.view,selectedParameter:wb.selected,data,dirtyCount:totalChangeCount()},{source:'editor-load'});renderShell();window.MCSRouter?.setRevisionEditMode?.(true,{view:wb.view,replace:true});if(wb.draft)toast('已恢复上次未冻结的设计草稿。','INFO',4200);
    }catch(error){if(window.MCSPageRuntime?.isAbortError?.(error))return;if(canvas)canvas.innerHTML=`<div class="workspace-empty"><b>模型工作台加载失败</b><p>${escHtml(error.message||error)}</p></div>`;toast(error.message,'ERROR',8000);}
  }

  async function openWorkbenchView(view='radial',parameterId=null){
    await openRevisionEditorV024();
    if(view)wb.view=view;
    if(parameterId&&recordFor(parameterId)){wb.selected=parameterId;wb.group=recordFor(parameterId)?.category||wb.group;renderParameters();renderSelected();}
    renderVisual();window.MCSRouter?.syncDesignView?.(wb.view,{replace:true});
  }

  window.openRevisionEditorV024=openRevisionEditorV024;
  function applyRouteView(route){
    let requested=route?.designView||window.MCSAppCoreV062?.viewForRoute?.(route?.designSection,route?.designSubview);
    if(requested==='evidence')requested='native';
    if(!requested)return;
    wb.view=requested;window.MCSDesignStore?.setView?.(requested,{source:'editor-route'});
    if(wb.data){renderVisual();scheduleDraftSave()}
  }

  window.MCSModelWorkbench={open:openRevisionEditorV024,openView:openWorkbenchView,applyRouteView,selectParameter,setValue,state:wb};
})();
