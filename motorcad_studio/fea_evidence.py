from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NativeFEAExportConfig:
    enabled: bool = True
    outputs: str = "RegCode,X,Y,B,Pt"
    regions: str = ""
    max_steps: int = 36
    max_points_per_frame: int = 6000
    separator: str = ","

    @classmethod
    def from_solver_settings(cls, solver_settings: dict[str, Any] | None) -> "NativeFEAExportConfig":
        root = solver_settings or {}
        raw = root.get("native_fea") if isinstance(root, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            outputs=str(raw.get("outputs") or "RegCode,X,Y,B,Pt"),
            regions=str(raw.get("regions") or ""),
            max_steps=max(1, min(240, int(raw.get("max_steps") or 36))),
            max_points_per_frame=max(250, min(50000, int(raw.get("max_points_per_frame") or 6000))),
            separator=str(raw.get("separator") or ",")[:1] or ",",
        )


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _norm(name: str) -> str:
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())


def _pick(headers: list[str], candidates: tuple[str, ...], *, fuzzy: bool = True) -> str | None:
    lookup = {_norm(header): header for header in headers}
    for candidate in candidates:
        if _norm(candidate) in lookup:
            return lookup[_norm(candidate)]
    if fuzzy:
        for header in headers:
            token = _norm(header)
            if any(_norm(candidate) in token for candidate in candidates):
                return header
    return None


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _scalar_id(value: Any) -> int | str | None:
    number = _to_float(value)
    if number is not None:
        return int(number) if number.is_integer() else str(number)
    text = str(value or "").strip()
    return text or None


