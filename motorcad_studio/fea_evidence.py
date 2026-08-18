from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fea_pipeline import build_fea_plan, validate_fea_manifest
from .native_fea_stream import normalize_native_fea_tables


@dataclass(frozen=True)
class NativeFEAExportConfig:
    enabled: bool = True
    outputs: str = "RegCode,X,Y,B,Pt,J,JEddy"
    regions: str = ""
    max_steps: int = 36
    max_points_per_frame: int = 6000
    separator: str = ","
    policy: str = "optional"
    required_fields: tuple[str, ...] = ()
    required_regions: tuple[str, ...] = ()
    require_coordinates: bool = True
    require_connectivity: bool = False
    min_field_coverage: float = 0.95
    max_coordinate_drop_fraction: float = 0.05
    min_points_per_frame: int = 2
    require_extrema_preserved: bool = True
    contract_id: str | None = None
    required_for_qualification: bool = False

    @classmethod
    def from_solver_settings(cls, solver_settings: dict[str, Any] | None, recipe_id: str = "emag") -> "NativeFEAExportConfig":
        root = solver_settings or {}
        raw = root.get("native_fea") if isinstance(root, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        plan = build_fea_plan(recipe_id, root)
        # Motor-CAD's official stress post-processing example exports SVM/Ux/Uy.
        # Request those documented names and derive displacement magnitude during
        # normalization.  Custom profiles may still request legacy aliases.
        default_outputs = "RegCode,X,Y,SVM,Ux,Uy" if recipe_id == "mechanical" else "RegCode,X,Y,B,Pt,J,JEddy"
        return cls(
            enabled=bool(plan["enabled"]),
            outputs=str(raw.get("outputs") or default_outputs),
            regions=str(raw.get("regions") or ""),
            max_steps=max(1, min(240, int(raw.get("max_steps") or 36))),
            max_points_per_frame=max(250, min(50000, int(raw.get("max_points_per_frame") or 6000))),
            separator=str(raw.get("separator") or ",")[:1] or ",",
            policy=str(plan["policy"]),
            required_fields=tuple(plan["required_fields"]),
            required_regions=tuple(plan["required_regions"]),
            require_coordinates=bool(plan["require_coordinates"]),
            require_connectivity=bool(plan["require_connectivity"]),
            min_field_coverage=float(plan["min_field_coverage"]),
            max_coordinate_drop_fraction=float(plan["max_coordinate_drop_fraction"]),
            min_points_per_frame=int(plan["min_points_per_frame"]),
            require_extrema_preserved=bool(plan["require_extrema_preserved"]),
            contract_id=str(plan["contract_id"]),
            required_for_qualification=bool(plan["required_for_qualification"]),
        )


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _norm(name: str) -> str:
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())


def _pick(headers: list[str], candidates: tuple[str, ...], *, fuzzy: bool = True) -> str | None:
    lookup = {_norm(header): header for header in headers}
    for candidate in candidates:
        if _norm(candidate) in lookup:
            return lookup[_norm(candidate)]
    if fuzzy:
        for header in headers:
            token = _norm(header)
            if any(_norm(candidate) in token for candidate in candidates):
                return header
    return None


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _scalar_id(value: Any) -> int | str | None:
    number = _to_float(value)
    if number is not None:
        return int(number) if number.is_integer() else str(number)
    text = str(value or "").strip()
    return text or None


FIELD_NAMES = (
    "b", "bx", "by", "pt", "current_density", "eddy_current_density",
    "stress", "displacement",
)


