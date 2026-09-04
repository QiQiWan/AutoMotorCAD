from __future__ import annotations

import csv
import hashlib
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


@lru_cache(maxsize=512)
def _fingerprinted_sha256(path_text: str, size: int, mtime_ns: int, inode: int) -> str | None:
    del size, mtime_ns, inode
    return file_sha256(Path(path_text))


def cached_file_sha256(path: Path) -> str | None:
    """Reuse a digest while the file identity, size and nanosecond mtime match."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return _fingerprinted_sha256(str(path.resolve()), stat.st_size, stat.st_mtime_ns, int(getattr(stat, "st_ino", 0)))


def _finite_number(value: str) -> int | float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _cell(value: str) -> str | int | float | None:
    text = str(value or "").strip()
    if not text:
        return None
    number = _finite_number(text)
    return number if number is not None else text


def _unique_columns(values: list[str]) -> list[str]:
    columns: list[str] = []
    counts: dict[str, int] = {}
    for index, value in enumerate(values):
        base = str(value or "").strip() or f"column_{index + 1}"
        counts[base] = counts.get(base, 0) + 1
        columns.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return columns


def parse_native_delimited_table(
    path: str | Path,
    *,
    authority: str,
    max_rows: int = 500,
    max_bytes: int = 1024 * 1024 * 1024,
) -> tuple[dict[str, Any] | None, str | None]:
    """Stream a Motor-CAD text/CSV export without inventing table semantics.

    Native exports can contain descriptive lines before the actual table.  A row is
    accepted as the header only when it contains text labels and the following row
    has the same width with at least one finite numeric value.  The complete native
    file remains an artifact; only the bounded preview rows are retained in
    memory.  Counts and numeric coverage are calculated across the complete file.
    """
    source = Path(path)
    if not source.exists():
        return None, "native_table_file_missing"
    try:
        size = source.stat().st_size
    except OSError as exc:
        return None, f"native_table_stat_failed: {type(exc).__name__}: {exc}"
    if size <= 0:
        return None, "native_table_file_empty"
    if size > max_bytes:
        return None, f"native_table_file_exceeds_limit: {size} > {max_bytes}"
    try:
        with source.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            sample = handle.read(16384)
    except OSError as exc:
        return None, f"native_table_read_failed: {type(exc).__name__}: {exc}"
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ";" if ";" in sample else ","
    parsed_rows: list[dict[str, Any]] = []
    source_row_count = 0
    numeric_cell_count = 0
    nonempty_cell_count = 0
    columns: list[str] | None = None
    previous: list[str] | None = None
    nonempty_row_index = -1

    def accept(row: list[str]) -> None:
        nonlocal source_row_count, numeric_cell_count, nonempty_cell_count
        if columns is None or len(row) != len(columns):
            return
        converted = [_cell(value) for value in row]
        if not any(value is not None for value in converted):
            return
        source_row_count += 1
        nonempty_cell_count += sum(value is not None for value in converted)
        numeric_cell_count += sum(
            not isinstance(value, bool) and isinstance(value, (int, float))
            for value in converted if value is not None
        )
        if len(parsed_rows) < max(1, int(max_rows)):
            parsed_rows.append(dict(zip(columns, converted)))

    try:
        with source.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for raw in csv.reader(handle, delimiter=delimiter):
                row = [str(cell).strip() for cell in raw]
                if not any(row):
                    continue
                nonempty_row_index += 1
                if columns is None:
                    if previous is not None and nonempty_row_index <= 80:
                        labels = sum(any(character.isalpha() for character in cell) for cell in previous)
                        numeric = sum(_finite_number(cell) is not None for cell in row)
                        if len(previous) >= 2 and len(row) == len(previous) and labels >= 1 and numeric >= 1:
                            columns = _unique_columns(previous)
                            accept(row)
                            previous = None
                            continue
                    previous = row
                    if nonempty_row_index > 80:
                        break
                    continue
                accept(row)
    except (OSError, csv.Error) as exc:
        return None, f"native_table_csv_failed: {type(exc).__name__}: {exc}"
    if columns is None:
        return None, "native_table_header_not_found"
    if not parsed_rows:
        return None, "native_table_has_no_parseable_rows"
    numeric_fraction = numeric_cell_count / nonempty_cell_count if nonempty_cell_count else 0.0
    return {
        "schema_version": 2,
        "authority": authority,
        "source_file": source.name,
        "source_size_bytes": size,
        "source_sha256": file_sha256(source),
        "delimiter": "TAB" if delimiter == "\t" else delimiter,
        "columns": columns,
        "rows": parsed_rows,
        "row_count": len(parsed_rows),
        "source_row_count": source_row_count,
        "truncated": len(parsed_rows) < source_row_count,
        "numeric_cell_fraction": round(numeric_fraction, 8),
        "parser_contract": "streaming_complete_scan_v1",
        "retained_row_limit": max(1, int(max_rows)),
    }, None


def read_native_table_page(
    path: str | Path, *, columns: list[str], delimiter: str,
    offset: int = 0, limit: int = 200,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read one bounded page from a verified native table using constant memory."""
    source = Path(path)
    if not source.exists() or not source.is_file():
        return None, "native_table_file_missing"
    expected = [str(column) for column in columns]
    if not expected:
        return None, "native_table_columns_missing"
    separator = "\t" if delimiter == "TAB" else str(delimiter or ",")[:1]
    start, page_limit = max(0, int(offset)), max(1, min(500, int(limit)))
    rows: list[dict[str, Any]] = []
    valid_index = 0
    header_found = False
    try:
        with source.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for raw in csv.reader(handle, delimiter=separator):
                row = [str(cell).strip() for cell in raw]
                if not any(row):
                    continue
                if not header_found:
                    if _unique_columns(row) == expected:
                        header_found = True
                    continue
                if len(row) != len(expected):
                    continue
                converted = [_cell(value) for value in row]
                if not any(value is not None for value in converted):
                    continue
                if valid_index >= start:
                    rows.append(dict(zip(expected, converted)))
                valid_index += 1
                if len(rows) >= page_limit:
                    break
    except (OSError, csv.Error) as exc:
        return None, f"native_table_page_failed: {type(exc).__name__}: {exc}"
    if not header_found:
        return None, "native_table_header_not_found"
    return {
        "schema_version": 1,
        "offset": start,
        "limit": page_limit,
        "returned_count": len(rows),
        "next_offset": start + len(rows),
        "rows": rows,
    }, None


