/* V0.64 Parameter Inspector renderer shared by read-only Design Viewer and Draft editor. */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before parameter inspector');
  const {safe,fmt,parameterRecord}=U;
  const categoryIcon={topology:'◎',geometry:'◫',magnet:'N/S',winding:'∿'};
  function display(value){if(value===null||value===undefined||value==='')return'—';if(typeof value==='number'&&Number.isFinite(value))return Number(value.toPrecision(8)).toString();return String(value)}

  function readOnlyPanel(view,data,{selectedParameter=null}={}){
    const spec=(data.design_views||[]).find(row=>row.id===view)||{},ids=spec.parameter_ids||[],values=data.effective_parameters||{};
    if(['evidence','native','compare'].includes(view))return`<aside class="design-context-panel-v031"><span class="eyebrow">${view==='compare'?'辅助工具':'设计验证'}</span><h4>${safe(view==='evidence'?'模型检查与计算依据':spec.label||view)}</h4><p>${safe(spec.description||'')}</p><div class="context-rule-v031"><b>工程显示规则</b><span>${view==='compare'?'版本比较不改变设计。':'先完成 Studio 约束检查，再以 Motor-CAD 原生模型检查作为计算前证据。'}</span></div></aside>`;
    if(view==='materials')return`<aside class="design-context-panel-v031"><span class="eyebrow">材料配置</span><h4>当前电机部件材料</h4><p>定子、转子、永磁体、绕组、转轴和机壳材料随 Design Revision 冻结；冷却介质进入分析设置。</p><div class="context-rule-v031"><b>数据追溯</b><span>材料库记录 Motor-CAD 数据库路径、文件哈希、材料段哈希和材料记录来源。</span></div><button type="button" class="primary edit-view-v031" data-edit-view-v031="materials">编辑材料配置</button></aside>`;
    return`<aside class="design-context-panel-v031"><div class="context-panel-head-v031"><div><span class="eyebrow">当前视图参数</span><h4>${safe(spec.label||view)}</h4></div><span>${ids.length}</span></div><p>${safe(spec.description||'')}</p><div class="context-param-list-v031">${ids.map(id=>{const row=parameterRecord(data,id),issue=(data.precheck?.issues||[]).some(item=>(item.parameter_ids||[]).includes(id));return row?`<button type="button" data-design-parameter-v031="${safe(id)}" class="${selectedParameter===id?'selected':''} ${issue?'has-issue':''}" title="${safe(row.description||row.label)}"><span><b>${safe(row.label)}</b><small>${safe(row.description||row.category_label||'设计参数')}</small></span><em>${fmt(values[id])} ${safe(row.unit||'')}</em></button>`:''}).join('')}</div><button type="button" class="primary edit-view-v031" data-edit-view-v031="${safe(view)}" ${ids.length?'':'disabled'}>编辑设计</button><small class="context-footnote-v031">当前版本只读；编辑会进入自动保存草稿，确认后创建新的不可变设计版本。</small></aside>`;
  }

  function editorGroupButtons({data,group,changed=new Set(),filter=''}){
    const needle=String(filter||'').trim().toLowerCase();
    return(data?.groups||[]).map(row=>{
      const rows=(data?.parameters||[]).filter(p=>p.category===row.id);
      const matches=!needle||rows.some(p=>`${p.label} ${p.id} ${(p.motorcad_candidates||[]).join(' ')}`.toLowerCase().includes(needle));
      if(!matches)return'';
      const changedCount=rows.filter(p=>changed.has(p.id)).length;
      return`<button type="button" class="workbench-group-btn-v024 ${group===row.id?'active':''}" data-workbench-group="${safe(row.id)}"><span class="group-icon-v024">${safe(categoryIcon[row.id]||'•')}</span><span><b>${safe(row.label)}</b><small>${rows.length} 个参数${changedCount?` · ${changedCount} 项已改`:''}</small></span></button>`;
    }).join('');
  }

  function editorRegionButtons({data}){
    return Object.entries(data?.regions||{}).map(([id,row])=>`<button type="button" data-workbench-region="${safe(id)}"><span>${safe(row.label||id)}</span><small>${(row.parameter_ids||[]).filter(pid=>parameterRecord(data,pid)).length} 参数</small></button>`).join('');
  }

  function editorParameterRows({data,group,values={},changed=new Set(),selected=null}){
    const rows=(data?.parameters||[]).filter(row=>row.category===group);
    return rows.map(row=>{
      const isChanged=changed.has(row.id),isSelected=selected===row.id;
      return`<article class="workbench-param-row-v024 ${isChanged?'changed':''} ${isSelected?'selected':''}" data-workbench-param-row="${safe(row.id)}"><button type="button" class="workbench-param-focus-v024" data-workbench-select="${safe(row.id)}"><span><b>${safe(row.label)}</b><small>${safe(row.description||'修改后立即更新模型预览')}</small></span><em>${row.explicit?'已单独设置':'采用模板值'}</em></button><div class="workbench-param-control-v024"><input aria-label="${safe(row.label)}" data-workbench-input="${safe(row.id)}" type="number" step="${row.type==='integer'?'1':'any'}" ${row.minimum!==null&&row.minimum!==undefined?`min="${safe(row.minimum)}"`:''} ${row.maximum!==null&&row.maximum!==undefined?`max="${safe(row.maximum)}"`:''} value="${safe(display(values[row.id]))}"><span>${safe(row.unit||'')}</span></div><div class="workbench-param-lineage-v024"><span>模板值 ${safe(display(row.template_default))}</span><span>上一可行值 ${safe(display(row.previous_feasible_value))}</span></div><div class="workbench-param-actions-v024"><button type="button" data-workbench-restore="previous" data-param-id="${safe(row.id)}" ${row.previous_feasible_value===undefined?'disabled':''}>恢复上一可行值</button><button type="button" data-workbench-restore="template" data-param-id="${safe(row.id)}" ${row.template_default===undefined?'disabled':''}>恢复模板值</button></div></article>`;
    }).join('')||'<div class="workspace-empty compact">当前分组没有可编辑设计参数。</div>';
  }

  function editorSelectedCard({data,values={},selected=null}){
    const row=parameterRecord(data,selected),dep=selected?data?.dependencies?.[selected]||{}:{};
    if(!row)return'<span class="eyebrow">参数联动</span><h3>选择一个参数</h3><p>点击参数、模型部件或错误条目，这里会显示影响范围和可恢复基线。</p>';
    const related=(dep.related||[]).filter(id=>parameterRecord(data,id));
    return`<span class="eyebrow">当前参数</span><h3>${safe(row.label)}</h3><p>${safe(row.description||dep.component||'')}</p><div class="selected-value-v024"><span>当前值</span><b>${safe(display(values[row.id]))} ${safe(row.unit||'')}</b></div><div class="dependency-chain-v024"><b>${safe(dep.component||'工程影响')}</b>${(dep.affects||[]).map(x=>`<span>→ ${safe(x)}</span>`).join('')||'<span>当前没有额外联动项</span>'}</div><div class="property-grid"><span>模板值</span><b>${safe(display(row.template_default))} ${safe(row.unit||'')}</b><span>上一可行值</span><b>${safe(display(row.previous_feasible_value))} ${safe(row.unit||'')}</b></div>${related.length?`<div class="related-params-v024"><b>关联参数</b>${related.map(id=>`<button type="button" data-workbench-select="${safe(id)}">${safe(parameterRecord(data,id)?.label||id)}</button>`).join('')}</div>`:''}`;
  }

  window.MCSDesignParameterInspector={readOnlyPanel,editorGroupButtons,editorRegionButtons,editorParameterRows,editorSelectedCard,display};
})();
