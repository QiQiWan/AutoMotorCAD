from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Iterable


NATIVE_SPATIAL_GEOMETRY_AUTHORITY = "NativeSpatialGeometryAuthorityV1"
NATIVE_RESULT_OVERLAY_AUTHORITY = "NativeSpatialResultOverlayAuthorityV1"
NATIVE_SPATIAL_GEOMETRY_SCHEMA_VERSION = 1
NATIVE_RESULT_OVERLAY_SCHEMA_VERSION = 1


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coord(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        x = _finite(value.get("x"))
        y = _finite(value.get("y"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x = _finite(value[0])
        y = _finite(value[1])
    else:
        x = _finite(getattr(value, "x", None))
        y = _finite(getattr(value, "y", None))
    return [x, y] if x is not None and y is not None else None


def _text_attr(value: Any, name: str) -> str | None:
    try:
        raw = getattr(value, name, None)
    except Exception:
        raw = None
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _number_attr(value: Any, name: str) -> float | int | None:
    try:
        raw = getattr(value, name, None)
    except Exception:
        return None
    number = _finite(raw)
    if number is None:
        return None
    return int(number) if number.is_integer() else number


def _entity_kind(entity: Any) -> str:
    token = entity.__class__.__name__.lower()
    if "arc" in token:
        return "arc"
    if "line" in token:
        return "line"
    return token or "entity"


def _sample_arc(start: list[float], end: list[float], centre: list[float], *, max_segments: int = 32) -> list[list[float]]:
    cx, cy = centre
    sx, sy = start
    ex, ey = end
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    sweep = (a1 - a0) % (2.0 * math.pi)
    if sweep <= 1.0e-12:
        sweep = 2.0 * math.pi
    radius = math.hypot(sx - cx, sy - cy)
    if radius <= 1.0e-12:
        return [start, end]
    segments = max(3, min(max_segments, int(math.ceil(sweep / (math.pi / 18.0)))))
    points = []
    for index in range(segments + 1):
        angle = a0 + sweep * index / segments
        points.append([cx + radius * math.cos(angle), cy + radius * math.sin(angle)])
    points[0] = list(start)
    points[-1] = list(end)
    return points


def _entity_payload(entity: Any) -> tuple[dict[str, Any], list[list[float]], bool]:
    kind = _entity_kind(entity)
    start = _coord(getattr(entity, "start", None))
    end = _coord(getattr(entity, "end", None))
    payload: dict[str, Any] = {"kind": kind, "start": start, "end": end}
    points: list[list[float]] = []
    complete = start is not None and end is not None
    if kind == "arc":
        centre = _coord(getattr(entity, "centre", None)) or _coord(getattr(entity, "center", None))
        radius = _number_attr(entity, "radius")
        payload["centre"] = centre
        payload["radius"] = radius
        payload["total_angle"] = _number_attr(entity, "total_angle")
        payload["length"] = _number_attr(entity, "length")
        if start and end and centre:
            points = _sample_arc(start, end, centre)
        elif start and end:
            points = [start, end]
            complete = False
    elif start and end:
        points = [start, end]
    else:
        complete = False
    payload["display_points"] = points
    return payload, points, complete


def _bounds(points: Iterable[list[float]]) -> dict[str, float] | None:
    values = [(float(point[0]), float(point[1])) for point in points if len(point) >= 2 and _finite(point[0]) is not None and _finite(point[1]) is not None]
    if not values:
        return None
    xs = [item[0] for item in values]
    ys = [item[1] for item in values]
    return {"xmin": min(xs), "xmax": max(xs), "ymin": min(ys), "ymax": max(ys)}


def _iter_tree_regions(tree: Any) -> list[tuple[str, Any]]:
    if tree is None:
        return []
    rows: list[tuple[str, Any]] = []
    try:
        items = list(tree.items()) if hasattr(tree, "items") else []
    except Exception:
        items = []
    for key, value in items:
        if value is None:
            continue
        name = _text_attr(value, "name") or str(key or "").strip()
        if not name or name.lower() in {"root", "geometry", "regions", "children"}:
            continue
        # GeometryTree behaves as a mapping of TreeRegion/TreeRegionMagnet values.
        # Do not probe ``entities`` here: some native property getters can raise
        # and those failures must be preserved later as PARTIAL boundary evidence.
        rows.append((name, value))
    return rows


def capture_native_spatial_geometry(
    mc: Any,
    *,
    geometry_tree: Any | None = None,
    design_snapshot_hash: str | None = None,
    binding_plan_hash: str | None = None,
    model_source_fingerprint: str | None = None,
    design_state_hash: str | None = None,
    max_regions: int = 320,
    max_entities: int = 20000,
) -> dict[str, Any]:
    """Capture bounded, exact Motor-CAD region boundaries from the live geometry tree.

    The payload stores native line/arc entities and a deterministic display polyline.
    It does not infer CAD boundaries from Studio parameters. GeometryTree is the
    preferred 2026R1 source; Maxwell UDM JSON is recorded only as supplementary
    provenance when available.
    """
    errors: list[str] = []
    boundary_errors: list[str] = []
    warnings: list[str] = []
    tree = geometry_tree
    if tree is None and hasattr(mc, "get_geometry_tree"):
        try:
            tree = mc.get_geometry_tree()
        except Exception as exc:
            message = f"get_geometry_tree: {type(exc).__name__}: {exc}"
            errors.append(message)
            boundary_errors.append(message)
    elif tree is None:
        message = "get_geometry_tree: API_UNAVAILABLE"
        errors.append(message)
        boundary_errors.append(message)
    regions_raw = _iter_tree_regions(tree)
    truncated_regions = len(regions_raw) > max_regions
    regions_raw = regions_raw[:max_regions]
    regions: list[dict[str, Any]] = []
    all_points: list[list[float]] = []
    entity_count = 0
    incomplete_entity_count = 0
    truncated_entities = False

    for native_name, region in regions_raw:
        try:
            entities = list(getattr(region, "entities", None) or [])
        except Exception as exc:
            entities = []
            message = f"region:{native_name}:entities: {type(exc).__name__}: {exc}"
            errors.append(message)
            boundary_errors.append(message)
        remaining = max(0, max_entities - entity_count)
        if len(entities) > remaining:
            entities = entities[:remaining]
            truncated_entities = True
        entity_rows: list[dict[str, Any]] = []
        region_points: list[list[float]] = []
        for entity in entities:
            item, points, complete = _entity_payload(entity)
            entity_rows.append(item)
            region_points.extend(points)
            entity_count += 1
            if not complete:
                incomplete_entity_count += 1
            if entity_count >= max_entities:
                truncated_entities = True
                break
        all_points.extend(region_points)
        colour = None
        try:
            raw_colour = getattr(region, "colour", None)
            if raw_colour is not None:
                colour = str(raw_colour)
        except Exception:
            pass
        try:
            singular_raw = getattr(region, "singular", None)
            singular = bool(singular_raw) if singular_raw is not None else None
        except Exception as exc:
            singular = None
            warnings.append(f"region:{native_name}:singular: {type(exc).__name__}: {exc}")
        regions.append({
            "name": native_name,
            "region_type": _text_attr(region, "region_type") or _text_attr(region, "type"),
            "material": _text_attr(region, "material"),
            "colour": colour,
            "parent_name": _text_attr(region, "parent_name"),
            "duplications": _number_attr(region, "duplications"),
            "duplication_angle_deg": _number_attr(region, "duplication_angle"),
            "singular": singular,
            "entity_count": len(entity_rows),
            "entities": entity_rows,
            "bounds": _bounds(region_points),
            "closed_candidate": bool(entity_rows and all(row.get("start") and row.get("end") for row in entity_rows)),
        })
        if entity_count >= max_entities:
            break

    maxwell_udm_digest = None
    if hasattr(mc, "get_maxwell_udm_geometry_json"):
        try:
            maxwell_udm = mc.get_maxwell_udm_geometry_json()
            if maxwell_udm:
                maxwell_udm_digest = _stable_hash(maxwell_udm)
        except Exception as exc:
            warnings.append(f"get_maxwell_udm_geometry_json: {type(exc).__name__}: {exc}")

    drawable_regions = [row for row in regions if row.get("entity_count")]
    complete = bool(drawable_regions) and not truncated_regions and not truncated_entities and incomplete_entity_count == 0 and not boundary_errors
    status = "COMPLETE" if complete else "PARTIAL" if drawable_regions else "UNAVAILABLE"
    core = {
        "schema_version": NATIVE_SPATIAL_GEOMETRY_SCHEMA_VERSION,
        "authority": NATIVE_SPATIAL_GEOMETRY_AUTHORITY,
        "status": status,
        "source_api": "get_geometry_tree" if tree is not None else None,
        "coordinate_system": {
            "frame": "motorcad_native_xy",
            "origin": [0.0, 0.0],
            "axis_order": ["x", "y"],
            "unit": None,
            "unit_status": "SOURCE_NATIVE_UNVERIFIED",
            "orientation": "native_geometry_tree",
        },
        "lineage": {
            "design_snapshot_hash": design_snapshot_hash,
            "binding_plan_hash": binding_plan_hash,
            "model_source_fingerprint": model_source_fingerprint,
            "design_state_hash": design_state_hash,
        },
        "region_count": len(regions),
        "drawable_region_count": len(drawable_regions),
        "entity_count": entity_count,
        "incomplete_entity_count": incomplete_entity_count,
        "truncated": bool(truncated_regions or truncated_entities),
        "regions": regions,
        "bounds": _bounds(all_points),
        "maxwell_udm_geometry_digest": maxwell_udm_digest,
        "boundary_errors": boundary_errors,
        "warnings": warnings,
        "errors": errors,
    }
    core["content_hash"] = _stable_hash(core)
    return core


def _intersection_ratio(inner: dict[str, Any] | None, outer: dict[str, Any] | None) -> float | None:
    if not inner or not outer:
        return None
    try:
        ix0, ix1, iy0, iy1 = map(float, (inner["xmin"], inner["xmax"], inner["ymin"], inner["ymax"]))
        ox0, ox1, oy0, oy1 = map(float, (outer["xmin"], outer["xmax"], outer["ymin"], outer["ymax"]))
    except (KeyError, TypeError, ValueError):
        return None
    area = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if area <= 0:
        return None
    overlap = max(0.0, min(ix1, ox1) - max(ix0, ox0)) * max(0.0, min(iy1, oy1) - max(iy0, oy0))
    return overlap / area


def bind_fea_manifest_lineage(manifest: dict[str, Any] | None, native_model_snapshot: Any | None) -> dict[str, Any] | None:
    """Bind an exported FEA manifest to the exact post-solve NativeModelSnapshot."""
    if not isinstance(manifest, dict):
        return manifest
    snapshot = native_model_snapshot.model_dump(mode="json") if hasattr(native_model_snapshot, "model_dump") else dict(native_model_snapshot or {})
    if not snapshot:
        return manifest
    preview = dict(snapshot.get("preview_projection") or {})
    spatial = dict(preview.get("spatial_geometry") or {})
    manifest["native_lineage"] = {
        "binding_plan_hash": snapshot.get("binding_plan_hash"),
        "design_snapshot_hash": snapshot.get("design_snapshot_hash"),
        "model_source_fingerprint": snapshot.get("model_source_fingerprint"),
        "native_model_snapshot_phase": snapshot.get("phase"),
        "native_model_snapshot_status": snapshot.get("status"),
        "native_model_snapshot_hash": _stable_hash(snapshot),
        "native_model_design_state_hash": (snapshot.get("metadata") or {}).get("design_state_hash") or preview.get("design_state_hash"),
        "spatial_geometry_hash": spatial.get("content_hash"),
        "spatial_geometry_status": spatial.get("status"),
    }
    return manifest


class NativeSpatialResultOverlayAuthority:
    """Reconcile exact native region boundaries with Motor-CAD FEA result points.

    The authority never interpolates a field when mesh connectivity is absent. It
    returns native region boundaries plus either native mesh-contour capability or
    point-overlay capability, with strict Design/solve lineage checks.
    """

    authority = NATIVE_RESULT_OVERLAY_AUTHORITY

    def build(self, *, native_model_snapshot: dict[str, Any] | Any | None, fea_manifest: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = native_model_snapshot.model_dump(mode="json") if hasattr(native_model_snapshot, "model_dump") else dict(native_model_snapshot or {})
        manifest = dict(fea_manifest or {})
        preview = dict(snapshot.get("preview_projection") or {})
        spatial = dict(preview.get("spatial_geometry") or {})
        normalization = dict(manifest.get("normalization") or {})
        validation = dict(manifest.get("validation") or {})
        lineage = dict(manifest.get("native_lineage") or {})
        blockers: list[str] = []
        warnings: list[str] = []

        expected = {
            "binding_plan_hash": snapshot.get("binding_plan_hash"),
            "design_snapshot_hash": snapshot.get("design_snapshot_hash"),
            "model_source_fingerprint": snapshot.get("model_source_fingerprint"),
            "native_model_design_state_hash": (snapshot.get("metadata") or {}).get("design_state_hash") or preview.get("design_state_hash"),
            "spatial_geometry_hash": spatial.get("content_hash"),
        }
        lineage_matches: dict[str, bool | None] = {}
        for key, expected_value in expected.items():
            actual = lineage.get(key)
            if expected_value and actual:
                lineage_matches[key] = str(expected_value) == str(actual)
                if not lineage_matches[key]:
                    blockers.append(f"LINEAGE_MISMATCH:{key}")
            else:
                lineage_matches[key] = None
                blockers.append(f"LINEAGE_MISSING:{key}")

        if snapshot.get("phase") != "post_solve":
            blockers.append("NATIVE_MODEL_NOT_POST_SOLVE")
        if snapshot.get("status") != "QUALIFIED":
            blockers.append("NATIVE_MODEL_NOT_QUALIFIED")
        if spatial.get("status") != "COMPLETE":
            blockers.append("SPATIAL_GEOMETRY_INCOMPLETE")
        if not normalization.get("normalized"):
            blockers.append("FEA_NORMALIZATION_UNAVAILABLE")
        if validation and validation.get("qualification_eligible") is not True:
            blockers.append("FEA_CONTRACT_NOT_QUALIFIED")

        fea_bounds = normalization.get("coordinate_bounds") if isinstance(normalization.get("coordinate_bounds"), dict) else None
        geometry_bounds = spatial.get("bounds") if isinstance(spatial.get("bounds"), dict) else None
        containment = _intersection_ratio(fea_bounds, geometry_bounds)
        if containment is None:
            warnings.append("COORDINATE_ALIGNMENT_UNVERIFIED")
            alignment = "UNVERIFIED"
        elif containment >= 0.85:
            alignment = "CONFIRMED"
        elif containment >= 0.35:
            alignment = "PARTIAL"
            blockers.append("COORDINATE_ALIGNMENT_PARTIAL")
        else:
            alignment = "MISMATCH"
            blockers.append("COORDINATE_ALIGNMENT_MISMATCH")

        capabilities = dict(normalization.get("capabilities") or {})
        frame_count = int(normalization.get("frame_count") or 0)
        mesh_contour = bool(capabilities.get("filled_contours") and capabilities.get("mesh_edges"))
        point_overlay = bool(normalization.get("normalized") and frame_count > 0)
        if not point_overlay:
            blockers.append("RESULT_OVERLAY_POINTS_UNAVAILABLE")

        status = "QUALIFIED" if not blockers else "BLOCKED"
        result = {
            "schema_version": NATIVE_RESULT_OVERLAY_SCHEMA_VERSION,
            "authority": self.authority,
            "status": status,
            "render_mode": "native_mesh_contour" if status == "QUALIFIED" and mesh_contour else "native_point_overlay" if point_overlay else "unavailable",
            "native_spatial_geometry": deepcopy(spatial),
            "spatial_geometry_hash": spatial.get("content_hash"),
            "native_model_snapshot_hash": lineage.get("native_model_snapshot_hash"),
            "native_model_design_state_hash": expected.get("native_model_design_state_hash"),
            "lineage": {
                "expected": expected,
                "manifest": lineage,
                "matches": lineage_matches,
            },
            "coordinate_alignment": {
                "status": alignment,
                "fea_bounds": fea_bounds,
                "geometry_bounds": geometry_bounds,
                "fea_bounds_inside_geometry_ratio": containment,
                "coordinate_system": spatial.get("coordinate_system"),
            },
            "field_contract": {
                "available_fields": list(normalization.get("available_fields") or []),
                "regions": list(normalization.get("regions") or []),
                "frame_count": frame_count,
                "mesh_edges": bool(capabilities.get("mesh_edges")),
                "filled_contours": mesh_contour,
                "point_overlay": point_overlay,
                "interpolation_policy": "native_connectivity_only" if mesh_contour else "NO_INTERPOLATION",
            },
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "evidence_boundary": (
                "区域边界来自 Motor-CAD 2026R1 GeometryTree；场值来自同一 Case 的 save_fea_data 原生导出。"
                "缺少有限元连接时只叠加原生点，不生成插值等值云图。"
            ),
        }
        result["content_hash"] = _stable_hash(result)
        return result
