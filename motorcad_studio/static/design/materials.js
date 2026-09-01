/* Material assignment renderer. Template material defaults remain visible and replaceable in Draft mode. */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before material renderer');
  const {safe,viewData,authorityStrip}=U;
  const COPY={
    zh:{
      eyebrow:'电机对象 · 材料配置',title:'部件材料配置',description:'优先继承模板自身材料定义，通常无需逐项重选。只有需要替换某个部件时，点击该行“选择其他材料”。',
      assigned:'项已有材料',defaults:'项模板默认',applyPath:'应用材料的路径',applyGuide:'在部件行点击“选择其他材料” → 在材料库查看关键属性 / B-H / 退磁 / 损耗曲线 → 点击“用于当前部件”。草稿会自动保存。',
      component:'电机部件',material:'材料',source:'数据来源',apply:'应用',status:'状态',chooseOther:'选择其他材料',choose:'选择材料',nativeReadback:'原生回读',templateDefault:'模板默认',templateBaseline:'模板基线',modelInherited:'模型继承',versionFrozen:'版本冻结',modelReadback:'Motor-CAD 模型回读',templateMaterial:'模板材料',modelRevision:'Motor-CAD / 电机版本',section:'材料段',
      library:'Motor-CAD 材料工程数据库',currentDb:'当前模型 / 默认材料数据库',libraryHint:'材料库用于检索、曲线和原始属性管理；当前表用于把具体材料绑定到电机版本。',manageLibrary:'管理材料库 / 查看曲线',cooling:'冷却介质属于分析工况',coolingHint:'水 / 油 / 空气、入口温度、流量和对流边界在分析案例中配置，可对同一电机版本建立多个冷却方案。',analysis:'进入分析设置 →',inheritBaseline:'沿用 Motor-CAD 模型基线',configured:'已配置材料',nativeAuthority:'材料来自当前 Motor-CAD 模型回读；此处只读显示',revisionAuthority:'当前电机版本的部件材料；保存新版本时一并记录',
      stator:'定子铁心',rotor:'转子铁心',magnet:'永磁体',conductor:'绕组导体',shaft:'转轴',housing:'机壳',sleeve:'转子套筒'
    },
    en:{
      eyebrow:'MOTOR OBJECT · MATERIAL CONFIGURATION',title:'Component material configuration',description:'Template material definitions are inherited by default. Replace a component only when the design requires a different material.',
      assigned:'materials assigned',defaults:'template defaults',applyPath:'Material replacement workflow',applyGuide:'Choose “Select another material” on a component → review properties / B-H / demagnetization / loss curves → apply it to the current component. The draft is saved automatically.',
      component:'Motor component',material:'Material',source:'Data source',apply:'Apply',status:'Status',chooseOther:'Select another material',choose:'Select material',nativeReadback:'Native readback',templateDefault:'Template default',templateBaseline:'Template baseline',modelInherited:'Model inherited',versionFrozen:'Revision frozen',modelReadback:'Motor-CAD model readback',templateMaterial:'Template material',modelRevision:'Motor-CAD / motor revision',section:'Material section',
      library:'Motor-CAD engineering material database',currentDb:'Current model / default material database',libraryHint:'The library manages search, curves and source properties; this table binds concrete materials to the motor revision.',manageLibrary:'Manage material library / curves',cooling:'Cooling medium belongs to the analysis condition',coolingHint:'Water / oil / air, inlet temperature, flow rate and convection boundaries are configured in the analysis case. Multiple cooling schemes can use the same motor revision.',analysis:'Go to analysis setup →',inheritBaseline:'Use Motor-CAD model baseline',configured:'Material configured',nativeAuthority:'Materials are read back from the current Motor-CAD model; this view is read-only.',revisionAuthority:'Component materials of the current motor revision; they are recorded with a new revision.',
      stator:'Stator lamination',rotor:'Rotor lamination',magnet:'Magnet',conductor:'Winding conductor',shaft:'Shaft',housing:'Housing',sleeve:'Rotor sleeve'
    }
  };
  const language=()=>String(window.MCS_I18N?.language||document.documentElement.lang||'zh').toLowerCase().startsWith('en')?'en':'zh';
  const c=key=>COPY[language()][key]??COPY.zh[key]??key;
  const components=()=>[
    {key:'Stator Lamination',label:c('stator'),type:'Steel'},
    {key:'Rotor Lamination',label:c('rotor'),type:'Steel'},
    {key:'Magnet',label:c('magnet'),type:'Magnet'},
    {key:'Conductor',aliases:['Winding'],label:c('conductor'),type:'General'},
    {key:'Shaft',label:c('shaft'),type:'Steel'},
    {key:'Housing',label:c('housing'),type:'General'},
    {key:'Sleeve',label:c('sleeve'),type:'General'},
  ];
  function materialDisplayName(value){if(value===null||value===undefined||value==='')return c('inheritBaseline');if(typeof value!=='object')return String(value);return value.label||value.name||value.material||value.motorcad_name||c('configured')}
  function valueFor(values,row){if(values[row.key]!==undefined)return values[row.key];for(const alias of row.aliases||[])if(values[alias]!==undefined)return values[alias];return undefined}
  function originFor(provenance,row){if(provenance[row.key])return provenance[row.key];for(const alias of row.aliases||[])if(provenance[alias])return provenance[alias];return{}}
  function materialsView(ctx){
    const {data,editable,motorObject}=viewData(ctx),objectMaterials=motorObject?.materials||{},materials=data.materials||objectMaterials||{},objectComponents=Object.fromEntries(Object.entries(objectMaterials.components||{}).map(([key,value])=>[key,value?.material_name||value?.material||value])),values=materials.component_materials||materials.components||objectComponents||{},provenance=materials.material_provenance||{},inherited=materials.inherited_component_materials||{};
    const base=components(),known=new Set(base.flatMap(row=>[row.key,...(row.aliases||[])]));
    const defs=[...base,...Object.keys(values).filter(key=>!known.has(key)).map(key=>({key,label:key,type:''}))];
    const assigned=defs.filter(row=>valueFor(values,row)!==undefined&&valueFor(values,row)!==null&&valueFor(values,row)!=='').length;
    const inheritedCount=Object.keys(inherited).length;
    const rows=defs.map(row=>{
      const value=valueFor(values,row),origin=originFor(provenance,row),isNative=origin.source_kind==='motorcad_native_readback',isTemplate=!isNative&&(origin.source_kind==='template_mtt'||inherited[row.key]!==undefined),source=isNative?c('modelReadback'):origin.source_database_path||origin.source_database||origin.source_template_id||(isTemplate?c('templateMaterial'):c('modelRevision')),sectionHash=origin.material_section_hash||'';
      return`<tr><td><b>${safe(row.label)}</b><small>${safe(row.key)}</small></td><td><strong>${safe(materialDisplayName(value))}</strong>${isNative?`<small class="material-template-default-v066 native">${safe(c('nativeReadback'))}</small>`:isTemplate?`<small class="material-template-default-v066">${safe(c('templateDefault'))}</small>`:''}</td><td><span title="${safe(source)}">${safe(String(source).split(/[\\/]/).pop()||source)}</span>${sectionHash?`<small title="${safe(sectionHash)}">${safe(c('section'))} ${safe(String(sectionHash).slice(0,12))}…</small>`:''}</td><td>${editable?`<button type="button" class="material-apply-button-v066" data-workbench-material-component="${safe(row.key)}" data-material-type-v062="${safe(row.type)}">${safe(value?c('chooseOther'):c('choose'))}</button>`:`<span class="material-state-v031">${safe(isNative?c('nativeReadback'):isTemplate?c('templateBaseline'):value?c('versionFrozen'):c('modelInherited'))}</span>`}</td></tr>`;
    }).join('');
    return`<div class="motorcad-view-v031 materials-view-v031 materials-assignment-v062"><div class="visual-heading-v031"><div><span class="eyebrow">${safe(c('eyebrow'))}</span><h3>${safe(c('title'))}</h3><p>${safe(c('description'))}</p></div><div class="visual-facts-v031"><span>${assigned} ${safe(c('assigned'))}</span><span>${inheritedCount} ${safe(c('defaults'))}</span><span>${safe(motorObject?.topology_id||'motor')}</span></div></div>
      ${editable?`<div class="material-apply-guidance-v066"><b>${safe(c('applyPath'))}</b><span>${safe(c('applyGuide'))}</span></div>`:''}
      <div class="materials-table-v031"><table><thead><tr><th>${safe(c('component'))}</th><th>${safe(c('material'))}</th><th>${safe(c('source'))}</th><th>${safe(editable?c('apply'):c('status'))}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="materials-meta-v031 materials-library-entry-v061"><div><span>${safe(c('library'))}</span><b>${safe(materials.material_database_path||c('currentDb'))}</b><small>${safe(c('libraryHint'))}</small></div><button type="button" data-open-material-library-v061>${safe(c('manageLibrary'))}</button></div>
      <div class="analysis-boundary-v062"><div><b>${safe(c('cooling'))}</b><span>${safe(c('coolingHint'))}</span></div><button type="button" data-design-next-v061="input_data">${safe(c('analysis'))}</button></div>${authorityStrip(viewData(ctx).visualSource==='native'?c('nativeAuthority'):c('revisionAuthority'))}
    </div>`;
  }
  function render(view,ctx){return view==='materials'?materialsView(ctx):null}
  function rerenderForLanguage(){
    if(window.MCSDesignViewer?.state?.view==='materials')window.MCSDesignViewer.render?.();
    window.MCSDesignEditor?.refresh?.();
  }
  window.addEventListener('mcs-language-change',()=>requestAnimationFrame(rerenderForLanguage));
  window.MCSDesignMaterials={render,materialsView,get MATERIAL_COMPONENTS_V062(){return components()}};
})();
