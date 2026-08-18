from __future__ import annotations

import math
import hashlib
import json
from datetime import datetime, timezone
from typing import Any


MISSING_ISSUES = {"value_missing", "series_empty", "field_empty", "table_empty"}


def _valid_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _numeric_profile(values: Any) -> tuple[list[float], int]:
    if not isinstance(values, (list, tuple)):
        return [], 0
    finite = [float(value) for value in values if _valid_number(value)]
    return finite, len(values) - len(finite)


def _unit_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _validate_value(output_type: str, value: Any, metadata: dict[str, Any] | None = None) -> tuple[bool, str | None, dict[str, Any]]:
    """Validate data quality deeply enough for automated downstream use."""
    metadata = metadata or {}
    if output_type == "scalar":
        if value is None:
            return False, "value_missing", {}
        if not _valid_number(value):
            return False, "scalar_not_numeric_or_finite", {"python_type": type(value).__name__}
        number = float(value)
        profile = {"value": number, "finite": True}
        minimum = metadata.get("minimum")
        maximum = metadata.get("maximum")
        profile.update({"contract_minimum": minimum, "contract_maximum": maximum})
        if _valid_number(minimum) and number < float(minimum):
            return False, "scalar_below_contract_minimum", profile
        if _valid_number(maximum) and number > float(maximum):
            return False, "scalar_above_contract_maximum", profile
        return True, None, profile

    if output_type in {"series", "spectrum"}:
        if not isinstance(value, dict) or not value.get("x") or not value.get("y"):
            return False, "series_empty", {}
        x_values, y_values = value.get("x"), value.get("y")
        if not isinstance(x_values, (list, tuple)) or not isinstance(y_values, (list, tuple)):
            return False, "series_axes_not_arrays", {}
        if len(x_values) != len(y_values):
            return False, "series_length_mismatch", {"x_count": len(x_values), "y_count": len(y_values)}
        if len(x_values) < 2:
            return False, "series_too_short", {"point_count": len(x_values)}
        x_numeric, x_invalid = _numeric_profile(x_values)
        y_numeric, y_invalid = _numeric_profile(y_values)
        profile = {"point_count": len(x_values), "invalid_x_count": x_invalid, "invalid_y_count": y_invalid}
        if x_invalid or y_invalid:
            return False, "series_contains_non_finite_values", profile
        deltas = [x_numeric[index + 1] - x_numeric[index] for index in range(len(x_numeric) - 1)]
        profile.update({
            "x_min": min(x_numeric), "x_max": max(x_numeric),
            "y_min": min(y_numeric), "y_max": max(y_numeric),
            "x_monotonic": all(delta >= 0 for delta in deltas) or all(delta <= 0 for delta in deltas),
            "duplicate_x_count": sum(delta == 0 for delta in deltas),
        })
        declared_unit = _unit_token(metadata.get("unit"))
        payload_unit = _unit_token(value.get("y_unit"))
        profile.update({"declared_unit": metadata.get("unit"), "payload_unit": value.get("y_unit")})
        if declared_unit and payload_unit and declared_unit != payload_unit:
            return False, "series_unit_mismatch", profile
        return True, None, profile

    if output_type in {"map", "map2d"}:
        if not isinstance(value, dict) or not value:
            return False, "field_empty", {}
        x_values, y_values, z_values = value.get("x"), value.get("y"), value.get("z")
        if not isinstance(x_values, (list, tuple)) or not isinstance(y_values, (list, tuple)) or not isinstance(z_values, (list, tuple)):
            return False, "map_axes_or_values_missing", {}
        if not x_values or not y_values or len(z_values) != len(y_values):
            return False, "map_shape_mismatch", {"x_count": len(x_values), "y_count": len(y_values), "z_rows": len(z_values)}
        flattened: list[Any] = []
        for row in z_values:
            if not isinstance(row, (list, tuple)) or len(row) != len(x_values):
                return False, "map_shape_mismatch", {"x_count": len(x_values), "y_count": len(y_values), "z_rows": len(z_values)}
            flattened.extend(row)
        _, x_invalid = _numeric_profile(x_values)
        _, y_invalid = _numeric_profile(y_values)
        z_numeric, z_invalid = _numeric_profile(flattened)
        profile = {"shape": [len(y_values), len(x_values)], "value_count": len(flattened), "invalid_value_count": x_invalid + y_invalid + z_invalid}
        if x_invalid or y_invalid or z_invalid:
            return False, "map_contains_non_finite_values", profile
        profile.update({"z_min": min(z_numeric), "z_max": max(z_numeric)})
        declared_unit = _unit_token(metadata.get("unit"))
        payload_unit = _unit_token(value.get("z_unit"))
        profile.update({"declared_unit": metadata.get("unit"), "payload_unit": value.get("z_unit")})
        if declared_unit and payload_unit and declared_unit != payload_unit:
            return False, "map_unit_mismatch", profile
        return True, None, profile

    if output_type in {"mesh_field", "field"}:
        if not isinstance(value, dict) or not value:
            return False, "field_empty", {}
        if value.get("kind") == "native_fea_reference":
            frame_count = int(value.get("frame_count") or 0)
            return frame_count > 0, None if frame_count > 0 else "field_frame_missing", {
                "kind": "native_fea_reference", "frame_count": frame_count,
                "native_field": value.get("native_field"), "authority": value.get("authority"),
            }
        points = value.get("points") or value.get("nodes")
        values = value.get("values")
        if not isinstance(points, (list, tuple)) or not points or not isinstance(values, (list, tuple)) or len(points) != len(values):
            return False, "mesh_field_shape_invalid", {}
        numeric, invalid = _numeric_profile(values)
        profile = {"point_count": len(points), "invalid_value_count": invalid}
        if invalid:
            return False, "field_contains_non_finite_values", profile
        profile.update({"value_min": min(numeric), "value_max": max(numeric)})
        return True, None, profile

    if output_type == "vector_field":
        if not isinstance(value, dict) or not value:
            return False, "field_empty", {}
        points, vectors = value.get("points") or value.get("nodes"), value.get("vectors")
        if not isinstance(points, (list, tuple)) or not isinstance(vectors, (list, tuple)) or not points or len(points) != len(vectors):
            return False, "vector_field_shape_invalid", {}
        invalid = 0
        magnitudes: list[float] = []
        for vector in vectors:
            if not isinstance(vector, (list, tuple)) or len(vector) < 2 or not all(_valid_number(component) for component in vector[:2]):
                invalid += 1
                continue
            magnitudes.append(math.hypot(float(vector[0]), float(vector[1])))
        profile = {"vector_count": len(vectors), "invalid_vector_count": invalid}
        if invalid:
            return False, "vector_field_contains_non_finite_values", profile
        profile.update({"magnitude_min": min(magnitudes), "magnitude_max": max(magnitudes)})
        return True, None, profile

    if output_type == "table":
        if not isinstance(value, (dict, list)) or len(value) == 0:
            return False, "table_empty", {}
        if isinstance(value, dict) and ("columns" in value or "rows" in value):
            columns, rows = value.get("columns"), value.get("rows")
            if not isinstance(columns, list) or not columns or not isinstance(rows, list) or not rows:
                return False, "table_shape_invalid", {}
            invalid_rows = 0
            numeric_cells = 0
            nonempty_cells = 0
            for row in rows:
                if isinstance(row, dict):
                    if any(column not in row for column in columns):
                        invalid_rows += 1
                        continue
                    cells = [row.get(column) for column in columns]
                elif isinstance(row, (list, tuple)) and len(row) == len(columns):
                    cells = list(row)
                else:
                    invalid_rows += 1
                    continue
                nonempty_cells += sum(cell not in (None, "") for cell in cells)
                numeric_cells += sum(_valid_number(cell) for cell in cells if cell not in (None, ""))
            sampled_numeric_fraction = numeric_cells / nonempty_cells if nonempty_cells else 0.0
            numeric_fraction = float(value.get("numeric_cell_fraction") or sampled_numeric_fraction)
            profile = {
                "row_count": len(rows), "source_row_count": int(value.get("source_row_count") or len(rows)),
                "column_count": len(columns), "invalid_row_count": invalid_rows,
                "numeric_cell_fraction": round(numeric_fraction, 8),
                "sampled_numeric_cell_fraction": round(sampled_numeric_fraction, 8),
                "truncated": bool(value.get("truncated")),
                "authority": value.get("authority"), "source_sha256": value.get("source_sha256"),
            }
            if invalid_rows:
                return False, "table_rows_inconsistent", profile
            minimum_numeric = float(metadata.get("minimum_numeric_fraction") or 0.0)
            if numeric_fraction < minimum_numeric:
                return False, "table_numeric_coverage_too_low", profile
            if metadata.get("require_source_hash") and not (
                isinstance(value.get("source_sha256"), str) and len(value["source_sha256"]) == 64
            ):
                return False, "table_source_hash_missing", profile
            return True, None, profile
        row_count = len(value) if isinstance(value, list) else max((len(item) for item in value.values() if isinstance(item, list)), default=len(value))
        return True, None, {"row_count": row_count, "container": type(value).__name__, "legacy_shape": True}

    return value is not None, None if value is not None else "value_missing", {"python_type": type(value).__name__ if value is not None else None}


