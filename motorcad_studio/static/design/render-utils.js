/* V0.64 stable Design renderer utilities. No page ownership lives here. */
(() => {
  const safe=value=>typeof window.esc==='function'
    ? window.esc(value)
    : String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const number=(value,fallback=0)=>{
    const parsed=Number(value);if(value!==null&&value!==''&&Number.isFinite(parsed))return parsed;
    const backup=Number(fallback);return Number.isFinite(backup)?backup:fallback;
  };
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const fmt=(value,digits=3)=>{
    if(value===null||value===undefined||value==='')return'—';
    const n=Number(value);return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:digits}):String(value);
  };
  const parameterRecord=(data,id)=>(data?.parameters||[]).find(row=>row.id===id)||null;
  const selectAttribute=(id,editable)=>editable?`data-workbench-select="${safe(id)}"`:`data-design-parameter-v031="${safe(id)}"`;
  const polar=(cx,cy,r,degrees)=>{const a=(degrees-90)*Math.PI/180;return[cx+r*Math.cos(a),cy+r*Math.sin(a)]};
  const ringSegment=(cx,cy,inner,outer,start,end)=>{
    const a=polar(cx,cy,outer,end),b=polar(cx,cy,outer,start),c=polar(cx,cy,inner,start),d=polar(cx,cy,inner,end);
    const large=Math.abs(end-start)>180?1:0;
    return`M${a[0].toFixed(2)},${a[1].toFixed(2)} A${outer},${outer} 0 ${large} 0 ${b[0].toFixed(2)},${b[1].toFixed(2)} L${c[0].toFixed(2)},${c[1].toFixed(2)} A${inner},${inner} 0 ${large} 1 ${d[0].toFixed(2)},${d[1].toFixed(2)} Z`;
  };
  // Narrow compatibility adapter for integrations that load renderer modules without the
  // V0.71 browser domain boundary. Geometry/winding renderers still consume one motor
  // object; this adapter only converts a legacy parameter dictionary at the boundary.
  const legacyMotorObjectAdapter=(data,values,materials)=>{
    const hint=String(data?.motor_snapshot?.identity?.topology_id||data?.template?.topology||data?.template?.motor_type||'rfpm_spm').toLowerCase();
    const topology=hint.includes('afpm')||hint.includes('axial')?'afpm':hint.includes('outer')||hint.includes('bpmor')?'outer_rotor_pm':hint.includes('ipm')?'rfpm_ipm':'rfpm_spm';
    const outer=Math.max(number(values.stator_outer_diameter),number(values.stator_inner_diameter)),inner=Math.min(number(values.stator_outer_diameter),number(values.stator_inner_diameter)),gap=Math.max(0,number(values.air_gap)),magnetT=Math.max(0,number(values.magnet_thickness));
    const stator={inner_diameter_mm:inner,outer_diameter_mm:outer,lamination_length_mm:Math.max(0,number(values.stator_lamination_length)),native_dimension_order_normalized:false,slot:{count:Math.max(1,Math.round(number(values.slot_count,12))),width_mm:Math.max(0,number(values.slot_width)),opening_mm:Math.max(0,number(values.slot_opening)),depth_mm:Math.max(0,number(values.slot_depth)),corner_radius_mm:Math.max(0,number(values.slot_corner_radius)),tooth_width_mm:Math.max(0,number(values.tooth_width)),tooth_tip_depth_mm:Math.max(0,number(values.tooth_tip_depth)),tooth_tip_angle_deg:number(values.tooth_tip_angle)}};
    let rotorOuter=Math.max(0,number(values.rotor_diameter));
    if((topology==='rfpm_spm'||topology==='rfpm_ipm')&&(!rotorOuter||!Object.prototype.hasOwnProperty.call(values,'rotor_diameter')))rotorOuter=Math.max(0,inner-2*gap);
    if(topology==='outer_rotor_pm')rotorOuter=Math.max(number(values.rotor_outer_diameter),outer+2*gap+2*magnetT);
    if(topology==='afpm')rotorOuter=Math.max(number(values.axial_rotor_diameter),outer);
    const arrangement=topology==='rfpm_ipm'?'interior_v':topology==='afpm'?'axial_surface':topology==='outer_rotor_pm'?'outer_surface':'surface';
    const rotor={kind:topology==='rfpm_ipm'?'interior_pm':topology==='afpm'?'axial_pm':topology==='outer_rotor_pm'?'outer_rotor_pm':'surface_pm',position:topology==='afpm'?'dual_disc':topology==='outer_rotor_pm'?'outer':'inner',inner_diameter_mm:Math.max(0,number(values.shaft_diameter)),outer_diameter_mm:rotorOuter,core_outer_diameter_mm:topology==='rfpm_spm'?Math.max(0,rotorOuter-2*magnetT):rotorOuter,lamination_length_mm:Math.max(0,number(values.rotor_lamination_length,values.stator_lamination_length)),magnet:{arrangement,thickness_mm:magnetT,width_mm:Math.max(0,number(values.magnet_width)),length_mm:Math.max(0,number(values.magnet_length)),arc_deg:Math.max(0,number(values.magnet_arc_deg,140)),embed_depth_mm:Math.max(0,number(values.magnet_embed_depth)),v_angle_deg:number(values.pole_v_angle_deg,130),separation_mm:Math.max(0,number(values.magnet_separation)),layers:Math.max(1,Math.round(number(values.magnet_layers,1)))},native_dimension_authority:'legacy_parameter_adapter'};
    return{schema_version:1,identity:data?.motor_snapshot?.identity||{},topology_id:topology,flux_direction:topology==='afpm'?'axial':'radial',rotor_position:rotor.position,stator,rotor,shaft:{diameter_mm:Math.max(0,number(values.shaft_diameter)),hole_diameter_mm:Math.max(0,number(values.shaft_hole_diameter))},housing:{diameter_mm:Math.max(0,number(values.housing_diameter,outer))},winding:{...(data?.winding_design||{}),slot_count:stator.slot.count,pole_count:Math.max(2,Math.round(number(values.pole_count,8))),parallel_paths:Math.max(1,Math.round(number(values.parallel_paths,1))),turns_per_coil:Math.max(1,Math.round(number(values.turns_per_coil,1)))},materials:materials||data?.materials||{},parameters:values,visualization:{radial_provider:topology==='rfpm_ipm'?'rfpm_ipm_radial':topology==='outer_rotor_pm'?'outer_rotor_pm_radial':topology==='afpm'?'afpm_face':'rfpm_spm_radial',longitudinal_provider:topology==='afpm'?'afpm_stack':topology==='outer_rotor_pm'?'outer_rotor_pm_longitudinal':'rfpm_longitudinal',preferred_view:topology==='afpm'?'axial':'radial',view_parameter_ids:{}},derived:{pole_count:Math.max(2,Math.round(number(values.pole_count,8))),slot_count:stator.slot.count,air_gap_mm:gap,geometric_air_gap_mm:gap,air_gap_consistency_error_mm:0,is_axial:topology==='afpm',is_outer_rotor:topology==='outer_rotor_pm',magnet_arrangement:arrangement},warnings:['Legacy parameter adapter active; production pages load MCSPMMotorObject before renderers.']};
  };
  const viewData=ctx=>{
    const source=ctx.data||{},recon=ctx.visualizationReconciliation||source.visualization_reconciliation||{},requested=String(ctx.visualSource||'design');
    const nativeRequested=requested==='native'&&Boolean(recon.native_render_allowed);
    const designValues=ctx.values||source.effective_parameters||{};
    const nativeProjection=recon.native_projection||{};
    const nativeValues=recon.native_effective_parameters||{...designValues,...(nativeProjection.parameters||{})};
    const values=nativeRequested?nativeValues:designValues;
    const selectedMaterials=nativeRequested?(recon.native_materials||source.materials||{}):(ctx.materials||source.materials||{});
    const data=nativeRequested?{...source,effective_parameters:values,materials:selectedMaterials,winding_design:recon.native_winding_design||source.winding_design||{}}:(ctx.materials?{...source,materials:ctx.materials}:source);
    const projectedObject=nativeRequested?(recon.native_motor_object||null):null;
    const motorObject=projectedObject||window.MCSMotorObject?.resolve?.(data,values,selectedMaterials)||window.MCSPMMotorObject?.resolve?.(data,values,selectedMaterials)||legacyMotorObjectAdapter(data,values,selectedMaterials);
    return{data,values,precheck:ctx.precheck||source.precheck||{},editable:Boolean(ctx.editable),selected:ctx.selected||null,motorObject,visualSource:nativeRequested?'native':'design',visualizationReconciliation:recon};
  };
  const authorityStrip=(label='Studio 参数化即时示意')=>`<div class="visual-authority-v031"><span>视图用途</span><b>${safe(label)}</b><em>Motor-CAD 原生几何 / 绕组 / FEA 为最终权威</em></div>`;
  const phaseColors=['#e5484d','#2563eb','#16a36a','#8b5cf6','#e07a24','#64748b'];
  window.MCSDesignRenderUtils={safe,number,clamp,fmt,parameterRecord,selectAttribute,polar,ringSegment,viewData,authorityStrip,phaseColors};
})();
