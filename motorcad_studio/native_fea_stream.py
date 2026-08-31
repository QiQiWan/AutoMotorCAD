from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


TABLE_PATTERN = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(ElementsTable|NodesTable|RegionsTable)\s*$",
    re.IGNORECASE,
)
FIELD_NAMES = (
    "b", "bx", "by", "pt", "current_density", "eddy_current_density",
    "stress", "displacement",
)


def _norm(name: str) -> str:
    return "".join(character.lower() for character in str(name) if character.isalnum())


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


def _parts(line: str, separator: str) -> list[str]:
    return [part.strip() for part in line.rstrip("\r\n").split(separator)]


def _detect_separator(raw_path: Path) -> str:
    candidates = (",", ";", "\t", "|")
    scores = {candidate: 0 for candidate in candidates}
    with raw_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for _ in range(128):
            line = handle.readline()
            if not line:
                break
            if any(token in line.lower() for token in ("triindex", "nodeindex", "regcode")):
                for candidate in candidates:
                    scores[candidate] = max(scores[candidate], line.count(candidate))
    return max(candidates, key=lambda candidate: scores[candidate]) if any(scores.values()) else ","


def _element_row(parts: list[str], expected: int | None) -> bool:
    if len(parts) < (expected or 5):
        return False
    try:
        for value in parts[:4]:
            int(float(value))
    except (TypeError, ValueError):
        return False
    return True


def _generic_row(parts: list[str], _expected: int | None) -> bool:
    return len(parts) >= 2 and _to_float(parts[0]) is not None


@dataclass(frozen=True)
class NativeBlock:
    name: str
    declared_count: int
    headers: list[str]
    rows: Iterator[list[str]]


def _iter_native_blocks(raw_path: Path, element_width: int | None, separator: str) -> Iterator[NativeBlock]:
    """Yield one native table at a time while retaining only its preamble.

    Consumers must exhaust ``rows`` before advancing the outer iterator.  Every
    production consumer in this module does so, which keeps the file cursor and
    memory use deterministic.
    """
    with raw_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        while True:
            line = handle.readline()
            if not line:
                break
            match = TABLE_PATTERN.match(line)
            if not match:
                continue
            count = int(match.group(2))
            name = match.group(3).lower()
            if count <= 0:
                yield NativeBlock(name=name, declared_count=0, headers=[], rows=iter(()))
                continue
            validator = _element_row if name == "elementstable" else _generic_row
            expected = element_width if name == "elementstable" else None
            preamble: list[str] = []
            first: list[str] | None = None
            for _ in range(32):
                candidate = handle.readline()
                if not candidate:
                    break
                parts = _parts(candidate, separator)
                if validator(parts, expected):
                    first = parts
                    break
                preamble.append(candidate)
            header_candidates = [
                _parts(candidate, separator) for candidate in preamble
                if len(_parts(candidate, separator)) >= 2
                and any(any(character.isalpha() for character in part) for part in _parts(candidate, separator))
            ]
            if name == "elementstable":
                structural_headers = [
                    candidate for candidate in header_candidates
                    if len(candidate) >= 4
                    and _norm(candidate[0]) in {"triindex", "elementindex", "elementid", "element"}
                    and all(_norm(candidate[index]).startswith("node") for index in (1, 2, 3))
                ]
                headers = structural_headers[-1] if structural_headers else (header_candidates[-1] if header_candidates else [])
            elif name == "nodestable":
                # Native exports commonly put a unit row immediately below the
                # semantic header.  Selecting the last alpha-containing preamble
                # row therefore loses NodeIndex/X/Y (for example ``[-],[mm],[mm]``)
                # and makes every otherwise valid triangle look disconnected.
                structural_headers = [
                    candidate for candidate in header_candidates
                    if _pick(candidate, ("NodeIndex", "NodeID", "Node", "Index"), fuzzy=False)
                    and _pick(candidate, ("X", "XCoord", "XCoordinate", "NodeX"))
                    and _pick(candidate, ("Y", "YCoord", "YCoordinate", "NodeY"))
                ]
                headers = structural_headers[-1] if structural_headers else (header_candidates[-1] if header_candidates else [])
            elif name == "regionstable":
                structural_headers = [
                    candidate for candidate in header_candidates
                    if any(token in _norm(candidate[0]) for token in ("reg", "region", "code", "index"))
                ]
                headers = structural_headers[-1] if structural_headers else (header_candidates[-1] if header_candidates else [])
            else:
                headers = header_candidates[-1] if header_candidates else []

            def rows(first_row: list[str] | None = first) -> Iterator[list[str]]:
                consumed = 0
                if first_row is not None:
                    consumed += 1
                    yield first_row
                while consumed < count:
                    candidate = handle.readline()
                    if not candidate:
                        break
                    parts = _parts(candidate, separator)
                    if not validator(parts, expected):
                        break
                    consumed += 1
                    yield parts

            yield NativeBlock(name=name, declared_count=count, headers=headers, rows=rows())


