from __future__ import annotations

import math
from typing import Any


FEA_FIELDS = {
    "b", "bx", "by", "pt", "current_density", "eddy_current_density",
    "stress", "displacement",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _point_in_bounds(point: dict[str, Any], bounds: tuple[float, float, float, float] | None) -> bool:
    if bounds is None:
        return True
    x, y = _number(point.get("x")), _number(point.get("y"))
    return x is not None and y is not None and bounds[0] <= x <= bounds[1] and bounds[2] <= y <= bounds[3]


def _sample_indices(points: list[dict[str, Any]], field: str, limit: int) -> list[int]:
    """Preserve field extrema and region coverage, then fill by stable stride."""
    if len(points) <= limit:
        return list(range(len(points)))
    groups: dict[str, list[int]] = {}
    for index, point in enumerate(points):
        groups.setdefault(str(point.get("region") or ""), []).append(index)
    mandatory: set[int] = {0, len(points) - 1}
    for coordinate in ("x", "y"):
        finite_coordinates = [(index, _number(point.get(coordinate))) for index, point in enumerate(points)]
        finite_coordinates = [(index, value) for index, value in finite_coordinates if value is not None]
        if finite_coordinates:
            mandatory.add(min(finite_coordinates, key=lambda item: item[1])[0])
            mandatory.add(max(finite_coordinates, key=lambda item: item[1])[0])
    for indices in groups.values():
        if len(mandatory) >= limit:
            break
        mandatory.add(indices[0])
        mandatory.add(indices[-1])
        finite = [(index, _number(points[index].get(field))) for index in indices]
        finite = [(index, value) for index, value in finite if value is not None]
        if finite:
            mandatory.add(min(finite, key=lambda item: item[1])[0])
            mandatory.add(max(finite, key=lambda item: item[1])[0])
    mandatory = set(sorted(mandatory)[:limit])
    remaining = limit - len(mandatory)
    if remaining > 0:
        candidates = [index for index in range(len(points)) if index not in mandatory]
        if len(candidates) <= remaining:
            mandatory.update(candidates)
        else:
            stride = len(candidates) / remaining
            mandatory.update(candidates[min(len(candidates) - 1, int(offset * stride))] for offset in range(remaining))
    return sorted(mandatory)


def build_fea_frame_view(
    payload: dict[str, Any], *, field: str, region: str | None = None,
    max_points: int = 12000,
    bounds: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    if field not in FEA_FIELDS:
        raise ValueError(f"unsupported_fea_field: {field}")
    limit = max(250, min(20000, int(max_points)))
    source = payload.get("points") if isinstance(payload.get("points"), list) else []
    filtered = [
        point for point in source
        if isinstance(point, dict) and _number(point.get(field)) is not None
        and (not region or str(point.get("region") or "") == region)
        and _point_in_bounds(point, bounds)
    ]
    indices = _sample_indices(filtered, field, limit) if filtered else []
    selected = [filtered[index] for index in indices]
    node_ids = {
        str(node_id) for point in selected for node_id in (point.get("node_ids") or [])
        if node_id is not None
    }
    source_nodes = payload.get("mesh_nodes") if isinstance(payload.get("mesh_nodes"), list) else []
    mesh_nodes = [node for node in source_nodes if str(node.get("id")) in node_ids]
    values = [float(point[field]) for point in selected]
    x_values = [float(point["x"]) for point in filtered if _number(point.get("x")) is not None]
    y_values = [float(point["y"]) for point in filtered if _number(point.get("y")) is not None]
    data_bounds = [min(x_values), max(x_values), min(y_values), max(y_values)] if x_values and y_values else None
    selected_x = [float(point["x"]) for point in selected if _number(point.get("x")) is not None]
    selected_y = [float(point["y"]) for point in selected if _number(point.get("y")) is not None]
    return {
        "schema_version": 1,
        "frame_schema_version": payload.get("schema_version"),
        "index": payload.get("index"),
        "step": payload.get("step"),
        "field": field,
        "region": region,
        "bounds": list(bounds) if bounds else None,
        "data_bounds": data_bounds,
        "point_count": len(selected),
        "filtered_point_count": len(filtered),
        "frame_point_count": len(source),
        "source_point_count": payload.get("source_point_count") or len(source),
        "truncated": len(selected) < len(filtered),
        "sampling": {
            "strategy": "region_extrema_stride_lod_v1",
            "requested_limit": limit,
            "field_extrema_preserved": bool(selected) and min(values) == min(float(point[field]) for point in filtered) and max(values) == max(float(point[field]) for point in filtered),
            "coordinate_extrema_preserved": bool(data_bounds and selected_x and selected_y) and [min(selected_x), max(selected_x), min(selected_y), max(selected_y)] == data_bounds,
            "region_coverage_preserved": {str(point.get("region") or "") for point in selected} == {str(point.get("region") or "") for point in filtered},
        },
        "regions": sorted({str(point.get("region")) for point in selected if point.get("region") not in (None, "")}),
        "mesh_complete": bool(payload.get("mesh_complete")) and all(
            len(point.get("node_ids") or []) >= 3 for point in selected
        ),
        "mesh_nodes": mesh_nodes,
        "points": selected,
    }
