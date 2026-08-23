/* V0.77 design parameter catalog. Capability-only module: no route/page ownership. */
(() => {
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function open(){
    const revision=state.workspaceRevision,solution=state.workspaceDesign;
    if(!revision||!solution)return toast('请选择电机 Revision','WARNING');
    const catalog=await api(`/api/model-revisions/${encodeURIComponent(revision.id)}/parameter-catalog?context=All`);
    const rows=(catalog.parameters||[]).filter(row=>row.writable);
    const groups=Object.entries(rows.reduce((acc,row)=>{(acc[row.category||'其他']??=[]).push(row);return acc},{}));
    if(!window.StudioDialog?.sheet)return toast('参数目录对话框尚未加载','WARNING');
    const result=await StudioDialog.sheet({
      title:`全部电机参数 · ${catalog.count||rows.length} 项`,width:'min(1180px,96vw)',
      html:`<div class="parameter-catalog-intro-v057"><b>按工程对象修改参数</b><p>保存后生成新的不可变 Motor Revision。分析与历史结果继续引用原 Revision。</p></div><div class="parameter-catalog-head-v040"><input data-parameter-search-v077 placeholder="搜索工程名称、用途或变量名"><select data-parameter-context-v077><option value="All">全部物理域</option><option value="EMag">电磁</option><option value="Therm">热</option><option value="Lab">性能图谱</option><option value="Mechanical">机械</option></select></div><div data-parameter-groups-v077 class="parameter-catalog-groups-v040">${groups.map(([group,items])=>`<details open><summary>${safe(group)} <span>${items.length}</span></summary><div class="parameter-table-v040">${items.map(row=>`<label data-parameter-row-v077 data-search="${safe(`${row.label} ${row.automation_name} ${row.description}`.toLowerCase())}" data-context="${safe(row.context||'All')}"><span><b>${safe(row.label||row.id)}</b><small>${safe(row.description||'')}</small><details><summary>技术信息</summary><code>${safe(row.automation_name||row.id)} · ${safe(row.context||'')}</code></details></span><div class="parameter-value-v057"><input data-parameter-id-v077="${safe(row.id)}" value="${safe(row.value??'')}" type="${['number','integer'].includes(row.type)?'number':'text'}" ${row.minimum!=null?`min="${safe(row.minimum)}"`:''} ${row.maximum!=null?`max="${safe(row.maximum)}"`:''} step="${row.type==='integer'?'1':'any'}"><em>${safe(row.unit||'')}</em></div></label>`).join('')}</div></details>`).join('')}</div>`,
      actions:[{label:'取消',value:null},{label:'保存为新 Motor Revision',primary:true,getValue:box=>{
        const updates={};for(const input of box.querySelectorAll('[data-parameter-id-v077]')){const row=rows.find(item=>String(item.id)===String(input.dataset.parameterIdV077));if(!row)continue;let value=input.value;if(['number','integer'].includes(row.type)){value=Number(value);if(!Number.isFinite(value))throw new Error(`${row.label||row.id} 请输入有效数值`);if(row.type==='integer'&&!Number.isInteger(value))throw new Error(`${row.label||row.id} 请输入整数`);if(row.minimum!=null&&value<Number(row.minimum))throw new Error(`${row.label||row.id} 不得小于 ${row.minimum}`);if(row.maximum!=null&&value>Number(row.maximum))throw new Error(`${row.label||row.id} 不得大于 ${row.maximum}`)}const equal=['number','integer'].includes(row.type)?Number(value)===Number(row.value):String(value)===String(row.value??'');if(!equal)updates[row.id]={row,value}}
        return updates;
      }}],
    });
    if(!result||!Object.keys(result).length)return;
    const parameters=Object.fromEntries(Object.entries(revision.parameters||{}).filter(([,value])=>value!==null&&value!=='')),automation=JSON.parse(JSON.stringify(revision.automation_parameters||{})),explicit=new Set(revision.explicit_parameter_ids||[]);
    for(const {row,value} of Object.values(result)){if(String(row.id).startsWith('automation:'))(automation[row.context]??={})[row.automation_name]=value;else{parameters[row.id]=value;explicit.add(row.id)}}
    const created=await api(`/api/solutions/${encodeURIComponent(solution.id)}/revisions`,{method:'POST',body:JSON.stringify({parameters,materials:revision.materials||{},explicit_parameter_ids:[...explicit],automation_parameters:automation,capability_snapshot:catalog.capability_snapshot,notes:`参数目录编辑：修改 ${Object.keys(result).length} 项，基于 Rev.${revision.revision}`})});
    toast(`已创建 Motor Revision Rev.${created.revision||''}`,'SUCCESS');
    if(window.MCSRouter?.navigate)await MCSRouter.navigate(`/app/projects/${encodeURIComponent(state.activeProjectId)}/designs/${encodeURIComponent(solution.id)}/revisions/${encodeURIComponent(created.id)}/geometry/radial`);
  }
  window.MCSDesignParameterCatalog=Object.freeze({open});
})();
