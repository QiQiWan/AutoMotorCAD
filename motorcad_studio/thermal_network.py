from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _native_rows(table: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(table, dict):
        nodes = table.get("nodes") or []
        edges = table.get("edges") or table.get("links") or []
        return ([dict(row) for row in nodes if isinstance(row, dict)], [dict(row) for row in edges if isinstance(row, dict)])
    return [], []


def normalize_thermal_network(result: dict[str, Any], scenario: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create one explicit thermal evidence contract for all viewer consumers."""
    tables = result.get("tables") or {}
    nodes, edges = _native_rows(tables.get("thermal_network"))
    if nodes:
        normalized_nodes = []
        for index, node in enumerate(nodes):
            normalized_nodes.append({
                "id": str(node.get("id") or node.get("name") or f"N{index + 1}"),
                "label": str(node.get("label") or node.get("name") or node.get("id") or f"Node {index + 1}"),
                "temperature_c": _finite(node.get("temperature_c", node.get("temperature"))),
                "power_w": _finite(node.get("power_w", node.get("power"))),
                "x": _finite(node.get("x")), "y": _finite(node.get("y")),
                "component": node.get("component") or node.get("group"),
            })
        normalized_edges = []
        for index, edge in enumerate(edges):
            normalized_edges.append({
                "id": str(edge.get("id") or f"R{index + 1}"),
                "source": str(edge.get("source") or edge.get("from") or ""),
                "target": str(edge.get("target") or edge.get("to") or ""),
                "resistance_k_per_w": _finite(edge.get("resistance_k_per_w", edge.get("resistance"))),
                "heat_flow_w": _finite(edge.get("heat_flow_w", edge.get("heat_flow"))),
                "kind": edge.get("kind") or "thermal_resistance",
            })
        payload = {"nodes": normalized_nodes, "edges": normalized_edges}
        temperatures = [row["temperature_c"] for row in normalized_nodes if row.get("temperature_c") is not None]
        return {
            "schema_version": 1, "available": True, "native": True,
            "authority": "motorcad_native_thermal_network", "status": "NATIVE_NETWORK",
            "nodes": normalized_nodes, "edges": normalized_edges,
            "temperature_range_c": {"min": min(temperatures), "max": max(temperatures)} if temperatures else None,
            "completeness": {"topology": bool(normalized_edges), "temperatures": bool(temperatures), "resistances": any(row.get("resistance_k_per_w") is not None for row in normalized_edges)},
            "evidence_hash": _hash(payload), "disclaimer": None,
        }

    scalars = result.get("scalars") or {}
    scenario = scenario or {}
    candidates = []
    for key, value in scalars.items():
        if "temp" in str(key).lower() or "temperature" in str(key).lower():
            number = _finite(value)
            if number is not None:
                candidates.append({"id": str(key), "label": str(key).replace("_", " "), "temperature_c": number, "power_w": None, "component": "result"})
    ambient = _finite(scenario.get("ambient_temperature", scenario.get("ambient_temperature_c")))
    if ambient is not None:
        candidates.append({"id": "ambient", "label": "环境", "temperature_c": ambient, "power_w": None, "component": "boundary"})
    return {
        "schema_version": 1, "available": bool(candidates), "native": False,
        "authority": "studio_engineering_summary", "status": "SUMMARY_ONLY" if candidates else "UNAVAILABLE",
        "nodes": candidates, "edges": [],
        "temperature_range_c": {"min": min(row["temperature_c"] for row in candidates), "max": max(row["temperature_c"] for row in candidates)} if candidates else None,
        "completeness": {"topology": False, "temperatures": bool(candidates), "resistances": False},
        "evidence_hash": _hash(candidates) if candidates else None,
        "disclaimer": "当前仅为已提取温度结果摘要；未将其表示为 Motor-CAD 原生热网络拓扑。",
    }
