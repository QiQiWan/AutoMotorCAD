/* MotorCAD Studio V0.91.8 — engineer workflow, result navigation and diagnostics repair. */
(() => {
  const q=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const safe=v=>typeof window.esc==='function'?window.esc(v):String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stageLabels={
    STARTING_SOLVER:'启动 Motor-CAD',LOAD_TEMPLATE:'加载模型基线',APPLY_EMAG_PARAMETERS:'写入电磁参数',APPLY_THERM_PARAMETERS:'写入热参数',MATERIALS:'应用材料',MODEL_VALIDATION:'几何与绕组检查',MECHANICAL_PREPARING:'准备机械模型',LAB_PREPARING:'准备性能图模型',EMAG_SOLVING:'电磁有限元求解',EMAG_ADVANCED_SOLVING:'高级电磁求解',EMAG_RESUMED:'恢复电磁有限元求解',THERMAL_SOLVING:'稳态热求解',THERMAL_TRANSIENT_SOLVING:'瞬态热求解',COUPLED_SOLVING:'电磁—热耦合',MECHANICAL_SOLVING:'机械有限元求解',LAB_BUILDING:'构建性能图模型',LAB_SOLVING:'性能图计算',WEIGHT_SOLVING:'质量计算',EXPORTING_FEA:'导出有限元场',FEA_EXPORT_ATTEMPT:'尝试导出有限元场',FEA_RAW_WRITTEN:'有限元场文件已生成',NORMALIZING_FEA:'整理空间场数据',FEA_NORMALIZED:'空间场可视化就绪',FEA_EXPORT_WARNING:'有限元场导出告警',FEA_NORMALIZATION_WARNING:'空间场解析告警',NATIVE_FEA_FRAME_AVAILABLE:'有限元画面已生成',NATIVE_SCREEN_CAPTURE_WARNING:'有限元画面抓取告警',EMAG_EXTRACTING:'提取电磁结果',THERMAL_EXTRACTING:'提取热结果',COUPLED_EXTRACTING:'提取耦合结果',MECHANICAL_EXTRACTING:'提取机械结果',LAB_EXTRACTING:'提取性能图结果',VALIDATING_RESULTS:'结果验证',QUALITY_CHECK:'质量检查',ARCHIVING:'归档结果',CHECKPOINT:'保存检查点'
  };
  const humanStage=value=>stageLabels[String(value||'')]||String(value||'等待').replaceAll('_',' ');
  const labelKey=key=>{
    const maps={shaft_speed_rpm:'转速',peak_current_a:'峰值电流',rms_current_a:'RMS 电流',dc_bus_voltage_v:'直流母线电压',phase_advance_deg:'相位超前角',ambient_temperature_c:'环境温度',radiation_temperature_c:'辐射环境温度',initial_temperature_c:'初始温度',coolant_inlet_temperature_c:'冷却介质入口温度',coolant_flow_rate_lpm:'冷却介质流量',external_air_speed_mps:'外部风速',altitude_m:'海拔',cooling_type:'冷却方式'};
    return maps[key]||state.registry?.parameters?.[key]?.label||String(key).replaceAll('_',' ');
  };
  const unitKey=key=>state.registry?.parameters?.[key]?.unit||({shaft_speed_rpm:'rpm',peak_current_a:'A',rms_current_a:'A',dc_bus_voltage_v:'V',phase_advance_deg:'°elec',ambient_temperature_c:'°C',radiation_temperature_c:'°C',initial_temperature_c:'°C',coolant_inlet_temperature_c:'°C',coolant_flow_rate_lpm:'L/min',external_air_speed_mps:'m/s',altitude_m:'m'})[key]||'';
  const outputLabel=key=>state.viewer?.output_schema?.[key]?.label||state.registry?.outputs?.[key]?.label||String(key||'').replaceAll('_',' ');
  const statusLabel=value=>({SUCCEEDED:'求解完成',FAILED:'求解失败',RUNNING:'求解中',QUEUED:'等待求解',CANCELLED:'已取消',VALID:'结果可用',WARNING:'结果有提示',INVALID:'结果不可用',UNVERIFIED:'待结果验证'})[String(value||'')]||String(value||'状态未知').replaceAll('_',' ');
  function humanIssue(value){const text=String(value||'');const known={'Motor-CAD native FEA export did not produce a readable file':'有限元场导出没有生成可读取的文件','native FEA data not normalized':'有限元场数据尚未转换为可视格式','no replayable FEA frames':'没有可回放的有限元场帧'};return known[text]||text.replace(/native FEA/gi,'有限元场').replace(/torque_speed_envelope/g,'转矩—转速包络')}

  function flatRows(object,prefix=''){
    const rows=[];for(const [key,value] of Object.entries(object||{})){
      if(['native_screen_capture','native_fea','native_fea_export','native_fea_policy','fingerprint'].includes(key))continue;
      const path=prefix?`${prefix} · ${labelKey(key)}`:labelKey(key);
      if(value&&typeof value==='object'&&!Array.isArray(value)){rows.push(...flatRows(value,path));continue}
      rows.push([path,Array.isArray(value)?`${value.length} 项`:value,unitKey(key)]);
    }return rows;
  }
  function inputSnapshot(viewer){
    const groups=[['设计参数','随 Design Revision 冻结；改变后应保存新设计版本',viewer.inputs?.parameters],['运行工况','只影响本次分析版本和 Case',viewer.inputs?.scenario],['材料与介质','决定电磁、热、质量和机械属性',viewer.inputs?.materials],['求解设置','分析方法、离散精度和耦合方式',viewer.inputs?.solver_settings]];
    return `<section class="engineer-input-snapshot-v057"><div class="result-section-intro-v057"><h3>本次计算实际使用的输入</h3><p>按设计参数、运行工况、材料介质和求解设置分组显示工程含义、数值与单位；内部技术字段保留在任务诊断包。</p></div>${groups.map(([name,meaning,data])=>{const rows=flatRows(data);return`<article><header><b>${safe(name)}</b><span>${safe(meaning)}</span></header><div>${rows.map(([label,value,unit])=>`<dl><dt>${safe(label)}</dt><dd>${value===null||value===undefined||value===''?'—':safe(value)} <small>${safe(unit)}</small></dd></dl>`).join('')||'<p>本次计算没有显式覆盖，沿用模型基线。</p>'}</div></article>`}).join('')}</section>`;
  }
  function resultIssues(viewer){
    const contract=viewer?.result_contract||{},extract=contract.extraction||{},fea=contract.fea||{};
    return [...(extract.missing_required||[]).map(id=>`缺少必需结果：${outputLabel(id)}`),...(extract.invalid_required||[]).map(id=>`数值未通过：${outputLabel(id)}`),...(fea.issues||[]).map(item=>`有限元场：${humanIssue(item)}`),...(contract.integrity_issues||[]).map(humanIssue)].filter(Boolean);
  }
  function resultDecision(){
    const viewer=state.viewer,quality=viewer?.case?.quality_status,execution=viewer?.case?.execution_status,ok=['VALID','WARNING'].includes(quality),issues=resultIssues(viewer),taskId=viewer?.case?.task_id;
    return `<section class="result-decision-v057 ${ok?'ok':'blocked'}"><div><span>${safe(statusLabel(execution))}</span><h3>${ok?'结果验证通过，可开始工程分析':'求解已结束，结果验证未通过'}</h3><p>${ok?'下方只启用当前计算记录真正拥有的数据模块。':safe(issues[0]||'当前结果不适合作为工程结论，请先处理缺失结果或有限元场。')}</p></div><div class="actions">${!ok?'<button type="button" data-result-action-v057="analysis">返回分析设置</button>':''}${taskId?`<a href="/api/logs/export.zip?task_id=${encodeURIComponent(taskId)}&minutes=1440&current_session=true">下载任务诊断包</a>`:''}</div>${issues.length?`<details><summary>查看 ${issues.length} 个阻断原因</summary><ul>${issues.map(x=>`<li>${safe(x)}</li>`).join('')}</ul></details>`:''}</section>`;
  }
  function scrubUnqualifiedValues(root){
    if(state.viewer?.case?.quality_status!=='INVALID')return;
    qa('.viewer-kpi',root).forEach(card=>{const value=q('b',card);if(value)value.innerHTML='— <small>结果验证未通过</small>';card.classList.add('untrusted-v057')});
  }
  function nativeScreen(){
    const image=(state.viewer?.artifacts||[]).find(item=>/native_screens[\\/].*\.(png|jpg|jpeg|bmp)$/i.test(item.path||'')||/fea_results\.(png|jpg|jpeg|bmp)$/i.test(item.name||''));
    if(!image)return'';
    return `<figure class="native-screen-result-v057"><figcaption><b>Motor-CAD 原生有限元画面</b><span>来自本次 Case 的可视化抓取，可与结构化空间场切换查看。</span></figcaption><img src="/api/artifacts/${encodeURIComponent(image.id)}" alt="Motor-CAD 原生有限元结果画面"></figure>`;
  }
  function decorateResult(key){
    const canvas=q('#viewerCanvas'),header=q('#viewerCaseHeader');if(!canvas||!state.viewer)return;
    q('.result-decision-v057',header)?.remove();header.insertAdjacentHTML('beforeend',resultDecision());
    qa('[data-result-action-v057="analysis"]',header).forEach(button=>button.addEventListener('click',()=>showTab('analysisConfig')));
    const artifacts=q('[data-viewer-module="artifacts"]');if(artifacts)artifacts.remove();
    qa('.viewer-module:disabled').forEach(button=>{button.title='当前 Case 没有该模块所需的已提取数据';const small=q('small',button);if(small&&!small.textContent.includes('当前 Case'))small.textContent+=' · 当前 Case 无可用数据'});
    if(key==='inputs')canvas.innerHTML=inputSnapshot(state.viewer);
    if(key==='fea')canvas.insertAdjacentHTML('afterbegin',nativeScreen());
    scrubUnqualifiedValues(canvas);
    if(state.viewer?.case?.quality_status==='INVALID'){
      const summary=q('#engineeringResultSummaryV030 .result-key-metrics-v030');
      if(summary)summary.innerHTML='<div class="untrusted-result-v057"><b>关键指标已隐藏</b><span>结果验证未通过；零值和缺失值均不作为电机性能显示。</span></div>';
    }
  }
  function installResultGuide(){const toolbar=q('.viewer-case-toolbar');if(!toolbar||q('.result-guide-v057',toolbar))return;toolbar.insertAdjacentHTML('afterbegin','<section class="result-guide-v057"><div><h3>查看计算结果</h3><p>选择计算记录后，系统自动打开第一个 Case；左侧只保留当前 Case 有数据的模块。</p></div><ol><li>选择计算记录</li><li>确认 Case 状态</li><li>先看结果验证</li><li>再看曲线或有限元场</li></ol></section>')}

  const previousViewer=window.renderViewerModule;
  if(typeof previousViewer==='function')window.renderViewerModule=function(key){const result=previousViewer.apply(this,arguments);decorateResult(key);return result};
  const previousOpen=window.openCaseViewer;
  if(typeof previousOpen==='function')window.openCaseViewer=async function(){const result=await previousOpen.apply(this,arguments);if(result)decorateResult('overview');return result};
  // V0.58: the base loader owns the single auto-open decision.  Keeping the
  // policy in one place prevents duplicate viewer requests on deep links.

  const previousMonitor=window.renderMonitorSnapshot;
  if(typeof previousMonitor==='function')window.renderMonitorSnapshot=function(snapshot){const result=previousMonitor.apply(this,arguments),stage=q('#monitorStageText');if(stage)stage.textContent=humanStage(snapshot?.current_stage);qa('#stagePipeline .stage-node').forEach(node=>{node.removeAttribute('title');const label=q('b',node);if(label)label.textContent=humanStage(label.textContent)});return result};
  const previousEvents=window.renderLiveEvents;
  if(typeof previousEvents==='function')window.renderLiveEvents=function(){const result=previousEvents.apply(this,arguments);qa('#liveEventConsole .console-row').forEach(row=>{const stage=row.children[2];if(stage)stage.textContent=humanStage(stage.textContent)});renderIOMonitor();return result};
  function renderIOMonitor(){
    const panel=q('#solverIOMonitorV057')||(()=>{const host=q('#stagePipeline')?.closest('.panel');if(!host)return null;const node=document.createElement('section');node.id='solverIOMonitorV057';node.className='solver-io-monitor-v057';host.appendChild(node);return node})();if(!panel)return;
    const all=state.monitorEvents||[],rows=all.filter(ev=>/FEA_|EXTRACT|MATERIAL|MODEL_VALIDATION|ARCHIV|PARAMETER|SOLVING|QUALITY/i.test(`${ev.stage||''} ${ev.event_type||''}`)).slice(-12).reverse(),groups=[['模型输入',['LOAD_TEMPLATE','APPLY_EMAG_PARAMETERS','APPLY_THERM_PARAMETERS','MATERIALS','MODEL_VALIDATION']],['有限元求解',['EMAG_SOLVING','EMAG_ADVANCED_SOLVING','EMAG_RESUMED','MECHANICAL_SOLVING']],['空间场输出',['EXPORTING_FEA','FEA_EXPORT_ATTEMPT','FEA_RAW_WRITTEN','NORMALIZING_FEA','FEA_NORMALIZED']],['结果提取',['EMAG_EXTRACTING','THERMAL_EXTRACTING','COUPLED_EXTRACTING','MECHANICAL_EXTRACTING','LAB_EXTRACTING']],['结果验证',['VALIDATING_RESULTS','QUALITY_CHECK']],['归档',['ARCHIVING','CHECKPOINT']]];
    const groupCards=groups.map(([name,aliases],index)=>{const matches=all.filter(ev=>aliases.includes(String(ev.stage||''))||aliases.includes(String(ev.event_type||''))),last=matches.at(-1),level=String(last?.severity||'').toUpperCase(),cls=level==='ERROR'?'failed':level==='WARNING'?'warn':last?'done':'pending',text=cls==='failed'?'失败':cls==='warn'?'需处理':cls==='done'?'已有记录':'等待';return`<article class="solver-io-phase-v058 ${cls}"><span>${cls==='done'?'✓':cls==='failed'?'!':cls==='warn'?'△':index+1}</span><b>${safe(name)}</b><small>${text}</small></article>`}).join('');
    const diagnosis=state.monitorTask?`<a href="/api/logs/export.zip?task_id=${encodeURIComponent(state.monitorTask)}&minutes=1440&current_session=true">下载本任务诊断包</a>`:'';
    panel.innerHTML=`<header><div><h3>有限元步骤与输入输出监控</h3><small>从模型输入到结果归档逐阶段记录；警告会保留原始错误信息用于定位。</small></div><div><span>${rows.length} 条关键记录</span>${diagnosis}</div></header><div class="solver-io-phases-v058">${groupCards}</div>${rows.length?`<div class="solver-io-rows-v057">${rows.map(ev=>{const level=String(ev.severity||'INFO').toLowerCase(),time=ev.created_at?new Date(ev.created_at).toLocaleTimeString():'';return`<article class="${level==='error'?'error':level==='warning'?'warn':''}"><b>${safe(humanStage(ev.stage||ev.event_type))}</b><span>${safe(humanIssue(ev.message||''))}</span><small>${safe(time)}${ev.case_id?' · 当前工况记录':''}</small></article>`}).join('')}</div>`:'<p>等待计算进入模型检查、有限元求解或结果提取阶段。</p>'}`;
  }
  document.addEventListener('click',event=>{if(event.target.closest('[data-open-advanced-evidence-v057]'))showTab('logs')});
  installResultGuide();document.body.classList.add('solver-evidence-enabled');
  window.MCSSolverEvidence={humanStage,decorateResult,renderIOMonitor};
})();
