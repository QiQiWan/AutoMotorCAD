from __future__ import annotations

from typing import Any

from .contracts import EngineeringResultBase, ResultBundle


RESULT_PRESENTATION_CONTRACT_VERSION = "0.73-D"

PRIMARY_METRIC_PRIORITY = [
    "shaft_torque_nm",
    "efficiency_percent",
    "torque_ripple_percent",
    "output_power_w",
    "total_loss_w",
    "copper_loss_w",
    "stator_iron_loss_w",
    "magnet_loss_w",
    "winding_max_temperature_c",
    "magnet_temperature_c",
    "housing_temperature_c",
    "lab_shaft_torque_nm",
    "lab_efficiency_percent",
]


def metric_group(result_id: str) -> str:
    token = str(result_id or "").lower()
    if any(word in token for word in ("temperature", "temp", "heat")):
        return "thermal"
    if "loss" in token:
        return "loss"
    if any(word in token for word in ("torque", "efficiency", "power", "voltage", "current", "emf")):
        return "performance"
    if any(word in token for word in ("stress", "force", "nvh", "modal")):
        return "mechanical"
    return "other"


def metric_row(row: EngineeringResultBase) -> dict[str, Any]:
    value = getattr(row, "value", None) if row.result_type == "scalar" else None
    return {
        "id": row.result_id,
        "label": row.label or row.result_id,
        "unit": row.unit or "",
        "native_unit": row.native_unit,
        "type": row.result_type,
        "group": metric_group(row.result_id),
        "required": row.required,
        "status": row.status,
        "value": value,
        "quality_flags": list(row.quality_flags or []),
        "source": row.source,
        "native_name": row.native_name,
        "extractor": row.extractor,
    }


def metric_registry(bundle: ResultBundle | None) -> dict[str, Any]:
    if bundle is None:
        return {
            "contract_version": RESULT_PRESENTATION_CONTRACT_VERSION,
            "authority": "LegacyResultCompatibility",
            "metrics": [],
            "primary_metrics": [],
        }
    rows = [metric_row(row) for row in bundle.results]
    scalar_rows = [row for row in rows if row["type"] == "scalar" and row["status"] == "EXTRACTED"]
    by_id = {row["id"]: row for row in scalar_rows}
    primary = [by_id[result_id] for result_id in PRIMARY_METRIC_PRIORITY if result_id in by_id]
    if len(primary) < 8:
        primary_ids = {row["id"] for row in primary}
        primary.extend(row for row in scalar_rows if row["id"] not in primary_ids)
    return {
        "contract_version": RESULT_PRESENTATION_CONTRACT_VERSION,
        "authority": "ResultBundleV1",
        "metrics": rows,
        "primary_metrics": primary[:8],
    }
