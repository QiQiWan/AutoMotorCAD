from __future__ import annotations

import re
from pathlib import Path

from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'motorcad_studio' / 'static' / 'index.html').read_text(encoding='utf-8')
APP_JS = (ROOT / 'motorcad_studio' / 'static' / 'app.js').read_text(encoding='utf-8')
FLOW_JS = (ROOT / 'motorcad_studio' / 'static' / 'operator-flow.js').read_text(encoding='utf-8')


def _fragment(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_version_and_operator_flow_asset_are_enabled():
    assert tuple(map(int, __version__.split('.'))) >= (0, 19, 0)
    assert f'data-studio-version="{__version__}"' in INDEX
    assert f'/static/operator-flow.js?v={__version__}' in INDEX
    assert '<option value="operator">引导模式 / Guided</option>' in INDEX
    assert '<option value="engineering" selected>' in INDEX


def test_global_information_architecture_has_only_four_global_destinations():
    nav = _fragment(INDEX, '<nav class="nav-tabs global-nav"', '</nav>')
    tabs = re.findall(r'data-tab="([^"]+)"', nav)
    assert tabs == ['projects', 'setup', 'logs', 'system']
    for project_page in ['dashboard', 'workspace', 'templates', 'newTask', 'monitor', 'tasks', 'resultViewer', 'dataFactory']:
        assert f'data-tab="{project_page}"' not in nav


def test_project_shell_exposes_engineer_centered_primary_stages():
    shell = _fragment(INDEX, '<section id="projectShell"', '</section>')
    stages = re.findall(r'data-project-stage="([^"]+)"', shell)
    assert stages == ['overview', 'design', 'simulation', 'results', 'data']
    assert '项目内不提供跨项目切换' in FLOW_JS
    assert "dashboard: 'overview'" in FLOW_JS
    assert "workspace: 'design'" in FLOW_JS
    assert "newTask: 'simulation'" in FLOW_JS


def test_entering_project_opens_overview_and_design_returns_to_overview():
    assert "showTab('dashboard')" in APP_JS
    assert "$('#workspaceBackProjects')?.addEventListener('click',()=>showTab('dashboard'))" in APP_JS
    assert '← 返回项目概览' in INDEX


def test_project_overview_drives_one_recommended_next_action():
    assert '推荐下一步' in FLOW_JS
    assert "title:'创建第一个 Design'" in FLOW_JS
    assert "title:'先完成一次单次基准计算'" in FLOW_JS
    assert "title:'审查最新有效结果'" in FLOW_JS
    assert 'projectNextActionCard' in INDEX
    assert 'workflowRibbon' in INDEX


def test_design_definition_is_separated_from_task_runtime_overrides():
    assert '修改设计并创建新 Revision' in FLOW_JS
    assert '/api/designs/${encodeURIComponent(design.id)}/revisions' in FLOW_JS
    assert '设计修改与仿真分离' in FLOW_JS
    assert '高级：本次运行覆盖 Design Revision' in FLOW_JS
    assert '长期几何/绕组修改建议返回“设计”创建新 Revision' in FLOW_JS


def test_simulation_builder_is_a_five_step_wizard_with_baseline_gate():
    assert "['基线', '工况', '计算方式', '输出', '检查提交']" in FLOW_JS
    assert 'taskWizardHeader' in FLOW_JS
    assert '先跑通单次基准' in FLOW_JS
    assert "r.disabled = operator && !hasBaseline" in FLOW_JS


def test_new_task_submission_continues_directly_to_live_monitor():
    submit_flow = re.search(r"state\.monitorTask\s*=\s*r\.task_id.*?showTab\('monitor'\)", APP_JS, re.S)
    assert submit_flow, 'Task creation should continue to the live monitor instead of dropping the operator in a list page.'


def test_runtime_is_first_run_only_and_project_manager_shows_runtime_state():
    assert "const defaultTab=runtimeConfigured?'projects':'setup'" in APP_JS
    assert 'MCSRouter.start(defaultTab)' in APP_JS
    assert 'projectManagerRuntimeBadge' in INDEX
    assert 'syncProjectManagerRuntimeV019' in FLOW_JS
    assert 'Motor-CAD 未绑定' in FLOW_JS
    assert 'Motor-CAD 已绑定' in FLOW_JS


def test_project_stage_statuses_make_future_stages_visibly_pending():
    assert 'syncProjectStageStateV019' in FLOW_JS
    assert "results: completed > 0" in FLOW_JS
    assert "data: completed > 0" in FLOW_JS
    assert 'stage-pending' in (ROOT / 'motorcad_studio' / 'static' / 'styles.css').read_text(encoding='utf-8')
