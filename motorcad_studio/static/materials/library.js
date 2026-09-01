/* MotorCAD Studio V0.66 material library module — searchable local Motor-CAD engineering data. */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const stateV061={status:null,records:[],selected:null,query:'',kind:'',materialType:'',searchTimer:null,picker:null,resize:null};
  const propertyMeta={
    'Thermal Conductivity':['热导率','W/m/°C'],
    'Specific Heat':['比热容','J/kg/°C'],
    'Density':['密度','kg/m³'],
    'ElectricalResistivity':['电阻率','Ω·m'],
    'TempCoefElectricalResistivity':['电阻率温度系数','1/°C'],
    'PoissonsRatio':['泊松比',''],
    'YoungsCoefficient':['杨氏模量','MPa'],
    'YieldStress':['屈服强度','MPa'],
    'MagnetBrValue':['剩磁 Br','T'],
    'MagnetHcJValue':['内禀矫顽力 HcJ','A/m'],
    'MagneturValue':['相对磁导率 µr',''],
    'MagnetTempCoefBr':['Br 温度系数','%/°C'],
    'MagnetTempCoefHcJ':['HcJ 温度系数','%/°C'],
    'MagnetRefTemp':['磁体参考温度','°C'],
    'ValidMagnetTemperature_Min':['磁体有效最低温度','°C'],
    'ValidMagnetTemperature_Max':['磁体有效最高温度','°C'],
    'LaminationThickness':['叠片厚度','mm'],
    'Frequency':['损耗测试频率','Hz'],
    'FluxDensity':['损耗测试磁密','T'],
    'LossDensity':['比损耗','W/kg'],
    'BValue':['B-H 曲线磁密','T'],
    'HValue':['B-H 曲线磁场强度','A/m'],
    'BValue_Magnet':['磁体退磁曲线 B','T'],
    'HValue_Magnet':['磁体退磁曲线 H','A/m'],
    'Temperature':['磁体曲线温度','°C'],
    'Kinematic Viscosity':['运动黏度','m²/s']
  };

  function resetDialogSize(section){if(!section)return;section.style.width='90vw';section.style.height='90vh'}
  function bindResizableDialog(node){
    const section=q('section',node),handle=q('[data-material-resize-v088]',node);if(!section||!handle)return;
    resetDialogSize(section);
    let drag=null;
    const move=event=>{if(!drag)return;const maxW=Math.max(680,window.innerWidth-28),maxH=Math.max(460,window.innerHeight-28);section.style.width=`${Math.max(680,Math.min(maxW,drag.w+event.clientX-drag.x))}px`;section.style.height=`${Math.max(460,Math.min(maxH,drag.h+event.clientY-drag.y))}px`};
    const up=()=>{drag=null;window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up)};
    handle.addEventListener('pointerdown',event=>{if(window.innerWidth<=820)return;event.preventDefault();const rect=section.getBoundingClientRect();drag={x:event.clientX,y:event.clientY,w:rect.width,h:rect.height};handle.setPointerCapture?.(event.pointerId);window.addEventListener('pointermove',move);window.addEventListener('pointerup',up,{once:true})});
    handle.addEventListener('dblclick',()=>resetDialogSize(section));
  }
  function close(){q('#materialLibraryV061')?.remove();stateV061.picker=null;if(!q('#materialLibraryV061'))document.body.classList.remove('engineering-sheet-open')}
  function shell(){
    window.MCSCloseEngineeringSheets?.();q('#materialLibraryV061')?.remove();
    const node=document.createElement('div');node.id='materialLibraryV061';node.className='material-library-shell-v061';
    const picker=stateV061.picker;
    node.innerHTML=`<div class="material-library-backdrop-v061"></div><section role="dialog" aria-modal="true" aria-label="Motor-CAD 材料库"><header><div><span>${picker?'材料选择':'材料工程数据'}</span><h2>${safe(picker?.title||'Motor-CAD 材料库')}</h2><p>${picker?'单击预览，双击或使用底部按钮赋值。':'浏览、筛选和维护材料；数据库来源信息默认折叠。'}</p></div><button type="button" data-material-close-v061 aria-label="关闭">×</button></header><div id="materialLibraryBodyV061" class="material-library-body-v061"><div class="material-loading-v061">正在读取材料数据库状态…</div></div><div class="material-library-resize-handle-v088" data-material-resize-v088 title="拖动调整窗口大小；双击恢复默认大小"></div></section>`;
    document.body.appendChild(node);document.body.classList.add('engineering-sheet-open');
    q('[data-material-close-v061]',node)?.addEventListener('click',close);q('.material-library-backdrop-v061',node)?.addEventListener('click',close);bindResizableDialog(node);return node;
  }

  function sourceLabel(row){return row?.source_kind==='studio_custom'?'Studio 管理材料':'Motor-CAD 数据库快照'}
  function hashShort(value){return value?String(value).slice(0,16):'—'}
  function sourceCards(){
    const databases=stateV061.status?.databases||[],discovered=stateV061.status?.discovered||[];
    const known=new Set(databases.map(row=>row.path));
    const rows=[...databases.map(row=>({...row,imported:true})),...discovered.filter(row=>!known.has(row.path)).map(row=>({...row,imported:false}))];
    if(!rows.length)return `<div class="material-source-empty-v061"><b>尚未发现本机 Motor-CAD .mdb</b><span>在 Windows Motor-CAD 工作站点击“扫描本机数据库”；也可以直接填写 Solids.mdb / Fluids.mdb 路径导入。</span></div>`;
    return rows.map(row=>`<article class="material-source-card-v061 ${row.readable===false?'error':''}"><div><b>${safe(row.kind||'数据库')}</b><span>${row.imported?'已载入 Studio':'已发现，待载入'}</span></div><code title="${safe(row.path)}">${safe(row.path)}</code><small>${row.material_count??'—'} 种材料 · SHA-256 ${safe(hashShort(row.file_hash))}${row.source?` · ${safe(row.source)}`:''}</small>${row.error?`<em>${safe(row.error)}</em>`:''}</article>`).join('');
  }
  function recordItem(row){
    const selected=stateV061.selected?.id===row.id;return `<button type="button" data-material-record-v061="${safe(row.id)}" class="material-record-v061 ${selected?'selected':''}"><span><b>${safe(row.name)}</b><small>${safe(row.material_type)} · ${safe(row.kind==='fluid'?'流体':'固体')}</small></span><em class="${row.source_kind==='studio_custom'?'custom':'source'}">${row.source_kind==='studio_custom'?'Studio':'Motor-CAD'}</em></button>`;
  }
  function renderList(){
    const box=q('#materialRecordListV061');if(!box)return;
    box.innerHTML=stateV061.records.length?stateV061.records.map(recordItem).join(''):'<div class="material-list-empty-v061">当前筛选条件没有材料记录。</div>';
    qa('[data-material-record-v061]',box).forEach(button=>{
      button.addEventListener('click',()=>selectRecord(button.dataset.materialRecordV061));
      button.addEventListener('dblclick',async event=>{event.preventDefault();if(!stateV061.picker)return;await selectRecord(button.dataset.materialRecordV061);chooseSelected()});
    });
  }

  function curveMetric(label,count){return `<div><span>${safe(label)}</span><b>${Number(count)||0}</b></div>`}
  function curveChart(points,title,xLabel,yLabel){
    const raw=(points||[]).map(row=>({x:Number(row.x),y:Number(row.y)})).filter(row=>Number.isFinite(row.x)&&Number.isFinite(row.y));if(raw.length<2)return'';
    const maxAbs=(rows,key)=>Math.max(...rows.map(row=>Math.abs(row[key])),0);
    const axisScale=(rows,key,label)=>/A·m/.test(label)&&maxAbs(rows,key)>=10000?{factor:1000,label:label.replace('A·m⁻¹','kA·m⁻¹').replace('A/m','kA/m')}:{factor:1,label};
    const sx=axisScale(raw,'x',xLabel),sy=axisScale(raw,'y',yLabel);
    const clean=raw.map(row=>({x:row.x/sx.factor,y:row.y/sy.factor})).sort((a,b)=>a.x-b.x);
    const width=560,height=210,padL=48,padR=22,padT=28,padB=38,xs=clean.map(row=>row.x),ys=clean.map(row=>row.y),xmin=Math.min(...xs),xmax=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys),dx=xmax-xmin||1,rawDy=y1-y0||Math.max(Math.abs(y1),1),yp=Math.max(rawDy*.08,Math.abs(y1||1)*.015),ymin=y0-yp,ymax=y1+yp,dy=ymax-ymin||1;
    const px=x=>padL+(x-xmin)/dx*(width-padL-padR),py=y=>height-padB-(y-ymin)/dy*(height-padT-padB),poly=clean.map(row=>`${px(row.x).toFixed(1)},${py(row.y).toFixed(1)}`).join(' ');
    const fmt=value=>{const a=Math.abs(value);const digits=a>=100?0:a>=10?1:a>=1?2:3;return Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits})};
    const markers=clean.map(row=>`<circle cx="${px(row.x).toFixed(1)}" cy="${py(row.y).toFixed(1)}" r="2.6"/>`).join('');
    return `<article class="material-curve-card-v061"><header><b>${safe(title)}</b><small>${clean.length} 个数据点</small></header><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${safe(title)}"><line class="axis" x1="${padL}" y1="${height-padB}" x2="${width-padR}" y2="${height-padB}"/><line class="axis" x1="${padL}" y1="${padT}" x2="${padL}" y2="${height-padB}"/><line class="guide" x1="${padL}" y1="${py((ymin+ymax)/2)}" x2="${width-padR}" y2="${py((ymin+ymax)/2)}"/><polyline points="${poly}"/>${markers}<text x="${padL}" y="17">${safe(sy.label)}</text><text x="${width-padR}" y="${height-8}" text-anchor="end">${safe(sx.label)}</text><text x="${padL}" y="${height-13}">${safe(fmt(xmin))}</text><text x="${width-padR}" y="${height-13}" text-anchor="end">${safe(fmt(xmax))}</text><text x="${padL-7}" y="${padT+4}" text-anchor="end">${safe(fmt(ymax))}</text><text x="${padL-7}" y="${height-padB+4}" text-anchor="end">${safe(fmt(ymin))}</text></svg></article>`;
  }

  function materialCurvePreview(summary){
    const charts=[],steel=summary?.bh_curve||[],magnet=summary?.magnet_bh_curve||[],derived=summary?.magnet_reference_curve||[],magnetTemp=summary?.magnet_temperature_points||[],loss=summary?.loss_points||[];
    let note='';
    if(steel.length)charts.push(curveChart(steel.map(row=>({x:row.x,y:row.y})),'钢材 B-H 曲线','H / A·m⁻¹','B / T'));
    if(magnet.length){
      const temps=[...new Set(magnet.map(row=>row.temperature).filter(value=>value!==null&&value!==undefined))],target=temps[0],rows=target===undefined?magnet:magnet.filter(row=>row.temperature===target);
      charts.push(curveChart(rows.map(row=>({x:row.h,y:row.b})),`磁体原始退磁曲线${target===undefined?'':` · ${target} °C`}`,'H / A·m⁻¹','B / T'));
    }else if(derived.length){
      const target=summary?.magnet_reference_meta?.reference_temperature;
      charts.push(curveChart(derived.map(row=>({x:row.h,y:row.b})),`磁体退磁参考线${target===undefined?'':` · ${target} °C`}（由 Br / µr 推导）`,'H / A·m⁻¹','B / T'));
      note='<div class="material-curve-note-v088"><b>曲线来源说明</b><span>该 Motor-CAD 材料记录没有原始 BValue_Magnet/HValue_Magnet 采样点。图中退磁工作线由 Br 与 µr 按 B=Br+µ0µrH 推导；HcJ 单独作为内禀矫顽力显示，不把推导线伪装成实测充磁/退磁滞回曲线。</span></div>';
    }
    if(magnetTemp.length){
      charts.push(curveChart(magnetTemp.map(row=>({x:row.temperature,y:row.br})),'剩磁 Br - 温度','T / °C','Br / T'));
      if(magnetTemp.some(row=>Number.isFinite(Number(row.hcj))))charts.push(curveChart(magnetTemp.map(row=>({x:row.temperature,y:row.hcj})),'内禀矫顽力 |HcJ| - 温度','T / °C','HcJ / A·m⁻¹'));
    }
    if(loss.length){const freqs=[...new Set(loss.map(row=>row.frequency).filter(value=>value!==null&&value!==undefined))],target=freqs[0],rows=target===undefined?loss:loss.filter(row=>row.frequency===target);charts.push(curveChart(rows.map(row=>({x:row.flux_density,y:row.loss_density})),`铁损样本${target===undefined?'':` · ${target} Hz`}`,'B / T','Loss / W·kg⁻¹'))}
    const html=charts.filter(Boolean).join('');return html||note?`<section class="material-curve-preview-v061">${note}${html}</section>`:'';
  }

  function propertyDescription(key){
    const direct=propertyMeta[key];if(direct)return direct;
    const base=String(key).replace(/\[\d+\]$/,'');return propertyMeta[base]||['Motor-CAD 原始字段',''];
  }
  function propertyRow(key,value,index){const [label,unit]=propertyDescription(key);return `<tr data-property-row-v061><td><input data-property-key-v061 value="${safe(key)}" aria-label="材料属性键"></td><td><span>${safe(label)}</span>${unit?`<small>${safe(unit)}</small>`:''}</td><td><input data-property-value-v061 value="${safe(value)}" aria-label="材料属性值"></td><td><button type="button" data-property-remove-v061="${index}" title="删除该属性">×</button></td></tr>`}
  function keyPropertyCards(properties){
    const preferred=['Thermal Conductivity','Specific Heat','Density','ElectricalResistivity','LaminationThickness','MagnetBrValue','MagnetHcJValue','MagneturValue','YoungsCoefficient','YieldStress'];
    const rows=preferred.filter(key=>properties[key]!==undefined&&properties[key]!==null&&properties[key]!=="").slice(0,8);
    if(!rows.length)return '<div class="material-key-empty-v066">该材料没有可直接归类的标量关键属性；曲线和完整原始字段仍可在下方查看。</div>';
    return `<section class="material-key-properties-v066">${rows.map(key=>{const [label,unit]=propertyDescription(key);return `<div><span>${safe(label)}</span><b>${safe(properties[key])}${unit?` <em>${safe(unit)}</em>`:''}</b><small>${safe(key)}</small></div>`}).join('')}</section>`;
  }
  function renderDetail(){
    const box=q('#materialDetailV061');if(!box)return;const row=stateV061.selected;
    if(!row){box.innerHTML='<div class="material-detail-empty-v061"><b>选择一种材料</b><span>右侧会显示关键属性、曲线与数据来源。</span></div>';return}
    const properties=row.properties||{},summary=row.summary||{},bh=summary.bh_curve||[],magnetBh=summary.magnet_bh_curve||[],magnetRef=summary.magnet_reference_curve||[],loss=summary.loss_points||[],temps=summary.temperature_curves||{},isNew=!row.id,imported=row.source_kind==='motorcad_database',picker=stateV061.picker;
    const provenance=`<details class="material-provenance-details-v088"><summary><b>来源与数据完整性</b><small>${safe(sourceLabel(row))} · SHA ${safe(hashShort(row.material_section_hash))}</small></summary><div class="material-provenance-v061"><div><span>来源数据库</span><b title="${safe(row.source_database_path||'')}">${safe(row.source_database_path||'Studio 管理库')}</b></div><div><span>源文件 SHA-256</span><b title="${safe(row.source_database_hash||'')}">${safe(hashShort(row.source_database_hash))}</b></div><div><span>材料段 SHA-256</span><b title="${safe(row.material_section_hash||'')}">${safe(hashShort(row.material_section_hash))}</b></div><div><span>Motor-CAD 版本标记</span><b>${safe(row.motorcad_version||stateV061.status?.motorcad_version||'—')}</b></div></div></details>`;
    const editor=picker?'':`<form id="materialEditorV061" class="material-editor-v061"><div class="material-editor-basics-v061"><label><span>材料名称</span><input id="materialNameV061" value="${safe(row.name||'')}"></label><label><span>介质</span><select id="materialKindV061"><option value="solid" ${row.kind!=='fluid'?'selected':''}>固体</option><option value="fluid" ${row.kind==='fluid'?'selected':''}>流体</option></select></label><label><span>材料类型</span><select id="materialTypeV061" ${row.kind==='fluid'?'disabled':''}><option value="General" ${row.material_type==='General'?'selected':''}>General / 通用</option><option value="Magnet" ${row.material_type==='Magnet'?'selected':''}>Magnet / 永磁体</option><option value="Steel" ${row.material_type==='Steel'?'selected':''}>Steel / 电工钢</option><option value="Fluid" ${row.material_type==='Fluid'?'selected':''}>Fluid / 流体</option></select></label></div><details class="material-raw-properties-v066" ${isNew?'open':''}><summary><span><b>完整 Motor-CAD 原始属性</b><small>${Object.keys(properties).length} 个字段 · 需要时展开编辑</small></span></summary><div class="material-property-head-v061"><div><h4>原始字段与数值</h4><p>需要核对数据库原始字段时展开查看。</p></div><button type="button" data-property-add-v061>＋ 添加属性</button></div><div class="material-property-table-v061"><table><thead><tr><th>Motor-CAD 字段</th><th>工程含义与单位</th><th>值</th><th></th></tr></thead><tbody id="materialPropertyRowsV061">${Object.entries(properties).map(([key,value],index)=>propertyRow(key,value,index)).join('')}</tbody></table></div></details><footer><small>${imported?'保存后生成可编辑的 Studio 材料副本。':'保存只修改 Studio 管理记录。'}</small><button type="submit" class="primary" data-material-save-v089g2>${isNew?'创建材料':'保存材料库记录'}</button></footer></form>`;
    const pickerFooter=picker&&row.id?`<div class="material-picker-assign-footer-v088"><div><b>将“${safe(row.name)}”赋值给：${safe(picker.componentLabel||'当前部件')}</b><small>此操作只更新当前设计草稿的材料绑定，不修改材料数据库。也可以在左侧双击该材料直接完成赋值。</small></div><button type="button" class="primary" data-material-choose-v062>确认选中并赋值</button></div>`:'';
    box.innerHTML=`<div class="material-detail-head-v061"><div><span>${isNew?'新建材料':safe(sourceLabel(row))}</span><h3>${safe(row.name||'未命名材料')}</h3><p>${picker?'正在预览材料；确认赋值只会更新当前部件的设计草稿。':imported?'来源：本机 Motor-CAD 材料库 · 当前记录只读。':'当前记录由 Studio 管理，可直接编辑保存。'}</p></div><div class="material-detail-actions-v061">${!picker&&row.id?`<button type="button" data-material-clone-v061>复制为新材料</button><button type="button" data-material-delete-v061 class="danger">${imported?'从 Studio 索引移除':'删除材料'}</button>`:''}</div></div>
      ${provenance}<div class="material-curve-metrics-v061">${curveMetric('钢材 B-H 点',bh.length)}${curveMetric('磁体原始点',magnetBh.length)}${curveMetric('磁体参考点',magnetRef.length)}${curveMetric('损耗数据点',loss.length)}${curveMetric('原始字段',Object.keys(properties).length)}</div><div class="material-detail-section-title-v066"><b>关键工程属性</b><span>优先显示常用标量；曲线和原始字段保留数据来源说明。</span></div>${keyPropertyCards(properties)}${materialCurvePreview(summary)}${editor}${pickerFooter}`;
    bindDetail(box);
  }

  function scalar(text){const value=String(text??'').trim();if(value==='')return '';if(/^true$/i.test(value))return true;if(/^false$/i.test(value))return false;if(/^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(value)){const n=Number(value);if(Number.isFinite(n))return n}return value}
  function collectEditor(){const properties={};qa('[data-property-row-v061]').forEach(row=>{const key=q('[data-property-key-v061]',row)?.value.trim();if(!key)return;properties[key]=scalar(q('[data-property-value-v061]',row)?.value)});const kind=q('#materialKindV061')?.value||'solid',materialType=kind==='fluid'?'Fluid':q('#materialTypeV061')?.value||'General';return{name:q('#materialNameV061')?.value.trim(),kind,material_type:materialType,properties}}
  function bindDetail(root){
    q('#materialKindV061',root)?.addEventListener('change',event=>{const type=q('#materialTypeV061',root);if(type){type.disabled=event.target.value==='fluid';if(event.target.value==='fluid')type.value='Fluid';else if(type.value==='Fluid')type.value='General'}});
    q('[data-property-add-v061]',root)?.addEventListener('click',()=>{q('#materialPropertyRowsV061',root)?.insertAdjacentHTML('beforeend',propertyRow('', '', Date.now()));bindPropertyRemove(root);const rows=qa('[data-property-row-v061]',root);q('[data-property-key-v061]',rows.at(-1))?.focus()});bindPropertyRemove(root);
    q('#materialEditorV061',root)?.addEventListener('submit',saveRecord);
    q('[data-material-clone-v061]',root)?.addEventListener('click',cloneRecord);
    q('[data-material-delete-v061]',root)?.addEventListener('click',deleteRecord);
    q('[data-material-choose-v062]',root)?.addEventListener('click',chooseSelected);
  }
  function bindPropertyRemove(root){qa('[data-property-remove-v061]',root).forEach(button=>{if(button.dataset.boundV061)return;button.dataset.boundV061='1';button.addEventListener('click',()=>button.closest('[data-property-row-v061]')?.remove())})}
  async function saveRecord(event){event.preventDefault();const payload=collectEditor();if(!payload.name)return toast('材料名称不能为空。','WARNING');try{const imported=stateV061.selected?.source_kind==='motorcad_database',saved=stateV061.selected?.id?await api(`/api/material-library/${encodeURIComponent(stateV061.selected.id)}`,{method:'PATCH',body:JSON.stringify(payload)}):await api('/api/material-library',{method:'POST',body:JSON.stringify(payload)});toast(imported?'已创建 Studio 管理副本；Motor-CAD 源数据库保持不变。':'材料已保存。','SUCCESS',5200);await refreshAll(saved.id)}catch(error){toast(`材料保存失败：${error.message}`,'ERROR',7000)}}
  async function cloneRecord(){const row=stateV061.selected;if(!row?.id)return;try{const saved=await api(`/api/material-library/${encodeURIComponent(row.id)}/clone`,{method:'POST',body:JSON.stringify({name:`${row.name} - Studio`})});toast('已复制为 Studio 管理材料。','SUCCESS');await refreshAll(saved.id)}catch(error){toast(`复制失败：${error.message}`,'ERROR')}}
  async function deleteRecord(){const row=stateV061.selected;if(!row?.id)return;const message=row.source_kind==='motorcad_database'?`仅从 Studio 索引移除“${row.name}”？源 .mdb 不会删除。`:`删除 Studio 材料“${row.name}”？`;const ok=window.StudioDialog?.confirm?await StudioDialog.confirm({title:'确认材料操作',message,confirmText:'确认',danger:true,key:`material-delete:${row.id}`}):false;if(!ok)return;try{await api(`/api/material-library/${encodeURIComponent(row.id)}`,{method:'DELETE'});stateV061.selected=null;toast(row.source_kind==='motorcad_database'?'已从 Studio 索引移除；源数据库未改动。':'材料已删除。','SUCCESS');await refreshAll()}catch(error){toast(`删除失败：${error.message}`,'ERROR')}}
  function chooseSelected(){const row=stateV061.selected,picker=stateV061.picker;if(!row?.id||!picker)return;const callback=picker.onSelect;const snapshot={id:row.id,name:row.name,kind:row.kind,material_type:row.material_type,source_kind:row.source_kind,source_database_path:row.source_database_path||'',source_database_hash:row.source_database_hash||'',material_section_hash:row.material_section_hash||'',motorcad_version:row.motorcad_version||stateV061.status?.motorcad_version||''};q('#materialLibraryV061')?.remove();stateV061.picker=null;if(!q('#materialLibraryV061'))document.body.classList.remove('engineering-sheet-open');if(typeof callback==='function')callback(snapshot)}
  async function selectRecord(id){try{stateV061.selected=await api(`/api/material-library/${encodeURIComponent(id)}`);renderList();renderDetail()}catch(error){toast(`材料详情读取失败：${error.message}`,'ERROR')}}
  function newRecord(){stateV061.selected={id:null,name:'',kind:'solid',material_type:'General',source_kind:'studio_custom',properties:{Type:'Fixed_Solid','Solid Type':'General'},summary:{bh_curve:[],loss_points:[],temperature_curves:{}}};renderList();renderDetail();requestAnimationFrame(()=>q('#materialNameV061')?.focus())}
  async function scan(){const button=q('[data-material-scan-v061]');try{if(button){button.disabled=true;button.textContent='正在扫描…'}const result=await api('/api/material-library/scan',{method:'POST',body:'{}'});const count=(result.imported||[]).reduce((sum,row)=>sum+Number(row.material_count||0),0);toast(result.imported?.length?`扫描完成：载入 ${result.imported.length} 个数据库、${count} 条材料记录。`:'未自动发现可读取的 Motor-CAD .mdb，请使用数据库路径导入。',result.imported?.length?'SUCCESS':'WARNING',6500);await refreshAll()}catch(error){toast(`扫描失败：${error.message}`,'ERROR',7000)}finally{if(button){button.disabled=false;button.textContent='扫描本机 Motor-CAD 数据库'}}}
  async function importPath(){const input=q('#materialDatabasePathV061'),path=input?.value.trim();if(!path)return toast('请填写 Solids.mdb 或 Fluids.mdb 的完整路径。','WARNING');const button=q('[data-material-import-v061]');try{button.disabled=true;const result=await api('/api/material-library/import',{method:'POST',body:JSON.stringify({path,replace:true})});toast(`已载入 ${result.material_count} 条材料记录。`,'SUCCESS');await refreshAll()}catch(error){toast(`数据库导入失败：${error.message}`,'ERROR',7000)}finally{if(button)button.disabled=false}}
  async function exportManaged(kind){try{const result=await api('/api/material-library/export-managed',{method:'POST',body:JSON.stringify({kind})});const box=q('#materialExportResultV061');if(box)box.innerHTML=`<b>${kind==='solid'?'固体':'流体'}管理数据库已生成</b><code>${safe(result.path)}</code><small>${result.material_count} 条记录 · SHA-256 ${safe(hashShort(result.file_hash))}</small>${kind==='solid'?`<button type="button" data-material-use-v061="${safe(result.path)}">用于当前计算配置</button>`:''}`;q('[data-material-use-v061]',box)?.addEventListener('click',event=>useManagedDatabase(event.currentTarget.dataset.materialUseV061));toast('管理数据库已导出。','SUCCESS')}catch(error){toast(`材料数据库导出失败：${error.message}`,'ERROR',7000)}}
  function useManagedDatabase(path){const input=q('#materialDb');if(!input){toast('当前页面没有计算材料库输入项；创建/打开分析案例后再选择此数据库。','WARNING',6000);return}input.value=path;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));toast('已写入当前计算配置的材料数据库路径。保存/提交计算时生效。','SUCCESS',6000)}
  function bindShell(node){
    q('[data-material-scan-v061]',node)?.addEventListener('click',scan);q('[data-material-import-v061]',node)?.addEventListener('click',importPath);q('[data-material-new-v061]',node)?.addEventListener('click',newRecord);q('[data-material-export-solid-v061]',node)?.addEventListener('click',()=>exportManaged('solid'));q('[data-material-export-fluid-v061]',node)?.addEventListener('click',()=>exportManaged('fluid'));
    q('#materialSearchV061',node)?.addEventListener('input',event=>{stateV061.query=event.target.value;clearTimeout(stateV061.searchTimer);stateV061.searchTimer=setTimeout(()=>refreshRecords(),180)});
    q('#materialKindFilterV061',node)?.addEventListener('change',event=>{stateV061.kind=event.target.value;refreshRecords()});q('#materialTypeFilterV061',node)?.addEventListener('change',event=>{stateV061.materialType=event.target.value;refreshRecords()});
  }
  function renderShellBody(){
    const body=q('#materialLibraryBodyV061');if(!body)return;const picker=stateV061.picker;
    body.classList.toggle('picker-mode-v088',Boolean(picker));
    const intro=picker?'':`<div class="material-library-compact-head-v089g1r"><div><b>Motor-CAD 材料库</b><span>${stateV061.status?.records??0} 条材料 · Studio 管理 ${stateV061.status?.custom_records??0} 条 · Motor-CAD ${safe(stateV061.status?.motorcad_version||'—')}</span></div><button type="button" class="primary" data-material-scan-v061>重新扫描</button></div><details class="material-source-details-v089g1r"><summary><span><b>数据库来源</b><small>已载入的 Solids.mdb / Fluids.mdb 与手动导入路径</small></span><em>展开</em></summary><section class="material-source-section-v061"><div class="material-import-row-v061"><input id="materialDatabasePathV061" placeholder="例如 C:\\Users\\...\\Solids.mdb"><button type="button" data-material-import-v061>按路径导入</button></div><div class="material-source-grid-v061">${sourceCards()}</div></section></details>`;
    const banner=picker?`<div class="material-picker-banner-v062"><b>正在为：${safe(picker.componentLabel||'当前部件')} 选择材料</b><span>单击查看属性/曲线；双击材料可直接赋值。材料库的“保存”与电机部件“赋值”已经分离。</span></div>`:'';
    body.innerHTML=`${banner}${intro}<section class="material-manager-v061 ${picker?'picker-v088':''}"><aside><header><div><h3>材料列表</h3><p>${picker?'选择目标材料；双击直接赋值。':'按名称、介质和材料类型筛选。'}</p></div>${picker?'':'<button type="button" data-material-new-v061>＋ 新建</button>'}</header><div class="material-filter-v061"><input id="materialSearchV061" placeholder="搜索材料名称" value="${safe(stateV061.query)}"><select id="materialKindFilterV061"><option value="">全部介质</option><option value="solid" ${stateV061.kind==='solid'?'selected':''}>固体</option><option value="fluid" ${stateV061.kind==='fluid'?'selected':''}>流体</option></select><select id="materialTypeFilterV061"><option value="">全部类型</option><option value="General" ${stateV061.materialType==='General'?'selected':''}>General</option><option value="Magnet" ${stateV061.materialType==='Magnet'?'selected':''}>Magnet</option><option value="Steel" ${stateV061.materialType==='Steel'?'selected':''}>Steel</option><option value="Fluid" ${stateV061.materialType==='Fluid'?'selected':''}>Fluid</option></select></div><div id="materialRecordListV061" class="material-record-list-v061"></div>${picker?'':`<div class="material-export-v061"><b>导出 Studio 管理数据库</b><p>生成标准 .mdb，可作为计算配置的材料数据库来源。</p><div><button type="button" data-material-export-solid-v061>导出固体 .mdb</button><button type="button" data-material-export-fluid-v061>导出流体 .mdb</button></div><div id="materialExportResultV061"></div></div>`}</aside><main id="materialDetailV061"></main></section>`;
    bindShell(q('#materialLibraryV061'));renderList();renderDetail();
  }

  async function refreshRecords(preferredId=null){const params=new URLSearchParams();if(stateV061.query)params.set('q',stateV061.query);if(stateV061.kind)params.set('kind',stateV061.kind);if(stateV061.materialType)params.set('material_type',stateV061.materialType);params.set('limit','1500');try{const result=await api(`/api/material-library?${params.toString()}`);stateV061.records=result.records||[];const preserved=stateV061.selected?.id&&stateV061.records.some(row=>row.id===stateV061.selected.id)?stateV061.selected.id:null;const nextId=preferredId||preserved||stateV061.records[0]?.id||null;if(nextId){stateV061.selected=await api(`/api/material-library/${encodeURIComponent(nextId)}`)}else{stateV061.selected=null}renderList();renderDetail()}catch(error){toast(`材料列表读取失败：${error.message}`,'ERROR')}}
  async function refreshAll(preferredId=null){try{stateV061.status=await api('/api/material-library/status');await refreshRecords(preferredId);renderShellBody();if(preferredId)await selectRecord(preferredId)}catch(error){const body=q('#materialLibraryBodyV061');if(body)body.innerHTML=`<div class="material-detail-empty-v061"><b>材料模块无法加载</b><span>${safe(error.message)}</span></div>`;toast(`材料模块加载失败：${error.message}`,'ERROR',7000)}}
  async function open(options={}){stateV061.picker=options?.picker?options:null;if(stateV061.picker){stateV061.kind=options.kind||'solid';stateV061.materialType=options.materialType||'';stateV061.query='';stateV061.selected=null}shell();await refreshAll()}
  async function pick(options={}){return open({...options,picker:true})}
  document.addEventListener('click',event=>{if(event.target.closest?.('[data-open-material-library-v061]')){event.preventDefault();open()}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&q('#materialLibraryV061'))close()});
  window.addEventListener('mcs:navigation-transaction-committed',()=>{if(q('#materialLibraryV061'))close()});
  window.MCSMaterialLibrary={open,pick,close,refresh:refreshAll,state:stateV061};
})();
