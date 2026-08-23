/* Analysis Guidance Authority client: templates, smart defaults and revision-safe auto-fix. */
(() => {
  const esc=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const encode=value=>encodeURIComponent(String(value??''));
  function confidenceClass(value){const n=Number(value||0);return n>=.95?'high':n>=.8?'medium-high':n>=.6?'medium':'low'}
  function sourceLabel(source){return ({user_decision:'人工确认',motor_revision:'Motor Revision',mapping_baseline_template:'模型映射基线',derived_motor_revision:'Revision 推导',analysis_template:'分析模板',recipe_default:'配方默认',saved_analysis:'已保存 Analysis',input_domain_default:'物理输入域默认',unresolved:'待确认'})[source]||source||'-'}
  function compact(value){if(value===null||value===undefined||value==='')return '未配置';if(typeof value==='object'){if(value.configured&&value.field_count!==undefined)return `已配置 ${value.field_count} 个字段`;if(value.count!==undefined)return `${value.count} 项`;return '已配置'}return String(value)}
  function decisionControl(row){
    const unit=row.unit?`<span>${esc(row.unit)}</span>`:'';
    const min=row.minimum!==null&&row.minimum!==undefined?` min="${esc(row.minimum)}"`:'';const max=row.maximum!==null&&row.maximum!==undefined?` max="${esc(row.maximum)}"`:'';
    return `<label class="analysis-guidance-decision" data-guidance-decision="${esc(row.field_id)}"><div><b>${esc(row.label||row.field_id)}</b><small>${esc(sourceLabel(row.source))} · 置信度 ${esc(row.confidence_label||'-')}</small></div><div class="analysis-guidance-value"><input type="number" step="any"${min}${max} data-guidance-value="${esc(row.field_id)}" value="${esc(row.value??'')}">${unit}</div><p>${esc(row.reason||'')}</p></label>`;
  }
  function templateCard(row,active){
    const question=row.engineering_question||row.intent||'';const use=row.when_to_use||'';
    return `<button type="button" class="analysis-template-card ${active?'active':''} ${row.available?'':'unavailable'}" data-analysis-template="${esc(row.id)}" ${row.available?'':'disabled'}><header><span class="chip">${esc(row.module||'')}</span><span>${esc(row.expected_runtime||'')}</span></header><b>${esc(row.label||row.id)}</b><p>${esc(question)}</p>${use?`<small>${esc(use)}</small>`:''}<footer><span>${esc((row.engineering_groups||[]).join(' · ')||row.short_label||row.recipe_id||'')}</span><span>${row.available?'可用':esc(row.unavailable_reason||'不可用')}</span></footer></button>`;
  }
  function recommendationRow(row){
    const current=row.current_value;
    const display=current!==undefined&&current!==null&&current!==''?current:row.value;
    return `<div class="analysis-guidance-rec ${esc(row.status||'')}"><div><b>${esc(row.label||row.field_id)}</b><small>${esc(row.path||'')}</small></div><strong>${esc(display??'待确认')}${row.unit?` ${esc(row.unit)}`:''}</strong><span class="analysis-confidence ${confidenceClass(row.confidence)}">${esc(row.confidence_label||'-')}</span><p>${esc(row.reason||'')}</p></div>`;
  }
  function actionCard(row){
    const preview=(row.change_preview||[]).slice(0,4);const paths=(row.touched_paths||[]).slice(0,4);
    const changes=preview.length?`<div class="analysis-guidance-change-preview">${preview.map(item=>`<small><code>${esc(item.path)}</code><span>${esc(compact(item.before))} → ${row.can_apply?esc(compact(item.after)):'人工确认'}</span></small>`).join('')}</div>`:(paths.length?`<small>影响：${paths.map(esc).join(' · ')}</small>`:'');
    return `<div class="analysis-guidance-action ${row.can_apply?'applicable':'manual'}"><div><span class="chip">${esc(row.type||'')}</span><b>${esc(row.label||row.type)}</b><p>${esc(row.reason||'')}</p>${changes}</div>${row.can_apply&&row.changes?`<button type="button" data-analysis-autofix="${esc(row.id)}">应用并生成新 Revision</button>`:`<span class="analysis-guidance-manual">${row.can_apply?'已满足':'需要人工确认'}</span>`}</div>`;
  }
  async function listTemplates(api,revisionId){return api(`/api/analysis-templates${revisionId?`?design_revision_id=${encode(revisionId)}`:''}`)}
  async function preview(api,templateId,revisionId,decisions={}){return api(`/api/analysis-templates/${encode(templateId)}/preview`,{method:'POST',body:JSON.stringify({design_revision_id:revisionId,decisions})})}
  async function guidance(api,analysisId){return api(`/api/analysis-definitions/${encode(analysisId)}/guidance`)}
  async function applyAutoFix(api,analysisId,actionId,revisionId){return api(`/api/analysis-definitions/${encode(analysisId)}/auto-fix`,{method:'POST',body:JSON.stringify({action_id:actionId,expected_analysis_revision_id:revisionId})})}
  window.MCSAnalysisGuidance=Object.freeze({listTemplates,preview,guidance,applyAutoFix,decisionControl,templateCard,recommendationRow,actionCard,sourceLabel,confidenceClass});
})();
