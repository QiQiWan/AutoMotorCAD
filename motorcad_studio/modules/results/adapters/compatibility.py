from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from ....engineering_lineage import EngineeringLineage
from ....models import BaselineCaptureRequest, BaselineCompareRequest, ResultCalibrationRequest
from ....native_closure import build_native_closure_scope
from ....result_domain.aggregate import (
    ResultBundleAggregateBatchResponse,
    ResultBundleAggregateEnvelope,
)
from ....result_domain.comparison import ResultSetAggregateEnvelope, ResultSetCompareRequest
from ....result_domain.interpretation import BaselineSetRequest
from ....runtime.result_probe_process import MotorCADResultProbeRunner
from ....bootstrap.container import ServiceContainer


class ResultsCompatibilityAdapter:
    """Infrastructure adapter for the stable V1 Results HTTP semantics.

    The adapter owns transitional compatibility behavior while the application
    service exposes a database-agnostic operation port. No process-wide resource is
    constructed here; every dependency comes from the sealed ServiceContainer.
    """

    def __init__(self, container: ServiceContainer) -> None:
        self.settings = container.settings
        self.db = container.db
        self.logs = container.logs
        self.registry = container.registry
        self.templates = container.templates
        self.calibration = container.calibration
        self.result_viewer = container.result_viewer
        self.result_aggregates = container.result_aggregates
        self.result_sets = container.result_sets
        self.engineering_requirements = container.engineering_requirements
        self.result_interpretation = container.result_interpretation
        self.results_optimization = container.results_optimization
        self.tasks = container.tasks
        self.engineering_lineage = container.engineering_lineage
        self.native_closure_profiles = container.native_closure_profiles
        self.native_closure_registry = container.native_closure_registry
        self.motor_domain = container.motor_domain
        self.motorcad_binding_planner = container.motorcad_binding_planner
        self.system_service = container.system_service
    def _native_closure_expected_scopes(self) -> dict[str, dict[str, Any]]:
        """Derive current V0.73-A trust scopes without opening Motor-CAD."""
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        scopes: dict[str, dict[str, Any]] = {}
        for profile in native_closure_profiles.list_profiles():
            profile_id = str(profile.get('id') or '')
            try:
                template = templates.get_template(str(profile.get('template_id') or ''))
                scopes[profile_id] = build_native_closure_scope(motor_domain=motor_domain, binding_planner=motorcad_binding_planner, template=template, profile=profile)
            except Exception as exc:
                scopes[profile_id] = {'profile_id': profile_id, 'scope_error': f'{type(exc).__name__}: {exc}'}
        return scopes

    def _native_closure_matrix(self) -> dict[str, Any]:
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        profiles = native_closure_profiles.list_profiles()
        scopes = _native_closure_expected_scopes()
        matrix = native_closure_registry.matrix(profiles, expected_scopes=scopes)
        for row in matrix.get('profiles') or []:
            scope = scopes.get(str(row.get('profile_id') or '')) or {}
            if scope.get('scope_error'):
                row['status'] = 'BINDING_ERROR'
                row['qualified'] = False
                row['scope_error'] = scope['scope_error']
        matrix['complete'] = bool(matrix.get('profiles')) and all((bool(row.get('qualified')) for row in matrix.get('profiles') or []))
        matrix['gate'] = 'PASS' if matrix['complete'] else 'PENDING'
        matrix['release_track'] = 'V0.88-C Validation Fault Tree & Native Repair Orchestration'
        return matrix

    def _lineage_etag_matches(self, header: str | None, etag: str) -> bool:
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        if not header:
            return False
        target = etag.strip('"')
        for token in header.split(','):
            candidate = token.strip()
            if candidate.startswith('W/'):
                candidate = candidate[2:].strip()
            if candidate.strip('"') == target or candidate == '*':
                return True
        return False

    def _resolve_engineering_lineage_http(self, request: Request, response: Response, **identity: str | None) -> EngineeringLineage | Response:
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            lineage, etag, cache_hit, generation = engineering_lineage.resolve_cached(**identity)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if lineage is None or etag is None:
            raise HTTPException(status_code=404, detail='engineering lineage object not found')
        cacheable = bool(lineage.integrity.valid)
        headers = {'ETag': f'"{etag}"', 'Cache-Control': 'private, no-cache, must-revalidate' if cacheable else 'no-store', 'X-MCS-Lineage-Cache': ('HIT' if cache_hit else 'MISS') if cacheable else 'BYPASS', 'X-MCS-Lineage-Generation': str(generation), 'X-MCS-DB-Generation': str(generation)}
        if cacheable and _lineage_etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        for key, value in headers.items():
            response.headers[key] = value
        return lineage

    def result_calibration_entries(self, template_id: str | None=Query(default=None)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        return {'motorcad_version': settings.motorcad_version, 'entries': calibration.result_calibrations(template_id)}

    def result_calibration_recommended(self, template_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='template not found') from exc
        probes = []
        for result_id, spec in registry.output_schema(template_id).items():
            extractor = str(spec.get('extractor') or '')
            candidates = spec.get('graph_candidates') or []
            if extractor in {'magnetic_graph', 'magnetic_harmonics', 'fea_graph', 'magnetic_3d_graph', 'temperature_graph', 'heatflow_graph', 'power_graph'} and candidates:
                probes.append({'result_id': result_id, 'extractor': extractor, 'graph_name': str(candidates[0]), 'section_number': int(spec.get('section_number') or 1), 'point_number': int(spec.get('point_number') or 0), 'source': 'versioned_output_registry'})
        return {'template_id': template_id, 'motorcad_version': settings.motorcad_version, 'probes': probes, 'note': 'PyMotorCAD documented graph APIs require a graph name; Motor-CAD Help -> Graph Viewer is the authoritative place to confirm names.'}

    def probe_result_calibration(self, payload: ResultCalibrationRequest, timeout_s: float=Query(default=180.0, ge=20.0, le=900.0)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            template = templates.get_template(payload.template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='template not found') from exc
        request_payload = {**_deep_preflight_payload(), 'template': template, 'analysis': payload.analysis.value, 'run_calculation': payload.run_calculation, 'probes': [item.model_dump() for item in payload.probes]}
        result = MotorCADResultProbeRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(request_payload)
        for item in result.get('results') or []:
            calibration.save_result_calibration(payload.template_id, item['result_id'], item['extractor'], item['graph_name'], int(item.get('section_number') or 1), item.get('status') or 'FAILED', {'summary': item.get('summary'), 'error': item.get('error'), 'analysis': payload.analysis.value, 'run_calculation': payload.run_calculation})
        logs.audit(level='INFO' if result.get('ok') else 'WARNING', component='result_calibration', event_type='RESULT_PROBE', message=f'result probe {payload.template_id}', payload={'template_id': payload.template_id, 'analysis': payload.analysis.value, 'run_calculation': payload.run_calculation, 'count': len(payload.probes), 'ok': result.get('ok')})
        return {**result, 'calibrations': calibration.result_calibrations(payload.template_id)}

    def project_results_workbench(self, project_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
            payload = results_optimization.project_workbench(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目不存在') from exc
        matrix = _native_closure_matrix()
        payload['native_closure'] = matrix
        payload['native_parity'] = matrix
        payload['engineering_decision_status'] = 'NATIVE_QUALIFIED' if matrix.get('complete') else 'NATIVE_QUALIFICATION_PENDING'
        return payload

    def get_result_bundle_engineering_lineage(self, result_bundle_id: str, request: Request, response: Response):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        return _resolve_engineering_lineage_http(request, response, result_bundle_id=result_bundle_id)

    def result_viewer_catalog(self):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        return result_viewer.catalog()

    def result_viewer_compare(self, case_ids: str=Query(..., min_length=1)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        ids = [item.strip() for item in case_ids.split(',') if item.strip()]
        if len(ids) >= 2:
            placeholders = ','.join(('?' for _ in ids))
            rows = db.query_all(f'SELECT id,result_bundle_id FROM cases WHERE id IN ({placeholders})', tuple(ids))
            by_id = {str(row['id']): row for row in rows}
            bundle_ids = [str((by_id.get(case_id) or {}).get('result_bundle_id') or '') for case_id in ids]
            if len(rows) == len(ids) and all(bundle_ids):
                try:
                    result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
                    aggregate = result_sets.build(bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope='general')
                    return result_sets.legacy_case_compare_projection(aggregate)
                except (KeyError, ValueError):
                    pass
        try:
            return result_viewer.compare_cases(ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'Case不存在: {exc.args[0]}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def task_result_comparison(self, task_id: str, case_ids: str=Query(..., min_length=1)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        ids = [item.strip() for item in case_ids.split(',') if item.strip()]
        if len(ids) < 2 or len(ids) > 8 or len(set(ids)) != len(ids):
            raise HTTPException(status_code=422, detail='同一 Task 工程比较必须选择 2–8 个互不重复的 Case')
        if not db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        placeholders = ','.join(('?' for _ in ids))
        rows = db.query_all(f'SELECT id,task_id,result_bundle_id FROM cases WHERE id IN ({placeholders})', tuple(ids))
        by_id = {str(row['id']): row for row in rows}
        missing = [case_id for case_id in ids if case_id not in by_id]
        if missing:
            raise HTTPException(status_code=404, detail=f'Case不存在: {missing[0]}')
        foreign = [case_id for case_id in ids if str((by_id.get(case_id) or {}).get('task_id') or '') != task_id]
        if foreign:
            raise HTTPException(status_code=422, detail={'code': 'CASE_COMPARISON_TASK_MISMATCH', 'message': '通用工程结果比较要求所有 Case 来自同一个 Task / Run Configuration。', 'task_id': task_id, 'foreign_case_ids': foreign})
        bundle_ids = [str(by_id[case_id].get('result_bundle_id') or '') for case_id in ids]
        if all(bundle_ids):
            try:
                result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
                aggregate = result_sets.build(bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope='same_task')
                payload = result_sets.legacy_case_compare_projection(aggregate)
                payload['comparison_scope'] = 'same_task'
                payload['task_id'] = task_id
                return payload
            except ValueError as exc:
                detail = str(exc)
                if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                    raise HTTPException(status_code=409, detail={'code': 'RESULT_SET_MEMBER_LINEAGE_INVALID', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
                raise HTTPException(status_code=422, detail=detail) from exc
        try:
            payload = result_viewer.compare_cases(ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'Case不存在: {exc.args[0]}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload['comparison_scope'] = 'same_task'
        payload['task_id'] = task_id
        payload['comparison_authority'] = 'LegacyResultCompatibility'
        return payload

    def case_result_viewer(self, case_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        payload = result_viewer.case_payload(case_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='Case不存在')
        payload['result_calibrations'] = calibration.result_calibrations(str(payload.get('case', {}).get('template_id') or ''))
        return payload

    def case_result_trust(self, case_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        result_viewer.result_trust.native_qualification_resolver = result_viewer.native_qualification_resolver
        trust = result_viewer.result_trust.evaluate_case(case_id)
        if trust is None:
            raise HTTPException(status_code=404, detail='Case不存在')
        return {'trust': trust.model_dump(mode='json'), 'trust_authority': 'ResultTrustSnapshotV1', 'contract_version': '0.73-D'}

    def case_result_bundle(self, case_id: str, include_data: bool=Query(default=False)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        if not db.query_one('SELECT id FROM cases WHERE id=?', (case_id,)):
            raise HTTPException(status_code=404, detail='Case不存在')
        bundle = tasks.result_bundles.get_for_case(case_id, hydrate_heavy=include_data)
        if bundle is None:
            raise HTTPException(status_code=404, detail={'code': 'RESULT_BUNDLE_NOT_AVAILABLE', 'message': '该历史 Case 尚未生成 V0.73-C ResultBundle，可通过重新计算或兼容读取访问旧结果。'})
        return {'result_bundle': bundle.model_dump(mode='json'), 'result_bundle_hash': bundle.content_hash(), 'result_authority': 'ResultBundleV1', 'heavy_data_hydrated': bool(include_data), 'result_data_gateway': 'ResultDataGatewayV2'}

    def result_bundle_aggregate_query(self, payload: dict[str, Any]):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        raw_ids = payload.get('result_bundle_ids') or []
        ids = [str(value).strip() for value in raw_ids if str(value).strip()] if isinstance(raw_ids, list) else []
        ids = list(dict.fromkeys(ids))
        if not ids or len(ids) > 24:
            raise HTTPException(status_code=422, detail='result_bundle_ids 必须包含 1–24 个互不重复的 ResultBundle ID')
        include = payload.get('include')
        try:
            include_sections = result_aggregates.normalize_includes(include)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(ids) > 8 and {'datasets', 'viewer'} & set(include_sections):
            raise HTTPException(status_code=422, detail='批量 Aggregate 的 datasets/viewer 重载模式最多支持 8 个 ResultBundle')
        strict = bool(payload.get('strict', True))
        aggregates = []
        errors = []
        result_aggregates.native_qualification_resolver = result_viewer.native_qualification_resolver
        for bundle_id in ids:
            try:
                aggregate = result_aggregates.build(bundle_id, include=include_sections)
                if aggregate is None:
                    errors.append({'result_bundle_id': bundle_id, 'code': 'RESULT_BUNDLE_NOT_FOUND'})
                    continue
                aggregates.append({'result_bundle_id': bundle_id, 'aggregate_hash': result_aggregates.content_hash(aggregate), 'aggregate': aggregate})
            except ValueError as exc:
                detail = str(exc)
                code = 'RESULT_BUNDLE_LINEAGE_INVALID' if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:') else 'RESULT_BUNDLE_AGGREGATE_INVALID'
                errors.append({'result_bundle_id': bundle_id, 'code': code, 'detail': detail})
        if strict and errors:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_BUNDLE_AGGREGATE_BATCH_REJECTED', 'errors': errors})
        return {'aggregate_authority': 'ResultBundleAggregateV1', 'contract_version': '0.79-A', 'requested_count': len(ids), 'aggregate_count': len(aggregates), 'error_count': len(errors), 'aggregates': aggregates, 'errors': errors}

    def result_bundle_requirement_evaluation(self, result_bundle_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            evaluation = engineering_requirements.evaluate_result_bundle(result_bundle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='ResultBundle不存在') from exc
        return {'evaluation': evaluation, 'authority': 'RequirementEvaluationV1', 'contract_version': '0.83'}

    def project_active_result_baseline(self, project_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        if not db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        baseline = result_interpretation.active_baseline(project_id)
        return {'baseline': baseline, 'integrity': result_interpretation.baseline_integrity(baseline) if baseline else None, 'authority': 'ProjectBaselineReferenceV1', 'contract_version': '0.81-D'}

    def project_result_baseline_history(self, project_id: str, limit: int=Query(default=20, ge=1, le=100)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        if not db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'baselines': result_interpretation.baseline_history(project_id, limit=limit), 'authority': 'ProjectBaselineReferenceV1', 'contract_version': '0.81-D'}

    def set_project_result_baseline(self, project_id: str, payload: BaselineSetRequest):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
            baseline = result_interpretation.set_baseline(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目或 ResultBundle 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': 'BASELINE_REJECTED', 'message': str(exc)}) from exc
        logs.log(level='INFO', component='result_interpretation', event_type='PROJECT_BASELINE_SET', message='Project engineering baseline updated', payload={'project_id': project_id, 'baseline_id': baseline.get('id'), 'result_bundle_id': baseline.get('result_bundle_id')})
        return {'baseline': baseline, 'integrity': result_interpretation.baseline_integrity(baseline), 'authority': 'ProjectBaselineReferenceV1', 'contract_version': '0.81-D'}

    def result_bundle_comparability_fingerprint(self, result_bundle_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
            fingerprint = result_interpretation.fingerprint(result_bundle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='ResultBundle不存在') from exc
        return {'fingerprint': fingerprint, 'authority': 'ComparabilityFingerprintV1', 'contract_version': '0.81-D'}

    def result_bundle_engineering_interpretation(self, result_bundle_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
            interpretation = result_interpretation.interpret(result_bundle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='ResultBundle不存在') from exc
        return {'interpretation': interpretation, 'authority': 'EngineeringInterpretationV1', 'contract_version': '0.81-D'}

    def result_set_aggregate_compare(self, payload: ResultSetCompareRequest, request: Request, response: Response):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
            aggregate = result_sets.build(payload.result_bundle_ids, baseline_result_bundle_id=payload.baseline_result_bundle_id, scope=payload.scope, objectives=payload.objectives)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={'code': 'RESULT_BUNDLE_NOT_FOUND', 'result_bundle_id': str(exc.args[0])}) from exc
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_SET_MEMBER_LINEAGE_INVALID', 'message': 'At least one ResultBundle failed engineering lineage integrity validation.', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        digest = result_sets.content_hash(aggregate)
        etag = f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Set-Contract': '0.79-B', 'X-MCS-Result-Set-Scope': str(aggregate.get('comparison_scope') or 'general'), 'X-MCS-Result-Set-Gate': str((aggregate.get('comparability') or {}).get('status') or 'REVIEW_ONLY')}
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {'aggregate': aggregate, 'aggregate_hash': digest, 'aggregate_authority': 'ResultSetAggregateV1'}

    def task_result_set_aggregate(self, task_id: str, request: Request, response: Response, case_ids: str=Query(..., min_length=1)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        ids = [item.strip() for item in case_ids.split(',') if item.strip()]
        if len(ids) < 2 or len(ids) > 8 or len(set(ids)) != len(ids):
            raise HTTPException(status_code=422, detail='同一 Task ResultSet Aggregate 必须选择 2–8 个互不重复的 Case')
        if not db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        placeholders = ','.join(('?' for _ in ids))
        rows = db.query_all(f'SELECT id,task_id,result_bundle_id FROM cases WHERE id IN ({placeholders})', tuple(ids))
        by_id = {str(row['id']): row for row in rows}
        for case_id in ids:
            row = by_id.get(case_id)
            if row is None:
                raise HTTPException(status_code=404, detail={'code': 'CASE_NOT_FOUND', 'case_id': case_id})
            if str(row.get('task_id') or '') != task_id:
                raise HTTPException(status_code=422, detail={'code': 'CASE_COMPARISON_TASK_MISMATCH', 'case_id': case_id, 'task_id': task_id})
            if not row.get('result_bundle_id'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_BUNDLE_REQUIRED', 'case_id': case_id, 'message': 'V0.79-B canonical comparison requires immutable ResultBundle evidence.'})
        bundle_ids = [str(by_id[case_id]['result_bundle_id']) for case_id in ids]
        try:
            result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
            aggregate = result_sets.build(bundle_ids, scope='same_task')
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_SET_MEMBER_LINEAGE_INVALID', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        digest = result_sets.content_hash(aggregate)
        etag = f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Set-Contract': '0.79-B', 'X-MCS-Result-Set-Scope': 'same_task', 'X-MCS-Result-Set-Gate': str((aggregate.get('comparability') or {}).get('status') or 'REVIEW_ONLY')}
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {'aggregate': aggregate, 'aggregate_hash': digest, 'aggregate_authority': 'ResultSetAggregateV1'}

    def result_bundle_aggregate(self, result_bundle_id: str, request: Request, response: Response, include: str | None=Query(default=None, description='Optional sections: inputs,datasets,evidence,stages,viewer; use all for every section.')):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        try:
            result_aggregates.native_qualification_resolver = result_viewer.native_qualification_resolver
            aggregate = result_aggregates.build(result_bundle_id, include=include)
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_BUNDLE_LINEAGE_INVALID', 'message': 'ResultBundle engineering lineage failed integrity validation.', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        if aggregate is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        digest = result_aggregates.content_hash(aggregate)
        etag = f'"{digest}"'
        response.headers['ETag'] = etag
        response.headers['Cache-Control'] = 'private, no-cache, must-revalidate'
        response.headers['X-MCS-Result-Aggregate-Contract'] = '0.79-A'
        response.headers['X-MCS-Result-Aggregate-Includes'] = ','.join(aggregate.get('included_sections') or []) or 'summary'
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers={'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Aggregate-Contract': '0.79-A', 'X-MCS-Result-Aggregate-Includes': ','.join(aggregate.get('included_sections') or []) or 'summary'})
        return {'aggregate': aggregate, 'aggregate_hash': digest, 'aggregate_authority': 'ResultBundleAggregateV1'}

    def result_bundle_item(self, result_bundle_id: str, result_id: str, request: Request, response: Response, offset: int | None=Query(default=None, ge=0), limit: int | None=Query(default=None, ge=0, le=100000), metadata_only: bool=Query(default=False)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        thin_bundle = tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
        if thin_bundle is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        thin_item = thin_bundle.by_id().get(result_id)
        if thin_item is None:
            raise HTTPException(status_code=404, detail='Result不存在')
        conditional_etag = None
        if thin_item.data_ref is not None:
            conditional_etag = f'''"{result_aggregates.content_hash({'contract': '0.80-A', 'resource': 'result-item', 'bundle_hash': thin_bundle.content_hash(), 'result_id': result_id, 'content_hash': thin_item.data_ref.content_hash, 'offset': offset, 'limit': limit, 'metadata_only': bool(metadata_only)})}"'''
            if self._etag_matches(request.headers.get('if-none-match'), conditional_etag) and (metadata_only or tasks.result_bundles.data_gateway.available_window(thin_item.data_ref.content_hash, offset=int(offset or 0), limit=limit)):
                return Response(status_code=304, headers={'ETag': conditional_etag, 'Cache-Control': 'private, max-age=31536000, immutable', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Results-Application-Contract': '1'})
        try:
            resolved = tasks.result_bundles.result_payload(result_bundle_id, result_id, offset=offset, limit=limit, metadata_only=metadata_only)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'message': str(exc)}) from exc
        if resolved is None:
            raise HTTPException(status_code=404, detail='Result不存在')
        bundle, item, data, window = resolved
        result_payload = item.model_dump(mode='json')
        if item.result_type != 'scalar' and (not metadata_only):
            result_payload['data'] = data
        access = {'authority': 'ResultDataGatewayV2' if item.data_ref is not None else 'ResultBundleInlineV1', 'externalized': bool(item.data_ref is not None), 'metadata_only': bool(metadata_only), 'window': window, 'data_href': f'/api/result-bundles/{result_bundle_id}/results/{result_id}/data' if item.data_ref is not None else None}
        payload = {'result_bundle_id': result_bundle_id, 'result_bundle_hash': bundle.content_hash(), 'result': result_payload, 'data_access': access, 'result_authority': 'ResultBundleV1'}
        digest = result_aggregates.content_hash(payload)
        etag = conditional_etag or f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=31536000, immutable', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Results-Application-Contract': '1'}
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return payload

    def result_bundle_item_data(self, result_bundle_id: str, result_id: str, request: Request, response: Response, offset: int=Query(default=0, ge=0), limit: int | None=Query(default=None, ge=0, le=100000)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        thin_bundle = tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
        if thin_bundle is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        thin_item = thin_bundle.by_id().get(result_id)
        if thin_item is None:
            raise HTTPException(status_code=404, detail='Result不存在')
        if thin_item.result_type == 'scalar':
            raise HTTPException(status_code=422, detail='Scalar Result 不需要 Heavy Result Data Gateway')
        conditional_etag = None
        if thin_item.data_ref is not None:
            conditional_etag = f'''"{result_aggregates.content_hash({'contract': '0.80-A', 'resource': 'result-data', 'bundle_hash': thin_bundle.content_hash(), 'result_id': result_id, 'content_hash': thin_item.data_ref.content_hash, 'offset': int(offset or 0), 'limit': limit})}"'''
            headers = {'ETag': conditional_etag, 'Cache-Control': 'private, max-age=31536000, immutable', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Results-Application-Contract': '1'}
            if self._etag_matches(request.headers.get('if-none-match'), conditional_etag) and tasks.result_bundles.data_gateway.available_window(thin_item.data_ref.content_hash, offset=int(offset or 0), limit=limit):
                return Response(status_code=304, headers=headers)
        try:
            resolved = tasks.result_bundles.result_payload(result_bundle_id, result_id, offset=offset, limit=limit, metadata_only=False)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'message': str(exc)}) from exc
        if resolved is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        bundle, item, data, window = resolved
        payload = {'result_bundle_id': result_bundle_id, 'result_bundle_hash': bundle.content_hash(), 'result_id': result_id, 'result_type': item.result_type, 'unit': item.unit, 'data_ref': item.data_ref.model_dump(mode='json') if item.data_ref is not None else None, 'data': data, 'window': window, 'data_authority': 'ResultDataGatewayV2' if item.data_ref is not None else 'ResultBundleInlineV1'}
        digest = result_aggregates.content_hash(payload)
        etag = conditional_etag or f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=31536000, immutable', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Results-Application-Contract': '1'}
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return payload

    def result_bundle_item_data_manifest(self, result_bundle_id: str, result_id: str, request: Request, response: Response):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        item = tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
        if item is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        if item.data_ref is None:
            return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': False, 'chunk_native': False, 'layout': 'inline'}
        try:
            manifest = tasks.result_bundles.data_gateway.manifest_info(item.data_ref.content_hash)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'message': str(exc)}) from exc
        etag = f'''"{result_aggregates.content_hash({'contract': '0.80-A', 'resource': 'result-data-manifest', 'content_hash': item.data_ref.content_hash, 'manifest': manifest})}"'''
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=31536000, immutable', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Results-Application-Contract': '1'}
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': True, 'manifest': manifest}

    def result_bundle_item_data_chunk(self, result_bundle_id: str, result_id: str, chunk_index: int, request: Request, response: Response):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        item = tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
        if item is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        if item.data_ref is None or not bool(getattr(item.data_ref, 'random_access', False)):
            raise HTTPException(status_code=422, detail='该 ResultData 不是 chunk-native 对象')
        try:
            descriptor = tasks.result_bundles.data_gateway.chunk_descriptor(item.data_ref.content_hash, chunk_index)
        except IndexError as exc:
            raise HTTPException(status_code=404, detail='ResultData chunk不存在') from exc
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'chunk_index': chunk_index, 'message': str(exc)}) from exc
        etag = f'''"{descriptor['chunk_hash']}"'''
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=31536000, immutable', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Results-Application-Contract': '1', 'X-MCS-Result-Data-Chunk': str(chunk_index)}
        if self._etag_matches(request.headers.get('if-none-match'), etag) and tasks.result_bundles.data_gateway.available_chunk(item.data_ref.content_hash, chunk_index):
            return Response(status_code=304, headers=headers)
        try:
            data, safe_descriptor = tasks.result_bundles.data_gateway.read_chunk_index(item.data_ref.content_hash, chunk_index)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError, IndexError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'chunk_index': chunk_index, 'message': str(exc)}) from exc
        response.headers.update(headers)
        return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'content_hash': item.data_ref.content_hash, 'chunk': safe_descriptor, 'data': data, 'data_authority': 'ResultDataGatewayV2'}

    def result_bundle_item_integrity(self, result_bundle_id: str, result_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        item = tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
        if item is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        if item.data_ref is None:
            return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': False, 'valid': True, 'status': 'INLINE'}
        return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': True, **tasks.result_bundles.data_gateway.verify(item.data_ref.content_hash)}

    def result_data_gateway_status(self):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        return tasks.result_bundles.data_gateway.status()

    def result_data_gateway_gc(self, dry_run: bool=Query(default=True)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        return tasks.result_bundles.data_gateway.garbage_collect(dry_run=dry_run)

    def result_bundle_by_id(self, result_bundle_id: str, include_data: bool=Query(default=False)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        bundle = tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=include_data)
        if bundle is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        return {'id': result_bundle_id, 'case_id': bundle.provenance.case_id, 'result_bundle': bundle.model_dump(mode='json'), 'result_bundle_hash': bundle.content_hash(), 'heavy_data_hydrated': bool(include_data), 'result_data_gateway': 'ResultDataGatewayV2'}

    def case_thermal_network(self, case_id: str):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        payload = result_viewer.case_payload(case_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='Case不存在')
        return {'case_id': case_id, **((payload.get('evidence') or {}).get('thermal_network') or {})}

    def engineering_result_semantics(self, template_id: str | None=Query(default=None)):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        schema = registry.output_schema(template_id)
        return {'authority': 'EngineeringSemanticRegistryV1', 'contract_version': '0.87-C', 'template_id': template_id, 'count': len(schema), 'metrics': schema}

    def capture_baseline_api(self, case_id: str, payload: BaselineCaptureRequest):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        output = settings.baselines_dir / f'{case_id}.json'
        try:
            path = tasks.capture_case_baseline(case_id, output, notes=payload.notes, allow_unverified=payload.allow_unverified)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Case不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {'path': str(path)}

    def compare_baseline_api(self, case_id: str, payload: BaselineCompareRequest):
        settings = self.settings
        db = self.db
        logs = self.logs
        registry = self.registry
        templates = self.templates
        calibration = self.calibration
        result_viewer = self.result_viewer
        result_aggregates = self.result_aggregates
        result_sets = self.result_sets
        engineering_requirements = self.engineering_requirements
        result_interpretation = self.result_interpretation
        results_optimization = self.results_optimization
        tasks = self.tasks
        engineering_lineage = self.engineering_lineage
        native_closure_profiles = self.native_closure_profiles
        native_closure_registry = self.native_closure_registry
        motor_domain = self.motor_domain
        motorcad_binding_planner = self.motorcad_binding_planner
        _deep_preflight_payload = self.system_service.deep_preflight_payload
        _native_closure_expected_scopes = self._native_closure_expected_scopes
        _native_closure_matrix = self._native_closure_matrix
        _lineage_etag_matches = self._lineage_etag_matches
        _resolve_engineering_lineage_http = self._resolve_engineering_lineage_http
        baseline = Path(payload.baseline_path).resolve()
        baseline_root = settings.baselines_dir.resolve()
        if baseline_root not in baseline.parents and baseline != baseline_root:
            raise HTTPException(status_code=403, detail='基准文件必须位于data/baselines目录')
        if not baseline.exists():
            raise HTTPException(status_code=404, detail='基准文件不存在')
        case = tasks.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail='Case不存在')
        task_id = (db.query_one('SELECT task_id FROM cases WHERE id=?', (case_id,)) or {}).get('task_id')
        output = settings.results_dir / str(task_id) / case_id / 'baseline_comparison.html'
        try:
            return tasks.compare_case_baseline(case_id, baseline, output, payload.tolerances)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Case不存在') from exc


    OPERATIONS = frozenset({
        "result_calibration_entries", "result_calibration_recommended", "probe_result_calibration",
        "project_results_workbench", "get_result_bundle_engineering_lineage",
        "result_viewer_catalog", "result_viewer_compare", "task_result_comparison",
        "case_result_viewer", "case_result_trust", "case_result_bundle",
        "result_bundle_aggregate_query", "result_bundle_requirement_evaluation",
        "project_active_result_baseline", "project_result_baseline_history",
        "set_project_result_baseline", "result_bundle_comparability_fingerprint",
        "result_bundle_engineering_interpretation", "result_set_aggregate_compare",
        "task_result_set_aggregate", "result_bundle_aggregate", "result_bundle_item",
        "result_bundle_item_data", "result_bundle_item_data_manifest",
        "result_bundle_item_data_chunk", "result_bundle_item_integrity",
        "result_data_gateway_status", "result_data_gateway_gc", "result_bundle_by_id",
        "case_thermal_network", "engineering_result_semantics", "capture_baseline_api",
        "compare_baseline_api", "result_data_descriptor",
    })

    def operation(self, name: str):
        if name not in self.OPERATIONS:
            raise KeyError(f"Unknown Results operation: {name}")
        target = getattr(self, name, None)
        if not callable(target):
            raise RuntimeError(f"Results operation is not callable: {name}")
        return target

    def module_snapshot(self) -> dict[str, Any]:
        gateway = self.tasks.result_bundles.data_gateway
        return {
            "authority": "ResultsCompatibilityAdapterV1",
            "operation_count": len(self.OPERATIONS),
            "result_bundle_authority": "ResultBundleV1",
            "result_data_gateway": gateway.status(),
            "immutable_identity": "sha256-canonical-json",
            "random_access_native": True,
        }

    @staticmethod
    def _etag_matches(header: str | None, etag: str) -> bool:
        if not header:
            return False
        target = etag.strip('"')
        for token in header.split(','):
            candidate = token.strip()
            if candidate.startswith('W/'):
                candidate = candidate[2:].strip()
            if candidate == '*' or candidate.strip('"') == target:
                return True
        return False

    def result_data_descriptor(
        self,
        result_bundle_id: str,
        result_id: str,
        request: Request,
        response: Response,
    ):
        item = self.tasks.result_bundles.result_by_id(
            result_bundle_id, result_id, hydrate_heavy=False
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Result或ResultBundle不存在")
        data_ref = item.data_ref
        if data_ref is None:
            identity = self.result_aggregates.content_hash({
                "bundle": result_bundle_id,
                "result": result_id,
                "inline": item.model_dump(mode="json"),
            })
            etag = f'"{identity}"'
            manifest = None
            layout = "inline"
            chunk_native = False
            content_hash = None
            item_count = None
            chunk_count = 0
        else:
            content_hash = data_ref.content_hash
            manifest = self.tasks.result_bundles.data_gateway.manifest_info(content_hash)
            identity = self.result_aggregates.content_hash({
                "contract": "ResultDataDescriptorV1",
                "bundle": result_bundle_id,
                "result": result_id,
                "content_hash": content_hash,
                "manifest_hash": manifest.get("manifest_hash"),
            })
            etag = f'"{identity}"'
            layout = str(manifest.get("layout") or data_ref.layout or "external")
            chunk_native = bool(manifest.get("chunk_native"))
            item_count = manifest.get("item_count")
            chunk_count = int(manifest.get("chunk_count") or 0)
        headers = {
            "ETag": etag,
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-MCS-Result-Data-Contract": "1",
        }
        if self._etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {
            "authority": "ResultDataDescriptorV1",
            "result_bundle_id": result_bundle_id,
            "result_id": result_id,
            "result_type": item.result_type,
            "unit": item.unit,
            "externalized": data_ref is not None,
            "content_hash": content_hash,
            "etag": etag,
            "layout": layout,
            "chunk_native": chunk_native,
            "item_count": item_count,
            "chunk_count": chunk_count,
            "max_window_items": 100000 if data_ref is not None else None,
            "range_requests": bool(data_ref is not None),
            "manifest_url": (
                f"/api/result-bundles/{result_bundle_id}/results/{result_id}/data/manifest"
                if data_ref is not None else None
            ),
            "data_url": f"/api/result-bundles/{result_bundle_id}/results/{result_id}/data",
            "integrity_url": f"/api/result-bundles/{result_bundle_id}/results/{result_id}/integrity",
            "metadata": {
                "data_ref": data_ref.model_dump(mode="json") if data_ref is not None else None,
                "manifest": manifest,
            },
        }


__all__ = ["ResultsCompatibilityAdapter"]
