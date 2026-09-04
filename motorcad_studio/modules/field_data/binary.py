"""Binary indexed FieldData materialization and HTTP range delivery.

The adapter consumes the verified Motor-CAD native FEA evidence already owned by the
FieldData bounded context. It produces deterministic TypedArray payloads on demand,
keeps topology identity stable across transient frames, and avoids loading binary
responses into the FastAPI process for normal full-file transfers.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import threading
from array import array
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .adapters.compatibility import FieldDataCompatibilityAdapter

MAGIC = b"MCFD"
FORMAT_VERSION = 1
_FIXED_HEADER = struct.Struct("<4sHHI")
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _surface_faces(node_ids: Sequence[str], coordinates: Mapping[str, tuple[float, float, float]]) -> list[tuple[str, str, str]]:
    ids = [str(v) for v in node_ids if str(v) in coordinates]
    n = len(ids)
    if n == 3:
        return [(ids[0], ids[1], ids[2])]
    if n == 4:
        zs = [coordinates[v][2] for v in ids]
        if max(zs) - min(zs) > 1e-12:
            return [
                (ids[0], ids[1], ids[2]),
                (ids[0], ids[3], ids[1]),
                (ids[1], ids[3], ids[2]),
                (ids[2], ids[3], ids[0]),
            ]
        return [(ids[0], ids[1], ids[2]), (ids[0], ids[2], ids[3])]
    if n == 5:  # pyramid
        return [
            (ids[0], ids[1], ids[2]), (ids[0], ids[2], ids[3]),
            (ids[0], ids[4], ids[1]), (ids[1], ids[4], ids[2]),
            (ids[2], ids[4], ids[3]), (ids[3], ids[4], ids[0]),
        ]
    if n == 6:  # wedge
        return [
            (ids[0], ids[1], ids[2]), (ids[3], ids[5], ids[4]),
            (ids[0], ids[3], ids[4]), (ids[0], ids[4], ids[1]),
            (ids[1], ids[4], ids[5]), (ids[1], ids[5], ids[2]),
            (ids[2], ids[5], ids[3]), (ids[2], ids[3], ids[0]),
        ]
    if n == 8:  # hexahedron
        quads = [
            (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
            (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
        ]
        result: list[tuple[str, str, str]] = []
        for a, b, c, d in quads:
            result.extend(((ids[a], ids[b], ids[c]), (ids[a], ids[c], ids[d])))
        return result
    if n > 3:
        return [(ids[0], ids[i], ids[i + 1]) for i in range(1, n - 1)]
    return []


def _boundary_faces(elements: Sequence[Mapping[str, Any]], coordinates: Mapping[str, tuple[float, float, float]]) -> list[tuple[str, str, str]]:
    # Remove shared volume faces while preserving ordinary adjacent surface triangles.
    candidates: list[tuple[str, str, str]] = []
    counts: dict[tuple[str, ...], int] = {}
    keyed: list[tuple[tuple[str, ...], tuple[str, str, str]]] = []
    for element in elements:
        ids = [str(v) for v in (element.get("node_ids") or element.get("nodes") or [])]
        faces = _surface_faces(ids, coordinates)
        is_volume = len(ids) in {4, 5, 6, 8} and (
            len(ids) != 4 or max((coordinates.get(v, (0.0, 0.0, 0.0))[2] for v in ids), default=0.0)
            - min((coordinates.get(v, (0.0, 0.0, 0.0))[2] for v in ids), default=0.0) > 1e-12
        )
        for face in faces:
            key = tuple(sorted(face)) if is_volume else (f"surface:{len(keyed)}",)
            counts[key] = counts.get(key, 0) + 1
            keyed.append((key, face))
    for key, face in keyed:
        if key[0].startswith("surface:") or counts.get(key) == 1:
            candidates.append(face)
    return candidates


def _extract_mesh(payload: Mapping[str, Any], *, field: str, region: str | None) -> tuple[array, array, array, dict[str, Any]]:
    raw_nodes = payload.get("mesh_nodes") or payload.get("nodes") or []
    raw_elements = payload.get("elements") or payload.get("points") or []
    nodes: dict[str, tuple[float, float, float]] = {}
    node_rows: dict[str, Mapping[str, Any]] = {}
    for offset, row in enumerate(raw_nodes):
        if not isinstance(row, Mapping):
            continue
        node_id = str(row.get("id") or row.get("node_id") or offset)
        nodes[node_id] = (_finite(row.get("x")), _finite(row.get("y")), _finite(row.get("z")))
        node_rows[node_id] = row
    elements = [
        row for row in raw_elements
        if isinstance(row, Mapping) and (not region or str(row.get("region") or "") == region)
    ]
    # Some native exports provide only per-element centroids. Create stable vertices so
    # a usable point cloud still reaches the viewer, while the manifest marks topology.
    if not nodes:
        for offset, row in enumerate(elements):
            node_id = str(row.get("id") or row.get("element_id") or offset)
            nodes[node_id] = (_finite(row.get("x")), _finite(row.get("y")), _finite(row.get("z")))
            node_rows[node_id] = row
            row = dict(row)
            row["node_ids"] = [node_id]
            elements[offset] = row

    ordered_ids = sorted(nodes, key=lambda item: (len(item), item))
    index_by_id = {node_id: i for i, node_id in enumerate(ordered_ids)}
    positions = array("f")
    for node_id in ordered_ids:
        positions.extend(nodes[node_id])

    scalar_sum = [0.0] * len(ordered_ids)
    scalar_count = [0] * len(ordered_ids)
    for node_id, row in node_rows.items():
        if field in row:
            idx = index_by_id[node_id]
            scalar_sum[idx] += _finite(row.get(field))
            scalar_count[idx] += 1
    for element in elements:
        value = _finite(element.get(field), 0.0)
        for node_id in element.get("node_ids") or element.get("nodes") or []:
            node_id = str(node_id)
            if node_id in index_by_id:
                idx = index_by_id[node_id]
                scalar_sum[idx] += value
                scalar_count[idx] += 1
    scalars = array("f", [
        scalar_sum[i] / scalar_count[i] if scalar_count[i] else 0.0
        for i in range(len(ordered_ids))
    ])

    faces = _boundary_faces(elements, nodes)
    indices = array("I")
    for a, b, c in faces:
        if a in index_by_id and b in index_by_id and c in index_by_id:
            indices.extend((index_by_id[a], index_by_id[b], index_by_id[c]))
    # Point-only fallback: preserve positions/scalars with an empty index buffer.
    minimum = min(scalars) if scalars else 0.0
    maximum = max(scalars) if scalars else 0.0
    xs = [v[0] for v in nodes.values()] or [0.0]
    ys = [v[1] for v in nodes.values()] or [0.0]
    zs = [v[2] for v in nodes.values()] or [0.0]
    metadata = {
        "vertex_count": len(ordered_ids),
        "triangle_count": len(indices) // 3,
        "scalar_range": [minimum, maximum],
        "bounds": [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)],
        "physical_z": (max(zs) - min(zs)) > 1e-12,
        "mesh_complete": bool(indices),
        "field": field,
        "region": region,
    }
    return positions, indices, scalars, metadata


def encode_frame(
    positions: array,
    indices: array,
    scalars: array,
    *,
    metadata: Mapping[str, Any],
    source_hash: str,
    frame_index: int,
) -> tuple[bytes, dict[str, Any]]:
    if positions.typecode != "f" or scalars.typecode != "f" or indices.typecode != "I":
        raise TypeError("binary FieldData requires Float32 positions/scalars and Uint32 indices")
    # Python arrays follow host endian. Supported production targets are little-endian;
    # byteswap explicitly on any unusual host to keep the transfer contract stable.
    import sys
    if sys.byteorder != "little":
        positions = array("f", positions); positions.byteswap()
        indices = array("I", indices); indices.byteswap()
        scalars = array("f", scalars); scalars.byteswap()
    position_bytes = positions.tobytes()
    index_bytes = indices.tobytes()
    scalar_bytes = scalars.tobytes()
    topology_hash = _sha(position_bytes + index_bytes)
    scalar_hash = _sha(scalar_bytes)
    frame_hash = _sha(bytes.fromhex(topology_hash) + bytes.fromhex(scalar_hash))

    header: dict[str, Any] = {
        "authority": "MotorCADFieldDataBinaryV1",
        "format_version": FORMAT_VERSION,
        "frame_index": int(frame_index),
        "source_sha256": source_hash,
        "topology_hash": topology_hash,
        "scalar_hash": scalar_hash,
        "frame_hash": frame_hash,
        **dict(metadata),
        "arrays": {},
    }
    # Header offsets depend on the JSON length. Iterate until the encoded header and
    # offsets converge; fixed-width integer changes normally settle in two iterations.
    header_bytes = b""
    for _ in range(8):
        data_offset = _FIXED_HEADER.size + len(header_bytes)
        data_offset += (-data_offset) % 8
        arrays = {
            "positions": {"dtype": "float32", "components": 3, "offset": data_offset, "byte_length": len(position_bytes), "count": len(positions) // 3},
            "indices": {"dtype": "uint32", "components": 1, "offset": data_offset + len(position_bytes), "byte_length": len(index_bytes), "count": len(indices)},
            "scalars": {"dtype": "float32", "components": 1, "offset": data_offset + len(position_bytes) + len(index_bytes), "byte_length": len(scalar_bytes), "count": len(scalars)},
        }
        header["arrays"] = arrays
        candidate = _canonical(header)
        if candidate == header_bytes:
            break
        header_bytes = candidate
    prefix = _FIXED_HEADER.pack(MAGIC, FORMAT_VERSION, 0, len(header_bytes))
    padding = b"\0" * ((-(_FIXED_HEADER.size + len(header_bytes))) % 8)
    payload = prefix + header_bytes + padding + position_bytes + index_bytes + scalar_bytes
    header["payload_sha256"] = _sha(payload)
    header["size_bytes"] = len(payload)
    return payload, header


def decode_header(payload: bytes) -> dict[str, Any]:
    if len(payload) < _FIXED_HEADER.size:
        raise ValueError("binary FieldData payload is truncated")
    magic, version, flags, header_length = _FIXED_HEADER.unpack_from(payload, 0)
    if magic != MAGIC or version != FORMAT_VERSION:
        raise ValueError("binary FieldData magic or version is invalid")
    end = _FIXED_HEADER.size + int(header_length)
    header = json.loads(payload[_FIXED_HEADER.size:end].decode("utf-8"))
    header["flags"] = flags
    return header


class BinaryFieldDataService:
    CONTRACT_VERSION = "1"

    def __init__(self, backend: FieldDataCompatibilityAdapter) -> None:
        self.backend = backend
        self._locks_guard = threading.RLock()
        self._locks: dict[str, threading.Lock] = {}

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _source_identity(self, case_id: str, frame_index: int) -> tuple[dict[str, Any], Path, Path, Path | None, str]:
        """Resolve immutable source identity without decoding the heavy mesh payload.

        The old path decoded every JSON chunk before looking at the binary cache. A single
        29-frame viewer session therefore repeatedly reparsed the full native mesh even on
        cache hits. The viewer-manifest digest already commits to its verified chunks, so it
        is sufficient for a deterministic binary cache key.
        """
        _, manifest, root = self.backend._manifest_payload(case_id)
        frames = (manifest.get("normalization") or {}).get("frames") or []
        record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail="FEA frame does not exist")
        frame_path, _, frame_hash = self.backend._verified_fea_frame(root, record)
        source_hash = frame_hash or hashlib.sha256(frame_path.read_bytes()).hexdigest()
        viewer_path: Path | None = None
        if record.get("viewer_manifest_file"):
            viewer_path, viewer_hash = self.backend._verified_fea_viewer_manifest(root, record)
            source_hash = hashlib.sha256((source_hash + viewer_hash).encode("ascii")).hexdigest()
        return record, root, frame_path, viewer_path, source_hash

    def _source_payload(self, frame_path: Path, viewer_path: Path | None) -> dict[str, Any]:
        """Decode native mesh data only after a binary-cache miss."""
        try:
            frame_payload = json.loads(frame_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail=f"FEA frame cannot be decoded: {type(exc).__name__}") from exc
        if viewer_path is None:
            return frame_payload
        try:
            viewer = json.loads(viewer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail=f"FEA viewer manifest cannot be decoded: {type(exc).__name__}") from exc
        merged_nodes: dict[str, Mapping[str, Any]] = {}
        merged_elements: list[Mapping[str, Any]] = []
        for chunk in viewer.get("chunks") or []:
            chunk_path, _ = self.backend._verified_fea_viewer_chunk(viewer_path, chunk)
            try:
                chunk_payload = json.loads(chunk_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=409, detail=f"FEA viewer chunk cannot be decoded: {type(exc).__name__}") from exc
            for offset, node in enumerate(chunk_payload.get("mesh_nodes") or chunk_payload.get("nodes") or []):
                if isinstance(node, Mapping):
                    node_id = str(node.get("id") or node.get("node_id") or f"{chunk.get('index',0)}:{offset}")
                    merged_nodes[node_id] = node
            merged_elements.extend(
                row for row in (chunk_payload.get("elements") or chunk_payload.get("points") or [])
                if isinstance(row, Mapping)
            )
        if merged_nodes or merged_elements:
            frame_payload = dict(frame_payload)
            frame_payload["mesh_nodes"] = list(merged_nodes.values())
            frame_payload["elements"] = merged_elements
        return frame_payload

    @staticmethod
    def _cache_key(frame_index: int, field: str, region: str | None, source_hash: str) -> str:
        identity = _canonical({"frame_index": int(frame_index), "field": field, "region": region, "source_sha256": source_hash})
        return _sha(identity)

    def materialize(self, case_id: str, frame_index: int, *, field: str = "b", region: str | None = None) -> tuple[Path, dict[str, Any]]:
        record, root, frame_path, viewer_path, source_hash = self._source_identity(case_id, frame_index)
        key = self._cache_key(frame_index, field, region, source_hash)
        target_dir = (root / "binary_frames").resolve()
        if root != target_dir and root not in target_dir.parents:
            raise HTTPException(status_code=403, detail="Binary FieldData cache path escaped the case evidence root")
        target = target_dir / f"frame_{int(frame_index):04d}_{key[:16]}.mcfd"
        manifest_path = target.with_suffix(".json")
        with self._lock_for(str(target)):
            if target.exists() and manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    # Binary filenames are content-addressed by immutable source identity.
                    # Avoid an O(file-size) SHA pass on every manifest/range request; atomic
                    # creation plus source hash + exact size is the hot-path integrity gate.
                    if (
                        manifest.get("authority") == "MotorCADFieldDataBinaryV1"
                        and manifest.get("source_sha256") == source_hash
                        and target.stat().st_size == int(manifest.get("size_bytes") or 0)
                        and manifest.get("payload_sha256")
                    ):
                        return target, manifest
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            payload = self._source_payload(frame_path, viewer_path)
            positions, indices, scalars, mesh_meta = _extract_mesh(payload, field=field, region=region)
            binary, header = encode_frame(
                positions, indices, scalars,
                metadata={
                    **mesh_meta,
                    "case_id": case_id,
                    "step": record.get("step"),
                    "source_authority": "MotorCADNativeFEAEvidenceV1",
                    "coordinate_unit": (payload.get("coordinate_unit") or payload.get("length_unit")),
                },
                source_hash=source_hash,
                frame_index=frame_index,
            )
            # encode_frame hashes before attaching payload_sha256 to its in-memory header.
            header["payload_sha256"] = hashlib.sha256(binary).hexdigest()
            header["size_bytes"] = len(binary)
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
            tmp_manifest = manifest_path.with_suffix(manifest_path.suffix + f".{os.getpid()}.tmp")
            tmp.write_bytes(binary)
            tmp_manifest.write_text(json.dumps(header, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            os.replace(tmp, target)
            os.replace(tmp_manifest, manifest_path)
            return target, header

    def manifest(self, case_id: str, frame_index: int, request: Request, *, field: str = "b", region: str | None = None):
        path, manifest = self.materialize(case_id, frame_index, field=field, region=region)
        etag = f'"{manifest["payload_sha256"]}"'
        headers = {"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable", "X-MCS-Field-Data-Binary": "1"}
        if self.backend._etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        payload = {
            **manifest,
            "binary_url": f"/api/cases/{case_id}/field-data/frames/{frame_index}/binary?field={field}" + (f"&region={region}" if region else ""),
            "range_requests": True,
            "topology_reuse": True,
            "scalar_only_frame_update": True,
        }
        return JSONResponse(payload, headers=headers)

    @staticmethod
    def _range(value: str | None, size: int) -> tuple[int, int] | None:
        if not value:
            return None
        match = _RANGE_RE.match(value.strip())
        if not match or "," in value:
            raise HTTPException(status_code=416, detail="Only one byte range is supported", headers={"Content-Range": f"bytes */{size}"})
        start_text, end_text = match.groups()
        if not start_text and not end_text:
            raise HTTPException(status_code=416, detail="Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
        if not start_text:
            length = int(end_text)
            if length <= 0:
                raise HTTPException(status_code=416, detail="Invalid suffix byte range", headers={"Content-Range": f"bytes */{size}"})
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        if start < 0 or start >= size or end < start:
            raise HTTPException(status_code=416, detail="Byte range is outside the resource", headers={"Content-Range": f"bytes */{size}"})
        return start, min(end, size - 1)

    def binary(self, case_id: str, frame_index: int, request: Request, *, field: str = "b", region: str | None = None):
        path, manifest = self.materialize(case_id, frame_index, field=field, region=region)
        size = path.stat().st_size
        etag = f'"{manifest["payload_sha256"]}"'
        common = {
            "ETag": etag,
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-MCS-Field-Data-Binary": "1",
            "X-MCS-Topology-Hash": str(manifest.get("topology_hash") or ""),
            "X-MCS-Frame-Hash": str(manifest.get("frame_hash") or ""),
        }
        # Integrity was checked/materialized before honoring the conditional request.
        if self.backend._etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=common)
        byte_range = self._range(request.headers.get("range"), size)
        if byte_range is None:
            return FileResponse(path, media_type="application/vnd.motorcad.fielddata", filename=path.name, headers=common)
        start, end = byte_range
        length = end - start + 1
        def stream() -> Iterable[bytes]:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        return StreamingResponse(stream(), status_code=206, media_type="application/vnd.motorcad.fielddata", headers={**common, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})

    def summary(self) -> dict[str, Any]:
        return {"authority": "BinaryFieldDataServiceV1", "contract_version": self.CONTRACT_VERSION, "format": "MotorCADFieldDataBinaryV1", "range_requests": True, "topology_reuse": True}


__all__ = ["BinaryFieldDataService", "decode_header", "encode_frame", "MAGIC", "FORMAT_VERSION"]
