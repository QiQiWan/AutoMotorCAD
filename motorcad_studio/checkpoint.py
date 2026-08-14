from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def checkpoint_signature(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class CheckpointStore:
    def __init__(self, work_dir: Path, signature: str):
        self.work_dir = Path(work_dir)
        self.signature = signature
        self.path = self.work_dir / "checkpoint_manifest.json"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"signature": self.signature, "stages": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"signature": self.signature, "stages": {}}
        if payload.get("signature") != self.signature:
            return {"signature": self.signature, "stages": {}}
        payload.setdefault("stages", {})
        return payload

    def record(self, stage: str, *, artifacts: list[str] | None = None, payload_path: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        state = self._load()
        state["signature"] = self.signature
        state.setdefault("stages", {})[stage] = {
            "status": "SUCCEEDED",
            "artifacts": artifacts or [],
            "payload_path": payload_path,
            "metadata": metadata or {},
        }
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def stage(self, stage: str) -> dict[str, Any] | None:
        item = self._load().get("stages", {}).get(stage)
        if not item or item.get("status") != "SUCCEEDED":
            return None
        for artifact in item.get("artifacts", []):
            if artifact and not Path(artifact).exists():
                return None
        payload_path = item.get("payload_path")
        if payload_path and not Path(payload_path).exists():
            return None
        return item

    def latest(self) -> str | None:
        stages = self._load().get("stages", {})
        return list(stages)[-1] if stages else None
