from __future__ import annotations

import hashlib
from array import array
import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.bootstrap import build_container, create_app
from motorcad_studio.db import Database
from motorcad_studio.modules.field_data.binary import decode_header, encode_frame
from motorcad_studio.modules.shared.transfer_budget import (
    TransferBudget,
    TransferBudgetExceeded,
    TransferPayloadTooLarge,
)
from motorcad_studio.result_domain.contracts import (
    ResultBundle,
    ResultProvenance,
    ResultQuality,
    SeriesResult,
)
from motorcad_studio.result_domain.heavy_data import (
    CHUNKPACK_FORMAT,
    ResultDataGateway,
)
from motorcad_studio.result_domain.service import ResultBundleService
from tests.test_bootstrap import isolated_settings


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_canonical_json(path: Path, value: Any) -> tuple[int, str]:
    payload = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return len(payload), hashlib.sha256(payload).hexdigest()


def _insert_task_case(
    container,
    *,
    task_id: str,
    case_id: str,
    work_dir: Path,
    status: str = "COMPLETED",
) -> None:
    now = container.db.now()
    container.db.execute(
        """INSERT INTO tasks(
               id,project_name,name,template_id,solver_mode,analysis,status,progress,
               current_stage,cancel_requested,request_json,created_at,updated_at,case_count
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            "M5-A Test Project",
            "M5-A Test Task",
            "a1",
            "mock",
            "emag",
            status,
            100.0 if status == "COMPLETED" else 0.0,
            "COMPLETED" if status == "COMPLETED" else "QUEUED",
            0,
            container.db.dumps({"source": "m5a-test"}),
            now,
            now,
            1,
        ),
    )
    container.db.execute(
        """INSERT INTO cases(
               id,task_id,case_index,status,progress,parameters_json,result_json,
               work_dir,updated_at,execution_status,quality_status
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            case_id,
            task_id,
            0,
            status,
            100.0 if status == "COMPLETED" else 0.0,
            container.db.dumps({"speed_rpm": 3000}),
            container.db.dumps({}),
            str(work_dir),
            now,
            status,
            "PASS" if status == "COMPLETED" else "NOT_ASSESSED",
        ),
    )


