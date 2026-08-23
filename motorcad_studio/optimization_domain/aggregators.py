from __future__ import annotations
from typing import Iterable
from .contracts import (
    OperatingPointSet, ObjectiveAggregateSpec, ConstraintAggregateSpec, CandidatePointResult,
    AggregatedObjectiveResult, AggregatedConstraintResult, CandidateResultSet, MotorPatch,
)

def _percentile(values:list[float], q:float)->float:
    if not values: raise ValueError('empty values')
    xs=sorted(float(v) for v in values)
    if len(xs)==1: return xs[0]
    rank=(max(0.0,min(100.0,float(q)))/100.0)*(len(xs)-1)
    lo=int(rank); hi=min(len(xs)-1,lo+1); frac=rank-lo
    return xs[lo]*(1-frac)+xs[hi]*frac

def _aggregate(values:list[float], method:str, weights:list[float]|None=None, percentile:float=50.0)->float:
    if not values: raise ValueError('empty values')
    if method=='weighted_mean':
        ws=list(weights or [1.0]*len(values)); total=sum(ws)
        if total<=0: raise ValueError('weights must be positive')
        return sum(v*w for v,w in zip(values,ws))/total
    if method=='mean': return sum(values)/len(values)
    if method=='min': return min(values)
    if method=='max': return max(values)
    if method=='percentile': return _percentile(values,percentile)
    raise ValueError(f'unknown aggregation {method}')

def _compare(value:float, operator:str, limit:float)->bool:
    if operator=='<=': return value<=limit
    if operator=='<': return value<limit
    if operator=='>=': return value>=limit
    if operator=='>': return value>limit
    return abs(value-limit)<=1e-12

def _violation(value:float, operator:str, limit:float)->float:
    if operator in ('<=','<'): return max(0.0,value-limit)
    if operator in ('>=','>'): return max(0.0,limit-value)
    return abs(value-limit)

class ObjectiveAggregator:
    def aggregate(self, spec:ObjectiveAggregateSpec, points:list[CandidatePointResult], op_set:OperatingPointSet)->AggregatedObjectiveResult:
        point_values={p.operating_point_id:float(p.values[spec.result_id]) for p in points if spec.result_id in p.values}
        if len(point_values)!=len(op_set.points):
            return AggregatedObjectiveResult(result_id=spec.result_id,direction=spec.direction,aggregation=spec.aggregation,complete=False,point_values=point_values)
        weights=op_set.normalized_weights(); ordered=[point_values[p.operating_point_id] for p in op_set.points]
        ws=[weights[p.operating_point_id] for p in op_set.points]
        value=_aggregate(ordered,spec.aggregation,ws,spec.percentile)
        return AggregatedObjectiveResult(result_id=spec.result_id,direction=spec.direction,aggregation=spec.aggregation,value=value,complete=True,point_values=point_values)

class ConstraintAggregator:
    def aggregate(self, spec:ConstraintAggregateSpec, points:list[CandidatePointResult], op_set:OperatingPointSet)->AggregatedConstraintResult:
        # ResultBundle projections expose canonical result IDs while legacy constraint
        # syntax uses `result.<id>`. Accept both without changing the frozen field ID.
        value_keys=[spec.field]
        if spec.field.startswith('result.'):
            value_keys.append(spec.field.split('.',1)[1])
        point_values={}
        for p in points:
            key=next((candidate for candidate in value_keys if candidate in p.values),None)
            if key is not None:
                point_values[p.operating_point_id]=float(p.values[key])
        point_feasible={pid:_compare(v,spec.operator,float(spec.value)) for pid,v in point_values.items()}
        if len(point_values)!=len(op_set.points):
            return AggregatedConstraintResult(field=spec.field,operator=spec.operator,limit=spec.value,aggregation=spec.aggregation,value=None,feasible=False,violation=float('inf'),point_values=point_values,point_feasible=point_feasible)
        ordered=[point_values[p.operating_point_id] for p in op_set.points]
        weights=op_set.normalized_weights(); ws=[weights[p.operating_point_id] for p in op_set.points]
        if spec.aggregation=='all_points':
            feasible=all(point_feasible.values())
            if spec.operator in ('>=','>'): value=min(ordered)
            elif spec.operator in ('<=','<'): value=max(ordered)
            else: value=max(ordered,key=lambda v:abs(v-float(spec.value)))
            violation=sum(_violation(v,spec.operator,float(spec.value)) for v in ordered)
        else:
            value=_aggregate(ordered,spec.aggregation,ws,spec.percentile)
            feasible=_compare(value,spec.operator,float(spec.value))
            violation=_violation(value,spec.operator,float(spec.value))
        return AggregatedConstraintResult(field=spec.field,operator=spec.operator,limit=spec.value,aggregation=spec.aggregation,value=value,feasible=feasible,violation=violation,point_values=point_values,point_feasible=point_feasible)

class CandidateResultAggregator:
    def __init__(self):
        self.objectives=ObjectiveAggregator(); self.constraints=ConstraintAggregator()
    def build(self, *, task_id:str,candidate_id:str,generation:int,motor_patch:MotorPatch,op_set:OperatingPointSet,point_results:list[CandidatePointResult],objective_specs:list[ObjectiveAggregateSpec],constraint_specs:list[ConstraintAggregateSpec])->CandidateResultSet:
        expected={p.operating_point_id for p in op_set.points}
        actual={p.operating_point_id for p in point_results}
        complete=expected==actual and all(p.execution_status in {'SUCCEEDED','CACHED'} and p.quality_status!='INVALID' for p in point_results)
        objective_results=[self.objectives.aggregate(s,point_results,op_set) for s in objective_specs]
        constraint_results=[self.constraints.aggregate(s,point_results,op_set) for s in constraint_specs]
        complete=complete and all(o.complete for o in objective_results)
        feasible=complete and all(c.feasible for c in constraint_results)
        violation=sum(c.violation for c in constraint_results if c.violation != float('inf'))
        if any(c.violation == float('inf') for c in constraint_results): violation=float('inf')
        rep=point_results[0].case_id if point_results else None
        return CandidateResultSet(task_id=task_id,candidate_id=candidate_id,generation=generation,motor_patch_hash=motor_patch.content_hash(),motor_patch=motor_patch,operating_point_set_hash=op_set.content_hash(),point_results=point_results,objectives=objective_results,constraints=constraint_results,complete=complete,feasible=feasible,total_constraint_violation=violation,representative_case_id=rep)
