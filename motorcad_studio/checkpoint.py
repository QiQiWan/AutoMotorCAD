from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def checkpoint_signature(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


class CheckpointStore:
    def __init__(self, work_dir: Path, signature: str):
        self.work_dir = Path(work_dir)
        self.signature = signature
        self.path = self.work_dir / "checkpoint_manifest.json"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 2, "signature": self.signature, "stages": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": 2, "signature": self.signature, "stages": {}}
        if payload.get("signature") != self.signature:
            return {"schema_version": 2, "signature": self.signature, "stages": {}}
        payload.setdefault("schema_version", 1)
        payload.setdefault("stages", {})
        return payload

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(temporary, self.path)

    def record(self, stage: str, *, artifacts: list[str] | None = None, payload_path: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        state = self._load()
        state["schema_version"] = 2
        state["signature"] = self.signature
        artifact_paths = artifacts or []
        state.setdefault("stages", {})[stage] = {
            "status": "SUCCEEDED",
            "artifacts": artifact_paths,
            "artifact_sha256": {path: _file_sha256(Path(path)) for path in artifact_paths},
            "payload_path": payload_path,
            "payload_sha256": _file_sha256(Path(payload_path)) if payload_path else None,
            "metadata": metadata or {},
        }
        self._write_atomic(state)

    def stage(self, stage: str) -> dict[str, Any] | None:
        item = self._load().get("stages", {}).get(stage)
        if not item or item.get("status") != "SUCCEEDED":
            return None
        for artifact in item.get("artifacts", []):
            if artifact and not Path(artifact).exists():
                return None
            expected = (item.get("artifact_sha256") or {}).get(artifact)
            if expected and _file_sha256(Path(artifact)) != expected:
                return None
        payload_path = item.get("payload_path")
        if payload_path and not Path(payload_path).exists():
            return None
        if payload_path and item.get("payload_sha256") and _file_sha256(Path(payload_path)) != item.get("payload_sha256"):
            return None
        return item

    def latest(self) -> str | None:
        stages = self._load().get("stages", {})
        return next((stage for stage in reversed(list(stages)) if self.stage(stage) is not None), None)
