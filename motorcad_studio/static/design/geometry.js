/* V0.71 PM motor-object geometry renderer.
 * RFPM-SPM, RFPM-IPM, outer-rotor PM and AFPM consume MCSPMMotorObject.
 * Renderer code only projects a topology object; raw Design dictionaries no longer
 * determine topology-specific geometry inside this module.
 */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before geometry renderer');
  const {safe,number,clamp,fmt,selectAttribute,polar,ringSegment,viewData,authorityStrip}=U;
  const svgText=(x,y,text,attrs='')=>`<text x="${x}" y="${y}" ${attrs}>${safe(text)}</text>`;
  function facts(object){return`<span>${object.derived.slot_count||'—'} 槽</span><span>${object.derived.pole_count||'—'} 极</span><span>${safe(object.topology_id)}</span>`}
  function heading(object,title,description,extra=''){return`<div class="visual-heading-v031"><div><span class="eyebrow">MOTOR OBJECT · ${safe(object.visualization?.radial_provider||object.topology_id)}</span><h3>${safe(title)}</h3><p>${safe(description)}</p></div><div class="visual-facts-v031">${extra||facts(object)}</div></div>`}

  function statorSlots(cx,cy,innerR,outerR,object,editable,{copper=true}={}){
    const slot=object.stator.slot,slots=clamp(slot.count||12,3,96),pitch=360/slots,meanD=Math.max(1,object.stator.inner_diameter_mm),arcLength=Math.PI*meanD/slots,angular=clamp((slot.width_mm||slot.opening_mm||1)/(arcLength||1),.11,.82)*pitch;
    let cuts='',conductors='';
    for(let i=0;i<slots;i++){
      const c=i*pitch,start=c-angular/2,end=c+angular/2;
      cuts+=`<path d="${ringSegment(cx,cy,innerR+3,outerR-7,start,end)}" ${selectAttribute('slot_width',editable)||selectAttribute('slot_count',editable)} data-schematic-part="stator stator-slot"/>`;
      if(copper){const fill=clamp(number(object.parameters.slot_fill_factor,.42),.05,.95),copperOuter=innerR+8+(outerR-innerR-20)*fill;conductors+=`<path d="${ringSegment(cx,cy,innerR+8,copperOuter,start+angular*.14,end-angular*.14)}" class="phase-${i%3}" ${selectAttribute('slot_fill_factor',editable)} data-schematic-part="winding stator-slot"/>`}
    }
    return{cuts,conductors};
  }

  function rfpmBase(object,editable){
    const s=object.stator,r=object.rotor,cx=360,cy=255,outerR=198,scale=outerR/Math.max(1,s.outer_diameter_mm/2),innerR=clamp((s.inner_diameter_mm/2)*scale,68,outerR-24),housingR=clamp((Math.max(s.outer_diameter_mm,object.housing.diameter_mm||s.outer_diameter_mm)/2)*scale,outerR+7,230),rotorEnvelope=clamp((r.outer_diameter_mm/2)*scale,28,innerR-2),shaftR=clamp((object.shaft.diameter_mm/2)*scale,11,Math.max(13,rotorEnvelope*.72));
    const slots=statorSlots(cx,cy,innerR,outerR,object,editable);
    let fins='';for(let i=0;i<24;i++){const a=i*15,p1=polar(cx,cy,housingR+1,a),p2=polar(cx,cy,Math.min(244,housingR+12+(i%2)*4),a);fins+=`<line x1="${p1[0].toFixed(1)}" y1="${p1[1].toFixed(1)}" x2="${p2[0].toFixed(1)}" y2="${p2[1].toFixed(1)}"/>`}
    return{cx,cy,outerR,scale,innerR,housingR,rotorEnvelope,shaftR,slots,fins};
  }

  function spmRadial(object,editable){
    const b=rfpmBase(object,editable),m=object.rotor.magnet,poles=clamp(object.derived.pole_count||8,2,48),pitch=360/poles,arc=clamp((m.arc_deg||140)/180,.18,.98)*pitch,magPx=clamp((m.thickness_mm||1)*b.scale,4,24),coreR=Math.max(b.shaftR+8,b.rotorEnvelope-magPx);let mags='';
    for(let i=0;i<poles;i++){const c=i*pitch;mags+=`<path d="${ringSegment(b.cx,b.cy,coreR,b.rotorEnvelope,c-arc/2,c+arc/2)}" class="${i%2?'south':'north'}" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/>`}
    return`${heading(object,'RFPM-SPM 径向截面','表贴磁体位于内转子外表面；定子槽、气隙、磁体和转子包络由同一个 PM Motor Object 驱动。')}
      <div class="radial-canvas-v031"><svg viewBox="0 0 720 520" role="img" aria-label="RFPM SPM motor-object radial section"><g class="housing-fins-v031">${b.fins}</g><circle cx="${b.cx}" cy="${b.cy}" r="${b.housingR}" class="housing-v031" ${selectAttribute('housing_diameter',editable)} data-schematic-part="housing"/><circle cx="${b.cx}" cy="${b.cy}" r="${b.outerR}" class="stator-v031" data-schematic-part="stator"/><circle cx="${b.cx}" cy="${b.cy}" r="${b.innerR}" class="bore-v031" data-schematic-part="airgap stator"/><g class="slots-v031">${b.slots.cuts}</g><g class="slot-copper-v031">${b.slots.conductors}</g><circle cx="${b.cx}" cy="${b.cy}" r="${b.rotorEnvelope+2}" class="airgap-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><circle cx="${b.cx}" cy="${b.cy}" r="${coreR}" class="rotor-v031" data-schematic-part="rotor"/><g class="magnets-v031 pm-object-magnets-v071">${mags}</g><circle cx="${b.cx}" cy="${b.cy}" r="${b.shaftR}" class="shaft-v031" ${selectAttribute('shaft_diameter',editable)} data-schematic-part="shaft"/>${svgText(28,42,`SPM · Rotor envelope ${fmt(object.rotor.outer_diameter_mm)} mm`)}${svgText(28,66,`Air gap ${fmt(object.derived.air_gap_mm)} mm · Magnet ${fmt(m.thickness_mm)} mm`)}</svg></div>`;
  }

  function ipmMagnets(cx,cy,rotorR,object,editable){
    const m=object.rotor.magnet,poles=clamp(object.derived.pole_count||8,2,48),pitch=360/poles,v=clamp(m.v_angle_deg||130,30,175),baseWidth=clamp((m.width_mm||object.rotor.outer_diameter_mm*.22)*rotorR/Math.max(1,object.rotor.outer_diameter_mm/2),18,rotorR*.55),thickPx=clamp((m.thickness_mm||3)*rotorR/Math.max(1,object.rotor.outer_diameter_mm/2),4,16),embed=clamp((m.embed_depth_mm||2)*rotorR/Math.max(1,object.rotor.outer_diameter_mm/2),3,18),layers=clamp(Math.round(number(m.layers,1)),1,4),layerPitch=thickPx+clamp(number(m.separation_mm,2)*rotorR/Math.max(1,object.rotor.outer_diameter_mm/2),3,14);let out='';
    for(let i=0;i<poles;i++){
      const center=i*pitch,local=(180-v)/2;
      for(let layer=0;layer<layers;layer++){
        const widthPx=Math.max(12,baseWidth-layer*layerPitch*.55),rr=Math.max(16,rotorR-embed-widthPx*.24-layer*layerPitch),p=polar(cx,cy,rr,center);
        out+=`<g transform="translate(${p[0].toFixed(1)} ${p[1].toFixed(1)}) rotate(${center})" ${selectAttribute(layer?'magnet_layers':'pole_v_angle_deg',editable)} data-schematic-part="magnet rotor" data-ipm-layer="${layer+1}"><rect x="${(-widthPx).toFixed(1)}" y="${(-thickPx/2).toFixed(1)}" width="${widthPx.toFixed(1)}" height="${thickPx.toFixed(1)}" rx="2" class="${i%2?'south':'north'}" transform="rotate(${-local})"/><rect x="0" y="${(-thickPx/2).toFixed(1)}" width="${widthPx.toFixed(1)}" height="${thickPx.toFixed(1)}" rx="2" class="${i%2?'south':'north'}" transform="rotate(${local})"/></g>`;
      }
    }
    return out;
  }

  function ipmRadial(object,editable){
    const b=rfpmBase(object,editable),m=object.rotor.magnet,mags=ipmMagnets(b.cx,b.cy,b.rotorEnvelope,object,editable);
    return`${heading(object,'RFPM-IPM 径向截面','V 型磁体嵌入转子铁心内部；磁体宽度、厚度、嵌入深度和 V 角由 IPM Rotor Object 统一解释。',`<span>${object.derived.slot_count} 槽</span><span>${object.derived.pole_count} 极</span><span>V 角 ${fmt(m.v_angle_deg)}°</span><span>${fmt(m.layers,0)} 层</span>`)}
      <div class="radial-canvas-v031"><svg viewBox="0 0 720 520" role="img" aria-label="RFPM IPM motor-object radial section"><g class="housing-fins-v031">${b.fins}</g><circle cx="${b.cx}" cy="${b.cy}" r="${b.housingR}" class="housing-v031" data-schematic-part="housing"/><circle cx="${b.cx}" cy="${b.cy}" r="${b.outerR}" class="stator-v031" data-schematic-part="stator"/><circle cx="${b.cx}" cy="${b.cy}" r="${b.innerR}" class="bore-v031" data-schematic-part="airgap stator"/><g>${b.slots.cuts}</g><g>${b.slots.conductors}</g><circle cx="${b.cx}" cy="${b.cy}" r="${b.rotorEnvelope+2}" class="airgap-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><circle cx="${b.cx}" cy="${b.cy}" r="${b.rotorEnvelope}" class="rotor-v031" data-schematic-part="rotor"/><g class="magnets-v031 pm-object-magnets-v071">${mags}</g><circle cx="${b.cx}" cy="${b.cy}" r="${b.shaftR}" class="shaft-v031" data-schematic-part="shaft"/>${svgText(28,42,`IPM · Rotor ${fmt(object.rotor.outer_diameter_mm)} mm`)}${svgText(28,66,`Magnet W ${fmt(m.width_mm)} · T ${fmt(m.thickness_mm)} · embed ${fmt(m.embed_depth_mm)} mm`)}</svg></div>`;
  }

  function outerRotorRadial(object,editable){
    const s=object.stator,r=object.rotor,m=r.magnet,cx=360,cy=255,maxD=Math.max(r.outer_diameter_mm,s.outer_diameter_mm,object.housing.diameter_mm||0,1),scale=218/(maxD/2),statorOuter=clamp((s.outer_diameter_mm/2)*scale,80,176),statorInner=clamp((s.inner_diameter_mm/2)*scale,28,statorOuter-22),rotorOuter=218,rotorInner=clamp((r.inner_diameter_mm/2)*scale,statorOuter+6,rotorOuter-12),magPx=clamp((m.thickness_mm||1)*scale,4,18),magInner=Math.max(statorOuter+4,rotorInner-magPx),shaftR=clamp((object.shaft.diameter_mm/2)*scale,10,statorInner-10),slots=statorSlots(cx,cy,statorInner,statorOuter,object,editable),poles=clamp(object.derived.pole_count||8,2,64),pitch=360/poles,arc=clamp((m.arc_deg||140)/180,.15,.98)*pitch;let mags='';
    for(let i=0;i<poles;i++){const c=i*pitch;mags+=`<path d="${ringSegment(cx,cy,magInner,rotorInner,c-arc/2,c+arc/2)}" class="${i%2?'south':'north'}" data-schematic-part="magnet rotor"/>`}
    const warn=object.warnings?.[0]?`<div class="visual-object-warning-v071">${safe(object.warnings[0])}</div>`:'';
    return`${heading(object,'Outer-Rotor PM 径向截面','定子位于内部，气隙和磁体位于定子外侧，外转子铁心形成最外层旋转包络。',`<span>${object.derived.slot_count} 槽</span><span>${object.derived.pole_count} 极</span><span>外转子 ${fmt(r.outer_diameter_mm)} mm</span>`)}${warn}<div class="radial-canvas-v031"><svg viewBox="0 0 720 520" role="img" aria-label="outer rotor PM motor-object radial section"><circle cx="${cx}" cy="${cy}" r="${rotorOuter}" class="rotor-v031" ${selectAttribute('rotor_outer_diameter',editable)} data-schematic-part="rotor"/><circle cx="${cx}" cy="${cy}" r="${rotorInner}" class="bore-v031" data-schematic-part="rotor airgap"/><g class="magnets-v031 pm-object-magnets-v071">${mags}</g><circle cx="${cx}" cy="${cy}" r="${statorOuter+3}" class="airgap-v031" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><circle cx="${cx}" cy="${cy}" r="${statorOuter}" class="stator-v031" data-schematic-part="stator"/><circle cx="${cx}" cy="${cy}" r="${statorInner}" class="bore-v031" data-schematic-part="stator"/><g>${slots.cuts}</g><g>${slots.conductors}</g><circle cx="${cx}" cy="${cy}" r="${shaftR}" class="shaft-v031" data-schematic-part="shaft"/>${svgText(28,42,'BPMOR · stator inside / rotor outside')}${svgText(28,66,`Normalized stator ${fmt(s.inner_diameter_mm)}–${fmt(s.outer_diameter_mm)} mm`)}</svg></div>`;
  }

  function afpmFace(object,editable){
    const s=object.stator,r=object.rotor,m=r.magnet,cx=360,cy=255,outerR=205,scale=outerR/Math.max(1,s.outer_diameter_mm/2),innerR=clamp((s.inner_diameter_mm/2)*scale,55,outerR-55),rotorOuter=clamp((r.outer_diameter_mm/2)*scale,innerR+35,224),rotorInner=clamp((r.inner_diameter_mm/2)*scale,32,rotorOuter-55),slots=clamp(s.slot.count||12,3,72),slotPitch=360/slots,poles=clamp(object.derived.pole_count||10,2,48),polePitch=360/poles,arc=clamp((m.arc_deg||140)/180,.2,.96)*polePitch;let teeth='',mags='',numbers='';
    for(let i=0;i<slots;i++){const c=i*slotPitch,w=slotPitch*.58;teeth+=`<path d="${ringSegment(cx,cy,innerR,outerR,c-w/2,c+w/2)}" class="stator-v031" data-schematic-part="stator stator-slot"/>`;const p=polar(cx,cy,outerR+14,c);if(i<48)numbers+=`<text x="${p[0].toFixed(1)}" y="${(p[1]+3).toFixed(1)}" class="winding-slot-number-v066" text-anchor="middle">${i+1}</text>`}
    for(let i=0;i<poles;i++){const c=i*polePitch;mags+=`<path d="${ringSegment(cx,cy,rotorInner,rotorOuter,c-arc/2,c+arc/2)}" class="${i%2?'south':'north'}" data-schematic-part="magnet rotor"/>`}
    return`${heading(object,'AFPM 轴向端面对象视图','视线沿转轴方向观察轴向磁通电机；定子齿/线圈与转子盘磁极使用同一个 AFPM Motor Object。',`<span>${slots} 定子齿/槽</span><span>${poles} 极</span><span>转子盘 Ø${fmt(r.outer_diameter_mm)} mm</span>`)}<div class="radial-canvas-v031"><svg viewBox="0 0 720 520" role="img" aria-label="AFPM motor-object axial face"><circle cx="${cx}" cy="${cy}" r="${rotorOuter}" class="rotor-v031" data-schematic-part="rotor"/><g class="magnets-v031 pm-object-magnets-v071">${mags}</g><g>${teeth}</g><g>${numbers}</g><circle cx="${cx}" cy="${cy}" r="${rotorInner}" class="shaft-v031" ${selectAttribute('shaft_diameter',editable)} data-schematic-part="shaft"/>${svgText(28,42,'AFPM · axial face')}${svgText(28,66,`Stator annulus ${fmt(s.inner_diameter_mm)}–${fmt(s.outer_diameter_mm)} mm`)}</svg></div>`;
  }

  function rfpmLongitudinal(object,editable){
    // Shaft-axis r-z section. x = axial direction, y = radius from the shaft.
    // The previous implementation drew one filled rotor rectangle across the
    // shaft and one closed end-winding path around the complete machine. In SVG
    // an unstyled closed path is filled black, which produced the large black
    // block seen in the UI and also misrepresented the physical stack.
    const s=object.stator,r=object.rotor,m=r.magnet,outerD=Math.max(s.outer_diameter_mm,1),radialScale=160/(outerD/2),cy=250,outerR=160,
      boreR=clamp((s.inner_diameter_mm/2)*radialScale,60,outerR-24),rotorEnvelope=clamp((r.outer_diameter_mm/2)*radialScale,25,boreR-3),
      shaftR=clamp((object.shaft.diameter_mm/2)*radialScale,10,rotorEnvelope-12),statorLen=Math.max(8,s.lamination_length_mm||50),
      rotorLen=Math.max(8,r.lamination_length_mm||statorLen),axScale=340/Math.max(statorLen,rotorLen,20),statorW=clamp(statorLen*axScale,180,380),
      rotorW=clamp(rotorLen*axScale,160,390),sx=410-statorW/2,rx=410-rotorW/2,statorTop=cy-outerR,statorBottom=cy+outerR,
      boreTop=cy-boreR,boreBottom=cy+boreR,ipm=r.kind==='interior_pm',magPx=clamp((m.thickness_mm||1)*radialScale,4,18),
      coreOuter=ipm?rotorEnvelope:Math.max(shaftR+12,rotorEnvelope-magPx),coreTop=cy-coreOuter,coreBottom=cy+coreOuter,
      magnetTop=ipm?cy-rotorEnvelope*.62:cy-rotorEnvelope,magnetBottom=ipm?cy+rotorEnvelope*.62:cy+coreOuter,
      slotDepthPx=clamp(number(s.slot?.depth_mm??object.parameters.slot_depth,(outerR-boreR)*.62)*radialScale,22,Math.max(28,(outerR-boreR)-10)),
      slotInsetX=clamp(statorW*.045,8,18),slotX=sx+slotInsetX,slotW=Math.max(28,statorW-slotInsetX*2),
      topSlotY=boreTop-slotDepthPx,bottomSlotY=boreBottom,copperInset=clamp(slotDepthPx*.18,7,13),
      topCopperY=topSlotY+copperInset,bottomCopperY=bottomSlotY+copperInset,copperH=Math.max(9,slotDepthPx-copperInset*2),
      endReach=clamp(28+number(object.winding.turns_per_coil,80)*.018,30,54),leftX=sx-endReach,rightX=sx+statorW+endReach,
      topMid=topCopperY+copperH/2,bottomMid=bottomCopperY+copperH/2;

    const magnetSvg=ipm
      ? `<rect x="${rx+rotorW*.14}" y="${magnetTop-magPx/2}" width="${rotorW*.72}" height="${magPx}" class="north" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/><rect x="${rx+rotorW*.14}" y="${magnetBottom-magPx/2}" width="${rotorW*.72}" height="${magPx}" class="south" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/>`
      : `<rect x="${rx}" y="${cy-rotorEnvelope}" width="${rotorW}" height="${magPx}" class="north" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/><rect x="${rx}" y="${cy+coreOuter}" width="${rotorW}" height="${magPx}" class="south" ${selectAttribute('magnet_thickness',editable)} data-schematic-part="magnet rotor"/>`;

    const topEndLeft=`M${slotX},${topMid} C${sx-8},${topMid} ${leftX},${topMid-18} ${leftX},${topMid-34}`;
    const topEndRight=`M${slotX+slotW},${topMid} C${sx+statorW+8},${topMid} ${rightX},${topMid-18} ${rightX},${topMid-34}`;
    const bottomEndLeft=`M${slotX},${bottomMid} C${sx-8},${bottomMid} ${leftX},${bottomMid+18} ${leftX},${bottomMid+34}`;
    const bottomEndRight=`M${slotX+slotW},${bottomMid} C${sx+statorW+8},${bottomMid} ${rightX},${bottomMid+18} ${rightX},${bottomMid+34}`;
    const gapTopH=Math.max(2,(cy-rotorEnvelope)-boreTop),gapBottomH=Math.max(2,(cy+rotorEnvelope)-boreBottom);

    return`${heading(object,ipm?'RFPM-IPM 纵向装配剖面':'RFPM-SPM 纵向装配剖面','沿转轴中心线作 r-z 剖面：定子槽和有效铜位于叠片内，端绕组仅出现在叠片两端；转子铁心围绕转轴分为上下两部分，磁体与气隙按径向位置显示。',`<span>定子叠长 ${fmt(statorLen)} mm</span><span>转子叠长 ${fmt(rotorLen)} mm</span><span>${ipm?'嵌入式磁体':'表贴磁体'}</span>`)}
      <div class="axial-canvas-v031 longitudinal-shaft-section-v066"><svg viewBox="0 0 820 500" role="img" aria-label="RFPM motor-object longitudinal r-z section">
        <g class="ax-stator-stack-v088"><rect x="${sx}" y="${statorTop}" width="${statorW}" height="${outerR-boreR}" class="stator-v031" data-schematic-part="stator"/><rect x="${sx}" y="${boreBottom}" width="${statorW}" height="${outerR-boreR}" class="stator-v031" data-schematic-part="stator"/></g>
        <g class="ax-slot-windows-v088"><rect x="${slotX}" y="${topSlotY}" width="${slotW}" height="${slotDepthPx}" rx="3" class="ax-slot-window-v066" data-schematic-part="stator-slot winding"/><rect x="${slotX}" y="${bottomSlotY}" width="${slotW}" height="${slotDepthPx}" rx="3" class="ax-slot-window-v066" data-schematic-part="stator-slot winding"/><rect x="${slotX+7}" y="${topCopperY}" width="${slotW-14}" height="${copperH}" rx="4" class="ax-active-copper-v088" data-schematic-part="winding"/><rect x="${slotX+7}" y="${bottomCopperY}" width="${slotW-14}" height="${copperH}" rx="4" class="ax-active-copper-v088 phase-b" data-schematic-part="winding"/></g>
        <g class="ax-rotor-stack-v088"><rect x="${rx}" y="${coreTop}" width="${rotorW}" height="${Math.max(2,coreOuter-shaftR)}" class="ax-rotor-core-v088" data-schematic-part="rotor"/><rect x="${rx}" y="${cy+shaftR}" width="${rotorW}" height="${Math.max(2,coreOuter-shaftR)}" class="ax-rotor-core-v088" data-schematic-part="rotor"/>${magnetSvg}</g>
        <g class="ax-airgap-bands-v088"><rect x="${Math.max(sx,rx)}" y="${boreTop}" width="${Math.min(sx+statorW,rx+rotorW)-Math.max(sx,rx)}" height="${gapTopH}" class="ax-airgap-band-v088" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/><rect x="${Math.max(sx,rx)}" y="${cy+rotorEnvelope}" width="${Math.min(sx+statorW,rx+rotorW)-Math.max(sx,rx)}" height="${gapBottomH}" class="ax-airgap-band-v088" ${selectAttribute('air_gap',editable)} data-schematic-part="airgap"/></g>
        <rect x="42" y="${cy-shaftR}" width="736" height="${shaftR*2}" rx="${Math.min(8,shaftR/2)}" class="shaft-v031" ${selectAttribute('shaft_diameter',editable)} data-schematic-part="shaft"/>
        <g class="ax-end-turns-v088" data-schematic-part="winding"><path d="${topEndLeft}" class="ax-end-turn-v088"/><path d="${topEndRight}" class="ax-end-turn-v088"/><path d="${bottomEndLeft}" class="ax-end-turn-v088 phase-b"/><path d="${bottomEndRight}" class="ax-end-turn-v088 phase-b"/></g>
        <g class="ax-assembly-labels-v066"><line x1="${sx}" y1="94" x2="${sx+statorW}" y2="94"/><text x="${sx+statorW/2}" y="86" text-anchor="middle">定子叠长 ${fmt(statorLen)} mm</text><line x1="${rx}" y1="406" x2="${rx+rotorW}" y2="406"/><text x="${rx+rotorW/2}" y="424" text-anchor="middle">转子叠长 ${fmt(rotorLen)} mm</text></g>
        ${svgText(28,44,`${safe(object.topology_id)} · r-z shaft-axis section`)}${svgText(28,68,`g ${fmt(object.derived.air_gap_mm)} mm · shaft Ø${fmt(object.shaft.diameter_mm)} mm · yellow = active/end winding`)}
      </svg></div>`;
  }

  function outerLongitudinal(object){
    const s=object.stator,r=object.rotor,m=r.magnet,cy=250,maxD=Math.max(r.outer_diameter_mm,s.outer_diameter_mm,1),scale=165/(maxD/2),rotorOuter=165,rotorInner=clamp((r.inner_diameter_mm/2)*scale,100,rotorOuter-12),statorOuter=clamp((s.outer_diameter_mm/2)*scale,65,rotorInner-7),statorInner=clamp((s.inner_diameter_mm/2)*scale,25,statorOuter-22),shaftR=clamp((object.shaft.diameter_mm/2)*scale,9,statorInner-8),statorW=clamp((s.lamination_length_mm||30)*3.2,180,390),rotorW=clamp((r.lamination_length_mm||s.lamination_length_mm||30)*3.2,180,410),sx=410-statorW/2,rx=410-rotorW/2,magPx=clamp((m.thickness_mm||1)*scale,4,16),coilReach=58,coilTop=cy-statorOuter*.72,coilBottom=cy+statorOuter*.72,coil=`M${sx},${coilTop} L${sx+statorW},${coilTop} Q${sx+statorW+coilReach},${coilTop} ${sx+statorW+coilReach},${cy} Q${sx+statorW+coilReach},${coilBottom} ${sx+statorW},${coilBottom} L${sx},${coilBottom} Q${sx-coilReach},${coilBottom} ${sx-coilReach},${cy} Q${sx-coilReach},${coilTop} ${sx},${coilTop}`;
    return`${heading(object,'Outer-Rotor PM 纵向装配剖面','外转子筒体与内表面磁体包围定子；端绕组位于定子叠片两端，转轴只作为内部支承对象显示。',`<span>外转子 Ø${fmt(r.outer_diameter_mm)} mm</span><span>定子叠长 ${fmt(s.lamination_length_mm)} mm</span><span>气隙 ${fmt(object.derived.air_gap_mm)} mm</span>`)}<div class="axial-canvas-v031"><svg viewBox="0 0 820 500" role="img" aria-label="outer rotor motor-object longitudinal section"><rect x="${rx}" y="${cy-rotorOuter}" width="${rotorW}" height="${rotorOuter-rotorInner}" class="rotor-v031" data-schematic-part="rotor"/><rect x="${rx}" y="${cy+rotorInner}" width="${rotorW}" height="${rotorOuter-rotorInner}" class="rotor-v031" data-schematic-part="rotor"/><rect x="${rx}" y="${cy-rotorInner}" width="${rotorW}" height="${magPx}" class="north" data-schematic-part="magnet rotor"/><rect x="${rx}" y="${cy+rotorInner-magPx}" width="${rotorW}" height="${magPx}" class="south" data-schematic-part="magnet rotor"/><rect x="${sx}" y="${cy-statorOuter}" width="${statorW}" height="${statorOuter-statorInner}" class="stator-v031" data-schematic-part="stator"/><rect x="${sx}" y="${cy+statorInner}" width="${statorW}" height="${statorOuter-statorInner}" class="stator-v031" data-schematic-part="stator"/><path d="${coil}" class="end-winding-v066 ax-coil-loop-v066" data-schematic-part="winding"/><rect x="42" y="${cy-shaftR}" width="736" height="${shaftR*2}" class="shaft-v031" data-schematic-part="shaft"/>${svgText(28,44,'BPMOR · shaft-axis section')}</svg></div>`;
  }

  function afpmStack(object){
    const s=object.stator,r=object.rotor,m=r.magnet,gap=Math.max(.05,object.derived.air_gap_mm),statorT=Math.max(6,s.lamination_length_mm||20),rotorT=Math.max(4,r.lamination_length_mm||8),magT=Math.max(2,m.length_mm||m.thickness_mm||8),total=statorT+2*(gap+magT+rotorT),scale=500/Math.max(total,30),stW=clamp(statorT*scale,70,190),gapW=clamp(gap*scale,6,24),magW=clamp(magT*scale,20,90),rotW=clamp(rotorT*scale,20,80),cx=410,xSt=cx-stW/2,leftMag=xSt-gapW-magW,leftRotor=leftMag-rotW,rightMag=xSt+stW+gapW,rightRotor=rightMag+magW,outerH=320,innerH=clamp(outerH*(r.inner_diameter_mm/Math.max(r.outer_diameter_mm,1)),70,260),y=250-outerH/2,innerY=250-innerH/2,shaftH=clamp(outerH*(object.shaft.diameter_mm/Math.max(r.outer_diameter_mm,1)),24,innerH-12);
    return`${heading(object,'AFPM 轴向堆叠剖面','沿转轴中心线剖开：双转子盘位于两侧，磁体面向中央定子，两条轴向气隙和槽内绕组同时显示。',`<span>双转子 / 单定子</span><span>气隙 ${fmt(gap)} mm ×2</span><span>转子盘 Ø${fmt(r.outer_diameter_mm)} mm</span>`)}<div class="axial-canvas-v031"><svg viewBox="0 0 820 500" role="img" aria-label="AFPM motor-object axial stack"><rect x="${leftRotor}" y="${y}" width="${rotW}" height="${outerH}" class="rotor-v031" data-schematic-part="rotor"/><rect x="${leftMag}" y="${y+18}" width="${magW}" height="${outerH-36}" class="north" data-schematic-part="magnet rotor"/><rect x="${xSt}" y="${y}" width="${stW}" height="${outerH}" class="stator-v031" data-schematic-part="stator"/><rect x="${xSt+stW*.18}" y="${innerY}" width="${stW*.64}" height="${innerH}" class="slot-cavity-v066" data-schematic-part="stator-slot winding"/><rect x="${xSt+stW*.25}" y="${innerY+18}" width="${stW*.5}" height="${innerH-36}" class="slot-conductor-v031" data-schematic-part="winding"/><rect x="${rightMag}" y="${y+18}" width="${magW}" height="${outerH-36}" class="south" data-schematic-part="magnet rotor"/><rect x="${rightRotor}" y="${y}" width="${rotW}" height="${outerH}" class="rotor-v031" data-schematic-part="rotor"/><rect x="38" y="${250-shaftH/2}" width="744" height="${shaftH}" class="shaft-v031" data-schematic-part="shaft"/><rect x="${leftMag+magW}" y="${y}" width="${gapW}" height="${outerH}" class="airgap-v031"/><rect x="${xSt+stW}" y="${y}" width="${gapW}" height="${outerH}" class="airgap-v031"/>${svgText(40,40,'ROTOR | MAGNET | GAP | STATOR/WINDING | GAP | MAGNET | ROTOR')}${svgText(40,66,`Stack ${fmt(total)} mm conceptual envelope · actual native regions validated in Motor-CAD`)}</svg></div>`;
  }

  function radialView(ctx){const {motorObject,editable}=viewData(ctx);if(!motorObject)return null;const pluginView=window.MCSMotorObject?.renderVisualization?.('radial',motorObject,ctx);if(pluginView)return pluginView;let body;if(motorObject.topology_id==='rfpm_ipm')body=ipmRadial(motorObject,editable);else if(motorObject.topology_id==='outer_rotor_pm')body=outerRotorRadial(motorObject,editable);else if(motorObject.topology_id==='afpm')body=afpmFace(motorObject,editable);else body=spmRadial(motorObject,editable);return`<div class="motorcad-view-v031 radial-view-v031 motor-object-view-v071" data-motor-object-topology="${safe(motorObject.topology_id)}">${body}${authorityStrip('PM Motor Object 参数化投影；Motor-CAD 原生几何为最终权威')}</div>`}
  function longitudinalView(ctx){const {motorObject}=viewData(ctx);if(!motorObject)return null;const pluginView=window.MCSMotorObject?.renderVisualization?.('longitudinal',motorObject,ctx);if(pluginView)return pluginView;let body;if(motorObject.topology_id==='afpm')body=afpmStack(motorObject);else if(motorObject.topology_id==='outer_rotor_pm')body=outerLongitudinal(motorObject);else body=rfpmLongitudinal(motorObject,Boolean(ctx.editable));return`<div class="motorcad-view-v031 axial-view-v031 motor-object-view-v071" data-motor-object-topology="${safe(motorObject.topology_id)}">${body}${authorityStrip('沿转轴/轴向堆叠的 PM Motor Object 投影；原生模型区域边界以 Motor-CAD 为最终权威')}</div>`}
  // V0.61/V0.66 compatibility aliases.  Both now delegate to the PM Motor Object
  // projection rather than owning separate geometry implementations.
  function radialMachineAxialView(ctx){return longitudinalView(ctx)}
  function axialFluxAxialView(ctx){return longitudinalView(ctx)}
  function render(view,ctx){if(view==='radial')return radialView(ctx);if(view==='axial')return longitudinalView(ctx);return null}
  const axialView=longitudinalView;
  window.MCSDesignGeometry={render,radialView,longitudinalView,axialView,radialMachineAxialView,axialFluxAxialView};
})();
