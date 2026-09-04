from __future__ import annotations

import asyncio
import hashlib
import os
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ....bootstrap.container import ServiceContainer
from ....fea_views import build_fea_frame_view
from ....native_spatial import NativeSpatialResultOverlayAuthority
from ....native_tables import cached_file_sha256, file_sha256, read_native_table_page


class FieldDataCompatibilityAdapter:
    """Verified native FEA/file adapter used by the FieldData application module."""

    def __init__(self, container: ServiceContainer) -> None:
        self.settings = container.settings
        self.db = container.db
        self.tasks = container.tasks
        self.max_json_source_bytes = max(8 * 1024 * 1024, int(os.getenv("MOTORCAD_STUDIO_FIELD_DATA_MAX_SOURCE_BYTES") or 512 * 1024 * 1024))
    def _case_native_fea_root(self, case_id: str) -> tuple[dict[str, Any], Path]:
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        row = db.query_one('SELECT id,task_id,work_dir FROM cases WHERE id=?', (case_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Case不存在')
        if not row.get('work_dir'):
            raise HTTPException(status_code=404, detail='Case尚无运行目录')
        root = (Path(row['work_dir']) / 'native_fea').resolve()
        results_root = settings.results_dir.resolve()
        if results_root != root and results_root not in root.parents:
            raise HTTPException(status_code=403, detail='FEA证据路径不在允许目录')
        return (row, root)

    def _case_post_solve_native_model_snapshot(self, case_id: str, row: dict[str, Any] | None=None) -> dict[str, Any]:
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        case = row or db.query_one('SELECT id,task_id,work_dir,result_json FROM cases WHERE id=?', (case_id,))
        if not case:
            raise HTTPException(status_code=404, detail='Case不存在')
        result = db.loads(case.get('result_json'), {}) or {}
        raw = dict(result.get('raw') or {}) if isinstance(result, dict) else {}
        snapshot = raw.get('native_model_snapshot_post_solve') or raw.get('native_model_snapshot')
        if isinstance(snapshot, dict) and snapshot:
            return snapshot
        work_dir = case.get('work_dir')
        if work_dir:
            path = (Path(work_dir) / 'native_model_snapshot_post_solve.json').resolve()
            results_root = settings.results_dir.resolve()
            if results_root == path or results_root in path.parents:
                if path.exists():
                    try:
                        payload = json.loads(path.read_text(encoding='utf-8'))
                    except Exception as exc:
                        raise HTTPException(status_code=500, detail=f'NativeModelSnapshot损坏: {type(exc).__name__}: {exc}') from exc
                    if isinstance(payload, dict) and payload:
                        return payload
        raise HTTPException(status_code=404, detail='当前 Case 尚无 post_solve NativeModelSnapshot')

    def _verified_fea_frame(self, root: Path, record: dict[str, Any]) -> tuple[Path, str, str | None]:
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        frame = (root / 'frames' / str(record.get('file'))).resolve()
        if root not in frame.parents or not frame.exists():
            raise HTTPException(status_code=404, detail='FEA帧文件已丢失')
        expected_size = int(record.get('size_bytes') or 0)
        expected_hash = str(record.get('sha256') or '')
        if expected_size and frame.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='FEA帧完整性校验失败：文件大小与归档清单不一致')
        self._guard_json_source(frame)
        if expected_hash:
            actual_hash = cached_file_sha256(frame)
            if actual_hash != expected_hash:
                raise HTTPException(status_code=409, detail='FEA帧完整性校验失败：SHA-256 与归档清单不一致')
            return (frame, 'VERIFIED', expected_hash)
        return (frame, 'UNVERIFIED_LEGACY', None)

    def _verified_fea_viewer_manifest(self, root: Path, record: dict[str, Any]) -> tuple[Path, str]:
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        relative = str(record.get('viewer_manifest_file') or '')
        if not relative:
            raise HTTPException(status_code=404, detail='该 FEA 帧没有完整网格查看器清单')
        path = (root / relative).resolve()
        viewer_root = (root / 'viewer_frames').resolve()
        if viewer_root != path and viewer_root not in path.parents:
            raise HTTPException(status_code=403, detail='FEA完整网格清单路径不在允许目录')
        if not path.exists():
            raise HTTPException(status_code=404, detail='FEA完整网格清单已丢失')
        expected_size = int(record.get('viewer_manifest_size_bytes') or 0)
        expected_hash = str(record.get('viewer_manifest_sha256') or '')
        if expected_size and path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='FEA完整网格清单大小校验失败')
        self._guard_json_source(path)
        digest = cached_file_sha256(path)
        if expected_hash and digest != expected_hash:
            raise HTTPException(status_code=409, detail='FEA完整网格清单 SHA-256 校验失败')
        return (path, digest)

    def _verified_fea_viewer_chunk(self, manifest_path: Path, chunk: dict[str, Any]) -> tuple[Path, str]:
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        path = (manifest_path.parent / str(chunk.get('file') or '')).resolve()
        if manifest_path.parent != path and manifest_path.parent not in path.parents:
            raise HTTPException(status_code=403, detail='FEA网格分块路径不在允许目录')
        if not path.exists():
            raise HTTPException(status_code=404, detail='FEA网格分块已丢失')
        expected_size = int(chunk.get('size_bytes') or 0)
        expected_hash = str(chunk.get('sha256') or '')
        if expected_size and path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='FEA网格分块大小校验失败')
        self._guard_json_source(path)
        digest = cached_file_sha256(path)
        if expected_hash and digest != expected_hash:
            raise HTTPException(status_code=409, detail='FEA网格分块 SHA-256 校验失败')
        return (path, digest)

    def _verified_native_table(self, case_id: str, output_id: str) -> tuple[Path, dict[str, Any]]:
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        row, fea_root = _case_native_fea_root(case_id)
        root = (fea_root.parent / 'native_tables').resolve()
        manifest_path = root / 'native_table_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='当前 Case 尚无原生表格清单')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'原生表格清单无法解析: {type(exc).__name__}') from exc
        record = (manifest.get('tables') or {}).get(output_id)
        if not isinstance(record, dict):
            raise HTTPException(status_code=404, detail='原生表格不存在')
        path = (root / str(record.get('source_file') or '')).resolve()
        work_root = Path(str(row.get('work_dir') or '')).resolve()
        if work_root not in path.parents or root not in path.parents:
            raise HTTPException(status_code=403, detail='原生表格路径不在允许目录')
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail='原生表格文件已丢失')
        expected_size = int(record.get('source_size_bytes') or 0)
        expected_hash = str(record.get('source_sha256') or '')
        if expected_size and path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='原生表格完整性校验失败：文件大小不一致')
        if expected_hash and cached_file_sha256(path) != expected_hash:
            raise HTTPException(status_code=409, detail='原生表格完整性校验失败：SHA-256 不一致')
        return (path, record)

    def case_fea_evidence(self, case_id: str):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        row, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            native_screen = (root.parent / 'native_screens' / 'fea_results.png').resolve()
            return {'case_id': case_id, 'task_id': row['task_id'], 'available': False, 'status': 'NOT_EXPORTED', 'native_screen_available': native_screen.exists(), 'native_screen_url': f'/api/cases/{case_id}/native-screen' if native_screen.exists() else None}
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'FEA证据清单损坏: {type(exc).__name__}: {exc}') from exc
        normalization = manifest.get('normalization') or {}
        capabilities = dict(normalization.get('capabilities') or {})
        capabilities.setdefault('raw_download', bool(manifest.get('raw_size_bytes')))
        native_screen = (root.parent / 'native_screens' / 'fea_results.png').resolve()
        frames = normalization.get('frames') if isinstance(normalization.get('frames'), list) else []
        registered_frames = sum((isinstance(frame.get('sha256'), str) and len(frame['sha256']) == 64 and (int(frame.get('size_bytes') or 0) > 0) for frame in frames))
        return {'case_id': case_id, 'task_id': row['task_id'], 'available': True, 'status': manifest.get('status'), 'authority': manifest.get('authority'), 'motorcad_version': manifest.get('motorcad_version'), 'source_mot_sha256': manifest.get('source_mot_sha256'), 'raw_size_bytes': manifest.get('raw_size_bytes'), 'raw_sha256': manifest.get('raw_sha256'), 'first_step': manifest.get('first_step'), 'final_step': manifest.get('final_step'), 'normalization': normalization, 'validation': manifest.get('validation') or {}, 'policy': manifest.get('policy'), 'contract_id': manifest.get('contract_id'), 'capabilities': capabilities, 'integrity': {'status': 'REGISTERED' if registered_frames == len(frames) and frames else 'UNVERIFIED_LEGACY', 'algorithm': 'sha256' if registered_frames else None, 'registered_frame_count': registered_frames, 'frame_count': len(frames), 'verification_policy': 'serve_and_probe_time'}, 'native_screen_available': native_screen.exists(), 'native_screen_url': f'/api/cases/{case_id}/native-screen' if native_screen.exists() else None, 'spatial_overlay': manifest.get('spatial_overlay') or {}, 'spatial_overlay_url': f'/api/cases/{case_id}/spatial-overlay', 'evidence_boundary': '场值仅来自 Motor-CAD save_fea_data 原生导出；V0.89-G3.3 在原生三节点连接完整时按全部三角单元直接填色并绘制网格边线，不对缺失连接或缺失场值进行插值伪造。'}

    def case_spatial_overlay(self, case_id: str):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        row, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='当前 Case 尚无 Motor-CAD FEA 导出证据')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'FEA证据清单损坏: {type(exc).__name__}: {exc}') from exc
        case_row = db.query_one('SELECT id,task_id,work_dir,result_json FROM cases WHERE id=?', (case_id,)) or row
        snapshot = _case_post_solve_native_model_snapshot(case_id, case_row)
        contract = NativeSpatialResultOverlayAuthority().build(native_model_snapshot=snapshot, fea_manifest=manifest)
        contract['case_id'] = case_id
        contract['task_id'] = row.get('task_id')
        contract['frame_endpoint'] = f'/api/cases/{case_id}/fea-frames/{{frame_index}}'
        return contract

    def case_native_screen(self, case_id: str):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        row, root = _case_native_fea_root(case_id)
        path = (root.parent / 'native_screens' / 'fea_results.png').resolve()
        work_root = Path(str(row.get('work_dir') or '')).resolve()
        if work_root != path and work_root not in path.parents:
            raise HTTPException(status_code=403, detail='原生画面路径不在允许目录')
        if not path.exists():
            raise HTTPException(status_code=404, detail='当前 Case 尚无 Motor-CAD 原生画面')
        screen_manifest = path.parent / 'native_screen_manifest.json'
        if screen_manifest.exists():
            try:
                expected = str(json.loads(screen_manifest.read_text(encoding='utf-8')).get('sha256') or '')
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=409, detail=f'原生画面清单无法验证: {type(exc).__name__}') from exc
            if expected and cached_file_sha256(path) != expected:
                raise HTTPException(status_code=409, detail='原生画面完整性校验失败：SHA-256 不一致')
        return FileResponse(path, filename=f'{case_id}_motorcad_fea.png', media_type='image/png')

    async def case_fea_stream(self, case_id: str):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        row = db.query_one('SELECT cases.id,cases.task_id,cases.work_dir,cases.status,tasks.current_stage\n                 FROM cases LEFT JOIN tasks ON tasks.id=cases.task_id WHERE cases.id=?', (case_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Case不存在')
    
        async def stream():
            last_signature = ''
            idle_cycles = 0
            while idle_cycles < 600:
                case = db.query_one('SELECT c.id,c.task_id,c.status,c.progress,c.updated_at,t.current_stage\n                         FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?', (case_id,)) or {}
                try:
                    evidence = case_fea_evidence(case_id)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    evidence = {'case_id': case_id, 'available': False, 'status': 'WAITING_FOR_WORK_DIR', 'native_screen_url': None, 'authority': None}
                frames = (evidence.get('normalization') or {}).get('frames') or [] if evidence.get('available') else []
                payload = {'event': 'FEA_DATA_FRAME' if frames else 'SOLVE_STAGE_CHANGED', 'case_id': case_id, 'status': case.get('status'), 'stage': case.get('current_stage'), 'progress': case.get('progress'), 'frame_count': len(frames), 'latest_frame_index': int(frames[-1].get('index')) if frames else None, 'native_screen_url': evidence.get('native_screen_url'), 'authority': evidence.get('authority'), 'updated_at': case.get('updated_at')}
                signature = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()
                if signature != last_signature:
                    last_signature = signature
                    yield f"event: {payload['event']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    idle_cycles = 0
                else:
                    idle_cycles += 1
                    if idle_cycles % 15 == 0:
                        yield ': heartbeat\n\n'
                if str(case.get('status') or '') in {'COMPLETED', 'FAILED', 'CANCELLED', 'PARTIALLY_COMPLETED'}:
                    yield f'event: ANALYSIS_COMPLETED\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
                    break
                await asyncio.sleep(1.0)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    def case_fea_frame(self, case_id: str, frame_index: int, request: Request):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        _, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frames = (manifest.get('normalization') or {}).get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        frame, integrity_status, digest = _verified_fea_frame(root, record)
        etag = f'"{digest}"' if digest else None
        if etag and self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers={'ETag': etag})
        try:
            payload = json.loads(frame.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA帧内容无法解析: {type(exc).__name__}') from exc
        payload['integrity'] = {'status': integrity_status, 'sha256': digest}
        headers = {'Cache-Control': 'private, max-age=31536000, immutable'}
        if etag:
            headers['ETag'] = etag
        return JSONResponse(payload, headers=headers)

    def case_fea_mesh_manifest(self, case_id: str, frame_index: int, request: Request):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        _, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frames = (manifest.get('normalization') or {}).get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        path, digest = _verified_fea_viewer_manifest(root, record)
        etag = f'"{digest}"'
        response_headers = {
            'ETag': etag,
            'Cache-Control': 'private, max-age=31536000, immutable',
            'X-MCS-Field-Data-Contract': '1',
        }
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=response_headers)
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA完整网格清单无法解析: {type(exc).__name__}') from exc
        payload['integrity'] = {'status': 'VERIFIED', 'sha256': digest}
        payload['field_data_contract'] = {
            'authority': 'FieldDataMeshManifestV1',
            'contract_version': '1',
            'frame_index': frame_index,
            'topology_hash': digest,
        }
        payload['chunk_endpoint'] = f'/api/cases/{case_id}/field-data/frames/{frame_index}/mesh-chunks/{{chunk_index}}'
        payload['legacy_chunk_endpoint'] = f'/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{{chunk_index}}'
        return JSONResponse(payload, headers=response_headers)

    def case_fea_mesh_chunk(self, case_id: str, frame_index: int, chunk_index: int, request: Request):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        _, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frames = (manifest.get('normalization') or {}).get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        viewer_manifest_path, _ = _verified_fea_viewer_manifest(root, record)
        try:
            viewer_manifest = json.loads(viewer_manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA完整网格清单无法解析: {type(exc).__name__}') from exc
        chunk = next((row for row in viewer_manifest.get('chunks') or [] if int(row.get('index', -1)) == int(chunk_index)), None)
        if not chunk:
            raise HTTPException(status_code=404, detail='FEA网格分块不存在')
        path, digest = _verified_fea_viewer_chunk(viewer_manifest_path, chunk)
        etag = f'"{digest}"'
        response_headers = {
            'ETag': etag,
            'Cache-Control': 'private, max-age=31536000, immutable',
            'X-MCS-Field-Data-Contract': '1',
            'X-MCS-Field-Data-Chunk': str(chunk_index),
        }
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=response_headers)
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA网格分块无法解析: {type(exc).__name__}') from exc
        payload['integrity'] = {'status': 'VERIFIED', 'sha256': digest}
        payload['field_data_contract'] = {
            'authority': 'FieldDataMeshChunkV1',
            'contract_version': '1',
            'frame_index': frame_index,
            'chunk_index': chunk_index,
        }
        return JSONResponse(payload, headers=response_headers)

    def case_fea_frame_view(self, case_id: str, frame_index: int, request: Request, field: str=Query(default='b', pattern='^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$'), region: str | None=Query(default=None, max_length=160), max_points: int=Query(default=12000, ge=250, le=20000), xmin: float | None=Query(default=None), xmax: float | None=Query(default=None), ymin: float | None=Query(default=None), ymax: float | None=Query(default=None)):
        """Return a verified, field-specific FEA level-of-detail view.
    
            The immutable frame stays the evidence source.  This endpoint only reduces
            transfer and browser parsing work; every response retains extrema/region
            coverage metadata and the source frame digest.
            """
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        bounds_values = (xmin, xmax, ymin, ymax)
        if any((value is not None for value in bounds_values)) and (not all((value is not None for value in bounds_values))):
            raise HTTPException(status_code=422, detail='视口边界必须同时提供 xmin、xmax、ymin、ymax')
        bounds = tuple((float(value) for value in bounds_values)) if all((value is not None for value in bounds_values)) else None
        if bounds and (bounds[0] >= bounds[1] or bounds[2] >= bounds[3]):
            raise HTTPException(status_code=422, detail='FEA 视口边界无效')
        _, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA清单无法解析: {type(exc).__name__}') from exc
        normalization = manifest.get('normalization') or {}
        if field not in (normalization.get('available_fields') or []):
            raise HTTPException(status_code=422, detail=f'当前原生导出不包含字段: {field}')
        frames = normalization.get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        frame_path, integrity_status, digest = _verified_fea_frame(root, record)
        try:
            source_payload = json.loads(frame_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA帧内容无法解析: {type(exc).__name__}') from exc
        try:
            payload = build_fea_frame_view(source_payload, field=field, region=region, max_points=max_points, bounds=bounds)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        query_contract = json.dumps({'digest': digest, 'field': field, 'region': region, 'max_points': max_points, 'bounds': bounds}, sort_keys=True, separators=(',', ':'))
        view_digest = hashlib.sha256(query_contract.encode('utf-8')).hexdigest()
        etag = f'"{view_digest}"'
        if self._etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers={'ETag': etag})
        payload['integrity'] = {'status': integrity_status, 'source_sha256': digest, 'view_contract_sha256': view_digest}
        payload['transfer'] = {'contract': 'verified_progressive_fea_v1', 'source_frame_size_bytes': int(record.get('size_bytes') or 0), 'source_frame_point_count': int(record.get('point_count') or 0)}
        return JSONResponse(payload, headers={'Cache-Control': 'private, max-age=31536000, immutable', 'ETag': etag, 'X-FEA-View-Points': str(payload.get('point_count') or 0)})

    def case_fea_probe(self, case_id: str, frame_index: int=Query(default=0, ge=0), x: float=Query(...), y: float=Query(...), field: str=Query(default='b', pattern='^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$'), region: str | None=Query(default=None)):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        _, root = _case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        normalization = manifest.get('normalization') or {}
        available_fields = normalization.get('available_fields') or []
        if field not in available_fields:
            raise HTTPException(status_code=422, detail=f'当前原生导出不包含字段: {field}')
        frames = normalization.get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        frame_path, integrity_status, digest = _verified_fea_frame(root, record)
        try:
            frame_payload = json.loads(frame_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA帧内容无法解析: {type(exc).__name__}') from exc
        points = [point for point in frame_payload.get('points') or [] if point.get(field) is not None and (region is None or str(point.get('region')) == region)]
        if not points:
            raise HTTPException(status_code=404, detail='所选字段/区域没有可探测的原生数据点')
        nearest = min(points, key=lambda point: (float(point['x']) - x) ** 2 + (float(point['y']) - y) ** 2)
        distance = ((float(nearest['x']) - x) ** 2 + (float(nearest['y']) - y) ** 2) ** 0.5
        return {'case_id': case_id, 'frame_index': frame_index, 'field': field, 'requested': {'x': x, 'y': y, 'region': region}, 'nearest': nearest, 'value': nearest.get(field), 'distance': distance, 'authority': 'motorcad_native_export_nearest_point', 'integrity': {'status': integrity_status, 'sha256': digest}}

    def case_fea_raw(self, case_id: str):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        _, root = _case_native_fea_root(case_id)
        raw = root / 'native_fea_raw.csv'
        if not raw.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA原始导出')
        manifest_path = root / 'native_fea_manifest.json'
        if manifest_path.exists():
            try:
                expected = str(json.loads(manifest_path.read_text(encoding='utf-8')).get('raw_sha256') or '')
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=409, detail=f'FEA原始文件清单无法验证: {type(exc).__name__}') from exc
            if expected and cached_file_sha256(raw) != expected:
                raise HTTPException(status_code=409, detail='FEA原始文件完整性校验失败：SHA-256 不一致')
        return FileResponse(raw, filename=f'{case_id}_native_fea.csv', media_type='text/csv')

    def case_native_table_rows(self, case_id: str, output_id: str, offset: int=Query(default=0, ge=0), limit: int=Query(default=200, ge=1, le=500)):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        path, record = _verified_native_table(case_id, output_id)
        page, error = read_native_table_page(path, columns=list(record.get('columns') or []), delimiter=str(record.get('delimiter') or ','), offset=offset, limit=limit)
        if error or page is None:
            raise HTTPException(status_code=409, detail=f"原生表格分页读取失败：{error or 'unknown'}")
        page.update({'case_id': case_id, 'output_id': output_id, 'source_row_count': int(record.get('source_row_count') or 0), 'integrity': {'status': 'VERIFIED', 'source_sha256': record.get('source_sha256')}})
        return page

    def case_native_table(self, case_id: str, output_id: str):
        settings = self.settings
        db = self.db
        tasks = self.tasks
        _case_native_fea_root = self._case_native_fea_root
        _case_post_solve_native_model_snapshot = self._case_post_solve_native_model_snapshot
        _verified_fea_frame = self._verified_fea_frame
        _verified_fea_viewer_manifest = self._verified_fea_viewer_manifest
        _verified_fea_viewer_chunk = self._verified_fea_viewer_chunk
        _verified_native_table = self._verified_native_table
        case_fea_evidence = self.case_fea_evidence
        path, _ = _verified_native_table(case_id, output_id)
        return FileResponse(path, filename=f'{case_id}_{path.name}', media_type='text/csv')


    OPERATIONS = frozenset({
        "case_fea_evidence", "case_spatial_overlay", "case_native_screen",
        "case_fea_stream", "case_fea_frame", "case_fea_mesh_manifest",
        "case_fea_mesh_chunk", "case_fea_frame_view", "case_fea_probe",
        "case_fea_raw", "case_native_table_rows", "case_native_table",
        "field_data_manifest", "field_data_frame_lod", "field_data_integrity",
    })

    def operation(self, name: str):
        if name not in self.OPERATIONS:
            raise KeyError(f"Unknown FieldData operation: {name}")
        target = getattr(self, name, None)
        if not callable(target):
            raise RuntimeError(f"FieldData operation is not callable: {name}")
        return target

    def module_snapshot(self) -> dict[str, Any]:
        return {
            "authority": "FieldDataCompatibilityAdapterV1",
            "operation_count": len(self.OPERATIONS),
            "contract_version": "1",
            "source_authority": "motorcad_native_export",
            "integrity_algorithm": "sha256",
            "lod_levels": [0, 1, 2],
            "max_json_source_bytes": self.max_json_source_bytes,
            "progressive_chunks": True,
        }

    def _guard_json_source(self, path: Path) -> None:
        size = path.stat().st_size
        if size > self.max_json_source_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "FIELD_DATA_SOURCE_TOO_LARGE",
                    "message": "FEA JSON source exceeds the configured decode budget",
                    "size_bytes": size,
                    "max_source_bytes": self.max_json_source_bytes,
                },
            )

    @staticmethod
    def _etag_matches(header: str | None, etag: str) -> bool:
        if not header:
            return False
        target = etag.strip('"')
        for token in header.split(','):
            candidate = token.strip()
            if candidate.startswith('W/'):
                candidate = candidate[2:].strip()
            if candidate == '*' or candidate.strip('"') == target:
                return True
        return False

    def _manifest_payload(self, case_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
        row, root = self._case_native_fea_root(case_id)
        path = root / "native_fea_manifest.json"
        if not path.exists():
            return row, {}, root
        self._guard_json_source(path)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f"FEA证据清单无法解析: {type(exc).__name__}") from exc
        return row, manifest, root

    def field_data_manifest(self, case_id: str, request: Request):
        row, manifest, root = self._manifest_payload(case_id)
        if not manifest:
            evidence = self.case_fea_evidence(case_id)
            payload = {
                "authority": "FieldDataManifestV1",
                "contract_version": "1",
                "case_id": case_id,
                "task_id": row.get("task_id"),
                "available": False,
                "status": str(evidence.get("status") or "NOT_EXPORTED"),
                "etag": '"missing"',
                "coordinate_system": {
                    "authority": "FieldCoordinateSystemV1",
                    "axes": ["x", "y", "z"],
                    "length_unit": None,
                    "source": "motorcad_native_export",
                    "physical_z": False,
                    "planar_compatibility": True,
                },
                "available_fields": [],
                "regions": [],
                "frames": [],
                "full_mesh_available": False,
                "transfer_policy": {
                    "lod_levels": [0, 1, 2],
                    "lod_2_mode": "chunked_manifest",
                    "conditional_requests": True,
                },
                "integrity": evidence.get("integrity") or {},
                "compatibility": {"legacy_evidence": evidence},
            }
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})

        normalization = manifest.get("normalization") or {}
        frames = normalization.get("frames") if isinstance(normalization.get("frames"), list) else []
        capabilities = normalization.get("capabilities") or {}
        frame_rows: list[dict[str, Any]] = []
        physical_z = False
        for offset, record in enumerate(frames):
            frame_index = int(record.get("index", offset))
            bounds = record.get("viewer_data_bounds") or record.get("data_bounds") or []
            if isinstance(bounds, list) and len(bounds) >= 6:
                physical_z = physical_z or abs(float(bounds[5]) - float(bounds[4])) > 1e-12
            source_hash = str(record.get("sha256") or "") or None
            topology_hash = str(record.get("viewer_manifest_sha256") or source_hash or "") or None
            frame_rows.append({
                "frame_index": frame_index,
                "step": record.get("step"),
                "source_sha256": source_hash,
                "source_size_bytes": int(record.get("size_bytes") or 0),
                "point_count": int(record.get("point_count") or record.get("source_point_count") or 0),
                "element_count": int(record.get("viewer_element_count") or record.get("point_count") or 0),
                "topology_hash": topology_hash,
                "mesh_complete": bool(record.get("viewer_mesh_complete") or record.get("viewer_manifest_file")),
                "lod_urls": {
                    "0": f"/api/cases/{case_id}/field-data/frames/{frame_index}/lod/0",
                    "1": f"/api/cases/{case_id}/field-data/frames/{frame_index}/lod/1",
                    "2": f"/api/cases/{case_id}/field-data/frames/{frame_index}/lod/2",
                },
            })
        identity = {
            "contract": "FieldDataManifestV1",
            "case_id": case_id,
            "source_mot_sha256": manifest.get("source_mot_sha256"),
            "raw_sha256": manifest.get("raw_sha256"),
            "frames": [
                {
                    "index": row["frame_index"],
                    "source_sha256": row["source_sha256"],
                    "topology_hash": row["topology_hash"],
                }
                for row in frame_rows
            ],
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        etag = f'"{digest}"'
        headers = {
            "ETag": etag,
            "Cache-Control": "private, no-cache, must-revalidate",
            "X-MCS-Field-Data-Contract": "1",
        }
        if self._etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        evidence = self.case_fea_evidence(case_id)
        payload = {
            "authority": "FieldDataManifestV1",
            "contract_version": "1",
            "case_id": case_id,
            "task_id": row.get("task_id"),
            "available": True,
            "status": str(manifest.get("status") or "EXPORTED"),
            "etag": etag,
            "coordinate_system": {
                "authority": "FieldCoordinateSystemV1",
                "axes": ["x", "y", "z"],
                "length_unit": normalization.get("length_unit") or normalization.get("coordinate_unit"),
                "source": "motorcad_native_export",
                "physical_z": physical_z,
                "planar_compatibility": not physical_z,
            },
            "available_fields": list(normalization.get("available_fields") or []),
            "regions": list(normalization.get("regions") or []),
            "frames": frame_rows,
            "full_mesh_available": bool(capabilities.get("full_region_mesh") and capabilities.get("progressive_mesh_chunks")),
            "transfer_policy": {
                "lod_levels": [0, 1, 2],
                "lod_0_max_points": 4000,
                "lod_1_max_points": 16000,
                "lod_2_mode": "chunked_manifest",
                "conditional_requests": True,
                "immutable_frame_cache": True,
                "cancellation": "request_abort_and_viewer_abort_controller",
            },
            "integrity": evidence.get("integrity") or {},
            "compatibility": {
                "legacy_evidence": evidence,
                "legacy_frame_endpoint": f"/api/cases/{case_id}/fea-frames/{{frame_index}}",
                "legacy_mesh_manifest_endpoint": f"/api/cases/{case_id}/fea-frames/{{frame_index}}/mesh-manifest",
            },
        }
        return JSONResponse(payload, headers=headers)

    def field_data_frame_lod(
        self,
        case_id: str,
        frame_index: int,
        lod: int,
        request: Request,
        field: str = Query(default="b", pattern="^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$"),
        region: str | None = Query(default=None, max_length=160),
        xmin: float | None = Query(default=None),
        xmax: float | None = Query(default=None),
        ymin: float | None = Query(default=None),
        ymax: float | None = Query(default=None),
    ):
        if lod not in {0, 1, 2}:
            raise HTTPException(status_code=422, detail="LOD must be 0, 1, or 2")
        if lod in {0, 1}:
            max_points = 4000 if lod == 0 else 16000
            result = self.case_fea_frame_view(
                case_id, frame_index, request, field, region, max_points,
                xmin, xmax, ymin, ymax,
            )
            if isinstance(result, JSONResponse):
                payload = json.loads(result.body.decode("utf-8"))
                payload["field_data_contract"] = {
                    "authority": "FieldDataFrameLODContractV1",
                    "lod": lod,
                    "transfer_mode": "inline_sample",
                    "max_points": max_points,
                }
                headers = {
                    key: value for key, value in result.headers.items()
                    if key.lower() not in {"content-length", "content-type"}
                }
                headers["X-MCS-Field-Data-Contract"] = "1"
                headers["X-MCS-Field-Data-LOD"] = str(lod)
                return JSONResponse(payload, headers=headers)
            return result

        _, manifest, root = self._manifest_payload(case_id)
        normalization = manifest.get("normalization") or {}
        frames = normalization.get("frames") or []
        record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail="FEA帧不存在")
        path, digest = self._verified_fea_viewer_manifest(root, record)
        viewer_manifest = json.loads(path.read_text(encoding="utf-8"))
        identity = {
            "contract": "FieldDataFrameLODContractV1",
            "lod": 2,
            "case_id": case_id,
            "frame_index": frame_index,
            "manifest_sha256": digest,
            "field": field,
            "region": region,
        }
        response_digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        etag = f'"{response_digest}"'
        headers = {
            "ETag": etag,
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-MCS-Field-Data-Contract": "1",
            "X-MCS-Field-Data-LOD": "2",
        }
        if self._etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return JSONResponse({
            "authority": "FieldDataFrameLODV1",
            "case_id": case_id,
            "frame_index": frame_index,
            "lod": 2,
            "field": field,
            "region": region,
            "transfer_mode": "chunked_manifest",
            "manifest_sha256": digest,
            "mesh_complete": bool(viewer_manifest.get("mesh_complete")),
            "element_count": int(viewer_manifest.get("element_count") or 0),
            "node_count": int(viewer_manifest.get("node_count") or 0),
            "chunk_count": len(viewer_manifest.get("chunks") or []),
            "mesh_manifest_url": f"/api/cases/{case_id}/field-data/frames/{frame_index}/mesh-manifest",
            "chunk_url_template": f"/api/cases/{case_id}/field-data/frames/{frame_index}/mesh-chunks/{{chunk_index}}",
            "legacy_mesh_manifest_url": f"/api/cases/{case_id}/fea-frames/{frame_index}/mesh-manifest",
            "legacy_chunk_url_template": f"/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{{chunk_index}}",
            "topology_hash": digest,
        }, headers=headers)

    def field_data_integrity(
        self,
        case_id: str,
        verify_chunks: bool = Query(default=False),
    ):
        row, manifest, root = self._manifest_payload(case_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="当前 Case 尚无 Motor-CAD FEA 导出证据")
        normalization = manifest.get("normalization") or {}
        records = normalization.get("frames") or []
        issues: list[dict[str, Any]] = []
        frames: list[dict[str, Any]] = []
        verified_chunks = 0
        for offset, record in enumerate(records):
            frame_index = int(record.get("index", offset))
            try:
                _, status, digest = self._verified_fea_frame(root, record)
                frame_row = {"frame_index": frame_index, "status": status, "sha256": digest}
                if record.get("viewer_manifest_file"):
                    manifest_path, topology_hash = self._verified_fea_viewer_manifest(root, record)
                    frame_row["topology_hash"] = topology_hash
                    viewer = json.loads(manifest_path.read_text(encoding="utf-8"))
                    chunks = viewer.get("chunks") or []
                    frame_row["chunk_count"] = len(chunks)
                    if verify_chunks:
                        for chunk in chunks:
                            self._verified_fea_viewer_chunk(manifest_path, chunk)
                            verified_chunks += 1
                frames.append(frame_row)
            except HTTPException as exc:
                issues.append({
                    "frame_index": frame_index,
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                })
        return {
            "authority": "FieldDataIntegrityReportV1",
            "case_id": case_id,
            "task_id": row.get("task_id"),
            "valid": not issues and len(frames) == len(records),
            "frame_count": len(records),
            "verified_frame_count": len(frames),
            "verified_chunk_count": verified_chunks,
            "chunk_verification_requested": bool(verify_chunks),
            "frames": frames,
            "issues": issues,
        }


__all__ = ["FieldDataCompatibilityAdapter"]