def parse_thermal_node_table(
    path: str | Path,
    *,
    authority: str = "motorcad_export_results_steady_state",
    max_rows: int = 500,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract a thermal-node table only when the native CSV exposes node semantics.

    ``MotorCAD.export_results("SteadyState", ...)`` is version/template dependent.
    Some versions export a node/component table, while others export only summary
    results.  This parser deliberately refuses to label an arbitrary summary CSV as
    a thermal network.  It requires a temperature column plus a node/component-like
    identity column.  Heat-flow/power is retained when present.
    """
    table, error = parse_native_delimited_table(path, authority=authority, max_rows=max_rows)
    if not table:
        return None, error

    columns = [str(column) for column in table.get("columns") or []]
    if not columns:
        return None, "thermal_table_columns_missing"

    def norm(value: str) -> str:
        return "".join(character.lower() for character in str(value) if character.isalnum())

    normalized = {column: norm(column) for column in columns}

    def first(predicate):
        return next((column for column in columns if predicate(normalized[column])), None)

    temperature = first(lambda key: "temperature" in key or key.startswith("temp") or key.endswith("tempc") or key in {"t", "degc"})
    node = first(lambda key: any(token in key for token in ("node", "component", "part", "location", "name", "region")))
    power = first(lambda key: any(token in key for token in ("heatflow", "heatflux", "power", "loss")))

    if temperature is None:
        return None, "thermal_temperature_column_not_found"
    if node is None:
        return None, "thermal_node_identity_column_not_found"

    rows: list[dict[str, Any]] = []
    for index, source in enumerate(table.get("rows") or []):
        if not isinstance(source, dict):
            continue
        raw_temperature = source.get(temperature)
        raw_power = source.get(power) if power else None
        if not isinstance(raw_temperature, (int, float)) or isinstance(raw_temperature, bool):
            continue
        identity = source.get(node)
        if identity is None or str(identity).strip() == "":
            identity = index
        row = {
            "node_id": str(identity),
            "name": str(identity),
            "temperature_c": raw_temperature,
        }
        if isinstance(raw_power, (int, float)) and not isinstance(raw_power, bool):
            row["heat_flow_w"] = raw_power
        rows.append(row)

    if not rows:
        return None, "thermal_node_rows_not_found"

    return {
        "schema_version": 1,
        "authority": authority,
        "source_file": table.get("source_file"),
        "source_size_bytes": table.get("source_size_bytes"),
        "source_sha256": table.get("source_sha256"),
        "columns": ["node_id", "name", "temperature_c"] + (["heat_flow_w"] if power else []),
        "rows": rows,
        "row_count": len(rows),
        "source_row_count": table.get("source_row_count"),
        "truncated": bool(table.get("truncated")),
        "semantic_columns": {
            "node": node,
            "temperature": temperature,
            "heat_flow": power,
        },
        "topology_edges_available": False,
        "note": "Native steady-state result table; no thermal resistance edges are inferred.",
    }, None
