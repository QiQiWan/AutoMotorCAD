from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


NATIVE_PREVIEW_RECONCILIATION_SCHEMA_VERSION = 1
NATIVE_PREVIEW_RECONCILIATION_AUTHORITY = "NativePreviewReconciliationAuthorityV1"


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _same(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    try:
        a = float(left)
        b = float(right)
        return abs(a - b) <= 1.0e-9 + 1.0e-7 * max(abs(a), abs(b), 1.0)
    except (TypeError, ValueError):
        return str(left) == str(right)


def _material_projection(preview: dict[str, Any]) -> dict[str, Any]:
    native = dict(preview.get("materials") or {})
    components: dict[str, Any] = {}
    readbacks: dict[str, dict[str, Any]] = {}
    for component_id, raw in native.items():
        mapping = dict(raw or {}) if isinstance(raw, dict) else {}
        readbacks[str(component_id)] = mapping
        values = [str(value) for value in mapping.values() if value not in (None, "")]
        unique = list(dict.fromkeys(values))
        if len(unique) == 1:
            components[str(component_id)] = unique[0]
        elif unique:
            components[str(component_id)] = " / ".join(unique)
    return {
        "component_materials": components,
        "native_component_readbacks": readbacks,
        "material_provenance": {
            component_id: {"source_kind": "motorcad_native_readback", "native_components": sorted(mapping)}
            for component_id, mapping in readbacks.items()
        },
    }


def _winding_projection(preview: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    native = dict(preview.get("winding") or {})
    result = deepcopy(fallback or {})
    result.update({
        "phase_count": native.get("phase_count") if native.get("phase_count") is not None else result.get("phase_count"),
        "parallel_paths": native.get("parallel_paths") if native.get("parallel_paths") is not None else result.get("parallel_paths"),
        "turns_per_coil": native.get("turns_per_coil") if native.get("turns_per_coil") is not None else result.get("turns_per_coil"),
        "layers": native.get("layers") if native.get("layers") is not None else result.get("layers"),
        "slot_fill_factor": native.get("slot_fill_factor") if native.get("slot_fill_factor") is not None else result.get("slot_fill_factor"),
        "path_type": native.get("path_type") or result.get("path_type"),
        "coil_table": list(native.get("coils") or []),
        "definition_status": "NATIVE_MODEL_SNAPSHOT",
        "definition_authority": NATIVE_PREVIEW_RECONCILIATION_AUTHORITY,
        "native_signature": native.get("signature"),
    })
    if native.get("slot_count") is not None:
        result["slot_count"] = native.get("slot_count")
    return result


class NativePreviewReconciliationAuthority:
    """Choose and reconcile a lineage-compatible Motor-CAD preview projection.

    V0.88-E deliberately reuses the V0.88-B NativeModelSnapshot projection instead of
    inventing a second geometry extractor.  A native projection may be rendered only
    when its Design Snapshot hash belongs to the immutable Design Revision currently
    shown.  QUALIFIED projections can become the default read-only view; DRIFT/PARTIAL
    projections are compare-only evidence and never silently replace Design Intent.
    """

    authority = NATIVE_PREVIEW_RECONCILIATION_AUTHORITY

    @staticmethod
    def _candidate_from_reconciliation(reconciliation: dict[str, Any] | None) -> dict[str, Any] | None:
        record = dict(reconciliation or {})
        projection = dict(record.get("native_preview_projection") or {})
        if not projection:
            return None
        return {
            "source": "editor_native_check",
            "source_rank": 20,
            "case_id": None,
            "task_id": None,
            "snapshot_hash": record.get("native_model_snapshot_hash") or record.get("native_preview_snapshot_hash"),
            "design_state_hash": record.get("native_model_design_state_hash") or projection.get("design_state_hash"),
            "phase": record.get("native_preview_phase") or projection.get("source_phase"),
            "projection": projection,
            "native_status": record.get("native_model_status") or projection.get("status"),
            "checked_at": record.get("checked_at"),
        }

    @staticmethod
    def _candidate_from_case(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
        row = dict(evidence or {})
        snapshot = dict(row.get("native_model_snapshot") or {})
        projection = dict(snapshot.get("preview_projection") or row.get("native_preview_projection") or {})
        if not projection:
            return None
        phase = snapshot.get("phase") or row.get("native_model_snapshot_phase") or projection.get("source_phase")
        rank = {"post_solve": 40, "post_native_validation": 30, "post_binding": 10}.get(str(phase), 10)
        return {
            "source": "native_case_evidence",
            "source_rank": rank,
            "case_id": row.get("case_id"),
            "task_id": row.get("task_id"),
            "design_revision_id": row.get("design_revision_id"),
            "snapshot_hash": row.get("native_model_snapshot_hash"),
            "design_state_hash": row.get("native_model_design_state_hash") or projection.get("design_state_hash"),
            "phase": phase,
            "projection": projection,
            "native_status": snapshot.get("status") or projection.get("status"),
            "checked_at": row.get("finished_at"),
        }

    def build(
        self,
        *,
        revision: dict[str, Any],
        effective_parameters: dict[str, Any],
        parameter_rows: list[dict[str, Any]],
        winding_design: dict[str, Any],
        native_evidence: dict[str, Any] | None,
        native_reconciliation: dict[str, Any] | None,
        native_motor_object_builder=None,
    ) -> dict[str, Any]:
        revision_snapshot_hash = str(revision.get("motor_snapshot_hash") or "")
        revision_id = str(revision.get("id") or "")
        candidates = [
            self._candidate_from_case(native_evidence),
            self._candidate_from_reconciliation(native_reconciliation),
        ]
        candidates = [row for row in candidates if row]
        candidates.sort(key=lambda row: int(row.get("source_rank") or 0), reverse=True)

        selected: dict[str, Any] | None = None
        rejected: list[dict[str, Any]] = []
        for candidate in candidates:
            projection = dict(candidate.get("projection") or {})
            projected_hash = str(projection.get("design_snapshot_hash") or "")
            lineage_complete = bool(projection.get("lineage_complete"))
            revision_exact = candidate.get("source") != "native_case_evidence" or (bool(candidate.get("case_id")) and str(candidate.get("design_revision_id") or "") == revision_id)
            hash_match = bool(revision_snapshot_hash and projected_hash and revision_snapshot_hash == projected_hash)
            candidate["lineage"] = {
                "revision_id": revision_id,
                "revision_motor_snapshot_hash": revision_snapshot_hash or None,
                "native_design_snapshot_hash": projected_hash or None,
                "design_snapshot_hash_match": hash_match,
                "native_lineage_complete": lineage_complete,
                "case_bound_to_revision": revision_exact,
            }
            if hash_match and lineage_complete and revision_exact:
                selected = candidate
                break
            rejected.append({
                "source": candidate.get("source"),
                "case_id": candidate.get("case_id"),
                "phase": candidate.get("phase"),
                "reason": "DESIGN_SNAPSHOT_LINEAGE_MISMATCH" if not hash_match else "NATIVE_LINEAGE_INCOMPLETE",
                "native_design_snapshot_hash": projected_hash or None,
            })

        parameter_lookup = {str(row.get("id")): row for row in parameter_rows}
        if selected is None:
            result = {
                "schema_version": NATIVE_PREVIEW_RECONCILIATION_SCHEMA_VERSION,
                "authority": self.authority,
                "status": "DESIGN_ONLY" if not candidates else "STALE_NATIVE_EVIDENCE",
                "default_source": "design",
                "native_render_allowed": False,
                "native_authoritative": False,
                "compare_allowed": False,
                "reason": "当前设计尚无可用于可视化的 Motor-CAD 原生回读。" if not candidates else "现有 Motor-CAD 可视化证据与当前 Design Revision 的模型快照不一致，已禁止套用。",
                "source": None,
                "rejected_candidates": rejected,
                "design_parameters": deepcopy(effective_parameters),
                "diffs": [],
                "coverage": {"native_parameter_count": 0, "comparable_parameter_count": 0, "changed_parameter_count": 0},
            }
            result["content_hash"] = _stable_hash(result)
            return result

        projection = dict(selected.get("projection") or {})
        native_parameters = dict(projection.get("parameters") or {})
        native_effective = {**deepcopy(effective_parameters), **native_parameters}
        native_status = str(selected.get("native_status") or projection.get("status") or "UNAVAILABLE").upper()
        spatial_geometry = dict(projection.get("spatial_geometry") or {})
        spatial_status = str(spatial_geometry.get("status") or "UNAVAILABLE").upper()
        spatial_render_allowed = bool(spatial_status in {"COMPLETE", "PARTIAL"} and spatial_geometry.get("regions"))
        render_allowed = bool(native_parameters or projection.get("winding") or projection.get("materials") or spatial_render_allowed)
        native_authoritative = native_status == "QUALIFIED" and bool(projection.get("qualified_for_native_preview"))
        diffs: list[dict[str, Any]] = []
        comparable = 0
        changed = 0
        for semantic_id, native_value in sorted(native_parameters.items()):
            design_value = effective_parameters.get(semantic_id)
            row = parameter_lookup.get(semantic_id, {})
            if design_value is None:
                state = "NATIVE_ONLY"
            else:
                comparable += 1
                state = "MATCH" if _same(design_value, native_value) else "DELTA"
                if state == "DELTA":
                    changed += 1
            delta = None
            try:
                delta = float(native_value) - float(design_value) if design_value is not None else None
            except (TypeError, ValueError):
                delta = None
            diffs.append({
                "semantic_id": semantic_id,
                "label": row.get("label") or semantic_id,
                "unit": row.get("unit") or "",
                "category": row.get("category") or "other",
                "design_value": design_value,
                "native_value": native_value,
                "delta": delta,
                "status": state,
            })

        native_materials = _material_projection(projection)
        native_winding = _winding_projection(projection, winding_design)
        native_motor_object = None
        if native_motor_object_builder is not None:
            try:
                native_motor_object = native_motor_object_builder(native_effective)
            except Exception as exc:  # preview must not break the workbench
                selected.setdefault("warnings", []).append(f"native_motor_object: {type(exc).__name__}: {exc}")

        result = {
            "schema_version": NATIVE_PREVIEW_RECONCILIATION_SCHEMA_VERSION,
            "authority": self.authority,
            "status": "NATIVE_CURRENT" if native_authoritative else f"NATIVE_{native_status}",
            "default_source": "native" if native_authoritative else "design",
            "native_render_allowed": render_allowed,
            "native_authoritative": native_authoritative,
            "compare_allowed": render_allowed,
            "reason": (
                "Motor-CAD NativeModelSnapshot 与当前 Design Revision 完整同源，可作为只读可视化默认来源。"
                if native_authoritative else
                "Motor-CAD 回读与当前设计同源，但状态尚未 QUALIFIED；仅允许显式查看或差异对比。"
            ),
            "source": {
                "kind": selected.get("source"),
                "case_id": selected.get("case_id"),
                "task_id": selected.get("task_id"),
                "phase": selected.get("phase"),
                "snapshot_hash": selected.get("snapshot_hash"),
                "design_state_hash": selected.get("design_state_hash"),
                "checked_at": selected.get("checked_at"),
            },
            "lineage": selected.get("lineage"),
            "native_projection": projection,
            "native_spatial_geometry": spatial_geometry,
            "native_spatial_geometry_status": spatial_status,
            "native_spatial_geometry_hash": spatial_geometry.get("content_hash"),
            "native_spatial_render_allowed": spatial_render_allowed,
            "design_parameters": deepcopy(effective_parameters),
            "native_parameters": native_parameters,
            "native_effective_parameters": native_effective,
            "native_winding_design": native_winding,
            "native_materials": native_materials,
            "native_motor_object": native_motor_object,
            "diffs": diffs,
            "changed_diffs": [row for row in diffs if row.get("status") != "MATCH"],
            "coverage": {
                "native_parameter_count": len(native_parameters),
                "comparable_parameter_count": comparable,
                "changed_parameter_count": changed,
                "winding_coil_count": len((projection.get("winding") or {}).get("coils") or []),
                "material_component_count": len((projection.get("materials") or {})),
                "spatial_region_count": int(spatial_geometry.get("drawable_region_count") or 0),
                "spatial_entity_count": int(spatial_geometry.get("entity_count") or 0),
            },
            "rejected_candidates": rejected,
        }
        result["content_hash"] = _stable_hash({key: value for key, value in result.items() if key != "content_hash"})
        return result
