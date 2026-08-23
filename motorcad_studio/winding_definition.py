from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any


_ALIASES = {
    "coil": ("coil", "coilnumber", "coilno", "coilid"),
    "phase": ("phase", "phasename", "phaseid"),
    "go_slot": ("goslot", "startslot", "fromslot", "slotin", "slot1"),
    "return_slot": ("returnslot", "endslot", "toslot", "slotout", "slot2"),
    "turns": ("turns", "turnspercoil", "turnnumber"),
    "parallel_path": ("parallelpath", "path", "circuit"),
    "direction": ("direction", "polarity", "sense"),
}


def _norm(value: Any) -> str:
    return "".join(character.lower() for character in str(value or "") if character.isalnum())


def _column_map(headers: list[str]) -> dict[str, str]:
    normalized = {_norm(header): header for header in headers}
    result: dict[str, str] = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                result[field] = normalized[alias]
                break
    return result


def _scalar(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
        return int(number) if number.is_integer() else number
    except ValueError:
        return text


def parse_winding_pattern_text(text: str) -> dict[str, Any]:
    """Parse a saved Motor-CAD winding pattern without inventing coil data.

    Motor-CAD releases and templates may emit different text layouts.  A pattern
    is marked structured only when both slot endpoints can be read.  Unrecognized
    exports remain valid native evidence and retain their source statistics.
    """
    source = str(text or "")
    nonempty = [line for line in source.splitlines() if line.strip()]
    parsed: list[dict[str, Any]] = []
    parse_mode = "unrecognized"
    headers: list[str] = []

    if nonempty:
        sample = "\n".join(nonempty[:20])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            reader = csv.DictReader(io.StringIO(source), dialect=dialect)
            headers = [str(item or "").strip() for item in (reader.fieldnames or [])]
            mapping = _column_map(headers)
            if {"go_slot", "return_slot"}.issubset(mapping):
                for index, row in enumerate(reader, start=1):
                    coil = {field: _scalar(row.get(column)) for field, column in mapping.items()}
                    coil.setdefault("coil", index)
                    if coil.get("go_slot") is not None and coil.get("return_slot") is not None:
                        parsed.append(coil)
                if parsed:
                    parse_mode = "delimited_header"
        except csv.Error:
            pass

    if not parsed:
        label_pattern = re.compile(
            r"(?:coil\s*[:=#]?\s*(?P<coil>\d+).*?)?"
            r"(?:phase\s*[:=#]?\s*(?P<phase>[A-Za-z0-9+-]+).*?)?"
            r"(?:go|start|from)\s*slot\s*[:=#]?\s*(?P<go>\d+).*?"
            r"(?:return|end|to)\s*slot\s*[:=#]?\s*(?P<ret>\d+)"
            r"(?:.*?turns?\s*[:=#]?\s*(?P<turns>[0-9.]+))?",
            re.IGNORECASE,
        )
        for index, line in enumerate(nonempty, start=1):
            match = label_pattern.search(line)
            if not match:
                continue
            parsed.append({
                "coil": _scalar(match.group("coil")) or index,
                "phase": _scalar(match.group("phase")),
                "go_slot": _scalar(match.group("go")),
                "return_slot": _scalar(match.group("ret")),
                "turns": _scalar(match.group("turns")),
            })
        if parsed:
            parse_mode = "labeled_lines"

    phases = sorted({str(row["phase"]) for row in parsed if row.get("phase") not in (None, "")})
    used_slots = sorted({int(value) for row in parsed for value in (row.get("go_slot"), row.get("return_slot")) if isinstance(value, int)})
    fields = sorted({key for row in parsed for key, value in row.items() if value not in (None, "")})
    return {
        "schema_version": 1,
        "authority": "motorcad_saved_winding_pattern",
        "structured": bool(parsed),
        "parse_mode": parse_mode,
        "source_line_count": len(nonempty),
        "headers": headers,
        "fields": fields,
        "coil_count": len(parsed),
        "phase_count": len(phases) or None,
        "phases": phases,
        "used_slots": used_slots,
        "coils": parsed,
    }


def build_winding_definition_evidence(
    pattern_path: Path,
    template: dict[str, Any],
    parameters: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    text = pattern_path.read_text(encoding="utf-8-sig", errors="replace")
    parsed = parse_winding_pattern_text(text)
    digest = hashlib.sha256(pattern_path.read_bytes()).hexdigest()
    native_validation = dict(validation.get("winding_validation") or {})
    editable = {
        key: parameters.get(key)
        for key in ("slot_count", "pole_count", "turns_per_coil", "parallel_paths", "slot_fill_factor")
        if key in parameters
    }
    native_fields = {
        "coil_table": parsed.get("coils") if parsed.get("structured") else None,
        "phase_count": parsed.get("phase_count"),
        "winding_factor": (native_validation.get("details") or {}).get("fundamental_winding_factor"),
        "native_slot_fill": (native_validation.get("details") or {}).get("slot_fill"),
    }
    verified = sorted(key for key, value in native_fields.items() if value not in (None, [], ""))
    return {
        **parsed,
        "source_file": pattern_path.name,
        "source_sha256": digest,
        "template_id": template.get("id"),
        "editable_revision_fields": editable,
        "native_fields": native_fields,
        "verified_native_fields": verified,
        "definition_status": "STRUCTURED_NATIVE" if parsed.get("structured") else "NATIVE_RAW_ONLY",
        "native_validation": native_validation,
        "boundary": "Only parsed values and Motor-CAD validation messages are native claims.",
    }


def write_winding_definition(
    pattern_path: Path,
    output_path: Path,
    template: dict[str, Any],
    parameters: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    payload = build_winding_definition_evidence(pattern_path, template, parameters, validation)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload
