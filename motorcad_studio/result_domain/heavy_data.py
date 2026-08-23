from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Database
from .contracts import ResultDataRef

RESULT_DATA_GATEWAY_CONTRACT_VERSION = "0.80-A"
RESULT_DATA_SCHEMA_VERSION = 2
CHUNKPACK_FORMAT = "mcs-chunkpack-v1"
HEAVY_RESULT_TYPES = frozenset({"series", "spectrum", "map", "field", "vector_field", "table", "artifact"})
CHUNK_NATIVE_TYPES = frozenset({"series", "spectrum", "map", "field", "vector_field", "table"})
DEFAULT_INLINE_MAX_BYTES = 32 * 1024
DEFAULT_CHUNK_SIZE_ITEMS = 2048
DEFAULT_CHUNK_TARGET_BYTES = 256 * 1024
DEFAULT_GC_GRACE_SECONDS = 3600
MAX_WINDOW_ITEMS = 100_000


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _shape(value: Any, *, max_depth: int = 8) -> list[int]:
    shape: list[int] = []
    current = value
    for _ in range(max_depth):
        if not isinstance(current, list):
            break
        shape.append(len(current))
        if not current:
            break
        first = current[0]
        if any((isinstance(item, list) != isinstance(first, list)) for item in current[:32]):
            break
        current = first
    return shape


