from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_AUTOMATION_NAME_ALIASES = {
    # Legacy V0.91.6/V0.91.7 browser i18n could translate fragments inside raw
    # Motor-CAD identifiers rendered in the advanced Solver JSON editor.  Keep a
    # bounded compatibility bridge for already-persisted revisions.  New UI code
    # marks raw-identifier surfaces as i18n-skip, so these aliases are migration
    # protection rather than an ongoing translation mechanism.
    "当前Definition": "CurrentDefinition",
    "Torque计算": "TorqueCalculation",
    "BackEMF计算": "BackEMFCalculation",
    "CoggingTorque计算": "CoggingTorqueCalculation",
}
_AUTOMATION_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_\[\]()./+%:-]*$")


def _known_static_automation_names() -> set[str]:
    """Load the shipped solver-control identifiers used for conservative repair.

    Repairs are accepted only when the reconstructed token is present in the
    maintained Motor-CAD control catalog.  This prevents arbitrary localized text
    from being silently converted into an Automation Parameter Name.
    """
    try:
        path = Path(__file__).resolve().parent / "config" / "solver_controls.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {
            str(row.get("automation_name") or "").strip()
            for rows in (payload.get("contexts") or {}).values()
            for row in (rows or [])
            if str(row.get("automation_name") or "").strip()
        }
    except Exception:
        return set()


_STATIC_AUTOMATION_NAMES = _known_static_automation_names()


def canonical_automation_name(value: Any) -> str:
    """Return the exact Motor-CAD Automation Parameter Name used at RPC time.

    A legacy mixed-language key is repaired only when it maps unambiguously to a
    shipped Motor-CAD identifier. Unknown/non-ASCII names still fail validation.
    """
    raw = str(value or "").strip()
    alias = _AUTOMATION_NAME_ALIASES.get(raw)
    if alias:
        return alias
    candidates: list[str] = []
    if raw.startswith("当前"):
        candidates.append("Current" + raw[len("当前"):])
    if raw.endswith("计算"):
        stem = raw[:-len("计算")]
        candidates.extend((stem + "Calculation", stem + "Calc"))
    for candidate in candidates:
        if candidate in _STATIC_AUTOMATION_NAMES:
            return candidate
    return raw


def valid_automation_name(value: Any) -> bool:
    """Reject localized/corrupt raw identifiers before a Motor-CAD worker starts."""
    name = canonical_automation_name(value)
    return bool(name and name.isascii() and _AUTOMATION_NAME_PATTERN.fullmatch(name))


_HEADER_ALIASES = {
    "automation_name": {"automation name", "automation_name", "parameter", "parameter name", "name", "variable", "variable name"},
    "value": {"value", "current value", "current_value", "default value"},
    "unit": {"unit", "units", "default unit", "default units"},
    "description": {"description", "desc", "parameter description"},
    "category": {"category", "module", "group"},
    "io": {"io", "direction", "input/output", "input output", "type"},
}


def _normalise_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower().replace("_", " "))


