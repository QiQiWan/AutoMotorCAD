/* V0.92 Engineering requirements UX: engineer-readable, bilingual, immutable revisions. */
(() => {
  const safe=v=>typeof esc==='function'?esc(v??''):String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const q=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const lang=()=>String(document.documentElement.lang||window.MCS_I18N?.language||'zh').toLowerCase().startsWith('en')?'en':'zh';
  const tr=(zh,en)=>lang()==='en'?en:zh;
  const defaultCatalog=[
    {id:'shaft_torque_nm',label:'轴端转矩',unit:'Nm',operator:'GE',kind:'HARD_CONSTRAINT',group:'性能',description:'输出轴平均转矩，用于判断电机负载能力。'},
    {id:'efficiency_percent',label:'效率',unit:'%',operator:'GE',kind:'HARD_CONSTRAINT',group:'性能',description:'输入能量转换为机械输出的效率。'},
    {id:'torque_ripple_percent',label:'转矩脉动',unit:'%',operator:'LE',kind:'WARNING',group:'性能',description:'转矩周期波动比例，用于评价平顺性和电磁激振风险。'},
    {id:'output_power_w',label:'输出功率',unit:'W',operator:'GE',kind:'OBJECTIVE',group:'性能',description:'轴端机械输出功率。'},
    {id:'total_loss_w',label:'总损耗',unit:'W',operator:'LE',kind:'OBJECTIVE',group:'损耗',description:'电机主要损耗分量的总和。'},
    {id:'copper_loss_w',label:'铜耗',unit:'W',operator:'LE',kind:'WARNING',group:'损耗',description:'绕组电阻产生的铜损，是热负荷的重要来源。'},
    {id:'stator_iron_loss_w',label:'定子铁耗',unit:'W',operator:'LE',kind:'WARNING',group:'损耗',description:'定子铁心磁滞与涡流损耗。'},
    {id:'magnet_loss_w',label:'永磁体损耗',unit:'W',operator:'LE',kind:'WARNING',group:'损耗',description:'永磁体内附加损耗，关联磁钢温升与退磁风险。'},
    {id:'winding_max_temperature_c',label:'绕组最高温度',unit:'°C',operator:'LE',kind:'HARD_CONSTRAINT',group:'热',description:'绕组计算域内最高温度，用于绝缘寿命和热安全判断。'},
    {id:'magnet_temperature_c',label:'永磁体温度',unit:'°C',operator:'LE',kind:'HARD_CONSTRAINT',group:'热',description:'永磁体温度，用于磁性能衰减和退磁裕度判断。'}
  ];
  let catalog=[...defaultCatalog];
  const fallbackHint=id=>defaultCatalog.find(row=>row.id===id)||{id,label:id,unit:'',operator:'LE',kind:'MONITOR',group:'',description:''};
  const metricMeta=id=>catalog.find(row=>row.id===id)||fallbackHint(id);
  const kindLabel=v=>({HARD_CONSTRAINT:tr('必须满足','Required'),OBJECTIVE:tr('优化方向','Optimization target'),WARNING:tr('预警线','Warning'),MONITOR:tr('仅观察','Monitor')}[v]||v||'—');
  const opLabel=v=>({GE:tr('不低于','At least'),LE:tr('不高于','At most'),BETWEEN:tr('区间内','Within range')}[v]||v||'—');
  const evalStatus=v=>({QUALIFIED:tr('满足要求','Qualified'),QUALIFIED_WITH_WARNING:tr('满足要求 · 有预警','Qualified · warning'),BLOCKED:tr('未满足或证据不完整','Not qualified / incomplete'),NOT_CONFIGURED:tr('未配置','Not configured')}[v]||v||'—');

  function render(requirementSet,evaluation){
    if(!requirementSet)return `<article class="panel requirements-authority-card empty"><div class="section-head"><div><span class="eyebrow">${tr('工程要求','ENGINEERING REQUIREMENTS')}</span><h3>${tr('尚未设置工程要求','Engineering requirements are not configured')}</h3><p>${tr('当前可以查看计算结果，但系统还不能正式回答“这个设计是否达标”。定义必须满足的指标后，结果页会自动逐项判定。','Results can be reviewed, but the system cannot formally determine whether the design meets project targets until requirements are defined.')}</p></div><button type="button" class="primary" data-edit-engineering-requirements>${tr('定义工程要求','Define requirements')}</button></div></article>`;
    const summary=evaluation?.summary||{},rows=(requirementSet.requirements||[]).filter(r=>r.enabled!==false),policy=requirementSet.decision_policy||{};
    const status=evaluation?.status||'CONFIGURED';
    const name=(requirementSet.name==='Project engineering requirements'&&lang()==='zh')?'项目工程要求':(requirementSet.name||tr('项目工程要求','Project engineering requirements'));
    return `<article class="panel requirements-authority-card ${String(status).toLowerCase()}"><div class="section-head"><div><span class="eyebrow">${tr('工程要求','ENGINEERING REQUIREMENTS')} · ${tr('版本','REV.')} ${safe(requirementSet.revision)}</span><h3>${safe(name)}</h3><p>${evaluation?`${evalStatus(status)} · ${tr('本次结果适用','Applicable')} ${summary.applicable_count||0}/${summary.configured_count||rows.length} ${tr('项','')} · ${tr('未满足的必须指标','failed required metrics')} ${summary.hard_fail_count||0} · ${tr('预警','warnings')} ${summary.warning_count||0}`:tr(`已定义 ${rows.length} 项要求，求解完成后自动判定。`,`${rows.length} requirement(s) configured; evaluation runs automatically after solving.`)}</p></div><div class="actions"><span class="status ${evaluation?.formal_requirement_qualified?'formal':evaluation?.status==='BLOCKED'?'blocked':'review'}">${safe(evalStatus(status))}</span><button type="button" data-edit-engineering-requirements>${tr('编辑要求','Edit requirements')}</button></div></div><div class="requirements-rule-strip">${rows.slice(0,8).map(r=>`<span class="${String(r.kind||'monitor').toLowerCase()}"><b>${safe(r.label)}</b><small>${kindLabel(r.kind)}${r.kind==='MONITOR'?'':` · ${opLabel(r.operator)} ${r.limit!=null?safe(r.limit):r.lower!=null?`${safe(r.lower)}–${safe(r.upper)}`:''} ${safe(r.unit||'')}`}</small></span>`).join('')}</div><footer><small>${tr('判定规则：','Decision rules: ')}${policy.formal_result_required===false?tr('允许非正式结果；','non-formal results allowed; '):tr('必须使用正式结果；','formal results required; ')}${policy.missing_hard_constraint_blocks===false?tr('缺失指标可继续判定。','missing required metrics do not block.') : tr('必须指标缺失时判定不完整。','missing required metrics block the formal decision.')}</small></footer></article>`;
  }

  function rowHtml(row={}){
    const id=row.metric_id||'shaft_torque_nm',meta=metricMeta(id),kind=row.kind||meta.kind,op=row.operator||meta.operator;
    return `<article class="requirements-editor-row" data-requirement-row>
      <div class="requirement-metric-block"><label>${tr('指标','Metric')}<select data-req-metric>${catalog.map(m=>`<option value="${safe(m.id)}" ${m.id===id?'selected':''}>${safe(m.label)}</option>`).join('')}</select></label><small class="requirement-metric-id" data-req-metric-id>${safe(id)}</small><p data-req-metric-description>${safe(meta.description||tr('该指标来自当前项目可提取的结果目录。','This metric comes from the project result registry.'))}</p></div>
      <label>${tr('用途','Purpose')}<select data-req-kind><option ${kind==='HARD_CONSTRAINT'?'selected':''} value="HARD_CONSTRAINT">${tr('必须满足','Required')}</option><option ${kind==='OBJECTIVE'?'selected':''} value="OBJECTIVE">${tr('优化方向','Optimization target')}</option><option ${kind==='WARNING'?'selected':''} value="WARNING">${tr('预警线','Warning')}</option><option ${kind==='MONITOR'?'selected':''} value="MONITOR">${tr('仅观察','Monitor')}</option></select></label>
      <label><span data-req-op-label>${tr('判定方式','Rule')}</span><select data-req-op><option value="GE" ${op==='GE'?'selected':''}>${tr('不低于（≥）','At least (≥)')}</option><option value="LE" ${op==='LE'?'selected':''}>${tr('不高于（≤）','At most (≤)')}</option><option value="BETWEEN" ${op==='BETWEEN'?'selected':''}>${tr('介于范围内','Within range')}</option></select></label>
      <label data-limit-field>${tr('阈值','Threshold')}<input data-req-limit type="number" step="any" value="${row.limit??''}" placeholder="${tr('输入数值','Enter value')}"></label>
      <label data-lower-field>${tr('下限','Lower')}<input data-req-lower type="number" step="any" value="${row.lower??''}"></label>
      <label data-upper-field>${tr('上限','Upper')}<input data-req-upper type="number" step="any" value="${row.upper??''}"></label>
      <label>${tr('单位','Unit')}<input data-req-unit value="${safe(row.unit??meta.unit)}" readonly title="${tr('单位来自结果指标目录','Unit comes from the result registry')}"></label>
      <label data-warning-field>${tr('预警范围 %','Warning band %')}<input data-req-warning type="number" min="0" max="100" step="0.1" value="${row.warning_band_percent??5}"></label>
      <button type="button" class="danger-quiet" data-remove-requirement aria-label="${tr('删除指标','Remove metric')}">${tr('删除','Remove')}</button>
    </article>`;
  }

  function updateRowState(row){
    const metric=q('[data-req-metric]',row),meta=metricMeta(metric.value),kind=q('[data-req-kind]',row).value,op=q('[data-req-op]',row).value;
    const isObjective=kind==='OBJECTIVE',isRule=kind==='HARD_CONSTRAINT'||kind==='WARNING',isMonitor=kind==='MONITOR';
    q('[data-req-metric-id]',row).textContent=metric.value;
    q('[data-req-metric-description]',row).textContent=meta.description||tr('该指标来自当前项目可提取的结果目录。','This metric comes from the project result registry.');
    const opLabelNode=q('[data-req-op-label]',row);if(opLabelNode)opLabelNode.textContent=isObjective?tr('优化方向','Direction'):tr('判定方式','Rule');
    const opSelect=q('[data-req-op]',row);
    if(isObjective){opSelect.options[0].textContent=tr('越大越好','Maximize');opSelect.options[1].textContent=tr('越小越好','Minimize');opSelect.options[2].textContent=tr('接近目标值','Target value')}
    else{opSelect.options[0].textContent=tr('不低于（≥）','At least (≥)');opSelect.options[1].textContent=tr('不高于（≤）','At most (≤)');opSelect.options[2].textContent=tr('介于范围内','Within range')}
    opSelect.disabled=isMonitor;
    const limit=q('[data-req-limit]',row),lower=q('[data-req-lower]',row),upper=q('[data-req-upper]',row),warning=q('[data-req-warning]',row);
    const targetObjective=isObjective&&op==='BETWEEN';
    const singleLimit=isRule&&op!=='BETWEEN';
    limit.disabled=!(singleLimit||targetObjective);q('[data-limit-field]',row).classList.toggle('disabled-field',limit.disabled);
    lower.disabled=!(isRule&&op==='BETWEEN');upper.disabled=lower.disabled;q('[data-lower-field]',row).classList.toggle('disabled-field',lower.disabled);q('[data-upper-field]',row).classList.toggle('disabled-field',upper.disabled);
    warning.disabled=!(kind==='HARD_CONSTRAINT'||kind==='WARNING');q('[data-warning-field]',row).classList.toggle('disabled-field',warning.disabled);
  }

  async function openEditor(projectId,onRefresh){
    const [payload,catalogPayload]=await Promise.all([
      api(`/api/projects/${encodeURIComponent(projectId)}/requirements`),
      api(`/api/projects/${encodeURIComponent(projectId)}/requirements/metric-catalog`).catch(()=>({items:[]}))
    ]),current=payload.requirements||null;
    const dynamic=(catalogPayload.items||[]).map(item=>{const hint=fallbackHint(item.metric_id);return {id:item.metric_id,label:item.label||hint.label,unit:item.unit??hint.unit,operator:hint.operator,kind:hint.kind,description:item.description||hint.description||'',group:item.engineering_group||hint.group||'',favorable_direction:item.favorable_direction||''}});
    const existing=(current?.requirements||[]).map(item=>{const hint=fallbackHint(item.metric_id);return {id:item.metric_id,label:item.label||hint.label,unit:item.unit||hint.unit,operator:item.operator||hint.operator,kind:item.kind||hint.kind,description:hint.description||'',group:hint.group||''}});
    const byId=new Map([...defaultCatalog,...dynamic,...existing].map(row=>[row.id,row]));catalog=[...byId.values()].sort((a,b)=>String(a.group||'').localeCompare(String(b.group||''),'zh')||String(a.label).localeCompare(String(b.label),'zh'));
    q('#engineeringRequirementsEditor')?.remove();
    const overlay=document.createElement('div');overlay.id='engineeringRequirementsEditor';overlay.className='requirements-editor-overlay';
    const requirements=current?.requirements||[];const policy=current?.decision_policy||{};const currentName=(current?.name==='Project engineering requirements'&&lang()==='zh')?'项目工程要求':(current?.name||tr('项目工程要求','Project engineering requirements'));
    overlay.innerHTML=`<section class="requirements-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="requirementsEditorTitle">
      <header><div><span class="eyebrow">${tr('工程验收要求','ENGINEERING REQUIREMENTS')}</span><h2 id="requirementsEditorTitle">${tr('定义项目工程要求','Define project engineering requirements')}</h2><p>${tr('定义这个项目必须达到的性能边界。求解完成后，系统会自动把计算结果与这些要求逐项对照，并给出“满足、未满足或证据不完整”的结论。','Define the performance boundaries for this project. After solving, results are evaluated against these requirements automatically.')}</p></div><button type="button" data-close-requirements>${tr('关闭','Close')}</button></header>
      <div class="requirements-editor-guide"><div><b>1 · ${tr('选择指标','Choose metrics')}</b><span>${tr('例如转矩、效率、损耗和温度。','Torque, efficiency, losses and temperatures.')}</span></div><div><b>2 · ${tr('定义判定方式','Set the rule')}</b><span>${tr('必须满足、优化方向、预警线或仅观察。','Required, optimization target, warning or monitor.')}</span></div><div><b>3 · ${tr('保存版本','Save a revision')}</b><span>${tr('后续结果始终记录使用的是哪一版要求。','Every result keeps the exact requirement revision used.')}</span></div></div>
      <div class="requirements-editor-meta"><label>${tr('要求集名称','Requirement set name')}<input data-req-name value="${safe(currentName)}"></label><div class="requirement-version-card"><span>${tr('本次保存','This save')}</span><b>${tr('版本','Version')} ${safe((current?.revision||0)+1)}</b><small>${tr('保存后形成不可变版本，可继续创建下一版。','Saved revisions are immutable; create a new revision for later changes.')}</small></div></div>
      <section class="requirements-editor-core-policy"><div class="requirements-editor-head"><div><h3>${tr('基本判定规则','Basic decision rules')}</h3><p>${tr('推荐保持默认值。只有明确知道项目验收逻辑时再修改。','Keeping the defaults is recommended unless the project acceptance policy requires otherwise.')}</p></div></div><div class="requirements-policy-grid"><label><input type="checkbox" data-policy-formal ${policy.formal_result_required!==false?'checked':''}><span><b>${tr('只使用正式结果进行验收','Require formal results')}</b><small>${tr('结果可信度不足时，只允许查看，不给出正式达标结论。','If result trust is insufficient, allow review but no formal pass/fail decision.')}</small></span></label><label><input type="checkbox" data-policy-missing ${policy.missing_hard_constraint_blocks!==false?'checked':''}><span><b>${tr('必须指标缺失时判定不完整','Missing required metrics block the decision')}</b><small>${tr('避免在关键结果没有提取时误判为通过。','Prevents a pass when required outputs are missing.')}</small></span></label><label><input type="checkbox" data-policy-unit ${policy.unit_mismatch_blocks!==false?'checked':''}><span><b>${tr('单位不一致时停止判定','Unit mismatch blocks the decision')}</b><small>${tr('要求值和结果值必须使用兼容单位。','Requirement and result units must be compatible.')}</small></span></label></div></section>
      <div class="requirements-editor-head"><div><h3>${tr('工程指标','Engineering metrics')}</h3><p>${tr('“必须满足”决定设计是否达标；“优化方向”只用于比较和优化；“预警线”提示裕度；“仅观察”只显示数值。','Required metrics decide acceptance; optimization targets guide ranking; warnings manage margin; monitors are display-only.')}</p></div><button type="button" data-add-requirement>${tr('添加指标','Add metric')}</button></div>
      <div class="requirements-editor-rows" data-requirement-rows>${requirements.map(rowHtml).join('')||rowHtml()}</div>
      <details class="requirements-editor-advanced"><summary>${tr('高级判定规则与版本信息','Advanced decision rules and revision details')}</summary><div class="requirements-editor-policy"><label><input type="checkbox" data-policy-promotion ${policy.promotion_requires_requirement_qualification!==false?'checked':''}> ${tr('候选设计进入正式版本前必须通过工程要求','Require engineering qualification before candidate promotion')}</label><label><input type="checkbox" data-policy-warning ${policy.warning_blocks_promotion===true?'checked':''}> ${tr('预警项也阻止候选设计晋级','Warnings also block candidate promotion')}</label><label><input type="checkbox" data-policy-uncovered ${policy.uncovered_hard_constraint_blocks!==false?'checked':''}> ${tr('候选证据未覆盖必须指标时阻止晋级','Uncovered required metrics block candidate promotion')}</label></div><div class="requirements-revision-evidence"><span>${tr('当前版本','Current revision')} <b>${safe(current?.revision||0)}</b></span><span>${tr('版本指纹','Revision fingerprint')} <code>${safe(String(current?.content_hash||tr('尚未建立','Not created')).slice(0,16))}</code></span></div></details>
      <label class="requirements-editor-notes">${tr('版本说明（可选）','Revision note (optional)')}<textarea data-req-notes rows="2" placeholder="${tr('例如：根据额定工况验收要求调整最高温度上限','Example: adjusted maximum temperature for rated-condition acceptance')}"></textarea></label>
      <footer><div data-requirements-save-status aria-live="polite"></div><button type="button" data-close-requirements>${tr('取消','Cancel')}</button><button type="button" class="primary" data-save-requirements>${tr('保存新版本','Save new revision')}</button></footer>
    </section>`;
    document.body.appendChild(overlay);
    const rowsBox=q('[data-requirement-rows]',overlay);
    const bindRows=()=>{
      qa('[data-requirement-row]',rowsBox).forEach(row=>{
        updateRowState(row);
        q('[data-remove-requirement]',row).onclick=()=>{row.remove();if(!q('[data-requirement-row]',rowsBox))rowsBox.insertAdjacentHTML('beforeend',rowHtml());bindRows()};
        q('[data-req-metric]',row).onchange=()=>{const select=q('[data-req-metric]',row),meta=metricMeta(select.value),unit=q('[data-req-unit]',row);if(unit)unit.value=meta.unit||'';updateRowState(row)};
        q('[data-req-kind]',row).onchange=()=>updateRowState(row);q('[data-req-op]',row).onchange=()=>updateRowState(row);
      });
    };
    bindRows();q('[data-add-requirement]',overlay).onclick=()=>{rowsBox.insertAdjacentHTML('beforeend',rowHtml());bindRows()};qa('[data-close-requirements]',overlay).forEach(b=>b.onclick=()=>overlay.remove());
    q('[data-save-requirements]',overlay).onclick=async()=>{
      const status=q('[data-requirements-save-status]',overlay),button=q('[data-save-requirements]',overlay);button.disabled=true;status.textContent=tr('正在保存工程要求新版本…','Saving a new requirements revision…');
      try{
        const rules=qa('[data-requirement-row]',rowsBox).map((r,i)=>{const metric=q('[data-req-metric]',r).value,meta=metricMeta(metric),kind=q('[data-req-kind]',r).value,operator=q('[data-req-op]',r).value,limit=q('[data-req-limit]',r).value,lower=q('[data-req-lower]',r).value,upper=q('[data-req-upper]',r).value,direction=kind==='OBJECTIVE'?(operator==='GE'?'MAXIMIZE':operator==='LE'?'MINIMIZE':'TARGET'):'NONE';return {requirement_id:`REQ-${metric}-${i+1}`,metric_id:metric,label:meta.label,kind,operator:['HARD_CONSTRAINT','WARNING'].includes(kind)?operator:null,limit:((['HARD_CONSTRAINT','WARNING'].includes(kind)&&operator!=='BETWEEN')||(kind==='OBJECTIVE'&&direction==='TARGET'))&&limit!==''?Number(limit):null,lower:['HARD_CONSTRAINT','WARNING'].includes(kind)&&operator==='BETWEEN'&&lower!==''?Number(lower):null,upper:['HARD_CONSTRAINT','WARNING'].includes(kind)&&operator==='BETWEEN'&&upper!==''?Number(upper):null,unit:meta.unit||q('[data-req-unit]',r).value.trim(),direction,warning_band_percent:Number(q('[data-req-warning]',r).value||5),enabled:true,scope:{aggregation:'EACH'}}});
        const body={name:q('[data-req-name]',overlay).value.trim()||tr('项目工程要求','Project engineering requirements'),requirements:rules,decision_policy:{formal_result_required:q('[data-policy-formal]',overlay).checked,hard_constraints_must_all_pass:true,missing_hard_constraint_blocks:q('[data-policy-missing]',overlay).checked,unit_mismatch_blocks:q('[data-policy-unit]',overlay).checked,warning_blocks_promotion:q('[data-policy-warning]',overlay).checked,uncovered_hard_constraint_blocks:q('[data-policy-uncovered]',overlay).checked,promotion_requires_requirement_qualification:q('[data-policy-promotion]',overlay).checked,baseline_claims_require_formal_comparability:true,objective_policy:'INFORMATIVE'},notes:q('[data-req-notes]',overlay).value.trim(),expected_revision:current?.revision||0};
        await api(`/api/projects/${encodeURIComponent(projectId)}/requirements`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=tr('工程要求已保存','Requirements saved');if(typeof notify==='function')notify(tr('工程要求新版本已保存','New engineering requirements revision saved'),'SUCCESS');overlay.remove();await onRefresh?.();window.MCSDecisionCockpit?.refresh?.(projectId,{silent:true,force:true});
      }catch(error){button.disabled=false;status.textContent=`${tr('保存失败','Save failed')}：${error.message||error}`;if(typeof notify==='function')notify(error.message||String(error),'ERROR',9000)}
    };
  }

  function bind(host,{projectId,onRefresh}){qa('[data-edit-engineering-requirements]',host).forEach(b=>b.addEventListener('click',()=>openEditor(projectId,onRefresh)))}
  window.MCSEngineeringRequirements=Object.freeze({render,bind,openEditor,kindLabel,evalStatus});
})();
