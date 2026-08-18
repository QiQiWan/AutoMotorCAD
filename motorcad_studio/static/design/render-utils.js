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
  const viewData=ctx=>{const source=ctx.data||{},data=ctx.materials?{...source,materials:ctx.materials}:source;return{data,values:ctx.values||source.effective_parameters||{},precheck:ctx.precheck||source.precheck||{},editable:Boolean(ctx.editable),selected:ctx.selected||null}};
  const authorityStrip=(label='Studio 参数化即时示意')=>`<div class="visual-authority-v031"><span>视图用途</span><b>${safe(label)}</b><em>Motor-CAD 原生几何 / 绕组 / FEA 为最终权威</em></div>`;
  const phaseColors=['#e5484d','#2563eb','#16a36a','#8b5cf6','#e07a24','#64748b'];
  window.MCSDesignRenderUtils={safe,number,clamp,fmt,parameterRecord,selectAttribute,polar,ringSegment,viewData,authorityStrip,phaseColors};
})();
