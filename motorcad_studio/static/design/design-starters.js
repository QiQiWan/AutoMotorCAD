/* V0.87-A-D Guided Engineer UX + Golden Motor Design Starters */
(() => {
  const q=(s,r=document)=>r?.querySelector?.(s)||null;
  const qa=(s,r=document)=>[...(r?.querySelectorAll?.(s)||[])];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={payload:null,selected:null,loading:false};
  const apiCall=async(path,opts={})=>{
    if(window.api)return window.api(path,opts);
    const r=await fetch(path,{cache:'no-store',headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});
    if(!r.ok){let detail='';try{const p=await r.json();detail=p.detail||JSON.stringify(p)}catch(_){detail=await r.text()}throw new Error(detail||`HTTP ${r.status}`)}
    return r.json();
  };
  const projectId=()=>window.MCSEngineeringContext?.get?.().projectId||localStorage.getItem('motorcad-studio-active-project')||null;
  const qualificationLabel=qv=>qv?.production_verified?'生产已验证':'工程预制 · 待 Windows 实机资格';
  const card=s=>`<article class="golden-starter-card-v087" data-starter-card="${esc(s.id)}">
    <div class="golden-starter-card-head-v087"><div><span class="starter-type-v087">${esc(s.short_label)}</span><h3>${esc(s.label)}</h3></div><span class="starter-qualification-v087 ${s.qualification?.production_verified?'verified':'pending'}">${esc(qualificationLabel(s.qualification))}</span></div>
    <p>${esc(s.description)}</p>
    <div class="starter-facts-v087"><span><b>${esc(s.topology_label)}</b><small>拓扑</small></span><span><b>${esc(s.application)}</b><small>推荐应用</small></span><span><b>${(s.guided_inputs||[]).length} 项</b><small>首次输入</small></span><span><b>${(s.standard_analysis_package||[]).length} 项</b><small>标准分析</small></span></div>
    <div class="starter-flow-v087"><span>预制设计</span><i>→</i><span>Rev.1</span><i>→</i><span>设计验证</span><i>→</i><span>结果决策</span></div>
    <div class="actions"><button type="button" data-starter-detail="${esc(s.id)}">查看工程范围</button><button type="button" class="primary" data-starter-use="${esc(s.id)}">使用此预制设计</button></div>
  </article>`;
  function render(){
    const grid=q('#goldenStarterGridV087'),status=q('#goldenStarterStatusV087');if(!grid)return;
    const rows=state.payload?.starters||[];
    grid.innerHTML=rows.map(card).join('')||'<div class="workspace-empty compact"><b>没有可用的工程预制电机</b><span>请检查 design_starters.yaml。</span></div>';
    if(status){status.textContent=`${rows.length} 个预制入口`;status.className='status-chip ready'}
    bind();
  }
  function bind(){
    qa('[data-starter-use]').forEach(b=>{if(b.dataset.bound)return;b.dataset.bound='1';b.addEventListener('click',()=>openCreate(b.dataset.starterUse))});
    qa('[data-starter-detail]').forEach(b=>{if(b.dataset.bound)return;b.dataset.bound='1';b.addEventListener('click',()=>openDetail(b.dataset.starterDetail))});
  }
  function inputRow(spec){const current=spec.default_value??'';const range=(spec.recommended_min!=null&&spec.recommended_max!=null)?`建议 ${spec.recommended_min}–${spec.recommended_max} ${spec.unit||''}`:'按模板默认值';return `<label class="starter-input-v087"><span>${esc(spec.label)}${spec.required?'<b class="required-mark-v087">必填</b>':''}</span><div class="input-with-unit-v087"><input type="number" data-starter-input="${esc(spec.parameter_id)}" value="${esc(current)}" ${spec.step!=null?`step="${esc(spec.step)}"`:''} ${spec.hard_min!=null?`min="${esc(spec.hard_min)}"`:''} ${spec.hard_max!=null?`max="${esc(spec.hard_max)}"`:''}><em>${esc(spec.unit||'')}</em></div><small>${esc(range)}${spec.description?` · ${esc(spec.description)}`:''}</small></label>`}
  function openCreate(id){
    const starter=(state.payload?.starters||[]).find(x=>x.id===id);if(!starter)return;
    const host=q('#goldenStarterCreateV087');if(!host)return;
    const pid=projectId();state.selected=starter;host.classList.remove('hidden');
    host.innerHTML=`<div class="section-head"><div><span class="eyebrow">${esc(starter.short_label)} · GUIDED CREATE</span><h2>创建 ${esc(starter.label)}</h2><p>首次只确认设计名称和少量关键参数；未填写项继续使用受控模板默认值。</p></div><button type="button" data-starter-close>关闭</button></div>
      ${pid?'':`<div class="issue WARNING"><b>尚未进入项目</b><p>请先进入项目，再创建预制电机设计。</p><button type="button" data-go-projects-v087>进入项目管理</button></div>`}
      <div class="golden-starter-form-grid-v087"><label class="starter-name-v087"><span>设计名称</span><input id="goldenStarterNameV087" maxlength="120" value="${esc(starter.default_name||starter.label)}"></label>${(starter.guided_inputs||[]).map(inputRow).join('')}</div>
      <div class="starter-package-v087"><div><span>创建后标准验证</span><b>${(starter.standard_analysis_steps||[]).map(x=>esc(x.short_label||x.label)).join(' · ')}</b></div><div><span>推荐优化变量</span><b>${(starter.optimization_parameter_specs||[]).map(x=>esc(x.label||x.parameter_id)).join(' · ')}</b></div></div>
      <div class="callout info"><b>参数映射</b><br>${starter.mapping_readiness?.guided_registry_complete?'Guided 参数已进入 Motor-CAD 2026R1 版本化映射。':'存在尚未进入版本化映射的 Guided 参数。'}${Object.keys(starter.mapping_readiness?.deferred_parameters||{}).length?' 部分未完成 Native 语义确认的参数已从 Guided/自动优化中暂缓开放。':''}</div>
      <div class="callout info"><b>资格边界</b><br>${esc(starter.qualification?.message||'')}</div>
      <div class="actions"><button type="button" data-starter-close>取消</button><button id="goldenStarterConfirmV087" type="button" class="primary" ${pid?'':'disabled'}>创建预制设计 + Rev.1</button></div><div id="goldenStarterCreateStatusV087" class="hint"></div>`;
    qa('[data-starter-close]',host).forEach(b=>b.addEventListener('click',()=>host.classList.add('hidden')));
    q('[data-go-projects-v087]',host)?.addEventListener('click',()=>window.showTab?.('projects'));
    q('#goldenStarterConfirmV087',host)?.addEventListener('click',()=>createStarter(starter));
    host.scrollIntoView?.({behavior:'smooth',block:'nearest'});
  }
  function openDetail(id){
    const s=(state.payload?.starters||[]).find(x=>x.id===id);if(!s)return;const host=q('#goldenStarterCreateV087');if(!host)return;host.classList.remove('hidden');
    host.innerHTML=`<div class="section-head"><div><span class="eyebrow">ENGINEERING SCOPE</span><h2>${esc(s.label)}</h2><p>${esc(s.topology_label)} · ${esc(s.application)}</p></div><button type="button" data-starter-close>关闭</button></div><div class="starter-detail-grid-v087"><div><span>设计参数组</span><b>${(s.design_groups||[]).map(esc).join(' / ')}</b></div><div><span>标准分析包</span><b>${(s.standard_analysis_steps||[]).map(x=>esc(x.short_label||x.label)).join(' / ')}</b></div><div><span>结果 Scorecard</span><b>${(s.scorecard_metrics||[]).map(x=>esc(x.label||x.metric_id)).join(' / ')}</b></div><div><span>优化变量</span><b>${(s.optimization_parameter_specs||[]).map(x=>esc(x.label||x.parameter_id)).join(' / ')}</b></div></div>${Object.keys(s.mapping_readiness?.deferred_parameters||{}).length?`<div class="callout info"><b>暂缓开放参数</b><br>${Object.entries(s.mapping_readiness.deferred_parameters).map(([id,row])=>`${esc(id)}：${esc(row.reason||row.status)}`).join('<br>')}</div>`:''}<div class="callout warning"><b>当前资格状态</b><br>${esc(qualificationLabel(s.qualification))}。Studio 不会把“模板存在”误标记为 Windows Motor-CAD 生产验证通过。</div><div class="actions"><button class="primary" type="button" data-starter-use="${esc(s.id)}">使用此预制设计</button></div>`;
    qa('[data-starter-close]',host).forEach(b=>b.addEventListener('click',()=>host.classList.add('hidden')));bind();
  }
  async function createStarter(starter){
    const pid=projectId();if(!pid)return window.toast?.('请先进入项目','WARNING');
    const btn=q('#goldenStarterConfirmV087'),status=q('#goldenStarterCreateStatusV087');if(btn)btn.disabled=true;if(status)status.textContent='正在创建受控 Rev.1…';
    const inputs={};qa('[data-starter-input]').forEach(el=>{if(el.value!=='')inputs[el.dataset.starterInput]=Number(el.value)});
    const name=q('#goldenStarterNameV087')?.value?.trim()||starter.default_name||starter.label;
    try{
      const result=await apiCall(`/api/projects/${encodeURIComponent(pid)}/design-starters/${encodeURIComponent(starter.id)}`,{method:'POST',body:JSON.stringify({name,inputs})});
      if(status)status.textContent='创建完成，正在进入电机设计工作台。';window.toast?.(`已创建 ${name} · Rev.1`,'SUCCESS',6000);
      q('#goldenStarterCreateV087')?.classList.add('hidden');
      if(window.changeActiveProject)await window.changeActiveProject(pid);
      const sid=result.id;if(window.MCSRouter?.navigate)await window.MCSRouter.navigate(`/app/projects/${encodeURIComponent(pid)}/designs/${encodeURIComponent(sid)}`);else window.showTab?.('workspace');
    }catch(e){if(status)status.textContent=`创建失败：${e.message||e}`;window.toast?.(e.message||String(e),'ERROR',8000);if(btn)btn.disabled=false}
  }
  async function load(){if(state.loading)return;state.loading=true;try{state.payload=await apiCall('/api/design-starters');render()}catch(e){const status=q('#goldenStarterStatusV087');if(status){status.textContent='读取失败';status.className='status-chip error'}const grid=q('#goldenStarterGridV087');if(grid)grid.innerHTML=`<div class="issue ERROR">${esc(e.message||e)}</div>`}finally{state.loading=false}}
  document.addEventListener('DOMContentLoaded',load,{once:true});window.addEventListener('mcs:engineering-context-changed',()=>bind());
  window.MCSDesignStarters={load,openCreate,state};
})();
