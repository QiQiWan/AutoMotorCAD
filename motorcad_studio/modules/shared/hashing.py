"""Canonical hashing helpers shared by bounded contexts."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def weak_etag(payload: Any) -> str:
    return f'W/"{stable_hash(payload)[:32]}"'


__all__ = ["stable_hash", "weak_etag"]