def _reservoir_stride(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    step = len(rows) / float(limit)
    return [rows[min(len(rows) - 1, int(i * step))] for i in range(limit)]


def _parse_motorcad_table_export(text: str, requested_outputs: str | None) -> tuple[list[str], list[dict[str, Any]]] | None:
    """Parse the native Motor-CAD table format emitted by ``save_fea_data``.

    The official PyMotorCAD stress post-processing example documents a file that
    starts with ``<table> <count> ElementsTable`` followed by four descriptive
    lines and element rows.  Each element row starts with TriIndex/Node1/Node2/
    Node3, followed by the outputs requested from ``save_fea_data``.  We detect
    that structure instead of assuming a conventional CSV header.
    """
    lines = text.splitlines()
    table_pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+ElementsTable\s*$", re.IGNORECASE)
    outputs = [token.strip() for token in str(requested_outputs or "").split(",") if token.strip()]
    if not outputs:
        return None
    headers = ["TriIndex", "Node1", "Node2", "Node3", *outputs, "Step"]
    rows: list[dict[str, Any]] = []
    block_index = 0
    for index, line in enumerate(lines):
        match = table_pattern.match(line)
        if not match:
            continue
        count = int(match.group(2))
        block_index += 1
        expected = 4 + len(outputs)
        start: int | None = None
        # The documented format contains four descriptive/header lines.  Search a
        # small bounded window as a compatibility guard for minor release changes.
        for probe in range(index + 1, min(len(lines), index + 12)):
            parts = [part.strip() for part in lines[probe].split(",")]
            if len(parts) < expected:
                continue
            try:
                int(float(parts[0])); int(float(parts[1])); int(float(parts[2])); int(float(parts[3]))
            except (TypeError, ValueError):
                continue
            start = probe
            break
        if start is None:
            continue
        consumed = 0
        cursor = start
        while cursor < len(lines) and consumed < count:
            parts = [part.strip() for part in lines[cursor].split(",")]
            if len(parts) < expected:
                break
            try:
                int(float(parts[0])); int(float(parts[1])); int(float(parts[2])); int(float(parts[3]))
            except (TypeError, ValueError):
                break
            values = parts[:expected]
            row = {name: values[position] for position, name in enumerate(headers[:-1])}
            row["Step"] = str(block_index - 1)
            rows.append(row)
            consumed += 1
            cursor += 1
    if not rows:
        return None
    return headers, rows


def normalize_fea_csv(raw_path: Path, frames_dir: Path, max_points_per_frame: int, requested_outputs: str | None = None) -> dict[str, Any]:
    """Normalize Motor-CAD ``save_fea_data`` CSV into browser-friendly frames.

    Motor-CAD may vary the column spelling across versions.  The parser is
    deliberately tolerant and records the discovered schema.  If coordinates
    cannot be located the raw export is still valid evidence and the caller
    receives ``normalized=False`` instead of synthetic field data.
    """
    try:
        sample = raw_path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
    except OSError as exc:
        return {"normalized": False, "reason": f"raw_read_failed: {exc}"}
    if not sample.strip():
        return {"normalized": False, "reason": "raw_export_empty"}

    try:
        full_text = raw_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return {"normalized": False, "reason": f"raw_read_failed: {exc}"}

    native_table = _parse_motorcad_table_export(full_text, requested_outputs)
    source_format = "motorcad_table" if native_table else "delimited_table"
    delimiter = ","
    if native_table:
        headers, raw_rows = native_table
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            if "\t" in sample:
                delimiter = "\t"
            elif ";" in sample:
                delimiter = ";"
        try:
            reader = csv.DictReader(full_text.splitlines(), delimiter=delimiter)
            headers = list(reader.fieldnames or [])
            raw_rows = [row for row in reader if isinstance(row, dict)]
        except Exception as exc:
            return {"normalized": False, "reason": f"csv_parse_failed: {type(exc).__name__}: {exc}"}

    if not headers:
        return {"normalized": False, "reason": "header_missing"}

    x_key = _pick(headers, ("X", "XCoord", "XCoordinate", "NodeX"))
    y_key = _pick(headers, ("Y", "YCoord", "YCoordinate", "NodeY"))
    step_key = _pick(headers, ("Step", "StepNumber", "TimeStep", "TimeStepNumber", "SolutionStep"))
    region_key = _pick(headers, ("RegCode", "RegionCode", "Region"))
    b_key = _pick(headers, ("B", "FluxDensity", "BMag", "BMagnitude"), fuzzy=False)
    bx_key = _pick(headers, ("Bx", "FluxDensityX"))
    by_key = _pick(headers, ("By", "FluxDensityY"))
    pt_key = _pick(headers, ("Pt", "VectorPotential", "A", "Az"))
    element_key = _pick(headers, ("TriIndex", "ElementIndex", "ElementID", "Element"), fuzzy=False)
    node_keys = [
        key for key in (
            _pick(headers, ("Node1",), fuzzy=False),
            _pick(headers, ("Node2",), fuzzy=False),
            _pick(headers, ("Node3",), fuzzy=False),
        ) if key
    ]

    if not x_key or not y_key:
        return {
            "normalized": False,
            "reason": "coordinate_columns_not_found",
            "headers": headers,
            "row_count": len(raw_rows),
        }

    grouped: dict[str, list[dict[str, Any]]] = {}
    dropped = 0
    for row in raw_rows:
        x = _to_float(row.get(x_key))
        y = _to_float(row.get(y_key))
        if x is None or y is None:
            dropped += 1
            continue
        b = _to_float(row.get(b_key)) if b_key else None
        bx = _to_float(row.get(bx_key)) if bx_key else None
        by = _to_float(row.get(by_key)) if by_key else None
        if b is None and bx is not None and by is not None:
            b = math.hypot(bx, by)
        point: dict[str, Any] = {"x": x, "y": y}
        if b is not None:
            point["b"] = b
        if bx is not None:
            point["bx"] = bx
        if by is not None:
            point["by"] = by
        pt = _to_float(row.get(pt_key)) if pt_key else None
        if pt is not None:
            point["pt"] = pt
        if region_key and row.get(region_key) not in (None, ""):
            point["region"] = str(row.get(region_key))
        if element_key and row.get(element_key) not in (None, ""):
            point["element_id"] = _scalar_id(row.get(element_key))
        if node_keys:
            point["node_ids"] = [_scalar_id(row.get(key)) for key in node_keys if row.get(key) not in (None, "")]
        step_value = str(row.get(step_key) if step_key else 0)
        grouped.setdefault(step_value, []).append(point)

    if not grouped:
        return {"normalized": False, "reason": "no_numeric_points", "headers": headers}

    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_index: list[dict[str, Any]] = []
    all_b: list[float] = []
    all_pt: list[float] = []
    all_regions: set[str] = set()
    ordered = sorted(grouped.items(), key=lambda item: (_to_float(item[0]) is None, _to_float(item[0]) or 0.0, item[0]))
    for index, (step_value, points) in enumerate(ordered):
        sampled = _reservoir_stride(points, max_points_per_frame)
        b_values = [float(p["b"]) for p in sampled if "b" in p]
        pt_values = [float(p["pt"]) for p in sampled if "pt" in p]
        all_b.extend(b_values)
        all_pt.extend(pt_values)
        all_regions.update(str(p["region"]) for p in sampled if p.get("region") not in (None, ""))
        frame_name = f"frame_{index:04d}.json"
        payload = {
            "index": index,
            "step": step_value,
            "point_count": len(sampled),
            "source_point_count": len(points),
            "regions": sorted({str(p["region"]) for p in sampled if p.get("region") not in (None, "")}),
            "points": sampled,
        }
        (frames_dir / frame_name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        frame_index.append({
            "index": index,
            "step": step_value,
            "file": frame_name,
            "point_count": len(sampled),
            "source_point_count": len(points),
            "b_min": min(b_values) if b_values else None,
            "b_max": max(b_values) if b_values else None,
            "pt_min": min(pt_values) if pt_values else None,
            "pt_max": max(pt_values) if pt_values else None,
        })

    return {
        "normalized": True,
        "source_format": source_format,
        "headers": headers,
        "delimiter": delimiter,
        "coordinate_columns": {"x": x_key, "y": y_key},
        "field_columns": {"b": b_key, "bx": bx_key, "by": by_key, "pt": pt_key, "region": region_key, "step": step_key},
        "available_fields": [field for field, column in (("b", b_key), ("bx", bx_key), ("by", by_key), ("pt", pt_key)) if column],
        "regions": sorted(all_regions),
        "connectivity_columns": {"element": element_key, "nodes": node_keys},
        "capabilities": {
            "playback": len(frame_index) > 1,
            "field_selection": sum(column is not None for column in (b_key, bx_key, by_key, pt_key)) > 1,
            "region_filter": bool(all_regions),
            "manual_range": True,
            "nearest_point_probe": True,
            "raw_download": True,
            "connectivity_metadata": bool(element_key and len(node_keys) >= 3),
            "mesh_edges": False,
            "filled_contours": False,
            "equipotential_lines": False,
        },
        "row_count": len(raw_rows),
        "dropped_rows": dropped,
        "frame_count": len(frame_index),
        "frames": frame_index,
        "global_ranges": {
            "b_min": min(all_b) if all_b else None,
            "b_max": max(all_b) if all_b else None,
            "pt_min": min(all_pt) if all_pt else None,
            "pt_max": max(all_pt) if all_pt else None,
        },
    }


class NativeFEAEvidenceExporter:
    """Best-effort Motor-CAD native FEA evidence exporter.

    Evidence export must never turn a successful engineering solve into a failed
    Case.  Failures are recorded in the manifest and surfaced separately from
    ``execution_status``.
    """

    def __init__(self, config: NativeFEAExportConfig):
        self.config = config

    def _estimate_step_count(self, mc: Any) -> int:
        try:
            x_values, _ = mc.get_magnetic_graph("TorqueVW")
            return max(1, min(self.config.max_steps, len(x_values or [])))
        except Exception:
            return 1

    def export(self, mc: Any, work_dir: Path, *, source_mot: Path | None = None, motorcad_version: str | None = None) -> tuple[dict[str, Any], list[str]]:
        root = work_dir / "native_fea"
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "native_fea_manifest.json"
        warnings: list[str] = []
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "authority": "motorcad_save_fea_data",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "enabled": self.config.enabled,
            "status": "SKIPPED" if not self.config.enabled else "PENDING",
            "motorcad_version": motorcad_version,
            "source_mot": str(source_mot) if source_mot else None,
            "source_mot_sha256": _sha256(source_mot) if source_mot and source_mot.exists() else None,
            "requested_outputs": self.config.outputs,
            "regions": self.config.regions,
        }
        if not self.config.enabled or not hasattr(mc, "save_fea_data"):
            if self.config.enabled:
                manifest["status"] = "UNAVAILABLE"
                manifest["reason"] = "PyMotorCAD save_fea_data API unavailable"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return manifest, warnings

        step_count = self._estimate_step_count(mc)
        ranges: list[tuple[int, int]] = []
        if step_count > 1:
            ranges.extend([(0, step_count - 1), (1, step_count)])
        ranges.extend([(0, 0), (1, 1)])
        # Preserve order while removing duplicates.
        ranges = list(dict.fromkeys(ranges))
        attempts: list[dict[str, Any]] = []
        raw_path = root / "native_fea_raw.csv"
        used_range: tuple[int, int] | None = None
        for first_step, final_step in ranges:
            try:
                if raw_path.exists():
                    raw_path.unlink()
                mc.save_fea_data(
                    str(raw_path), int(first_step), int(final_step),
                    self.config.outputs, self.config.regions, self.config.separator,
                )
                if raw_path.exists() and raw_path.stat().st_size > 0:
                    used_range = (first_step, final_step)
                    attempts.append({"first_step": first_step, "final_step": final_step, "ok": True, "size_bytes": raw_path.stat().st_size})
                    break
                attempts.append({"first_step": first_step, "final_step": final_step, "ok": False, "error": "export file missing or empty"})
            except Exception as exc:
                attempts.append({"first_step": first_step, "final_step": final_step, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

        manifest["attempts"] = attempts
        if used_range is None:
            manifest["status"] = "WARNING"
            manifest["reason"] = "Motor-CAD native FEA export did not produce a readable file"
            warnings.append("Motor-CAD 原生 FEA 数据导出失败；求解结果仍有效，可继续使用曲线回放。")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return manifest, warnings

        manifest.update({
            "status": "PASS",
            "first_step": used_range[0],
            "final_step": used_range[1],
            "raw_file": raw_path.name,
            "raw_size_bytes": raw_path.stat().st_size,
            "raw_sha256": _sha256(raw_path),
        })
        normalized = normalize_fea_csv(raw_path, root / "frames", self.config.max_points_per_frame, self.config.outputs)
        manifest["normalization"] = normalized
        if not normalized.get("normalized"):
            manifest["status"] = "RAW_ONLY"
            warnings.append("已保存 Motor-CAD 原生 FEA 数据，但当前版本未识别其坐标列；可在诊断包中查看原始导出。")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest, warnings
