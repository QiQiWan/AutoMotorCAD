from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]; STATIC=ROOT/'motorcad_studio'/'static'
def read(name:str)->str:return (STATIC/name).read_text(encoding='utf-8')

def test_project_shell_has_one_four_stage_engineer_flow():
    html=read('index.html');nav=re.search(r'<nav class="project-stage-nav canonical-project-flow engineer-journey-nav-v086r".*?</nav>',html,re.S);assert nav
    rows=re.findall(r'data-tab="([^"]+)"[^>]+data-engineer-stage="([^"]+)"[^>]*>.*?<b>([^<]+)</b>',nav.group(0),re.S)
    assert rows==[('workspace','design','设计'),('analysisConfig','validate','验证'),('resultViewer','results','结果'),('resultViewer','decide','决策')]
    for token in ['id="workflowRibbon"','id="projectSecondaryNav"','id="motorcadContextNavV046"','/static/workflow/flow-rail.js']:assert token not in html

def test_solution_is_first_class_routed_page_and_api():
    html=read('index.html');app=read('app.js');router=read('router.js');controllers=read('routing/page-controllers.js');canonical=read('canonical-project-flow.js')
    assert 'id="solutions" class="tab"' in html and 'id="createSolutionCanonical"' in html
    assert "if(tab==='solutions')return projectPath('solutions')" in router and "if(rest[0]==='solutions')return{tab:'solutions',projectId}" in router
    assert 'solution:{' in controllers and 'async function mountSolutions' in canonical
    assert '/api/solutions/${encodeURIComponent(row.id)}' in canonical
    assert '/solutions/from-template' in app and '/api/solutions/${designId}' in app

def test_legacy_analysis_owners_are_physically_removed():
    html=read('index.html')
    retired=['analysis/workbench.js','analysis/execution.js','analysis/case-catalog.js','workflow/engineer-task-flow.js','workflow/engineer-language.js','workflow/flow-rail.js']
    assert all(not (STATIC/path).exists() for path in retired)
    assert 'id="workspaceToAnalysisCanonical"' in html
    assert 'id="newTask"' not in html and 'id="simulationAssets"' not in html
    source='\n'.join(p.read_text(encoding='utf-8') for p in STATIC.rglob('*.js'))
    assert '#taskForm' not in source and 'MCSV040' not in source and 'MCSV060' not in source

def test_analysis_creation_requires_existing_solution_revision():
    analysis=read('analysis/unified-configuration.js')
    assert 'selectedRevisionId' in analysis and 'design_revision_id' in analysis
    assert 'noRevision' in analysis and '/api/solutions/${encode(row.id)}' in analysis
    assert "showTab('newTask')" not in analysis

def test_canonical_assets_are_loaded_after_router_owner_boundary():
    html=read('index.html')
    assert '/static/canonical-project-flow.css?v=0.89.9' in html
    assert html.index('/static/canonical-project-flow.js?v=')>html.index('/static/router.js?v=')
