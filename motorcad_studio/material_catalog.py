from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class MaterialCatalog:
    def __init__(self, path: Path):
        self.path = Path(path)
        with self.path.open("r", encoding="utf-8") as handle:
            self.payload = yaml.safe_load(handle) or {}

    def catalog(self, language: str | None = None) -> dict[str, Any]:
        data = deepcopy(self.payload)
        lang = "en" if str(language or "zh").lower().startswith("en") else "zh"
        for row in data.get("materials", []):
            row["label"] = row.get(f"label_{lang}") or row.get("label_zh") or row.get("label_en") or row.get("id")
        for row in data.get("component_slots", []):
            row["label"] = row.get(f"label_{lang}") or row.get("label_zh") or row.get("label_en") or row.get("id")
        for row in data.get("fluid_slots", []):
            row["label"] = row.get(f"label_{lang}") or row.get("label_zh") or row.get("label_en") or row.get("id")
        return data

    def grouped(self, language: str | None = None) -> dict[str, Any]:
        payload = self.catalog(language)
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in payload.get("materials", []):
            groups.setdefault(str(row.get("category") or "other"), []).append(row)
        return {**payload, "groups": groups}