def _canonical_headers(headers: list[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for index, header in enumerate(headers):
        normal = _normalise_header(header)
        for canonical, aliases in _HEADER_ALIASES.items():
            if normal in aliases:
                result[index] = canonical
                break
    return result


def _infer_value_type(value: str) -> str:
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return "boolean"
    try:
        int(text)
        return "integer"
    except Exception:
        pass
    try:
        float(text)
        return "number"
    except Exception:
        return "string"


def _coerce_value(value: str) -> Any:
    text = value.strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    try:
        return int(text)
    except Exception:
        pass
    try:
        return float(text)
    except Exception:
        return text


@dataclass(frozen=True)
class AutomationRegistryKey:
    version: str
    machine_type: str
    context: str

    def safe_parts(self) -> tuple[str, str, str]:
        def clean(value: str) -> str:
            return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()) or "unknown"
        return clean(self.version), clean(self.machine_type), clean(self.context)


class AutomationParameterParser:
    """Parse the text file saved from Motor-CAD > Help > Automation Parameter Names.

    Motor-CAD versions may vary the exact text layout. The parser therefore accepts
    tab/comma/semicolon-delimited tables and a conservative whitespace fallback.
    The original row is retained for traceability.
    """

    @classmethod
    def parse(cls, text: str) -> list[dict[str, Any]]:
        cleaned = text.replace("\ufeff", "").strip()
        if not cleaned:
            return []
        rows = cls._parse_delimited(cleaned)
        if rows:
            return rows
        return cls._parse_whitespace(cleaned)

    @staticmethod
    def _parse_delimited(text: str) -> list[dict[str, Any]]:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        delimiter = None
        for candidate in ("\t", ",", ";", "|"):
            if candidate in lines[0]:
                delimiter = candidate
                break
        if delimiter is None:
            return []
        reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        table = list(reader)
        if not table:
            return []
        header_map = _canonical_headers(table[0])
        start_index = 1 if "automation_name" in header_map.values() else 0
        if start_index == 0:
            # Common exported layout: name, value, unit, description. Use positional
            # interpretation only when no recognizable header exists.
            header_map = {0: "automation_name", 1: "value", 2: "unit", 3: "description"}
        output: list[dict[str, Any]] = []
        for raw_row in table[start_index:]:
            if not raw_row or not raw_row[0].strip():
                continue
            item: dict[str, Any] = {"raw": raw_row}
            for index, canonical in header_map.items():
                if index < len(raw_row):
                    item[canonical] = raw_row[index].strip()
            raw_name = str(item.get("automation_name", "")).strip()
            name = canonical_automation_name(raw_name)
            if not name or name.lower().startswith("automation parameter"):
                continue
            raw_value = str(item.get("value", ""))
            item["automation_name"] = name
            if raw_name != name:
                item["raw_automation_name"] = raw_name
                item["name_normalized"] = True
            item["valid_automation_name"] = valid_automation_name(name)
            item["value_type"] = _infer_value_type(raw_value) if raw_value else "unknown"
            item["current_value"] = _coerce_value(raw_value) if raw_value else None
            item["unit"] = str(item.get("unit", "")).strip()
            item["description"] = str(item.get("description", "")).strip()
            item["category"] = str(item.get("category", "")).strip()
            item["io"] = str(item.get("io", "")).strip()
            output.append(item)
        return output

    @staticmethod
    def _parse_whitespace(text: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = re.split(r"\s{2,}", stripped)
            if len(parts) < 2:
                continue
            raw_name = parts[0].strip()
            name = canonical_automation_name(raw_name)
            if " " in name and not re.match(r"^[A-Za-z0-9_\[\]()./+%-]+$", name):
                continue
            value = parts[1].strip() if len(parts) > 1 else ""
            unit = parts[2].strip() if len(parts) > 2 else ""
            description = " ".join(parts[3:]).strip() if len(parts) > 3 else ""
            output.append({
                "automation_name": name,
                "raw_automation_name": raw_name if raw_name != name else None,
                "name_normalized": raw_name != name,
                "valid_automation_name": valid_automation_name(name),
                "current_value": _coerce_value(value) if value else None,
                "value_type": _infer_value_type(value) if value else "unknown",
                "unit": unit,
                "description": description,
                "category": "",
                "io": "",
                "raw": [stripped],
            })
        return output


class AutomationRegistryStore:
    def __init__(self, runtime_dir: Path, metadata_path: Path | None = None):
        self.root = runtime_dir / "automation_registry"
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata: dict[str, Any] = {}
        if metadata_path and Path(metadata_path).exists():
            try:
                payload = yaml.safe_load(Path(metadata_path).read_text(encoding="utf-8")) or {}
                self.metadata = payload.get("parameters", {}) if isinstance(payload, dict) else {}
            except Exception:
                self.metadata = {}

    def _enrich_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched = []
        for entry in entries:
            row = dict(entry)
            meta = self.metadata.get(str(entry.get("automation_name") or ""), {})
            row["metadata"] = dict(meta) if isinstance(meta, dict) else {}
            row["reviewed"] = bool(row["metadata"].get("reviewed", False))
            enriched.append(row)
        return enriched

    def _path(self, key: AutomationRegistryKey) -> Path:
        version, machine, context = key.safe_parts()
        return self.root / version / machine / f"{context}.json"

    def import_text(self, key: AutomationRegistryKey, text: str, source_name: str = "") -> dict[str, Any]:
        entries = AutomationParameterParser.parse(text)
        if not entries:
            raise ValueError("未从文本中解析到Automation Parameter Names条目")
        invalid = [str(row.get("automation_name") or "") for row in entries if not valid_automation_name(row.get("automation_name"))]
        if invalid:
            raise ValueError(
                "Automation Parameter Names包含非Motor-CAD原生标识符: "
                + ", ".join(invalid[:12])
                + "。请从目标Motor-CAD版本重新导出，不要翻译参数名。"
            )
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": key.version,
            "machine_type": key.machine_type,
            "context": key.context,
            "source_name": source_name,
            "count": len(entries),
            "entries": self._enrich_entries(entries),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {**payload, "path": str(path)}

    def get(self, key: AutomationRegistryKey) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["entries"] = self._enrich_entries(payload.get("entries", []))
        payload["reviewed_count"] = sum(1 for row in payload["entries"] if row.get("reviewed"))
        return payload

    def list_sets(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.root.glob("*/*/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append({
                "version": payload.get("version"),
                "machine_type": payload.get("machine_type"),
                "context": payload.get("context"),
                "count": payload.get("count", len(payload.get("entries", []))),
                "source_name": payload.get("source_name", ""),
                "path": str(path),
            })
        rows.sort(key=lambda row: (row.get("version") or "", row.get("machine_type") or "", row.get("context") or ""))
        return rows

    def coverage(self, version: str | None = None) -> dict[str, Any]:
        sets = [row for row in self.list_sets() if version is None or row.get("version") == version]
        return {
            "set_count": len(sets),
            "parameter_rows": sum(int(row.get("count") or 0) for row in sets),
            "sets": sets,
        }
