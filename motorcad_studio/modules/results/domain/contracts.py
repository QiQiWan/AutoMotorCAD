"""Stable result-data descriptors used by API and frontend clients."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ResultDataDescriptorV1(BaseModel):
    authority: Literal["ResultDataDescriptorV1"] = "ResultDataDescriptorV1"
    result_bundle_id: str
    result_id: str
    result_type: str
    unit: str | None = None
    externalized: bool
    content_hash: str | None = None
    etag: str
    layout: str
    chunk_native: bool = False
    item_count: int | None = None
    chunk_count: int = 0
    max_window_items: int | None = None
    range_requests: bool = False
    manifest_url: str | None = None
    data_url: str
    integrity_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ResultDataDescriptorV1"]
