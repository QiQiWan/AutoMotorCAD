/* V0.65 stable FEA and thermal result visualization enhancements.
 * Owns result rendering only; Design Viewer lifecycle is isolated in static/design/viewer.js.
 */
(() => {
  const $q=(selector,root=document)=>root.querySelector(selector);
  const $$q=(selector,root=document)=>[...root.querySelectorAll(selector)];
  const safe=value=>typeof window.esc==='function'?window.esc(value):String(value??'');
  const number=(value,fallback=0)=>{const parsed=Number(value);if(value!==null&&value!==''&&Number.isFinite(parsed))return parsed;const backup=Number(fallback);return Number.isFinite(backup)?backup:fallback};
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const fmt=(value,digits=3)=>{if(value===null||value===undefined||value==='')return'—';const n=Number(value);return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:digits}):String(value)};
  const feaState={caseId:null,fieldKey:null,mesh:false,outlines:true,vectors:false,legend:true,range:'auto'};
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
    canvas.innerHTML=`<section class="fea-workbench-v031"><div class="fea-toolbar-v031"><label>着色场<select id="feaFieldV031">${Object.entries(fields).map(([key,field])=>`<option value="${safe(key)}" ${key===feaState.fieldKey?'selected':''}>${safe(field.value_label||key)}${field.unit?` · ${safe(field.unit)}`:''}</option>`).join('')}</select></label><label>色标<select id="feaRangeV031"><option value="auto" ${feaState.range==='auto'?'selected':''}>自动范围</option><option value="p98" ${feaState.range==='p98'?'selected':''}>2–98% 分位</option></select></label><label class="check-row"><input id="feaLegendV031" type="checkbox" ${feaState.legend?'checked':''}>图例</label><label class="check-row"><input id="feaOutlinesV031" type="checkbox" ${feaState.outlines?'checked':''}>外框</label><label class="check-row"><input id="feaMeshV031" type="checkbox" ${feaState.mesh?'checked':''}>网格</label><label class="check-row"><input id="feaVectorsV031" type="checkbox" ${feaState.vectors?'checked':''} ${Object.keys(viewer.results?.vectors||{}).length?'':'disabled'}>矢量</label><span class="native-data-chip-v031">当前计算场数据</span></div><div id="feaSceneV031" class="fea-scene-v031"></div><div class="visual-authority-v031"><span>数据来源</span><b>当前计算记录的 Motor-CAD 有限元空间场</b><em>缺少求解节点、单元或场值时不生成替代云图</em></div></section>`;
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
  window.MCSResultVisuals={enhanceFEAViewer,enhanceThermalViewer,renderFEAScene,feaState};
})();
