"""DesignTransactionV1 aggregate and deterministic patch semantics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...shared import DesignTransactionStatus, stable_hash


def merge_mapping(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge JSON-object patches without mutating either input."""
    merged = dict(base or {})
    for key, value in dict(patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_mapping(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True, slots=True)
class DesignTransaction:
    transaction_id: str
    project_id: str
    solution_id: str
    base_revision_id: str
    base_revision_hash: str
    status: DesignTransactionStatus
    parameter_patch: dict[str, Any] = field(default_factory=dict)
    material_patch: dict[str, Any] = field(default_factory=dict)
    explicit_parameter_ids: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    validation: dict[str, Any] = field(default_factory=dict)
    intent_hash: str = ""
    commit_key: str = ""
    committed_revision_id: str | None = None
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    committed_at: str | None = None
    aborted_at: str | None = None

    def editable(self) -> bool:
        return self.status in {
            DesignTransactionStatus.OPEN,
            DesignTransactionStatus.VALIDATED,
        }

    def patch_hash(self) -> str:
        return stable_hash(
            {
                "base_revision_id": self.base_revision_id,
                "base_revision_hash": self.base_revision_hash,
                "parameter_patch": self.parameter_patch,
                "material_patch": self.material_patch,
                "explicit_parameter_ids": list(self.explicit_parameter_ids),
                "notes": self.notes,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "DesignTransactionV1",
            "transaction_id": self.transaction_id,
            "project_id": self.project_id,
            "solution_id": self.solution_id,
            "base_revision_id": self.base_revision_id,
            "base_revision_hash": self.base_revision_hash,
            "status": self.status.value,
            "parameter_patch": dict(self.parameter_patch),
            "material_patch": dict(self.material_patch),
            "explicit_parameter_ids": list(self.explicit_parameter_ids),
            "notes": self.notes,
            "validation": dict(self.validation),
            "intent_hash": self.intent_hash,
            "patch_hash": self.patch_hash(),
            "commit_key": self.commit_key,
            "committed_revision_id": self.committed_revision_id,
            "version": self.version,
            "editable": self.editable(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "committed_at": self.committed_at,
            "aborted_at": self.aborted_at,
        }


__all__ = ["DesignTransaction", "merge_mapping"]
