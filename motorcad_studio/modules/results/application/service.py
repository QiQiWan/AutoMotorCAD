"""Results application facade over immutable bundles and heavy-data descriptors."""
from __future__ import annotations

import inspect
from typing import Any

from ...shared.transfer_budget import TransferBudget
from ..ports.operations import ResultsOperationPort


HEAVY_RESULT_OPERATIONS = frozenset({
    "case_result_bundle",
    "result_bundle_aggregate_query",
    "result_set_aggregate_compare",
    "task_result_set_aggregate",
    "result_bundle_aggregate",
    "result_bundle_item",
    "result_bundle_item_data",
    "result_bundle_item_data_manifest",
    "result_bundle_item_data_chunk",
    "result_bundle_item_integrity",
    "result_bundle_by_id",
})


class ResultsApplicationService:
    CONTRACT_VERSION = "1"

    def __init__(self, backend: ResultsOperationPort, *, transfer_budget: TransferBudget) -> None:
        self.backend = backend
        self.transfer_budget = transfer_budget

    def endpoint(self, name: str):
        return self.backend.operation(name)

    def dispatch(self, name: str, *args: Any, **kwargs: Any) -> Any:
        target = self.backend.operation(name)
        if name in HEAVY_RESULT_OPERATIONS:
            with self.transfer_budget.lease(name):
                return self.transfer_budget.enforce_response_size(
                    name, target(*args, **kwargs)
                )
        return target(*args, **kwargs)

    async def dispatch_async(self, name: str, *args: Any, **kwargs: Any) -> Any:
        target = self.backend.operation(name)
        if name in HEAVY_RESULT_OPERATIONS:
            with self.transfer_budget.lease(name):
                result = target(*args, **kwargs)
                resolved = await result if inspect.isawaitable(result) else result
                return self.transfer_budget.enforce_response_size(name, resolved)
        result = target(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    def summary(self) -> dict[str, Any]:
        return {
            "authority": "ResultsApplicationModuleV1",
            "contract_version": self.CONTRACT_VERSION,
            "backend": self.backend.module_snapshot(),
            "transfer_budget": self.transfer_budget.snapshot(),
        }


__all__ = ["HEAVY_RESULT_OPERATIONS", "ResultsApplicationService"]
