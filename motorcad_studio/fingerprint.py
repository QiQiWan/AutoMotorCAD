from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .version import __version__


def file_sha256(path: str | Path | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_simulation_fingerprint(
    *,
    request: dict[str, Any],
    template: dict[str, Any],
    parameters: dict[str, Any],
    registry_hashes: dict[str, str],
    motorcad_version: str,
    pymotorcad_version: str | None = None,
    runtime_calibrations: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    model_source = template.get("model_source", {})
    local_mot = model_source.get("resolved_local_mot") or model_source.get("local_mot")
    source_mtt = model_source.get("resolved_source_mtt") or template.get("path")
    payload = {
        "application_version": __version__,
        "template": {
            "id": template.get("id"),
            "system_template_id": template.get("system_template_id"),
            "version": template.get("version"),
            "source_mtt_sha256": file_sha256(source_mtt),
            "local_mot_sha256": file_sha256(local_mot),
            "model_source_type": model_source.get("active_type"),
        },
        "solver": {
            "mode": request.get("solver_mode"),
            "analysis": request.get("analysis"),
            "motorcad_version": motorcad_version,
            "pymotorcad_version": pymotorcad_version,
        },
        "registries": registry_hashes,
        "runtime_calibrations": [
            {
                "result_id": item.get("result_id"),
                "extractor": item.get("extractor"),
                "graph_name": item.get("graph_name"),
                "section_number": item.get("section_number"),
                "status": item.get("status"),
                "updated_at": item.get("updated_at"),
            }
            for item in (runtime_calibrations or []) if str(item.get("status") or "").upper() == "VERIFIED"
        ],
        "recipe": {
            "id": request.get("analysis"),
            "version": "1.0.0",
            "quality_profile": request.get("quality_profile"),
        },
        "inputs": {
            "parameters": parameters,
            "scenario": request.get("scenario", {}),
            "materials": request.get("materials", {}),
            "solver_settings": request.get("solver_settings", {}),
            "automation_overrides": request.get("automation_overrides", {}),
            "requested_outputs": request.get("requested_outputs", []),
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), payload
