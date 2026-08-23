/* V0.66 Winding renderer. Slot numbering, parallel-path preview and slot geometry are parameter driven.
 * End-turn preview curves remain in the end-winding annulus and never imply native conductor placement.
 */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before winding renderer');
  const {safe,number,clamp,fmt,parameterRecord,selectAttribute,polar,viewData,authorityStrip,phaseColors}=U;
  function coilCurve(cx,cy,r,start,end){
    const outer=r+38,p1=polar(cx,cy,r,start),p2=polar(cx,cy,r,end),p1o=polar(cx,cy,outer,start),p2o=polar(cx,cy,outer,end);
    const delta=((end-start+540)%360)-180,sweep=delta>=0?1:0,large=Math.abs(delta)>180?1:0;
    return`M${p1[0].toFixed(1)},${p1[1].toFixed(1)} L${p1o[0].toFixed(1)},${p1o[1].toFixed(1)} A${outer},${outer} 0 ${large} ${sweep} ${p2o[0].toFixed(1)},${p2o[1].toFixed(1)} L${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  function nativeBranch(coil,fallback,paths){
    const value=coil?.parallel_path??coil?.path??coil?.branch??coil?.path_number;
    const parsed=Math.round(Number(value));return Number.isFinite(parsed)&&parsed>0?clamp(parsed,1,paths):fallback;
  }
  function previewBranch(slotIndex,phase,phases,paths){
    const phaseOrder=Math.max(0,Math.floor((slotIndex-phase)/Math.max(1,phases)));
    return phaseOrder%paths+1;
  }
  function windingView(ctx){
    const {data,values,editable,motorObject}=viewData(ctx),derived=(ctx.precheck?.winding||data.precheck?.winding||{}).derived||{},objectW=motorObject?.winding||{},evidenceW=data.winding_design||{},w={...evidenceW,...objectW,coil_table:(evidenceW.coil_table?.length?evidenceW.coil_table:(objectW.coils||[])),native_only_fields:evidenceW.native_only_fields||[]};
    const slots=clamp(Math.round(number(motorObject?.stator?.slot?.count??values.slot_count,12)),3,72),phases=clamp(Math.round(number(w.phase_count||derived.phase_count,3)),1,15),paths=clamp(Math.max(1,Math.round(number(motorObject?.winding?.parallel_paths??values.parallel_paths,w.parallel_paths||1))),1,24);
    const turns=Math.max(1,Math.round(number(motorObject?.winding?.turns_per_coil??values.turns_per_coil,w.turns_per_coil||1))),poleCount=Math.max(2,number(motorObject?.winding?.pole_count??values.pole_count,8)),throwSlots=clamp(Math.round(number(w.estimated_coil_throw_slots,Math.max(1,slots/poleCount))),1,Math.max(1,slots-1));
    const q=derived.slots_per_phase_path??w.slots_per_phase_path,valid=Number.isFinite(Number(q))&&Math.abs(Number(q)-Math.round(Number(q)))<1e-9;
    const nativeCoils=Array.isArray(w.coil_table)?w.coil_table:[],hasNative=nativeCoils.length>0;
    const cx=300,cy=265,r=166,slotStep=360/slots;let coils='',marks='',slotNumbers='',rows='';
    const drawRows=hasNative?nativeCoils.slice(0,96):Array.from({length:Math.min(slots,72)},(_,i)=>({go_slot:i+1,return_slot:(i+throwSlots)%slots+1,phase:i%phases+1}));
    drawRows.forEach((coil,i)=>{
      const phaseIndex=Number.isFinite(Number(coil.phase))?Math.max(0,Number(coil.phase)-1):i%phases,color=phaseColors[phaseIndex%phaseColors.length],start=(Number(coil.go_slot)-1)*slotStep,end=(Number(coil.return_slot)-1)*slotStep;
      const branch=nativeBranch(coil,(Math.floor(i/Math.max(1,phases))%paths)+1,paths);
      coils+=`<path d="${coilCurve(cx,cy,r+13,start,end)}" stroke="${color}" class="coil-path-v031 branch-${branch}" data-branch-v066="${branch}" style="--branch:${branch};stroke-dasharray:${paths>1?`${5+branch*2} ${Math.max(3,9-branch)}`:'none'}"/>`;
    });
    const nativeMarks=new Map();nativeCoils.forEach((coil,i)=>{
      const phaseIndex=Number.isFinite(Number(coil.phase))?Math.max(0,Number(coil.phase)-1):i%phases;
      const branch=nativeBranch(coil,(Math.floor(i/Math.max(1,phases))%paths)+1,paths);
      nativeMarks.set(Number(coil.go_slot),{phaseIndex,direction:'•',branch});nativeMarks.set(Number(coil.return_slot),{phaseIndex,direction:'×',branch});
    });
    for(let i=0;i<slots;i++){
      const a=i*slotStep,p=polar(cx,cy,r,a),labelP=polar(cx,cy,r+27,a),nativeMark=nativeMarks.get(i+1),phase=nativeMark?.phaseIndex??i%phases,color=phaseColors[phase%phaseColors.length],direction=nativeMark?.direction??(Math.floor(i/phases)%2?'×':'•'),branch=nativeMark?.branch??previewBranch(i,phase,phases,paths);
      marks+=`<g class="winding-mark-v031" ${selectAttribute('slot_count',editable)}><circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${slots>48?5:7}" fill="${color}"/><text x="${p[0].toFixed(1)}" y="${(p[1]+3).toFixed(1)}" text-anchor="middle">${direction}</text>${paths>1?`<text class="winding-branch-tag-v066" x="${(p[0]+9).toFixed(1)}" y="${(p[1]-7).toFixed(1)}">P${branch}</text>`:''}</g>`;
      const compact=slots>48&&i%2===1;
      if(!compact)slotNumbers+=`<text class="winding-slot-number-v066" x="${labelP[0].toFixed(1)}" y="${(labelP[1]+3).toFixed(1)}" text-anchor="middle">${i+1}</text>`;
      if(i<Math.min(slots,36))rows+=`<tr><td><b>${i+1}</b></td><td><span class="phase-dot-v031" style="--phase:${color}"></span>${hasNative?safe(nativeMark?`相 ${nativeMark.phaseIndex+1}`:'未占用'):`相 ${phase+1}`}</td><td>${nativeMark||!hasNative?(direction==='•'?'出':'入'):'—'}</td><td><span class="branch-chip-v066">P${branch}</span></td></tr>`;
    }
    return`<div class="motorcad-view-v031 winding-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">WINDING · PATTERN</span><h3>绕组排布、槽号与并联支路</h3><p>模型槽号与右侧槽表使用同一编号；并联支路改变后，P1…Pn 标记和预览分组即时重算。</p></div><div class="visual-facts-v031"><span>${phases} 相</span><span>${turns} 匝 / 线圈</span><span>${paths} 并联支路</span></div></div>
      <div class="winding-layout-v031"><div class="winding-canvas-v031"><svg viewBox="0 0 600 550" role="img" aria-label="带槽号和并联支路的绕组相槽关系预览"><circle cx="${cx}" cy="${cy}" r="210" class="winding-stator-v031"/><circle cx="${cx}" cy="${cy}" r="112" class="winding-rotor-v031"/><g>${coils}</g><g>${marks}</g><g>${slotNumbers}</g><text x="${cx}" y="248" text-anchor="middle" class="winding-title-v031">${slots} 槽 / ${poleCount} 极</text><text x="${cx}" y="274" text-anchor="middle" class="winding-subtitle-v031">${phases} 相 · ${paths} 支路 · 预估节距 ${throwSlots} 槽</text><text x="${cx}" y="298" text-anchor="middle" class="winding-subtitle-v031">${safe(w.pattern_class||'Concentrated')} · ${safe(w.slot_arrangement||'模板继承')}</text></svg></div>
      <aside class="winding-summary-v031"><div class="winding-health-v031 ${valid?'pass':'blocked'}"><span>${valid?'✓':'!'}</span><div><small>每相每支路槽数</small><b>${q!==null&&q!==undefined?fmt(q,5):'等待模型检查'}</b><p>${valid?'槽、相与支路关系可整数分配':'当前关系无法整数分配'}</p></div></div><div class="winding-evidence-v035 ${hasNative?'native':'preview'}"><b>${hasNative?'当前计算采用的线圈槽对':'设计版本即时预览'}</b><span>${hasNative?`${nativeCoils.length} 个线圈槽对已用于当前视图`:'P1…Pn 为 Studio 根据当前支路数生成的预览分组；等待模型结果后采用 Motor-CAD 线圈/支路定义'}</span></div><div class="winding-metrics-v031"><div><span>绕组层数</span><b>${fmt(w.layers,0)}</b></div><div><span>槽满率输入</span><b>${fmt(values.slot_fill_factor??w.slot_fill_factor)}</b></div><div><span>线圈节距</span><b>${hasNative?'按计算槽对':`${throwSlots} <em>视图估计</em>`}</b></div><div><span>并联支路</span><b>${paths}</b></div></div><div class="phase-legend-v031">${Array.from({length:phases},(_,i)=>`<span style="--phase:${phaseColors[i%phaseColors.length]}">相 ${i+1}</span>`).join('')}${paths>1?Array.from({length:paths},(_,i)=>`<span class="branch-legend-v066">P${i+1}</span>`).join(''):''}</div><div class="winding-slot-table-v031"><table><thead><tr><th>槽号</th><th>相</th><th>方向</th><th>支路</th></tr></thead><tbody>${rows}</tbody></table>${slots>36?`<small>显示前 36 / ${slots} 槽；模型仍标注全部或隔槽编号</small>`:''}</div></aside></div>${authorityStrip(hasNative?'当前计算采用的 Motor-CAD 绕组槽对':'槽号/相序直接来自当前设计参数；Studio 即时图不能替代 Motor-CAD 的真实 coil go/return slot 定义，原生线圈 Path Type 与并联路径以 Motor-CAD 检查结果为最终依据')}
    </div>`;
  }

  function slotView(ctx){
    const {data,values,motorObject}=viewData(ctx),w={...(data.winding_design||{}),...(motorObject?.winding||{})},editable=Boolean(ctx.editable);
    const fill=clamp(number(values.slot_fill_factor,.4),.05,.95),turns=Math.max(1,Math.round(number(values.turns_per_coil,w.turns_per_coil||100)));
    const slot=motorObject?.stator?.slot||{},opening=Math.max(.05,number(slot.opening_mm??values.slot_opening,2)),slotWidth=Math.max(opening+.1,number(slot.width_mm??values.slot_width,Math.max(opening*3,6))),depth=Math.max(1,number(slot.depth_mm??values.slot_depth,16)),tooth=Math.max(.1,number(slot.tooth_width_mm??values.tooth_width,4.8)),corner=Math.max(0,number(slot.corner_radius_mm??values.slot_corner_radius,1.5)),tipDepth=Math.max(0,number(slot.tooth_tip_depth_mm??values.tooth_tip_depth,1)),tipAngle=number(slot.tooth_tip_angle_deg??values.tooth_tip_angle,0);
    const cx=330,topY=70,depthPx=clamp(depth*15,190,335),baseY=topY+depthPx,openingPx=clamp(opening*18,22,120),slotWidthPx=clamp(slotWidth*18,90,260),tipPx=clamp(tipDepth*18,0,58),shoulderY=topY+Math.max(18,tipPx+14),bottomWidth=clamp(slotWidthPx*(1-clamp(tipAngle,-45,45)/360),80,285),linerInset=10;
    const leftTop=cx-slotWidthPx/2,rightTop=cx+slotWidthPx/2,leftBottom=cx-bottomWidth/2,rightBottom=cx+bottomWidth/2;
    const cavity=`M${cx-openingPx/2},${topY} L${cx-openingPx/2},${topY+tipPx} L${leftTop},${shoulderY} L${leftBottom},${baseY} Q${leftBottom},${baseY+corner*1.2} ${leftBottom+corner*1.4},${baseY+corner*1.2} L${rightBottom-corner*1.4},${baseY+corner*1.2} Q${rightBottom},${baseY+corner*1.2} ${rightBottom},${baseY} L${rightTop},${shoulderY} L${cx+openingPx/2},${topY+tipPx} L${cx+openingPx/2},${topY} Z`;
    const linerTopY=shoulderY+linerInset,linerBottomY=baseY-linerInset,linerLeftTop=leftTop+linerInset,linerRightTop=rightTop-linerInset,linerLeftBottom=leftBottom+linerInset,linerRightBottom=rightBottom-linerInset;
    const dividerW=clamp(slotWidthPx*.055,8,18),target=clamp(Math.round((10+turns*.22)*(.55+fill*.8)),14,120),radius=clamp(5.9-Math.max(0,target-55)*.025,3.6,5.9),gapPx=2.4;
    let conductors='',placed=0;
    const yStart=linerTopY+radius+5,yEnd=linerBottomY-radius-10,rowStep=radius*2+gapPx;
    for(let y=yStart,row=0;y<=yEnd&&placed<target;y+=rowStep,row++){
      const t=clamp((y-linerTopY)/Math.max(1,linerBottomY-linerTopY),0,1),left=linerLeftTop+(linerLeftBottom-linerLeftTop)*t,right=linerRightTop+(linerRightBottom-linerRightTop)*t,mid=cx;
      for(const [x0,x1] of [[left,mid-dividerW/2-4],[mid+dividerW/2+4,right]]){
        const count=Math.max(1,Math.floor((x1-x0)/(radius*2+gapPx))),span=(count-1)*(radius*2+gapPx),center=(x0+x1)/2;
        for(let col=0;col<count&&placed<target;col++){
          const x=center-span/2+col*(radius*2+gapPx)+((row%2)?radius*.45:0);
          if(x+radius>x1||x-radius<x0)continue;
          conductors+=`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${radius.toFixed(1)}" class="slot-conductor-v031"/>`;placed++;
        }
      }
    }
    const equivalentTurnsPerMarker=placed?turns/placed:turns;
    const markerMeaning=Number.isInteger(equivalentTurnsPerMarker)?`${equivalentTurnsPerMarker} 匝/标记`:`约 ${fmt(equivalentTurnsPerMarker,2)} 匝/标记`;
    const missing=(w.native_only_fields||[]).map(id=>({wire_diameter:'线径',copper_diameter:'铜径',strands_in_hand:'并绕根数',liner_thickness:'槽衬厚度',coil_divider_width:'线圈分隔宽度',conductor_separation:'导体间距',winding_factor:'基波绕组因数'})[id]||id);
    const parameterIds=['slot_opening','slot_width','slot_corner_radius','tooth_width','tooth_tip_depth','tooth_tip_angle','slot_depth','turns_per_coil','slot_fill_factor'];
    return`<div class="motorcad-view-v031 slot-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">WINDING · SLOT DEFINITION</span><h3>槽内定义与参数联动</h3><p>槽口、槽宽、槽深、齿顶和导体占用均由当前草稿驱动；修改右侧参数后本图在同一帧重绘。</p></div><div class="visual-facts-v031"><span>槽满率 ${fmt(fill)}</span><span>匝数 ${turns}</span><span>槽宽 ${fmt(slotWidth)} mm</span><span>槽深 ${fmt(depth)} mm</span></div></div>
      <div class="slot-layout-v031"><div class="slot-canvas-v031"><svg viewBox="0 0 660 500" role="img" aria-label="参数联动的定子槽内导体填充关系"><defs><clipPath id="slotChambersV031"><path d="M${linerLeftTop},${linerTopY} L${cx-dividerW/2-4},${linerTopY} L${cx-dividerW/2-4},${linerBottomY} L${linerLeftBottom},${linerBottomY} Z"/><path d="M${cx+dividerW/2+4},${linerTopY} L${linerRightTop},${linerTopY} L${linerRightBottom},${linerBottomY} L${cx+dividerW/2+4},${linerBottomY} Z"/></clipPath></defs><path d="M135,32 L525,32 L485,462 L175,462 Z" class="slot-steel-v031" ${selectAttribute('tooth_width',editable)} data-schematic-part="stator-slot"/><path d="${cavity}" class="slot-cavity-v066" ${selectAttribute('slot_width',editable)} data-schematic-part="slot cavity"/><path d="M${linerLeftTop},${linerTopY} L${linerRightTop},${linerTopY} L${linerRightBottom},${linerBottomY} L${linerLeftBottom},${linerBottomY} Z" class="slot-liner-v031" data-schematic-part="winding stator-slot"/><rect x="${cx-dividerW/2}" y="${linerTopY}" width="${dividerW}" height="${linerBottomY-linerTopY}" class="slot-divider-v031"/><g clip-path="url(#slotChambersV031)" ${selectAttribute('slot_fill_factor',editable)}>${conductors}</g><rect x="${cx-openingPx/2}" y="${topY-5}" width="${openingPx}" height="12" rx="3" class="slot-opening-marker-v066" ${selectAttribute('slot_opening',editable)}/><g class="slot-dimensions-v066"><line x1="${cx-openingPx/2}" y1="48" x2="${cx+openingPx/2}" y2="48"/><text x="${cx}" y="42" text-anchor="middle">槽口 ${fmt(opening)} mm</text><line x1="${rightBottom+26}" y1="${topY}" x2="${rightBottom+26}" y2="${baseY}"/><text x="${rightBottom+36}" y="${(topY+baseY)/2}" transform="rotate(90 ${rightBottom+36} ${(topY+baseY)/2})" text-anchor="middle">槽深 ${fmt(depth)} mm</text><line x1="${leftBottom}" y1="${baseY+34}" x2="${rightBottom}" y2="${baseY+34}"/><text x="${cx}" y="${baseY+52}" text-anchor="middle">槽宽 ${fmt(slotWidth)} mm · 圆角 ${fmt(corner)} mm</text></g><text x="330" y="486" text-anchor="middle" class="slot-preview-note-v066">铜面积等效采样 · ${placed} 个黄色标记表示 ${turns} 匝视觉采样 · ${safe(markerMeaning)}</text></svg><div class="slot-conductor-legend-v088"><span class="slot-conductor-symbol-v088"></span><div><b>黄色圆 = 等效导体截面标记</b><small>当前 ${placed} 个标记对应 ${turns} 匝，${safe(markerMeaning)}。在线径、并绕根数尚未由 Motor-CAD 回读前，不把一个圆解释为一根实际铜线。</small></div></div></div>
      <aside class="slot-definition-v031"><h4>当前可配置参数</h4>${parameterIds.map(id=>{const row=parameterRecord(data,id);return row?`<button type="button" ${selectAttribute(id,editable)}><span>${safe(row.label)}</span><b>${fmt(values[id])} ${safe(row.unit||'')}</b></button>`:''}).join('')}<h4>完成原生检查后可显示</h4><div class="native-field-list-v031">${missing.map(label=>`<span><b>${safe(label)}</b><em>等待 Motor-CAD</em></span>`).join('')}</div><p>线径、绝缘层、并绕根数与实际导体位置仍由 Motor-CAD 绕组定义和计算输出提供；即时图形不伪造这些原生字段。</p></aside></div>${authorityStrip('结构化槽几何和铜面积占用即时预览；实际导体布置与 FEA 槽面积以 Motor-CAD 原生模型为最终依据')}
    </div>`;
  }

  function render(view,ctx){if(view==='winding')return windingView(ctx);if(view==='slot')return slotView(ctx);return null;}
  window.MCSDesignWinding={render,windingView,slotView};
})();
