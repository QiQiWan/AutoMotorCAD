/* V0.64 Geometry renderer. Owns radial and longitudinal / axial-stack previews. */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before geometry renderer');
  const {safe,number,clamp,fmt,selectAttribute,polar,ringSegment,viewData,authorityStrip}=U;
  function radialView(ctx){
    const {data,values,editable}=viewData(ctx),template=data.template||{};
    const slots=clamp(Math.round(number(values.slot_count,12)),3,72),poles=clamp(Math.round(number(values.pole_count,8)),2,40);
    const od=Math.max(20,number(values.stator_outer_diameter,140)),id=clamp(number(values.stator_inner_diameter,80),5,od*.93);
    const housingD=Math.max(od,number(values.housing_diameter,od*1.08)),shaftD=clamp(number(values.shaft_diameter,id*.28),1,id*.8);
    const gap=Math.max(.05,number(values.air_gap,1)),magnet=Math.max(.1,number(values.magnet_thickness,4));
    const tooth=Math.max(.1,number(values.tooth_width,6)),opening=Math.max(.05,number(values.slot_opening,3)),slotWidthMm=Math.max(opening,number(values.slot_width,opening*2.8));
    const sleeve=Math.max(0,number(values.sleeve_thickness,0)),banding=Math.max(0,number(values.banding_thickness,0));
    const cx=360,cy=255,statorOuter=198,radialScale=statorOuter/(od/2),statorInner=clamp((id/2)*radialScale,70,statorOuter-24);
    const housingR=clamp((housingD/2)*radialScale,statorOuter+7,226),airgapOuter=statorInner;
    const rotorEnvelope=Math.max(35,airgapOuter-clamp(gap*radialScale,2.5,10));
    const sleevePx=clamp((sleeve+banding)*radialScale,0,11),magnetBand=clamp(magnet*radialScale,5,22),rotorSteelOuter=Math.max(30,rotorEnvelope-sleevePx-magnetBand);
    const shaftR=clamp((shaftD/2)*radialScale,13,Math.max(14,rotorSteelOuter*.72));
    const slotPitch=360/slots,slotArcLength=Math.PI*id/slots,slotAngular=clamp(slotWidthMm/(slotArcLength||1),.12,.82)*slotPitch;
    let fins='',slotsSvg='',magnets='',slotCopper='';
    for(let i=0;i<24;i++){
      const a=i*15,p1=polar(cx,cy,housingR+1,a),p2=polar(cx,cy,Math.min(244,housingR+13+(i%2)*5),a);
      fins+=`<line x1="${p1[0].toFixed(1)}" y1="${p1[1].toFixed(1)}" x2="${p2[0].toFixed(1)}" y2="${p2[1].toFixed(1)}"/>`;
    }
    for(let i=0;i<slots;i++){
      const center=i*slotPitch,start=center-slotAngular/2,end=center+slotAngular/2;
      slotsSvg+=`<path d="${ringSegment(cx,cy,statorInner+3,statorOuter-8,start,end)}" ${selectAttribute('slot_width',editable)||selectAttribute('slot_count',editable)} data-schematic-part="stator-slot winding"/>`;
      const fill=clamp(number(values.slot_fill_factor,.42),.05,.95),copperOuter=statorInner+8+(statorOuter-statorInner-22)*fill;
      slotCopper+=`<path d="${ringSegment(cx,cy,statorInner+8,copperOuter,start+slotAngular*.12,end-slotAngular*.12)}" class="phase-${i%3}" ${selectAttribute('slot_fill_factor',editable)} data-schematic-part="winding stator-slot"/>`;
    }
    const polePitch=360/poles,arc=clamp(number(values.magnet_arc_deg,140)/180,.2,.98)*polePitch;
    for(let i=0;i<poles;i++){
      const center=i*polePitch;
      magnets+=`<path d="${ringSegment(cx,cy,rotorSteelOuter,rotorSteelOuter+magnetBand,center-arc/2,center+arc/2)}" class="${i%2?'south':'north'}" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/>`;
    }
    const q=number((data.precheck?.winding?.derived||{}).slots_per_phase_path,NaN);
    return`<div class="motorcad-view-v031 radial-view-v031">
      <div class="visual-heading-v031"><div><span class="eyebrow">GEOMETRY · RADIAL</span><h3>径向截面与尺寸联动</h3><p>核心结构化尺寸直接驱动示意；Motor-CAD 全量参数仍可在“全部参数”中管理并由原生模型验证。</p></div><div class="visual-facts-v031"><span>${slots} 槽</span><span>${poles} 极</span><span>槽距 ${Number.isFinite(q)?fmt(q):'—'} / 相 / 支路</span></div></div>
      <div class="radial-canvas-v031"><svg viewBox="0 0 720 520" role="img" aria-label="径向电机参数化截面">
        <defs><marker id="arrowV031" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z"/></marker><linearGradient id="rotorSteelV031" x1="0" x2="1"><stop offset="0" stop-color="#52687f"/><stop offset=".5" stop-color="#91a0b2"/><stop offset="1" stop-color="#52687f"/></linearGradient></defs>
        <g class="housing-fins-v031">${fins}</g><circle cx="${cx}" cy="${cy}" r="${housingR}" class="housing-v031" ${selectAttribute('housing_diameter',editable)} data-schematic-part="housing"/>
        <circle cx="${cx}" cy="${cy}" r="${statorOuter}" class="stator-v031" ${selectAttribute('stator_outer_diameter',editable)} data-schematic-part="stator"/>
        <circle cx="${cx}" cy="${cy}" r="${statorInner}" class="bore-v031" ${selectAttribute('stator_inner_diameter',editable)} data-schematic-part="airgap stator"/>
        <g class="slots-v031">${slotsSvg}</g><g class="slot-copper-v031">${slotCopper}</g>
        <circle cx="${cx}" cy="${cy}" r="${rotorEnvelope+1}" class="airgap-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/>
        <circle cx="${cx}" cy="${cy}" r="${rotorSteelOuter}" fill="url(#rotorSteelV031)" class="rotor-v031" data-schematic-part="rotor"/>
        <g class="magnets-v031">${magnets}</g>${sleevePx>0?`<circle cx="${cx}" cy="${cy}" r="${rotorEnvelope}" class="rotor-sleeve-v066" ${selectAttribute(sleeve>0?'sleeve_thickness':'banding_thickness',editable)} data-schematic-part="rotor sleeve"/>`:''}
        <circle cx="${cx}" cy="${cy}" r="${shaftR}" class="shaft-v031" ${selectAttribute('shaft_diameter',editable)} data-schematic-part="shaft"/>
        <g class="dimension-v031"><line x1="${cx-statorOuter}" y1="488" x2="${cx+statorOuter}" y2="488"/><line x1="${cx-statorOuter}" y1="476" x2="${cx-statorOuter}" y2="498"/><line x1="${cx+statorOuter}" y1="476" x2="${cx+statorOuter}" y2="498"/><text x="${cx}" y="514" text-anchor="middle">定子外径 ${fmt(od)} mm</text><line x1="${cx+rotorEnvelope}" y1="${cy}" x2="${cx+statorInner}" y2="${cy}" marker-start="url(#arrowV031)" marker-end="url(#arrowV031)"/><text x="${cx+(rotorEnvelope+statorInner)/2}" y="${cy-10}" text-anchor="middle">g ${fmt(gap)} mm</text></g>
        <g class="visual-labels-v031"><text x="38" y="42">${safe(template.topology||template.motor_type||'Motor model')}</text><text x="38" y="66">OD ${fmt(od)} · ID ${fmt(id)} · 槽宽 ${fmt(slotWidthMm)} · 齿宽 ${fmt(tooth)} mm</text></g>
      </svg></div>${authorityStrip('结构化参数即时预览；真实槽型、转子细节与区域边界以 Motor-CAD 原生几何为最终依据')}
    </div>`;
  }

  function radialMachineAxialView(ctx){
    const {data,values,editable}=viewData(ctx),template=data.template||{};
    const statorLen=Math.max(8,number(values.stator_lamination_length,50)),rotorLen=Math.max(8,number(values.rotor_lamination_length,statorLen*.9)),magLen=Math.max(4,number(values.magnet_length,rotorLen));
    const od=Math.max(20,number(values.stator_outer_diameter,80)),id=clamp(number(values.stator_inner_diameter,41.6),5,od*.94),housingD=Math.max(od,number(values.housing_diameter,od*1.07));
    const shaftD=clamp(number(values.shaft_diameter,id*.48),2,id*.82),shaftHole=clamp(number(values.shaft_hole_diameter,0),0,shaftD*.86);
    const gap=Math.max(.02,number(values.air_gap,.8)),mag=Math.max(.05,number(values.magnet_thickness,4)),sleeve=Math.max(0,number(values.sleeve_thickness,0)),banding=Math.max(0,number(values.banding_thickness,0));
    const axialMax=Math.max(statorLen,rotorLen,magLen,20),axScale=340/axialMax,statorW=clamp(statorLen*axScale,170,380),rotorW=clamp(rotorLen*axScale,150,390),magW=clamp(magLen*axScale,120,400);
    const sx=410-statorW/2,rx=410-rotorW/2,mx=410-magW/2;
    const radialScale=155/(od/2),outerR=155,boreR=clamp((id/2)*radialScale,70,outerR-28),housingR=clamp((housingD/2)*radialScale,outerR+8,185);
    const gapPx=clamp(gap*radialScale,3,11),sleevePx=clamp((sleeve+banding)*radialScale,0,10),magPx=clamp(mag*radialScale,5,23);
    const rotorEnvelopeR=boreR-gapPx,magOuterR=rotorEnvelopeR-sleevePx,coreR=Math.max(25,magOuterR-magPx),shaftR=clamp((shaftD/2)*radialScale,12,coreR-8),shaftHoleR=clamp((shaftHole/2)*radialScale,0,shaftR-5);
    const cy=250,topOuter=cy-outerR,topBore=cy-boreR,bottomBore=cy+boreR,bottomOuter=cy+outerR;
    const topRotor=cy-coreR,bottomRotor=cy+coreR,topMag=cy-magOuterR,bottomMag=cy+magOuterR;
    const housingTop=cy-housingR,housingBottom=cy+housingR;
    const statorBuild=outerR-boreR,slotInner=boreR+statorBuild*.18,slotOuter=boreR+statorBuild*.64,coilYTop=cy-slotOuter,coilYBottom=cy+slotInner,coilH=Math.max(9,slotOuter-slotInner);
    const endReach=clamp(44+number(values.turns_per_coil,100)*.03,48,75),coilLeft=sx-endReach,coilRight=sx+statorW+endReach;
    const coilPath=(offset=0)=>`M${sx},${coilYTop+offset} L${sx+statorW},${coilYTop+offset} Q${coilRight},${coilYTop+offset} ${coilRight},${cy+offset} Q${coilRight},${coilYBottom+offset} ${sx+statorW},${coilYBottom+offset} L${sx},${coilYBottom+offset} Q${coilLeft},${coilYBottom+offset} ${coilLeft},${cy+offset} Q${coilLeft},${coilYTop+offset} ${sx},${coilYTop+offset}`;
    const bearingX1=72,bearingX2=704,bearingH=Math.max(44,shaftR*2+22),shaftY=cy-shaftR;
    return`<div class="motorcad-view-v031 axial-view-v031 longitudinal-shaft-section-v066">
      <div class="visual-heading-v031"><div><span class="eyebrow">GEOMETRY · SHAFT-AXIS SECTION</span><h3>径向磁通电机沿转轴中心线装配剖面</h3><p>剖切平面通过转轴中心线。上、下半部依次显示定子轭/槽、绕组有效边、气隙、表贴磁体、转子叠片和转轴，并显示两端端绕组回路。</p></div><div class="visual-facts-v031"><span>定子叠长 ${fmt(statorLen)} mm</span><span>转子叠长 ${fmt(rotorLen)} mm</span><span>轴径 ${fmt(shaftD)} mm</span></div></div>
      <div class="axial-canvas-v031"><svg viewBox="0 0 820 500" role="img" aria-label="沿转轴中心线的径向磁通电机纵向装配剖面">
        <defs><linearGradient id="lamV066" x1="0" x2="1"><stop offset="0" stop-color="#b94b42"/><stop offset=".5" stop-color="#df7565"/><stop offset="1" stop-color="#b94b42"/></linearGradient><linearGradient id="axRotorSteelV066" x1="0" x2="1"><stop offset="0" stop-color="#637589"/><stop offset=".5" stop-color="#a5b0bf"/><stop offset="1" stop-color="#637589"/></linearGradient><marker id="axArrowV066" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z"/></marker></defs>
        <rect x="42" y="${housingTop-15}" width="736" height="${housingBottom-housingTop+30}" rx="44" class="ax-housing-v031" ${selectAttribute('housing_diameter',editable)} data-schematic-part="housing"/>
        <rect x="${sx}" y="${topOuter}" width="${statorW}" height="${topBore-topOuter}" rx="4" fill="url(#lamV066)" ${selectAttribute('stator_lamination_length',editable)} data-schematic-part="stator"/>
        <rect x="${sx}" y="${bottomBore}" width="${statorW}" height="${bottomOuter-bottomBore}" rx="4" fill="url(#lamV066)" ${selectAttribute('stator_outer_diameter',editable)} data-schematic-part="stator"/>
        <rect x="${sx+5}" y="${coilYTop-4}" width="${statorW-10}" height="${coilH+8}" rx="5" class="ax-slot-window-v066" ${selectAttribute('slot_depth',editable)} data-schematic-part="stator-slot"/>
        <rect x="${sx+5}" y="${cy+slotInner-4}" width="${statorW-10}" height="${coilH+8}" rx="5" class="ax-slot-window-v066" ${selectAttribute('slot_depth',editable)} data-schematic-part="stator-slot"/>
        <path d="${coilPath(-4)}" class="ax-coil-loop-v066 phase-a" ${selectAttribute('turns_per_coil',editable)} data-schematic-part="winding"/><path d="${coilPath(4)}" class="ax-coil-loop-v066 phase-b" data-schematic-part="winding"/>
        <rect x="${mx}" y="${topMag}" width="${magW}" height="${magPx}" rx="3" class="ax-magnet-v031 north" ${selectAttribute('magnet_length',editable)} data-schematic-part="magnet rotor"/>
        <rect x="${mx}" y="${bottomMag-magPx}" width="${magW}" height="${magPx}" rx="3" class="ax-magnet-v031 south" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/>
        ${sleevePx>0?`<rect x="${mx}" y="${topMag-sleevePx}" width="${magW}" height="${sleevePx}" class="ax-sleeve-v066" ${selectAttribute(sleeve>0?'sleeve_thickness':'banding_thickness',editable)} data-schematic-part="sleeve"/><rect x="${mx}" y="${bottomMag}" width="${magW}" height="${sleevePx}" class="ax-sleeve-v066" data-schematic-part="sleeve"/>`:''}
        <rect x="${mx}" y="${topMag-sleevePx-gapPx}" width="${magW}" height="${gapPx}" class="ax-gap-band-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><rect x="${mx}" y="${bottomMag+sleevePx}" width="${magW}" height="${gapPx}" class="ax-gap-band-v031" data-schematic-part="airgap"/>
        <rect x="${rx}" y="${topRotor}" width="${rotorW}" height="${Math.max(2,coreR-shaftR)}" rx="3" fill="url(#axRotorSteelV066)" ${selectAttribute('rotor_lamination_length',editable)} data-schematic-part="rotor"/><rect x="${rx}" y="${cy+shaftR}" width="${rotorW}" height="${Math.max(2,coreR-shaftR)}" rx="3" fill="url(#axRotorSteelV066)" data-schematic-part="rotor"/>
        <rect x="28" y="${shaftY}" width="764" height="${shaftR*2}" rx="${shaftR}" class="ax-shaft-v031" ${selectAttribute('shaft_diameter',editable)} data-schematic-part="shaft"/>${shaftHoleR>1?`<rect x="28" y="${cy-shaftHoleR}" width="764" height="${shaftHoleR*2}" rx="${shaftHoleR}" class="ax-shaft-hole-v066" ${selectAttribute('shaft_hole_diameter',editable)} data-schematic-part="shaft-hole"/>`:''}
        <rect x="${bearingX1}" y="${cy-bearingH/2}" width="34" height="${bearingH}" class="ax-bearing-v031"/><rect x="${bearingX2}" y="${cy-bearingH/2}" width="34" height="${bearingH}" class="ax-bearing-v031"/>
        <g class="dimension-v031"><line x1="${sx}" y1="458" x2="${sx+statorW}" y2="458" marker-start="url(#axArrowV066)" marker-end="url(#axArrowV066)"/><text x="410" y="483" text-anchor="middle">定子叠长 ${fmt(statorLen)} mm</text><line x1="${mx+magW+22}" y1="${topBore}" x2="${mx+magW+22}" y2="${topMag-sleevePx}" marker-start="url(#axArrowV066)" marker-end="url(#axArrowV066)"/><text x="${mx+magW+34}" y="${topBore-gapPx/2+3}">g ${fmt(gap)} mm</text></g>
        <g class="ax-assembly-labels-v066"><text x="118" y="137">端绕组</text><line x1="164" y1="141" x2="${coilLeft+8}" y2="${cy-28}"/><text x="342" y="114">槽内有效导体</text><line x1="407" y1="119" x2="407" y2="${coilYTop-5}"/></g>
        <g class="visual-labels-v031"><text x="36" y="28">${safe(template.topology||template.motor_type||'SPM')} · 轴线方向 →</text><text x="36" y="47">纵向尺寸与径向尺寸均由当前草稿驱动；气隙/薄套筒保留最小像素厚度以便识别</text></g>
      </svg></div>${authorityStrip('轴中心剖面的参数化装配示意；端绕组形状用于拓扑表达，真实几何与端部尺寸以 Motor-CAD 原生模型为最终依据')}
    </div>`;
  }

  function axialFluxAxialView(ctx){
    const {data,values,editable}=viewData(ctx),template=data.template||{};
    const gap=Math.max(.05,number(values.air_gap,1)),mag=Math.max(.1,number(values.magnet_thickness,4)),length=Math.max(8,number(values.stator_lamination_length,28));
    const od=Math.max(20,number(values.stator_outer_diameter,180)),id=Math.max(5,number(values.stator_inner_diameter,80));
    const discH=276,discY=112,statorW=clamp(length*1.4,38,72),rotorW=44,magW=clamp(mag*2.0,8,18),gapW=clamp(gap*8,8,16),cx=360;
    const statorX=cx-statorW/2,leftRotorX=statorX-gapW-magW-rotorW,rightRotorX=statorX+statorW+gapW+magW;
    return`<div class="motorcad-view-v031 axial-view-v031 afm-axial-v061"><div class="visual-heading-v031"><div><span class="eyebrow">GEOMETRY · AXIAL FLUX STACK</span><h3>轴向磁通电机盘式堆叠剖面</h3><p>沿转轴方向显示转子盘—磁体—轴向气隙—定子盘的堆叠关系；具体单/双转子结构以当前 Motor-CAD 模型为准。</p></div><div class="visual-facts-v031"><span>参考厚度 ${fmt(length)} mm</span><span>外径 ${fmt(od)} mm</span><span>内径 ${fmt(id)} mm</span></div></div><div class="axial-canvas-v031"><svg viewBox="0 0 720 500" role="img" aria-label="轴向磁通电机盘式堆叠剖面"><defs><marker id="afmArrowV061" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z"/></marker></defs><rect x="66" y="54" width="588" height="392" rx="44" class="ax-housing-v031"/><rect x="24" y="235" width="672" height="30" rx="15" class="ax-shaft-v031"/><rect x="${leftRotorX}" y="${discY}" width="${rotorW}" height="${discH}" rx="5" class="afm-rotor-disc-v061" data-schematic-part="rotor"/><rect x="${leftRotorX+rotorW}" y="${discY+18}" width="${magW}" height="${discH-36}" rx="3" class="ax-magnet-v031 north" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet"/><rect x="${leftRotorX+rotorW+magW}" y="${discY+18}" width="${gapW}" height="${discH-36}" class="ax-gap-band-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><rect x="${statorX}" y="${discY}" width="${statorW}" height="${discH}" rx="6" class="afm-stator-disc-v061" ${selectAttribute('stator_lamination_length',editable)} data-schematic-part="stator"/><rect x="${statorX+8}" y="${discY+30}" width="${statorW-16}" height="70" rx="12" class="afm-coil-v061" data-schematic-part="winding"/><rect x="${statorX+8}" y="${discY+discH-100}" width="${statorW-16}" height="70" rx="12" class="afm-coil-v061" data-schematic-part="winding"/><rect x="${statorX+statorW}" y="${discY+18}" width="${gapW}" height="${discH-36}" class="ax-gap-band-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><rect x="${statorX+statorW+gapW}" y="${discY+18}" width="${magW}" height="${discH-36}" rx="3" class="ax-magnet-v031 south" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet"/><rect x="${rightRotorX}" y="${discY}" width="${rotorW}" height="${discH}" rx="5" class="afm-rotor-disc-v061" data-schematic-part="rotor"/><g class="afm-flux-arrow-v061"><line x1="${leftRotorX+rotorW/2}" y1="86" x2="${rightRotorX+rotorW/2}" y2="86" marker-end="url(#afmArrowV061)"/><text x="360" y="77" text-anchor="middle">轴向磁通方向</text></g><g class="visual-labels-v031"><text x="32" y="30">${safe(template.topology||template.motor_type||'轴向磁通电机')} · 轴线方向 →</text><text x="32" y="48">盘厚、磁体和气隙按当前结构化参数驱动；拓扑层数未结构化时使用双转子示意</text></g></svg></div>${authorityStrip('轴向磁通盘式堆叠关系示意')}</div>`;
  }

  function axialView(ctx){
    const template=(ctx.data||{}).template||{};
    return template.is_axial?axialFluxAxialView(ctx):radialMachineAxialView(ctx);
  }

  function render(view,ctx){
    if(view==='radial'||view==='geometry')return radialView(ctx);
    if(view==='axial')return axialView(ctx);
    return null;
  }
  window.MCSDesignGeometry={render,radialView,radialMachineAxialView,axialFluxAxialView,axialView};
})();
