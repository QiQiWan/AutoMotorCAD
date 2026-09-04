/* 工程界面只给结论和下一步；原始表仅在诊断包与高级下载中提供。 */
/* V0.64 Design validation / comparison renderer. */
(() => {
  const U=window.MCSDesignRenderUtils;if(!U)throw new Error('MCSDesignRenderUtils must load before validation renderer');
  const {safe,fmt,revisionLabel}=U;

  function nativeOperatorMessage(native){
    if(!native)return'';
    if(native.status==='PASS')return'当前材料、几何与绕组已取得原生 PASS 证据。';
    const typed=(native.native_fault_tree||[])[0];
    if(typed)return`首要故障 ${typed.code||'NATIVE_VALIDATION'}：${typed.message||'原生模型检查未通过'}${typed.repair_hint?` 处理：${typed.repair_hint}`:''}`;
    const root=native.root_cause||(native.checks||[]).find(row=>String(row?.status||'').toUpperCase()==='FAIL')||{},details=root.details||{},id=String(root.id||'').toLowerCase();
    if(id==='materials'){
      const component=details.component||'电机部件',material=details.material||'所选材料';
      return`失败阶段：材料绑定。${component} → ${material} 未完成 Motor-CAD 回读。${details.source_kind==='template_mtt'?'模板继承值将沿用原生绑定；请重新运行检查确认。':'请确认材料存在于当前 Motor-CAD 数据库并检查组件别名。'}`;
    }
    if(id==='winding')return`失败阶段：绕组检查。${root.message||native.winding?.message||'请检查槽/相/并联支路、槽满率及线圈连接。'}`;
    if(id==='geometry')return`失败阶段：几何检查。${root.message||native.geometry?.message||'请按 Motor-CAD 返回原因定位几何尺寸或相交部位。'}`;
    if(id==='parameter_roundtrip')return`失败阶段：参数回读。${root.message||'请恢复失败参数并核对 Motor-CAD 2026R1 参数映射。'}`;
    return root.message||native.geometry?.message||native.winding?.message||'请在问题中心查看首个失败阶段与 Motor-CAD 原始返回。';
  }

  function draftValidationView(data){
    const check=data.draft_validation||{},precheck=check.precheckCurrent?check.precheck:null,native=check.nativeCurrent?check.nativeCheck:null;
    const blocks=(precheck?.issues||[]).filter(issue=>issue.severity==='BLOCKING'),warns=(precheck?.issues||[]).filter(issue=>issue.severity!=='BLOCKING');
    const studioTone=check.precheckBusy?'running':!precheck?'pending':blocks.length?'blocked':warns.length?'warning':'pass';
    const studioLabel=check.precheckBusy?'检查中':!precheck?'待验证':blocks.length?`${blocks.length} 项阻断`:warns.length?`${warns.length} 项提示`:'通过';
    const nativeTone=check.nativeBusy?'running':!native?'pending':native.status==='PASS'?'pass':'blocked';
    const nativeLabel=check.nativeBusy?'检查中':!native?'未运行':native.status==='PASS'?'通过':'未通过';
    const issueRows=(precheck?.issues||[]).map((issue,index)=>`<button type="button" data-workbench-issue="${index}" class="${issue.severity==='BLOCKING'?'blocking':'warning'}"><b>${safe(issue.message||issue.code)}</b><small>${safe((issue.parameter_ids||[]).join(' / ')||'电机模型')}</small></button>`).join('');
    const qualified=Boolean(precheck&&!blocks.length&&native?.status==='PASS'&&check.nativeCurrent);
    const dirty=Number(data.dirty_count||0);
    const qualificationLabel=qualified?'设计资格已通过':native?.status==='PASS'?'设计参数已变化，需要刷新资格':'设计资格尚未完成';
    return`<div class="draft-validation-view-v065 design-qualification-v0919"><div class="visual-heading-v031"><div><span class="eyebrow">DESIGN QUALIFICATION · 设计资格</span><h3>${safe(qualificationLabel)}</h3><p>这里只判断电机设计本身：几何、绕组、材料以及 Motor-CAD 原生模型可接受性。分析工况与求解器在下一阶段单独检查。</p></div><span class="status ${qualified?'VALID':studioTone==='blocked'||nativeTone==='blocked'?'INVALID':'WARNING'}">${qualified?'READY':safe(nativeLabel==='通过'?studioLabel:nativeLabel)}</span></div>
      <div class="qualification-scope-v0919"><span><b>设计资格</b> 与 Design Revision / 草稿指纹绑定</span><i></i><span><b>计算就绪</b> 在分析配置中复用设计资格，仅补查工况、求解器、输出合同与运行环境</span></div>
      <div class="validation-pipeline-v065"><article class="${studioTone}"><span>1</span><div><b>Studio 结构一致性</b><small>几何包含关系、槽极/相/支路约束、参数一致性</small></div><strong>${safe(studioLabel)}</strong></article><i></i><article class="${nativeTone}"><span>2</span><div><b>Motor-CAD 模型可接受性</b><small>真实模型加载、材料绑定、几何与绕组原生检查</small></div><strong>${safe(nativeLabel)}</strong></article></div>
      <div class="validation-action-grid-v065"><button type="button" data-workbench-run-studio-check-v065 ${check.precheckBusy?'disabled':''}><b>${precheck?'重新检查结构一致性':'检查结构一致性'}</b><span>本地快速检查，不启动 Motor-CAD</span></button><button type="button" class="primary" data-workbench-run-native-check-v065 ${!precheck||blocks.length||check.nativeBusy?'disabled':''}><b>${check.nativeBusy?'Motor-CAD 检查中…':'检查 Motor-CAD 模型可接受性'}</b><span>${blocks.length?'先修复 Studio 阻断项':'生成与当前草稿绑定的原生资格证据'}</span></button></div>
      ${issueRows?`<div class="workbench-issue-list-v024 validation-issues-v065">${issueRows}</div>`:'<div class="validation-empty-v065"><b>当前没有 Studio 结构阻断项。</b><span>原生检查完成后即可形成当前设计的资格结论。</span></div>'}
      ${native?`<div class="native-validation-result-v065 ${native.status==='PASS'?'pass':'fail'}"><b>${native.status==='PASS'?'✓ Motor-CAD 模型可接受性通过':'Motor-CAD 模型可接受性未通过'}</b><span>${safe(nativeOperatorMessage(native))}</span>${native.status!=='PASS'&&(native.native_repair_plan?.auto_safe_action_ids||[]).length?`<button type="button" class="primary" data-workbench-native-safe-repair-v088c>安全修复并重新检查</button>`:''}</div>`:''}
      <div class="qualification-outcome-v0919 ${qualified?'ready':'pending'}"><div><span>资格结论</span><b>${safe(qualificationLabel)}</b><small>${qualified?(dirty?`当前有 ${dirty} 项草稿修改；进入分析前先冻结为新设计版本。`:'当前 Revision 无待保存修改，可直接进入分析配置。'):'完成两项设计资格检查后，系统会明确给出进入分析配置的下一步。'}</small></div><button type="button" class="primary" data-workbench-continue-analysis-v0919 ${qualified?'':'disabled'}>${qualified?(dirty?'保存新设计版本并进入分析配置':'进入分析配置'):'待设计资格通过'}</button></div></div>`;
  }

  function nativeEvidenceView(data){
    const evidence=data.native_evidence,execution=evidence?.execution_status||evidence?.task_status,quality=evidence?.quality_status;
    const usable=execution==='SUCCEEDED'&&['VALID','WARNING'].includes(quality),caseId=evidence?.case_id;
    const precheck=data.precheck||{},issues=precheck.issues||[],blocks=issues.filter(issue=>issue.severity==='BLOCKING'),warns=issues.filter(issue=>issue.severity!=='BLOCKING');
    const materialComponents=data.materials?.component_materials||{},materialCount=Object.values(materialComponents).filter(value=>value!==null&&value!==undefined&&value!=='').length;
    const winding=data.winding_design||{},windingReady=Boolean(winding.phase_count&&winding.turns_per_coil&&winding.parallel_paths);
    const geometryCount=(data.parameters||[]).filter(row=>['topology','geometry','stator','rotor','magnet','airgap'].includes(row.category)).length;
    const studioPass=precheck.valid!==false&&!blocks.length,studioTone=blocks.length?'blocked':warns.length?'warning':'pass';
    const issueRows=issues.slice(0,10).map(issue=>`<li class="${issue.severity==='BLOCKING'?'blocking':'warning'}"><b>${safe(issue.message||issue.code||'设计检查问题')}</b><span>${safe((issue.parameter_ids||[]).join(' / ')||'模型关系')}</span></li>`).join('');
    return`<div class="native-evidence-view-v031 engineer-evidence-v057 design-readiness-v066"><div class="visual-heading-v031"><div><span class="eyebrow">DESIGN · VALIDATION</span><h3>${studioPass?'当前设计已通过 Studio 静态检查':'当前设计存在待处理的设计约束'}</h3><p>先确认几何、绕组和材料完整性，形成当前电机版本的设计资格。分析配置阶段会复用该证据，并单独完成计算就绪检查。真实求解证据会在完成分析计算后追加到同一证据链。</p></div><span class="status ${studioTone==='pass'?'VALID':studioTone==='blocked'?'INVALID':'WARNING'}">${safe(blocks.length?`${blocks.length} 项阻断`:warns.length?`${warns.length} 项提示`:'Studio 检查通过')}</span></div>
      <div class="design-readiness-grid-v066">
        <article class="${geometryCount?'pass':'warning'}"><span>01</span><div><b>几何参数</b><small>${geometryCount} 项结构化核心参数已载入</small></div><strong>${geometryCount?'已就绪':'待完善'}</strong></article>
        <article class="${windingReady?'pass':'warning'}"><span>02</span><div><b>绕组定义</b><small>${safe(winding.phase_count||'—')} 相 · ${safe(winding.turns_per_coil||'—')} 匝/线圈 · ${safe(winding.parallel_paths||'—')} 支路</small></div><strong>${windingReady?'已就绪':'待完善'}</strong></article>
        <article class="${materialCount?'pass':'warning'}"><span>03</span><div><b>部件材料</b><small>${materialCount} 个部件已有模板或 Revision 材料</small></div><strong>${materialCount?'已配置':'待配置'}</strong></article>
        <article class="${evidence?'pass':'pending'}"><span>04</span><div><b>Motor-CAD 原生证据</b><small>${evidence?'已存在最近一次原生检查 / 求解记录':'当前 Revision 尚未生成原生证据'}</small></div><strong>${evidence?'已有证据':'待运行'}</strong></article>
      </div>
      ${issueRows?`<section class="validation-static-issues-v066"><header><div><b>Studio 检查问题</b><small>保存新 Revision 前可继续编辑；进入分析计算前必须清除阻断项。</small></div></header><ul>${issueRows}</ul></section>`:`<div class="validation-empty-v065 validation-pass-v066"><b>✓ 当前几何与绕组静态关系没有阻断项</b><span>建议进入编辑模式运行一次 Motor-CAD 原生模型检查，确认目标版本能够接受当前几何、绕组和材料定义。</span></div>`}
      <div class="validation-action-grid-v065 validation-action-grid-v066"><button type="button" class="primary" data-edit-view-v031="native"><b>${evidence?'重新进入设计验证':'进入设计验证'}</b><span>打开 Draft 后完成 Studio 结构一致性 + Motor-CAD 模型可接受性</span></button>${caseId?`<button type="button" data-open-evidence-case-v057="${safe(caseId)}"><b>查看最近工程结果</b><span>打开与当前 Revision 关联的最近计算案例</span></button>`:'<button type="button" data-design-next-v061="input_data"><b>配置分析工况</b><span>建立分析案例后执行真实计算</span></button>'}</div>
      <div class="authority-ladder-v031"><div class="done"><span>L0</span><b>参数预览</b><small>Studio</small></div><i></i><div class="done"><span>L1</span><b>静态约束</b><small>Studio</small></div><i></i><div class="${evidence?'done':'pending'}"><span>L2</span><b>原生模型</b><small>Motor-CAD</small></div><i></i><div class="${evidence?.execution_status==='SUCCEEDED'?'done':'pending'}"><span>L3</span><b>真实求解</b><small>Motor-CAD</small></div><i></i><div class="${evidence?.native_fea_artifact?'done':'pending'}"><span>L4</span><b>FEA / 质量</b><small>原生数据</small></div></div>
      ${evidence?`<div class="native-evidence-summary-v031"><div><span>计算任务</span><b>${safe(caseId||'—')}</b></div><div><span>分析类型</span><b>${safe(evidence.analysis||'—')}</b></div><div><span>结果验证</span><b>${safe(quality==='VALID'?'通过':quality==='WARNING'?'有告警':quality==='INVALID'?'未通过':quality||'待检查')}</b></div><div><span>完成时间</span><b>${safe(evidence.finished_at||'—')}</b></div></div><div class="evidence-actions-v057">${caseId?`<button type="button" data-open-evidence-case-v057="${safe(caseId)}">查看工程结果</button><a href="/api/logs/export.zip?task_id=${safe(String(caseId).split('-C')[0])}&minutes=1440&current_session=true">下载任务诊断包</a>`:''}<small>原生 MOT、日志、清单和 FEA 数据保留在诊断与结果资产中。</small></div>`:''}
    </div>`;
  }

  function compareView(data){
    const previous=data.previous_feasible,values=data.effective_parameters||{};
    if(!previous)return'<div class="native-empty-v031"><b>没有可用比较基线</b><p>创建第二个可行设计版本后即可查看参数差异。</p></div>';
    const rows=(data.parameters||[]).map(row=>({row,base:previous.parameters?.[row.id],current:values[row.id]})).filter(x=>x.base!==undefined&&String(x.base)!==String(x.current));
    const label=previous.source==='revision'?revisionLabel(previous.revision):'模板基线';
    return`<div class="design-compare-view-v031"><div class="visual-heading-v031"><div><span class="eyebrow">DESIGN · COMPARE</span><h3>${safe(label)} → 当前设计版本</h3></div><div class="visual-facts-v031"><span>${rows.length} 项差异</span></div></div><table><thead><tr><th>参数</th><th>${safe(label)}</th><th>当前</th><th>变化</th></tr></thead><tbody>${rows.length?rows.map(({row,base,current})=>{const delta=Number.isFinite(Number(base))&&Number.isFinite(Number(current))?Number(current)-Number(base):null;return`<tr><td><b>${safe(row.label)}</b><small>${safe(row.category_label||'设计参数')}</small></td><td>${fmt(base)} ${safe(row.unit||'')}</td><td>${fmt(current)} ${safe(row.unit||'')}</td><td class="${delta>0?'up':delta<0?'down':''}">${delta===null?'—':`${delta>0?'+':''}${fmt(delta)}`}</td></tr>`}).join(''):'<tr><td colspan="4">当前值与比较基线相同。</td></tr>'}</tbody></table></div>`;
  }

  function render(view,data){
    if((view==='evidence'||view==='native')&&data?.editable)return draftValidationView(data);
    if(view==='evidence'||view==='native')return nativeEvidenceView(data);
    if(view==='compare')return compareView(data);
    return null;
  }
  window.MCSDesignValidation={render,nativeEvidenceView,draftValidationView,compareView};
})();
