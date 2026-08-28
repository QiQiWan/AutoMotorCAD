/* V0.19 operator-first information architecture and task flow */
(() => {
  const PROJECT_STAGE = {
    dashboard: 'project',
    solutions: 'solution',
    templates: 'solution',
    workspace: 'motor',
    analysisConfig: 'analysis',
    tasks: 'analysis',
    monitor: 'analysis',
    resultViewer: 'results',
    dataFactory: 'results',
  };
  const PROJECT_TABS = new Set(Object.keys(PROJECT_STAGE));
  function secondaryRowsV022() { return []; }

  function activeTabV019() {
    return document.querySelector('.tab.active')?.id || 'projects';
  }
  function projectRecordV019() {
    if (typeof activeProjectRecord === 'function') return activeProjectRecord();
    return (state.workspaceProjects || []).find(p => p.id === state.activeProjectId) || state.workspaceProject || null;
  }

  function syncProjectManagerRuntimeV019() {
    const el = $('#projectManagerRuntimeBadge');
    if (!el) return;
    const selected = state.startupInstallation?.selected || state.startupInstallation?.manual_path || null;
    const available = Boolean(state.health?.solvers?.motorcad?.available);
    const deepOk = Boolean(state.runtimePreflight?.motorcad?.ok || state.runtimePreflight?.ok);
    el.classList.remove('ready', 'warning');
    if (!selected) {
      el.textContent = 'Motor-CAD 未绑定';
      el.classList.add('warning');
      el.title = '先进入“运行环境”绑定 Motor-CAD.exe。';
    } else if (!available) {
      el.textContent = 'Motor-CAD 接口不可用';
      el.classList.add('warning');
      el.title = '已配置路径，但 PyMotorCAD / Solver 运行能力尚未就绪。';
    } else if (deepOk) {
      el.textContent = 'Motor-CAD 已深度检查';
      el.classList.add('ready');
      el.title = '可执行文件、PyMotorCAD 与 RPC 深度检查已通过。';
    } else {
      el.textContent = 'Motor-CAD 已绑定';
      el.classList.add('ready');
      el.title = '路径和接口已识别；首次正式提交前建议完成深度检查。';
    }
  }

  function syncProjectStageStateV019() {
    const canonical=window.MCSEngineeringWorkflow?.state;if(canonical?.payload&&canonical.projectId===state.activeProjectId){window.MCSEngineeringWorkflow.render(canonical.payload);return}
    const p = projectRecordV019();
    const flow = state.projectFlowStateV019 || {};
    const designCount = Number(flow.designs ?? p?.designs?.length ?? 0);
    const completed = Number(flow.completed ?? 0);
    const running = Number(flow.running ?? 0);
    const stageState = {
      project: {status:'ready', title:'当前项目目标、对象范围和下一步'},
      solution: designCount > 0 ? {status:'ready', title:`已有 ${designCount} 个方案`} : {status:'attention', title:'尚无方案，先创建方案'},
      motor: designCount > 0 ? {status:'ready', title:'配置方案的几何、绕组和材料'} : {status:'pending', title:'需要先创建方案'},
      analysis: running > 0 ? {status:'running', title:`${running} 个计算正在 Motor-CAD 中运行`} : (designCount > 0 ? {status:'ready', title:'配置分析、工况、物理输入、求解与输出'} : {status:'pending', title:'需要先完成方案和电机配置'}),
      results: completed > 0 ? {status:'ready', title:`已有 ${completed} 个完成任务可审查`} : {status:'pending', title:'完成至少一次有效计算后查看结果'},
    };
    $$('#projectShell [data-project-stage]').forEach(btn => {
      const item = stageState[btn.dataset.projectStage] || {status:'pending', title:''};
      btn.dataset.stageStatus = item.status;
      btn.title = item.title;
      btn.classList.toggle('stage-attention', item.status === 'attention');
      btn.classList.toggle('stage-pending', item.status === 'pending');
      btn.classList.toggle('stage-running', item.status === 'running');
    });
  }
  function syncProjectShellV019(tab = activeTabV019()) {
    const shell = $('#projectShell');
    if (!shell) return;
    const p = projectRecordV019();
    const inProject = Boolean(p && PROJECT_TABS.has(tab));
    shell.classList.toggle('hidden', !inProject);
    if ($('#projectShellName')) $('#projectShellName').textContent = p?.name || '未进入项目';
    if ($('#projectShellMeta')) $('#projectShellMeta').textContent = p ? `${p.id} · 项目内不提供跨项目切换` : '请从项目管理进入项目';
    const stage = PROJECT_STAGE[tab];
    $$('#projectShell [data-project-stage]').forEach(b => b.classList.toggle('active', b.dataset.projectStage === stage));
    renderSecondaryNavV019(stage, tab);
    if (p && $('#currentProjectWorkspaceTitle')) $('#currentProjectWorkspaceTitle').textContent = `${p.name} · 电机配置`;
    if (p && $('#currentProjectWorkspaceMeta')) $('#currentProjectWorkspaceMeta').textContent = `${p.id} · 在这里维护当前方案的几何、绕组和材料；工况与求解设置进入“分析配置”。`;
    syncProjectStageStateV019();
    if (tab === 'projects') syncProjectManagerRuntimeV019();
  }
  function renderSecondaryNavV019(){
    $('#projectSecondaryNav')?.remove();
  }


  $('#userMode')?.addEventListener('change', () => queueMicrotask(() => syncProjectShellV019(activeTabV019())));

  const renderLegacyTabV019 = showTab;
  showTab = function(id) {
    renderLegacyTabV019(id);
    const actual = activeTabV019();
    syncProjectShellV019(actual);
  };
  const previousChangeActiveProject = changeActiveProject;
  changeActiveProject = async function(id) {
    await previousChangeActiveProject(id);
    syncProjectShellV019(activeTabV019());
  };

  async function loadProjectOverviewV019(routeCtx=null) {
    if (!state.activeProjectId) return;
    const id = encodeURIComponent(state.activeProjectId);
    try {
      const [d, p, readiness] = await Promise.all([
        api(`/api/dashboard?project_id=${id}`,routeCtx?.signal?{signal:routeCtx.signal}:{}),
        api(`/api/projects/${id}`,routeCtx?.signal?{signal:routeCtx.signal}:{}),
        api(`/api/workflow/readiness?project_id=${id}&analysis=${encodeURIComponent($('#analysis')?.value || 'emag')}`,routeCtx?.signal?{signal:routeCtx.signal}:{}),
      ]);
      if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return;
      state.workspaceProject = p;
      state.workflowReadiness = readiness;
      const completedTasks = Number(d.tasks?.completed || 0);
      const runningTasks = Number(d.tasks?.running || 0);
      const failedTasks = Number(d.tasks?.failed || 0);
      const designs = p.designs || [];
      const scenarios = p.scenarios || [];
      const experiments = p.experiments || [];
      state.projectFlowStateV019 = {designs: designs.length, completed: completedTasks, running: runningTasks, failed: failedTasks};
      $('#overviewProjectName').textContent = p.name || '项目概览';
      $('#overviewProjectMeta').textContent = `${p.id} · ${p.description || '暂无项目说明'}`;
      $('#dashboardMetrics').innerHTML = [
        ['方案', designs.length],
        ['已保存工况', scenarios.length],
        ['计算记录', d.tasks?.total || 0],
        ['可用结果', completedTasks],
      ].map(([k, v]) => `<div class="metric-card"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');

      const action = chooseNextActionV019({dashboard: d, project: p, readiness});
      const actionHtml = `<div class="next-action-card ${esc(action.tone || '')}"><span class="eyebrow">推荐下一步</span><h3>${esc(action.title)}</h3><p>${esc(action.detail)}</p><button type="button" class="primary" data-next-go="${esc(action.tab)}">${esc(action.button)}</button></div>`;
      $('#projectNextActionCard').innerHTML = actionHtml;
      $('#overviewPrimaryAction').innerHTML = `<button type="button" class="primary overview-cta" data-next-go="${esc(action.tab)}">${esc(action.button)}</button><small>${esc(action.short || action.title)}</small>`;
      $$('[data-next-go]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.nextGo)));

      $('#projectObjectSummary').innerHTML = `
        <div class="project-object-summary">
          <div class="summary-block"><span>方案</span><b>${designs.length}</b><small>${designs.length ? designs.slice(0, 3).map(x => esc(x.name)).join(' · ') : '尚未创建方案'}</small></div>
          <div class="summary-block"><span>已保存工况</span><b>${scenarios.length}</b><small>${scenarios.length ? scenarios.slice(0, 3).map(x => esc(x.name)).join(' · ') : '尚未保存工况'}</small></div>
          <div class="summary-block"><span>批量研究</span><b>${experiments.length}</b><small>${experiments.length ? '已保存 DOE / 优化定义' : '完成基准分析后再进行 DOE / 优化'}</small></div>
        </div>
        ${designs.length ? `<div class="overview-design-list">${designs.slice(0, 5).map(dsg => `<button type="button" data-overview-design="${esc(dsg.id)}"><b>${esc(dsg.name)}</b><small>${esc(dsg.template_id || '-')}</small></button>`).join('')}</div>` : ''}`;
      $$('[data-overview-design]').forEach(b => b.addEventListener('click', () => {
        const designId = b.dataset.overviewDesign;
        if(window.MCSRouter?.navigate)MCSRouter.navigate(`/app/projects/${encodeURIComponent(state.activeProjectId)}/designs/${encodeURIComponent(designId)}`);
        else{showTab('workspace');openWorkspaceDesign(designId)}
      }));
      $('#recentTasks').innerHTML = (d.recent_tasks || []).length ? d.recent_tasks.map(renderCompactTask).join('') : '<div class="workspace-empty compact"><b>尚无计算记录</b><span>完成方案和电机配置后，从“分析配置”创建第一条基准分析。</span></div>';
      // V0.88: the legacy refreshWorkflowReadiness helper was removed when the
      // canonical Engineering Workflow cockpit became authoritative. Refresh it
      // through its public controller instead of calling a stale global symbol.
      if (window.MCSEngineeringWorkflow?.refresh) {
        await window.MCSEngineeringWorkflow.refresh(state.activeProjectId, {silent: true});
      }
      syncProjectStageStateV019();
      syncProjectShellV019('dashboard');
    } catch (e) {
      if(window.MCSPageRuntime?.isAbortError?.(e))return;
      toast(`项目概览加载失败：${e.message}`, 'ERROR');
    }
  }
  loadDashboard = loadProjectOverviewV019;
  const operatorFlowController={syncProjectShell:syncProjectShellV019};
  window.MCSOperatorFlow=operatorFlowController;

  function chooseNextActionV019({dashboard, project, readiness}) {
    const designs = project.designs || [];
    const running = Number(dashboard.tasks?.running || 0);
    const completed = Number(dashboard.tasks?.completed || 0);
    const steps = new Map((readiness.steps || []).map(x => [x.id, x]));
    const motor = steps.get('motorcad');
    const qualification = steps.get('qualification');
    const requiredLevel = Number(readiness.required_qualification_level || 0);
    if (!designs.length) return {tab:'solutions', title:'创建第一个方案', detail:'创建方案后即可进入电机配置，维护几何、绕组和材料。', button:'进入方案管理', short:'项目尚无方案'};
    if (running > 0) return {tab:'monitor', title:`有 ${running} 个任务正在运行`, detail:'优先查看当前计算进度、计算进程和 Motor-CAD 异常；运行期间不需要重复提交。', button:'查看实时监控', short:'当前有任务运行', tone:'running'};
    if (!motor?.ready) return {tab:'setup', title:'确认 Motor-CAD 可运行', detail:motor?.detail || '需要完成安装路径绑定和一次 Motor-CAD 深度检查。', button:'检查运行环境', short:'Motor-CAD 尚未就绪', tone:'warning'};
    if (requiredLevel > 0 && !qualification?.ready) return {tab:'system', title:'完成当前模板资格检查', detail:qualification?.detail || '当前模型策略要求模板达到对应运行资格等级。', button:'打开资格检查', short:'模板资格不足', tone:'warning'};
    if (!completed) return {tab:'analysisConfig', title:'创建第一条基准分析', detail:'选择已保存的电机版本，配置工况、分析类型和输出。基准成功后再做扫描、DOE 或优化。', button:'进入分析配置', short:'尚无成功基准任务'};
    return {tab:'resultViewer', title:'审查最新有效结果', detail:`当前项目已有 ${completed} 个完成任务。先确认结果质量和关键性能，再决定是否创建新电机版本或开展 DOE。`, button:'查看结果', short:'已有可审查结果', tone:'success'};
  }

  function enhanceWorkspaceTreeV019() {
    const root = $('#workspaceProjectTree');
    if (!root || !state.workspaceProject) return;
    const p = state.workspaceProject;
    const designs = p.designs || [];
    root.innerHTML = `<div class="tree-project selected"><div class="tree-project-head"><div class="tree-row passive"><span class="tree-icon">▾</span><b>${esc(p.name)}</b><small>${esc(p.id)}</small></div></div><div class="tree-children"><div class="tree-group-label">方案 · ${designs.length}</div>${designs.map(d => `<button type="button" class="tree-row child ${state.workspaceDesign?.id === d.id ? 'selected' : ''}" data-workspace-design="${esc(d.id)}"><span class="tree-icon">◇</span><span>${esc(d.name)}</span><small>${esc(d.template_id || '')}</small></button>`).join('') || '<span class="muted tree-empty">暂无设计</span>'}<button type="button" class="tree-add-design" data-v019-new-design>← 返回方案管理</button></div></div>`;
    $$('[data-workspace-design]').forEach(b => b.addEventListener('click', e => {e.stopPropagation(); window.MCSWorkspaceNavigation?.openDesign?.(b.dataset.workspaceDesign) || openWorkspaceDesign(b.dataset.workspaceDesign);}));
    $('[data-v019-new-design]')?.addEventListener('click', () => showTab('solutions'));
  }
  const previousRenderWorkspaceTree = renderWorkspaceTree;
  renderWorkspaceTree = function() {
    previousRenderWorkspaceTree();
    enhanceWorkspaceTreeV019();
  };
  const previousRenderWorkspaceProjectChildren = renderWorkspaceProjectChildren;
  renderWorkspaceProjectChildren = function(project) {
    previousRenderWorkspaceProjectChildren(project);
    enhanceWorkspaceTreeV019();
  };

  const previousOpenWorkspaceDesign = openWorkspaceDesign;
  openWorkspaceDesign = async function(designId,routeCtx=null) {
    const loaded=await previousOpenWorkspaceDesign(designId,routeCtx);if(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx))return null;
    enhanceWorkspaceTreeV019();
    const actions = $('#workspaceCanvas .workspace-object-header .actions');
    if (!actions || !state.workspaceRevision) return;
    const clone = $('#workspaceCreateRevision');
    if (clone) {
      clone.textContent = '复制为新版本';
      clone.classList.add('engineering-only-action');
    }
    const use = $('#workspaceUseRevision');
    if (use) {
      use.textContent = '用于仿真';
      use.classList.remove('primary');
    }
    if (!$('#workspaceEditRevision')) {
      const edit = document.createElement('button');
      edit.id = 'workspaceEditRevision';
      edit.type = 'button';
      edit.className = 'primary';
      edit.textContent = '修改并保存为新版本';
      edit.addEventListener('click', openRevisionEditorV019);
      actions.prepend(edit);
    }
    return loaded||state.workspaceDesign;
  };

  function openRevisionEditorV019() {
    const design = state.workspaceDesign;
    const rev = state.workspaceRevision;
    if (!design || !rev) return toast('请先选择一个电机版本', 'WARNING');
    const template = state.templates.find(t => t.id === design.template_id);
    const schema = state.registry?.parameters || {};
    const ids = (template?.parameter_ids || Object.keys(rev.parameters || {})).filter(id => schema[id] && rev.parameters?.[id] !== undefined);
    const categoryLabels = {topology:'拓扑', geometry:'主要几何', magnet:'永磁体', winding:'绕组', operating:'运行参数', environment:'环境', cooling:'冷却'};
    const groups = {};
    ids.forEach(id => {(groups[schema[id].category || 'other'] ??= []).push(id);});
    const canvas = $('#workspaceCanvas');
    const inspector = $('#workspaceInspector');
    if (!canvas) return;
    canvas.innerHTML = `<div class="workspace-object-header workspace-create-header"><div><span class="eyebrow">编辑设计 · 创建不可变新版本</span><h2>${esc(design.name)} · 基于 Rev.${esc(rev.revision)}</h2><p>这里修改的是设计定义。保存后生成新的电机版本，历史计算仍保留原版本。</p></div><div class="actions"><button id="cancelRevisionEdit" type="button">取消</button></div></div><div class="design-revision-editor"><div class="revision-editor-toolbar"><div><b>设计参数</b><small id="designRevisionChangeCount">0 项修改</small></div><label>版本说明<input id="designRevisionNotes" placeholder="例如：12槽基线，减小气隙并增加磁体厚度"></label></div>${Object.entries(groups).map(([cat, rows]) => `<section class="design-editor-group"><h3>${esc(categoryLabels[cat] || cat)}</h3><div class="design-editor-grid">${rows.map(id => {const d=schema[id], value=rev.parameters[id]; return `<label class="design-editor-field" data-design-base="${esc(value)}"><span><b>${esc(d.label || id)}</b><small>${esc(id)}</small></span><div><input data-design-revision-param="${esc(id)}" type="number" step="${d.type === 'integer' ? '1' : 'any'}" min="${d.minimum ?? ''}" max="${d.maximum ?? ''}" value="${esc(value)}"><em>${esc(d.unit || '')}</em></div></label>`;}).join('')}</div></section>`).join('')}<div class="revision-editor-footer"><div class="callout info"><b>材料继承</b><br>本次只编辑参数；材料将继承自 Rev.${esc(rev.revision)}。需要调整材料时，请先在材料配置中修改。</div><div class="actions"><button id="saveDesignRevision" class="primary" type="button">保存为新版本</button></div></div></div>`;
    if (inspector) inspector.innerHTML = `<div class="inspector-block"><span class="eyebrow">版本规则</span><h3>设计修改与仿真分离</h3><p>几何、槽极和绕组修改会保存为新的电机版本；分析页选择版本、工况和分析类型。</p><div class="property-grid"><span>基于</span><b>Rev.${esc(rev.revision)}</b><span>参数数</span><b>${Object.keys(rev.parameters || {}).length}</b><span>明确修改</span><b>${(rev.explicit_parameter_ids || []).length}</b></div></div>`;
    const updateChanged = () => {
      let n = 0;
      $$('[data-design-revision-param]').forEach(input => {
        const field = input.closest('[data-design-base]');
        const base = Number(field.dataset.designBase), value = Number(input.value);
        const changed = Number.isFinite(base) && Number.isFinite(value) ? Math.abs(base - value) > Math.max(1e-9, Math.abs(base) * 1e-9) : String(field.dataset.designBase) !== String(input.value);
        field.classList.toggle('changed', changed);
        if (changed) n += 1;
      });
      $('#designRevisionChangeCount').textContent = `${n} 项修改`;
      return n;
    };
    $$('[data-design-revision-param]').forEach(i => i.addEventListener('input', updateChanged));
    $('#cancelRevisionEdit')?.addEventListener('click', () => openWorkspaceDesign(design.id));
    $('#saveDesignRevision')?.addEventListener('click', async () => {
      const changedIds = $$('[data-design-revision-param]').filter(i => i.closest('[data-design-base]')?.classList.contains('changed')).map(i => i.dataset.designRevisionParam);
      if (!changedIds.length) return toast('没有检测到参数修改，无需创建新版本。', 'WARNING');
      const parameters = {...(rev.parameters || {})};
      $$('[data-design-revision-param]').forEach(i => {parameters[i.dataset.designRevisionParam] = Number(i.value);});
      const explicit = [...new Set([...(rev.explicit_parameter_ids || []), ...changedIds])];
      const btn = $('#saveDesignRevision');
      btn.disabled = true; btn.textContent = '正在保存新版本…';
      try {
        const created = await api(`/api/solutions/${encodeURIComponent(design.id)}/revisions`, {method:'POST', body:JSON.stringify({parameters, materials:rev.materials || {}, explicit_parameter_ids:explicit, notes:$('#designRevisionNotes')?.value || `基于 Rev.${rev.revision} 的设计修改`})});
        state.workspaceProject = await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`);
        toast(`已创建 Rev.${created.revision}`, 'SUCCESS', 6000);
        await openWorkspaceDesign(design.id);
        if (created.id) selectWorkspaceRevision(created.id);
      } catch (e) {
        btn.disabled = false; btn.textContent = '保存为新版本';
        toast(e.message, 'ERROR', 8000);
      }
    });
    updateChanged();
  }




  const previousLoadProjectManagerV019 = loadProjectManager;
  loadProjectManager = async function() {
    await previousLoadProjectManagerV019();
    syncProjectManagerRuntimeV019();
  };
  const previousLoadStartupSetupV019 = loadStartupSetup;
  loadStartupSetup = async function(force = false) {
    const result = await previousLoadStartupSetupV019(force);
    syncProjectManagerRuntimeV019();
    return result;
  };

  $('#userMode')?.addEventListener('change', () => {
    queueMicrotask(() => {
      document.body.classList.toggle('operator-flow', document.body.dataset.userMode === 'operator');
    });
  });

  document.addEventListener('click', e => {
    const back = e.target.closest('#workspaceBackProjects');
    if (back) syncProjectShellV019('projects');
  });

  document.body.classList.toggle('operator-flow', document.body.dataset.userMode === 'operator');
  requestAnimationFrame(() => {
    syncProjectShellV019(activeTabV019());
    syncProjectManagerRuntimeV019();
  });
})();
