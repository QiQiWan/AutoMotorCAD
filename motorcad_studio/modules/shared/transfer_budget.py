"""Process-local admission and payload budgets for heavy result transfers.

The budget protects request-time decoding and response assembly.  It does not
construct an executor and therefore does not compete with the TaskManager or the
Motor-CAD native worker pool.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


class TransferBudgetExceeded(RuntimeError):
    """Raised when a heavy-data request cannot enter the bounded transfer pool."""

    def __init__(self, operation: str, *, retry_after_s: float) -> None:
        self.operation = str(operation)
        self.retry_after_s = max(0.1, float(retry_after_s))
        super().__init__(
            f"TRANSFER_BUDGET_EXHAUSTED[{self.operation}]: retry after {self.retry_after_s:.2f}s"
        )


class TransferPayloadTooLarge(RuntimeError):
    """Raised when a materialized response exceeds the configured byte ceiling."""

    def __init__(
        self,
        operation: str,
        *,
        size_bytes: int,
        max_response_bytes: int,
    ) -> None:
        self.operation = str(operation)
        self.size_bytes = max(0, int(size_bytes))
        self.max_response_bytes = max(1, int(max_response_bytes))
        super().__init__(
            "TRANSFER_PAYLOAD_TOO_LARGE"
            f"[{self.operation}]: {self.size_bytes} bytes exceeds "
            f"{self.max_response_bytes} bytes"
        )


@dataclass(frozen=True, slots=True)
class TransferLease:
    operation: str
    admitted_at: float


class TransferBudget:
    """Bound concurrent heavy reads and materialized response size.

    File and streaming responses are not materialized for measurement here.  Their
    byte-range or chunk contracts remain responsible for limiting one transfer.
    JSONResponse bodies and Python/Pydantic payloads are measured before they leave
    the application service.
    """

    AUTHORITY = "HeavyDataTransferBudgetV2"

    def __init__(
        self,
        *,
        name: str,
        max_concurrent: int | None = None,
        acquire_timeout_s: float | None = None,
        max_response_bytes: int | None = None,
    ) -> None:
        prefix = str(name).upper().replace("-", "_").replace(".", "_")
        self.name = str(name)
        self.max_concurrent = max(
            1,
            int(
                max_concurrent
                or os.getenv(f"MOTORCAD_STUDIO_{prefix}_MAX_CONCURRENT")
                or os.getenv("MOTORCAD_STUDIO_DATA_TRANSFER_MAX_CONCURRENT")
                or 4
            ),
        )
        self.acquire_timeout_s = max(
            0.05,
            float(
                acquire_timeout_s
                or os.getenv(f"MOTORCAD_STUDIO_{prefix}_ACQUIRE_TIMEOUT_S")
                or os.getenv("MOTORCAD_STUDIO_DATA_TRANSFER_ACQUIRE_TIMEOUT_S")
                or 2.0
            ),
        )
        self.max_response_bytes = max(
            1024 * 1024,
            int(
                max_response_bytes
                or os.getenv(f"MOTORCAD_STUDIO_{prefix}_MAX_RESPONSE_BYTES")
                or os.getenv("MOTORCAD_STUDIO_DATA_TRANSFER_MAX_RESPONSE_BYTES")
                or 64 * 1024 * 1024
            ),
        )
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent)
        self._lock = threading.RLock()
        self._active = 0
        self._peak_active = 0
        self._admitted = 0
        self._rejected = 0
        self._completed = 0
        self._failed = 0
        self._oversized = 0
        self._measured_responses = 0
        self._unmeasured_streams = 0
        self._response_bytes = 0
        self._largest_response_bytes = 0
        self._total_duration_s = 0.0
        self._by_operation: dict[str, dict[str, int | float]] = {}

    @contextmanager
    def lease(self, operation: str) -> Iterator[TransferLease]:
        operation = str(operation)
        admitted = self._semaphore.acquire(timeout=self.acquire_timeout_s)
        if not admitted:
            with self._lock:
                self._rejected += 1
                row = self._by_operation.setdefault(operation, {})
                row["rejected"] = int(row.get("rejected") or 0) + 1
            raise TransferBudgetExceeded(
                operation,
                retry_after_s=max(0.25, self.acquire_timeout_s),
            )
        started = time.monotonic()
        with self._lock:
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            self._admitted += 1
            row = self._by_operation.setdefault(operation, {})
            row["admitted"] = int(row.get("admitted") or 0) + 1
            row["active"] = int(row.get("active") or 0) + 1
        try:
            yield TransferLease(operation=operation, admitted_at=started)
        except BaseException:
            with self._lock:
                self._failed += 1
                row = self._by_operation.setdefault(operation, {})
                row["failed"] = int(row.get("failed") or 0) + 1
            raise
        else:
            with self._lock:
                self._completed += 1
                row = self._by_operation.setdefault(operation, {})
                row["completed"] = int(row.get("completed") or 0) + 1
        finally:
            elapsed = max(0.0, time.monotonic() - started)
            with self._lock:
                self._active = max(0, self._active - 1)
                self._total_duration_s += elapsed
                row = self._by_operation.setdefault(operation, {})
                row["active"] = max(0, int(row.get("active") or 0) - 1)
                row["duration_s"] = round(
                    float(row.get("duration_s") or 0.0) + elapsed,
                    6,
                )
            self._semaphore.release()

    @staticmethod
    def _known_response_size(value: Any) -> int | None:
        """Return an exact/serialized size when the response is materialized.

        StreamingResponse/FileResponse are intentionally reported as ``None``.  A
        Response with an in-memory body is measured exactly.  Native Python and
        Pydantic payloads use the same compact UTF-8 JSON representation used for
        content-addressed engineering identities.
        """

        if value is None:
            return 0
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value)
        if isinstance(value, str):
            return len(value.encode("utf-8"))

        # Starlette FileResponse and StreamingResponse expose a path or iterator,
        # while an in-memory Response exposes ``body``.
        body = getattr(value, "body", None)
        if isinstance(body, (bytes, bytearray, memoryview)):
            return len(body)
        if hasattr(value, "body_iterator") or hasattr(value, "path"):
            return None

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            value = model_dump(mode="json")
        try:
            return len(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
        except (TypeError, ValueError, RecursionError):
            return None

    def enforce_response_size(self, operation: str, value: Any) -> Any:
        """Measure one materialized payload and reject oversized responses."""

        operation = str(operation)
        size_bytes = self._known_response_size(value)
        with self._lock:
            row = self._by_operation.setdefault(operation, {})
            if size_bytes is None:
                self._unmeasured_streams += 1
                row["unmeasured_streams"] = int(row.get("unmeasured_streams") or 0) + 1
                return value
            self._measured_responses += 1
            self._response_bytes += size_bytes
            self._largest_response_bytes = max(self._largest_response_bytes, size_bytes)
            row["measured_responses"] = int(row.get("measured_responses") or 0) + 1
            row["response_bytes"] = int(row.get("response_bytes") or 0) + size_bytes
            row["largest_response_bytes"] = max(
                int(row.get("largest_response_bytes") or 0),
                size_bytes,
            )
            if size_bytes > self.max_response_bytes:
                self._oversized += 1
                row["oversized"] = int(row.get("oversized") or 0) + 1
                raise TransferPayloadTooLarge(
                    operation,
                    size_bytes=size_bytes,
                    max_response_bytes=self.max_response_bytes,
                )
        return value

    def snapshot(self) -> dict:
        with self._lock:
            average_duration = (
                self._total_duration_s / self._completed if self._completed else 0.0
            )
            average_bytes = (
                self._response_bytes / self._measured_responses
                if self._measured_responses
                else 0.0
            )
            return {
                "authority": self.AUTHORITY,
                "name": self.name,
                "max_concurrent": self.max_concurrent,
                "acquire_timeout_s": self.acquire_timeout_s,
                "max_response_bytes": self.max_response_bytes,
                "active": self._active,
                "peak_active": self._peak_active,
                "admitted": self._admitted,
                "rejected": self._rejected,
                "completed": self._completed,
                "failed": self._failed,
                "oversized": self._oversized,
                "measured_responses": self._measured_responses,
                "unmeasured_streams": self._unmeasured_streams,
                "response_bytes": self._response_bytes,
                "largest_response_bytes": self._largest_response_bytes,
                "average_response_bytes": round(average_bytes, 3),
                "average_duration_s": round(average_duration, 6),
                "operations": {
                    key: dict(value)
                    for key, value in sorted(self._by_operation.items())
                },
            }


__all__ = [
    "TransferBudget",
    "TransferBudgetExceeded",
    "TransferLease",
    "TransferPayloadTooLarge",
]
