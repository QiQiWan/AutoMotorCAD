from __future__ import annotations

from typing import Any

from .db import Database
from .geometry_guard import validate_geometry_relations
from .solution_repository import SolutionRepository
from .winding_guard import validate_winding_relations


def _clean(parameters: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key): value for key, value in (parameters or {}).items() if value is not None and value != ""}


class SolutionService:
    """Domain owner for Solution and immutable Motor Revision lifecycle.

    V0.78 removes the Solution domain's dependency on WorkspaceService persistence.
    All new Solution-domain reads/writes go through :class:`SolutionRepository`,
    which targets the physical SQLite tables ``solutions``, ``motor_revisions`` and
    ``solution_drafts``. Legacy ``design*`` SQL names remain database compatibility
    views for historical modules during the migration window.
    """

    def __init__(
        self,
        db: Database,
        repository: SolutionRepository,
        motor_domain: Any,
        *,
        template_service: Any,
        domain_service: Any,
        log_store: Any | None = None,
    ):
        self.db = db
        self.repository = repository
        self.motor_domain = motor_domain
        self.templates = template_service
        self.domain = domain_service
        self.logs = log_store

    @staticmethod
    def _canonical_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None
        row = dict(payload)
        if row.get("design_id") and not row.get("solution_id"):
            row["solution_id"] = row["design_id"]
        if row.get("base_revision_id") and not row.get("base_motor_revision_id"):
            row["base_motor_revision_id"] = row["base_revision_id"]
        if isinstance(row.get("revisions"), list):
            row["revisions"] = [SolutionService._canonical_payload(item) for item in row["revisions"]]
        return row

    def _snapshot(self, solution: dict[str, Any], revision: dict[str, Any]) -> tuple[dict[str, Any], int, str]:
        snapshot = self.motor_domain.build_snapshot(solution, revision)
        return snapshot.model_dump(mode="json"), int(snapshot.schema_version), snapshot.content_hash()

    def _with_snapshot(self, solution: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
        row = dict(revision)
        if row.get("motor_snapshot"):
            row["motor_snapshot_persisted"] = True
            return row
        payload, version, digest = self._snapshot(solution, row)
        row["motor_snapshot"] = payload
        row["motor_snapshot_schema_version"] = version
        row["motor_snapshot_hash"] = digest
        row["motor_snapshot_persisted"] = False
        return row

    def _persist_revision_snapshot(self, solution: dict[str, Any], revision_id: str) -> dict[str, Any]:
        revision = self.repository.get_revision(revision_id)
        if revision is None:
            raise KeyError(revision_id)
        payload, version, digest = self._snapshot(solution, revision)
        self.repository.persist_revision_snapshot(revision_id, payload, version, digest)
        refreshed = self.repository.get_revision(revision_id) or revision
        refreshed["motor_snapshot"] = payload
        refreshed["motor_snapshot_schema_version"] = version
        refreshed["motor_snapshot_hash"] = digest
        refreshed["motor_snapshot_persisted"] = True
        return refreshed

    def _draft_with_snapshot(self, solution: dict[str, Any], draft: dict[str, Any] | None) -> dict[str, Any] | None:
        if draft is None or draft.get("motor_snapshot"):
            return draft
        base = self.repository.get_revision(str(draft.get("base_motor_revision_id") or "")) or {}
        merged = dict(base)
        merged.update(
            {
                "id": f"DRAFT:{solution['id']}",
                "parameters": dict(draft.get("parameters") or {}),
                "materials": dict(draft.get("materials") or {}),
                "explicit_parameter_ids": list(draft.get("explicit_parameter_ids") or []),
            }
        )
        payload, version, digest = self._snapshot(solution, merged)
        row = dict(draft)
        row["motor_snapshot"] = payload
        row["motor_snapshot_schema_version"] = version
        row["motor_snapshot_hash"] = digest
        row["motor_snapshot_persisted"] = False
        return row

    def list_project_solutions(self, project_id: str) -> list[dict[str, Any]]:
        return [self._canonical_payload(item) or {} for item in self.repository.list_for_project(project_id)]

    def get_solution(self, solution_id: str) -> dict[str, Any] | None:
        solution = self.repository.get_solution(solution_id)
        if solution is None:
            return None
        solution["revisions"] = [self._with_snapshot(solution, revision) for revision in solution.get("revisions") or []]
        return self._canonical_payload(solution)

    def get_revision(self, revision_id: str) -> dict[str, Any] | None:
        revision = self.repository.get_revision(revision_id)
        if revision is None:
            return None
        solution = self.repository.get_solution(str(revision.get("solution_id") or ""), include_revisions=False)
        if solution is not None:
            revision = self._with_snapshot(solution, revision)
        return self._canonical_payload(revision)

    def get_draft(self, solution_id: str) -> dict[str, Any] | None:
        solution = self.repository.get_solution(solution_id, include_revisions=False)
        if solution is None:
            raise KeyError(solution_id)
        return self._canonical_payload(self._draft_with_snapshot(solution, self.repository.get_draft(solution_id)))

    def save_draft(
        self,
        solution_id: str,
        *,
        base_revision_id: str,
        parameters: dict[str, Any],
        materials: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        active_view: str = "radial",
        notes: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        solution = self.repository.get_solution(solution_id, include_revisions=False)
        if solution is None:
            raise KeyError(solution_id)
        draft = self.repository.save_draft(
            solution_id,
            base_motor_revision_id=base_revision_id,
            parameters=parameters,
            materials=materials,
            explicit_parameter_ids=explicit_parameter_ids,
            active_view=active_view,
            notes=notes,
            expected_version=expected_version,
        )
        expanded = self._draft_with_snapshot(solution, draft) or draft
        if expanded.get("motor_snapshot"):
            self.repository.persist_draft_snapshot(
                solution_id,
                dict(expanded["motor_snapshot"]),
                int(expanded.get("motor_snapshot_schema_version") or 1),
                str(expanded.get("motor_snapshot_hash") or ""),
            )
            expanded["motor_snapshot_persisted"] = True
        return self._canonical_payload(expanded) or {}

    def delete_draft(self, solution_id: str, *, expected_version: int | None = None) -> bool:
        if self.repository.get_solution(solution_id, include_revisions=False) is None:
            raise KeyError(solution_id)
        return self.repository.delete_draft(solution_id, expected_version=expected_version)

    def create_solution(self, project_id: str, name: str, motor_family: str, template_id: str) -> dict[str, Any]:
        return self._canonical_payload(self.repository.create_solution(project_id, name, motor_family, template_id)) or {}

    def create_from_template(
        self,
        *,
        project_id: str,
        name: str,
        template_id: str,
        motor_family: str | None = None,
        parameter_overrides: dict[str, Any] | None = None,
        material_overrides: dict[str, Any] | None = None,
        notes: str | None = None,
        source_snapshot: dict[str, Any] | None = None,
        capability_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        template = self.templates.get_template(template_id)
        family = motor_family or str(template.get("family_id") or template.get("motor_type") or template.get("topology") or "")
        parameters = self.domain.filter_design_parameters(template_id, {**dict(template.get("defaults") or {}), **dict(parameter_overrides or {})})
        materials = {
            "component_materials": dict(template.get("material_defaults") or {}),
            "material_provenance": {
                component: {
                    "source_kind": "template_mtt",
                    "source_template_id": template_id,
                    "source_key": ((template.get("material_default_metadata") or {}).get(component) or {}).get("selected_key"),
                }
                for component in (template.get("material_defaults") or {})
            },
        }
        if material_overrides:
            materials.update(dict(material_overrides))
        solution, revision_id = self.repository.create_solution_with_revision(
            project_id=project_id,
            name=name,
            motor_family=family,
            template_id=template_id,
            parameters=parameters,
            materials=materials,
            notes=notes or f"Created from template {template_id}",
            explicit_parameter_ids=list(parameter_overrides or {}),
            source_snapshot=source_snapshot,
            capability_snapshot=capability_snapshot,
        )
        self._persist_revision_snapshot(solution, revision_id)
        return self.get_solution(str(solution["id"])) or self._canonical_payload(solution) or {}

    def _revision_policy(
        self,
        solution: dict[str, Any],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | None,
    ) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
        template_id = str(solution.get("template_id") or "")
        cleaned = _clean(parameters)
        validation: dict[str, Any] = {"status": "NOT_EVALUATED", "issues": [], "blocking_count": 0}
        if not template_id:
            return cleaned, list(explicit_parameter_ids or []), validation
        try:
            template = self.templates.get_template(template_id)
        except KeyError:
            return cleaned, list(explicit_parameter_ids or []), validation
        stored = self.domain.filter_design_parameters(template_id, cleaned)
        explicit = [
            pid
            for pid in (explicit_parameter_ids or list(stored))
            if self.domain.parameter_scope(template_id, pid) == "design"
        ]
        merged = {**self.domain.filter_design_parameters(template_id, dict(template.get("defaults") or {})), **stored}
        geometry = validate_geometry_relations(merged, template, explicit)
        winding = validate_winding_relations(merged, template, explicit)
        issues = [*list(geometry.get("issues") or []), *list(winding.get("issues") or [])]
        blocking = [row for row in issues if row.get("severity") == "BLOCKING"]
        validation = {
            "status": "BLOCKED_DRAFT" if blocking else "PASS",
            "issues": issues,
            "blocking_count": len(blocking),
            "geometry": geometry,
            "winding": winding,
        }
        if blocking and self.logs:
            self.logs.audit(
                level="WARNING",
                component="solution_service",
                event_type="SOLUTION_REVISION_MODEL_BLOCKED",
                message=f"saved immutable motor revision with deterministic issues for {solution.get('id')}",
                payload={"solution_id": solution.get("id"), "template_id": template_id, "issues": blocking},
            )
        return stored, explicit, validation

    def create_revision(
        self,
        solution_id: str,
        *,
        parameters: dict[str, Any],
        materials: dict[str, Any],
        notes: str = "",
        explicit_parameter_ids: list[str] | None = None,
        automation_parameters: dict[str, dict[str, Any]] | None = None,
        capability_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        solution = self.get_solution(solution_id)
        if solution is None:
            raise KeyError(solution_id)
        stored, explicit, validation = self._revision_policy(solution, parameters, explicit_parameter_ids)
        created = self.repository.create_revision(
            solution_id,
            parameters=stored,
            materials=materials,
            notes=notes,
            explicit_parameter_ids=explicit,
            automation_parameters=automation_parameters,
            capability_snapshot=capability_snapshot,
        )
        created = self._persist_revision_snapshot(solution, str(created["id"]))
        created = self._canonical_payload(created) or created
        created["validation"] = validation
        return created