def _configure_index(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-4096")
    connection.execute(
        "CREATE TABLE nodes (node_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL) WITHOUT ROWID"
    )
    connection.execute(
        "CREATE TABLE coordinates (x REAL NOT NULL, y REAL NOT NULL, PRIMARY KEY (x, y)) WITHOUT ROWID"
    )


def _priority(step: int, source_index: int, point: dict[str, Any]) -> int:
    payload = (
        f"{step}|{source_index}|{point.get('x', 0):.17g}|{point.get('y', 0):.17g}|"
        f"{point.get('region', '')}"
    ).encode("utf-8", errors="replace")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


@dataclass
class FrameAccumulator:
    frame_index: int
    limit: int
    fields: list[str]
    source_count: int = 0
    dropped_count: int = 0
    field_counts: dict[str, int] = field(default_factory=dict)
    field_ranges: dict[str, list[float]] = field(default_factory=dict)
    source_regions: set[str] = field(default_factory=set)
    mandatory: dict[str, dict[str, Any]] = field(default_factory=dict)
    reservoir: list[tuple[int, int, dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.field_counts = {name: 0 for name in self.fields}
        self.field_ranges = {name: [math.inf, -math.inf] for name in self.fields}

    def _retain_bound(self, tag: str, point: dict[str, Any], value: float, *, low: bool) -> None:
        current = self.mandatory.get(tag)
        if current is None:
            self.mandatory[tag] = point
            return
        current_value = _to_float(current.get(tag.split(":", 1)[0]))
        if current_value is None or (value < current_value if low else value > current_value):
            self.mandatory[tag] = point

    def add(self, point: dict[str, Any]) -> None:
        source_index = self.source_count
        self.source_count += 1
        point["_source_index"] = source_index
        for coordinate in ("x", "y"):
            value = float(point[coordinate])
            low_tag, high_tag = f"{coordinate}:min", f"{coordinate}:max"
            current_low = self.mandatory.get(low_tag)
            current_high = self.mandatory.get(high_tag)
            if current_low is None or value < float(current_low[coordinate]):
                self.mandatory[low_tag] = point
            if current_high is None or value > float(current_high[coordinate]):
                self.mandatory[high_tag] = point
        region = str(point.get("region") or "")
        if region:
            self.source_regions.add(region)
            self.mandatory.setdefault(f"region:{region}", point)
        for name in self.fields:
            value = _to_float(point.get(name))
            if value is None:
                continue
            self.field_counts[name] += 1
            bounds = self.field_ranges[name]
            if value < bounds[0]:
                bounds[0] = value
                self.mandatory[f"field:{name}:min"] = point
            if value > bounds[1]:
                bounds[1] = value
                self.mandatory[f"field:{name}:max"] = point
        priority = _priority(self.frame_index, source_index, point)
        entry = (-priority, source_index, point)
        if len(self.reservoir) < self.limit:
            heapq.heappush(self.reservoir, entry)
        elif priority < -self.reservoir[0][0]:
            heapq.heapreplace(self.reservoir, entry)

    def sample(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        by_source: dict[int, dict[str, Any]] = {}
        structural_tags = ["x:min", "x:max", "y:min", "y:max"]
        structural_tags += [f"field:{name}:{edge}" for name in self.fields for edge in ("min", "max")]
        region_tags = sorted(tag for tag in self.mandatory if tag.startswith("region:"))
        for tag in [*structural_tags, *region_tags]:
            point = self.mandatory.get(tag)
            if point is not None and len(by_source) < self.limit:
                by_source[int(point["_source_index"])] = point
        for _negative_priority, source_index, point in sorted(
            self.reservoir, key=lambda item: (-item[0], item[1])
        ):
            if len(by_source) >= self.limit:
                break
            by_source.setdefault(source_index, point)
        selected_indices = set(by_source)
        sampled = [by_source[index] for index in sorted(by_source)]
        sampled_regions = {str(point.get("region")) for point in sampled if point.get("region") not in (None, "")}
        extrema_points = [
            point for tag, point in self.mandatory.items()
            if tag.startswith("field:")
        ]
        coordinate_points = [self.mandatory.get(tag) for tag in structural_tags[:4]]
        extrema_preserved = all(int(point["_source_index"]) in selected_indices for point in extrema_points)
        coordinate_preserved = all(
            point is None or int(point["_source_index"]) in selected_indices for point in coordinate_points
        )
        for point in sampled:
            point.pop("_source_index", None)
        region_coverage = (
            len(sampled_regions) / len(self.source_regions) if self.source_regions else 1.0
        )
        return sampled, {
            "strategy": "region_field_coordinate_hash_v1",
            "source_count": self.source_count,
            "output_count": len(sampled),
            "retained_fraction": round(len(sampled) / self.source_count, 8) if self.source_count else 0.0,
            "region_coverage": round(region_coverage, 8),
            "extrema_preserved": extrema_preserved,
            "coordinate_extrema_preserved": coordinate_preserved,
            "preserved_fields": sorted(
                name for name, values in self.field_ranges.items() if values[0] != math.inf
            ),
            "bounded_candidate_count": min(self.limit, self.source_count) + len(self.mandatory),
        }


def _field_contract(outputs: list[str]) -> tuple[dict[str, str | None], list[str]]:
    b_key = _pick(outputs, ("B", "FluxDensity", "BMag", "BMagnitude"), fuzzy=False)
    bx_key = _pick(outputs, ("Bx", "FluxDensityX"))
    by_key = _pick(outputs, ("By", "FluxDensityY"))
    pt_key = _pick(outputs, ("Pt", "VectorPotential", "A", "Az"))
    current_key = _pick(outputs, ("J", "JMag", "CurrentDensity", "CurrentDensityMagnitude"), fuzzy=False)
    eddy_key = _pick(outputs, ("JEddy", "EddyCurrentDensity", "EddyCurrentDensityMagnitude"), fuzzy=False)
    stress_key = _pick(outputs, ("Stress", "VonMisesStress", "EquivalentStress", "SigmaVM", "SVM"), fuzzy=False)
    displacement_key = _pick(outputs, ("Displacement", "TotalDisplacement", "DisplacementMagnitude"), fuzzy=False)
    ux_key = _pick(outputs, ("Ux", "DisplacementX", "XDisplacement"), fuzzy=False)
    uy_key = _pick(outputs, ("Uy", "DisplacementY", "YDisplacement"), fuzzy=False)
    columns: dict[str, str | None] = {
        "b": b_key or ("derived:hypot(Bx,By)" if bx_key and by_key else None),
        "bx": bx_key,
        "by": by_key,
        "pt": pt_key,
        "current_density": current_key,
        "eddy_current_density": eddy_key,
        "stress": stress_key,
        "displacement": displacement_key or ("derived:hypot(Ux,Uy)" if ux_key and uy_key else None),
        "region": _pick(outputs, ("RegCode", "RegionCode", "Region")),
        "step": "ElementsTable block index",
        "_ux": ux_key,
        "_uy": uy_key,
    }
    return columns, [name for name in FIELD_NAMES if columns.get(name)]


def _point_from_row(
    parts: list[str], outputs: list[str], columns: dict[str, str | None], region_names: dict[str, str]
) -> dict[str, Any] | None:
    expected = 4 + len(outputs)
    if len(parts) < expected:
        return None
    values = {name: parts[4 + index] for index, name in enumerate(outputs)}
    x_key = _pick(outputs, ("X", "XCoord", "XCoordinate", "NodeX"))
    y_key = _pick(outputs, ("Y", "YCoord", "YCoordinate", "NodeY"))
    x = _to_float(values.get(x_key)) if x_key else None
    y = _to_float(values.get(y_key)) if y_key else None
    if x is None or y is None:
        return None
    point: dict[str, Any] = {
        "x": x,
        "y": y,
        "element_id": _scalar_id(parts[0]),
        "node_ids": [_scalar_id(value) for value in parts[1:4]],
    }
    bx = _to_float(values.get(columns.get("bx"))) if columns.get("bx") else None
    by = _to_float(values.get(columns.get("by"))) if columns.get("by") else None
    b_source = columns.get("b")
    b = None if str(b_source or "").startswith("derived:") else _to_float(values.get(b_source))
    if b is None and bx is not None and by is not None:
        b = math.hypot(bx, by)
    if b is not None:
        point["b"] = b
    if bx is not None:
        point["bx"] = bx
    if by is not None:
        point["by"] = by
    for field_name in ("pt", "current_density", "eddy_current_density", "stress"):
        source = columns.get(field_name)
        value = _to_float(values.get(source)) if source else None
        if value is not None:
            point[field_name] = value
    displacement_source = columns.get("displacement")
    displacement = None if str(displacement_source or "").startswith("derived:") else _to_float(values.get(displacement_source))
    ux = _to_float(values.get(columns.get("_ux"))) if columns.get("_ux") else None
    uy = _to_float(values.get(columns.get("_uy"))) if columns.get("_uy") else None
    if displacement is None and ux is not None and uy is not None:
        displacement = math.hypot(ux, uy)
    if displacement is not None:
        point["displacement"] = displacement
    region_source = columns.get("region")
    if region_source and values.get(region_source) not in (None, ""):
        region_code = str(_scalar_id(values.get(region_source)))
        point["region_code"] = region_code
        point["region"] = region_names.get(region_code, region_code)
    return point


def _node_coordinates(connection: sqlite3.Connection, node_ids: set[str]) -> dict[str, tuple[float, float]]:
    coordinates: dict[str, tuple[float, float]] = {}
    ordered = sorted(node_ids, key=lambda value: (_to_float(value) is None, _to_float(value) or 0.0, value))
    for offset in range(0, len(ordered), 500):
        batch = ordered[offset:offset + 500]
        if not batch:
            continue
        placeholders = ",".join("?" for _ in batch)
        for node_id, x, y in connection.execute(
            f"SELECT node_id, x, y FROM nodes WHERE node_id IN ({placeholders})", batch
        ):
            coordinates[str(node_id)] = (float(x), float(y))
    return coordinates


def _atomic_frame(path: Path, payload: dict[str, Any]) -> tuple[int, str]:
    frame_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(frame_bytes)
    temporary.replace(path)
    return len(frame_bytes), hashlib.sha256(frame_bytes).hexdigest()


def normalize_native_fea_tables(
    raw_path: Path,
    frames_dir: Path,
    max_points_per_frame: int,
    requested_outputs: str | None,
) -> dict[str, Any]:
    """Normalize native Motor-CAD multi-table FEA with bounded Python memory.

    Pass one creates a temporary on-disk node index and discovers region names.
    Pass two scans element blocks, computes exact statistics online, retains a
    bounded engineering sample and atomically archives each frame.
    """
    configured_outputs = [token.strip() for token in str(requested_outputs or "").split(",") if token.strip()]
    frames_dir.mkdir(parents=True, exist_ok=True)
    viewer_root = frames_dir.parent / "viewer_frames"
    viewer_root.mkdir(parents=True, exist_ok=True)
    viewer_chunk_elements = 1800
    temp_handle = tempfile.NamedTemporaryFile(
        prefix="motorcad-native-index-", suffix=".sqlite3", dir=frames_dir.parent, delete=False
    )
    index_path = Path(temp_handle.name)
    temp_handle.close()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(index_path)
        _configure_index(connection)
        separator = _detect_separator(raw_path)
        region_names: dict[str, str] = {}
        table_counts = {"elements": 0, "nodes": 0, "regions": 0}
        declared_counts = {"elements": 0, "nodes": 0, "regions": 0}
        discovered_outputs: list[str] = []
        # Motor-CAD may silently omit unsupported requested outputs from the
        # written ElementsTable (for example JEddy on some EMag solutions).
        # Row validity must therefore follow the actual table structure rather
        # than the requested output width.
        element_width = None
        node_batch: list[tuple[str, float, float]] = []
        for block in _iter_native_blocks(raw_path, element_width, separator):
            logical_name = block.name.replace("table", "")
            declared_counts[logical_name] += block.declared_count
            parsed = 0
            if block.name == "elementstable":
                if len(block.headers) > 4:
                    for output in block.headers[4:]:
                        if _norm(output) not in {_norm(item) for item in discovered_outputs}:
                            discovered_outputs.append(output)
                for _ in block.rows:
                    parsed += 1
            elif block.name == "nodestable":
                node_key = _pick(block.headers, ("NodeIndex", "NodeID", "Node", "Index"), fuzzy=False)
                x_key = _pick(block.headers, ("X", "XCoord", "XCoordinate", "NodeX"))
                y_key = _pick(block.headers, ("Y", "YCoord", "YCoordinate", "NodeY"))
                key_index = block.headers.index(node_key) if node_key in block.headers else -1
                x_index = block.headers.index(x_key) if x_key in block.headers else -1
                y_index = block.headers.index(y_key) if y_key in block.headers else -1
                for parts in block.rows:
                    parsed += 1
                    if min(key_index, x_index, y_index) < 0 or max(key_index, x_index, y_index) >= len(parts):
                        continue
                    node_id = _scalar_id(parts[key_index])
                    x, y = _to_float(parts[x_index]), _to_float(parts[y_index])
                    if node_id is None or x is None or y is None:
                        continue
                    node_batch.append((str(node_id), x, y))
                    if len(node_batch) >= 1000:
                        connection.executemany("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?)", node_batch)
                        node_batch.clear()
            else:
                for parts in block.rows:
                    parsed += 1
                    region_id = _scalar_id(parts[0]) if parts else None
                    region_name = parts[-1].strip() if parts else ""
                    if region_id is not None and region_name and _to_float(region_name) is None:
                        region_names[str(region_id)] = region_name
            table_counts[logical_name] += parsed
        if node_batch:
            connection.executemany("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?)", node_batch)
        connection.commit()
        # The table header is the native authority for what Motor-CAD actually
        # exported. Requested fields are retained as provenance, but an omitted
        # optional field must not shift every subsequent column or invalidate
        # otherwise valid X/Y/B data.
        outputs = discovered_outputs or configured_outputs
        if not outputs:
            return {"normalized": False, "reason": "native_output_columns_not_found"}
        exported_norm = {_norm(item) for item in outputs}
        missing_requested_outputs = [
            item for item in configured_outputs if _norm(item) not in exported_norm
        ]
        x_key = _pick(outputs, ("X", "XCoord", "XCoordinate", "NodeX"))
        y_key = _pick(outputs, ("Y", "YCoord", "YCoordinate", "NodeY"))
        if not x_key or not y_key:
            return {
                "normalized": False,
                "reason": "coordinate_columns_not_found",
                "headers": ["TriIndex", "Node1", "Node2", "Node3", *outputs, "Step"],
                "row_count": table_counts["elements"],
            }
        field_columns, available_fields = _field_contract(outputs)
        headers = ["TriIndex", "Node1", "Node2", "Node3", *outputs, "Step"]
        global_ranges: dict[str, list[float]] = {name: [math.inf, -math.inf] for name in available_fields}
        field_counts = {name: 0 for name in available_fields}
        all_regions: set[str] = set()
        frame_index: list[dict[str, Any]] = []
        sampling_records: list[dict[str, Any]] = []
        coordinate_batch: list[tuple[float, float]] = []
        total_points = 0
        dropped = 0
        mesh_frame_count = 0
        full_mesh_frame_count = 0
        frame_number = 0
        for block in _iter_native_blocks(raw_path, None, separator):
            if block.name != "elementstable":
                for _ in block.rows:
                    pass
                continue
            block_outputs = block.headers[4:] if len(block.headers) > 4 else outputs
            block_field_columns, _ = _field_contract(block_outputs)
            accumulator = FrameAccumulator(frame_number, max_points_per_frame, available_fields)
            viewer_frame_index = len(frame_index)
            viewer_frame_dir = viewer_root / f"frame_{viewer_frame_index:04d}"
            viewer_frame_dir.mkdir(parents=True, exist_ok=True)
            for stale in viewer_frame_dir.glob("*.json"):
                stale.unlink(missing_ok=True)
            viewer_buffer: list[dict[str, Any]] = []
            viewer_chunks: list[dict[str, Any]] = []
            viewer_mesh_complete = True
            viewer_bounds = [math.inf, -math.inf, math.inf, -math.inf]

            def flush_viewer_chunk() -> None:
                nonlocal viewer_mesh_complete
                if not viewer_buffer:
                    return
                chunk_index = len(viewer_chunks)
                referenced_ids = {
                    str(node_id) for point in viewer_buffer for node_id in (point.get("node_ids") or [])[:3]
                    if node_id is not None
                }
                coordinates = _node_coordinates(connection, referenced_ids)
                complete = bool(
                    viewer_buffer and referenced_ids
                    and all(
                        len(point.get("node_ids") or []) >= 3
                        and all(str(node_id) in coordinates for node_id in (point.get("node_ids") or [])[:3])
                        for point in viewer_buffer
                    )
                )
                viewer_mesh_complete = viewer_mesh_complete and complete
                mesh_nodes = [
                    {"id": node_id, "x": coordinates[node_id][0], "y": coordinates[node_id][1]}
                    for node_id in sorted(coordinates, key=lambda value: (_to_float(value) is None, _to_float(value) or 0.0, value))
                ]
                geometry = mesh_nodes or viewer_buffer
                for item in geometry:
                    x, y = _to_float(item.get("x")), _to_float(item.get("y"))
                    if x is None or y is None:
                        continue
                    viewer_bounds[0] = min(viewer_bounds[0], x)
                    viewer_bounds[1] = max(viewer_bounds[1], x)
                    viewer_bounds[2] = min(viewer_bounds[2], y)
                    viewer_bounds[3] = max(viewer_bounds[3], y)
                chunk_name = f"chunk_{chunk_index:04d}.json"
                chunk_payload = {
                    "schema_version": 1, "contract_version": "0.89-G3.3",
                    "frame_index": viewer_frame_index, "chunk_index": chunk_index,
                    "element_count": len(viewer_buffer), "mesh_complete": complete,
                    "elements": list(viewer_buffer), "mesh_nodes": mesh_nodes,
                }
                size_bytes, sha256 = _atomic_frame(viewer_frame_dir / chunk_name, chunk_payload)
                viewer_chunks.append({
                    "index": chunk_index, "file": chunk_name, "element_count": len(viewer_buffer),
                    "node_count": len(mesh_nodes), "mesh_complete": complete,
                    "size_bytes": size_bytes, "sha256": sha256,
                })
                viewer_buffer.clear()

            for parts in block.rows:
                point = _point_from_row(parts, block_outputs, block_field_columns, region_names)
                if point is None:
                    dropped += 1
                    continue
                accumulator.add(point)
                viewer_buffer.append({key: value for key, value in point.items() if key != "_source_index"})
                if len(viewer_buffer) >= viewer_chunk_elements:
                    flush_viewer_chunk()
                total_points += 1
                coordinate_batch.append((float(point["x"]), float(point["y"])))
                if len(coordinate_batch) >= 1000:
                    connection.executemany("INSERT OR IGNORE INTO coordinates VALUES (?, ?)", coordinate_batch)
                    coordinate_batch.clear()
                region = str(point.get("region") or "")
                if region:
                    all_regions.add(region)
                for name in available_fields:
                    value = _to_float(point.get(name))
                    if value is None:
                        continue
                    field_counts[name] += 1
                    global_ranges[name][0] = min(global_ranges[name][0], value)
                    global_ranges[name][1] = max(global_ranges[name][1], value)
            flush_viewer_chunk()
            if accumulator.source_count <= 0:
                frame_number += 1
                continue
            sampled, sampling = accumulator.sample()
            sampling_records.append({"frame_index": len(frame_index), **sampling})
            referenced_ids = {
                str(node_id) for point in sampled for node_id in (point.get("node_ids") or [])
                if node_id is not None
            }
            coordinates = _node_coordinates(connection, referenced_ids)
            mesh_complete = bool(
                sampled and referenced_ids
                and all(
                    len(point.get("node_ids") or []) >= 3
                    and all(str(node_id) in coordinates for node_id in (point.get("node_ids") or [])[:3])
                    for point in sampled
                )
            )
            mesh_nodes = [
                {"id": node_id, "x": coordinates[node_id][0], "y": coordinates[node_id][1]}
                for node_id in sorted(coordinates, key=lambda value: (_to_float(value) is None, _to_float(value) or 0.0, value))
            ] if mesh_complete else []
            if mesh_complete:
                mesh_frame_count += 1
            index = len(frame_index)
            full_bounds = None if any(value in (math.inf, -math.inf) for value in viewer_bounds) else viewer_bounds
            full_mesh_complete = bool(
                viewer_chunks and viewer_mesh_complete
                and sum(int(chunk.get("element_count") or 0) for chunk in viewer_chunks) == accumulator.source_count
            )
            if full_mesh_complete:
                full_mesh_frame_count += 1
            viewer_manifest_name = "manifest.json"
            viewer_manifest_payload = {
                "schema_version": 1, "contract_version": "0.89-G3.3",
                "frame_index": index, "step": str(frame_number),
                "element_count": accumulator.source_count, "chunk_count": len(viewer_chunks),
                "chunk_element_limit": viewer_chunk_elements, "mesh_complete": full_mesh_complete,
                "full_region": True, "data_bounds": full_bounds,
                "available_fields": available_fields,
                "regions": sorted(accumulator.source_regions), "chunks": viewer_chunks,
            }
            viewer_manifest_size, viewer_manifest_sha = _atomic_frame(
                viewer_frame_dir / viewer_manifest_name, viewer_manifest_payload
            )
            frame_name = f"frame_{index:04d}.json"
            payload = {
                "schema_version": 3,
                "index": index,
                "step": str(frame_number),
                "point_count": len(sampled),
                "source_point_count": accumulator.source_count,
                "regions": sorted({str(point["region"]) for point in sampled if point.get("region") not in (None, "")}),
                "points": sampled,
                "sampling": sampling,
                "mesh_complete": mesh_complete,
                "mesh_nodes": mesh_nodes,
            }
            size_bytes, sha256 = _atomic_frame(frames_dir / frame_name, payload)
            record: dict[str, Any] = {
                "index": index,
                "step": str(frame_number),
                "file": frame_name,
                "point_count": len(sampled),
                "source_point_count": accumulator.source_count,
                "mesh_complete": mesh_complete,
                "sampling": sampling,
                "viewer_manifest_file": f"viewer_frames/frame_{index:04d}/{viewer_manifest_name}",
                "viewer_manifest_size_bytes": viewer_manifest_size,
                "viewer_manifest_sha256": viewer_manifest_sha,
                "viewer_chunk_count": len(viewer_chunks),
                "viewer_element_count": accumulator.source_count,
                "viewer_mesh_complete": full_mesh_complete,
                "viewer_data_bounds": full_bounds,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
            for name, bounds in accumulator.field_ranges.items():
                record[f"{name}_min"] = None if bounds[0] == math.inf else bounds[0]
                record[f"{name}_max"] = None if bounds[1] == -math.inf else bounds[1]
            frame_index.append(record)
            frame_number += 1
        if coordinate_batch:
            connection.executemany("INSERT OR IGNORE INTO coordinates VALUES (?, ?)", coordinate_batch)
        connection.commit()
        if not frame_index:
            return {"normalized": False, "reason": "no_numeric_points", "headers": headers}
        unique_coordinates = int(connection.execute("SELECT COUNT(*) FROM coordinates").fetchone()[0])
        indexed_nodes = int(connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
        row_count = table_counts["elements"]
        coordinate_drop_fraction = round(dropped / row_count, 8) if row_count else 0.0
        sampled_points = sum(int(record["output_count"]) for record in sampling_records)
        exact_ranges: dict[str, float | None] = {}
        finite_coverage: dict[str, float] = {}
        for name, bounds in global_ranges.items():
            exact_ranges[f"{name}_min"] = None if bounds[0] == math.inf else bounds[0]
            exact_ranges[f"{name}_max"] = None if bounds[1] == -math.inf else bounds[1]
            finite_coverage[name] = round(field_counts[name] / total_points, 8) if total_points else 0.0
        mechanical = any(name in available_fields for name in ("stress", "displacement"))
        field_metadata = {
            name: {
                "unit": "T" if name in {"b", "bx", "by"} else "MPa" if name == "stress" else "mm" if name == "displacement" else None,
                "unit_status": "REFERENCE_CONFIRMED" if name in {"b", "bx", "by"} else "OFFICIAL_EXAMPLE_CONFIRMED" if name in {"stress", "displacement"} else "SOURCE_NATIVE_UNVERIFIED",
                "source_column": field_columns.get(name),
            }
            for name in available_fields
        }
        all_extrema = all(bool(record.get("extrema_preserved")) for record in sampling_records)
        all_region_coverage = all(float(record.get("region_coverage") or 0.0) >= 1.0 for record in sampling_records)
        return {
            "schema_version": 6,
            "native_stream_schema": 2,
            "normalized": True,
            "source_format": "motorcad_table",
            "headers": headers,
            "delimiter": separator,
            "requested_output_columns": configured_outputs,
            "exported_output_columns": outputs,
            "missing_requested_outputs": missing_requested_outputs,
            "coordinate_columns": {"x": x_key, "y": y_key},
            "coordinate_metadata": {
                "unit": "mm" if mechanical else None,
                "unit_status": "OFFICIAL_MECHANICAL_EXAMPLE_CONFIRMED" if mechanical else "SOURCE_NATIVE_UNVERIFIED",
            },
            "field_columns": {key: value for key, value in field_columns.items() if not key.startswith("_")},
            "field_metadata": field_metadata,
            "available_fields": available_fields,
            "regions": sorted(all_regions),
            "region_names": region_names,
            "native_table_counts": table_counts,
            "native_table_declared_counts": declared_counts,
            "connectivity_columns": {"element": "TriIndex", "nodes": ["Node1", "Node2", "Node3"]},
            "capabilities": {
                "playback": len(frame_index) > 1,
                "autoplay_30": len(frame_index) > 1,
                "field_selection": len(available_fields) > 1,
                "region_filter": bool(all_regions),
                "manual_range": True,
                "nearest_point_probe": True,
                "raw_download": True,
                "connectivity_metadata": True,
                "mesh_edges": full_mesh_frame_count == len(frame_index) and full_mesh_frame_count > 0,
                "filled_contours": full_mesh_frame_count == len(frame_index) and full_mesh_frame_count > 0,
                "full_region_mesh": full_mesh_frame_count == len(frame_index) and full_mesh_frame_count > 0,
                "progressive_mesh_chunks": bool(frame_index),
                "auto_focus": True,
                "pan": True,
                "zoom": True,
                "rotate_2_5d": True,
                "equipotential_lines": False,
            },
            "viewer_contract": {
                "contract_version": "0.89-G3.3",
                "render_geometry": "native_triangle_elements",
                "surface_mode": "2.5d_engineering_plane",
                "target_playback_frames": 30,
                "playback_frame_indices": list(range(min(30, len(frame_index)))),
                "mesh_manifest_endpoint": "/api/cases/{case_id}/fea-frames/{frame_index}/mesh-manifest",
                "mesh_chunk_endpoint": "/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{chunk_index}",
                "default_mesh_edges": True,
                "default_auto_focus": True,
            },
            "row_count": row_count,
            "dropped_rows": dropped,
            "source_point_count": total_points,
            "display_point_count": sampled_points,
            "quality_metrics": {
                "coordinate_valid_fraction": round(1.0 - coordinate_drop_fraction, 8),
                "coordinate_drop_fraction": coordinate_drop_fraction,
                "unique_coordinate_count": unique_coordinates,
                "duplicate_coordinate_count": max(0, total_points - unique_coordinates),
                "finite_field_coverage": finite_coverage,
                "region_count": len(all_regions),
                "mesh_frame_count": mesh_frame_count,
                "full_mesh_frame_count": full_mesh_frame_count,
            },
            "sampling_contract": {
                "strategy": "region_field_coordinate_hash_v1",
                "max_points_per_frame": max_points_per_frame,
                "source_point_count": total_points,
                "display_point_count": sampled_points,
                "full_source_ranges": True,
                "all_extrema_preserved": all_extrema,
                "all_regions_preserved": all_region_coverage,
                "frames": sampling_records,
            },
            "normalization_io_contract": "two_pass_native_tables_v1",
            "resource_contract": {
                "element_passes": 2,
                "node_index": "temporary_sqlite_without_rowid",
                "indexed_node_count": indexed_nodes,
                "max_retained_points_per_frame": max_points_per_frame,
                "viewer_chunk_element_limit": viewer_chunk_elements,
                "viewer_mesh_storage": "progressive_verified_json_chunks",
                "full_element_rows_in_memory": False,
                "full_node_table_in_memory": False,
                "frame_write": "atomic_replace",
                "temporary_index_cleanup": "required",
            },
            "frame_integrity": {
                "algorithm": "sha256",
                "registered_frame_count": len(frame_index),
                "all_frames_registered": all(
                    isinstance(record.get("sha256"), str) and len(record["sha256"]) == 64
                    and int(record.get("size_bytes") or 0) > 0 for record in frame_index
                ),
                "verification_policy": "verify_before_serve_or_probe",
            },
            "frame_count": len(frame_index),
            "frames": frame_index,
            "global_ranges": exact_ranges,
        }
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {"normalized": False, "reason": f"native_stream_parse_failed: {type(exc).__name__}: {exc}"}
    finally:
        if connection is not None:
            connection.close()
        index_path.unlink(missing_ok=True)
        Path(str(index_path) + "-journal").unlink(missing_ok=True)
