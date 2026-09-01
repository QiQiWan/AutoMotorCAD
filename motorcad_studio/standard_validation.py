from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class StandardValidationPackageService:
    """V0.87-D one-click engineering validation planner/materializer.

    The package reuses immutable AnalysisDefinition objects. It does not bypass Studio
    or Motor-CAD prechecks; execution remains fail-closed through the existing analysis
    execution authority.
    """

    CONTRACT_VERSION = "0.87-D"

    def __init__(self, *, db: Any, workspace: Any, starters: Any, analysis_guidance: Any, registry: Any):
        self.db = db
        self.workspace = workspace
        self.starters = starters
        self.analysis_guidance = analysis_guidance
        self.registry = registry
        # Materialization performs a read-then-create sequence. Keep that sequence
        # single-flight inside the process so two rapid UI requests cannot create the
        # same standard analysis definition twice.
        self._materialize_lock = threading.RLock()

    def _context(self, project_id: str, design_revision_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        revision = self.workspace.get_design_revision(design_revision_id)
        if not revision:
            raise KeyError(design_revision_id)
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
        if not design or str(design.get("project_id") or "") != str(project_id):
            raise ValueError("Design Revision 不属于当前项目")
        source = dict(revision.get("source_snapshot") or {})
        starter_id = str(source.get("design_starter_id") or "")
        starter = None
        if starter_id:
            try:
                starter = self.starters.get(starter_id)
            except KeyError:
                starter = None
        if starter is None:
            starter = self.starters.find_for_template(str(design.get("template_id") or ""))
        if starter is None:
            raise ValueError("当前 Design Revision 没有可用的 Golden Motor 标准验证包")
        return revision, design, starter

    def preview(
        self,
        project_id: str,
        design_revision_id: str,
        *,
        decisions_by_analysis: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        revision, design, starter = self._context(project_id, design_revision_id)
        decisions_by_analysis = dict(decisions_by_analysis or {})
        steps: list[dict[str, Any]] = []
        for index, analysis_template_id in enumerate(starter.get("standard_analysis_package") or [], start=1):
            try:
                preview = self.analysis_guidance.preview_template(
                    str(analysis_template_id),
                    design_revision_id=design_revision_id,
                    decisions=decisions_by_analysis.get(str(analysis_template_id)) or {},
                )
                step = {
                    "sequence": index,
                    "analysis_template_id": analysis_template_id,
                    "label": (preview.get("template") or {}).get("label") or analysis_template_id,
                    "short_label": (preview.get("template") or {}).get("short_label") or analysis_template_id,
                    "module": (preview.get("template") or {}).get("module"),
                    "recipe_id": (preview.get("template") or {}).get("recipe_id"),
                    "ready": bool(preview.get("ready_to_create")),
                    "unresolved_decision_count": int(preview.get("unresolved_decision_count") or 0),
                    "common_decisions": deepcopy(preview.get("common_decisions") or []),
                    "requested_outputs": list((preview.get("definition") or {}).get("requested_outputs") or []),
                    "compute_cost_class": (preview.get("template") or {}).get("compute_cost_class"),
                    "compute_cost_weight": (preview.get("template") or {}).get("compute_cost_weight"),
                    "engineering_question": (preview.get("template") or {}).get("engineering_question") or (preview.get("template") or {}).get("intent") or "",
                    "when_to_use": (preview.get("template") or {}).get("when_to_use") or "",
                    "expected_runtime": (preview.get("template") or {}).get("expected_runtime") or (preview.get("template") or {}).get("compute_cost_class") or "",
                    "engineering_groups": list((preview.get("template") or {}).get("engineering_groups") or []),
                    "status": "READY" if preview.get("ready_to_create") else "NEEDS_INPUT",
                }
            except (KeyError, ValueError) as exc:
                step = {
                    "sequence": index,
                    "analysis_template_id": analysis_template_id,
                    "label": str(analysis_template_id),
                    "ready": False,
                    "unresolved_decision_count": 0,
                    "common_decisions": [],
                    "requested_outputs": [],
                    "status": "UNAVAILABLE",
                    "reason": str(exc),
                }
            steps.append(step)

        output_schema = self.registry.output_schema(str(design.get("template_id") or "") or None)
        scorecard = []
        for metric_id in starter.get("result_scorecard") or []:
            definition = output_schema.get(str(metric_id)) or {}
            scorecard.append({
                "metric_id": str(metric_id),
                "label": definition.get("label") or str(metric_id),
                "unit": definition.get("unit") or "",
                "type": definition.get("type") or "scalar",
                "engineering": deepcopy(definition.get("engineering") or {}),
            })
        coverage_by_metric: dict[str, list[dict[str, Any]]] = {}
        for metric in scorecard:
            metric_id = str(metric.get("metric_id") or "")
            coverage_by_metric[metric_id] = [
                {"sequence": step.get("sequence"), "analysis_template_id": step.get("analysis_template_id"), "label": step.get("label")}
                for step in steps
                if metric_id in [str(value) for value in (step.get("requested_outputs") or [])]
            ]
        missing_scorecard_metrics = [metric_id for metric_id, providers in coverage_by_metric.items() if not providers]
        ready = bool(steps) and all(step.get("ready") for step in steps) and not missing_scorecard_metrics
        package_identity = {
            "contract_version": self.CONTRACT_VERSION,
            "starter_id": starter.get("id"),
            "design_revision_id": design_revision_id,
            "analysis_templates": [str(x) for x in starter.get("standard_analysis_package") or []],
            "scorecard_metrics": [str(x) for x in starter.get("result_scorecard") or []],
        }
        package_id = f"SVP-{_hash(package_identity)[:12].upper()}"
        return {
            "schema_version": 1,
            "contract_version": self.CONTRACT_VERSION,
            "authority": "StandardValidationPackageV1",
            "package_id": package_id,
            "project_id": project_id,
            "design_revision_id": design_revision_id,
            "design_revision": revision.get("revision"),
            "design_id": revision.get("design_id"),
            "design_name": design.get("name"),
            "starter": {
                "id": starter.get("id"), "label": starter.get("label"), "short_label": starter.get("short_label"),
                "template_id": starter.get("template_id"), "family_id": starter.get("family_id"),
            },
            "label": starter.get("validation_package_label") or "标准设计验证",
            "policy": deepcopy(starter.get("validation_package_policy") or {}),
            "steps": steps,
            "scorecard_contract": scorecard,
            "scorecard_coverage": {
                "complete": not missing_scorecard_metrics,
                "covered_count": len(scorecard) - len(missing_scorecard_metrics),
                "metric_count": len(scorecard),
                "missing_metric_ids": missing_scorecard_metrics,
                "providers": coverage_by_metric,
            },
            "ready_to_materialize": ready,
            "blocking_step_count": sum(not bool(step.get("ready")) for step in steps) + len(missing_scorecard_metrics),
            "package_hash": _hash(package_identity),
        }

    def _existing_analysis(self, project_id: str, design_revision_id: str, starter_id: str, analysis_template_id: str) -> dict[str, Any] | None:
        rows = self.db.query_all(
            "SELECT id FROM analysis_definitions WHERE project_id=? AND design_revision_id=? ORDER BY updated_at DESC",
            (project_id, design_revision_id),
        )
        for row in rows:
            analysis = self.analysis_guidance.platform.get_analysis_definition(str(row.get("id")))
            if not analysis:
                continue
            revision = (analysis.get("revisions") or [{}])[0]
            guidance = ((revision.get("definition") or {}).get("analysis_guidance") or {})
            package = guidance.get("standard_validation_package") or {}
            if (
                str(package.get("contract_version") or "") == self.CONTRACT_VERSION
                and str(package.get("starter_id") or "") == str(starter_id)
                and str(package.get("design_revision_id") or "") == str(design_revision_id)
                and str(package.get("analysis_template_id") or "") == str(analysis_template_id)
            ):
                return analysis
            # Definitions created by an older Studio build may carry the Analysis
            # Template identity but predate standard_validation_package metadata.
            # Reuse them instead of materializing a visually identical row.
            if str(guidance.get("template_id") or "") == str(analysis_template_id):
                return analysis
        return None

    def materialize(
        self,
        project_id: str,
        design_revision_id: str,
        *,
        decisions_by_analysis: dict[str, dict[str, Any]] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        with self._materialize_lock:
            return self._materialize_locked(
                project_id,
                design_revision_id,
                decisions_by_analysis=decisions_by_analysis,
                notes=notes,
            )

    def _materialize_locked(
        self,
        project_id: str,
        design_revision_id: str,
        *,
        decisions_by_analysis: dict[str, dict[str, Any]] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        preview = self.preview(project_id, design_revision_id, decisions_by_analysis=decisions_by_analysis)
        if not preview.get("ready_to_materialize"):
            missing = ((preview.get("scorecard_coverage") or {}).get("missing_metric_ids") or [])
            if missing:
                raise ValueError("标准验证包尚不能覆盖 Engineering Scorecard：" + ", ".join(str(value) for value in missing))
            raise ValueError("标准验证包仍有不可用或需要工程师确认的分析步骤")
        decisions_by_analysis = dict(decisions_by_analysis or {})
        starter = preview["starter"]
        items = []
        for step in preview.get("steps") or []:
            template_id = str(step["analysis_template_id"])
            existing = self._existing_analysis(project_id, design_revision_id, str(starter["id"]), template_id)
            if existing:
                items.append({
                    "analysis_template_id": template_id,
                    "analysis_definition_id": existing.get("id"),
                    "analysis_revision_id": ((existing.get("revisions") or [{}])[0]).get("id"),
                    "status": "REUSED",
                    "label": step.get("label"),
                })
                continue
            metadata = {
                "standard_validation_package": {
                    "authority": "StandardValidationPackageV1",
                    "contract_version": self.CONTRACT_VERSION,
                    "package_id": preview.get("package_id"),
                    "starter_id": starter.get("id"),
                    "design_revision_id": design_revision_id,
                    "analysis_template_id": template_id,
                    "package_hash": preview.get("package_hash"),
                }
            }
            created = self.analysis_guidance.create_from_template(
                project_id,
                design_revision_id=design_revision_id,
                template_id=template_id,
                name=f"{starter.get('short_label') or starter.get('label')} · {step.get('short_label') or step.get('label')}",
                decisions=decisions_by_analysis.get(template_id) or {},
                notes=notes or f"Standard validation package {preview.get('package_id')} / {template_id}",
                guidance_metadata_extra=metadata,
            )
            analysis = created.get("analysis_definition") or {}
            items.append({
                "analysis_template_id": template_id,
                "analysis_definition_id": analysis.get("id"),
                "analysis_revision_id": ((analysis.get("revisions") or [{}])[0]).get("id"),
                "status": "CREATED",
                "label": step.get("label"),
            })
        return {
            **preview,
            "materialized": True,
            "analysis_definitions": items,
            "created_count": sum(item["status"] == "CREATED" for item in items),
            "reused_count": sum(item["status"] == "REUSED" for item in items),
        }


class EngineeringScorecardService:
    """V0.87-D design-revision scorecard assembled from authoritative ResultBundles."""

    CONTRACT_VERSION = "0.87-D"
    STATUS_RANK = {"FAIL": 5, "WARNING": 4, "MISSING": 3, "UNIT_MISMATCH": 3, "PASS": 2, "OBSERVED": 1}

    def __init__(self, *, db: Any, workspace: Any, starters: Any, registry: Any, result_viewer: Any, requirements: Any):
        self.db = db
        self.workspace = workspace
        self.starters = starters
        self.registry = registry
        self.result_viewer = result_viewer
        self.requirements = requirements

    def _context(self, project_id: str, design_revision_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        revision = self.workspace.get_design_revision(design_revision_id)
        if not revision:
            raise KeyError(design_revision_id)
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
        if not design or str(design.get("project_id") or "") != str(project_id):
            raise ValueError("Design Revision 不属于当前项目")
        source = dict(revision.get("source_snapshot") or {})
        starter = None
        if source.get("design_starter_id"):
            try:
                starter = self.starters.get(str(source.get("design_starter_id")))
            except KeyError:
                starter = None
        if starter is None:
            starter = self.starters.find_for_template(str(design.get("template_id") or ""))
        if starter is None:
            raise ValueError("当前 Design Revision 没有 Engineering Scorecard 契约")
        return revision, design, starter

    @staticmethod
    def _worst_requirement(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        rank = EngineeringScorecardService.STATUS_RANK
        return sorted(rows, key=lambda row: rank.get(str(row.get("status")), 0), reverse=True)[0]

    def build(self, project_id: str, design_revision_id: str) -> dict[str, Any]:
        revision, design, starter = self._context(project_id, design_revision_id)
        metric_ids = [str(x) for x in starter.get("result_scorecard") or []]
        output_schema = self.registry.output_schema(str(design.get("template_id") or "") or None)
        rows = self.db.query_all(
            """SELECT c.id case_id,c.execution_status,c.quality_status,c.result_bundle_id,c.finished_at,
                      t.id task_id,t.analysis,t.created_at
                 FROM cases c JOIN tasks t ON t.id=c.task_id
                WHERE t.project_id=? AND t.design_revision_id=?
                  AND c.execution_status IN ('SUCCEEDED','CACHED')
                ORDER BY COALESCE(c.finished_at,t.created_at) DESC""",
            (project_id, design_revision_id),
        )
        latest_metric: dict[str, dict[str, Any]] = {}
        evidence_cases: list[dict[str, Any]] = []
        for row in rows:
            payload = self.result_viewer.case_payload(str(row["case_id"]), hydrate_heavy=False)
            if not payload:
                continue
            scalars = ((payload.get("results") or {}).get("scalars") or {})
            evaluation = None
            bundle_id = str(row.get("result_bundle_id") or "")
            if bundle_id:
                try:
                    evaluation = self.requirements.evaluate_result_bundle(bundle_id)
                except (KeyError, ValueError, RuntimeError):
                    evaluation = None
            requirement_rows = (evaluation or {}).get("requirements") or []
            for metric_id in metric_ids:
                if metric_id in latest_metric or metric_id not in scalars:
                    continue
                req = self._worst_requirement([r for r in requirement_rows if str(r.get("metric_id") or "") == metric_id and r.get("applies")])
                latest_metric[metric_id] = {
                    "value": scalars.get(metric_id),
                    "case_id": row.get("case_id"),
                    "task_id": row.get("task_id"),
                    "analysis": row.get("analysis"),
                    "result_bundle_id": row.get("result_bundle_id"),
                    "quality_status": row.get("quality_status"),
                    "requirement": req,
                }
            evidence_cases.append({
                "case_id": row.get("case_id"), "task_id": row.get("task_id"), "analysis": row.get("analysis"),
                "result_bundle_id": row.get("result_bundle_id"), "quality_status": row.get("quality_status"),
            })

        cards = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for metric_id in metric_ids:
            definition = output_schema.get(metric_id) or {}
            engineering = deepcopy(definition.get("engineering") or {})
            evidence = latest_metric.get(metric_id)
            raw_value = evidence.get("value") if evidence else None
            status = "MISSING"
            requirement = evidence.get("requirement") if evidence else None
            if evidence:
                status = str((requirement or {}).get("status") or "OBSERVED")
            scale = float(engineering.get("display_scale") or 1.0)
            display_value = None
            if raw_value is not None:
                try:
                    display_value = float(raw_value) * scale
                except (TypeError, ValueError):
                    display_value = raw_value
            card = {
                "metric_id": metric_id,
                "label": definition.get("label") or metric_id,
                "unit": definition.get("unit") or "",
                "display_unit": engineering.get("display_unit") or definition.get("unit") or "",
                "value": raw_value,
                "display_value": display_value,
                "status": status,
                "engineering_group": engineering.get("engineering_group") or "其他",
                "favorable_direction": engineering.get("favorable_direction") or "target",
                "description": engineering.get("description") or definition.get("description") or "",
                "case_id": (evidence or {}).get("case_id"),
                "task_id": (evidence or {}).get("task_id"),
                "analysis": (evidence or {}).get("analysis"),
                "result_bundle_id": (evidence or {}).get("result_bundle_id"),
                "requirement": requirement,
            }
            cards.append(card)
            groups.setdefault(card["engineering_group"], []).append(card)

        missing = [card for card in cards if card["status"] == "MISSING"]
        failed = [card for card in cards if card["status"] == "FAIL"]
        warnings = [card for card in cards if card["status"] == "WARNING"]
        observed = [card for card in cards if card["status"] not in {"MISSING", "FAIL", "WARNING"}]
        if not evidence_cases:
            overall = "NO_RESULTS"
            conclusion = "尚无可用于当前设计版本的有效结果。"
        elif failed:
            overall = "NEEDS_ATTENTION"
            conclusion = f"{len(failed)} 项工程要求未满足，建议先处理阻断指标。"
        elif missing:
            overall = "INCOMPLETE"
            conclusion = f"已有部分结果，但仍缺少 {len(missing)} 个 Scorecard 指标。"
        elif warnings:
            overall = "READY_WITH_WARNING"
            conclusion = f"结果可用于工程判断，{len(warnings)} 项指标接近边界。"
        else:
            overall = "READY"
            conclusion = "标准 Scorecard 指标已齐全，可进入对比、扫描或优化决策。"
        return {
            "schema_version": 1,
            "contract_version": self.CONTRACT_VERSION,
            "authority": "EngineeringScorecardV1",
            "project_id": project_id,
            "design_revision_id": design_revision_id,
            "design_revision": revision.get("revision"),
            "design_id": revision.get("design_id"),
            "design_name": design.get("name"),
            "starter": {"id": starter.get("id"), "label": starter.get("label"), "short_label": starter.get("short_label")},
            "overall_status": overall,
            "conclusion": conclusion,
            "summary": {
                "metric_count": len(cards), "observed_count": len(observed), "missing_count": len(missing),
                "fail_count": len(failed), "warning_count": len(warnings), "evidence_case_count": len(evidence_cases),
            },
            "cards": cards,
            "groups": [{"group": group, "metrics": values} for group, values in groups.items()],
            "evidence_cases": evidence_cases[:20],
            "next_action": {
                "label": "运行标准设计验证" if overall in {"NO_RESULTS", "INCOMPLETE"} else ("处理未满足指标" if failed else "进入参数对比与优化"),
                "stage": "validate" if overall in {"NO_RESULTS", "INCOMPLETE"} else "decide",
            },
        }