def _seed_field_data(container) -> dict[str, Any]:
    token = uuid.uuid4().hex[:12].upper()
    task_id = f"TSK-M5A-{token}"
    case_id = f"CAS-M5A-{token}"
    work_dir = container.settings.results_dir / task_id / case_id
    root = work_dir / "native_fea"
    _insert_task_case(
        container,
        task_id=task_id,
        case_id=case_id,
        work_dir=work_dir,
    )

    nodes = [
        {"id": "1", "x": 0.0, "y": 0.0},
        {"id": "2", "x": 1.0, "y": 0.0},
        {"id": "3", "x": 0.0, "y": 1.0},
        {"id": "4", "x": 1.0, "y": 1.0},
    ]
    elements = [
        {
            "id": "e1",
            "element_id": "e1",
            "x": 1.0 / 3.0,
            "y": 1.0 / 3.0,
            "region": "stator",
            "node_ids": ["1", "2", "3"],
            "b": 1.0,
        },
        {
            "id": "e2",
            "element_id": "e2",
            "x": 2.0 / 3.0,
            "y": 2.0 / 3.0,
            "region": "rotor",
            "node_ids": ["2", "4", "3"],
            "b": 2.0,
        },
    ]
    frame_payload = {
        "schema_version": 3,
        "index": 0,
        "step": 0,
        "point_count": 2,
        "source_point_count": 2,
        "regions": ["stator", "rotor"],
        "mesh_complete": True,
        "mesh_nodes": nodes,
        "points": elements,
    }
    frame_path = root / "frames" / "frame_0000.json"
    frame_size, frame_hash = _write_canonical_json(frame_path, frame_payload)

    chunk_payload = {
        "schema_version": 1,
        "frame_index": 0,
        "chunk_index": 0,
        "mesh_nodes": nodes,
        "elements": elements,
    }
    chunk_path = root / "viewer_frames" / "frame_0000" / "chunk_0000.json"
    chunk_size, chunk_hash = _write_canonical_json(chunk_path, chunk_payload)
    original_chunk_bytes = chunk_path.read_bytes()

    viewer_manifest = {
        "schema_version": 1,
        "contract_version": "0.89-G3.3",
        "frame_index": 0,
        "step": 0,
        "element_count": 2,
        "node_count": 4,
        "chunk_count": 1,
        "mesh_complete": True,
        "full_region": True,
        "data_bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 0.0],
        "available_fields": ["b"],
        "regions": ["stator", "rotor"],
        "chunks": [
            {
                "index": 0,
                "file": "chunk_0000.json",
                "element_count": 2,
                "node_count": 4,
                "size_bytes": chunk_size,
                "sha256": chunk_hash,
            }
        ],
    }
    viewer_manifest_path = root / "viewer_frames" / "frame_0000" / "manifest.json"
    viewer_size, viewer_hash = _write_canonical_json(viewer_manifest_path, viewer_manifest)

    frame_record = {
        "index": 0,
        "step": 0,
        "file": "frame_0000.json",
        "size_bytes": frame_size,
        "sha256": frame_hash,
        "point_count": 2,
        "source_point_count": 2,
        "viewer_manifest_file": "viewer_frames/frame_0000/manifest.json",
        "viewer_manifest_size_bytes": viewer_size,
        "viewer_manifest_sha256": viewer_hash,
        "viewer_element_count": 2,
        "viewer_mesh_complete": True,
        "viewer_data_bounds": [0.0, 1.0, 0.0, 1.0, 0.0, 0.0],
    }
    native_manifest = {
        "authority": "MotorCADNativeFEAEvidenceV1",
        "status": "EXPORTED",
        "motorcad_version": "MOCK-M5A",
        "source_mot_sha256": "a" * 64,
        "raw_sha256": "b" * 64,
        "raw_size_bytes": 0,
        "first_step": 0,
        "final_step": 0,
        "contract_id": "m5a-test-contract",
        "normalization": {
            "normalized": True,
            "frame_count": 1,
            "coordinate_unit": "m",
            "coordinate_bounds": {
                "xmin": 0.0,
                "xmax": 1.0,
                "ymin": 0.0,
                "ymax": 1.0,
            },
            "available_fields": ["b"],
            "regions": ["stator", "rotor"],
            "capabilities": {
                "full_region_mesh": True,
                "progressive_mesh_chunks": True,
                "filled_contours": True,
                "mesh_edges": True,
            },
            "frames": [frame_record],
            "viewer_contract": {"playback_frame_indices": [0]},
            "quality_metrics": {"coordinate_valid_fraction": 1.0},
        },
        "validation": {"qualification_eligible": True},
        "policy": {"field_source": "motorcad_native_export"},
    }
    manifest_path = root / "native_fea_manifest.json"
    _write_canonical_json(manifest_path, native_manifest)

    return {
        "task_id": task_id,
        "case_id": case_id,
        "work_dir": work_dir,
        "root": root,
        "frame_path": frame_path,
        "chunk_path": chunk_path,
        "chunk_bytes": original_chunk_bytes,
        "viewer_manifest_path": viewer_manifest_path,
        "chunk_hash": chunk_hash,
    }


