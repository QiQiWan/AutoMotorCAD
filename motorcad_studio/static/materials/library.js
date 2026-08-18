/* MotorCAD Studio V0.66 material library module — searchable local Motor-CAD engineering data. */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const stateV061={status:null,records:[],selected:null,query:'',kind:'',materialType:'',searchTimer:null,picker:null};
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

  function close(){q('#materialLibraryV061')?.remove();stateV061.picker=null;if(!q('.engineering-sheet-v040,.engineering-sheet-v060,#materialLibraryV061'))document.body.classList.remove('engineering-sheet-open')}
  function shell(){
    window.MCSCloseEngineeringSheets?.();close();
    const node=document.createElement('div');node.id='materialLibraryV061';node.className='material-library-shell-v061';
    const picker=stateV061.picker;
    node.innerHTML=`<div class="material-library-backdrop-v061"></div><section role="dialog" aria-modal="true" aria-label="Motor-CAD 材料库"><header><div><span>${picker?'材料选择':'材料工程数据'}</span><h2>${safe(picker?.title||'Motor-CAD 材料库')}</h2><p>${picker?'选择材料后会返回当前设计草稿；材料原始属性和来源仍由材料库管理。':'读取本机实际 .mdb，保留来源与文件哈希；编辑导入材料时创建 Studio 管理副本。'}</p></div><button type="button" data-material-close-v061 aria-label="关闭">×</button></header><div id="materialLibraryBodyV061" class="material-library-body-v061"><div class="material-loading-v061">正在读取材料数据库状态…</div></div></section>`;
    document.body.appendChild(node);document.body.classList.add('engineering-sheet-open');
    q('[data-material-close-v061]',node)?.addEventListener('click',close);q('.material-library-backdrop-v061',node)?.addEventListener('click',close);return node;
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
  function renderList(){const box=q('#materialRecordListV061');if(!box)return;box.innerHTML=stateV061.records.length?stateV061.records.map(recordItem).join(''):'<div class="material-list-empty-v061">当前筛选条件没有材料记录。</div>';qa('[data-material-record-v061]',box).forEach(button=>button.addEventListener('click',()=>selectRecord(button.dataset.materialRecordV061)))}
  function curveMetric(label,count){return `<div><span>${safe(label)}</span><b>${Number(count)||0}</b></div>`}
  function curveChart(points,title,xLabel,yLabel){
    const clean=(points||[]).map(row=>({x:Number(row.x),y:Number(row.y)})).filter(row=>Number.isFinite(row.x)&&Number.isFinite(row.y));if(clean.length<2)return'';
    clean.sort((a,b)=>a.x-b.x);const width=520,height=190,pad=34,xs=clean.map(row=>row.x),ys=clean.map(row=>row.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),dx=xmax-xmin||1,dy=ymax-ymin||1;
    const px=x=>pad+(x-xmin)/dx*(width-2*pad),py=y=>height-pad-(y-ymin)/dy*(height-2*pad),poly=clean.map(row=>`${px(row.x).toFixed(1)},${py(row.y).toFixed(1)}`).join(' ');
    return `<article class="material-curve-card-v061"><header><b>${safe(title)}</b><small>${clean.length} points</small></header><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${safe(title)}"><line x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}"/><line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height-pad}"/><polyline points="${poly}"/><text x="${pad}" y="18">${safe(yLabel)}</text><text x="${width-pad}" y="${height-8}" text-anchor="end">${safe(xLabel)}</text><text x="${pad}" y="${height-12}">${safe(Number(xmin).toPrecision(4))}</text><text x="${width-pad}" y="${height-12}" text-anchor="end">${safe(Number(xmax).toPrecision(4))}</text></svg></article>`;
  }
  function materialCurvePreview(summary){
    const charts=[],steel=summary?.bh_curve||[],magnet=summary?.magnet_bh_curve||[],loss=summary?.loss_points||[];
    if(steel.length)charts.push(curveChart(steel.map(row=>({x:row.x,y:row.y})),'钢材 B-H 曲线','H / A·m⁻¹','B / T'));
    if(magnet.length){const temps=[...new Set(magnet.map(row=>row.temperature).filter(value=>value!==null&&value!==undefined))],target=temps[0],rows=target===undefined?magnet:magnet.filter(row=>row.temperature===target);charts.push(curveChart(rows.map(row=>({x:row.h,y:row.b})),`磁体退磁曲线${target===undefined?'':` · ${target} °C`}`,'H / A·m⁻¹','B / T'))}
    if(loss.length){const freqs=[...new Set(loss.map(row=>row.frequency).filter(value=>value!==null&&value!==undefined))],target=freqs[0],rows=target===undefined?loss:loss.filter(row=>row.frequency===target);charts.push(curveChart(rows.map(row=>({x:row.flux_density,y:row.loss_density})),`铁损样本${target===undefined?'':` · ${target} Hz`}`,'B / T','Loss / W·kg⁻¹'))}
    const html=charts.filter(Boolean).join('');return html?`<section class="material-curve-preview-v061">${html}</section>`:'';
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
    if(!row){box.innerHTML='<div class="material-detail-empty-v061"><b>选择一种材料</b><span>右侧会显示完整原始参数、B-H 曲线点、损耗点和数据来源。</span></div>';return}
    const properties=row.properties||{},summary=row.summary||{},bh=summary.bh_curve||[],magnetBh=summary.magnet_bh_curve||[],loss=summary.loss_points||[],temps=summary.temperature_curves||{},isNew=!row.id,imported=row.source_kind==='motorcad_database';
    box.innerHTML=`<div class="material-detail-head-v061"><div><span>${isNew?'新建材料':safe(sourceLabel(row))}</span><h3>${safe(row.name||'未命名材料')}</h3><p>${imported?'当前记录是本机 Motor-CAD 数据库的只读快照。修改并保存后会创建 Studio 管理副本，源 .mdb 不会被写入。':'当前记录由 Studio 管理；导出管理数据库后可在计算配置中选用。'}</p></div><div class="material-detail-actions-v061">${stateV061.picker&&row.id?`<button type="button" class="primary" data-material-choose-v062>用于当前部件</button>`:''}${row.id?`<button type="button" data-material-clone-v061>复制为新材料</button><button type="button" data-material-delete-v061 class="danger">${imported?'从 Studio 索引移除':'删除材料'}</button>`:''}</div></div>
      <div class="material-provenance-v061"><div><span>来源数据库</span><b title="${safe(row.source_database_path||'')}">${safe(row.source_database_path||'Studio 管理库')}</b></div><div><span>源文件 SHA-256</span><b title="${safe(row.source_database_hash||'')}">${safe(hashShort(row.source_database_hash))}</b></div><div><span>材料段 SHA-256</span><b title="${safe(row.material_section_hash||'')}">${safe(hashShort(row.material_section_hash))}</b></div><div><span>Motor-CAD 版本标记</span><b>${safe(row.motorcad_version||stateV061.status?.motorcad_version||'—')}</b></div></div>
      <div class="material-curve-metrics-v061">${curveMetric('钢材 B-H 点',bh.length)}${curveMetric('磁体退磁点',magnetBh.length)}${curveMetric('损耗数据点',loss.length)}${curveMetric('温变属性组',Object.keys(temps).length)}${curveMetric('原始字段',Object.keys(properties).length)}</div><div class="material-detail-section-title-v066"><b>关键工程属性</b><span>优先显示常用标量；曲线和原始字段保留完整数据。</span></div>${keyPropertyCards(properties)}${materialCurvePreview(summary)}
      <form id="materialEditorV061" class="material-editor-v061"><div class="material-editor-basics-v061"><label><span>材料名称</span><input id="materialNameV061" value="${safe(row.name||'')}"></label><label><span>介质</span><select id="materialKindV061"><option value="solid" ${row.kind!=='fluid'?'selected':''}>固体</option><option value="fluid" ${row.kind==='fluid'?'selected':''}>流体</option></select></label><label><span>材料类型</span><select id="materialTypeV061" ${row.kind==='fluid'?'disabled':''}><option value="General" ${row.material_type==='General'?'selected':''}>General / 通用</option><option value="Magnet" ${row.material_type==='Magnet'?'selected':''}>Magnet / 永磁体</option><option value="Steel" ${row.material_type==='Steel'?'selected':''}>Steel / 电工钢</option><option value="Fluid" ${row.material_type==='Fluid'?'selected':''}>Fluid / 流体</option></select></label></div><details class="material-raw-properties-v066" ${isNew?'open':''}><summary><span><b>完整 Motor-CAD 原始属性</b><small>${Object.keys(properties).length} 个字段 · 需要时展开编辑</small></span></summary><div class="material-property-head-v061"><div><h4>原始 Key / Value</h4><p>含磁体参数、B-H 点、铁损点、温变热物性及机械参数。</p></div><button type="button" data-property-add-v061>＋ 添加属性</button></div><div class="material-property-table-v061"><table><thead><tr><th>Motor-CAD Key</th><th>工程含义 / 单位</th><th>值</th><th></th></tr></thead><tbody id="materialPropertyRowsV061">${Object.entries(properties).map(([key,value],index)=>propertyRow(key,value,index)).join('')}</tbody></table></div></details><footer><small>${imported?'保存会生成新的 Studio 材料记录；源数据库保持原样。':'保存只修改 Studio 管理记录。'}</small><button type="submit" class="primary">${isNew?'创建材料':'保存材料'}</button></footer></form>`;
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
  async function deleteRecord(){const row=stateV061.selected;if(!row?.id)return;const message=row.source_kind==='motorcad_database'?`仅从 Studio 索引移除“${row.name}”？源 .mdb 不会删除。`:`删除 Studio 材料“${row.name}”？`;if(!window.confirm(message))return;try{await api(`/api/material-library/${encodeURIComponent(row.id)}`,{method:'DELETE'});stateV061.selected=null;toast(row.source_kind==='motorcad_database'?'已从 Studio 索引移除；源数据库未改动。':'材料已删除。','SUCCESS');await refreshAll()}catch(error){toast(`删除失败：${error.message}`,'ERROR')}}
  function chooseSelected(){const row=stateV061.selected,picker=stateV061.picker;if(!row?.id||!picker)return;const callback=picker.onSelect;const snapshot={id:row.id,name:row.name,kind:row.kind,material_type:row.material_type,source_kind:row.source_kind,source_database_path:row.source_database_path||'',source_database_hash:row.source_database_hash||'',material_section_hash:row.material_section_hash||'',motorcad_version:row.motorcad_version||stateV061.status?.motorcad_version||''};q('#materialLibraryV061')?.remove();stateV061.picker=null;if(!q('.engineering-sheet-v040,.engineering-sheet-v060,#materialLibraryV061'))document.body.classList.remove('engineering-sheet-open');if(typeof callback==='function')callback(snapshot)}
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
    const body=q('#materialLibraryBodyV061');if(!body)return;
    body.innerHTML=`${stateV061.picker?`<div class="material-picker-banner-v062"><b>正在为：${safe(stateV061.picker.componentLabel||'当前部件')} 选择材料</b><span>选择左侧材料，检查关键属性/曲线后点击右上角「用于当前部件」。</span></div>`:`<div class="material-manager-mode-v066"><b>材料管理模式</b><span>这里用于检索、查看曲线和维护数据库，不会直接改动当前 Design Revision。应用材料请回到「材料配置」并点击具体部件的「选择/更换材料」。</span></div>`}<div class="material-library-intro-v061"><div><span>本机数据优先</span><h3>以当前 Motor-CAD 安装实际数据库为材料事实源</h3><p>扫描会读取默认文件位置和可发现的 Solids.mdb / Fluids.mdb。导入内容作为只读快照；工程修改进入 Studio 管理副本，避免覆盖 Motor-CAD 原始材料库。</p></div><div class="material-library-counts-v061"><div><span>材料记录</span><b>${stateV061.status?.records??0}</b></div><div><span>Studio 管理</span><b>${stateV061.status?.custom_records??0}</b></div><div><span>Motor-CAD</span><b>${safe(stateV061.status?.motorcad_version||'—')}</b></div></div></div>
      <section class="material-source-section-v061"><header><div><h3>数据库来源</h3><p>优先扫描 Motor-CAD Defaults.INI 指向的实际数据库，也支持手工输入 .mdb 路径。</p></div><button type="button" class="primary" data-material-scan-v061>扫描本机 Motor-CAD 数据库</button></header><div class="material-import-row-v061"><input id="materialDatabasePathV061" placeholder="例如 C:\\Users\\...\\Solids.mdb"><button type="button" data-material-import-v061>按路径导入</button></div><div class="material-source-grid-v061">${sourceCards()}</div></section>
      <section class="material-manager-v061"><aside><header><div><h3>材料列表</h3><p>按名称、介质和材料类型筛选。</p></div><button type="button" data-material-new-v061>＋ 新建</button></header><div class="material-filter-v061"><input id="materialSearchV061" placeholder="搜索材料名称" value="${safe(stateV061.query)}"><select id="materialKindFilterV061"><option value="">全部介质</option><option value="solid" ${stateV061.kind==='solid'?'selected':''}>固体</option><option value="fluid" ${stateV061.kind==='fluid'?'selected':''}>流体</option></select><select id="materialTypeFilterV061"><option value="">全部类型</option><option value="General" ${stateV061.materialType==='General'?'selected':''}>General</option><option value="Magnet" ${stateV061.materialType==='Magnet'?'selected':''}>Magnet</option><option value="Steel" ${stateV061.materialType==='Steel'?'selected':''}>Steel</option><option value="Fluid" ${stateV061.materialType==='Fluid'?'selected':''}>Fluid</option></select></div><div id="materialRecordListV061" class="material-record-list-v061"></div><div class="material-export-v061"><b>导出 Studio 管理数据库</b><p>生成标准 .mdb，可作为计算配置的材料数据库来源。</p><div><button type="button" data-material-export-solid-v061>导出固体 .mdb</button><button type="button" data-material-export-fluid-v061>导出流体 .mdb</button></div><div id="materialExportResultV061"></div></div></aside><main id="materialDetailV061"></main></section>`;
    bindShell(q('#materialLibraryV061'));renderList();renderDetail();
  }
  async function refreshRecords(preferredId=null){const params=new URLSearchParams();if(stateV061.query)params.set('q',stateV061.query);if(stateV061.kind)params.set('kind',stateV061.kind);if(stateV061.materialType)params.set('material_type',stateV061.materialType);params.set('limit','1500');try{const result=await api(`/api/material-library?${params.toString()}`);stateV061.records=result.records||[];const preserved=stateV061.selected?.id&&stateV061.records.some(row=>row.id===stateV061.selected.id)?stateV061.selected.id:null;const nextId=preferredId||preserved||stateV061.records[0]?.id||null;if(nextId){stateV061.selected=await api(`/api/material-library/${encodeURIComponent(nextId)}`)}else{stateV061.selected=null}renderList();renderDetail()}catch(error){toast(`材料列表读取失败：${error.message}`,'ERROR')}}
  async function refreshAll(preferredId=null){try{stateV061.status=await api('/api/material-library/status');await refreshRecords(preferredId);renderShellBody();if(preferredId)await selectRecord(preferredId)}catch(error){const body=q('#materialLibraryBodyV061');if(body)body.innerHTML=`<div class="material-detail-empty-v061"><b>材料模块无法加载</b><span>${safe(error.message)}</span></div>`;toast(`材料模块加载失败：${error.message}`,'ERROR',7000)}}
  async function open(options={}){stateV061.picker=options?.picker?options:null;if(stateV061.picker){stateV061.kind=options.kind||'solid';stateV061.materialType=options.materialType||'';stateV061.query='';stateV061.selected=null}shell();await refreshAll()}
  async function pick(options={}){return open({...options,picker:true})}
  document.addEventListener('click',event=>{if(event.target.closest?.('[data-open-material-library-v061]')){event.preventDefault();open()}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&q('#materialLibraryV061'))close()});
  window.MCSMaterialLibrary={open,pick,close,refresh:refreshAll,state:stateV061};
})();
