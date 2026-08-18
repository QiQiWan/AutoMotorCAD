/* V0.19 operator-first information architecture and task flow */
(() => {
  const PROJECT_STAGE = {
    dashboard: 'overview',
    workspace: 'design',
    templates: 'design',
    simulationAssets: 'simulation',
    analysisWorkbench: 'simulation',
    newTask: 'simulation',
    tasks: 'simulation',
    monitor: 'simulation',
    resultViewer: 'results',
    dataFactory: 'data',
  };
  const PROJECT_TABS = new Set(Object.keys(PROJECT_STAGE));
  const SECONDARY = {
    design: [
      ['workspace', '模型参数与版本'],
      ['templates', '模板库'],
    ],
    simulation: [
      ['analysisWorkbench', '分析工作台'],
      ['newTask', '高级任务配置'],
      ['tasks', '计算记录'],
      ['monitor', '实时求解'],
    ],
  };
  function secondaryRowsV022(stage) {
    const rows = [...(SECONDARY[stage] || [])];
    if (stage === 'simulation' && document.body.dataset.userMode !== 'operator') rows.push(['simulationAssets', '高级配置资产']);
    return rows;
  }

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
    const p = projectRecordV019();
    const flow = state.projectFlowStateV019 || {};
    const designCount = Number(flow.designs ?? p?.designs?.length ?? 0);
    const completed = Number(flow.completed ?? 0);
    const running = Number(flow.running ?? 0);
    const stageState = {
      overview: {status:'ready', title:'项目总览与下一步建议'},
      design: designCount > 0 ? {status:'ready', title:`已有 ${designCount} 个 Design`} : {status:'attention', title:'尚无 Design，先从模板创建'},
      simulation: running > 0 ? {status:'running', title:`${running} 个任务正在 Motor-CAD 中求解`} : (designCount > 0 ? {status:'ready', title:'配置工况、计算方式、输出并查看实时求解'} : {status:'pending', title:'需要先创建模型'}),
      results: completed > 0 ? {status:'ready', title:`已有 ${completed} 个完成任务可审查`} : {status:'pending', title:'完成至少一次有效计算后查看结果'},
      data: completed > 0 ? {status:'ready', title:'可从有效结果构建数据集'} : {status:'pending', title:'产生有效结果后再构建数据集'},
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
    if (p && $('#currentProjectWorkspaceTitle')) $('#currentProjectWorkspaceTitle').textContent = `${p.name} · 模型`;
    if (p && $('#currentProjectWorkspaceMeta')) $('#currentProjectWorkspaceMeta').textContent = `${p.id} · 这里维护电机模型与不可变 Revision；工况、计算配置和实时求解统一在“仿真”阶段完成。`;
    syncProjectStageStateV019();
    if (tab === 'projects') syncProjectManagerRuntimeV019();
  }
  function renderSecondaryNavV019(stage, tab) {
    const box = $('#projectSecondaryNav');
    if (!box) return;
    const rows = secondaryRowsV022(stage);
    box.classList.toggle('hidden', rows.length === 0);
    box.innerHTML = rows.map(([target, label]) => `<button type="button" data-v019-go="${esc(target)}" class="${target === tab ? 'active' : ''}">${esc(label)}</button>`).join('');
    $$('[data-v019-go]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.v019Go)));
  }

  $('#userMode')?.addEventListener('change', () => setTimeout(() => syncProjectShellV019(activeTabV019()), 0));

  const renderLegacyTabV019 = showTab;
  showTab = function(id) {
    renderLegacyTabV019(id);
    const actual = activeTabV019();
    syncProjectShellV019(actual);
    if (actual === 'newTask') {
      if (state.routeOwnsLoadV025) {
        refreshOperatorBaselineGateV019();
        setTaskWizardStepV019(state.taskWizardStepV019 || 0, false);
      } else {
        setTimeout(() => {
          refreshOperatorBaselineGateV019();
          setTaskWizardStepV019(state.taskWizardStepV019 || 0, false);
        }, 0);
      }
    }
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
        ['Design', designs.length],
        ['Scenario', scenarios.length],
        ['仿真任务', d.tasks?.total || 0],
        ['已完成', completedTasks],
        ['运行中', runningTasks],
        ['失败/部分完成', failedTasks],
      ].map(([k, v]) => `<div class="metric-card"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');

      const action = chooseNextActionV019({dashboard: d, project: p, readiness});
      const actionHtml = `<div class="next-action-card ${esc(action.tone || '')}"><span class="eyebrow">推荐下一步</span><h3>${esc(action.title)}</h3><p>${esc(action.detail)}</p><button type="button" class="primary" data-next-go="${esc(action.tab)}">${esc(action.button)}</button></div>`;
      $('#projectNextActionCard').innerHTML = actionHtml;
      $('#overviewPrimaryAction').innerHTML = `<button type="button" class="primary overview-cta" data-next-go="${esc(action.tab)}">${esc(action.button)}</button><small>${esc(action.short || action.title)}</small>`;
      $$('[data-next-go]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.nextGo)));

      $('#projectObjectSummary').innerHTML = `
        <div class="project-object-summary">
          <div class="summary-block"><span>设计版本</span><b>${designs.length}</b><small>${designs.length ? designs.slice(0, 3).map(x => esc(x.name)).join(' · ') : '尚未创建设计'}</small></div>
          <div class="summary-block"><span>工况</span><b>${scenarios.length}</b><small>${scenarios.length ? scenarios.slice(0, 3).map(x => esc(x.name)).join(' · ') : '尚未保存工况'}</small></div>
          <div class="summary-block"><span>批量试验</span><b>${experiments.length}</b><small>${experiments.length ? '已保存批量试验定义' : '完成基准计算后再进行 DOE / 优化'}</small></div>
        </div>
        ${designs.length ? `<div class="overview-design-list">${designs.slice(0, 5).map(dsg => `<button type="button" data-overview-design="${esc(dsg.id)}"><b>${esc(dsg.name)}</b><small>${esc(dsg.template_id || '-')}</small></button>`).join('')}</div>` : ''}`;
      $$('[data-overview-design]').forEach(b => b.addEventListener('click', () => {
        const designId = b.dataset.overviewDesign;
        if(window.MCSRouter?.navigate)MCSRouter.navigate(`/app/projects/${encodeURIComponent(state.activeProjectId)}/designs/${encodeURIComponent(designId)}`);
        else{showTab('workspace');openWorkspaceDesign(designId)}
      }));
      $('#recentTasks').innerHTML = (d.recent_tasks || []).length ? d.recent_tasks.map(renderCompactTask).join('') : '<div class="workspace-empty compact"><b>尚无仿真任务</b><span>完成设计后，从“分析与计算”创建案例并运行第一条基准任务。</span></div>';
      await refreshWorkflowReadiness(readiness);
      syncProjectStageStateV019();
      syncProjectShellV019('dashboard');
    } catch (e) {
      if(window.MCSPageRuntime?.isAbortError?.(e))return;
      toast(`项目概览加载失败：${e.message}`, 'ERROR');
    }
  }
  loadDashboard = loadProjectOverviewV019;
  window.MCSOperatorFlowV025={syncProjectShell:syncProjectShellV019,activateTaskStep(step){state.taskWizardStepV019=Number(step)||0;refreshOperatorBaselineGateV019();setTaskWizardStepV019(state.taskWizardStepV019,false)}};

  function chooseNextActionV019({dashboard, project, readiness}) {
    const designs = project.designs || [];
    const running = Number(dashboard.tasks?.running || 0);
    const completed = Number(dashboard.tasks?.completed || 0);
    const steps = new Map((readiness.steps || []).map(x => [x.id, x]));
    const motor = steps.get('motorcad');
    const qualification = steps.get('qualification');
    const requiredLevel = Number(readiness.required_qualification_level || 0);
    if (!designs.length) return {tab:'templates', title:'创建第一个 Design', detail:'先从模板确定电机拓扑，并在当前项目中创建不可变 Rev.1。完成后再配置计算。', button:'从模板创建设计', short:'项目尚无 Design'};
    if (running > 0) return {tab:'monitor', title:`有 ${running} 个任务正在运行`, detail:'优先查看当前计算进度、Worker状态和 Motor-CAD 原生错误；运行期间不需要重新提交。', button:'查看实时监控', short:'当前有任务运行', tone:'running'};
    if (!motor?.ready) return {tab:'setup', title:'确认 Motor-CAD 可运行', detail:motor?.detail || '需要完成安装路径绑定和一次深度启动/RPC检查。', button:'检查运行环境', short:'Motor-CAD 尚未就绪', tone:'warning'};
    if (requiredLevel > 0 && !qualification?.ready) return {tab:'system', title:'完成当前模板资格检查', detail:qualification?.detail || '当前模型策略要求模板达到对应运行资格等级。', button:'打开资格检查', short:'模板资格不足', tone:'warning'};
    if (!completed) return {tab:'analysisWorkbench', title:'先完成一次单次基准计算', detail:'第一条任务建议保持 Design Revision 不变，只设置工况与分析类型。基准成功后再做扫描、DOE 或优化。', button:'配置基准计算', short:'尚无成功基准任务'};
    return {tab:'resultViewer', title:'审查最新有效结果', detail:`当前项目已有 ${completed} 个完成任务。先确认结果质量和关键性能，再决定是否创建新 Revision 或开展 DOE。`, button:'查看结果', short:'已有可审查结果', tone:'success'};
  }

  function enhanceWorkspaceTreeV019() {
    const root = $('#workspaceProjectTree');
    if (!root || !state.workspaceProject) return;
    const p = state.workspaceProject;
    const designs = p.designs || [];
    root.innerHTML = `<div class="tree-project selected"><div class="tree-project-head"><div class="tree-row passive"><span class="tree-icon">▾</span><b>${esc(p.name)}</b><small>${esc(p.id)}</small></div></div><div class="tree-children"><div class="tree-group-label">DESIGN · ${designs.length}</div>${designs.map(d => `<button type="button" class="tree-row child ${state.workspaceDesign?.id === d.id ? 'selected' : ''}" data-workspace-design="${esc(d.id)}"><span class="tree-icon">◇</span><span>${esc(d.name)}</span><small>${esc(d.template_id || '')}</small></button>`).join('') || '<span class="muted tree-empty">暂无设计</span>'}<button type="button" class="tree-add-design" data-v019-new-design>＋ 从模板新建设计</button></div></div>`;
    $$('[data-workspace-design]').forEach(b => b.addEventListener('click', e => {e.stopPropagation(); window.MCSWorkspaceNavigationV065?.openDesign?.(b.dataset.workspaceDesign) || openWorkspaceDesign(b.dataset.workspaceDesign);}));
    $('[data-v019-new-design]')?.addEventListener('click', () => showTab('templates'));
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
      clone.textContent = '直接复制 Revision';
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
      edit.textContent = '修改设计并创建新 Revision';
      edit.addEventListener('click', openRevisionEditorV019);
      actions.prepend(edit);
    }
    return loaded||state.workspaceDesign;
  };

  function openRevisionEditorV019() {
    const design = state.workspaceDesign;
    const rev = state.workspaceRevision;
    if (!design || !rev) return toast('请先选择 Design Revision', 'WARNING');
    const template = state.templates.find(t => t.id === design.template_id);
    const schema = state.registry?.parameters || {};
    const ids = (template?.parameter_ids || Object.keys(rev.parameters || {})).filter(id => schema[id] && rev.parameters?.[id] !== undefined);
    const categoryLabels = {topology:'拓扑', geometry:'主要几何', magnet:'永磁体', winding:'绕组', operating:'运行参数', environment:'环境', cooling:'冷却'};
    const groups = {};
    ids.forEach(id => {(groups[schema[id].category || 'other'] ??= []).push(id);});
    const canvas = $('#workspaceCanvas');
    const inspector = $('#workspaceInspector');
    if (!canvas) return;
    canvas.innerHTML = `<div class="workspace-object-header workspace-create-header"><div><span class="eyebrow">编辑设计 · 创建不可变新版本</span><h2>${esc(design.name)} · 基于 Rev.${esc(rev.revision)}</h2><p>这里修改的是设计定义。保存后生成新的不可变 Revision，历史计算仍指向旧版本。</p></div><div class="actions"><button id="cancelRevisionEdit" type="button">取消</button></div></div><div class="design-revision-editor"><div class="revision-editor-toolbar"><div><b>设计参数</b><small id="designRevisionChangeCount">0 项修改</small></div><label>Revision说明<input id="designRevisionNotes" placeholder="例如：12槽基线，减小气隙并增加磁体厚度"></label></div>${Object.entries(groups).map(([cat, rows]) => `<section class="design-editor-group"><h3>${esc(categoryLabels[cat] || cat)}</h3><div class="design-editor-grid">${rows.map(id => {const d=schema[id], value=rev.parameters[id]; return `<label class="design-editor-field" data-design-base="${esc(value)}"><span><b>${esc(d.label || id)}</b><small>${esc(id)}</small></span><div><input data-design-revision-param="${esc(id)}" type="number" step="${d.type === 'integer' ? '1' : 'any'}" min="${d.minimum ?? ''}" max="${d.maximum ?? ''}" value="${esc(value)}"><em>${esc(d.unit || '')}</em></div></label>`;}).join('')}</div></section>`).join('')}<div class="revision-editor-footer"><div class="callout info"><b>材料继承</b><br>本次只编辑参数；材料快照将继承 Rev.${esc(rev.revision)}。材料体系需要调整时可在工程模式中配置后再保存 Revision。</div><div class="actions"><button id="saveDesignRevision" class="primary" type="button">保存为新 Revision</button></div></div></div>`;
    if (inspector) inspector.innerHTML = `<div class="inspector-block"><span class="eyebrow">版本规则</span><h3>设计修改与仿真分离</h3><p>几何、槽极、绕组等长期设计意图在这里形成新 Revision；仿真页默认只选择 Revision、工况和分析类型。</p><div class="property-grid"><span>Base</span><b>Rev.${esc(rev.revision)}</b><span>Parameters</span><b>${Object.keys(rev.parameters || {}).length}</b><span>Explicit intent</span><b>${(rev.explicit_parameter_ids || []).length}</b></div></div>`;
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
      if (!changedIds.length) return toast('没有检测到参数修改，无需创建新 Revision。', 'WARNING');
      const parameters = {...(rev.parameters || {})};
      $$('[data-design-revision-param]').forEach(i => {parameters[i.dataset.designRevisionParam] = Number(i.value);});
      const explicit = [...new Set([...(rev.explicit_parameter_ids || []), ...changedIds])];
      const btn = $('#saveDesignRevision');
      btn.disabled = true; btn.textContent = '正在创建新 Revision…';
      try {
        const created = await api(`/api/designs/${encodeURIComponent(design.id)}/revisions`, {method:'POST', body:JSON.stringify({parameters, materials:rev.materials || {}, explicit_parameter_ids:explicit, notes:$('#designRevisionNotes')?.value || `基于 Rev.${rev.revision} 的设计修改`})});
        state.workspaceProject = await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}`);
        toast(`已创建 Rev.${created.revision}`, 'SUCCESS', 6000);
        await openWorkspaceDesign(design.id);
        if (created.id) selectWorkspaceRevision(created.id);
      } catch (e) {
        btn.disabled = false; btn.textContent = '保存为新 Revision';
        toast(e.message, 'ERROR', 8000);
      }
    });
    updateChanged();
  }

  function initTaskWizardV019() {
    const form = $('#taskForm');
    if (!form || $('#taskWizardHeader')) return;
    const panels = [...form.children].filter(el => el.matches('article.panel'));
    const findPanel = needle => panels.find(p => (p.querySelector('h2')?.textContent || '').includes(needle));
    const context = findPanel('任务与设计上下文');
    const params = findPanel('工程参数编辑器');
    const materials = findPanel('材料与高级');
    const scenario = findPanel('运行场景与边界条件');
    const automation = findPanel('自动化任务');
    const outputs = findPanel('结果请求');
    const submit = panels.find(p => p.classList.contains('submit-panel'));
    if (!context || !scenario || !automation || !outputs || !submit) return;

    const header = document.createElement('article');
    header.id = 'taskWizardHeader';
    header.className = 'panel task-wizard-header';
    header.innerHTML = `<div><span class="eyebrow">仿真配置</span><h2>配置一次可追溯的 Motor-CAD 计算</h2><p>操作模式按“基线 → 工况 → 计算方式 → 输出 → 检查提交”推进。设计参数长期修改应在“设计”阶段创建新 Revision。</p></div><div id="taskWizardNav" class="task-wizard-nav"></div>`;
    form.before(header);

    if (params || materials) {
      const drawer = document.createElement('details');
      drawer.id = 'taskOverrideDrawer';
      drawer.className = 'task-override-drawer';
      drawer.innerHTML = `<summary><span><b>高级：本次运行覆盖 Design Revision</b><small>仅用于临时试算；长期几何/绕组修改建议返回“设计”创建新 Revision</small></span><span class="chip warning">可选</span></summary><div class="task-override-content"></div>`;
      context.after(drawer);
      const body = drawer.querySelector('.task-override-content');
      if (params) {params.querySelector('h2').textContent = '临时设计参数覆盖'; body.appendChild(params);}
      if (materials) {materials.querySelector('h2').textContent = '材料与高级 Motor-CAD 覆盖'; body.appendChild(materials);}
    }

    context.querySelector('h2').textContent = '选择计算基线';
    scenario.querySelector('h2').textContent = '设置工况';
    automation.querySelector('h2').textContent = '选择计算方式';
    outputs.querySelector('h2').textContent = '选择需要的输出';
    [context, scenario, automation, outputs].forEach((panel, i) => {
      const badge = panel.querySelector('.section-head .step');
      if (badge) badge.textContent = String(i + 1);
    });
    if (!submit.querySelector('.section-head')) submit.insertAdjacentHTML('afterbegin', '<div class="section-head"><div><span class="step">5</span><h2>检查并提交</h2><p>先运行模型可解性和预检查；通过后提交真实 Motor-CAD 任务。</p></div></div>');

    state.taskWizardPanelsV019 = [context, scenario, automation, outputs, submit];
    state.taskWizardLabelsV019 = ['基线', '工况', '计算方式', '输出', '检查提交'];
    state.taskWizardPanelsV019.forEach((panel, i) => {
      panel.dataset.taskWizardStep = String(i);
      const controls = document.createElement('div');
      controls.className = 'task-wizard-controls';
      controls.innerHTML = `${i > 0 ? '<button type="button" data-task-prev>← 上一步</button>' : '<span></span>'}${i < 4 ? `<button type="button" class="primary" data-task-next>下一步：${esc(state.taskWizardLabelsV019[i+1])} →</button>` : ''}`;
      panel.appendChild(controls);
      controls.querySelector('[data-task-prev]')?.addEventListener('click', () => setTaskWizardStepV019(i - 1));
      controls.querySelector('[data-task-next]')?.addEventListener('click', () => {
        if (i === 0 && !$('#taskDesignRevisionSelect')?.value) return toast('先选择当前项目的 Design Revision。', 'WARNING');
        if (i === 3 && !$$('[data-output]:checked').length) return toast('至少选择一个结果输出。', 'WARNING');
        setTaskWizardStepV019(i + 1);
      });
    });
    $('#taskDesignRevisionHint').textContent = '选择不可变 Design Revision 作为本次计算基线。长期设计修改请回到“设计”阶段。';
    const saveRev = $('#saveTaskDesignRevision');
    if (saveRev) saveRev.closest('.revision-save-row')?.classList.add('engineering-only-action');
    setTaskWizardStepV019(0, false);
  }

  function setTaskWizardStepV019(step, scroll = true) {
    const panels = state.taskWizardPanelsV019 || [];
    if (!panels.length) return;
    const next = Math.max(0, Math.min(panels.length - 1, Number(step) || 0));
    state.taskWizardStepV019 = next;
    panels.forEach((p, i) => p.classList.toggle('task-wizard-hidden', i !== next));
    $('#taskOverrideDrawer')?.classList.toggle('task-wizard-hidden', next !== 0);
    const nav = $('#taskWizardNav');
    if (nav) {
      nav.innerHTML = (state.taskWizardLabelsV019 || []).map((label, i) => `<button type="button" data-task-wizard-jump="${i}" class="${i === next ? 'active' : ''} ${i < next ? 'done' : ''}"><span>${i + 1}</span>${esc(label)}</button>`).join('');
      $$('[data-task-wizard-jump]').forEach(b => b.addEventListener('click', () => {
        const target = Number(b.dataset.taskWizardJump);
        if (target > 0 && !$('#taskDesignRevisionSelect')?.value) return toast('先选择 Design Revision，再继续配置计算。', 'WARNING');
        setTaskWizardStepV019(target);
      }));
    }
    if (scroll) $('#taskWizardHeader')?.scrollIntoView({behavior:'smooth', block:'start'});
  }

  async function refreshOperatorBaselineGateV019() {
    if (!state.activeProjectId) return;
    try {
      const d = await api(`/api/dashboard?project_id=${encodeURIComponent(state.activeProjectId)}`);
      const hasBaseline = Number(d.tasks?.completed || 0) > 0;
      state.operatorHasBaselineV019 = hasBaseline;
      const operator = document.body.dataset.userMode === 'operator';
      const radios = $$('input[name="experimentMode"]');
      radios.forEach(r => {
        if (r.value === 'single') return;
        r.disabled = operator && !hasBaseline;
        r.closest('label')?.classList.toggle('mode-locked', operator && !hasBaseline);
        r.closest('label')?.setAttribute('title', operator && !hasBaseline ? '先完成一次成功的单次基准计算，再开展扫描/DOE/优化。' : '');
      });
      if (operator && !hasBaseline && !$('#taskBaselineGate')) {
        const modeTabs = $('.mode-tabs');
        modeTabs?.insertAdjacentHTML('beforebegin', '<div id="taskBaselineGate" class="baseline-gate"><b>建议流程：先跑通单次基准</b><span>当前项目还没有成功基准任务。操作模式暂时锁定扫描、DOE 和 NSGA-II；基准成功后自动开放。</span></div>');
      }
      if (hasBaseline) $('#taskBaselineGate')?.remove();
      if (operator && !hasBaseline) {
        const checked = document.querySelector('input[name="experimentMode"]:checked');
        if (checked && checked.value !== 'single') {
          const single = document.querySelector('input[name="experimentMode"][value="single"]');
          if (single) {single.checked = true; single.dispatchEvent(new Event('change', {bubbles:true}));}
        }
      }
    } catch (e) {
      console.warn('baseline gate', e);
    }
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
    setTimeout(() => {
      refreshOperatorBaselineGateV019();
      document.body.classList.toggle('operator-flow', document.body.dataset.userMode === 'operator');
    }, 0);
  });

  document.addEventListener('click', e => {
    const back = e.target.closest('#workspaceBackProjects');
    if (back) syncProjectShellV019('projects');
  });

  initTaskWizardV019();
  document.body.classList.toggle('operator-flow', document.body.dataset.userMode === 'operator');
  setTimeout(() => {
    syncProjectShellV019(activeTabV019());
    syncProjectManagerRuntimeV019();
  }, 250);
})();
