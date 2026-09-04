"""FieldData application facade with bounded native-evidence decoding."""
from __future__ import annotations

import inspect
from typing import Any

from ...shared.transfer_budget import TransferBudget
from ..ports.operations import FieldDataOperationPort


HEAVY_FIELD_OPERATIONS = frozenset({
    "case_fea_frame",
    "case_fea_mesh_manifest",
    "case_fea_mesh_chunk",
    "case_fea_frame_view",
    "case_fea_probe",
    "case_native_table_rows",
    "field_data_manifest",
    "field_data_frame_lod",
    "field_data_integrity",
})


class FieldDataApplicationService:
    CONTRACT_VERSION = "1"

    def __init__(self, backend: FieldDataOperationPort, *, transfer_budget: TransferBudget) -> None:
        self.backend = backend
        self.transfer_budget = transfer_budget

    def endpoint(self, name: str):
        return self.backend.operation(name)

    def dispatch(self, name: str, *args: Any, **kwargs: Any) -> Any:
        target = self.backend.operation(name)
        if name in HEAVY_FIELD_OPERATIONS:
            with self.transfer_budget.lease(name):
                return self.transfer_budget.enforce_response_size(
                    name, target(*args, **kwargs)
                )
        return target(*args, **kwargs)

    async def dispatch_async(self, name: str, *args: Any, **kwargs: Any) -> Any:
        target = self.backend.operation(name)
        if name in HEAVY_FIELD_OPERATIONS:
            with self.transfer_budget.lease(name):
                result = target(*args, **kwargs)
                resolved = await result if inspect.isawaitable(result) else result
                return self.transfer_budget.enforce_response_size(name, resolved)
        result = target(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    def summary(self) -> dict[str, Any]:
        return {
            "authority": "FieldDataApplicationModuleV1",
            "contract_version": self.CONTRACT_VERSION,
            "backend": self.backend.module_snapshot(),
            "transfer_budget": self.transfer_budget.snapshot(),
        }


__all__ = ["FieldDataApplicationService", "HEAVY_FIELD_OPERATIONS"]