def _engineering_sample(rows: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministically retain region coverage and every available field extrema.

    A plain row stride can silently remove a local peak and then distort both the
    plotted range and engineering interpretation.  This sampler first pins spatial
    bounds, one point per region and min/max points for every field.  Remaining
    capacity is filled uniformly without duplicating rows.
    """
    if len(rows) <= limit:
        return rows, {
            "strategy": "full_resolution",
            "source_count": len(rows),
            "output_count": len(rows),
            "retained_fraction": 1.0,
            "region_coverage": 1.0,
            "extrema_preserved": True,
        }

    selected: set[int] = set()
    numeric_fields = [field for field in FIELD_NAMES if any(field in row for row in rows)]

    def pin(index: int | None) -> None:
        if index is not None and len(selected) < limit:
            selected.add(index)

    for coordinate in ("x", "y"):
        values = [(index, _to_float(row.get(coordinate))) for index, row in enumerate(rows)]
        finite = [(index, value) for index, value in values if value is not None]
        if finite:
            pin(min(finite, key=lambda item: item[1])[0])
            pin(max(finite, key=lambda item: item[1])[0])

    first_by_region: dict[str, int] = {}
    for index, row in enumerate(rows):
        region = str(row.get("region") or "")
        if region and region not in first_by_region:
            first_by_region[region] = index
    for index in first_by_region.values():
        pin(index)

    extrema_indices: dict[str, tuple[int, int]] = {}
    for field in numeric_fields:
        finite = [(index, float(row[field])) for index, row in enumerate(rows) if _to_float(row.get(field)) is not None]
        if not finite:
            continue
        low = min(finite, key=lambda item: item[1])[0]
        high = max(finite, key=lambda item: item[1])[0]
        extrema_indices[field] = (low, high)
        pin(low)
        pin(high)

    remaining = limit - len(selected)
    if remaining > 0:
        step = len(rows) / float(remaining)
        for offset in range(remaining):
            candidate = min(len(rows) - 1, int((offset + 0.5) * step))
            if candidate not in selected:
                selected.add(candidate)
                continue
            # Search deterministically around a collision so the contract reaches
            # the requested capacity whenever possible.
            for delta in range(1, len(rows)):
                alternatives = (candidate + delta, candidate - delta)
                available = next((item for item in alternatives if 0 <= item < len(rows) and item not in selected), None)
                if available is not None:
                    selected.add(available)
                    break
            if len(selected) >= limit:
                break

    ordered_indices = sorted(selected)[:limit]
    sampled = [rows[index] for index in ordered_indices]
    source_regions = {str(row.get("region")) for row in rows if row.get("region") not in (None, "")}
    sampled_regions = {str(row.get("region")) for row in sampled if row.get("region") not in (None, "")}
    extrema_preserved = all(low in selected and high in selected for low, high in extrema_indices.values())
    return sampled, {
        "strategy": "region_extrema_uniform_v1",
        "source_count": len(rows),
        "output_count": len(sampled),
        "retained_fraction": round(len(sampled) / len(rows), 8),
        "region_coverage": round(len(sampled_regions) / len(source_regions), 8) if source_regions else 1.0,
        "extrema_preserved": extrema_preserved,
        "preserved_fields": sorted(extrema_indices),
    }


def _table_header(lines: list[str], table_line: int, data_line: int) -> list[str]:
    candidates: list[list[str]] = []
    for line in lines[table_line + 1:data_line]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and any(any(character.isalpha() for character in part) for part in parts):
            candidates.append(parts)
    return candidates[-1] if candidates else []


def _parse_motorcad_table_export(text: str, requested_outputs: str | None) -> dict[str, Any] | None:
    """Parse the native Motor-CAD table format emitted by ``save_fea_data``.

    The official PyMotorCAD stress post-processing example documents a file that
    starts with ``<table> <count> ElementsTable`` followed by four descriptive
    lines and element rows.  Each element row starts with TriIndex/Node1/Node2/
    Node3, followed by the outputs requested from ``save_fea_data``.  We detect
    that structure instead of assuming a conventional CSV header.
    """
    lines = text.splitlines()
    table_pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+(ElementsTable|NodesTable|RegionsTable)\s*$", re.IGNORECASE)
    outputs = [token.strip() for token in str(requested_outputs or "").split(",") if token.strip()]
    if not outputs:
        return None
    headers = ["TriIndex", "Node1", "Node2", "Node3", *outputs, "Step"]
    rows: list[dict[str, Any]] = []
    node_coordinates: dict[str, list[float]] = {}
    region_names: dict[str, str] = {}
    table_counts = {"elements": 0, "nodes": 0, "regions": 0}
    block_index = 0
    for index, line in enumerate(lines):
        match = table_pattern.match(line)
        if not match:
            continue
        count = int(match.group(2))
        table_name = match.group(3).lower()
        if table_name != "elementstable":
            start: int | None = None
            for probe in range(index + 1, min(len(lines), index + count + 16)):
                parts = [part.strip() for part in lines[probe].split(",")]
                if len(parts) < 2 or _to_float(parts[0]) is None:
                    continue
                start = probe
                break
            if start is None:
                continue
            detected_headers = _table_header(lines, index, start)
            parsed = 0
            for cursor in range(start, min(len(lines), start + count)):
                parts = [part.strip() for part in lines[cursor].split(",")]
                if len(parts) < 2 or _to_float(parts[0]) is None:
                    break
                if table_name == "nodestable" and detected_headers:
                    node_key = _pick(detected_headers, ("NodeIndex", "NodeID", "Node", "Index"), fuzzy=False)
                    node_x_key = _pick(detected_headers, ("X", "XCoord", "XCoordinate", "NodeX"))
                    node_y_key = _pick(detected_headers, ("Y", "YCoord", "YCoordinate", "NodeY"))
                    row = {name: parts[position] for position, name in enumerate(detected_headers) if position < len(parts)}
                    node_id = _scalar_id(row.get(node_key)) if node_key else None
                    x = _to_float(row.get(node_x_key)) if node_x_key else None
                    y = _to_float(row.get(node_y_key)) if node_y_key else None
                    if node_id is not None and x is not None and y is not None:
                        node_coordinates[str(node_id)] = [x, y]
                elif table_name == "regionstable":
                    # The official Motor-CAD example documents region code in the
                    # first column and region name in the final column.
                    region_id = _scalar_id(parts[0])
                    region_name = parts[-1].strip()
                    if region_id is not None and region_name and _to_float(region_name) is None:
                        region_names[str(region_id)] = region_name
                parsed += 1
            if table_name == "nodestable":
                table_counts["nodes"] += parsed
            else:
                table_counts["regions"] += parsed
            continue
        block_index += 1
        expected = 4 + len(outputs)
        start: int | None = None
        # The documented format contains four descriptive/header lines.  Search a
        # small bounded window as a compatibility guard for minor release changes.
        for probe in range(index + 1, min(len(lines), index + 12)):
            parts = [part.strip() for part in lines[probe].split(",")]
            if len(parts) < expected:
                continue
            try:
                int(float(parts[0])); int(float(parts[1])); int(float(parts[2])); int(float(parts[3]))
            except (TypeError, ValueError):
                continue
            start = probe
            break
        if start is None:
            continue
        consumed = 0
        cursor = start
        while cursor < len(lines) and consumed < count:
            parts = [part.strip() for part in lines[cursor].split(",")]
            if len(parts) < expected:
                break
            try:
                int(float(parts[0])); int(float(parts[1])); int(float(parts[2])); int(float(parts[3]))
            except (TypeError, ValueError):
                break
            values = parts[:expected]
            row = {name: values[position] for position, name in enumerate(headers[:-1])}
            row["Step"] = str(block_index - 1)
            rows.append(row)
            consumed += 1
            cursor += 1
        table_counts["elements"] += consumed
    if not rows:
        return None
    return {
        "headers": headers,
        "rows": rows,
        "node_coordinates": node_coordinates,
        "region_names": region_names,
        "table_counts": table_counts,
    }


def normalize_fea_csv(raw_path: Path, frames_dir: Path, max_points_per_frame: int, requested_outputs: str | None = None) -> dict[str, Any]:
    """Normalize Motor-CAD ``save_fea_data`` CSV into browser-friendly frames.

    Motor-CAD may vary the column spelling across versions.  The parser is
    deliberately tolerant and records the discovered schema.  If coordinates
    cannot be located the raw export is still valid evidence and the caller
    receives ``normalized=False`` instead of synthetic field data.
    """
    try:
        with raw_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            sample = handle.read(8192)
    except OSError as exc:
        return {"normalized": False, "reason": f"raw_read_failed: {exc}"}
    if not sample.strip():
        return {"normalized": False, "reason": "raw_export_empty"}

    native_marker = re.search(r"^\s*\d+\s+\d+\s+(?:ElementsTable|NodesTable|RegionsTable)\s*$", sample, re.IGNORECASE | re.MULTILINE)
    if native_marker:
        return normalize_native_fea_tables(
            raw_path, frames_dir, max_points_per_frame, requested_outputs,
        )
    native_table = None
    source_format = "motorcad_table" if native_table else "delimited_table"
    delimiter = ","
    node_coordinates: dict[str, list[float]] = {}
    region_names: dict[str, str] = {}
    native_table_counts: dict[str, int] = {}
    if native_table:
        headers = list(native_table["headers"])
        raw_rows = list(native_table["rows"])
        raw_row_count = len(raw_rows)
        node_coordinates = dict(native_table.get("node_coordinates") or {})
        region_names = dict(native_table.get("region_names") or {})
        native_table_counts = dict(native_table.get("table_counts") or {})
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            if "\t" in sample:
                delimiter = "\t"
            elif ";" in sample:
                delimiter = ";"
        try:
            with raw_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                headers = list(csv.DictReader(handle, delimiter=delimiter).fieldnames or [])
        except (OSError, csv.Error) as exc:
            return {"normalized": False, "reason": f"csv_parse_failed: {type(exc).__name__}: {exc}"}

        def stream_rows():
            with raw_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                yield from (row for row in csv.DictReader(handle, delimiter=delimiter) if isinstance(row, dict))

        raw_rows = stream_rows()
        raw_row_count = 0

    if not headers:
        return {"normalized": False, "reason": "header_missing"}

    x_key = _pick(headers, ("X", "XCoord", "XCoordinate", "NodeX"))
    y_key = _pick(headers, ("Y", "YCoord", "YCoordinate", "NodeY"))
    step_key = _pick(headers, ("Step", "StepNumber", "TimeStep", "TimeStepNumber", "SolutionStep"))
    region_key = _pick(headers, ("RegCode", "RegionCode", "Region"))
    b_key = _pick(headers, ("B", "FluxDensity", "BMag", "BMagnitude"), fuzzy=False)
    bx_key = _pick(headers, ("Bx", "FluxDensityX"))
    by_key = _pick(headers, ("By", "FluxDensityY"))
    pt_key = _pick(headers, ("Pt", "VectorPotential", "A", "Az"))
    current_density_key = _pick(headers, ("J", "JMag", "CurrentDensity", "CurrentDensityMagnitude"), fuzzy=False)
    eddy_current_density_key = _pick(headers, ("JEddy", "EddyCurrentDensity", "EddyCurrentDensityMagnitude"), fuzzy=False)
    stress_key = _pick(headers, ("Stress", "VonMisesStress", "EquivalentStress", "SigmaVM", "SVM"), fuzzy=False)
    displacement_key = _pick(headers, ("Displacement", "TotalDisplacement", "DisplacementMagnitude"), fuzzy=False)
    ux_key = _pick(headers, ("Ux", "DisplacementX", "XDisplacement"), fuzzy=False)
    uy_key = _pick(headers, ("Uy", "DisplacementY", "YDisplacement"), fuzzy=False)
    element_key = _pick(headers, ("TriIndex", "ElementIndex", "ElementID", "Element"), fuzzy=False)
    node_keys = [
        key for key in (
            _pick(headers, ("Node1",), fuzzy=False),
            _pick(headers, ("Node2",), fuzzy=False),
            _pick(headers, ("Node3",), fuzzy=False),
        ) if key
    ]

    if not x_key or not y_key:
        return {
            "normalized": False,
            "reason": "coordinate_columns_not_found",
            "headers": headers,
            "row_count": raw_row_count if native_table else None,
        }

    grouped: dict[str, list[dict[str, Any]]] = {}
    dropped = 0
    for row in raw_rows:
        if not native_table:
            raw_row_count += 1
        x = _to_float(row.get(x_key))
        y = _to_float(row.get(y_key))
        if x is None or y is None:
            dropped += 1
            continue
        b = _to_float(row.get(b_key)) if b_key else None
        bx = _to_float(row.get(bx_key)) if bx_key else None
        by = _to_float(row.get(by_key)) if by_key else None
        if b is None and bx is not None and by is not None:
            b = math.hypot(bx, by)
        point: dict[str, Any] = {"x": x, "y": y}
        if b is not None:
            point["b"] = b
        if bx is not None:
            point["bx"] = bx
        if by is not None:
            point["by"] = by
        pt = _to_float(row.get(pt_key)) if pt_key else None
        if pt is not None:
            point["pt"] = pt
        current_density = _to_float(row.get(current_density_key)) if current_density_key else None
        if current_density is not None:
            point["current_density"] = current_density
        eddy_current_density = _to_float(row.get(eddy_current_density_key)) if eddy_current_density_key else None
        if eddy_current_density is not None:
            point["eddy_current_density"] = eddy_current_density
        stress = _to_float(row.get(stress_key)) if stress_key else None
        if stress is not None:
            point["stress"] = stress
        displacement = _to_float(row.get(displacement_key)) if displacement_key else None
        ux = _to_float(row.get(ux_key)) if ux_key else None
        uy = _to_float(row.get(uy_key)) if uy_key else None
        if displacement is None and ux is not None and uy is not None:
            displacement = math.hypot(ux, uy)
        if displacement is not None:
            point["displacement"] = displacement
        if region_key and row.get(region_key) not in (None, ""):
            region_code = str(_scalar_id(row.get(region_key)))
            point["region_code"] = region_code
            point["region"] = region_names.get(region_code, region_code)
        if element_key and row.get(element_key) not in (None, ""):
            point["element_id"] = _scalar_id(row.get(element_key))
        if node_keys:
            point["node_ids"] = [_scalar_id(row.get(key)) for key in node_keys if row.get(key) not in (None, "")]
        step_value = str(row.get(step_key) if step_key else 0)
        grouped.setdefault(step_value, []).append(point)

    if not grouped:
        return {"normalized": False, "reason": "no_numeric_points", "headers": headers}

    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_index: list[dict[str, Any]] = []
    field_columns = {
        "b": b_key or ("derived:hypot(Bx,By)" if bx_key and by_key else None),
        "bx": bx_key, "by": by_key, "pt": pt_key,
        "current_density": current_density_key,
        "eddy_current_density": eddy_current_density_key,
        "stress": stress_key,
        "displacement": displacement_key or ("derived:hypot(Ux,Uy)" if ux_key and uy_key else None),
        "region": region_key, "step": step_key,
    }
    available_fields = [field for field in FIELD_NAMES if field_columns.get(field)]
    all_values: dict[str, list[float]] = {field: [] for field in available_fields}
    all_regions: set[str] = set()
    sampling_records: list[dict[str, Any]] = []
    mesh_frame_count = 0
    coordinate_pairs: set[tuple[float, float]] = set()
    ordered = sorted(grouped.items(), key=lambda item: (_to_float(item[0]) is None, _to_float(item[0]) or 0.0, item[0]))
    for index, (step_value, points) in enumerate(ordered):
        # Engineering ranges are always computed from the complete source points,
        # independently of the browser display budget.
        frame_values = {
            field: [float(point[field]) for point in points if _to_float(point.get(field)) is not None]
            for field in available_fields
        }
        for field, values in frame_values.items():
            all_values[field].extend(values)
        all_regions.update(str(point["region"]) for point in points if point.get("region") not in (None, ""))
        coordinate_pairs.update((float(point["x"]), float(point["y"])) for point in points)

        sampled, sampling = _engineering_sample(points, max_points_per_frame)
        sampling_records.append({"frame_index": index, **sampling})
        referenced_node_ids = {
            str(node_id)
            for point in sampled for node_id in (point.get("node_ids") or [])
            if node_id is not None
        }
        mesh_complete = bool(
            sampled and node_coordinates
            and all(
                len(point.get("node_ids") or []) >= 3
                and all(str(node_id) in node_coordinates for node_id in (point.get("node_ids") or [])[:3])
                for point in sampled
            )
        )
        mesh_nodes = [
            {"id": node_id, "x": node_coordinates[node_id][0], "y": node_coordinates[node_id][1]}
            for node_id in sorted(referenced_node_ids, key=lambda value: (_to_float(value) is None, _to_float(value) or 0.0, value))
            if node_id in node_coordinates
        ] if mesh_complete else []
        if mesh_complete:
            mesh_frame_count += 1
        frame_name = f"frame_{index:04d}.json"
        payload = {
            "schema_version": 3,
            "index": index,
            "step": step_value,
            "point_count": len(sampled),
            "source_point_count": len(points),
            "regions": sorted({str(p["region"]) for p in sampled if p.get("region") not in (None, "")}),
            "points": sampled,
            "sampling": sampling,
            "mesh_complete": mesh_complete,
            "mesh_nodes": mesh_nodes,
        }
        frame_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (frames_dir / frame_name).write_bytes(frame_bytes)
        frame_record = {
            "index": index,
            "step": step_value,
            "file": frame_name,
            "point_count": len(sampled),
            "source_point_count": len(points),
            "mesh_complete": mesh_complete,
            "sampling": sampling,
            "size_bytes": len(frame_bytes),
            "sha256": hashlib.sha256(frame_bytes).hexdigest(),
        }
        for field, values in frame_values.items():
            frame_record[f"{field}_min"] = min(values) if values else None
            frame_record[f"{field}_max"] = max(values) if values else None
        frame_index.append(frame_record)

    total_points = sum(len(points) for points in grouped.values())
    global_ranges: dict[str, float | None] = {}
    finite_field_coverage: dict[str, float] = {}
    for field, values in all_values.items():
        global_ranges[f"{field}_min"] = min(values) if values else None
        global_ranges[f"{field}_max"] = max(values) if values else None
        finite_field_coverage[field] = round(len(values) / total_points, 8) if total_points else 0.0
    coordinate_drop_fraction = round(dropped / raw_row_count, 8) if raw_row_count else 0.0
    sampled_points = sum(int(record["output_count"]) for record in sampling_records)
    field_metadata = {
        field: {
            "unit": (
                "T" if field in {"b", "bx", "by"}
                else "MPa" if field == "stress"
                else "mm" if field == "displacement"
                else None
            ),
            "unit_status": (
                "REFERENCE_CONFIRMED" if field in {"b", "bx", "by"}
                else "OFFICIAL_EXAMPLE_CONFIRMED" if field in {"stress", "displacement"}
                else "SOURCE_NATIVE_UNVERIFIED"
            ),
            "source_column": field_columns.get(field),
        }
        for field in available_fields
    }
    coordinate_metadata = {
        "unit": "mm" if any(field in available_fields for field in ("stress", "displacement")) else None,
        "unit_status": "OFFICIAL_MECHANICAL_EXAMPLE_CONFIRMED" if any(field in available_fields for field in ("stress", "displacement")) else "SOURCE_NATIVE_UNVERIFIED",
    }

    return {
        "schema_version": 5,
        "normalized": True,
        "source_format": source_format,
        "headers": headers,
        "delimiter": delimiter,
        "coordinate_columns": {"x": x_key, "y": y_key},
        "coordinate_metadata": coordinate_metadata,
        "field_columns": field_columns,
        "field_metadata": field_metadata,
        "available_fields": available_fields,
        "regions": sorted(all_regions),
        "region_names": region_names,
        "native_table_counts": native_table_counts,
        "connectivity_columns": {"element": element_key, "nodes": node_keys},
        "capabilities": {
            "playback": len(frame_index) > 1,
            "field_selection": len(available_fields) > 1,
            "region_filter": bool(all_regions),
            "manual_range": True,
            "nearest_point_probe": True,
            "raw_download": True,
            "connectivity_metadata": bool(element_key and len(node_keys) >= 3),
            "mesh_edges": mesh_frame_count == len(frame_index) and mesh_frame_count > 0,
            "filled_contours": mesh_frame_count == len(frame_index) and mesh_frame_count > 0,
            "equipotential_lines": False,
        },
        "row_count": raw_row_count,
        "dropped_rows": dropped,
        "source_point_count": total_points,
        "display_point_count": sampled_points,
        "quality_metrics": {
            "coordinate_valid_fraction": round(1.0 - coordinate_drop_fraction, 8),
            "coordinate_drop_fraction": coordinate_drop_fraction,
            "unique_coordinate_count": len(coordinate_pairs),
            "duplicate_coordinate_count": max(0, total_points - len(coordinate_pairs)),
            "finite_field_coverage": finite_field_coverage,
            "region_count": len(all_regions),
            "mesh_frame_count": mesh_frame_count,
        },
        "sampling_contract": {
            "strategy": "region_extrema_uniform_v1",
            "max_points_per_frame": max_points_per_frame,
            "source_point_count": total_points,
            "display_point_count": sampled_points,
            "full_source_ranges": True,
            "all_extrema_preserved": all(record.get("extrema_preserved") for record in sampling_records),
            "all_regions_preserved": all(float(record.get("region_coverage") or 0.0) >= 1.0 for record in sampling_records),
            "frames": sampling_records,
        },
        "normalization_io_contract": "single_pass_delimited_v1" if not native_table else "bounded_native_table_v1",
        "frame_integrity": {
            "algorithm": "sha256",
            "registered_frame_count": len(frame_index),
            "all_frames_registered": all(
                isinstance(record.get("sha256"), str) and len(record["sha256"]) == 64
                and int(record.get("size_bytes") or 0) > 0
                for record in frame_index
            ),
            "verification_policy": "verify_before_serve_or_probe",
        },
        "frame_count": len(frame_index),
        "frames": frame_index,
        "global_ranges": global_ranges,
    }


class NativeFEAEvidenceExporter:
    """Policy-driven Motor-CAD native FEA exporter and evidence validator."""

    def __init__(self, config: NativeFEAExportConfig):
        self.config = config

    def _validation_plan(self) -> dict[str, Any]:
        return {
            "policy": self.config.policy,
            "required_for_qualification": self.config.required_for_qualification,
            "required_fields": list(self.config.required_fields),
            "required_regions": list(self.config.required_regions),
            "require_coordinates": self.config.require_coordinates,
            "require_connectivity": self.config.require_connectivity,
            "min_field_coverage": self.config.min_field_coverage,
            "max_coordinate_drop_fraction": self.config.max_coordinate_drop_fraction,
            "min_points_per_frame": self.config.min_points_per_frame,
            "require_extrema_preserved": self.config.require_extrema_preserved,
            "contract_id": self.config.contract_id,
        }

    def _estimate_step_count(self, mc: Any) -> int:
        try:
            x_values, _ = mc.get_magnetic_graph("TorqueVW")
            return max(1, min(self.config.max_steps, len(x_values or [])))
        except Exception:
            return 1

    def export(self, mc: Any, work_dir: Path, *, source_mot: Path | None = None, motorcad_version: str | None = None, progress: Any | None = None) -> tuple[dict[str, Any], list[str]]:
        root = work_dir / "native_fea"
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "native_fea_manifest.json"
        warnings: list[str] = []
        manifest: dict[str, Any] = {
            "schema_version": 5,
            "authority": "motorcad_save_fea_data",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "enabled": self.config.enabled,
            "status": "SKIPPED" if not self.config.enabled else "PENDING",
            "motorcad_version": motorcad_version,
            "source_mot": str(source_mot) if source_mot else None,
            "source_mot_sha256": _sha256(source_mot) if source_mot and source_mot.exists() else None,
            "requested_outputs": self.config.outputs,
            "regions": self.config.regions,
            "policy": self.config.policy,
            "contract_id": self.config.contract_id,
        }
        if not self.config.enabled or not hasattr(mc, "save_fea_data"):
            if self.config.enabled:
                manifest["status"] = "UNAVAILABLE"
                manifest["reason"] = "PyMotorCAD save_fea_data API unavailable"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            plan = self._validation_plan()
            manifest["validation"] = validate_fea_manifest(manifest, plan)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return manifest, warnings

        if progress:
            progress("EXPORTING_FEA", 0.72, "导出 Motor-CAD 原生有限元数据")
        step_count = self._estimate_step_count(mc)
        ranges: list[tuple[int, int]] = []
        if step_count > 1:
            ranges.extend([(0, step_count - 1), (1, step_count)])
        ranges.extend([(0, 0), (1, 1)])
        # Preserve order while removing duplicates.
        ranges = list(dict.fromkeys(ranges))
        attempts: list[dict[str, Any]] = []
        raw_path = root / "native_fea_raw.csv"
        used_range: tuple[int, int] | None = None
        used_outputs: str | None = None
        if "stress" in self.config.required_fields:
            output_sets = list(dict.fromkeys([
                self.config.outputs,
                "RegCode,X,Y,SVM,Ux,Uy",
                "RegCode,X,Y,SVM",
                "RegCode,X,Y,Stress,Displacement",
            ]))
        else:
            output_sets = list(dict.fromkeys([self.config.outputs, "RegCode,X,Y,B,Pt"]))
        attempt_number = 0
        for outputs in output_sets:
            for first_step, final_step in ranges:
                attempt_number += 1
                if progress:
                    progress(
                        "FEA_EXPORT_ATTEMPT",
                        min(0.755, 0.72 + attempt_number * 0.003),
                        f"原生 FEA 导出尝试 {attempt_number}：步 {first_step}–{final_step}，字段 {outputs}",
                    )
                try:
                    if raw_path.exists():
                        raw_path.unlink()
                    mc.save_fea_data(
                        str(raw_path), int(first_step), int(final_step),
                        outputs, self.config.regions, self.config.separator,
                    )
                    if raw_path.exists() and raw_path.stat().st_size > 0:
                        used_range = (first_step, final_step)
                        used_outputs = outputs
                        attempts.append({"outputs": outputs, "first_step": first_step, "final_step": final_step, "ok": True, "size_bytes": raw_path.stat().st_size})
                        if progress:
                            progress("FEA_RAW_WRITTEN", 0.758, f"原生 FEA 文件已生成：{raw_path.stat().st_size:,} bytes")
                        break
                    attempts.append({"outputs": outputs, "first_step": first_step, "final_step": final_step, "ok": False, "error": "export file missing or empty"})
                except Exception as exc:
                    attempts.append({"outputs": outputs, "first_step": first_step, "final_step": final_step, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            if used_range is not None:
                break

        manifest["attempts"] = attempts
        if used_range is None:
            manifest["status"] = "WARNING"
            manifest["reason"] = "Motor-CAD native FEA export did not produce a readable file"
            warnings.append("Motor-CAD 原生 FEA 数据导出失败；求解结果仍有效，可继续使用曲线回放。")
            if progress:
                progress("FEA_EXPORT_WARNING", 0.76, f"原生 FEA 导出未生成文件；已记录 {len(attempts)} 次尝试")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            plan = self._validation_plan()
            manifest["validation"] = validate_fea_manifest(manifest, plan)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return manifest, warnings

        manifest.update({
            "status": "PASS",
            "first_step": used_range[0],
            "final_step": used_range[1],
            "exported_outputs": used_outputs,
            "raw_file": raw_path.name,
            "raw_size_bytes": raw_path.stat().st_size,
            "raw_sha256": _sha256(raw_path),
        })
        if progress:
            progress("NORMALIZING_FEA", 0.76, "标准化有限元场与时间帧")
        normalized = normalize_fea_csv(raw_path, root / "frames", self.config.max_points_per_frame, used_outputs)
        manifest["normalization"] = normalized
        if progress:
            if normalized.get("normalized"):
                progress(
                    "FEA_NORMALIZED",
                    0.78,
                    f"原生 FEA 已标准化：{int(normalized.get('frame_count') or 0)} 帧，{int(normalized.get('source_point_count') or 0):,} 个源单元",
                )
            else:
                progress("FEA_NORMALIZATION_WARNING", 0.78, f"原生文件已保存，场坐标解析失败：{normalized.get('reason') or '未知格式'}")
        if not normalized.get("normalized"):
            manifest["status"] = "RAW_ONLY"
            warnings.append("已保存 Motor-CAD 原生 FEA 数据，但当前版本未识别其坐标列；可在诊断包中查看原始导出。")
        plan = self._validation_plan()
        manifest["validation"] = validate_fea_manifest(manifest, plan)
        if not manifest["validation"]["qualification_eligible"] and self.config.policy == "required":
            manifest["status"] = "BLOCKED"
            warnings.append("原生 FEA 结果未通过必需证据合同，当前 Case 不具备结果资格。")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest, warnings
