"""Material projection application service.

The service derives all counters from the same row projection returned to the UI.
This removes the prior split logic where the header and table interpreted material
inheritance differently.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from ...shared import MaterialSourceKind, ModuleNotFoundError, stable_hash
from ..domain.projection import ComponentMaterialProjection


_CANONICAL_COMPONENTS: tuple[str, ...] = (
    "stator_lamination",
    "rotor_lamination",
    "magnet",
    "winding_conductor",
    "shaft",
    "housing",
    "rotor_sleeve",
)

_COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    "stator_lamination": ("stator_lamination", "stator", "stator_steel"),
    "rotor_lamination": ("rotor_lamination", "rotor", "rotor_steel"),
    "magnet": ("magnet", "magnets", "permanent_magnet"),
    "winding_conductor": ("winding_conductor", "conductor", "winding", "copper"),
    "shaft": ("shaft",),
    "housing": ("housing", "case", "frame"),
    "rotor_sleeve": ("rotor_sleeve", "sleeve", "banding"),
}


def _material_name(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("name", "material", "material_name", "selected", "value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return None


def _component_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _canonical_component_id(value: Any) -> str:
    token = _component_token(value)
    compact = token.replace("_", "")
    for component_id, aliases in _COMPONENT_ALIASES.items():
        candidates = {_component_token(component_id), *(_component_token(alias) for alias in aliases)}
        if token in candidates or compact in {candidate.replace("_", "") for candidate in candidates}:
            return component_id
    return token


def _lookup(mapping: dict[str, Any], component_id: str) -> tuple[str | None, Any]:
    # Preserve mapping insertion order as edit precedence. A revision patch can
    # legitimately add a canonical key beside a historical display-name key.
    # Selecting the last matching alias makes the newest intent authoritative.
    match: tuple[str | None, Any] = (None, None)
    for key, value in mapping.items():
        if _canonical_component_id(key) == component_id:
            match = (str(key), value)
    return match


def _native_material_mapping(reconciliation: dict[str, Any]) -> dict[str, Any]:
    queue: list[Any] = [reconciliation]
    visited: set[int] = set()
    while queue:
        item = queue.pop(0)
        if not isinstance(item, dict) or id(item) in visited:
            continue
        visited.add(id(item))
        for key in (
            "component_materials",
            "material_readback",
            "materials_readback",
            "materials",
        ):
            value = item.get(key)
            if isinstance(value, dict) and any(
                _material_name(candidate) for candidate in value.values()
            ):
                return dict(value)
        queue.extend(value for value in item.values() if isinstance(value, dict))
    return {}


class MaterialProjectionService:
    CONTRACT_VERSION = "1"

    def __init__(self, *, solutions: Any, templates: Any):
        self._solutions = solutions
        self._templates = templates

    def for_revision(self, revision_id: str) -> dict[str, Any]:
        revision = self._solutions.get_revision(revision_id)
        if revision is None:
            raise ModuleNotFoundError("motor revision", revision_id)
        solution_id = str(revision.get("solution_id") or revision.get("design_id") or "")
        solution = self._solutions.get_solution_summary(solution_id)
        if solution is None:
            raise ModuleNotFoundError("solution", solution_id)
        template_id = str(solution.get("template_id") or "")
        try:
            template = self._templates.get_template(template_id) if template_id else {}
        except KeyError:
            template = {}

        defaults = dict(template.get("material_defaults") or {})
        default_metadata = dict(template.get("material_default_metadata") or {})
        revision_materials = dict(revision.get("materials") or {})
        selected = dict(
            revision_materials.get("component_materials")
            if isinstance(revision_materials.get("component_materials"), dict)
            else revision_materials
        )
        provenance = dict(revision_materials.get("material_provenance") or {})
        native = _native_material_mapping(
            dict(revision.get("native_reconciliation") or {})
        )

        components: list[str] = list(_CANONICAL_COMPONENTS)
        for mapping in (defaults, selected, native):
            for key in mapping:
                canonical = _canonical_component_id(key)
                if canonical and canonical not in components:
                    components.append(canonical)

        rows: list[ComponentMaterialProjection] = []
        for component_id in components:
            selected_key, selected_value = _lookup(selected, component_id)
            default_key, default_value = _lookup(defaults, component_id)
            native_key, native_value = _lookup(native, component_id)
            selected_name = _material_name(selected_value)
            default_name = _material_name(default_value)
            native_name = _material_name(native_value)
            provenance_row = dict(provenance.get(selected_key or component_id) or {})
            source_hint = str(provenance_row.get("source_kind") or "").lower()

            if native_name and selected_name and native_name == selected_name:
                source_kind = MaterialSourceKind.NATIVE_READBACK
                source_reference = native_key or "native_reconciliation"
                status = "NATIVE_CONFIRMED"
            elif selected_name:
                template_source = source_hint.startswith("template")
                if default_name and selected_name == default_name and (
                    template_source or not source_hint
                ):
                    source_kind = MaterialSourceKind.TEMPLATE_DEFAULT
                    source_reference = str(
                        provenance_row.get("source_template_id") or template_id or ""
                    ) or None
                    status = "TEMPLATE_BASELINE"
                else:
                    source_kind = MaterialSourceKind.REVISION_OVERRIDE
                    source_reference = f"motor_revision:{revision_id}"
                    status = "REVISION_FROZEN"
            elif default_name:
                selected_name = default_name
                source_kind = MaterialSourceKind.TEMPLATE_DEFAULT
                source_reference = template_id or None
                status = "TEMPLATE_BASELINE"
            elif native_name:
                selected_name = native_name
                source_kind = MaterialSourceKind.NATIVE_READBACK
                source_reference = native_key or "native_reconciliation"
                status = "NATIVE_INHERITED"
            else:
                source_kind = MaterialSourceKind.MODEL_INHERITED
                source_reference = "motorcad_model_baseline"
                status = "MODEL_INHERITED"

            rows.append(
                ComponentMaterialProjection(
                    component_id=component_id,
                    material_name=selected_name,
                    source_kind=source_kind,
                    source_reference=source_reference,
                    template_default=default_name,
                    native_readback=native_name,
                    status=status,
                    metadata={
                        "selected_key": selected_key,
                        "template_key": default_key,
                        "native_key": native_key,
                        "template_metadata": default_metadata.get(default_key or component_id),
                        "provenance": provenance_row,
                    },
                )
            )

        counts = Counter(row.source_kind.value for row in rows)
        assigned = sum(1 for row in rows if row.material_name)
        payload = {
            "authority": "ComponentMaterialProjectionV1",
            "revision_id": revision_id,
            "motor_revision_id": revision_id,
            "solution_id": solution_id,
            "project_id": solution.get("project_id"),
            "template_id": template_id,
            "rows": [row.to_dict() for row in rows],
            "summary": {
                "component_count": len(rows),
                "assigned_count": assigned,
                "template_default_count": counts[MaterialSourceKind.TEMPLATE_DEFAULT.value],
                "revision_override_count": counts[MaterialSourceKind.REVISION_OVERRIDE.value],
                "native_readback_count": counts[MaterialSourceKind.NATIVE_READBACK.value],
                "model_inherited_count": counts[MaterialSourceKind.MODEL_INHERITED.value],
                "unresolved_count": counts[MaterialSourceKind.UNRESOLVED.value],
            },
        }
        payload["content_hash"] = stable_hash(
            {
                "revision_id": revision_id,
                "rows": payload["rows"],
            }
        )
        return payload

    def for_solution(self, solution_id: str) -> dict[str, Any]:
        revision = self._solutions.get_latest_revision(solution_id)
        if revision is None:
            if self._solutions.get_solution_summary(solution_id) is None:
                raise ModuleNotFoundError("solution", solution_id)
            raise ModuleNotFoundError("motor revision", solution_id)
        return self.for_revision(str(revision.get("id") or ""))


__all__ = ["MaterialProjectionService"]