@pytest.fixture(scope="module")
def m5a_runtime(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m5a-results-field-data")
    container = build_container(isolated_settings(root))
    app = create_app(container)
    with TestClient(app) as client:
        yield root, container, app, client


def test_field_data_canonical_lod_and_compatibility(m5a_runtime):
    _, container, _, client = m5a_runtime
    seeded = _seed_field_data(container)
    case_id = seeded["case_id"]

    manifest_url = f"/api/cases/{case_id}/field-data/manifest"
    response = client.get(manifest_url)
    assert response.status_code == 200
    payload = response.json()
    assert payload["authority"] == "FieldDataManifestV1"
    assert payload["contract_version"] == "1"
    assert payload["available"] is True
    assert payload["full_mesh_available"] is True
    assert payload["coordinate_system"]["physical_z"] is False
    assert payload["coordinate_system"]["planar_compatibility"] is True
    assert payload["available_fields"] == ["b"]
    assert payload["regions"] == ["stator", "rotor"]
    assert payload["frames"][0]["lod_urls"]["2"].endswith("/lod/2")
    assert response.headers["x-mcs-field-data-contract"] == "1"
    manifest_etag = response.headers["etag"]

    conditional = client.get(
        manifest_url,
        headers={"If-None-Match": f'W/{manifest_etag}, "other"'},
    )
    assert conditional.status_code == 304

    for lod, expected_mode in ((0, "inline_sample"), (1, "inline_sample")):
        lod_response = client.get(
            f"/api/cases/{case_id}/field-data/frames/0/lod/{lod}?field=b"
        )
        assert lod_response.status_code == 200
        lod_payload = lod_response.json()
        assert lod_payload["field_data_contract"]["lod"] == lod
        assert lod_payload["field_data_contract"]["transfer_mode"] == expected_mode
        assert lod_payload["point_count"] == 2
        assert lod_payload["mesh_complete"] is True
        assert lod_response.headers["x-mcs-field-data-contract"] == "1"
        assert lod_response.headers["x-mcs-field-data-lod"] == str(lod)

    full = client.get(
        f"/api/cases/{case_id}/field-data/frames/0/lod/2?field=b"
    )
    assert full.status_code == 200
    full_payload = full.json()
    assert full_payload["authority"] == "FieldDataFrameLODV1"
    assert full_payload["transfer_mode"] == "chunked_manifest"
    assert full_payload["mesh_complete"] is True
    assert full_payload["element_count"] == 2
    assert full_payload["node_count"] == 4
    assert full_payload["chunk_count"] == 1
    assert "/field-data/" in full_payload["mesh_manifest_url"]
    assert "/fea-frames/" in full_payload["legacy_mesh_manifest_url"]
    assert full.headers["cache-control"].endswith("immutable")

    canonical_manifest_url = full_payload["mesh_manifest_url"]
    mesh_manifest = client.get(canonical_manifest_url)
    assert mesh_manifest.status_code == 200
    mesh_payload = mesh_manifest.json()
    assert mesh_payload["field_data_contract"]["authority"] == "FieldDataMeshManifestV1"
    assert mesh_payload["field_data_contract"]["topology_hash"]
    assert "/field-data/" in mesh_payload["chunk_endpoint"]
    assert mesh_manifest.headers["x-mcs-field-data-contract"] == "1"
    mesh_etag = mesh_manifest.headers["etag"]
    assert client.get(
        canonical_manifest_url,
        headers={"If-None-Match": f'W/{mesh_etag}'},
    ).status_code == 304

    canonical_chunk_url = mesh_payload["chunk_endpoint"].replace("{chunk_index}", "0")
    mesh_chunk = client.get(canonical_chunk_url)
    assert mesh_chunk.status_code == 200
    chunk_payload = mesh_chunk.json()
    assert chunk_payload["field_data_contract"]["authority"] == "FieldDataMeshChunkV1"
    assert chunk_payload["integrity"]["status"] == "VERIFIED"
    assert len(chunk_payload["elements"]) == 2
    chunk_etag = mesh_chunk.headers["etag"]
    assert client.get(
        canonical_chunk_url,
        headers={"If-None-Match": f'W/{chunk_etag}, "unused"'},
    ).status_code == 304

    legacy_manifest = client.get(f"/api/cases/{case_id}/fea-frames/0/mesh-manifest")
    legacy_chunk = client.get(f"/api/cases/{case_id}/fea-frames/0/mesh-chunks/0")
    assert legacy_manifest.status_code == 200
    assert legacy_chunk.status_code == 200
    assert legacy_manifest.json()["integrity"]["sha256"] == mesh_payload["integrity"]["sha256"]
    assert legacy_chunk.json()["integrity"]["sha256"] == chunk_payload["integrity"]["sha256"]

    integrity = client.get(
        f"/api/cases/{case_id}/field-data/integrity?verify_chunks=true"
    )
    assert integrity.status_code == 200
    integrity_payload = integrity.json()
    assert integrity_payload["valid"] is True
    assert integrity_payload["verified_frame_count"] == 1
    assert integrity_payload["verified_chunk_count"] == 1


def test_field_data_integrity_tamper_and_path_escape_are_blocked(m5a_runtime, tmp_path: Path):
    _, container, _, client = m5a_runtime
    seeded = _seed_field_data(container)
    case_id = seeded["case_id"]
    chunk_path: Path = seeded["chunk_path"]
    original: bytes = seeded["chunk_bytes"]

    try:
        chunk_path.write_bytes(b'{"tampered":true}')
        report = client.get(
            f"/api/cases/{case_id}/field-data/integrity?verify_chunks=true"
        )
        assert report.status_code == 200
        payload = report.json()
        assert payload["valid"] is False
        assert payload["issues"]
        assert payload["issues"][0]["status_code"] == 409

        canonical = client.get(
            f"/api/cases/{case_id}/field-data/frames/0/mesh-chunks/0"
        )
        legacy = client.get(f"/api/cases/{case_id}/fea-frames/0/mesh-chunks/0")
        assert canonical.status_code == 409
        assert legacy.status_code == 409
    finally:
        chunk_path.write_bytes(original)

    token = uuid.uuid4().hex[:10].upper()
    escaped_task = f"TSK-ESC-{token}"
    escaped_case = f"CAS-ESC-{token}"
    escaped_work_dir = tmp_path / "outside-results" / escaped_case
    _insert_task_case(
        container,
        task_id=escaped_task,
        case_id=escaped_case,
        work_dir=escaped_work_dir,
    )
    escaped = client.get(f"/api/cases/{escaped_case}/field-data/manifest")
    assert escaped.status_code == 403
    assert "允许目录" in str(escaped.json()["detail"])


def _seed_result_bundle(container) -> dict[str, Any]:
    token = uuid.uuid4().hex[:12].upper()
    task_id = f"TSK-RD-{token}"
    case_id = f"CAS-RD-{token}"
    work_dir = container.settings.results_dir / task_id / case_id
    _insert_task_case(
        container,
        task_id=task_id,
        case_id=case_id,
        work_dir=work_dir,
    )
    series = {
        "x": list(range(5000)),
        "y": [round(index * 0.125, 6) for index in range(5000)],
        "name": "torque",
    }
    bundle = ResultBundle(
        provenance=ResultProvenance(
            task_id=task_id,
            case_id=case_id,
            solver_mode="mock",
            analysis="emag",
        ),
        results=[
            SeriesResult(
                result_id="torque_curve",
                label="Torque curve",
                unit="Nm",
                physical_domain="electromagnetic",
                viewer_modules=["curve"],
                data=series,
            )
        ],
        quality=ResultQuality(status="PASS", qualification_eligible=True),
    )
    stored = container.tasks.result_bundles.persist(bundle)
    return {
        "task_id": task_id,
        "case_id": case_id,
        "bundle": bundle,
        "stored": stored,
        "series": series,
    }


def test_result_data_chunkpack_random_access_etag_and_integrity(m5a_runtime):
    _, container, _, client = m5a_runtime
    seeded = _seed_result_bundle(container)
    stored = seeded["stored"]
    bundle_id = stored["id"]
    result_id = "torque_curve"
    stored_row = stored["bundle"]["results"][0]
    data_ref = stored_row["data_ref"]

    assert stored_row["data"] is None
    assert data_ref["encoding"] == CHUNKPACK_FORMAT
    assert data_ref["layout"] == "chunked"
    assert data_ref["random_access"] is True
    assert data_ref["chunk_count"] >= 3

    descriptor_url = f"/api/result-bundles/{bundle_id}/results/{result_id}/descriptor"
    descriptor = client.get(descriptor_url)
    assert descriptor.status_code == 200
    descriptor_payload = descriptor.json()
    assert descriptor_payload["authority"] == "ResultDataDescriptorV1"
    assert descriptor_payload["externalized"] is True
    assert descriptor_payload["layout"] == "chunked"
    assert descriptor_payload["chunk_native"] is True
    assert descriptor_payload["content_hash"] == data_ref["content_hash"]
    assert descriptor_payload["chunk_count"] == data_ref["chunk_count"]
    descriptor_etag = descriptor.headers["etag"]
    assert client.get(
        descriptor_url,
        headers={"If-None-Match": f'W/{descriptor_etag}, "other"'},
    ).status_code == 304

    manifest_url = descriptor_payload["manifest_url"]
    manifest = client.get(manifest_url)
    assert manifest.status_code == 200
    manifest_payload = manifest.json()["manifest"]
    assert manifest_payload["chunk_native"] is True
    assert manifest_payload["encoding"] == CHUNKPACK_FORMAT
    assert manifest_payload["chunk_count"] == data_ref["chunk_count"]
    assert manifest.headers["cache-control"].endswith("immutable")
    assert manifest.headers["x-mcs-results-application-contract"] == "1"
    manifest_etag = manifest.headers["etag"]
    assert client.get(
        manifest_url,
        headers={"If-None-Match": f'W/{manifest_etag}'},
    ).status_code == 304

    chunk_url = (
        f"/api/result-bundles/{bundle_id}/results/{result_id}/data/chunks/1"
    )
    chunk = client.get(chunk_url)
    assert chunk.status_code == 200
    chunk_payload = chunk.json()
    assert chunk_payload["data_authority"] == "ResultDataGatewayV2"
    assert chunk_payload["chunk"]["index"] == 1
    assert chunk_payload["chunk"]["chunk_hash"]
    assert len(chunk_payload["data"]["x"]) == chunk_payload["chunk"]["item_count"]
    chunk_etag = chunk.headers["etag"]
    assert client.get(
        chunk_url,
        headers={"If-None-Match": f'W/{chunk_etag}, "unused"'},
    ).status_code == 304

    window_url = (
        f"/api/result-bundles/{bundle_id}/results/{result_id}/data?offset=2050&limit=25"
    )
    window = client.get(window_url)
    assert window.status_code == 200
    window_payload = window.json()
    assert window_payload["window"]["chunk_native"] is True
    assert window_payload["window"]["offset"] == 2050
    assert window_payload["window"]["limit"] == 25
    assert window_payload["data"]["x"] == list(range(2050, 2075))
    assert window_payload["data"]["y"][0] == pytest.approx(256.25)
    window_etag = window.headers["etag"]
    assert client.get(
        window_url,
        headers={"If-None-Match": f'W/{window_etag}'},
    ).status_code == 304

    integrity = client.get(descriptor_payload["integrity_url"])
    assert integrity.status_code == 200
    assert integrity.json()["valid"] is True
    assert integrity.json()["encoding"] == CHUNKPACK_FORMAT

    # Conditional requests must not conceal local storage corruption. The gateway
    # verifies the addressed chunk before authorizing a 304 response.
    gateway = container.tasks.result_bundles.data_gateway
    chunk_descriptor = gateway.chunk_descriptor(data_ref["content_hash"], 1)
    chunk_path = gateway._chunk_path(
        str(chunk_descriptor["chunk_hash"]),
        str(chunk_descriptor.get("storage_key") or ""),
    )
    original_chunk = chunk_path.read_bytes()
    try:
        chunk_path.write_bytes(b"corrupted-m5a-chunk")
        corrupted_chunk = client.get(
            chunk_url,
            headers={"If-None-Match": f'W/{chunk_etag}'},
        )
        corrupted_window = client.get(
            window_url,
            headers={"If-None-Match": f'W/{window_etag}'},
        )
        corrupted_integrity = client.get(descriptor_payload["integrity_url"])
        assert corrupted_chunk.status_code == 409
        assert corrupted_window.status_code == 409
        assert corrupted_integrity.status_code == 200
        assert corrupted_integrity.json()["valid"] is False
    finally:
        chunk_path.write_bytes(original_chunk)
    assert gateway.verify(data_ref["content_hash"])["valid"] is True

    # Re-persisting the same engineering fact keeps the immutable content identity.
    replay = container.tasks.result_bundles.persist(seeded["bundle"])
    assert replay["id"] == bundle_id
    assert replay["content_hash"] == stored["content_hash"]
    assert replay["bundle"]["results"][0]["data_ref"]["content_hash"] == data_ref["content_hash"]

    fresh_gateway = ResultDataGateway(
        container.db,
        container.tasks.result_bundles.data_gateway.root,
    )
    assert fresh_gateway.read(data_ref["content_hash"]) == seeded["series"]
    assert fresh_gateway.content_hash(seeded["series"]) == data_ref["content_hash"]


def test_result_data_gc_removes_only_unreferenced_content(tmp_path: Path):
    db = Database(tmp_path / "runtime" / "studio.db")
    service = ResultBundleService(
        db,
        tmp_path / "results" / "result_data",
        inline_max_bytes=1,
        chunk_size_items=64,
    )
    token = uuid.uuid4().hex[:10].upper()
    task_id = f"TSK-GC-{token}"
    case_id = f"CAS-GC-{token}"
    now = db.now()
    db.execute(
        """INSERT INTO tasks(
               id,project_name,name,template_id,solver_mode,analysis,status,progress,
               current_stage,cancel_requested,request_json,created_at,updated_at,case_count
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            "GC Project",
            "GC Task",
            "a1",
            "mock",
            "emag",
            "COMPLETED",
            100.0,
            "COMPLETED",
            0,
            db.dumps({}),
            now,
            now,
            1,
        ),
    )
    db.execute(
        """INSERT INTO cases(
               id,task_id,case_index,status,progress,parameters_json,result_json,
               work_dir,updated_at,execution_status,quality_status
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            case_id,
            task_id,
            0,
            "COMPLETED",
            100.0,
            db.dumps({}),
            db.dumps({}),
            str(tmp_path / "results" / task_id / case_id),
            now,
            "COMPLETED",
            "PASS",
        ),
    )
    referenced_data = {"x": list(range(256)), "y": list(range(256))}
    bundle = ResultBundle(
        provenance=ResultProvenance(
            task_id=task_id,
            case_id=case_id,
            solver_mode="mock",
            analysis="emag",
        ),
        results=[
            SeriesResult(
                result_id="referenced",
                label="Referenced",
                data=referenced_data,
            )
        ],
    )
    persisted = service.persist(bundle)
    referenced_hash = persisted["bundle"]["results"][0]["data_ref"]["content_hash"]
    orphan_ref = service.data_gateway.put(
        {"x": list(range(320)), "y": [value * 2 for value in range(320)]},
        logical_type="series",
    )
    service.data_gateway.gc_grace_seconds = 0

    dry_run = service.data_gateway.garbage_collect(dry_run=True)
    assert dry_run["registered_orphan_count"] >= 1
    assert dry_run["candidate_count"] >= 1
    assert dry_run["reclaimable_stored_bytes"] > 0
    assert service.data_gateway.available(referenced_hash) is True
    assert service.data_gateway.available(orphan_ref.content_hash) is True

    collected = service.data_gateway.garbage_collect(dry_run=False)
    assert orphan_ref.content_hash in collected["removed_hashes"]
    assert collected["removed_count"] >= 1
    assert service.data_gateway.available(orphan_ref.content_hash) is False
    assert service.data_gateway.available(referenced_hash) is True
    assert service.data_gateway.verify(referenced_hash)["valid"] is True


def test_transfer_budget_bounds_concurrency_and_materialized_payloads():
    budget = TransferBudget(
        name="m5a-test",
        max_concurrent=1,
        acquire_timeout_s=0.05,
        max_response_bytes=1024 * 1024,
    )
    entered = threading.Event()
    release = threading.Event()

    def hold_lease() -> None:
        with budget.lease("hold"):
            entered.set()
            release.wait(timeout=3.0)

    thread = threading.Thread(target=hold_lease, daemon=True)
    thread.start()
    assert entered.wait(timeout=2.0)
    with pytest.raises(TransferBudgetExceeded) as exhausted:
        with budget.lease("blocked"):
            pass
    assert exhausted.value.operation == "blocked"
    release.set()
    thread.join(timeout=3.0)
    assert not thread.is_alive()

    with pytest.raises(TransferPayloadTooLarge) as oversized:
        budget.enforce_response_size("oversized", b"x" * (1024 * 1024 + 1))
    assert oversized.value.max_response_bytes == 1024 * 1024
    assert oversized.value.size_bytes == 1024 * 1024 + 1

    snapshot = budget.snapshot()
    assert snapshot["authority"] == "HeavyDataTransferBudgetV2"
    assert snapshot["active"] == 0
    assert snapshot["peak_active"] == 1
    assert snapshot["admitted"] == 1
    assert snapshot["completed"] == 1
    assert snapshot["rejected"] == 1
    assert snapshot["oversized"] == 1


def test_application_ports_and_domain_remain_infrastructure_free():
    package_root = Path(__file__).resolve().parents[1] / "motorcad_studio" / "modules"
    forbidden = (
        "from ....db import Database",
        "from ...db import Database",
        "import sqlite",
        "from pathlib import Path",
        "ServiceContainer",
    )
    violations: list[str] = []
    for bounded_context in ("results", "field_data"):
        for layer in ("application", "ports", "domain"):
            for path in (package_root / bounded_context / layer).rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                for token in forbidden:
                    if token in text:
                        violations.append(
                            f"{path.relative_to(package_root)} contains {token}"
                        )
    assert violations == []


def test_fea_worker_builds_transferable_typed_geometry_and_viewer_cleans_up():
    root = Path(__file__).resolve().parents[1]
    worker = root / "motorcad_studio" / "static" / "results" / "field-worker.js"
    legacy_viewer = root / "motorcad_studio" / "frontend_legacy" / "results" / "field-viewer.js"
    binary_viewer = root / "motorcad_studio" / "static" / "features" / "results" / "binary-field-viewer.js"
    subprocess.run(["node", "--check", str(worker)], check=True, capture_output=True, text=True)
    subprocess.run(["node", "--check", str(legacy_viewer)], check=True, capture_output=True, text=True)
    subprocess.run(["node", "--check", str(binary_viewer)], check=True, capture_output=True, text=True)

    node_script = r"""
const fs = require('fs');
const vm = require('vm');
const { performance } = require('perf_hooks');
const workerPath = process.argv[1];
const sandbox = { performance, captured: null, transfer: null };
sandbox.self = {
  postMessage(message, transfer) {
    sandbox.captured = message;
    sandbox.transfer = transfer;
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(workerPath, 'utf8'), sandbox, {filename: workerPath});
vm.runInContext(`
  self.onmessage({data:{
    type:'build', id:'geometry-test',
    frame:{
      nodeMap:new Map([
        ['1',{id:'1',x:0,y:0,z:0}],
        ['2',{id:'2',x:1,y:0,z:0}],
        ['3',{id:'3',x:0,y:1,z:0}],
        ['4',{id:'4',x:1,y:1,z:0}]
      ]),
      elements:[
        {id:'e1',node_ids:['1','2','3'],region:'stator',b:1},
        {id:'e2',node_ids:['2','4','3'],region:'rotor',b:2}
      ]
    },
    options:{field:'b',region:'',mode:'physical',heightScale:0.4,minimum:0,maximum:2}
  }});
`, sandbox);
const result = sandbox.captured;
const output = {
  ok: Boolean(result && result.ok),
  id: result && result.id,
  triangleCount: result && result.scene && result.scene.triangleCount,
  sourceElementCount: result && result.scene && result.scene.sourceElementCount,
  fillType: result && result.scene && result.scene.fill.positions.constructor.name,
  fillLength: result && result.scene && result.scene.fill.positions.length,
  transferCount: Array.isArray(sandbox.transfer) ? sandbox.transfer.length : 0,
  transferAreBuffers: Array.isArray(sandbox.transfer) && sandbox.transfer.every(value => Object.prototype.toString.call(value) === '[object ArrayBuffer]'),
};
process.stdout.write(JSON.stringify(output));
"""
    completed = subprocess.run(
        ["node", "-e", node_script, str(worker)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["id"] == "geometry-test"
    assert result["triangleCount"] >= 2
    assert result["sourceElementCount"] == 2
    assert result["fillType"] == "Float32Array"
    assert result["fillLength"] > 0
    assert result["transferCount"] == 9
    assert result["transferAreBuffers"] is True

    legacy_source = legacy_viewer.read_text(encoding="utf-8")
    for token in (
        "/field-data/manifest",
        "/field-data/frames/",
        "new Worker(",
        ".terminate()",
        "AbortController",
        "Float32Array",
        "disposeNativeField",
    ):
        assert token in legacy_source

    binary_source = binary_viewer.read_text(encoding="utf-8")
    for token in (
        "/binary-manifest",
        "Range",
        "topology_hash",
        "scalarOnlyUpdates",
        "webglcontextlost",
        "webglcontextrestored",
        "gl.deleteBuffer",
        "gl.deleteVertexArray",
        "gl.deleteProgram",
    ):
        assert token in binary_source



def test_binary_field_data_manifest_ranges_etag_and_cache_repair(m5a_runtime):
    _, container, _, client = m5a_runtime
    seeded = _seed_field_data(container)
    case_id = seeded["case_id"]
    manifest_url = f"/api/cases/{case_id}/field-data/frames/0/binary-manifest?field=b"
    binary_url = f"/api/cases/{case_id}/field-data/frames/0/binary?field=b"

    manifest_response = client.get(manifest_url)
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["authority"] == "MotorCADFieldDataBinaryV1"
    assert manifest["format_version"] == 1
    assert manifest["vertex_count"] == 4
    assert manifest["triangle_count"] == 2
    assert manifest["range_requests"] is True
    assert manifest["topology_reuse"] is True
    assert manifest["scalar_only_frame_update"] is True
    assert manifest_response.headers["x-mcs-field-data-binary"] == "1"

    full = client.get(binary_url)
    assert full.status_code == 200
    payload = full.content
    assert len(payload) == manifest["size_bytes"]
    assert hashlib.sha256(payload).hexdigest() == manifest["payload_sha256"]
    header = decode_header(payload)
    assert header["topology_hash"] == manifest["topology_hash"]
    assert header["scalar_hash"] == manifest["scalar_hash"]
    arrays = header["arrays"]
    assert arrays["positions"]["count"] == 4
    assert arrays["indices"]["count"] == 6
    assert arrays["scalars"]["count"] == 4

    etag = full.headers["etag"]
    assert client.get(binary_url, headers={"If-None-Match": f'W/{etag}, "other"'}).status_code == 304

    topology_start = int(arrays["positions"]["offset"])
    topology_end = int(arrays["indices"]["offset"]) + int(arrays["indices"]["byte_length"]) - 1
    topology = client.get(binary_url, headers={"Range": f"bytes={topology_start}-{topology_end}"})
    assert topology.status_code == 206
    assert topology.headers["content-range"] == f"bytes {topology_start}-{topology_end}/{len(payload)}"
    assert hashlib.sha256(topology.content).hexdigest() == manifest["topology_hash"]

    scalar_start = int(arrays["scalars"]["offset"])
    scalar_end = scalar_start + int(arrays["scalars"]["byte_length"]) - 1
    scalars = client.get(binary_url, headers={"Range": f"bytes={scalar_start}-{scalar_end}"})
    assert scalars.status_code == 206
    assert hashlib.sha256(scalars.content).hexdigest() == manifest["scalar_hash"]

    suffix = client.get(binary_url, headers={"Range": "bytes=-16"})
    assert suffix.status_code == 206
    assert suffix.content == payload[-16:]
    invalid = client.get(binary_url, headers={"Range": f"bytes={len(payload)}-"})
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{len(payload)}"

    # Corrupt the materialized cache. A conditional request must validate and
    # repair it before returning 304, so a stale browser cache cannot hide damage.
    binary_root = seeded["root"] / "binary_frames"
    cache_file = next(binary_root.glob("*.mcfd"))
    cache_file.write_bytes(b"corrupted")
    repaired = client.get(binary_url, headers={"If-None-Match": etag})
    assert repaired.status_code == 304
    assert hashlib.sha256(cache_file.read_bytes()).hexdigest() == manifest["payload_sha256"]


def test_binary_frame_topology_hash_is_reused_when_only_scalars_change():
    positions = array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0])
    indices = array("I", [0, 1, 2, 1, 3, 2])
    first, first_manifest = encode_frame(
        positions,
        indices,
        array("f", [0.1, 0.2, 0.3, 0.4]),
        metadata={"field": "b"},
        source_hash="1" * 64,
        frame_index=0,
    )
    second, second_manifest = encode_frame(
        positions,
        indices,
        array("f", [0.2, 0.3, 0.4, 0.5]),
        metadata={"field": "b"},
        source_hash="2" * 64,
        frame_index=1,
    )
    assert first_manifest["topology_hash"] == second_manifest["topology_hash"]
    assert first_manifest["scalar_hash"] != second_manifest["scalar_hash"]
    assert first_manifest["frame_hash"] != second_manifest["frame_hash"]
    assert decode_header(first)["frame_index"] == 0
    assert decode_header(second)["frame_index"] == 1