def _item_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("values", "data", "y", "z", "rows", "points", "nodes", "frames"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return len(candidate)
        return len(value)
    return None


def _utc_age_seconds(value: str | None, now: datetime) -> float:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return 0.0


class ResultDataGateway:
    """V0.80-A content-addressed heavy-result storage with chunk-native random access.

    Engineering identity is always SHA-256 of the *complete canonical logical payload*.
    New Series/Table/Map/Field/VectorField objects are persisted as MCS ChunkPack V1:
    a small manifest plus independently compressed, independently hashed chunks.  Legacy
    V0.79-C ``json-gzip`` objects remain readable indefinitely and are never rewritten
    behind an immutable ResultBundle reference.
    """

    def __init__(
        self,
        db: Database,
        root: Path | None = None,
        *,
        inline_max_bytes: int | None = None,
        chunk_size_items: int | None = None,
    ):
        self.db = db
        if root is None:
            configured_root = os.getenv("MOTORCAD_STUDIO_RESULT_DATA_DIR")
            configured_results = os.getenv("MOTORCAD_STUDIO_RESULTS_DIR")
            if configured_root:
                root = Path(configured_root)
            elif configured_results:
                root = Path(configured_results) / "result_data"
            else:
                db_parent = Path(db.path).resolve().parent
                root = (db_parent.parent / "results" / "result_data") if db_parent.name == "runtime" else (db_parent / "result_data")
        self.root = Path(root).resolve()
        self.objects_dir = self.root / "sha256"
        self.chunks_dir = self.root / "chunks" / "sha256"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        configured_inline = os.getenv("MOTORCAD_STUDIO_RESULT_INLINE_MAX_BYTES")
        configured_chunk = os.getenv("MOTORCAD_STUDIO_RESULT_CHUNK_ITEMS")
        configured_target = os.getenv("MOTORCAD_STUDIO_RESULT_CHUNK_TARGET_BYTES")
        self.inline_max_bytes = max(0, int(configured_inline or inline_max_bytes or DEFAULT_INLINE_MAX_BYTES))
        self.chunk_size_items = max(64, int(configured_chunk or chunk_size_items or DEFAULT_CHUNK_SIZE_ITEMS))
        self.chunk_target_bytes = max(32 * 1024, int(configured_target or DEFAULT_CHUNK_TARGET_BYTES))
        self.gc_grace_seconds = max(0, int(os.getenv("MOTORCAD_STUDIO_RESULT_GC_GRACE_SECONDS") or DEFAULT_GC_GRACE_SECONDS))

    @staticmethod
    def canonical_bytes(value: Any) -> bytes:
        return _canonical_json_bytes(value)

    @staticmethod
    def content_hash(value: Any) -> str:
        return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()

    def should_externalize(self, result_type: str, value: Any) -> bool:
        if value is None or str(result_type) not in HEAVY_RESULT_TYPES:
            return False
        return len(_canonical_json_bytes(value)) > self.inline_max_bytes

    @staticmethod
    def _legacy_storage_key(content_hash: str) -> str:
        digest = str(content_hash).lower()
        return f"sha256/{digest[:2]}/{digest}.json.gz"

    @staticmethod
    def _manifest_storage_key(content_hash: str) -> str:
        digest = str(content_hash).lower()
        return f"sha256/{digest[:2]}/{digest}.chunkpack.json"

    @staticmethod
    def _chunk_storage_key(chunk_hash: str) -> str:
        digest = str(chunk_hash).lower()
        return f"chunks/sha256/{digest[:2]}/{digest}.json.gz"

    @staticmethod
    def _validate_digest(content_hash: str) -> str:
        digest = str(content_hash).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"Invalid ResultData content hash: {content_hash}")
        return digest

    def _expected_object_key(self, content_hash: str, encoding: str) -> str:
        return self._manifest_storage_key(content_hash) if encoding == CHUNKPACK_FORMAT else self._legacy_storage_key(content_hash)

    def _safe_path(self, storage_key: str) -> Path:
        target = (self.root / str(storage_key).replace("\\", "/")).resolve()
        if target != self.root and self.root not in target.parents:
            raise RuntimeError("ResultData storage path escapes configured root")
        return target

    def _path_for_hash(self, content_hash: str, row: dict[str, Any] | None = None) -> Path:
        digest = self._validate_digest(content_hash)
        encoding = str((row or {}).get("encoding") or "json-gzip")
        expected_key = self._expected_object_key(digest, encoding)
        if row is not None:
            recorded_key = str(row.get("storage_key") or expected_key).replace("\\", "/")
            if recorded_key != expected_key:
                raise RuntimeError(f"ResultData storage-key mismatch: {digest}")
        return self._safe_path(expected_key)

    def _chunk_path(self, chunk_hash: str, storage_key: str | None = None) -> Path:
        digest = self._validate_digest(chunk_hash)
        expected = self._chunk_storage_key(digest)
        if storage_key is not None and str(storage_key).replace("\\", "/") != expected:
            raise RuntimeError(f"ResultData chunk storage-key mismatch: {digest}")
        return self._safe_path(expected)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name[:18]}-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _chunk_layout(value: Any, logical_type: str) -> dict[str, Any] | None:
        if str(logical_type) not in CHUNK_NATIVE_TYPES:
            return None
        if isinstance(value, list):
            return {"mode": "sequence", "total": len(value), "chunk_keys": [], "static_payload": None, "path": None}
        if not isinstance(value, dict):
            return None

        # Prefer known engineering data alignments.  This keeps map rows, field points,
        # vector points and x/y series coherent when only a subset is requested.
        preferred = (
            (("points", "vectors"), "vector_points"),
            (("points", "values"), "field_points"),
            (("nodes", "values"), "field_nodes"),
            (("y", "z"), "map_rows"),
            (("x", "y"), "aligned_axes"),
        )
        for keys, label in preferred:
            arrays = [value.get(key) for key in keys]
            if all(isinstance(arr, list) for arr in arrays) and len({len(arr) for arr in arrays}) == 1 and len(arrays[0]) > 0:
                total = len(arrays[0])
                chunk_keys = [key for key, candidate in value.items() if isinstance(candidate, list) and len(candidate) == total]
                static = {key: candidate for key, candidate in value.items() if key not in chunk_keys}
                return {"mode": "aligned_dict", "total": total, "chunk_keys": chunk_keys, "static_payload": static, "path": label}

        list_lengths = Counter(len(candidate) for candidate in value.values() if isinstance(candidate, list) and len(candidate) > 0)
        if not list_lengths:
            return None
        total, frequency = max(list_lengths.items(), key=lambda item: (item[1], item[0]))
        # A single obvious sequence such as ``rows`` is still chunkable.
        chunk_keys = [key for key, candidate in value.items() if isinstance(candidate, list) and len(candidate) == total]
        if not chunk_keys:
            return None
        static = {key: candidate for key, candidate in value.items() if key not in chunk_keys}
        label = chunk_keys[0] if len(chunk_keys) == 1 else "aligned_arrays"
        return {"mode": "aligned_dict", "total": total, "chunk_keys": chunk_keys, "static_payload": static, "path": label}

    def _write_legacy_object(self, digest: str, raw: bytes) -> dict[str, Any]:
        target = self._path_for_hash(digest, {"encoding": "json-gzip", "storage_key": self._legacy_storage_key(digest)})
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        if target.exists():
            try:
                existing = gzip.decompress(target.read_bytes())
            except OSError as exc:
                raise RuntimeError(f"ResultData object unreadable: {digest}") from exc
            if hashlib.sha256(existing).hexdigest() != digest:
                raise RuntimeError(f"ResultData content-address collision/corruption: {digest}")
        else:
            self._atomic_write(target, compressed)
        return {
            "encoding": "json-gzip",
            "storage_key": self._legacy_storage_key(digest),
            "manifest_hash": None,
            "chunk_count": 0,
            "chunk_size_items": None,
            "stored_bytes": len(compressed),
            "chunks": [],
        }

    def _write_chunkpack(self, digest: str, value: Any, raw: bytes, *, logical_type: str, layout: dict[str, Any]) -> dict[str, Any]:
        total = int(layout["total"])
        estimated_item_bytes = max(1.0, len(raw) / max(1, total))
        target_items = max(64, int(self.chunk_target_bytes / estimated_item_bytes))
        chunk_size = max(1, min(self.chunk_size_items, target_items, total))
        chunks: list[dict[str, Any]] = []
        for index, start in enumerate(range(0, total, chunk_size)):
            end = min(total, start + chunk_size)
            if layout["mode"] == "sequence":
                chunk_payload = value[start:end]
            else:
                chunk_payload = {key: value[key][start:end] for key in layout["chunk_keys"]}
            chunk_raw = _canonical_json_bytes(chunk_payload)
            chunk_hash = hashlib.sha256(chunk_raw).hexdigest()
            chunk_key = self._chunk_storage_key(chunk_hash)
            chunk_path = self._chunk_path(chunk_hash, chunk_key)
            compressed = gzip.compress(chunk_raw, compresslevel=6, mtime=0)
            if chunk_path.exists():
                try:
                    existing = gzip.decompress(chunk_path.read_bytes())
                except OSError as exc:
                    raise RuntimeError(f"ResultData chunk unreadable: {chunk_hash}") from exc
                if hashlib.sha256(existing).hexdigest() != chunk_hash:
                    raise RuntimeError(f"ResultData chunk content-address collision/corruption: {chunk_hash}")
            else:
                self._atomic_write(chunk_path, compressed)
            chunks.append({
                "index": index,
                "offset": start,
                "item_count": end - start,
                "chunk_hash": chunk_hash,
                "storage_key": chunk_key,
                "size_bytes": len(chunk_raw),
                "stored_bytes": len(compressed),
            })

        manifest = {
            "format": CHUNKPACK_FORMAT,
            "schema_version": RESULT_DATA_SCHEMA_VERSION,
            "contract_version": RESULT_DATA_GATEWAY_CONTRACT_VERSION,
            "content_hash": digest,
            "logical_type": str(logical_type),
            "size_bytes": len(raw),
            "item_count": total,
            "chunk_size_items": chunk_size,
            "layout": layout,
            "chunks": chunks,
        }
        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_key = self._manifest_storage_key(digest)
        manifest_path = self._safe_path(manifest_key)
        if manifest_path.exists():
            existing = manifest_path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != manifest_hash:
                raise RuntimeError(f"ResultData manifest collision/corruption: {digest}")
        else:
            self._atomic_write(manifest_path, manifest_bytes)
        return {
            "encoding": CHUNKPACK_FORMAT,
            "storage_key": manifest_key,
            "manifest_hash": manifest_hash,
            "chunk_count": len(chunks),
            "chunk_size_items": chunk_size,
            "stored_bytes": len(manifest_bytes) + sum(int(row["stored_bytes"]) for row in chunks),
            "chunks": chunks,
        }

    def _persist_object_metadata(self, digest: str, raw_size: int, storage: dict[str, Any]) -> None:
        now = self.db.now()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO result_data_objects(
                       content_hash,storage_key,encoding,media_type,size_bytes,stored_bytes,schema_version,
                       created_at,last_verified_at,layout,chunk_count,chunk_size_items,manifest_hash
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(content_hash) DO UPDATE SET
                       storage_key=excluded.storage_key,encoding=excluded.encoding,size_bytes=excluded.size_bytes,
                       stored_bytes=excluded.stored_bytes,schema_version=excluded.schema_version,
                       layout=excluded.layout,chunk_count=excluded.chunk_count,
                       chunk_size_items=excluded.chunk_size_items,manifest_hash=excluded.manifest_hash""",
                (
                    digest, storage["storage_key"], storage["encoding"], "application/json", raw_size,
                    int(storage["stored_bytes"]), RESULT_DATA_SCHEMA_VERSION, now, now,
                    "chunked" if storage["encoding"] == CHUNKPACK_FORMAT else "monolithic",
                    int(storage.get("chunk_count") or 0), storage.get("chunk_size_items"), storage.get("manifest_hash"),
                ),
            )
            conn.execute("DELETE FROM result_data_chunks WHERE parent_content_hash=?", (digest,))
            for row in storage.get("chunks") or []:
                conn.execute(
                    """INSERT INTO result_data_chunks(
                           parent_content_hash,chunk_index,chunk_hash,storage_key,offset_items,item_count,
                           size_bytes,stored_bytes,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        digest, int(row["index"]), row["chunk_hash"], row["storage_key"], int(row["offset"]),
                        int(row["item_count"]), int(row["size_bytes"]), int(row["stored_bytes"]), now,
                    ),
                )

    def _ref_for(self, row: dict[str, Any], *, logical_type: str, value: Any, data_profile: dict[str, Any] | None) -> ResultDataRef:
        profile = dict(data_profile or {})
        if "shape" not in profile:
            detected = _shape(value)
            if detected:
                profile["shape"] = detected
        count = _item_count(value)
        encoding = str(row.get("encoding") or "json-gzip")
        chunk_count = int(row.get("chunk_count") or 0)
        chunk_size = int(row.get("chunk_size_items") or 0) or None
        profile.update({
            "storage_layout": "chunked" if encoding == CHUNKPACK_FORMAT else "monolithic",
            "chunk_native": encoding == CHUNKPACK_FORMAT,
        })
        if chunk_count:
            profile.update({"chunk_count": chunk_count, "chunk_size_items": chunk_size})
        return ResultDataRef(
            content_hash=str(row["content_hash"]),
            storage_backend="content_addressed_filesystem",
            encoding=encoding,
            media_type=str(row.get("media_type") or "application/json"),
            logical_type=str(logical_type),
            size_bytes=int(row.get("size_bytes") or 0),
            stored_bytes=int(row.get("stored_bytes") or 0),
            item_count=count,
            shape=list(profile.get("shape") or []),
            layout="chunked" if encoding == CHUNKPACK_FORMAT else "monolithic",
            chunk_count=chunk_count,
            chunk_size_items=chunk_size,
            random_access=encoding == CHUNKPACK_FORMAT,
            data_profile=profile,
        )

    def put(self, value: Any, *, logical_type: str, data_profile: dict[str, Any] | None = None) -> ResultDataRef:
        raw = _canonical_json_bytes(value)
        digest = hashlib.sha256(raw).hexdigest()
        existing = self.metadata(digest)
        if existing and self.available(digest):
            return self._ref_for(existing, logical_type=logical_type, value=value, data_profile=data_profile)

        # Preserve an existing object's encoding if metadata survived but bytes need repair.
        layout = self._chunk_layout(value, logical_type)
        prefer_chunked = bool(layout and int(layout.get("total") or 0) > 0)
        if existing and str(existing.get("encoding") or "") == "json-gzip":
            prefer_chunked = False
        storage = (
            self._write_chunkpack(digest, value, raw, logical_type=logical_type, layout=layout)
            if prefer_chunked and layout is not None
            else self._write_legacy_object(digest, raw)
        )
        self._persist_object_metadata(digest, len(raw), storage)
        return self._ref_for(self.metadata(digest) or {"content_hash": digest, **storage, "size_bytes": len(raw), "media_type": "application/json"}, logical_type=logical_type, value=value, data_profile=data_profile)

    def metadata(self, content_hash: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM result_data_objects WHERE content_hash=?", (content_hash,))

    def _load_manifest(self, content_hash: str, row: dict[str, Any] | None = None) -> dict[str, Any]:
        row = row or self.metadata(content_hash)
        if not row:
            raise KeyError(content_hash)
        if str(row.get("encoding") or "") != CHUNKPACK_FORMAT:
            raise ValueError(f"ResultData is not chunk-native: {content_hash}")
        path = self._path_for_hash(content_hash, row)
        if not path.exists():
            raise FileNotFoundError(f"ResultData manifest missing: {content_hash}")
        raw = path.read_bytes()
        expected_manifest_hash = str(row.get("manifest_hash") or "")
        if expected_manifest_hash and hashlib.sha256(raw).hexdigest() != expected_manifest_hash:
            raise RuntimeError(f"ResultData manifest integrity mismatch: {content_hash}")
        manifest = json.loads(raw.decode("utf-8"))
        if manifest.get("format") != CHUNKPACK_FORMAT or manifest.get("content_hash") != content_hash:
            raise RuntimeError(f"ResultData manifest identity mismatch: {content_hash}")
        indexed = self.db.query_all(
            "SELECT * FROM result_data_chunks WHERE parent_content_hash=? ORDER BY chunk_index", (content_hash,)
        )
        chunks = list(manifest.get("chunks") or [])
        if len(indexed) != len(chunks) or int(row.get("chunk_count") or 0) != len(chunks):
            raise RuntimeError(f"ResultData chunk index count mismatch: {content_hash}")
        for db_row, chunk in zip(indexed, chunks):
            if (
                int(db_row.get("chunk_index") or 0) != int(chunk.get("index") or 0)
                or str(db_row.get("chunk_hash") or "") != str(chunk.get("chunk_hash") or "")
                or str(db_row.get("storage_key") or "") != str(chunk.get("storage_key") or "")
                or int(db_row.get("offset_items") or 0) != int(chunk.get("offset") or 0)
                or int(db_row.get("item_count") or 0) != int(chunk.get("item_count") or 0)
            ):
                raise RuntimeError(f"ResultData chunk index mismatch: {content_hash}:{chunk.get('index')}")
        return manifest

    def _read_chunk(self, chunk: dict[str, Any]) -> Any:
        digest = str(chunk["chunk_hash"])
        path = self._chunk_path(digest, str(chunk.get("storage_key") or ""))
        if not path.exists():
            raise FileNotFoundError(f"ResultData chunk missing: {digest}")
        try:
            raw = gzip.decompress(path.read_bytes())
        except OSError as exc:
            raise RuntimeError(f"ResultData chunk unreadable: {digest}") from exc
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError(f"ResultData chunk integrity mismatch: {digest}")
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _window_chunks(manifest: dict[str, Any], offset: int, limit: int | None) -> tuple[list[dict[str, Any]], int, int, int]:
        total = int(manifest.get("item_count") or (manifest.get("layout") or {}).get("total") or 0)
        start = max(0, min(int(offset or 0), total))
        end = total if limit is None else min(total, start + max(0, min(int(limit), MAX_WINDOW_ITEMS)))
        chunks = [
            row for row in manifest.get("chunks") or []
            if int(row.get("offset") or 0) < end and int(row.get("offset") or 0) + int(row.get("item_count") or 0) > start
        ]
        return chunks, start, end, total

    def chunk_descriptor(self, content_hash: str, chunk_index: int) -> dict[str, Any]:
        row = self.metadata(content_hash)
        if not row:
            raise KeyError(content_hash)
        if str(row.get("encoding") or "json-gzip") != CHUNKPACK_FORMAT:
            raise ValueError(f"ResultData is not chunk-native: {content_hash}")
        manifest = self._load_manifest(content_hash, row)
        index = int(chunk_index)
        descriptor = next((item for item in manifest.get("chunks") or [] if int(item.get("index") or 0) == index), None)
        if descriptor is None:
            raise IndexError(index)
        return descriptor

    def available_chunk(self, content_hash: str, chunk_index: int) -> bool:
        try:
            descriptor = self.chunk_descriptor(content_hash, chunk_index)
            return self._chunk_path(str(descriptor["chunk_hash"]), str(descriptor.get("storage_key") or "")).is_file()
        except (RuntimeError, ValueError, KeyError, IndexError, json.JSONDecodeError):
            return False

    def read_chunk_index(self, content_hash: str, chunk_index: int) -> tuple[Any, dict[str, Any]]:
        descriptor = self.chunk_descriptor(content_hash, chunk_index)
        payload = self._read_chunk(descriptor)
        return payload, {
            "index": int(descriptor.get("index") or 0),
            "offset": int(descriptor.get("offset") or 0),
            "item_count": int(descriptor.get("item_count") or 0),
            "chunk_hash": descriptor.get("chunk_hash"),
            "size_bytes": int(descriptor.get("size_bytes") or 0),
            "stored_bytes": int(descriptor.get("stored_bytes") or 0),
        }

    def available_window(self, content_hash: str, *, offset: int = 0, limit: int | None = None) -> bool:
        row = self.metadata(content_hash)
        if not row:
            return False
        try:
            object_path = self._path_for_hash(content_hash, row)
            if not object_path.is_file():
                return False
            if str(row.get("encoding") or "json-gzip") != CHUNKPACK_FORMAT:
                return True
            manifest = self._load_manifest(content_hash, row)
            chunks, _, _, _ = self._window_chunks(manifest, offset, limit)
            return all(self._chunk_path(str(chunk["chunk_hash"]), str(chunk.get("storage_key") or "")).is_file() for chunk in chunks)
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError):
            return False

    def available(self, content_hash: str) -> bool:
        row = self.metadata(content_hash)
        if not row:
            return False
        try:
            object_path = self._path_for_hash(content_hash, row)
            if not object_path.is_file():
                return False
            if str(row.get("encoding") or "json-gzip") != CHUNKPACK_FORMAT:
                return True
            manifest = self._load_manifest(content_hash, row)
            return all(self._chunk_path(str(chunk["chunk_hash"]), str(chunk.get("storage_key") or "")).is_file() for chunk in manifest.get("chunks") or [])
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError):
            return False

    def _read_legacy(self, content_hash: str, row: dict[str, Any], *, verify: bool = True) -> Any:
        target = self._path_for_hash(content_hash, row)
        if not target.exists():
            raise FileNotFoundError(f"ResultData object missing: {content_hash}")
        try:
            raw = gzip.decompress(target.read_bytes())
        except OSError as exc:
            raise RuntimeError(f"ResultData object unreadable: {content_hash}") from exc
        if verify and hashlib.sha256(raw).hexdigest() != content_hash:
            raise RuntimeError(f"ResultData integrity mismatch: {content_hash}")
        return json.loads(raw.decode("utf-8"))

    def _assemble_chunks(self, manifest: dict[str, Any], chunks: list[dict[str, Any]], *, start: int, end: int) -> tuple[Any, int]:
        layout = dict(manifest.get("layout") or {})
        mode = layout.get("mode")
        bytes_read = 0
        if mode == "sequence":
            output: list[Any] = []
            for descriptor in chunks:
                payload = self._read_chunk(descriptor)
                bytes_read += int(descriptor.get("stored_bytes") or 0)
                chunk_start = int(descriptor.get("offset") or 0)
                local_start = max(0, start - chunk_start)
                local_end = min(len(payload), end - chunk_start)
                if local_end > local_start:
                    output.extend(payload[local_start:local_end])
            return output, bytes_read
        if mode == "aligned_dict":
            output = dict(layout.get("static_payload") or {})
            keys = list(layout.get("chunk_keys") or [])
            for key in keys:
                output[key] = []
            for descriptor in chunks:
                payload = self._read_chunk(descriptor)
                bytes_read += int(descriptor.get("stored_bytes") or 0)
                chunk_start = int(descriptor.get("offset") or 0)
                local_start = max(0, start - chunk_start)
                local_end = min(int(descriptor.get("item_count") or 0), end - chunk_start)
                if local_end <= local_start:
                    continue
                for key in keys:
                    values = payload.get(key) or []
                    output[key].extend(values[local_start:local_end])
            return output, bytes_read
        raise RuntimeError(f"Unsupported ResultData chunk layout: {mode}")

    def read(self, content_hash: str, *, verify: bool = True) -> Any:
        row = self.metadata(content_hash)
        if not row:
            raise KeyError(content_hash)
        if str(row.get("encoding") or "json-gzip") != CHUNKPACK_FORMAT:
            return self._read_legacy(content_hash, row, verify=verify)
        manifest = self._load_manifest(content_hash, row)
        total = int(manifest.get("item_count") or 0)
        value, _ = self._assemble_chunks(manifest, list(manifest.get("chunks") or []), start=0, end=total)
        if verify and hashlib.sha256(_canonical_json_bytes(value)).hexdigest() != content_hash:
            raise RuntimeError(f"ResultData integrity mismatch: {content_hash}")
        return value

    def read_window(self, content_hash: str, *, offset: int = 0, limit: int | None = None) -> tuple[Any, dict[str, Any]]:
        row = self.metadata(content_hash)
        if not row:
            raise KeyError(content_hash)
        if str(row.get("encoding") or "json-gzip") != CHUNKPACK_FORMAT:
            # Legacy V0.79-C path: full object decode followed by projection.
            value = self._read_legacy(content_hash, row, verify=True)
            start = max(0, int(offset or 0))
            if limit is not None:
                limit = max(0, min(int(limit), MAX_WINDOW_ITEMS))
            target = value
            path: str | None = None
            if isinstance(value, dict):
                aligned_groups = (("y", "z", "map_rows"), ("points", "vectors", "vector_points"), ("points", "values", "field_points"), ("nodes", "values", "field_nodes"), ("x", "y", "aligned_axes"))
                for left, right, label in aligned_groups:
                    if isinstance(value.get(left), list) and isinstance(value.get(right), list) and len(value[left]) == len(value[right]):
                        total = len(value[right]); end = total if limit is None else min(total, start + limit)
                        payload = dict(value)
                        for key, candidate in value.items():
                            if isinstance(candidate, list) and len(candidate) == total:
                                payload[key] = candidate[start:end]
                        return payload, {"windowed": True, "offset": start, "limit": end-start, "total": total, "path": label, "chunk_native": False, "chunks_read": 0, "encoding": "json-gzip"}
                for key in ("values", "data", "y", "rows", "points", "frames"):
                    if isinstance(value.get(key), list):
                        target = value[key]; path = key; break
            if not isinstance(target, list):
                return value, {"windowed": False, "offset": 0, "limit": None, "total": None, "path": None, "chunk_native": False, "chunks_read": 0, "encoding": "json-gzip"}
            total = len(target); end = total if limit is None else min(total, start + limit); sliced = target[start:end]
            payload = sliced if path is None else {**value, path: sliced}
            return payload, {"windowed": True, "offset": start, "limit": end-start, "total": total, "path": path, "chunk_native": False, "chunks_read": 0, "encoding": "json-gzip"}

        manifest = self._load_manifest(content_hash, row)
        chunks, start, end, total = self._window_chunks(manifest, offset, limit)
        value, bytes_read = self._assemble_chunks(manifest, chunks, start=start, end=end)
        return value, {
            "windowed": True,
            "offset": start,
            "limit": end - start,
            "total": total,
            "path": (manifest.get("layout") or {}).get("path"),
            "chunk_native": True,
            "encoding": CHUNKPACK_FORMAT,
            "chunks_read": len(chunks),
            "chunk_indexes": [int(row.get("index") or 0) for row in chunks],
            "chunk_count_total": len(manifest.get("chunks") or []),
            "chunk_size_items": int(manifest.get("chunk_size_items") or 0),
            "stored_bytes_read": bytes_read,
        }

    def manifest_info(self, content_hash: str) -> dict[str, Any]:
        row = self.metadata(content_hash)
        if not row:
            raise KeyError(content_hash)
        encoding = str(row.get("encoding") or "json-gzip")
        if encoding != CHUNKPACK_FORMAT:
            return {
                "content_hash": content_hash,
                "encoding": encoding,
                "layout": "monolithic",
                "chunk_native": False,
                "chunk_count": 0,
                "size_bytes": int(row.get("size_bytes") or 0),
                "stored_bytes": int(row.get("stored_bytes") or 0),
            }
        manifest = self._load_manifest(content_hash, row)
        return {
            "content_hash": content_hash,
            "encoding": encoding,
            "layout": "chunked",
            "chunk_native": True,
            "manifest_hash": row.get("manifest_hash"),
            "logical_type": manifest.get("logical_type"),
            "item_count": manifest.get("item_count"),
            "chunk_size_items": manifest.get("chunk_size_items"),
            "chunk_count": len(manifest.get("chunks") or []),
            "size_bytes": int(row.get("size_bytes") or 0),
            "stored_bytes": int(row.get("stored_bytes") or 0),
            "chunk_index": [
                {
                    "index": int(chunk.get("index") or 0), "offset": int(chunk.get("offset") or 0),
                    "item_count": int(chunk.get("item_count") or 0), "chunk_hash": chunk.get("chunk_hash"),
                    "stored_bytes": int(chunk.get("stored_bytes") or 0),
                }
                for chunk in manifest.get("chunks") or []
            ],
        }

    def verify(self, content_hash: str) -> dict[str, Any]:
        row = self.metadata(content_hash)
        if not row:
            return {"content_hash": content_hash, "status": "MISSING_METADATA", "valid": False}
        try:
            value = self.read(content_hash, verify=True)
            self.db.execute("UPDATE result_data_objects SET last_verified_at=? WHERE content_hash=?", (self.db.now(), content_hash))
            raw_size = len(_canonical_json_bytes(value))
            return {
                "content_hash": content_hash,
                "status": "VALID",
                "valid": True,
                "size_bytes": raw_size,
                "stored_bytes": int(row.get("stored_bytes") or 0),
                "encoding": row.get("encoding"),
                "layout": row.get("layout") or ("chunked" if row.get("encoding") == CHUNKPACK_FORMAT else "monolithic"),
                "chunk_count": int(row.get("chunk_count") or 0),
                "manifest_hash": row.get("manifest_hash"),
            }
        except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError, KeyError) as exc:
            return {"content_hash": content_hash, "status": "INVALID", "valid": False, "issue": str(exc), "encoding": row.get("encoding")}

    def status(self) -> dict[str, Any]:
        row = self.db.query_one(
            """SELECT COUNT(*) AS object_count,
                      COALESCE(SUM(size_bytes),0) AS logical_bytes,
                      COALESCE(SUM(stored_bytes),0) AS registered_stored_bytes,
                      SUM(CASE WHEN encoding=? THEN 1 ELSE 0 END) AS chunked_object_count,
                      SUM(CASE WHEN encoding=? THEN 0 ELSE 1 END) AS monolithic_object_count
                 FROM result_data_objects""",
            (CHUNKPACK_FORMAT, CHUNKPACK_FORMAT),
        ) or {}
        refs = self.db.query_one("SELECT COUNT(*) AS ref_count FROM result_bundle_data_refs") or {}
        orphan = self.db.query_one("""SELECT COUNT(*) AS orphan_count FROM result_data_objects o
            WHERE NOT EXISTS (SELECT 1 FROM result_bundle_data_refs r WHERE r.content_hash=o.content_hash)""") or {}
        chunks = self.db.query_one("""SELECT COUNT(*) AS chunk_record_count,
                    COUNT(DISTINCT chunk_hash) AS unique_chunk_count,
                    COALESCE(SUM(stored_bytes),0) AS mapped_chunk_bytes
               FROM result_data_chunks""") or {}
        physical_bytes = 0
        physical_files = 0
        for base, patterns in ((self.objects_dir, ("*.json.gz", "*.chunkpack.json")), (self.chunks_dir, ("*.json.gz",))):
            for pattern in patterns:
                for path in base.glob(f"*/*{pattern[1:]}") if pattern.startswith("*") else base.glob(pattern):
                    if path.is_file():
                        try:
                            physical_bytes += path.stat().st_size; physical_files += 1
                        except OSError:
                            pass
        logical = int(row.get("logical_bytes") or 0)
        return {
            "contract_version": RESULT_DATA_GATEWAY_CONTRACT_VERSION,
            "schema_version": RESULT_DATA_SCHEMA_VERSION,
            "backend": "content_addressed_chunk_filesystem",
            "chunk_format": CHUNKPACK_FORMAT,
            "inline_max_bytes": self.inline_max_bytes,
            "chunk_size_items": self.chunk_size_items,
            "chunk_target_bytes": self.chunk_target_bytes,
            "max_window_items": MAX_WINDOW_ITEMS,
            "gc_grace_seconds": self.gc_grace_seconds,
            "object_count": int(row.get("object_count") or 0),
            "chunked_object_count": int(row.get("chunked_object_count") or 0),
            "monolithic_object_count": int(row.get("monolithic_object_count") or 0),
            "reference_count": int(refs.get("ref_count") or 0),
            "orphan_count": int(orphan.get("orphan_count") or 0),
            "chunk_record_count": int(chunks.get("chunk_record_count") or 0),
            "unique_chunk_count": int(chunks.get("unique_chunk_count") or 0),
            "logical_bytes": logical,
            "registered_stored_bytes": int(row.get("registered_stored_bytes") or 0),
            "physical_file_count": physical_files,
            "physical_stored_bytes": physical_bytes,
            "compression_ratio": (round(physical_bytes / logical, 6) if logical else None),
            "random_access_native": True,
            "legacy_monolithic_read_compatible": True,
        }

    def garbage_collect(self, *, dry_run: bool = True) -> dict[str, Any]:
        rows = self.db.query_all("""SELECT o.* FROM result_data_objects o
            WHERE NOT EXISTS (SELECT 1 FROM result_bundle_data_refs r WHERE r.content_hash=o.content_hash)
            ORDER BY o.created_at,o.content_hash""")
        now = datetime.now(timezone.utc)
        eligible_rows = [row for row in rows if _utc_age_seconds(row.get("created_at"), now) >= self.gc_grace_seconds]
        deferred_rows = len(rows) - len(eligible_rows)
        eligible_hashes = {str(row.get("content_hash") or "") for row in eligible_rows}

        all_chunk_rows = self.db.query_all(
            "SELECT parent_content_hash,chunk_hash,storage_key,stored_bytes FROM result_data_chunks"
        )
        retained_chunk_hashes = {
            str(row.get("chunk_hash") or "") for row in all_chunk_rows
            if str(row.get("parent_content_hash") or "") not in eligible_hashes
        }
        candidate_by_hash: dict[str, dict[str, Any]] = {}
        for row in all_chunk_rows:
            if str(row.get("parent_content_hash") or "") in eligible_hashes:
                candidate_by_hash.setdefault(str(row.get("chunk_hash") or ""), row)
        reclaimable_chunks = [
            row for digest, row in candidate_by_hash.items() if digest and digest not in retained_chunk_hashes
        ]

        registered_object_keys = {str(row.get("storage_key") or "") for row in self.db.query_all("SELECT storage_key FROM result_data_objects")}
        registered_chunk_keys = {str(row.get("storage_key") or "") for row in self.db.query_all("SELECT DISTINCT storage_key FROM result_data_chunks")}
        unregistered_files: list[Path] = []
        deferred_unregistered = 0
        for base, registered, patterns in (
            (self.objects_dir, registered_object_keys, ("*.json.gz", "*.chunkpack.json")),
            (self.chunks_dir, registered_chunk_keys, ("*.json.gz",)),
        ):
            for pattern in patterns:
                for path in base.glob(f"*/{pattern}"):
                    key = str(path.relative_to(self.root)).replace("\\", "/")
                    if key in registered:
                        continue
                    try:
                        age = max(0.0, now.timestamp() - path.stat().st_mtime)
                    except OSError:
                        continue
                    if age < self.gc_grace_seconds:
                        deferred_unregistered += 1
                    else:
                        unregistered_files.append(path)

        reclaimable = sum(self._path_for_hash(str(row["content_hash"]), row).stat().st_size for row in eligible_rows if self._path_for_hash(str(row["content_hash"]), row).exists())
        reclaimable += sum(int(row.get("stored_bytes") or 0) for row in reclaimable_chunks)
        reclaimable += sum(path.stat().st_size for path in unregistered_files if path.exists())
        removed: list[str] = []
        removed_chunks: list[str] = []
        removed_unregistered: list[str] = []
        if not dry_run:
            # Delete DB parent rows first so chunk reference decisions are authoritative.
            for row in eligible_rows:
                digest = str(row.get("content_hash") or "")
                try:
                    path = self._path_for_hash(digest, row)
                    path.unlink(missing_ok=True)
                except (OSError, RuntimeError, ValueError):
                    continue
                self.db.execute("DELETE FROM result_data_objects WHERE content_hash=?", (digest,))
                removed.append(digest)
            for row in reclaimable_chunks:
                digest = str(row.get("chunk_hash") or "")
                still_used = self.db.query_one("SELECT 1 AS yes FROM result_data_chunks WHERE chunk_hash=? LIMIT 1", (digest,))
                if still_used:
                    continue
                try:
                    self._chunk_path(digest, str(row.get("storage_key") or "")).unlink(missing_ok=True)
                    removed_chunks.append(digest)
                except (OSError, RuntimeError, ValueError):
                    continue
            for path in unregistered_files:
                try:
                    key = str(path.relative_to(self.root)).replace("\\", "/")
                    path.unlink(missing_ok=True)
                    removed_unregistered.append(key)
                except OSError:
                    continue
        return {
            "dry_run": bool(dry_run),
            "candidate_count": len(eligible_rows) + len(reclaimable_chunks) + len(unregistered_files),
            "registered_orphan_count": len(eligible_rows),
            "orphan_chunk_file_count": len(reclaimable_chunks),
            "unregistered_file_count": len(unregistered_files),
            "deferred_recent_count": deferred_rows + deferred_unregistered,
            "grace_seconds": self.gc_grace_seconds,
            "removed_count": len(removed) + len(removed_chunks) + len(removed_unregistered),
            "reclaimable_stored_bytes": reclaimable,
            "removed_hashes": removed,
            "removed_chunk_hashes": removed_chunks,
            "removed_unregistered_keys": removed_unregistered,
        }
