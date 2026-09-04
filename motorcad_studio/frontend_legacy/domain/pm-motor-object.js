/* V0.71 PM Motor Object browser projection.
 * Renderer modules consume this object instead of reinterpreting raw Design dictionaries.
 * The base server object carries topology/authority; current Draft values are overlaid here
 * so one domain object drives geometry, winding, slot, materials and parameter views.
 */
(() => {
  const cache=new Map();
  const safeId=value=>encodeURIComponent(String(value||''));
  const n=(value,fallback=0)=>{const parsed=Number(value);return value!==null&&value!==''&&Number.isFinite(parsed)?parsed:Number(fallback)||0};
  const pos=(value,fallback=0)=>Math.max(0,n(value,fallback));
  const integer=(value,fallback=0)=>Math.max(0,Math.round(n(value,fallback)));
  const clone=value=>value?JSON.parse(JSON.stringify(value)):value;
  function normalizedStator(values){
    const a=pos(values.stator_outer_diameter),b=pos(values.stator_inner_diameter),outer=Math.max(a,b),inner=Math.min(a,b);
    return {inner_diameter_mm:inner,outer_diameter_mm:outer,lamination_length_mm:pos(values.stator_lamination_length),native_dimension_order_normalized:Boolean(a&&b&&a<b),slot:{count:integer(values.slot_count),width_mm:pos(values.slot_width),opening_mm:pos(values.slot_opening),depth_mm:pos(values.slot_depth),corner_radius_mm:pos(values.slot_corner_radius),tooth_width_mm:pos(values.tooth_width),tooth_tip_depth_mm:pos(values.tooth_tip_depth),tooth_tip_angle_deg:n(values.tooth_tip_angle)}};
  }
  function magnet(values,arrangement){return{arrangement,thickness_mm:pos(values.magnet_thickness),width_mm:pos(values.magnet_width),length_mm:pos(values.magnet_length),arc_deg:pos(values.magnet_arc_deg),embed_depth_mm:pos(values.magnet_embed_depth),v_angle_deg:n(values.pole_v_angle_deg,130),separation_mm:pos(values.magnet_separation),layers:Math.max(1,integer(values.magnet_layers,1))}}
  function rotor(topology,stator,values,warnings){
    const gap=pos(values.air_gap),rotorD=pos(values.rotor_diameter),nativeOuter=pos(values.rotor_outer_diameter),lam=pos(values.rotor_lamination_length),mt=pos(values.magnet_thickness);
    if(topology==='rfpm_ipm'){
      const envelope=rotorD||Math.max(0,stator.inner_diameter_mm-2*gap);
      return{kind:'interior_pm',position:'inner',inner_diameter_mm:pos(values.shaft_diameter),outer_diameter_mm:envelope,core_outer_diameter_mm:envelope,lamination_length_mm:lam,magnet:magnet(values,'interior_v'),native_dimension_authority:'canonical_parameters'};
    }
    if(topology==='rfpm_spm'){
      const envelope=rotorD||Math.max(0,stator.inner_diameter_mm-2*gap);
      return{kind:'surface_pm',position:'inner',inner_diameter_mm:pos(values.shaft_diameter),outer_diameter_mm:envelope,core_outer_diameter_mm:Math.max(0,envelope-2*mt),lamination_length_mm:lam,magnet:magnet(values,'surface'),native_dimension_authority:'canonical_parameters'};
    }
    if(topology==='outer_rotor_pm'){
      const minimum=stator.outer_diameter_mm+2*gap+2*mt;let outer=nativeOuter,authority='rotor_outer_diameter';
      if(outer<=stator.outer_diameter_mm){outer=Math.max(minimum,pos(values.housing_diameter));authority='derived_outer_rotor_envelope';warnings.push('外转子原生尺寸未形成完整包含关系；当前视图使用派生包络，Motor-CAD 原生几何保持最终权威。')}
      const inner=Math.max(stator.outer_diameter_mm+2*gap,outer-2*Math.max(mt,1)-Math.max(2,.08*outer));
      return{kind:'outer_rotor_pm',position:'outer',inner_diameter_mm:inner,outer_diameter_mm:outer,core_outer_diameter_mm:outer,lamination_length_mm:lam,magnet:magnet(values,'outer_surface'),native_dimension_authority:authority};
    }
    const outer=pos(values.axial_rotor_diameter)||stator.outer_diameter_mm,inner=Math.max(pos(values.shaft_diameter),stator.inner_diameter_mm);
    return{kind:'axial_pm',position:'dual_disc',inner_diameter_mm:inner,outer_diameter_mm:Math.max(inner,outer),core_outer_diameter_mm:Math.max(inner,outer),lamination_length_mm:lam,magnet:magnet(values,'axial_surface'),native_dimension_authority:'canonical_parameters'};
  }
  function provider(topology){
    if(topology==='rfpm_ipm')return{radial_provider:'rfpm_ipm_radial',longitudinal_provider:'rfpm_longitudinal',preferred_view:'radial'};
    if(topology==='outer_rotor_pm')return{radial_provider:'outer_rotor_pm_radial',longitudinal_provider:'outer_rotor_pm_longitudinal',preferred_view:'radial'};
    if(topology==='afpm')return{radial_provider:'afpm_face',longitudinal_provider:'afpm_stack',preferred_view:'axial'};
    return{radial_provider:'rfpm_spm_radial',longitudinal_provider:'rfpm_longitudinal',preferred_view:'radial'};
  }
  function resolve(data={},values={},materials=null){
    const base=data.motor_object||{},identity=base.identity||data.motor_snapshot?.identity||{},topology=String(base.topology_id||identity.topology_id||(data.template?.is_axial?'afpm':'rfpm_spm'));
    const baseline={...(base.parameters||{}),...(data.effective_parameters||{})},merged={...baseline,...(values||{})},warnings=[...(base.warnings||[])],stator=normalizedStator(merged),geometryValues={...merged};
    const changed=(id)=>Object.prototype.hasOwnProperty.call(values||{},id)&&String((values||{})[id])!==String(baseline[id]);
    // During Draft editing, an explicit air-gap change moves the inner rotor envelope when
    // the rotor diameter itself was not edited.  This keeps the section visually reactive
    // without silently overwriting the canonical rotor-diameter input.
    if((topology==='rfpm_spm'||topology==='rfpm_ipm')&&changed('air_gap')&&!changed('rotor_diameter')){
      geometryValues.rotor_diameter=Math.max(0,stator.inner_diameter_mm-2*pos(merged.air_gap));
    }
    if(stator.native_dimension_order_normalized&&!warnings.some(x=>String(x).includes('规范化')))warnings.push('当前拓扑的 Stator_Lam_Dia / Stator_Bore 已按内外径几何关系规范化显示。');
    const rotorObj=rotor(topology,stator,geometryValues,warnings),baseW=clone(base.winding||{})||{},winding={...baseW,slot_count:stator.slot.count||baseW.slot_count,pole_count:Math.max(1,integer(merged.pole_count,baseW.pole_count||1)),parallel_paths:Math.max(1,integer(merged.parallel_paths,baseW.parallel_paths||1)),turns_per_coil:merged.turns_per_coil??baseW.turns_per_coil};
    let geometricGap=pos(merged.air_gap);
    if(topology==='rfpm_spm'||topology==='rfpm_ipm')geometricGap=Math.max(0,(stator.inner_diameter_mm-rotorObj.outer_diameter_mm)/2);
    else if(topology==='outer_rotor_pm')geometricGap=Math.max(0,(rotorObj.inner_diameter_mm-stator.outer_diameter_mm)/2);
    const gapError=geometricGap-pos(merged.air_gap);
    if((topology==='rfpm_spm'||topology==='rfpm_ipm')&&Math.abs(gapError)>Math.max(.02,pos(merged.air_gap)*.02)&&!warnings.some(x=>String(x).includes('几何间隙'))){
      warnings.push(`当前视图几何间隙 ${geometricGap.toFixed(3)} mm 与 air_gap 输入 ${pos(merged.air_gap).toFixed(3)} mm 不一致；Motor-CAD 原生 readback 决定最终几何。`);
    }
    const p=provider(topology),viewParams=base.visualization?.view_parameter_ids||{};
    return{schema_version:1,identity,topology_id:topology,flux_direction:topology==='afpm'?'axial':'radial',rotor_position:topology==='afpm'?'dual_disc':topology==='outer_rotor_pm'?'outer':'inner',stator,rotor:rotorObj,shaft:{diameter_mm:pos(merged.shaft_diameter),hole_diameter_mm:pos(merged.shaft_hole_diameter)},housing:{diameter_mm:pos(merged.housing_diameter)},winding,materials:materials||data.materials||base.materials||{},parameters:merged,applicable_parameter_ids:base.applicable_parameter_ids||[],visualization:{...base.visualization,...p,view_parameter_ids:viewParams},derived:{...(base.derived||{}),pole_count:Math.max(1,integer(merged.pole_count,1)),slot_count:stator.slot.count,air_gap_mm:pos(merged.air_gap),geometric_air_gap_mm:geometricGap,air_gap_consistency_error_mm:gapError,stator_radial_build_mm:Math.max(0,(stator.outer_diameter_mm-stator.inner_diameter_mm)/2),is_axial:topology==='afpm',is_outer_rotor:topology==='outer_rotor_pm',magnet_arrangement:rotorObj.magnet.arrangement},warnings};
  }
  async function load(revisionId,options={}){
    const key=String(revisionId||'');if(!key)throw new Error('design revision id is required');
    if(cache.has(key)&&!options.refresh)return cache.get(key);
    if(typeof window.api!=='function')throw new Error('api() is required to load a PM Motor Object');
    const payload=await window.api(`/api/design-revisions/${safeId(key)}/motor-object`,options.signal?{signal:options.signal}:{});
    cache.set(key,payload);return payload;
  }
  function invalidate(revisionId){cache.delete(String(revisionId||''))}
  function viewParameterIds(data,view){return data?.motor_object?.visualization?.view_parameter_ids?.[view]||data?.design_views?.find(row=>row.id===view)?.parameter_ids||[]}
  const supported=new Set(['rfpm_spm','rfpm_ipm','outer_rotor_pm','afpm']);
  window.MCSPMMotorObject={resolve,load,invalidate,viewParameterIds,supported};
  window.MCSMotorObject?.register?.([...supported],resolve);
})();
