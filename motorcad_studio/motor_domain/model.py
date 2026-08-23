from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .parameters import ParameterDescriptor
from .snapshot import MotorChange, MotorChangeSet, MotorSnapshot


@dataclass(frozen=True, slots=True)
class MotorModel:
    """Pure domain façade around one immutable :class:`MotorSnapshot`.

    The model has no Motor-CAD, database, HTTP or UI dependency.  It is the V0.70
    boundary used by future visualization/native/optimization adapters.  Parameter
    edits produce a new model and an explicit :class:`MotorChangeSet`; callers never
    mutate the original snapshot in place.
    """

    snapshot: MotorSnapshot
    descriptors: Mapping[str, ParameterDescriptor]

    @property
    def identity(self):
        return self.snapshot.identity

    @property
    def snapshot_hash(self) -> str:
        return self.snapshot.content_hash()

    def parameter(self, parameter_id: str, default: Any = None) -> Any:
        if parameter_id in self.snapshot.parameters.values:
            return self.snapshot.parameters.values[parameter_id]
        return self.snapshot.parameters.unknown_values.get(parameter_id, default)

    def parameter_values(self) -> dict[str, Any]:
        return {
            **deepcopy(self.snapshot.parameters.values),
            **deepcopy(self.snapshot.parameters.unknown_values),
        }

    def component_parameters(self, component_id: str) -> dict[str, Any]:
        component = getattr(self.snapshot.assembly, component_id, None)
        if component is None:
            return {}
        return {
            parameter_id: self.parameter(parameter_id)
            for parameter_id in component.parameter_ids
            if self.parameter(parameter_id) is not None
        }

    def optimization_space(self) -> list[dict[str, Any]]:
        """Return design-owned variables that may safely enter an optimizer.

        Scenario/operating-point values are excluded by descriptor ownership, which
        prevents shaft speed/current/cooling conditions from silently becoming Design
        Revision parameters.
        """
        rows: list[dict[str, Any]] = []
        for parameter_id, descriptor in self.descriptors.items():
            if not descriptor.optimizable or descriptor.owner in {"scenario", "advanced"}:
                continue
            if descriptor.applicable_topologies and self.identity.topology_id not in descriptor.applicable_topologies:
                continue
            if descriptor.applicable_families and self.identity.family_id not in descriptor.applicable_families:
                continue
            value = self.parameter(parameter_id)
            if value is None:
                continue
            rows.append({
                "parameter_id": parameter_id,
                "owner": descriptor.owner,
                "value": value,
                "unit": descriptor.unit,
                "minimum": descriptor.minimum,
                "maximum": descriptor.maximum,
                "semantic_type": descriptor.semantic_type,
                "affects": list(descriptor.affects),
                "requires_native_readback": bool(descriptor.native.candidates),
            })
        return rows

    def with_parameter_patch(
        self,
        patch: Mapping[str, Any],
        *,
        explicit_parameter_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    ) -> tuple["MotorModel", MotorChangeSet]:
        next_snapshot = self.snapshot.model_copy(deep=True)
        explicit = set(next_snapshot.parameters.explicit_ids)
        explicit.update(str(value) for value in (explicit_parameter_ids or []) if str(value))
        explicit.update(str(value) for value in patch.keys())

        changes: list[MotorChange] = []
        affected_owners: list[str] = []
        affected_views: list[str] = []
        invalidated: list[str] = []
        native_readback = False

        for raw_id, after in patch.items():
            parameter_id = str(raw_id)
            before = self.parameter(parameter_id)
            if before == after:
                continue
            descriptor = self.descriptors.get(parameter_id)
            if descriptor is not None:
                next_snapshot.parameters.values[parameter_id] = deepcopy(after)
                next_snapshot.parameters.unknown_values.pop(parameter_id, None)
                owner = descriptor.owner
                affects = list(descriptor.affects)
                native_readback = native_readback or bool(descriptor.native.candidates)
            else:
                next_snapshot.parameters.unknown_values[parameter_id] = deepcopy(after)
                next_snapshot.parameters.values.pop(parameter_id, None)
                owner = "advanced"
                affects = ["validation.design", "analysis.emag"]
            changes.append(MotorChange(
                parameter_id=parameter_id,
                before=before,
                after=after,
                owner=owner,
                affects=affects,
            ))
            affected_owners.append(owner)
            affected_views.extend(
                value for value in affects
                if value.startswith("geometry.") or value.startswith("winding.")
            )
            invalidated.extend(value for value in affects if value.startswith("analysis."))

        next_snapshot.parameters.explicit_ids = sorted(explicit)
        change_set = MotorChangeSet(
            changes=changes,
            affected_owners=list(dict.fromkeys(affected_owners)),
            affected_views=list(dict.fromkeys(affected_views)),
            invalidated_analysis_domains=list(dict.fromkeys(invalidated)),
            requires_native_readback=native_readback,
        )
        return MotorModel(next_snapshot, self.descriptors), change_set
