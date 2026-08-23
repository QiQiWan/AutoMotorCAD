from __future__ import annotations

import time
from fastapi.testclient import TestClient

import motorcad_studio.main as main_module
from motorcad_studio.main import app
from motorcad_studio.motor_domain import MotorSnapshot

client = TestClient(app)


def create_project() -> dict:
    r = client.post('/api/projects', json={'name': f'Optimization-{time.time_ns()}', 'description': 'current optimization decision fixture'})
    assert r.status_code == 201, r.text
    return r.json()


def create_analysis_case(project_id: str) -> dict:
    r = client.post(f'/api/projects/{project_id}/analysis-cases', json={
        'name': 'Current robust EMag', 'motor_name': 'Current BPM', 'motor_type_id': 'BPM', 'source_kind': 'default',
        'module': 'EMag', 'recipe_id': 'emag',
        'load_cases': [
            {'shaft_speed_rpm': 2000, 'peak_current_a': 6, 'dc_bus_voltage_v': 320, 'phase_advance_deg': 0},
            {'shaft_speed_rpm': 5000, 'peak_current_a': 10, 'dc_bus_voltage_v': 360, 'phase_advance_deg': 5},
        ],
        'requested_outputs': ['shaft_torque_nm', 'magnet_loss_w', 'efficiency_percent'],
    })
    assert r.status_code == 201, r.text
    created = r.json()
    m = client.put(f"/api/analysis-definitions/{created['id']}/input-domains/materials", json={'values': {
        'stator_material': 'M350-50A', 'rotor_material': 'M350-50A', 'magnet_material': 'N30UH',
        'conductor_material': 'Copper (Pure)', 'housing_material': 'Aluminium (Cast)', 'coolant_fluid': 'Air',
    }, 'notes': 'current material confirmation'})
    assert m.status_code == 200, m.text
    return created


def wait_task(task_id: str) -> dict:
    for _ in range(1200):
        r = client.get(f'/api/tasks/{task_id}/summary')
        assert r.status_code == 200, r.text
        data = r.json()
        if data['status'] in {'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'}:
            return data
        time.sleep(.02)
    raise AssertionError('task did not finish')


def build_task_payload(project_row: dict, created: dict, *, mode: str = 'full_factorial', generations: int = 1) -> dict:
    design = main_module.workspace.get_design(created['design_id'])
    revision = main_module.workspace.get_design_revision(created['design_revision_id'])
    assert design and revision
    template = main_module.templates.get_template(design['template_id'])
    parameters = {**(template.get('defaults') or {}), **(revision.get('parameters') or {})}
    snapshot = MotorSnapshot.model_validate(revision['motor_snapshot'])
    latest = client.get(f"/api/analysis-definitions/{created['id']}").json()['revisions'][0]
    load_cases = latest['definition']['load_cases']
    op_set = main_module.optimization_planning.build_operating_point_set(
        analysis_definition_revision_id=latest['id'], load_cases=load_cases,
        selections=[{'load_case_index': 0, 'weight': 1, 'label': '低速点'}, {'load_case_index': 1, 'weight': 2, 'label': '高速点'}],
    )
    experiment = {
        'mode': mode, 'variables': [{'parameter': 'air_gap', 'low': 0.7, 'high': 0.9, 'levels': 2}],
        'samples': 4, 'seed': 87, 'include_baseline': True, 'population_size': 4, 'generations': generations,
        'crossover_rate': 0.9, 'mutation_rate': 0.2,
        'objectives': ([
            {'result_id': 'shaft_torque_nm', 'direction': 'max', 'aggregation': 'weighted_mean', 'percentile': 95},
            {'result_id': 'magnet_loss_w', 'direction': 'min', 'aggregation': 'weighted_mean', 'percentile': 95},
        ] if mode == 'nsga2' else [
            {'result_id': 'shaft_torque_nm', 'direction': 'max', 'aggregation': 'weighted_mean', 'percentile': 95}
        ]),
        'constraints': [{'field': 'result.magnet_loss_w', 'operator': '<=', 'value': 1e9, 'aggregation': 'all_points', 'percentile': 95}],
        'robustness': {
            'enabled': True, 'samples': 2, 'seed': 8703, 'include_nominal': True, 'sampling': 'latin_hypercube',
            'distributions': [{'target_scope': 'design', 'target_id': 'air_gap', 'distribution': 'uniform', 'scale_mode': 'relative', 'lower_delta': -0.02, 'upper_delta': 0.02}],
            'objective_strategy': 'risk_adjusted_mean', 'risk_weight': 1.0, 'percentile': 95,
            'constraint_strategy': 'probability', 'required_feasibility_probability': 0.66,
        },
        'sensitivity': {'enabled': True, 'methods': ['local', 'morris', 'sobol'], 'output_ids': ['shaft_torque_nm']},
    }
    unc, rob = main_module.optimization_planning.build_uncertainty_scenario_set(
        snapshot=snapshot, operating_point_set=op_set, robustness=experiment['robustness']
    )
    assert unc and rob and len(unc.samples) == 3
    space, plan = main_module.optimization_planning.build_experiment_plan(
        design_revision_id=revision['id'], snapshot=snapshot, experiment=experiment,
        analysis_definition_revision_id=latest['id'], execution_plan_hash=None, operating_point_set=op_set,
        uncertainty_scenario_set=unc, robustness_plan=rob,
    )
    return {
        'project_id': project_row['id'], 'project_name': project_row['name'], 'name': f'Current robust {time.time_ns()}',
        'template_id': design['template_id'], 'design_revision_id': revision['id'], 'analysis_definition_revision_id': latest['id'],
        'solver_mode': 'mock', 'analysis': 'emag', 'parameters': parameters, 'explicit_parameter_ids': ['air_gap'],
        'scenario': load_cases[0], 'scenario_matrix': load_cases, 'experiment': experiment,
        'optimization_space': space.model_dump(mode='json'), 'experiment_plan': plan.model_dump(mode='json'),
        'operating_point_set': op_set.model_dump(mode='json'), 'uncertainty_scenario_set': unc.model_dump(mode='json'),
        'robustness_plan': rob.model_dump(mode='json'),
        'requested_outputs': ['shaft_torque_nm', 'magnet_loss_w', 'efficiency_percent'], 'reuse_cache': False,
    }
