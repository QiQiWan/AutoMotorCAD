/* MotorCAD Studio V0.31.0 — Motor-CAD-inspired visual design and result workflow.
   Studio previews explain design intent; native Motor-CAD artifacts remain authoritative. */
(() => {
  const $q=(selector,root=document)=>root.querySelector(selector);
  const $$q=(selector,root=document)=>[...root.querySelectorAll(selector)];
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
  const visualState={revisionId:null,data:null,view:'radial',selectedParameter:null,requestToken:0};
  const feaState={caseId:null,fieldKey:null,mesh:false,outlines:true,vectors:false,legend:true,range:'auto'};
  const phaseColors=['#e5484d','#2563eb','#16a36a','#8b5cf6','#e07a24','#64748b'];

  function parameterRecord(data,id){return(data?.parameters||[]).find(row=>row.id===id)||null}
  function selectAttribute(id,editable){return editable?`data-workbench-select="${safe(id)}"`:`data-design-parameter-v031="${safe(id)}"`}
  function polar(cx,cy,r,degrees){const a=(degrees-90)*Math.PI/180;return[cx+r*Math.cos(a),cy+r*Math.sin(a)]}
  function ringSegment(cx,cy,inner,outer,start,end){
    const a=polar(cx,cy,outer,end),b=polar(cx,cy,outer,start),c=polar(cx,cy,inner,start),d=polar(cx,cy,inner,end);
    const large=Math.abs(end-start)>180?1:0;
    return`M${a[0].toFixed(2)},${a[1].toFixed(2)} A${outer},${outer} 0 ${large} 0 ${b[0].toFixed(2)},${b[1].toFixed(2)} L${c[0].toFixed(2)},${c[1].toFixed(2)} A${inner},${inner} 0 ${large} 1 ${d[0].toFixed(2)},${d[1].toFixed(2)} Z`;
  }
  function viewData(ctx){return{data:ctx.data||{},values:ctx.values||ctx.data?.effective_parameters||{},precheck:ctx.precheck||ctx.data?.precheck||{},editable:Boolean(ctx.editable),selected:ctx.selected||null}}
  function authorityStrip(label='Studio 参数化即时示意'){
    return`<div class="visual-authority-v031"><span>视图用途</span><b>${safe(label)}</b><em>Motor-CAD 原生几何 / 绕组 / FEA 为最终权威</em></div>`;
  }

  function radialView(ctx){
    const {data,values,editable}=viewData(ctx),template=data.template||{};
    const slots=clamp(Math.round(number(values.slot_count,12)),3,72),poles=clamp(Math.round(number(values.pole_count,8)),2,40);
    const od=Math.max(20,number(values.stator_outer_diameter,140)),id=clamp(number(values.stator_inner_diameter,80),5,od*.93);
    const gap=Math.max(.05,number(values.air_gap,1)),magnet=Math.max(.1,number(values.magnet_thickness,4));
    const tooth=Math.max(.1,number(values.tooth_width,6)),opening=Math.max(.05,number(values.slot_opening,3));
    const cx=360,cy=255,housingR=222,statorOuter=203,statorInner=112+88*id/od;
    const rotorOuter=Math.max(70,statorInner-clamp(gap*4,3,11)),shaftR=Math.max(30,rotorOuter*.31),magnetBand=clamp(magnet*1.4,7,18);
    const slotPitch=360/slots,slotWidth=clamp(.18+opening/(Math.PI*id/slots||1)*.18,.18,.42)*slotPitch;
    let fins='',slotsSvg='',magnets='',slotCopper='';
    for(let i=0;i<24;i++){
      const a=i*15,p1=polar(cx,cy,housingR+1,a),p2=polar(cx,cy,housingR+18+(i%2)*7,a);
      fins+=`<line x1="${p1[0].toFixed(1)}" y1="${p1[1].toFixed(1)}" x2="${p2[0].toFixed(1)}" y2="${p2[1].toFixed(1)}"/>`;
    }
    for(let i=0;i<slots;i++){
      const center=i*slotPitch,start=center-slotWidth/2,end=center+slotWidth/2;
      slotsSvg+=`<path d="${ringSegment(cx,cy,statorInner+3,statorOuter-8,start,end)}" ${selectAttribute('slot_count',editable)} data-schematic-part="stator-slot winding"/>`;
      const fill=clamp(number(values.slot_fill_factor,.42),.05,.95),copperOuter=statorInner+8+(statorOuter-statorInner-22)*fill;
      slotCopper+=`<path d="${ringSegment(cx,cy,statorInner+8,copperOuter,start+slotWidth*.15,end-slotWidth*.15)}" class="phase-${i%3}" ${selectAttribute('slot_fill_factor',editable)} data-schematic-part="winding stator-slot"/>`;
    }
    const polePitch=360/poles,arc=clamp(number(values.magnet_arc_deg,140)/180,.2,.98)*polePitch;
    for(let i=0;i<poles;i++){
      const center=i*polePitch;
      magnets+=`<path d="${ringSegment(cx,cy,rotorOuter-magnetBand,rotorOuter-2,center-arc/2,center+arc/2)}" class="${i%2?'south':'north'}" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/>`;
    }
    const outerAttr=selectAttribute('stator_outer_diameter',editable),innerAttr=selectAttribute('stator_inner_diameter',editable);
    const q=number((data.precheck?.winding?.derived||{}).slots_per_phase_path,NaN);
    return`<div class="motorcad-view-v031 radial-view-v031">
      <div class="visual-heading-v031"><div><span class="eyebrow">GEOMETRY · RADIAL</span><h3>径向截面与尺寸联动</h3></div><div class="visual-facts-v031"><span>${slots} 槽</span><span>${poles} 极</span><span>槽距 ${Number.isFinite(q)?fmt(q):'—'} / 相 / 支路</span></div></div>
      <div class="radial-canvas-v031"><svg viewBox="0 0 720 520" role="img" aria-label="径向电机参数化截面">
        <defs><marker id="arrowV031" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z"/></marker><linearGradient id="rotorSteelV031" x1="0" x2="1"><stop offset="0" stop-color="#52687f"/><stop offset=".5" stop-color="#91a0b2"/><stop offset="1" stop-color="#52687f"/></linearGradient></defs>
        <g class="housing-fins-v031">${fins}</g><circle cx="${cx}" cy="${cy}" r="${housingR}" class="housing-v031" data-schematic-part="housing"/>
        <circle cx="${cx}" cy="${cy}" r="${statorOuter}" class="stator-v031" ${outerAttr} data-schematic-part="stator"/>
        <circle cx="${cx}" cy="${cy}" r="${statorInner}" class="bore-v031" ${innerAttr} data-schematic-part="airgap stator"/>
        <g class="slots-v031">${slotsSvg}</g><g class="slot-copper-v031">${slotCopper}</g>
        <circle cx="${cx}" cy="${cy}" r="${rotorOuter+2}" class="airgap-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/>
        <circle cx="${cx}" cy="${cy}" r="${rotorOuter}" fill="url(#rotorSteelV031)" class="rotor-v031" data-schematic-part="rotor"/>
        <g class="magnets-v031">${magnets}</g><circle cx="${cx}" cy="${cy}" r="${shaftR}" class="shaft-v031" data-schematic-part="shaft"/>
        <g class="dimension-v031"><line x1="${cx-statorOuter}" y1="488" x2="${cx+statorOuter}" y2="488"/><line x1="${cx-statorOuter}" y1="476" x2="${cx-statorOuter}" y2="498"/><line x1="${cx+statorOuter}" y1="476" x2="${cx+statorOuter}" y2="498"/><text x="${cx}" y="514" text-anchor="middle">定子外径 ${fmt(od)} mm</text><line x1="${cx+rotorOuter}" y1="${cy}" x2="${cx+statorInner}" y2="${cy}" marker-start="url(#arrowV031)" marker-end="url(#arrowV031)"/><text x="${cx+(rotorOuter+statorInner)/2}" y="${cy-10}" text-anchor="middle">g ${fmt(gap)} mm</text></g>
        <g class="visual-labels-v031"><text x="38" y="42">${safe(template.topology||template.motor_type||'Motor model')}</text><text x="38" y="66">OD ${fmt(od)} · ID ${fmt(id)} · 齿宽 ${fmt(tooth)} mm</text></g>
      </svg></div>${authorityStrip()}
    </div>`;
  }

  function axialView(ctx){
    const {data,values,editable}=viewData(ctx),template=data.template||{};
    const length=Math.max(10,number(values.stator_lamination_length,90)),gap=Math.max(.05,number(values.air_gap,1)),mag=Math.max(.1,number(values.magnet_thickness,4));
    const od=Math.max(20,number(values.stator_outer_diameter,140)),id=Math.max(5,number(values.stator_inner_diameter,80));
    const lamW=clamp(length*2.6,150,360),x=360-lamW/2,statorH=118,shaftY=250;
    return`<div class="motorcad-view-v031 axial-view-v031">
      <div class="visual-heading-v031"><div><span class="eyebrow">GEOMETRY · AXIAL</span><h3>轴向装配剖面</h3></div><div class="visual-facts-v031"><span>叠长 ${fmt(length)} mm</span><span>外径 ${fmt(od)} mm</span><span>孔径 ${fmt(id)} mm</span></div></div>
      <div class="axial-canvas-v031"><svg viewBox="0 0 720 500" role="img" aria-label="电机轴向装配剖面">
        <defs><linearGradient id="lamV031" x1="0" x2="1"><stop offset="0" stop-color="#b94b42"/><stop offset=".5" stop-color="#df7565"/><stop offset="1" stop-color="#b94b42"/></linearGradient><marker id="axArrowV031" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z"/></marker></defs>
        <rect x="72" y="70" width="576" height="360" rx="42" class="ax-housing-v031" data-schematic-part="housing"/>
        <rect x="${x}" y="100" width="${lamW}" height="${statorH}" rx="5" fill="url(#lamV031)" ${selectAttribute('stator_lamination_length',editable)} data-schematic-part="stator"/>
        <rect x="${x}" y="282" width="${lamW}" height="${statorH}" rx="5" fill="url(#lamV031)" ${selectAttribute('stator_lamination_length',editable)} data-schematic-part="stator"/>
        <rect x="${x+8}" y="219" width="${lamW-16}" height="62" rx="4" class="ax-rotor-v031" data-schematic-part="rotor"/>
        <rect x="${x+8}" y="219" width="${lamW-16}" height="9" class="ax-magnet-v031" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet"/>
        <path d="M${x},112 Q${x-74},112 ${x-76},170 Q${x-76},218 ${x},218" class="ax-endwinding-v031" data-schematic-part="winding"/><path d="M${x+lamW},112 Q${x+lamW+74},112 ${x+lamW+76},170 Q${x+lamW+76},218 ${x+lamW},218" class="ax-endwinding-v031" data-schematic-part="winding"/>
        <path d="M${x},388 Q${x-74},388 ${x-76},330 Q${x-76},282 ${x},282" class="ax-endwinding-v031" data-schematic-part="winding"/><path d="M${x+lamW},388 Q${x+lamW+74},388 ${x+lamW+76},330 Q${x+lamW+76},282 ${x+lamW},282" class="ax-endwinding-v031" data-schematic-part="winding"/>
        <rect x="28" y="${shaftY-16}" width="664" height="32" rx="16" class="ax-shaft-v031" data-schematic-part="shaft"/><rect x="80" y="218" width="34" height="64" class="ax-bearing-v031"/><rect x="606" y="218" width="34" height="64" class="ax-bearing-v031"/>
        <g class="dimension-v031"><line x1="${x}" y1="452" x2="${x+lamW}" y2="452" marker-start="url(#axArrowV031)" marker-end="url(#axArrowV031)"/><text x="360" y="477" text-anchor="middle">定子叠长 ${fmt(length)} mm</text><line x1="${x+lamW+22}" y1="228" x2="${x+lamW+22}" y2="282"/><text x="${x+lamW+32}" y="260">气隙 ${fmt(gap)} mm</text></g>
        <g class="visual-labels-v031"><text x="34" y="38">${safe(template.is_axial?'轴向磁通装配关系':'径向磁通电机轴向剖面')}</text><text x="34" y="58">当前模板仅绘制已结构化尺寸；端盖、轴承和端绕组为装配关系示意</text></g>
      </svg></div>${authorityStrip('Studio 轴向装配关系示意')}
    </div>`;
  }

  function coilCurve(cx,cy,r,start,end){
    const p1=polar(cx,cy,r,start),p2=polar(cx,cy,r,end),mid=(start+end)/2,control=polar(cx,cy,r+52,mid);
    return`M${p1[0].toFixed(1)},${p1[1].toFixed(1)} Q${control[0].toFixed(1)},${control[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  function windingView(ctx){
    const {data,values,editable}=viewData(ctx),w=data.winding_design||{},derived=(ctx.precheck?.winding||data.precheck?.winding||{}).derived||{};
    const slots=clamp(Math.round(number(values.slot_count,12)),3,72),phases=clamp(Math.round(number(w.phase_count||derived.phase_count,3)),1,9),paths=Math.max(1,Math.round(number(values.parallel_paths,w.parallel_paths||1)));
    const turns=Math.max(1,Math.round(number(values.turns_per_coil,w.turns_per_coil||1))),throwSlots=clamp(Math.round(number(w.estimated_coil_throw_slots,Math.max(1,slots/Math.max(2,number(values.pole_count,8))))),1,Math.max(1,slots-1));
    const q=derived.slots_per_phase_path??w.slots_per_phase_path,valid=Number.isFinite(Number(q))&&Math.abs(Number(q)-Math.round(Number(q)))<1e-9;
    const nativeCoils=Array.isArray(w.coil_table)?w.coil_table:[],hasNative=nativeCoils.length>0;
    const cx=280,cy=255,r=166,slotStep=360/slots;let coils='',marks='',rows='';
    const drawRows=hasNative?nativeCoils.slice(0,84):Array.from({length:Math.min(slots,42)},(_,i)=>({go_slot:i+1,return_slot:(i+throwSlots)%slots+1,phase:i%phases+1}));
    drawRows.forEach((coil,i)=>{
      const phaseIndex=Number.isFinite(Number(coil.phase))?Math.max(0,Number(coil.phase)-1):i%phases,color=phaseColors[phaseIndex%phaseColors.length],start=(Number(coil.go_slot)-1)*slotStep,end=(Number(coil.return_slot)-1)*slotStep;
      coils+=`<path d="${coilCurve(cx,cy,r+13,start,end)}" stroke="${color}" class="coil-path-v031"/>`;
    });
    const nativeMarks=new Map();nativeCoils.forEach((coil,i)=>{const phaseIndex=Number.isFinite(Number(coil.phase))?Math.max(0,Number(coil.phase)-1):i%phases;nativeMarks.set(Number(coil.go_slot),{phaseIndex,direction:'•'});nativeMarks.set(Number(coil.return_slot),{phaseIndex,direction:'×'})});
    for(let i=0;i<slots;i++){
      const a=i*slotStep,p=polar(cx,cy,r,a),nativeMark=nativeMarks.get(i+1),phase=nativeMark?.phaseIndex??i%phases,color=phaseColors[phase%phaseColors.length],direction=nativeMark?.direction??(Math.floor(i/phases)%2?'×':'•');
      marks+=`<g class="winding-mark-v031" ${selectAttribute('slot_count',editable)}><circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${slots>48?5:7}" fill="${color}"/><text x="${p[0].toFixed(1)}" y="${(p[1]+3).toFixed(1)}" text-anchor="middle">${direction}</text></g>`;
      if(i<Math.min(slots,18))rows+=`<tr><td>${i+1}</td><td><span class="phase-dot-v031" style="--phase:${color}"></span>${hasNative?safe(nativeMark?`相 ${nativeMark.phaseIndex+1}`:'未占用'):`相 ${phase+1}`}</td><td>${nativeMark||!hasNative?(direction==='•'?'出':'入'):'—'}</td></tr>`;
    }
    return`<div class="motorcad-view-v031 winding-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">WINDING · PATTERN</span><h3>绕组排布与整数关系</h3></div><div class="visual-facts-v031"><span>${phases} 相</span><span>${turns} 匝 / 线圈</span><span>${paths} 并联支路</span></div></div>
      <div class="winding-layout-v031"><div class="winding-canvas-v031"><svg viewBox="0 0 560 520" role="img" aria-label="绕组相槽关系预览"><circle cx="${cx}" cy="${cy}" r="204" class="winding-stator-v031"/><circle cx="${cx}" cy="${cy}" r="112" class="winding-rotor-v031"/><g>${coils}</g><g>${marks}</g><text x="${cx}" y="244" text-anchor="middle" class="winding-title-v031">${slots} 槽 / ${number(values.pole_count,8)} 极</text><text x="${cx}" y="271" text-anchor="middle" class="winding-subtitle-v031">预估线圈节距 ${throwSlots} 槽</text><text x="${cx}" y="294" text-anchor="middle" class="winding-subtitle-v031">${safe(w.pattern_class||'模板继承')} · ${safe(w.slot_arrangement||'模板继承')}</text></svg></div>
      <aside class="winding-summary-v031"><div class="winding-health-v031 ${valid?'pass':'blocked'}"><span>${valid?'✓':'!'}</span><div><small>槽 / 相 / 支路</small><b>${q!==null&&q!==undefined?fmt(q,5):'待原生检查'}</b><p>${valid?'整数关系通过':'当前关系无法整数分配'}</p></div></div><div class="winding-evidence-v035 ${hasNative?'native':'preview'}"><b>${hasNative?'已读取 Motor-CAD 线圈表':'设计版本即时预览'}</b><span>${hasNative?`${nativeCoils.length} 个原生线圈记录 · SHA ${safe((w.native_source_sha256||'').slice(0,10))}`:'执行模型检查后升级为原生绕组证据'}</span></div><div class="winding-metrics-v031"><div><span>绕组层数</span><b>${fmt(w.layers,0)}</b></div><div><span>槽满率输入</span><b>${fmt(values.slot_fill_factor??w.slot_fill_factor)}</b></div><div><span>线圈节距</span><b>${hasNative?'按原生槽对':`${throwSlots} <em>仅视图估计</em>`}</b></div><div><span>Motor-CAD 定义码</span><b>${fmt(w.motorcad_winding_type_code,0)} / ${fmt(w.motorcad_definition_code,0)}</b></div></div><div class="phase-legend-v031">${Array.from({length:phases},(_,i)=>`<span style="--phase:${phaseColors[i%phaseColors.length]}">相 ${i+1}</span>`).join('')}</div><div class="winding-slot-table-v031"><table><thead><tr><th>槽</th><th>相</th><th>方向</th></tr></thead><tbody>${rows}</tbody></table>${slots>18?`<small>显示前 18 / ${slots} 槽</small>`:''}</div></aside></div>${authorityStrip(hasNative?'Motor-CAD 保存的绕组槽对':'Studio 相槽关系预览；线圈节距为可视估计')}
    </div>`;
  }

  function slotView(ctx){
    const {data,values,editable}=viewData(ctx),w=data.winding_design||{};
    const fill=clamp(number(values.slot_fill_factor,.4),.05,.95),count=clamp(Math.round(10+fill*54),12,64);
    let conductors='';
    for(let i=0;i<count;i++){
      const side=i%2,row=Math.floor(i/2),col=row%4,layer=Math.floor(row/4),x=side?378+col*14:282-col*14,y=117+layer*29+(col%2)*7;
      if(y>360)continue;conductors+=`<circle cx="${x}" cy="${y}" r="9" class="slot-conductor-v031"/>`;
    }
    const missing=(w.native_only_fields||[]).map(id=>({wire_diameter:'线径',copper_diameter:'铜径',strands_in_hand:'并绕根数',liner_thickness:'槽衬厚度',coil_divider_width:'线圈分隔宽度',conductor_separation:'导体间距',winding_factor:'基波绕组因数'})[id]||id);
    return`<div class="motorcad-view-v031 slot-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">WINDING · DEFINITION</span><h3>槽内定义与导体占用</h3></div><div class="visual-facts-v031"><span>槽满率 ${fmt(fill)}</span><span>匝数 ${fmt(values.turns_per_coil,0)}</span><span>槽深 ${fmt(values.slot_depth)} mm</span></div></div>
      <div class="slot-layout-v031"><div class="slot-canvas-v031"><svg viewBox="0 0 660 470" role="img" aria-label="定子槽内导体填充关系"><path d="M178,34 L482,34 L430,425 L230,425 Z" class="slot-steel-v031" ${selectAttribute('tooth_width',editable)} data-schematic-part="stator-slot"/><path d="M242,64 L418,64 L391,397 L269,397 Z" class="slot-liner-v031" data-schematic-part="winding stator-slot"/><path d="M320,65 L340,65 L340,397 L320,397 Z" class="slot-divider-v031"/><g ${selectAttribute('slot_fill_factor',editable)}>${conductors}</g><rect x="269" y="397" width="122" height="20" class="slot-wedge-v031" ${selectAttribute('slot_opening',editable)}/><g class="slot-labels-v031"><text x="330" y="26" text-anchor="middle">槽口 ${fmt(values.slot_opening)} mm</text><text x="330" y="452" text-anchor="middle">密度随槽满率输入变化；圆点不代表真实线径和根数</text></g></svg></div>
      <aside class="slot-definition-v031"><h4>已结构化参数</h4>${['slot_opening','tooth_width','slot_depth','turns_per_coil','slot_fill_factor'].map(id=>{const row=parameterRecord(data,id);return row?`<button type="button" ${selectAttribute(id,editable)}><span>${safe(row.label)}</span><b>${fmt(values[id])} ${safe(row.unit||'')}</b></button>`:''}).join('')}<h4>需要原生回读后开放</h4><div class="native-field-list-v031">${missing.map(label=>`<span><b>${safe(label)}</b><em>待 Motor-CAD 证据</em></span>`).join('')}</div><p>后续应从 winding definition / winding output 提取线径、绝缘、分隔和实际槽满率，避免通过近似几何反推。</p></aside></div>${authorityStrip('Studio 槽满率密度示意')}
    </div>`;
  }

  function materialsView(ctx){
    const {data}=viewData(ctx),materials=data.materials||{},components=materials.component_materials||{},fluids=materials.cooling_fluids||{};
    const componentRows=Object.entries(components),fluidRows=Object.entries(fluids),rows=[...componentRows.map(([k,v])=>[k,v,'设计版本']),...fluidRows.map(([k,v])=>[k,v,'冷却介质'])];
    return`<div class="motorcad-view-v031 materials-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">INPUT DATA · MATERIALS</span><h3>材料与介质快照</h3></div><div class="visual-facts-v031"><span>${rows.length} 项覆盖</span><span>${safe(data.template?.cooling_note||'模板冷却')}</span></div></div>
      <div class="materials-table-v031"><table><thead><tr><th>组件 / 介质</th><th>材料</th><th>来源</th><th>状态</th></tr></thead><tbody>${rows.length?rows.map(([k,v,source])=>`<tr><td>${safe(k)}</td><td><b>${safe(typeof v==='object'?JSON.stringify(v):v)}</b></td><td>${safe(source)}</td><td><span class="material-state-v031">已冻结</span></td></tr>`).join(''):`<tr><td colspan="4"><div class="materials-empty-v031"><b>当前设计版本没有显式材料覆盖</b><span>求解时沿用模板材料；若材料是研究变量，应在新设计版本中冻结材料映射与数据库来源。</span></div></td></tr>`}</tbody></table></div><div class="materials-meta-v031"><span>材料数据库</span><b>${safe(materials.material_database_path||'沿用 Motor-CAD 模板数据库')}</b></div>${authorityStrip('Design Revision 材料快照')}
    </div>`;
  }

  function renderWorkbenchView(view,ctx){
    if(view==='radial'||view==='geometry')return radialView(ctx);
    if(view==='axial')return axialView(ctx);
    if(view==='winding')return windingView(ctx);
    if(view==='slot')return slotView(ctx);
    if(view==='materials')return materialsView(ctx);
    return null;
  }

  function nativeEvidenceView(data){
    const evidence=data.native_evidence,artifacts=evidence?.artifacts||[];
    return`<div class="native-evidence-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">MOTOR-CAD · NATIVE EVIDENCE</span><h3>${evidence?'最近一次原生模型证据':'尚无原生模型证据'}</h3></div>${evidence?`<span class="status ${safe(evidence.execution_status||'UNVERIFIED')}">${safe(evidence.execution_status||'UNKNOWN')}</span>`:''}</div>
      <div class="authority-ladder-v031"><div class="done"><span>L0</span><b>参数示意</b><small>Studio</small></div><i></i><div class="done"><span>L1</span><b>静态约束</b><small>Studio</small></div><i></i><div class="${evidence?'done':'pending'}"><span>L2</span><b>几何 / 绕组</b><small>Motor-CAD</small></div><i></i><div class="${evidence?.execution_status==='SUCCEEDED'?'done':'pending'}"><span>L3</span><b>真实求解</b><small>Motor-CAD</small></div><i></i><div class="${evidence?.native_fea_artifact?'done':'pending'}"><span>L4</span><b>FEA / 质量</b><small>原生数据</small></div></div>
      ${evidence?`<div class="native-evidence-summary-v031"><div><span>Case</span><b>${safe(evidence.case_id)}</b></div><div><span>分析</span><b>${safe(evidence.analysis||'—')}</b></div><div><span>结果质量</span><b>${safe(evidence.quality_status||'—')}</b></div><div><span>完成时间</span><b>${safe(evidence.finished_at||'—')}</b></div></div><div class="native-artifacts-v031">${artifacts.map(a=>`<a href="${safe(a.download_url||`/api/artifacts/${a.id}`)}" target="_blank"><span>${safe(a.name||a.kind)}</span><small>${Number(a.size_bytes||0).toLocaleString()} bytes</small></a>`).join('')||'<p>当前 Case 没有登记模型证据文件。</p>'}</div>`:'<div class="native-empty-v031"><b>先执行 Motor-CAD 模型检查或真实计算</b><p>完成后可在这里查看 model_validation、原生绕组文件、pre-solve MOT 和 Native FEA manifest。</p></div>'}
    </div>`;
  }

  function compareView(data){
    const previous=data.previous_feasible,values=data.effective_parameters||{};
    if(!previous)return'<div class="native-empty-v031"><b>没有可用比较基线</b><p>创建第二个可行设计版本后即可查看参数差异。</p></div>';
    const rows=(data.parameters||[]).map(row=>({row,base:previous.parameters?.[row.id],current:values[row.id]})).filter(x=>x.base!==undefined&&String(x.base)!==String(x.current));
    const label=previous.source==='revision'?`Rev.${previous.revision}`:'模板基线';
    return`<div class="design-compare-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">DESIGN · COMPARE</span><h3>${safe(label)} → 当前设计版本</h3></div><div class="visual-facts-v031"><span>${rows.length} 项差异</span></div></div><table><thead><tr><th>参数</th><th>${safe(label)}</th><th>当前</th><th>变化</th></tr></thead><tbody>${rows.length?rows.map(({row,base,current})=>{const delta=Number.isFinite(Number(base))&&Number.isFinite(Number(current))?Number(current)-Number(base):null;return`<tr><td><b>${safe(row.label)}</b><small>${safe(row.id)}</small></td><td>${fmt(base)} ${safe(row.unit||'')}</td><td>${fmt(current)} ${safe(row.unit||'')}</td><td class="${delta>0?'up':delta<0?'down':''}">${delta===null?'—':`${delta>0?'+':''}${fmt(delta)}`}</td></tr>`}).join(''):'<tr><td colspan="4">当前值与比较基线相同。</td></tr>'}</tbody></table></div>`;
  }

  function parameterPanel(view,data){
    const spec=(data.design_views||[]).find(row=>row.id===view)||{},ids=spec.parameter_ids||[],values=data.effective_parameters||{};
    if(['native','compare'].includes(view))return`<aside class="design-context-panel-v031"><span class="eyebrow">视图说明</span><h4>${safe(spec.label||view)}</h4><p>${safe(spec.description||'')}</p><div class="context-rule-v031"><b>证据规则</b><span>低层级示意不会覆盖更高层级的 Motor-CAD 原生证据。</span></div></aside>`;
    if(view==='materials')return`<aside class="design-context-panel-v031"><span class="eyebrow">材料边界</span><h4>设计材料快照</h4><p>材料覆盖应随 Design Revision 冻结。任务中的临时材料覆盖只属于本次计算配置。</p><div class="context-rule-v031"><b>下一阶段</b><span>补齐材料属性表、数据库版本和 B-H / 损耗曲线哈希。</span></div></aside>`;
    return`<aside class="design-context-panel-v031"><div class="context-panel-head-v031"><div><span class="eyebrow">当前视图参数</span><h4>${safe(spec.label||view)}</h4></div><span>${ids.length}</span></div><p>${safe(spec.description||'')}</p><div class="context-param-list-v031">${ids.map(id=>{const row=parameterRecord(data,id),issue=(data.precheck?.issues||[]).some(item=>(item.parameter_ids||[]).includes(id));return row?`<button type="button" data-design-parameter-v031="${safe(id)}" class="${visualState.selectedParameter===id?'selected':''} ${issue?'has-issue':''}"><span><b>${safe(row.label)}</b><small>${safe((row.motorcad_candidates||[])[0]||row.id)}</small></span><em>${fmt(values[id])} ${safe(row.unit||'')}</em></button>`:''}).join('')}</div><button type="button" class="primary edit-view-v031" data-edit-view-v031="${safe(view)}" ${ids.length?'':'disabled'}>修改当前视图参数</button><small class="context-footnote-v031">保存时创建新的不可变设计版本。</small></aside>`;
  }

  function renderDesignView(){
    const data=visualState.data,stage=$q('#designViewStageV031'),panel=$q('#designParamPanelV031');if(!data||!stage||!panel)return;
    $$q('[data-design-view-v031]').forEach(button=>button.classList.toggle('active',button.dataset.designViewV031===visualState.view));
    const ctx={data,values:data.effective_parameters||{},precheck:data.precheck||{},editable:false,selected:visualState.selectedParameter};
    if(visualState.view==='native')stage.innerHTML=nativeEvidenceView(data);
    else if(visualState.view==='compare')stage.innerHTML=compareView(data);
    else stage.innerHTML=renderWorkbenchView(visualState.view,ctx)||'<div class="native-empty-v031">当前视图不可用。</div>';
    panel.innerHTML=parameterPanel(visualState.view,data);
  }

  function bindDesignViewer(root){
    root.addEventListener('click',event=>{
      const tab=event.target.closest('[data-design-view-v031]');if(tab){visualState.view=tab.dataset.designViewV031;visualState.selectedParameter=null;renderDesignView();return;}
      const parameter=event.target.closest('[data-design-parameter-v031]');if(parameter){visualState.selectedParameter=parameter.dataset.designParameterV031;renderDesignView();return;}
      const edit=event.target.closest('[data-edit-view-v031]');if(edit){const spec=(visualState.data?.design_views||[]).find(row=>row.id===edit.dataset.editViewV031),first=visualState.selectedParameter||(spec?.parameter_ids||[])[0]||null;window.MCSModelWorkbench?.openView?.(edit.dataset.editViewV031,first);}
    });
  }

  async function decorateDesignViewer(){
    const revision=state.workspaceRevision,layout=$q('#workspaceCanvas .design-visual-layout');if(!revision||!layout)return;
    const token=++visualState.requestToken;
    try{
      const data=await api(`/api/design-revisions/${encodeURIComponent(revision.id)}/workbench`);
      if(token!==visualState.requestToken||state.workspaceRevision?.id!==revision.id)return;
      visualState.revisionId=revision.id;visualState.data=data;visualState.view=(data.design_views||[]).find(row=>row.preferred)?.id||'radial';visualState.selectedParameter=null;
      const oldCard=layout.querySelector('.design-schematic-card');let root=$q('#designViewerV031');
      if(!root){root=document.createElement('section');root.id='designViewerV031';root.className='design-viewer-v031';oldCard?.replaceWith(root);bindDesignViewer(root)}
      layout.classList.add('design-visual-layout-v031');
      root.innerHTML=`<div class="design-view-tabs-v031" role="tablist" aria-label="电机设计视图">${(data.design_views||[]).map(row=>`<button type="button" role="tab" data-design-view-v031="${safe(row.id)}" class="${row.id===visualState.view?'active':''}" ${row.available?'':'disabled'}><b>${safe(row.label)}</b><small>${safe(row.description)}</small></button>`).join('')}</div><div class="design-view-body-v031"><div id="designViewStageV031" class="design-view-stage-v031"></div><div id="designParamPanelV031"></div></div>`;
      const summary=$q('#workspaceRevisionSummary');if(summary&&!summary.dataset.v031Wrapped){const original=summary.innerHTML;summary.innerHTML=`<details class="revision-trace-v031"><summary><span><b>设计版本参数与追溯信息</b><small>完整参数快照、内容哈希与创建时间</small></span></summary><div>${original}</div></details>`;summary.dataset.v031Wrapped='1'}
      renderDesignView();
    }catch(error){console.warn('design visual workspace',error)}
  }

  function stepProgress(){
    const guidance=state.uiGuidanceV030||{},map={design:0,analysis:1,solve:2,result:3};let progress=map[guidance.current_step]??0;
    if(guidance.status==='COMPLETED')progress=3;if(guidance.status==='RUNNING')progress=2;
    return{guidance,progress};
  }
  function activeFlowStep(){const tab=$q('.tab.active')?.id||'';if(['workspace','templates'].includes(tab))return'design';if(['newTask','tasks','simulationAssets'].includes(tab))return'analysis';if(tab==='monitor')return'solve';if(tab==='resultViewer')return'result';return state.uiGuidanceV030?.current_step||'design'}
  function upgradeFlowBar(){
    const bar=$q('#engineerFlowBarV030');if(!bar||bar.dataset.v031Applying==='1')return;
    bar.dataset.v031Applying='1';bar.classList.add('workflow-state-rail-v031');document.body.classList.add('motorcad-visual-workflow-v031');
    const {guidance,progress}=stepProgress(),active=activeFlowStep(),status=guidance.status||'NEEDS_CHECK';
    const stateMeta={READY:['可以计算','ready'],NEEDS_CHECK:['需要检查','needs-check'],BLOCKED:['无法计算','blocked'],RUNNING:['计算中','running'],COMPLETED:['已有结果','completed']}[status]||[status,'needs-check'];
    const rows=[['design','1','设计电机','结构 · 几何 · 绕组','workspace'],['analysis','2','设置分析','工况 · 求解 · 输出','newTask'],['solve','3','计算模型','检查 · 求解 · 证据',status==='RUNNING'?'monitor':'newTask'],['result','4','分析结果','性能 · 拓扑 · FEA','resultViewer']];
    bar.innerHTML=`<div class="workflow-state-head-v031"><div class="workflow-project-state-v031 ${stateMeta[1]}"><span></span><div><small>${safe(stateMeta[0])}</small><b>${safe(guidance.headline||'按四个工程阶段完成电机分析')}</b></div></div><div class="workflow-utilities-v031"><button type="button" data-v031-flow-tab="dashboard">项目概览</button><button type="button" data-v031-flow-tab="dataFactory">数据资产</button></div></div><div class="workflow-steps-v031">${rows.map(([id,n,title,desc,tab],index)=>{let cls=index<progress?'done':index===progress?'current':'pending';if(id===active)cls+=' active';if(status==='BLOCKED'&&index===progress)cls+=' blocked';if(status==='RUNNING'&&id==='solve')cls+=' running';return`${index?'<i></i>':''}<button type="button" data-v031-flow-tab="${tab}" class="${cls}"><span>${index<progress?'✓':n}</span><div><b>${title}</b><small>${desc}</small></div></button>`}).join('')}</div>`;
    $$q('[data-v031-flow-tab]',bar).forEach(button=>button.addEventListener('click',()=>typeof window.showTab==='function'&&showTab(button.dataset.v031FlowTab)));
    bar.dataset.v031Applying='0';
  }

  function percentile(sorted,q){if(!sorted.length)return 0;const index=(sorted.length-1)*q,lo=Math.floor(index),hi=Math.ceil(index);return sorted[lo]+(sorted[hi]-sorted[lo])*(index-lo)}
  function colorFor(value,min,max){const t=clamp((value-min)/(max-min||1),0,1),stops=[[13,59,102],[25,113,194],[32,190,188],[239,214,77],[231,76,60]],p=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(p)),f=p-i,a=stops[i],b=stops[i+1];return`rgb(${Math.round(a[0]+(b[0]-a[0])*f)},${Math.round(a[1]+(b[1]-a[1])*f)},${Math.round(a[2]+(b[2]-a[2])*f)})`}
  function fieldNodeOffset(field){
    const nodes=field.nodes||[],ids=(field.elements||[]).flatMap(row=>(row||[]).map(Number)).filter(Number.isInteger);
    return ids.length&&Math.min(...ids)>=1&&Math.max(...ids)<=nodes.length?1:0;
  }
  function fieldElementValues(field,nodeOffset=fieldNodeOffset(field)){
    const nodes=field.nodes||[],elements=field.elements||[],values=field.values||[];
    return elements.map((element,index)=>{if(values.length===elements.length)return Number(values[index]);const local=(element||[]).map(id=>Number(values[Number(id)-nodeOffset])).filter(Number.isFinite);return local.length?local.reduce((a,b)=>a+b,0)/local.length:NaN});
  }
  function renderFEAScene(viewer){
    const stage=$q('#feaSceneV031');if(!stage)return;const fields=viewer.results?.fields||{},field=fields[feaState.fieldKey]||fields[Object.keys(fields)[0]];
    if(!field){stage.innerHTML='<div class="native-empty-v031"><b>当前 Case 没有非结构场数据</b><p>只显示由 Motor-CAD 原生 FEA 证据解析得到的网格场。</p></div>';return;}
    const nodes=field.nodes||[],elements=field.elements||[];if(!nodes.length||!elements.length){stage.innerHTML='<div class="native-empty-v031">场数据缺少节点或单元。</div>';return;}
    const nodeOffset=fieldNodeOffset(field),xs=nodes.map(row=>Number(row[0])).filter(Number.isFinite),ys=nodes.map(row=>Number(row[1])).filter(Number.isFinite),elementValues=fieldElementValues(field,nodeOffset),finite=elementValues.filter(Number.isFinite).sort((a,b)=>a-b);
    if(!xs.length||!ys.length||!finite.length){stage.innerHTML='<div class="native-empty-v031">场数据格式无法绘制。</div>';return;}
    const rawMin=finite[0],rawMax=finite[finite.length-1],min=feaState.range==='p98'?percentile(finite,.02):rawMin,max=feaState.range==='p98'?percentile(finite,.98):rawMax;
    const w=860,h=520,p=34,xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),px=x=>p+(Number(x)-xmin)/(xmax-xmin||1)*(w-2*p),py=y=>h-p-(Number(y)-ymin)/(ymax-ymin||1)*(h-2*p);
    let shapes='';elements.slice(0,50000).forEach((element,index)=>{const ids=(element||[]).slice(0,4).map(Number),points=ids.map(id=>nodes[id-nodeOffset]).filter(Boolean),value=elementValues[index];if(points.length<3||!Number.isFinite(value))return;shapes+=`<polygon points="${points.map(point=>`${px(point[0]).toFixed(2)},${py(point[1]).toFixed(2)}`).join(' ')}" fill="${colorFor(value,min,max)}" stroke="${feaState.mesh?'rgba(18,37,56,.34)':'none'}" stroke-width="${feaState.mesh?'.38':'0'}"><title>${safe(field.value_label||feaState.fieldKey)} ${fmt(value,5)} ${safe(field.unit||'')}</title></polygon>`});
    let vectors='';if(feaState.vectors){const source=Object.values(viewer.results?.vectors||{})[0],points=source?.points||source?.nodes||[],rows=source?.vectors||[],step=Math.max(1,Math.ceil(Math.min(points.length,rows.length)/220)),magnitudes=rows.map(v=>Math.hypot(Number(v[0])||0,Number(v[1])||0)),mmax=Math.max(...magnitudes,1e-12);for(let i=0;i<Math.min(points.length,rows.length);i+=step){const point=points[i],v=rows[i],m=magnitudes[i];if(!point||!v)continue;const scale=22*m/mmax,n=Math.hypot(Number(v[0])||0,Number(v[1])||0)||1,x1=px(point[0]),y1=py(point[1]),x2=x1+scale*Number(v[0]||0)/n,y2=y1-scale*Number(v[1]||0)/n;vectors+=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/><circle cx="${x2}" cy="${y2}" r="1.4"/>`}}
    const ticks=Array.from({length:6},(_,i)=>min+(max-min)*(5-i)/5);
    stage.innerHTML=`<div class="fea-scene-wrap-v031"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="有限元场云图"><g>${shapes}</g>${feaState.outlines?`<rect x="${p}" y="${p}" width="${w-2*p}" height="${h-2*p}" class="fea-outline-v031"/>`:''}<g class="fea-vectors-v031">${vectors}</g></svg>${feaState.legend?`<div class="fea-legend-v031"><span>${safe(field.value_label||feaState.fieldKey)}</span><div><i></i><ol>${ticks.map(t=>`<li>${fmt(t,4)}</li>`).join('')}</ol></div><small>${safe(field.unit||'')}</small></div>`:''}</div><div class="fea-scene-meta-v031"><span><b>${nodes.length.toLocaleString()}</b> 节点</span><span><b>${elements.length.toLocaleString()}</b> 单元</span><span><b>${fmt(rawMin,5)} – ${fmt(rawMax,5)}</b> ${safe(field.unit||'')}</span><em>${feaState.range==='p98'?'色标按 2–98% 分位截断；原始范围仍保留':'自动色标'}</em></div>`;
  }
  function enhanceFEAViewer(){
    const viewer=state.viewer,canvas=$q('#viewerCanvas'),fields=viewer?.results?.fields||{};if(!viewer||!canvas||!Object.keys(fields).length)return;
    if(feaState.caseId!==viewer.case?.id){feaState.caseId=viewer.case?.id;feaState.fieldKey=Object.keys(fields)[0];feaState.mesh=false;feaState.vectors=false;feaState.range='auto'}
    canvas.innerHTML=`<section class="fea-workbench-v031"><div class="fea-toolbar-v031"><label>着色场<select id="feaFieldV031">${Object.entries(fields).map(([key,field])=>`<option value="${safe(key)}" ${key===feaState.fieldKey?'selected':''}>${safe(field.value_label||key)}${field.unit?` · ${safe(field.unit)}`:''}</option>`).join('')}</select></label><label>色标<select id="feaRangeV031"><option value="auto" ${feaState.range==='auto'?'selected':''}>自动范围</option><option value="p98" ${feaState.range==='p98'?'selected':''}>2–98% 分位</option></select></label><label class="check-row"><input id="feaLegendV031" type="checkbox" ${feaState.legend?'checked':''}>图例</label><label class="check-row"><input id="feaOutlinesV031" type="checkbox" ${feaState.outlines?'checked':''}>外框</label><label class="check-row"><input id="feaMeshV031" type="checkbox" ${feaState.mesh?'checked':''}>网格</label><label class="check-row"><input id="feaVectorsV031" type="checkbox" ${feaState.vectors?'checked':''} ${Object.keys(viewer.results?.vectors||{}).length?'':'disabled'}>矢量</label><span class="native-data-chip-v031">原生数据</span></div><div id="feaSceneV031" class="fea-scene-v031"></div><div class="visual-authority-v031"><span>数据来源</span><b>当前 Case 的 Motor-CAD Native FEA Evidence</b><em>缺少原生节点、单元或场值时不生成替代云图</em></div></section>`;
    $q('#feaFieldV031')?.addEventListener('change',event=>{feaState.fieldKey=event.target.value;renderFEAScene(viewer)});$q('#feaRangeV031')?.addEventListener('change',event=>{feaState.range=event.target.value;renderFEAScene(viewer)});$q('#feaLegendV031')?.addEventListener('change',event=>{feaState.legend=event.target.checked;renderFEAScene(viewer)});$q('#feaOutlinesV031')?.addEventListener('change',event=>{feaState.outlines=event.target.checked;renderFEAScene(viewer)});$q('#feaMeshV031')?.addEventListener('change',event=>{feaState.mesh=event.target.checked;renderFEAScene(viewer)});$q('#feaVectorsV031')?.addEventListener('change',event=>{feaState.vectors=event.target.checked;renderFEAScene(viewer)});renderFEAScene(viewer);
  }

  function normalizeThermalNetwork(native){
    const sourceNodes=native.nodes||[],count=sourceNodes.length,columns=Math.max(1,Math.min(4,Math.ceil(Math.sqrt(count*1.7)))),rows=Math.max(1,Math.ceil(count/columns));
    const nodes=sourceNodes.map((source,index)=>{const col=index%columns,row=Math.floor(index/columns);return{...source,id:String(source.id??index),label:source.label||source.name||source.component||`节点 ${index+1}`,temperature:source.temperature??source.temperature_c??source.value,power:source.power??source.power_w,x:Number.isFinite(Number(source.x))?Number(source.x):90+col*(540/Math.max(1,columns-1)),y:Number.isFinite(Number(source.y))?Number(source.y):70+row*(210/Math.max(1,rows-1))}});
    const ids=new Set(nodes.map(node=>node.id)),resolve=value=>{const key=String(value);if(ids.has(key))return key;const index=Number(value);return Number.isInteger(index)&&nodes[index]?nodes[index].id:key};
    const edges=(native.edges||[]).map(edge=>({...edge,source:resolve(edge.source??edge.from),target:resolve(edge.target??edge.to)}));
    return{native:true,nodes,edges};
  }
  function thermalTopology(viewer,mode='temperature'){
    const scalar=viewer.results?.scalars||{},scenario=viewer.inputs?.scenario||{},tables=viewer.results?.tables||{},native=tables.thermal_network||tables.thermal_circuit||null;
    if(native?.nodes?.length)return normalizeThermalNetwork(native);
    const ambient=number(scenario.ambient_temperature_c,25),nodes=[
      {id:'ambient',label:'环境',temperature:ambient,x:78,y:170,tone:'ambient'},
      {id:'housing',label:'机壳',temperature:scalar.housing_temperature_c,x:240,y:170,tone:'housing'},
      {id:'stator',label:'定子铁心',temperature:null,x:410,y:94,tone:'stator'},
      {id:'winding',label:'绕组',temperature:scalar.winding_average_temperature_c??scalar.winding_max_temperature_c,x:620,y:70,tone:'winding',power:scalar.copper_loss_w},
      {id:'rotor',label:'转子',temperature:null,x:410,y:250,tone:'rotor'},
      {id:'magnet',label:'永磁体',temperature:scalar.magnet_temperature_c,x:620,y:270,tone:'magnet',power:scalar.magnet_loss_w},
    ],edges=[['ambient','housing'],['housing','stator'],['stator','winding'],['housing','rotor'],['rotor','magnet'],['winding','ambient'],['magnet','ambient']].map(([source,target])=>({source,target}));
    return{native:false,nodes,edges,mode};
  }
  function renderThermalTopology(viewer,mode='temperature'){
    const model=thermalTopology(viewer,mode),lookup=new Map(model.nodes.map(node=>[node.id,node]));let edges='',nodes='';
    model.edges.forEach(edge=>{const a=lookup.get(edge.source),b=lookup.get(edge.target);if(!a||!b)return;edges+=`<g class="thermal-edge-v031 ${model.native?'native':'inferred'}"><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/><circle cx="${(a.x+b.x)/2}" cy="${(a.y+b.y)/2}" r="4"/>${edge.value!==undefined?`<text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-10}" text-anchor="middle">${fmt(edge.value)} ${safe(edge.unit||'')}</text>`:''}</g>`});
    model.nodes.forEach(node=>{const value=mode==='power'?node.power:node.temperature;nodes+=`<g class="thermal-node-v031 ${safe(node.tone||'default')}"><rect x="${node.x-64}" y="${node.y-34}" width="128" height="68" rx="12"/><text x="${node.x}" y="${node.y-6}" text-anchor="middle">${safe(node.label||node.id)}</text><text x="${node.x}" y="${node.y+18}" text-anchor="middle" class="value">${value!==null&&value!==undefined?`${fmt(value)} ${mode==='power'?'W':'°C'}`:'—'}</text></g>`});
    return`<svg viewBox="0 0 720 340" role="img" aria-label="电机热路径拓扑图"><g>${edges}</g><g>${nodes}</g></svg><div class="thermal-topology-note-v031 ${model.native?'native':'summary'}"><b>${model.native?'Motor-CAD 原生热网络':'工程热路径摘要'}</b><span>${model.native?'节点与连接来自当前 Case 的结构化热网络表。':'连接用于总览主要热路径；当前结果未包含原生节点/热阻表，虚线不代表 Motor-CAD 的完整热网络。'}</span></div>`;
  }
  function enhanceThermalViewer(){
    const viewer=state.viewer,canvas=$q('#viewerCanvas');if(!viewer||!canvas)return;const existing=canvas.innerHTML;
    canvas.innerHTML=`<section class="thermal-topology-v031"><div class="thermal-topology-head-v031"><div><span class="eyebrow">THERMAL · TOPOLOGY</span><h3>整体热路径</h3><p>先定位温度与损耗在机壳、定子、绕组、转子和磁体之间的关系，再查看详细温升曲线。</p></div><div class="segmented"><button type="button" class="active" data-thermal-mode-v031="temperature">节点温度</button><button type="button" data-thermal-mode-v031="power">损耗源</button></div></div><div id="thermalTopologyStageV031">${renderThermalTopology(viewer,'temperature')}</div></section><section class="thermal-detail-results-v031"><div class="viewer-section-title"><h3>详细热结果</h3></div>${existing}</section>`;
    $$q('[data-thermal-mode-v031]',canvas).forEach(button=>button.addEventListener('click',()=>{$$q('[data-thermal-mode-v031]',canvas).forEach(row=>row.classList.toggle('active',row===button));const stage=$q('#thermalTopologyStageV031');if(stage)stage.innerHTML=renderThermalTopology(viewer,button.dataset.thermalModeV031)}));
  }

  const previousRenderViewerModule=window.renderViewerModule;
  if(typeof previousRenderViewerModule==='function'){
    window.renderViewerModule=function(key){const result=previousRenderViewerModule.apply(this,arguments);if(key==='fea')enhanceFEAViewer();if(key==='thermal')enhanceThermalViewer();return result};
  }
  const previousOpenWorkspaceDesign=window.openWorkspaceDesign;
  if(typeof previousOpenWorkspaceDesign==='function'){
    window.openWorkspaceDesign=async function(){const result=await previousOpenWorkspaceDesign.apply(this,arguments);await decorateDesignViewer();return result};
  }
  const previousSelectWorkspaceRevision=window.selectWorkspaceRevision;
  if(typeof previousSelectWorkspaceRevision==='function'){
    window.selectWorkspaceRevision=function(){const result=previousSelectWorkspaceRevision.apply(this,arguments);const summary=$q('#workspaceRevisionSummary');if(summary)delete summary.dataset.v031Wrapped;decorateDesignViewer();return result};
  }

  const flowObserver=new MutationObserver(()=>{const bar=$q('#engineerFlowBarV030');if(bar&&!bar.querySelector('.workflow-steps-v031')&&bar.dataset.v031Applying!=='1')queueMicrotask(upgradeFlowBar)});
  flowObserver.observe(document.body,{childList:true,subtree:true});
  window.addEventListener('mcs:route-ready',()=>setTimeout(()=>{upgradeFlowBar();if($q('.tab.active')?.id==='workspace'&&state.workspaceRevision)decorateDesignViewer()},0));
  document.addEventListener('change',event=>{if(event.target.id==='userMode')setTimeout(upgradeFlowBar,0)},true);
  window.MCSVisualV031={renderWorkbenchView,decorateDesignViewer,upgradeFlowBar,enhanceFEAViewer,enhanceThermalViewer,state:visualState};
  setTimeout(upgradeFlowBar,80);
})();
