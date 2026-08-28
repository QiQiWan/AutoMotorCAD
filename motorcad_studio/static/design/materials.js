/* V0.66 Material assignment renderer. Template material defaults are visible and directly replaceable in Draft mode. */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before material renderer');
  const {safe,viewData,authorityStrip}=U;
  const MATERIAL_COMPONENTS_V062=[
    {key:'Stator Lamination',label:'定子铁心',type:'Steel'},
    {key:'Rotor Lamination',label:'转子铁心',type:'Steel'},
    {key:'Magnet',label:'永磁体',type:'Magnet'},
    {key:'Conductor',aliases:['Winding'],label:'绕组导体',type:'General'},
    {key:'Shaft',label:'转轴',type:'Steel'},
    {key:'Housing',label:'机壳',type:'General'},
    {key:'Sleeve',label:'转子套筒',type:'General'},
  ];
  function materialDisplayName(value){if(value===null||value===undefined||value==='')return'沿用 Motor-CAD 模型基线';if(typeof value!=='object')return String(value);return value.label||value.name||value.material||value.motorcad_name||'已配置材料'}
  function valueFor(components,row){if(components[row.key]!==undefined)return components[row.key];for(const alias of row.aliases||[])if(components[alias]!==undefined)return components[alias];return undefined}
  function originFor(provenance,row){if(provenance[row.key])return provenance[row.key];for(const alias of row.aliases||[])if(provenance[alias])return provenance[alias];return{}}
  function materialsView(ctx){
    const {data,editable,motorObject}=viewData(ctx),objectMaterials=motorObject?.materials||{},materials=data.materials||objectMaterials||{},objectComponents=Object.fromEntries(Object.entries(objectMaterials.components||{}).map(([key,value])=>[key,value?.material_name||value?.material||value])),components=materials.component_materials||materials.components||objectComponents||{},provenance=materials.material_provenance||{},inherited=materials.inherited_component_materials||{};
    const known=new Set(MATERIAL_COMPONENTS_V062.flatMap(row=>[row.key,...(row.aliases||[])]));
    const defs=[...MATERIAL_COMPONENTS_V062,...Object.keys(components).filter(key=>!known.has(key)).map(key=>({key,label:key,type:''}))];
    const assigned=defs.filter(row=>valueFor(components,row)!==undefined&&valueFor(components,row)!==null&&valueFor(components,row)!=='').length;
    const inheritedCount=Object.keys(inherited).length;
    const rows=defs.map(row=>{
      const value=valueFor(components,row),origin=originFor(provenance,row),isNative=origin.source_kind==='motorcad_native_readback',isTemplate=!isNative&&(origin.source_kind==='template_mtt'||inherited[row.key]!==undefined),source=isNative?'Motor-CAD 模型回读':origin.source_database_path||origin.source_database||origin.source_template_id||(isTemplate?'模板材料':'Motor-CAD / 电机版本'),sectionHash=origin.material_section_hash||'';
      return`<tr><td><b>${safe(row.label)}</b><small>${safe(row.key)}</small></td><td><strong>${safe(materialDisplayName(value))}</strong>${isNative?'<small class="material-template-default-v066 native">Native 回读</small>':isTemplate?'<small class="material-template-default-v066">模板默认</small>':''}</td><td><span title="${safe(source)}">${safe(String(source).split(/[\\/]/).pop()||source)}</span>${sectionHash?`<small title="${safe(sectionHash)}">材料段 ${safe(String(sectionHash).slice(0,12))}…</small>`:''}</td><td>${editable?`<button type="button" class="material-apply-button-v066" data-workbench-material-component="${safe(row.key)}" data-material-type-v062="${safe(row.type)}">${value?'选择其他材料':'选择材料'}</button>`:`<span class="material-state-v031">${isNative?'Native 回读':isTemplate?'模板基线':value?'版本冻结':'模型继承'}</span>`}</td></tr>`;
    }).join('');
    return`<div class="motorcad-view-v031 materials-view-v031 materials-assignment-v062"><div class="visual-heading-v031"><div><span class="eyebrow">MOTOR OBJECT · MATERIAL PROJECTION</span><h3>部件材料配置</h3><p>优先继承模板自身材料定义，通常无需逐项重选。只有需要替换某个部件时，点击该行“选择其他材料”。</p></div><div class="visual-facts-v031"><span>${assigned} 项已有材料</span><span>${inheritedCount} 项模板默认</span><span>${safe(motorObject?.topology_id||'motor')}</span></div></div>
      ${editable?'<div class="material-apply-guidance-v066"><b>应用材料的路径</b><span>在部件行点击“选择其他材料” → 在材料库查看关键属性 / B-H / 退磁 / 损耗曲线 → 点击“用于当前部件”。草稿会自动保存。</span></div>':''}
      <div class="materials-table-v031"><table><thead><tr><th>电机部件</th><th>材料</th><th>数据来源</th><th>${editable?'应用':'状态'}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="materials-meta-v031 materials-library-entry-v061"><div><span>Motor-CAD 材料工程数据库</span><b>${safe(materials.material_database_path||'当前模型 / 默认材料数据库')}</b><small>材料库用于检索、曲线和原始属性管理；当前表用于把具体材料绑定到电机版本。</small></div><button type="button" data-open-material-library-v061>管理材料库 / 查看曲线</button></div>
      <div class="analysis-boundary-v062"><div><b>冷却介质属于分析工况</b><span>水 / 油 / 空气、入口温度、流量和对流边界在分析案例中配置，可对同一电机版本建立多个冷却方案。</span></div><button type="button" data-design-next-v061="input_data">进入分析设置 →</button></div>${authorityStrip(viewData(ctx).visualSource==='native'?'材料来自当前 Motor-CAD 模型回读；此处只读显示':'当前电机版本的部件材料；保存新版本时一并记录')}
    </div>`;
  }
  function render(view,ctx){return view==='materials'?materialsView(ctx):null}
  window.MCSDesignMaterials={render,materialsView,MATERIAL_COMPONENTS_V062};
})();
