from __future__ import annotations
from typing import Any
from .contracts import (
    MotorOptimizationSpace, OptimizationVariableDescriptor, MotorPatch, MotorPatchEntry,
    ExperimentVariableSpec, ExperimentPlan, OperatingPoint, OperatingPointSet,
    ObjectiveAggregateSpec, ConstraintAggregateSpec, ToleranceDistribution, UncertaintyScenarioSet, RobustnessPlan,
)
from .robustness import UncertaintySamplingService
from ..motor_domain import MotorSnapshot, MotorModel

class OptimizationPlanningService:
    def __init__(self, motor_domain):
        self.motor_domain=motor_domain
        self.uncertainty_sampling=UncertaintySamplingService()

    def build_space(self, *, design_revision_id:str, snapshot:MotorSnapshot)->MotorOptimizationSpace:
        model=self.motor_domain.model(snapshot)
        rows=[]
        for row in model.optimization_space():
            value=row.get('value')
            if not isinstance(value,(int,float)) or isinstance(value,bool): continue
            rows.append(OptimizationVariableDescriptor(**row))
        return MotorOptimizationSpace(design_revision_id=design_revision_id,motor_snapshot_hash=snapshot.content_hash(),topology_id=snapshot.identity.topology_id,template_id=snapshot.identity.template_id,variables=rows)

    def validate_variables(self, space:MotorOptimizationSpace, experiment:dict[str,Any])->list[ExperimentVariableSpec]:
        allowed=space.variable_map(); result=[]
        for row in experiment.get('variables') or []:
            pid=str(row.get('parameter') or row.get('parameter_id') or '')
            spec=allowed.get(pid)
            if not spec: raise ValueError(f'OPTIMIZATION_VARIABLE_NOT_ALLOWED:{pid}')
            low=float(row.get('low')); high=float(row.get('high'))
            if spec.minimum is not None and low<float(spec.minimum): raise ValueError(f'OPTIMIZATION_VARIABLE_OUT_OF_RANGE:{pid}')
            if spec.maximum is not None and high>float(spec.maximum): raise ValueError(f'OPTIMIZATION_VARIABLE_OUT_OF_RANGE:{pid}')
            result.append(ExperimentVariableSpec(parameter_id=pid,low=low,high=high,levels=int(row.get('levels') or 3),owner=spec.owner,unit=spec.unit))
        return result

    def build_operating_point_set(self, *, analysis_definition_revision_id:str|None, load_cases:list[dict[str,Any]], selections:list[dict[str,Any]]|None=None, fallback_index:int=0)->OperatingPointSet:
        if not load_cases: load_cases=[{}]
        selected=selections or [{'load_case_index':fallback_index,'weight':1.0}]
        points=[]; seen=set()
        for pos,row in enumerate(selected):
            idx=int(row.get('load_case_index',fallback_index))
            if idx<0 or idx>=len(load_cases): raise ValueError('LOAD_CASE_INDEX_OUT_OF_RANGE')
            if idx in seen: raise ValueError('DUPLICATE_OPERATING_POINT')
            seen.add(idx)
            label=str(row.get('label') or f'Operating point {idx+1}')
            points.append(OperatingPoint(operating_point_id=f'OP-{pos+1:03d}',source_index=idx,label=label,weight=float(row.get('weight') or 1.0),scenario=dict(load_cases[idx] or {})))
        return OperatingPointSet(analysis_definition_revision_id=analysis_definition_revision_id,points=points)

    def build_uncertainty_scenario_set(self, *, snapshot:MotorSnapshot, operating_point_set:OperatingPointSet, robustness:dict[str,Any]|None)->tuple[UncertaintyScenarioSet|None,RobustnessPlan|None]:
        config=dict(robustness or {})
        if not bool(config.get('enabled')):
            return None,None
        descriptors=self.motor_domain.parameter_descriptors(snapshot.identity.template_id)
        distributions=[]
        for index,row in enumerate(config.get('distributions') or []):
            scope=str(row.get('target_scope') or 'design'); target_id=str(row.get('target_id') or '')
            if scope=='design':
                descriptor=descriptors.get(target_id)
                value=snapshot.parameters.values.get(target_id)
                if descriptor is None or descriptor.owner=='scenario' or descriptor.topology_parameter or not isinstance(value,(int,float)) or isinstance(value,bool):
                    raise ValueError(f'UNCERTAINTY_TARGET_NOT_ALLOWED:{scope}:{target_id}')
                unit=str(descriptor.unit or '')
            elif scope=='scenario':
                values=[point.scenario.get(target_id) for point in operating_point_set.points]
                if not values or any(not isinstance(value,(int,float)) or isinstance(value,bool) for value in values):
                    raise ValueError(f'UNCERTAINTY_TARGET_NOT_ALLOWED:{scope}:{target_id}')
                unit=''
            else:
                raise ValueError(f'UNCERTAINTY_SCOPE_NOT_ALLOWED:{scope}')
            payload={**row,'uncertainty_id':str(row.get('uncertainty_id') or f'U-{index+1:03d}'),'target_scope':scope,'target_id':target_id,'unit':str(row.get('unit') or unit)}
            distributions.append(ToleranceDistribution.model_validate(payload))
        uncertainty_set=self.uncertainty_sampling.build(
            distributions=distributions,samples=int(config.get('samples') or 8),seed=int(config.get('seed') or 7403),
            sampling=str(config.get('sampling') or 'latin_hypercube'),include_nominal=bool(config.get('include_nominal',True)),
            metadata={'design_snapshot_hash':snapshot.content_hash(),'operating_point_set_hash':operating_point_set.content_hash()},
        )
        plan=RobustnessPlan(
            uncertainty_scenario_set_hash=uncertainty_set.content_hash(),
            objective_strategy=str(config.get('objective_strategy') or 'risk_adjusted_mean'),
            risk_weight=float(config.get('risk_weight',1.0)),percentile=float(config.get('percentile',95.0)),
            constraint_strategy=str(config.get('constraint_strategy') or 'probability'),
            required_feasibility_probability=float(config.get('required_feasibility_probability',0.95)),
            metadata={'sampling':uncertainty_set.sampling,'sample_count':len(uncertainty_set.samples)},
        )
        return uncertainty_set,plan

    def build_experiment_plan(self, *, design_revision_id:str, snapshot:MotorSnapshot, experiment:dict[str,Any], analysis_definition_revision_id:str|None, execution_plan_hash:str|None, operating_point_set:OperatingPointSet, uncertainty_scenario_set:UncertaintyScenarioSet|None=None, robustness_plan:RobustnessPlan|None=None)->tuple[MotorOptimizationSpace,ExperimentPlan]:
        space=self.build_space(design_revision_id=design_revision_id,snapshot=snapshot)
        variables=self.validate_variables(space,experiment)
        objectives=[ObjectiveAggregateSpec(result_id=str(o.get('result_id')),direction=str(o.get('direction') or 'min'),aggregation=str(o.get('aggregation') or 'weighted_mean'),percentile=float(o.get('percentile',50))) for o in experiment.get('objectives') or []]
        constraints=[ConstraintAggregateSpec(field=str(c.get('field')),operator=str(c.get('operator') or '<='),value=float(c.get('value')),aggregation=str(c.get('aggregation') or 'all_points'),percentile=float(c.get('percentile',50))) for c in experiment.get('constraints') or []]
        plan=ExperimentPlan(design_revision_id=design_revision_id,motor_snapshot_hash=snapshot.content_hash(),optimization_space_hash=space.content_hash(),analysis_definition_revision_id=analysis_definition_revision_id,execution_plan_hash=execution_plan_hash,operating_point_set_hash=operating_point_set.content_hash(),operating_point_policy='multi_frozen_points' if len(operating_point_set.points)>1 else 'single_frozen_point',uncertainty_scenario_set_hash=uncertainty_scenario_set.content_hash() if uncertainty_scenario_set else None,robustness_plan_hash=robustness_plan.content_hash() if robustness_plan else None,robustness_policy='integrated_uncertainty' if robustness_plan else 'nominal',mode=str(experiment.get('mode') or 'single'),variables=variables,objectives=objectives,constraints=constraints,algorithm={k:experiment.get(k) for k in ('samples','seed','include_baseline','population_size','generations','crossover_rate','mutation_rate') if k in experiment},metadata={'sensitivity':dict(experiment.get('sensitivity') or {})})
        return space,plan

    def build_patch(self, *, space:MotorOptimizationSpace, candidate_parameters:dict[str,Any])->MotorPatch:
        changes=[]
        for v in space.variables:
            if v.parameter_id not in candidate_parameters: continue
            after=candidate_parameters[v.parameter_id]
            if after==v.value: continue
            changes.append(MotorPatchEntry(parameter_id=v.parameter_id,before=v.value,after=after,owner=v.owner,unit=v.unit))
        return MotorPatch(baseline_design_revision_id=space.design_revision_id,baseline_motor_snapshot_hash=space.motor_snapshot_hash,optimization_space_hash=space.content_hash(),changes=changes)
