/* V0.88-E Design renderer facade.
 * Geometry/winding/material renderers still own topology-specific SVG/table markup.
 * This facade owns the Design Intent <-> Motor-CAD Native visualization source contract
 * and the side-by-side reconciliation view. Native values are consumed only from the
 * lineage-qualified NativeModelSnapshot preview projection.
 */
(() => {
  const safe=value=>window.MCSDesignRenderUtils?.safe?.(value)??String(value??'');
  const same=(a,b)=>{const x=Number(a),y=Number(b);if(a!==null&&a!==''&&b!==null&&b!==''&&Number.isFinite(x)&&Number.isFinite(y))return Math.abs(x-y)<=1e-9+1e-7*Math.max(Math.abs(x),Math.abs(y),1);return String(a??'')===String(b??'')};
  const fmt=value=>window.MCSDesignRenderUtils?.fmt?.(value)??String(value??'—');

  function rawRender(view,ctx){
    const geometry=window.MCSDesignGeometry?.render?.(view,ctx);if(geometry!==null&&geometry!==undefined)return geometry;
    const winding=window.MCSDesignWinding?.render?.(view,ctx);if(winding!==null&&winding!==undefined)return winding;
    const materials=window.MCSDesignMaterials?.render?.(view,ctx);if(materials!==null&&materials!==undefined)return materials;
    return null;
  }

  function materialProjection(projection){
    const native=projection?.materials||{},component_materials={},native_component_readbacks={};
    Object.entries(native).forEach(([component,raw])=>{const map=raw&&typeof raw==='object'?raw:{};native_component_readbacks[component]=map;const values=[...new Set(Object.values(map).filter(v=>v!==null&&v!==undefined&&v!=='').map(String))];if(values.length===1)component_materials[component]=values[0];else if(values.length)component_materials[component]=values.join(' / ')});
    return{component_materials,native_component_readbacks,material_provenance:Object.fromEntries(Object.keys(native_component_readbacks).map(key=>[key,{source_kind:'motorcad_native_readback',native_components:Object.keys(native_component_readbacks[key])}]))};
  }

  function runtimeReconciliation(data,nativeRecord=null){
    const base={...(data?.visualization_reconciliation||{})};
    const record=nativeRecord||{};const projection=record.native_preview_projection||null;
    if(!projection)return base;
    const design={...(data?.effective_parameters||{})},nativeParams={...(projection.parameters||{})},nativeEffective={...design,...nativeParams};
    const lookup=new Map((data?.parameters||[]).map(row=>[row.id,row]));
    const diffs=Object.entries(nativeParams).map(([id,nativeValue])=>{const row=lookup.get(id)||{},designValue=design[id],delta=Number.isFinite(Number(nativeValue))&&Number.isFinite(Number(designValue))?Number(nativeValue)-Number(designValue):null;return{semantic_id:id,label:row.label||id,unit:row.unit||'',category:row.category||'other',design_value:designValue,native_value:nativeValue,delta,status:same(designValue,nativeValue)?'MATCH':'DELTA'}});
    const nw=projection.winding||{},nativeWinding={...(data?.winding_design||{}),phase_count:nw.phase_count??data?.winding_design?.phase_count,parallel_paths:nw.parallel_paths??data?.winding_design?.parallel_paths,turns_per_coil:nw.turns_per_coil??data?.winding_design?.turns_per_coil,layers:nw.layers??data?.winding_design?.layers,slot_fill_factor:nw.slot_fill_factor??data?.winding_design?.slot_fill_factor,path_type:nw.path_type||data?.winding_design?.path_type,coil_table:nw.coils||[],definition_status:'NATIVE_MODEL_SNAPSHOT',definition_authority:'NativePreviewReconciliationAuthorityV1',native_signature:nw.signature};
    const nativeStatus=String(record.native_model_status||projection.status||'UNAVAILABLE').toUpperCase(),status=String(record.status||'UNCHECKED').toUpperCase();
    const renderAllowed=Boolean(projection.lineage_complete&&(Object.keys(nativeParams).length||Object.keys(projection.materials||{}).length||(nw.coils||[]).length));
    return{...base,authority:'NativePreviewReconciliationAuthorityV1',status:status==='CURRENT'&&nativeStatus==='QUALIFIED'?'NATIVE_CURRENT':`NATIVE_${nativeStatus}`,default_source:status==='CURRENT'&&nativeStatus==='QUALIFIED'?'native':'design',native_render_allowed:renderAllowed,native_authoritative:status==='CURRENT'&&nativeStatus==='QUALIFIED'&&Boolean(projection.qualified_for_native_preview),compare_allowed:renderAllowed,native_projection:projection,native_spatial_geometry:projection.spatial_geometry||{},native_spatial_geometry_status:projection.spatial_geometry?.status||'UNAVAILABLE',native_spatial_geometry_hash:projection.spatial_geometry?.content_hash||null,native_spatial_render_allowed:Boolean((projection.spatial_geometry?.regions||[]).length),native_parameters:nativeParams,native_effective_parameters:nativeEffective,native_winding_design:nativeWinding,native_materials:materialProjection(projection),diffs,changed_diffs:diffs.filter(row=>row.status!=='MATCH'),source:{kind:'editor_native_check',phase:record.native_preview_phase||projection.source_phase,snapshot_hash:record.native_preview_snapshot_hash||record.native_model_snapshot_hash,design_state_hash:record.native_model_design_state_hash,checked_at:record.checked_at},coverage:{native_parameter_count:Object.keys(nativeParams).length,comparable_parameter_count:diffs.length,changed_parameter_count:diffs.filter(row=>row.status!=='MATCH').length,winding_coil_count:(nw.coils||[]).length,material_component_count:Object.keys(projection.materials||{}).length,spatial_region_count:Number(projection.spatial_geometry?.drawable_region_count||0),spatial_entity_count:Number(projection.spatial_geometry?.entity_count||0)}};
  }

  function resolveVisualSource(recon,requested='auto',mode='read'){
    const token=String(requested||'auto');
    if(token==='compare')return recon?.compare_allowed?'compare':'design';
    if(token==='native')return recon?.native_render_allowed?'native':'design';
    if(token==='design')return'design';
    if(mode==='edit')return'design';
    return recon?.default_source==='native'&&recon?.native_render_allowed?'native':'design';
  }

  function toolbar(data,{source='auto',mode='read',reconciliation=null}={}){
    const recon=reconciliation||data?.visualization_reconciliation||{},effective=resolveVisualSource(recon,source,mode),nativeOK=Boolean(recon.native_render_allowed),compareOK=Boolean(recon.compare_allowed);const status=String(recon.status||'DESIGN_ONLY');
    const label=recon.native_authoritative?'原生模型已对齐':status.includes('DRIFT')?'原生模型存在差异':status.includes('PARTIAL')?'原生证据不完整':status==='STALE_NATIVE_EVIDENCE'?'原生证据已过期':'当前使用设计意图';
    const sourceMeta=recon.source||{},hash=sourceMeta.design_state_hash||sourceMeta.snapshot_hash||'',geometryEvidence=recon.native_projection?.geometry_evidence||{},regionCount=(geometryEvidence.region_names||[]).length;
    return`<div class="visual-reconciliation-toolbar-v088e" data-visual-source-current="${safe(effective)}"><div class="visual-source-switch-v088e" role="group" aria-label="设计与 Motor-CAD 可视化来源"><button type="button" data-visual-source-v088e="design" class="${effective==='design'?'active':''}">设计意图</button><button type="button" data-visual-source-v088e="native" class="${effective==='native'?'active':''}" ${nativeOK?'':'disabled'}>Motor-CAD 原生</button><button type="button" data-visual-source-v088e="compare" class="${effective==='compare'?'active':''}" ${compareOK?'':'disabled'}>差异对比</button></div><div class="visual-source-status-v088e ${recon.native_authoritative?'current':status.includes('DRIFT')?'drift':status.includes('PARTIAL')?'partial':'design'}"><span>显示依据</span><b>${safe(label)}</b><small>${sourceMeta.phase?safe(String(sourceMeta.phase).replaceAll('_',' ')):nativeOK?'NativeModelSnapshot':'Studio parameter model'}${hash?` · State ${safe(String(hash).slice(0,10))}`:''}${regionCount?` · GeometryTree ${regionCount} regions`:''}</small></div></div>`;
  }

  function relevantDiffs(view,data,recon){
    const all=recon?.diffs||[],spec=(data?.design_views||[]).find(row=>row.id===view),ids=new Set(spec?.parameter_ids||[]);
    if(view==='winding'||view==='slot')return all.filter(row=>row.category==='winding'||ids.has(row.semantic_id));
    if(view==='materials')return[];
    if(ids.size)return all.filter(row=>ids.has(row.semantic_id));
    return all;
  }

  function diffSummary(view,data,recon){
    if(!recon?.compare_allowed)return'';
    const rows=relevantDiffs(view,data,recon),changed=rows.filter(row=>row.status!=='MATCH');const materialDesign=data?.materials?.component_materials||{},materialNative=recon?.native_materials?.component_materials||{};
    const materialDiffs=view==='materials'?[...new Set([...Object.keys(materialDesign),...Object.keys(materialNative)])].map(id=>({semantic_id:id,label:id,unit:'',design_value:materialDesign[id],native_value:materialNative[id],status:same(materialDesign[id],materialNative[id])?'MATCH':'DELTA'})).filter(row=>row.status!=='MATCH'):[];
    const display=[...changed,...materialDiffs];
    return`<div class="visual-diff-summary-v088e"><div><span>Design ↔ Native 差异</span><b>${display.length?`${display.length} 项需要关注`:'当前可比参数一致'}</b><small>差异只来自同一 Design Snapshot 的 Motor-CAD 回读；未回读字段继续显示 Design Intent。</small></div>${display.length?`<div class="visual-diff-list-v088e">${display.slice(0,12).map(row=>`<span><b>${safe(row.label||row.semantic_id)}</b><em>${safe(fmt(row.design_value))}${row.unit?` ${safe(row.unit)}`:''} → ${safe(fmt(row.native_value))}${row.unit?` ${safe(row.unit)}`:''}</em></span>`).join('')}${display.length>12?`<span><b>另有 ${display.length-12} 项</b><em>在参数总览中查看完整差异</em></span>`:''}</div>`:''}</div>`;
  }


  function nativeSpatialGeometryCard(view,ctx,recon,source){
    if(source!=='native'||view!=='radial')return'';
    const spatial=recon?.native_spatial_geometry||recon?.native_projection?.spatial_geometry||{};
    if(!['COMPLETE','PARTIAL'].includes(String(spatial.status||'').toUpperCase())||!(spatial.regions||[]).length)return'';
    const raw=[];(spatial.regions||[]).forEach(region=>(region.entities||[]).forEach(entity=>(entity.display_points||[]).forEach(point=>{const x=Number(point?.[0]),y=Number(point?.[1]);if(Number.isFinite(x)&&Number.isFinite(y))raw.push([x,y])})));
    if(!raw.length)return'';const b=spatial.bounds||{xmin:Math.min(...raw.map(p=>p[0])),xmax:Math.max(...raw.map(p=>p[0])),ymin:Math.min(...raw.map(p=>p[1])),ymax:Math.max(...raw.map(p=>p[1]))};const w=820,h=460,pad=28,px=x=>pad+(x-Number(b.xmin))/(Number(b.xmax)-Number(b.xmin)||1)*(w-pad*2),py=y=>h-pad-(y-Number(b.ymin))/(Number(b.ymax)-Number(b.ymin)||1)*(h-pad*2);
    const paths=(spatial.regions||[]).map(region=>{const entities=(region.entities||[]).map(entity=>{const pts=(entity.display_points||[]).filter(point=>Number.isFinite(Number(point?.[0]))&&Number.isFinite(Number(point?.[1])));return pts.length>1?`<polyline points="${pts.map(point=>`${px(Number(point[0])).toFixed(2)},${py(Number(point[1])).toFixed(2)}`).join(' ')}"/>`:''}).join('');return entities?`<g><title>${safe(region.name||'Region')}${region.material?` · ${safe(region.material)}`:''}</title>${entities}</g>`:''}).join('');
    return`<section class="native-spatial-preview-v088f"><header><div><span>Motor-CAD 原生几何</span><b>原生区域边界</b></div><small>${safe(spatial.status)} · ${Number(spatial.drawable_region_count||0)} 个区域 · ${Number(spatial.entity_count||0)} 个几何元素 · ${safe(String(spatial.content_hash||'').slice(0,12))}</small></header><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Motor-CAD GeometryTree 原生区域边界"><rect x="${pad}" y="${pad}" width="${w-pad*2}" height="${h-pad*2}"/><g>${paths}</g></svg><footer>当前图形来自 Motor-CAD 原生几何边界；下方工程视图用于参数化解释。</footer></section>`;
  }

  function renderWorkbenchView(view,ctx){
    const recon=ctx.visualizationReconciliation||ctx.data?.visualization_reconciliation||{},source=resolveVisualSource(recon,ctx.visualSource||'design',ctx.editable?'edit':'read');
    if(source!=='compare'){const rendered=rawRender(view,{...ctx,visualSource:source,visualizationReconciliation:recon});return`${nativeSpatialGeometryCard(view,ctx,recon,source)}${rendered||''}`}
    const design=rawRender(view,{...ctx,visualSource:'design',visualizationReconciliation:recon});
    const native=rawRender(view,{...ctx,visualSource:'native',visualizationReconciliation:recon});
    return`<div class="visual-reconciliation-compare-v088e"><section><header><span>设计参数</span><b>当前设计参数</b></header>${design||''}</section><section><header><span>Motor-CAD 原生模型</span><b>${safe(recon.source?.phase||'NativeModelSnapshot')}</b></header>${nativeSpatialGeometryCard(view,ctx,recon,'native')}${native||''}</section></div>${diffSummary(view,ctx.data,recon)}`;
  }
  function renderAuxiliaryView(view,data){return window.MCSDesignValidation?.render?.(view,data)??null}
  function renderReadOnlyPanel(view,data,options){return window.MCSDesignParameterInspector?.readOnlyPanel?.(view,data,options)||''}
  window.MCSDesignRenderer={renderWorkbenchView,renderAuxiliaryView,renderReadOnlyPanel,rawRender,runtimeReconciliation,resolveVisualSource,toolbar,diffSummary};
})();