def build_extraction_contract(
    *, requested_outputs: list[str], required_outputs: list[str], output_schema: dict[str, Any],
    scalars: dict[str, Any], series: dict[str, Any], maps: dict[str, Any],
    fields: dict[str, Any] | None = None, vectors: dict[str, Any] | None = None,
    tables: dict[str, Any] | None = None, audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the V3 automatic extraction and data-quality contract."""
    stores = {
        "scalar": scalars, "series": series, "spectrum": series,
        "map": maps, "map2d": maps, "field": fields or {}, "mesh_field": fields or {},
        "vector_field": vectors or {}, "table": tables or {},
    }
    requested = list(dict.fromkeys([*required_outputs, *requested_outputs]))
    records: list[dict[str, Any]] = []
    for output_id in requested:
        metadata = output_schema.get(output_id) or {}
        output_type = str(metadata.get("type") or "scalar")
        value = stores.get(output_type, scalars).get(output_id)
        valid, issue, data_profile = _validate_value(output_type, value, metadata)
        extraction_audit = (audit or {}).get(output_id) if isinstance(audit, dict) else None
        records.append({
            "id": output_id,
            "label": metadata.get("label") or output_id,
            "unit": metadata.get("unit"),
            "unit_contract": "OUTPUT_REGISTRY_DECLARED" if metadata.get("unit") is not None else "UNSPECIFIED",
            "type": output_type,
            "required": output_id in required_outputs,
            "status": "EXTRACTED" if valid else "MISSING" if issue in MISSING_ISSUES else "INVALID",
            "issue": issue,
            "data_profile": data_profile,
            "extractor": extraction_audit.get("extractor") if isinstance(extraction_audit, dict) else None,
            "source": extraction_audit.get("source") if isinstance(extraction_audit, dict) else None,
        })
    missing_required = [row["id"] for row in records if row["required"] and row["status"] == "MISSING"]
    invalid_required = [row["id"] for row in records if row["required"] and row["status"] == "INVALID"]
    extracted = sum(row["status"] == "EXTRACTED" for row in records)
    invalid = sum(row["status"] == "INVALID" for row in records)
    required_count = sum(row["required"] for row in records)
    required_extracted = sum(row["required"] and row["status"] == "EXTRACTED" for row in records)
    eligible = not missing_required and not invalid_required
    contract = {
        "schema_version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE" if eligible else "INCOMPLETE",
        "qualification_eligible": eligible,
        "requested_count": len(records),
        "extracted_count": extracted,
        "invalid_count": invalid,
        "coverage_percent": round(100.0 * extracted / len(records), 1) if records else 100.0,
        "required_coverage_percent": round(100.0 * required_extracted / required_count, 1) if required_count else 100.0,
        "missing_required": missing_required,
        "invalid_required": invalid_required,
        "outputs": records,
    }
    contract["content_sha256"] = extraction_contract_sha256(contract)
    return contract


def extraction_contract_sha256(contract: dict[str, Any] | None) -> str | None:
    """Hash the deterministic engineering content, excluding timestamps and annotations."""
    if not isinstance(contract, dict):
        return None
    payload = {
        key: value for key, value in contract.items()
        if key not in {"created_at", "content_sha256", "artifact_schema_version", "artifact_integrity"}
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
