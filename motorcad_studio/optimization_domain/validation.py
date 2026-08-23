from __future__ import annotations

import uuid
from typing import Any, Callable

from ..analysis_domain.contracts import stable_hash
from ..geometry_guard import validate_geometry_relations
from ..models import ExperimentDefinition, ScenarioDefinition, TaskCreate
from ..result_domain import ResultTrustService
from ..validation import validate_parameters
from ..winding_guard import validate_winding_relations
from .contracts import (
    CandidateCriticalPoint,
    CandidateValidationLevel,
    CandidateValidationReport,
    CandidateResultSet,
    MotorOptimizationSpace,
    MotorPatch,
    RobustCandidateEvaluation,
)


class CandidateValidationService:
    """V0.74-D authority for candidate validation and promotion eligibility.

    It does not introduce a new solver. L1 validates the candidate design contract;
    L2-L4 consume the existing ResultTrustSnapshot produced by a dedicated critical-
    point re-execution task. Promotion policy is environment-scoped.
    """

    def __init__(self, db, workspace, motor_domain, registry, templates, result_bundles, *, model_policy: str = 'development'):
        self.db = db
        self.workspace = workspace
        self.motor_domain = motor_domain
        self.registry = registry
        self.templates = templates
        self.result_trust = ResultTrustService(db, result_bundles)
        policy = str(model_policy or 'development').lower()
        self.model_policy = policy if policy in {'development','validation','production'} else 'development'
        self.native_qualification_resolver: Callable[[str, str], dict[str, Any] | None] | None = None
        self.optimization_result_authority = None
        self.decision_snapshot_resolver: Callable[[str], dict[str, Any] | None] | None = None

    @staticmethod
    def _level(level: int, level_id: str, label: str, status: str, *, satisfied: bool, blocking: bool, authority: str, message: str, evidence: dict[str, Any] | None = None) -> CandidateValidationLevel:
        return CandidateValidationLevel(level=level, id=level_id, label=label, status=status, satisfied=satisfied, blocking=blocking, authority=authority, message=message, evidence=evidence or {})

    def _candidate_context(self, source_case_id: str) -> dict[str, Any]:
        case = self.db.query_one("SELECT * FROM cases WHERE id=?", (source_case_id,))
        if not case:
            raise KeyError(source_case_id)
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (case.get('task_id'),)) or {}
        if not task:
            raise KeyError(str(case.get('task_id') or ''))
        exp = self.db.query_one("SELECT * FROM experiments WHERE task_id=?", (task.get('id'),)) or {}
        patch_payload = self.db.loads(case.get('motor_patch_json'), {}) or {}
        if not patch_payload:
            raise ValueError('CANDIDATE_MOTOR_PATCH_MISSING')
        patch = MotorPatch.model_validate(patch_payload)
        candidate_id = str(case.get('candidate_id') or '')
        if not candidate_id:
            raise ValueError('CANDIDATE_ID_MISSING')
        space_payload = self.db.loads(exp.get('optimization_space_json'), {}) or {}
        if not space_payload:
            raise ValueError('OPTIMIZATION_SPACE_MISSING')
        space = MotorOptimizationSpace.model_validate(space_payload)
        candidate_row = self.db.query_one("SELECT * FROM candidate_result_sets WHERE task_id=? AND candidate_id=?", (task.get('id'), candidate_id)) or {}
        candidate_set = CandidateResultSet.model_validate(self.db.loads(candidate_row.get('result_set_json'), {})) if candidate_row.get('result_set_json') else None
        robust_row = self.db.query_one("SELECT * FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?", (task.get('id'), candidate_id)) or {}
        robust = RobustCandidateEvaluation.model_validate(self.db.loads(robust_row.get('evaluation_json'), {})) if robust_row.get('evaluation_json') else None
        request = self.db.loads(task.get('request_json'), {}) or {}
        return {'case': case, 'task': task, 'experiment': exp, 'patch': patch, 'space': space, 'candidate_set': candidate_set, 'robust': robust, 'request': request}

    def _l1(self, context: dict[str, Any]) -> tuple[CandidateValidationLevel, dict[str, Any]]:
        patch: MotorPatch = context['patch']; space: MotorOptimizationSpace = context['space']; task=context['task']
        base = self.workspace.get_design_revision(patch.baseline_design_revision_id)
        if not base:
            return self._level(1,'L1','Domain Validation','FAIL',satisfied=False,blocking=True,authority='MotorSnapshot + MotorPatch',message='候选基准 Design Revision 已不存在。'), {}
        design = self.workspace.get_design(str(base.get('design_id') or '')) or {}
        payload = dict(base.get('motor_snapshot') or {})
        snapshot = self.motor_domain.model_from_snapshot(payload).snapshot if hasattr(self.motor_domain, 'model_from_snapshot') else None
        if snapshot is None:
            from ..motor_domain import MotorSnapshot
            snapshot = MotorSnapshot.model_validate(payload) if payload else self.motor_domain.build_snapshot(design, base)
        base_hash = snapshot.content_hash()
        allowed = space.variable_map()
        issues: list[dict[str, Any]] = []
        if patch.baseline_motor_snapshot_hash != base_hash:
            issues.append({'code':'BASELINE_MOTOR_SNAPSHOT_STALE','severity':'BLOCKING','message':'MotorPatch 基准 MotorSnapshot hash 已变化。'})
        if patch.optimization_space_hash != space.content_hash():
            issues.append({'code':'OPTIMIZATION_SPACE_STALE','severity':'BLOCKING','message':'MotorPatch 与冻结 MotorOptimizationSpace 不一致。'})
        for change in patch.changes:
            spec = allowed.get(change.parameter_id)
            if spec is None or spec.owner in {'scenario','advanced'}:
                issues.append({'code':'PATCH_NOT_DESIGN_OWNED','severity':'BLOCKING','message':f'{change.parameter_id} 不是当前 Design-owned 优化变量。'})
                continue
            try:
                value=float(change.after)
                if spec.minimum is not None and value < float(spec.minimum): issues.append({'code':'PATCH_BELOW_MIN','severity':'BLOCKING','message':f'{change.parameter_id} 低于允许下限。'})
                if spec.maximum is not None and value > float(spec.maximum): issues.append({'code':'PATCH_ABOVE_MAX','severity':'BLOCKING','message':f'{change.parameter_id} 高于允许上限。'})
            except (TypeError,ValueError):
                issues.append({'code':'PATCH_VALUE_INVALID','severity':'BLOCKING','message':f'{change.parameter_id} 候选值无效。'})
        model = self.motor_domain.model(snapshot)
        candidate_model, _ = model.with_parameter_patch(patch.values(), explicit_parameter_ids=[row.parameter_id for row in patch.changes])
        candidate = candidate_model.snapshot
        template = self.templates.get_template(candidate.identity.template_id)
        schema = self.registry.parameter_schema(candidate.identity.template_id)
        parameters = dict(candidate.parameters.values)
        explicit_ids = sorted(set((base.get('explicit_parameter_ids') or []) + [row.parameter_id for row in patch.changes]))
        issues.extend(validate_parameters(parameters, schema))
        issues.extend(validate_geometry_relations(parameters, template, explicit_ids).get('issues', []))
        issues.extend(validate_winding_relations(parameters, template, explicit_ids).get('issues', []))
        blocking=[row for row in issues if str(row.get('severity') or '').upper()=='BLOCKING']
        ok=not blocking and bool(patch.changes)
        level=self._level(1,'L1','Domain Validation','PASS' if ok else 'FAIL',satisfied=ok,blocking=not ok,authority='MotorSnapshot v2 + MotorOptimizationSpace + MotorPatch',message='候选 MotorPatch 可生成满足当前领域合同的 MotorSnapshot。' if ok else '候选设计未通过领域一致性验证。',evidence={'baseline_motor_snapshot_hash':base_hash,'candidate_motor_snapshot_hash':candidate.content_hash(),'motor_patch_hash':patch.content_hash(),'optimization_space_hash':space.content_hash(),'blocking_issues':blocking[:50]})
        return level, {'candidate_snapshot':candidate,'base_revision':base,'design':design,'parameters':parameters,'explicit_parameter_ids':explicit_ids}

    @staticmethod
    def _critical_points(candidate_set: CandidateResultSet | None, limit: int) -> list[CandidateCriticalPoint]:
        if candidate_set is None:
            return []
        by_op={row.operating_point_id:row for row in candidate_set.point_results}
        reasons: dict[str,list[str]] = {}
        for constraint in candidate_set.constraints:
            for op_id, feasible in constraint.point_feasible.items():
                if feasible is False:
                    reasons.setdefault(op_id,[]).append(f'constraint:{constraint.field}')
        for objective in candidate_set.objectives:
            if not objective.point_values: continue
            items=list(objective.point_values.items())
            if objective.direction=='max': op_id,_=min(items,key=lambda item:item[1])
            else: op_id,_=max(items,key=lambda item:item[1])
            reasons.setdefault(op_id,[]).append(f'worst_objective:{objective.result_id}')
        if candidate_set.representative_case_id:
            rep=next((row.operating_point_id for row in candidate_set.point_results if row.case_id==candidate_set.representative_case_id),None)
            if rep: reasons.setdefault(rep,[]).append('representative')
        if not reasons:
            for row in candidate_set.point_results[:1]: reasons.setdefault(row.operating_point_id,[]).append('representative')
        ordered=sorted(reasons.items(),key=lambda item:(0 if any(token.startswith('constraint:') for token in item[1]) else 1,item[0]))[:max(1,limit)]
        return [CandidateCriticalPoint(source_case_id=by_op[op_id].case_id,operating_point_id=op_id,reason=', '.join(reason),source_result_bundle_hash=by_op[op_id].result_bundle_hash) for op_id,reason in ordered if op_id in by_op]

    def prepare(self, source_case_id: str, *, critical_point_count: int = 3) -> tuple[CandidateValidationReport, dict[str, Any]]:
        context=self._candidate_context(source_case_id)
        l1, materialized=self._l1(context)
        critical=self._critical_points(context.get('candidate_set'), critical_point_count)
        if not critical:
            critical=[CandidateCriticalPoint(source_case_id=source_case_id,operating_point_id=context['case'].get('operating_point_id'),reason='source_candidate')]
        robust=context.get('robust')
        candidate_set=context.get('candidate_set')
        authority_snapshot=(candidate_set.result_authority if candidate_set is not None else None)
        authority_ready=bool(authority_snapshot is not None and authority_snapshot.integrity_valid and candidate_set.result_authority_hash==authority_snapshot.content_hash())
        candidate_ready=bool(candidate_set is not None and candidate_set.complete and candidate_set.feasible and authority_ready)
        robust_required=robust is not None
        robust_authority_ready=bool(robust is not None and robust.result_authority_closure_hash and robust.sample_result_authority_hashes) if robust_required else True
        robust_feasible=(bool(robust.robust_feasible and robust_authority_ready) if robust is not None else None)
        decision_snapshot=None
        if self.decision_snapshot_resolver is not None:
            try:
                decision_snapshot=self.decision_snapshot_resolver(str(context['task']['id']))
            except Exception:
                decision_snapshot=None
        decision_hash=(decision_snapshot or {}).get('content_hash') or (decision_snapshot or {}).get('optimization_decision_snapshot_hash')
        report=CandidateValidationReport(
            report_id=f'CVR-{uuid.uuid4().hex[:10].upper()}', task_id=str(context['task']['id']), candidate_id=str(context['case']['candidate_id']), source_case_id=source_case_id,
            baseline_design_revision_id=context['patch'].baseline_design_revision_id, motor_patch_hash=context['patch'].content_hash(),
            candidate_result_set_hash=candidate_set.content_hash() if candidate_set is not None else None,
            result_authority_hash=candidate_set.result_authority_hash if candidate_set is not None else None,
            robust_candidate_evaluation_hash=robust.content_hash() if robust is not None else None,
            robust_result_authority_closure_hash=robust.result_authority_closure_hash if robust is not None else None,
            optimization_decision_snapshot_hash=decision_hash, policy=self.model_policy,
            critical_points=critical, levels=[l1,
                self._level(2,'L2','Native Validation','PENDING',satisfied=False,blocking=self.model_policy!='development',authority='ResultTrustSnapshot L2',message='等待关键工况再验证任务形成 Native readback 证据。'),
                self._level(3,'L3','Critical-point Re-execution','PENDING',satisfied=False,blocking=True,authority='ExecutionPlan v2',message='等待冻结关键工况重新计算。'),
                self._level(4,'L4','Result Qualification','PENDING',satisfied=False,blocking=self.model_policy!='development',authority='ResultBundle v1 + Native Closure',message='等待关键工况 ResultBundle 与资格证据。')],
            robustness_required=robust_required, robustness_feasible=robust_feasible,
            status='BLOCKED' if (not l1.satisfied or not candidate_ready or (robust_required and not robust_feasible)) else 'PENDING_REEXECUTION', promotion_allowed=False, formal_validation=False,
            metadata={
                'robust_candidate_evaluation_hash':robust.content_hash() if robust is not None else None,
                'candidate_result_set_hash':candidate_set.content_hash() if candidate_set is not None else None,
                'result_authority_hash':candidate_set.result_authority_hash if candidate_set is not None else None,
                'result_authority_integrity_valid':authority_ready,
                'robust_result_authority_closure_hash':robust.result_authority_closure_hash if robust is not None else None,
                'robust_result_authority_ready':robust_authority_ready,
                'optimization_decision_snapshot_hash':decision_hash,
                'candidate_result_ready':candidate_ready,
            },
        )
        return report, {**context, **materialized}

    def refresh(self, report: CandidateValidationReport) -> CandidateValidationReport:
        report.policy=self.model_policy
        source_case=self.db.query_one("SELECT motor_patch_json FROM cases WHERE id=?",(report.source_case_id,)) or {}
        source_patch=self.db.loads(source_case.get('motor_patch_json'),{}) or {}
        source_patch_hash=MotorPatch.model_validate(source_patch).content_hash() if source_patch else None
        current_candidate=self.db.query_one("SELECT content_hash,result_set_json FROM candidate_result_sets WHERE task_id=? AND candidate_id=?",(report.task_id,report.candidate_id)) or {}
        current_robust=self.db.query_one("SELECT content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?",(report.task_id,report.candidate_id)) or {}
        candidate_payload=self.db.loads(current_candidate.get('result_set_json'),{}) or {}
        current_candidate_set=CandidateResultSet.model_validate(candidate_payload) if candidate_payload else None
        robust_payload=self.db.loads(current_robust.get('evaluation_json'),{}) or {}
        current_robust_eval=RobustCandidateEvaluation.model_validate(robust_payload) if robust_payload else None
        stale_reasons=[]
        if current_candidate_set is not None and current_candidate.get('content_hash') and current_candidate_set.content_hash() != current_candidate.get('content_hash'):
            stale_reasons.append('candidate_result_set:persisted_hash_mismatch')
        if current_robust_eval is not None and current_robust.get('content_hash') and current_robust_eval.content_hash() != current_robust.get('content_hash'):
            stale_reasons.append('robust_candidate_evaluation:persisted_hash_mismatch')
        if current_robust_eval is not None and current_robust_eval.result_authority_closure_hash and current_robust_eval.computed_result_authority_closure_hash() != current_robust_eval.result_authority_closure_hash:
            stale_reasons.append('robust_result_authority:closure_hash_mismatch')
        if source_patch_hash != report.motor_patch_hash: stale_reasons.append('motor_patch')
        expected_candidate_hash=report.candidate_result_set_hash or report.metadata.get('candidate_result_set_hash')
        if expected_candidate_hash and current_candidate.get('content_hash') != expected_candidate_hash: stale_reasons.append('candidate_result_set')
        expected_authority_hash=report.result_authority_hash or report.metadata.get('result_authority_hash')
        if expected_authority_hash and (current_candidate_set is None or current_candidate_set.result_authority_hash != expected_authority_hash): stale_reasons.append('result_authority')
        if current_candidate_set is not None and current_candidate_set.result_authority is not None and self.optimization_result_authority is not None:
            self.optimization_result_authority.native_qualification_resolver=self.native_qualification_resolver
            authority_issues=self.optimization_result_authority.verify_candidate(current_candidate_set)
            if authority_issues:
                stale_reasons.extend([f'result_authority:{item}' for item in authority_issues])
        elif expected_authority_hash:
            stale_reasons.append('result_authority_missing')
        expected_robust_hash=report.robust_candidate_evaluation_hash or report.metadata.get('robust_candidate_evaluation_hash')
        if expected_robust_hash and current_robust.get('content_hash') != expected_robust_hash: stale_reasons.append('robust_candidate_evaluation')
        expected_robust_authority=report.robust_result_authority_closure_hash or report.metadata.get('robust_result_authority_closure_hash')
        if expected_robust_authority and (current_robust_eval is None or current_robust_eval.result_authority_closure_hash != expected_robust_authority): stale_reasons.append('robust_result_authority')
        if current_robust_eval is not None and self.optimization_result_authority is not None:
            for sample in current_robust_eval.sample_results:
                if sample.result_authority is None:
                    stale_reasons.append(f'robust_result_authority_missing:{sample.sample_id}')
                    continue
                if sample.result_authority_hash and sample.result_authority.content_hash() != sample.result_authority_hash:
                    stale_reasons.append(f'robust_result_authority:{sample.sample_id}:snapshot_hash_mismatch')
                sample_issues=self.optimization_result_authority.verify_snapshot(sample.result_authority)
                sample_issues.extend(self.optimization_result_authority.verify_metric_outputs(sample.result_authority, sample.objectives, sample.constraints))
                stale_reasons.extend([f'robust_result_authority:{sample.sample_id}:{item}' for item in sample_issues])
        if report.optimization_decision_snapshot_hash and self.decision_snapshot_resolver is not None:
            try:
                current_decision=self.decision_snapshot_resolver(report.task_id) or {}
                current_decision_hash=current_decision.get('content_hash') or current_decision.get('optimization_decision_snapshot_hash')
            except Exception:
                current_decision_hash=None
            if current_decision_hash != report.optimization_decision_snapshot_hash:
                stale_reasons.append('optimization_decision_snapshot')
        if stale_reasons:
            report.status='BLOCKED'; report.promotion_allowed=False; report.formal_validation=False
            report.metadata['source_evidence_stale']=stale_reasons
            by=report.by_id(); l1=by.get('L1')
            if l1 is not None:
                l1.status='FAIL'; l1.satisfied=False; l1.blocking=True; l1.message='候选验证依赖的 MotorPatch/候选结果事实已经变化，必须重新验证。'; l1.evidence['stale_sources']=stale_reasons
                report.levels=[by[key] for key in ('L1','L2','L3','L4') if key in by]
            return report
        if not report.validation_task_id:
            return report
        task=self.db.query_one("SELECT * FROM tasks WHERE id=?",(report.validation_task_id,)) or {}
        cases=self.db.query_all("SELECT id,execution_status FROM cases WHERE task_id=? ORDER BY case_index",(report.validation_task_id,))
        report.validation_case_ids=[str(row['id']) for row in cases]
        terminal=str(task.get('status') or '') in {'COMPLETED','PARTIALLY_COMPLETED','FAILED','CANCELLED'}
        if not terminal:
            report.status='RUNNING'; return report
        trusts=[]
        self.result_trust.native_qualification_resolver=self.native_qualification_resolver
        for row in cases:
            trust=self.result_trust.evaluate_case(str(row['id']))
            if trust is not None: trusts.append(trust)
        def all_level(level_id: str, *, allow_na: bool=False) -> tuple[bool,list[dict[str,Any]]]:
            evidence=[]; ok=bool(trusts)
            for trust in trusts:
                level=trust.by_id().get(level_id)
                if level is None: ok=False; continue
                accepted=(allow_na if level.status=='NOT_APPLICABLE' else bool(level.satisfied))
                ok=ok and accepted
                evidence.append({'case_id':trust.case_id,'status':level.status,'satisfied':level.satisfied,'authority':level.authority})
            return ok,evidence
        l2_ok,l2_evidence=all_level('native_model',allow_na=self.model_policy=='development')
        l3_ok,l3_evidence=all_level('execution')
        l4_ok,l4_evidence=all_level('result')
        by=report.by_id()
        by['L2'].status='PASS' if l2_ok else ('NOT_APPLICABLE' if self.model_policy=='development' and trusts and all(t.solver_mode!='motorcad' for t in trusts) else 'FAIL'); by['L2'].satisfied=l2_ok; by['L2'].blocking=not l2_ok and self.model_policy!='development'; by['L2'].evidence={'cases':l2_evidence}
        by['L3'].status='PASS' if l3_ok else 'FAIL'; by['L3'].satisfied=l3_ok; by['L3'].blocking=not l3_ok; by['L3'].evidence={'cases':l3_evidence,'validation_task_id':report.validation_task_id}
        by['L4'].status='PASS' if l4_ok else ('UNQUALIFIED' if trusts else 'FAIL'); by['L4'].satisfied=l4_ok; by['L4'].blocking=not l4_ok and self.model_policy!='development'; by['L4'].evidence={'cases':l4_evidence}
        formal=bool(trusts) and all(t.formal_recommendation for t in trusts)
        l1_ok=by['L1'].satisfied
        candidate_ready=bool(current_candidate_set is not None and current_candidate_set.complete and current_candidate_set.feasible and current_candidate_set.result_authority is not None and current_candidate_set.result_authority.integrity_valid and current_candidate_set.result_authority_hash==current_candidate_set.result_authority.content_hash())
        report.metadata['candidate_result_ready']=candidate_ready
        robust_ok=(not report.robustness_required) or bool(report.robustness_feasible and current_robust_eval is not None and current_robust_eval.result_authority_closure_hash)
        if self.model_policy=='development':
            allowed=l1_ok and candidate_ready and l3_ok and l4_ok and robust_ok
            report.status='DEVELOPMENT_VALIDATED' if allowed else 'BLOCKED'
            report.formal_validation=False
        else:
            allowed=l1_ok and candidate_ready and l2_ok and l3_ok and l4_ok and formal and robust_ok
            report.status='PASSED' if allowed else 'BLOCKED'
            report.formal_validation=allowed
        report.promotion_allowed=allowed
        report.levels=[by['L1'],by['L2'],by['L3'],by['L4']]
        report.metadata['validation_task_status']=task.get('status')
        report.metadata['formal_case_count']=sum(1 for t in trusts if t.formal_recommendation)
        return report

    def persist(self, report: CandidateValidationReport) -> dict[str, Any]:
        now=self.db.now(); digest=report.content_hash()
        existing=self.db.query_one("SELECT created_at FROM candidate_validation_reports WHERE report_id=?",(report.report_id,)) or {}
        created=existing.get('created_at') or now
        self.db.execute("""INSERT INTO candidate_validation_reports(report_id,task_id,candidate_id,source_case_id,validation_task_id,report_json,content_hash,schema_version,status,promotion_allowed,formal_validation,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET validation_task_id=excluded.validation_task_id,report_json=excluded.report_json,content_hash=excluded.content_hash,schema_version=excluded.schema_version,status=excluded.status,promotion_allowed=excluded.promotion_allowed,formal_validation=excluded.formal_validation,updated_at=excluded.updated_at""",(report.report_id,report.task_id,report.candidate_id,report.source_case_id,report.validation_task_id,self.db.dumps(report.model_dump(mode='json')),digest,report.schema_version,report.status,1 if report.promotion_allowed else 0,1 if report.formal_validation else 0,created,now))
        return {'report_id':report.report_id,'content_hash':digest,'report':report.model_dump(mode='json')}

    def latest(self, task_id: str, candidate_id: str) -> CandidateValidationReport | None:
        row=self.db.query_one("SELECT report_json FROM candidate_validation_reports WHERE task_id=? AND candidate_id=? ORDER BY updated_at DESC LIMIT 1",(task_id,candidate_id)) or {}
        return CandidateValidationReport.model_validate(self.db.loads(row.get('report_json'),{})) if row.get('report_json') else None
