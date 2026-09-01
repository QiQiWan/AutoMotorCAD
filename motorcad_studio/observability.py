from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_SENSITIVE_RE = re.compile(r"(password|passwd|token|secret|authorization|api[_-]?key|licen[cs]e[_-]?key)", re.I)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_payload(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            out[key_s] = "<redacted>" if _SENSITIVE_RE.search(key_s) else _safe_payload(item, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_safe_payload(item, depth + 1) for item in list(value)[:500]]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _signature(record: dict[str, Any]) -> str:
    message = str(record.get("message") or "")
    # Normalize volatile identifiers so repeated failures aggregate into one problem.
    message = re.sub(r"\bTASK-[A-Z0-9]+(?:-C\d+)?\b", "TASK-#", message, flags=re.I)
    message = re.sub(r"\b(?:CASE|REQ|PRJ|DSN|DRV|SCN|SRV|DST)-[A-Z0-9-]+\b", "ID-#", message, flags=re.I)
    message = re.sub(r"0x[0-9a-fA-F]+", "0x#", message)
    message = re.sub(r"\b\d+(?:\.\d+)?\b", "#", message)
    message = re.sub(r"\s+", " ", message).strip()
    return f"{record.get('component','')}:{record.get('event_type','')}:{message[:240]}"


def _diagnostic_classification(record: dict[str, Any]) -> dict[str, Any]:
    hay = json.dumps(record or {}, ensure_ascii=False).lower()
    event_type = str((record or {}).get("event_type") or "").upper()
    message = str((record or {}).get("message") or "")
    consequence = event_type in {"TASK_FINISHED"} or (event_type in {"CASE_FAILED", "CASE_VALIDATING"} and len(message) < 120)
    category = "GENERAL"
    root_cause = False
    recommendations: list[str] = []
    if str((record or {}).get("component") or "").lower() == "frontend" or event_type.startswith("FRONTEND_"):
        category = "FRONTEND"
        root_cause = event_type in {"FRONTEND_ROUTE_FAILED", "FRONTEND_UNCAUGHT_ERROR", "FRONTEND_UNHANDLED_REJECTION"}
        consequence = False
        if event_type == "FRONTEND_ROUTE_SLOW":
            recommendations.append("检查该路由的API耗时和重复加载；Route-first页面会自动取消旧请求，持续慢加载应继续定位到具体接口或渲染阶段。")
        else:
            recommendations.append("检查记录中的route、浏览器错误堆栈和相邻API请求。优先修复页面生命周期、过期响应覆盖或前端未处理异常。")
    elif "no module named 'ansys" in hay or "no module named \"ansys" in hay or ("pymotorcad" in hay and any(token in hay for token in ("unavailable", "不可用", "missing", "缺少"))):
        category = "PYMOTORCAD_DEPENDENCY"
        root_cause = True
        consequence = False
        recommendations.append("确认 Studio 与 Worker 使用同一 Python 解释器；在该解释器中执行 python -m pip install -r requirements-motorcad.txt，然后重启 Studio 并运行深度检查。")
        recommendations.append("不要只在系统 Python 或另一个虚拟环境中安装 ansys-motorcad-core；诊断包中的 Python executable 与 Worker 能力握手必须指向同一环境。")
    elif any(token in hay for token in ("set_component_material", "组件材料设置失败", "material binding failed", "materialbindingvalidationerror", "component_material")):
        category = "MATERIAL_BINDING"
        root_cause = True
        consequence = False
        recommendations.append("先区分模板继承材料与显式材料赋值：模板继承值应沿用已加载 .mtt/.mot 的原生绑定，避免重复调用 set_component_material。")
        recommendations.append("显式更换材料时，确认材料名称存在于当前 Solids.mdb / Fluids.mdb，并查看诊断中的 component、material、candidate_targets 与 Motor-CAD 原始错误。")
        recommendations.append("若只有 Conductor 等逻辑部件失败，核对当前 Motor-CAD 版本的组件别名与 get_component_material 回读结果。")
    elif any(token in hay for token in ("winding is not feasible", "slot_number/phases/parallel paths", "fundamental winding factor", "windingvalidationerror", "winding_slot_phase_path", "绕组不可行")):
        category = "WINDING"
        root_cause = True
        consequence = False
        recommendations.append("绕组拓扑不可解。核对 Slot_Number / Phases / ParallelPaths；该比值必须满足当前模板的整数约束。优先恢复Design Revision/模板基线槽数，再重新生成绕组。")
        if "slot fill" in hay:
            recommendations.append("Motor-CAD同时报告槽满率异常时，先修复槽/相/支路关系，再重新计算实际槽满率；若仍大于1，再调整导体数、槽尺寸或导体尺寸。")
    elif "slot fill" in hay and "should not be > 1" in hay:
        category = "WINDING"
        root_cause = True
        consequence = False
        recommendations.append("Motor-CAD报告槽满率超过1。检查Conductors/Slot、导体尺寸与槽面积，修正后重新生成绕组。")
    elif any(token in hay for token in ("geometryvalidationerror", "slot opening", "statorair", "geometry", "几何", "相交")):
        category = "GEOMETRY"
        root_cause = event_type not in {"TASK_FINISHED"}
        recommendations.append("检查槽口宽度、齿宽、槽深、槽数和定子内外径；优先查看Case目录中的 model_validation.json 与 parameter_audit.json。")
    elif any(token in hay for token in ("brokenpipe", "winerror 109", "管道已结束")):
        category = "IPC"
        root_cause = True
        consequence = False
        recommendations.append("检查父进程与求解Worker的IPC收尾。若前序已有 SOLVER_RUN_SUCCESS，该错误更可能属于Windows管道EOF竞态。")
    elif "timeout" in hay or "超时" in hay:
        category = "TIMEOUT"
        root_cause = True
        consequence = False
        recommendations.append("检查当前Stage耗时、Motor-CAD进程CPU/内存以及solver timeout；必要时增大超时或降低单Case复杂度。")
    elif "license" in hay or "许可证" in hay:
        category = "LICENSE"
        root_cause = True
        consequence = False
        recommendations.append("检查LicensePool容量与实际Motor-CAD许可可用性，并核对等待发生的模块资源。")
    elif "automation" in hay or ("parameter" in hay and "mapping" in hay):
        category = "PARAMETER_MAPPING"
        root_cause = True
        consequence = False
        recommendations.append("核对目标Motor-CAD版本的Automation Parameter Names、上下文和单位映射。")
    elif "data_factory" in hay or "dataset" in hay:
        category = "DATA_FACTORY"
        root_cause = event_type not in {"TASK_FINISHED"}
        recommendations.append("检查Data Factory目录权限、磁盘空间、质量门禁与Schema/Content Hash。")
    elif "disk" in hay or "storage" in hay:
        category = "STORAGE"
        root_cause = True
        consequence = False
        recommendations.append("清理旧Artifact/缓存或扩展结果盘空间，避免求解完成后归档失败。")
    return {"category": category, "root_cause": root_cause, "consequence": consequence, "recommendations": recommendations}


class StructuredLogStore:
    """Local structured observability store.

    Parent-process logs are written to rotating JSONL and text files. Solver child
    processes send structured records back through the existing multiprocessing queue,
    so concurrent children do not write to the shared central file directly.
    """

    def __init__(
        self,
        root: Path,
        *,
        level: str = "INFO",
        max_bytes: int = 20 * 1024 * 1024,
        backup_count: int = 8,
        retention_days: int = 14,
        memory_records: int = 5000,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.level = str(level or "INFO").upper()
        if self.level not in _LEVELS:
            self.level = "INFO"
        self.max_bytes = max(256 * 1024, int(max_bytes))
        self.backup_count = max(1, int(backup_count))
        self.retention_days = max(1, int(retention_days))
        self.jsonl_path = self.root / "studio.jsonl"
        self.text_path = self.root / "studio.log"
        self.audit_path = self.root / "audit.jsonl"
        self.native_path = self.root / "native.jsonl"
        self.qualification_path = self.root / "qualification.jsonl"
        self.plugin_path = self.root / "plugins.jsonl"
        self.trace_path = self.root / "traces.jsonl"
        self._lock = threading.RLock()
        self._records: deque[dict[str, Any]] = deque(maxlen=max(200, int(memory_records)))
        self.session_id = f"BOOT-{uuid.uuid4().hex[:12].upper()}"
        self._seq = 0
        self.cleanup_old_files()
        self._seq = self._load_max_seq()

    def _load_max_seq(self) -> int:
        maximum = 0
        for path in self.root.glob("studio.jsonl*"):
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        maximum = max(maximum, int(row.get("seq") or 0))
                    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                        continue
            except OSError:
                continue
        return maximum

    def _enabled(self, level: str) -> bool:
        return _LEVELS.get(level.upper(), 20) >= _LEVELS.get(self.level, 20)

    def _rotate(self, path: Path) -> None:
        try:
            if not path.exists() or path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        for index in range(self.backup_count - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            target = path.with_name(f"{path.name}.{index + 1}")
            if source.exists():
                try:
                    if target.exists():
                        target.unlink()
                    source.replace(target)
                except OSError:
                    pass
        first = path.with_name(f"{path.name}.1")
        try:
            if first.exists():
                first.unlink()
            path.replace(first)
        except OSError:
            pass

    def _write_json(self, path: Path, record: dict[str, Any]) -> None:
        self._rotate(path)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")

    def _write_text(self, record: dict[str, Any]) -> None:
        self._rotate(self.text_path)
        prefix = " ".join(
            part for part in [
                record.get("timestamp", ""),
                f"[{record.get('level','INFO')}]",
                f"[{record.get('component','studio')}]",
                f"[{record.get('event_type','EVENT')}]",
                f"task={record.get('task_id')}" if record.get("task_id") else "",
                f"case={record.get('case_id')}" if record.get("case_id") else "",
                f"stage={record.get('stage')}" if record.get("stage") else "",
            ] if part
        )
        with self.text_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{prefix} {record.get('message','')}\n")

    def log(
        self,
        *,
        level: str = "INFO",
        component: str = "studio",
        event_type: str = "EVENT",
        message: str,
        task_id: str | None = None,
        case_id: str | None = None,
        stage: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        operation_id: str | None = None,
        plugin_id: str | None = None,
        topology_id: str | None = None,
        binding_version: str | None = None,
        payload: dict[str, Any] | None = None,
        channel: str = "runtime",
        timestamp: str | None = None,
        pid: int | None = None,
    ) -> dict[str, Any] | None:
        level = str(level or "INFO").upper()
        if level not in _LEVELS:
            level = "INFO"
        if not self._enabled(level):
            return None
        with self._lock:
            self._seq += 1
            record = {
                "seq": self._seq,
                "session_id": self.session_id,
                "timestamp": timestamp or _iso_now(),
                "level": level,
                "channel": str(channel or "runtime"),
                "component": str(component or "studio"),
                "event_type": str(event_type or "EVENT"),
                "message": str(message or ""),
                "task_id": task_id,
                "case_id": case_id,
                "stage": stage,
                "request_id": request_id,
                "trace_id": trace_id or task_id or request_id or run_id or operation_id,
                "run_id": run_id,
                "operation_id": operation_id,
                "plugin_id": plugin_id,
                "topology_id": topology_id,
                "binding_version": binding_version,
                "pid": int(pid if pid is not None else os.getpid()),
                "thread": threading.current_thread().name,
                "payload": _safe_payload(payload or {}),
            }
            self._records.append(record)
            self._write_json(self.jsonl_path, record)
            self._write_text(record)
            channel_paths = {
                "audit": self.audit_path,
                "native": self.native_path,
                "qualification": self.qualification_path,
                "plugin": self.plugin_path,
                "trace": self.trace_path,
            }
            channel_path = channel_paths.get(record["channel"])
            if channel_path is not None:
                self._write_json(channel_path, record)
            return record

    def audit(self, **kwargs: Any) -> dict[str, Any] | None:
        kwargs["channel"] = "audit"
        return self.log(**kwargs)

    def native(self, **kwargs: Any) -> dict[str, Any] | None:
        kwargs["channel"] = "native"
        return self.log(**kwargs)

    def qualification(self, **kwargs: Any) -> dict[str, Any] | None:
        kwargs["channel"] = "qualification"
        return self.log(**kwargs)

    def plugin(self, **kwargs: Any) -> dict[str, Any] | None:
        kwargs["channel"] = "plugin"
        return self.log(**kwargs)

    @contextmanager
    def span(
        self, *, component: str, operation: str, message: str = "", level: str = "INFO",
        task_id: str | None = None, case_id: str | None = None, trace_id: str | None = None,
        run_id: str | None = None, plugin_id: str | None = None, topology_id: str | None = None,
        binding_version: str | None = None, payload: dict[str, Any] | None = None, channel: str = "trace",
    ):
        operation_id = f"OP-{uuid.uuid4().hex[:12].upper()}"
        started = time.perf_counter()
        self.log(
            level=level, channel=channel, component=component, event_type=f"{operation}_START",
            message=message or f"{operation} started", task_id=task_id, case_id=case_id, trace_id=trace_id,
            run_id=run_id, operation_id=operation_id, plugin_id=plugin_id, topology_id=topology_id,
            binding_version=binding_version, payload=payload or {},
        )
        try:
            yield operation_id
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self.log(
                level="ERROR", channel=channel, component=component, event_type=f"{operation}_FAILED",
                message=f"{message or operation} failed: {type(exc).__name__}: {exc}", task_id=task_id, case_id=case_id,
                trace_id=trace_id, run_id=run_id, operation_id=operation_id, plugin_id=plugin_id,
                topology_id=topology_id, binding_version=binding_version,
                payload={**(payload or {}), "duration_ms": elapsed_ms, "error_type": type(exc).__name__, "error": str(exc)},
            )
            raise
        else:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self.log(
                level=level, channel=channel, component=component, event_type=f"{operation}_END",
                message=f"{message or operation} completed", task_id=task_id, case_id=case_id, trace_id=trace_id,
                run_id=run_id, operation_id=operation_id, plugin_id=plugin_id, topology_id=topology_id,
                binding_version=binding_version, payload={**(payload or {}), "duration_ms": elapsed_ms},
            )

    def memory_since(self, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(row) for row in self._records if int(row.get("seq") or 0) > int(after_seq)]
        return rows[: max(1, min(int(limit), 2000))]

    def _log_files(self) -> list[Path]:
        files = [path for path in self.root.glob("studio.jsonl*") if path.is_file()]
        return sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    @staticmethod
    def _reverse_lines(path: Path, block_size: int = 64 * 1024) -> Iterable[str]:
        """Yield UTF-8 lines newest-first without loading a rotated log into memory."""
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                position = handle.tell()
                buffer = b""
                while position > 0:
                    size = min(block_size, position)
                    position -= size
                    handle.seek(position)
                    buffer = handle.read(size) + buffer
                    parts = buffer.split(b"\n")
                    buffer = parts[0]
                    for raw in reversed(parts[1:]):
                        if raw.strip():
                            yield raw.decode("utf-8", errors="replace")
                if buffer.strip():
                    yield buffer.decode("utf-8", errors="replace")
        except OSError:
            return

    def _iter_records(self) -> Iterable[dict[str, Any]]:
        # Current file first, then rotated files from newest to oldest.
        for path in self._log_files():
            for line in self._reverse_lines(path):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row

    def query(
        self,
        *,
        level: str | None = None,
        component: str | None = None,
        task_id: str | None = None,
        case_id: str | None = None,
        stage: str | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        channel: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        operation_id: str | None = None,
        plugin_id: str | None = None,
        topology_id: str | None = None,
        binding_version: str | None = None,
        text: str | None = None,
        minutes: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        level = level.upper() if level else None
        threshold = _LEVELS.get(level, None) if level else None
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(0, int(minutes))) if minutes is not None else None
        needle = str(text or "").lower().strip()
        rows: list[dict[str, Any]] = []
        for row in self._iter_records():
            if threshold is not None and _LEVELS.get(str(row.get("level", "INFO")).upper(), 20) < threshold:
                continue
            if component and str(row.get("component")) != component:
                continue
            if task_id and str(row.get("task_id")) != task_id:
                continue
            if case_id and str(row.get("case_id")) != case_id:
                continue
            if stage and str(row.get("stage")) != stage:
                continue
            if request_id and str(row.get("request_id")) != request_id:
                continue
            if session_id and str(row.get("session_id")) != session_id:
                continue
            if channel and str(row.get("channel")) != channel:
                continue
            if trace_id and str(row.get("trace_id")) != trace_id:
                continue
            if run_id and str(row.get("run_id")) != run_id:
                continue
            if operation_id and str(row.get("operation_id")) != operation_id:
                continue
            if plugin_id and str(row.get("plugin_id")) != plugin_id:
                continue
            if topology_id and str(row.get("topology_id")) != topology_id:
                continue
            if binding_version and str(row.get("binding_version")) != binding_version:
                continue
            if cutoff is not None:
                try:
                    ts = datetime.fromisoformat(str(row.get("timestamp")))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            if needle:
                haystack = json.dumps(row, ensure_ascii=False, default=str).lower()
                if needle not in haystack:
                    continue
            rows.append(row)
            if len(rows) >= max(1, min(int(limit), 5000)):
                break
        rows.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return rows

    def summary(self, minutes: int = 60, session_id: str | None = None) -> dict[str, Any]:
        rows = self.query(minutes=minutes, session_id=session_id, limit=5000)
        levels = Counter(str(row.get("level") or "INFO") for row in rows)
        components = Counter(str(row.get("component") or "studio") for row in rows)
        channels = Counter(str(row.get("channel") or "runtime") for row in rows)
        errors = [row for row in rows if _LEVELS.get(str(row.get("level") or "INFO"), 20) >= 40]
        warnings = [row for row in rows if str(row.get("level")) == "WARNING"]
        score = 100
        score -= min(45, len(errors) * 8)
        score -= min(25, len(warnings) * 2)
        score = max(0, score)
        return {
            "window_minutes": int(minutes),
            "session_id": session_id or None,
            "current_session_id": self.session_id,
            "total": len(rows),
            "levels": dict(levels),
            "components": dict(components.most_common(20)),
            "channels": dict(channels.most_common(20)),
            "errors": len(errors),
            "warnings": len(warnings),
            "health_score": score,
            "last_seq": self._seq,
            "log_dir": str(self.root),
            "jsonl_path": str(self.jsonl_path),
            "text_path": str(self.text_path),
        }

    def diagnose(self, minutes: int = 240, limit: int = 20, session_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
        rows = self.query(level="WARNING", minutes=minutes, session_id=session_id, task_id=task_id, limit=5000)
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            sig = _signature(row)
            classification = _diagnostic_classification(row)
            item = groups.setdefault(sig, {
                "signature": sig, "count": 0, "last": row, "first": row,
                "level": row.get("level"), "recommendations": [],
                "affected_tasks": set(), "affected_cases": set(),
                "category": classification["category"],
                "root_cause": classification["root_cause"],
                "consequence": classification["consequence"],
            })
            item["count"] += 1
            item["first"] = row
            if row.get("task_id"):
                item["affected_tasks"].add(str(row["task_id"]))
            if row.get("case_id"):
                item["affected_cases"].add(str(row["case_id"]))
            if _LEVELS.get(str(row.get("level")), 20) > _LEVELS.get(str(item.get("level")), 20):
                item["level"] = row.get("level")
            if classification["root_cause"]:
                item["root_cause"] = True
                item["consequence"] = False
            if item.get("category") == "GENERAL" and classification["category"] != "GENERAL":
                item["category"] = classification["category"]

        problems = list(groups.values())
        for item in problems:
            classification = _diagnostic_classification(item.get("last") or {})
            rec = list(classification.get("recommendations") or [])
            hay = json.dumps(item.get("last") or {}, ensure_ascii=False).lower()
            if "heartbeat" in hay or ("process_lost" in hay) or ("worker" in hay and "exit" in hay):
                rec.append("检查Worker/Motor-CAD进程树、最近心跳和error.log，并结合solver_runtime.jsonl确认进程退出前最后Stage。")
            if not rec:
                rec.append("从该记录的task_id/case_id跳转到Case时间线，并结合前后日志确认最早异常点。")
            item["recommendations"] = list(dict.fromkeys(rec))
            item["affected_tasks"] = sorted(item["affected_tasks"])[:100]
            item["affected_cases"] = sorted(item["affected_cases"])[:200]
            base = _LEVELS.get(str(item.get("level")), 20) + min(40, int(item["count"]) * 4)
            if item.get("root_cause"):
                base += 25
            if item.get("consequence"):
                base -= 30
            item["problem_score"] = max(0, min(100, base))
        problems.sort(key=lambda item: (int(item.get("problem_score") or 0), bool(item.get("root_cause")), int(item.get("count") or 0)), reverse=True)
        root_causes = [item for item in problems if item.get("root_cause") and not item.get("consequence")]
        summary = self.summary(minutes=minutes, session_id=session_id)
        all_rows = self.query(minutes=minutes, session_id=session_id, task_id=task_id, limit=5000)
        http_rows = [row for row in all_rows if str(row.get("event_type")) == "HTTP_REQUEST"]
        slow_http = sorted(
            http_rows,
            key=lambda row: float((row.get("payload") or {}).get("elapsed_ms") or 0.0),
            reverse=True,
        )[:25]
        frontend_rows = [
            row for row in all_rows
            if str(row.get("channel")) == "frontend"
            or str(row.get("component")) == "frontend"
        ][:100]
        performance = {
            "http_request_count": len(http_rows),
            "slow_http_count_over_1000ms": sum(
                1 for row in http_rows
                if float((row.get("payload") or {}).get("elapsed_ms") or 0.0) >= 1000.0
            ),
            "slowest_http_requests": [
                {
                    "method": (row.get("payload") or {}).get("method"),
                    "path": (row.get("payload") or {}).get("path"),
                    "status_code": (row.get("payload") or {}).get("status_code"),
                    "elapsed_ms": (row.get("payload") or {}).get("elapsed_ms"),
                    "request_id": row.get("request_id"),
                    "timestamp": row.get("timestamp"),
                }
                for row in slow_http
            ],
            "frontend_event_count": len(frontend_rows),
            "recent_frontend_events": frontend_rows,
        }
        if task_id:
            scoped_rows = self.query(minutes=minutes, session_id=session_id, task_id=task_id, limit=5000)
            summary = {**summary, "task_id": task_id, "task_scoped_total": len(scoped_rows)}
        return {
            "summary": summary,
            "session_id": session_id or None,
            "task_id": task_id or None,
            "current_session_id": self.session_id,
            "problem_count": len(problems),
            "root_cause_count": len(root_causes),
            "root_causes": root_causes[: max(1, min(int(limit), 20))],
            "problems": problems[: max(1, min(int(limit), 100))],
            "performance": performance,
            "diagnostic_contract_version": "0.89-G4.2",
        }

    def cleanup_old_files(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        for path in self.root.iterdir() if self.root.exists() else []:
            if not path.is_file() or path.name in {".gitkeep"}:
                continue
            try:
                if path.stat().st_mtime < cutoff and path.name.startswith(("studio.", "audit.", "native.", "qualification.", "plugins.", "traces.")):
                    path.unlink()
            except OSError:
                pass

    def export_bundle(self, target: Path, *, task_id: str | None = None, minutes: int | None = None, session_id: str | None = None) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        records = self.query(task_id=task_id, minutes=minutes, session_id=session_id, limit=5000)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("logs_filtered.jsonl", "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in records))
            archive.writestr("diagnostics.json", json.dumps(self.diagnose(minutes=minutes or 240, task_id=task_id, session_id=session_id), ensure_ascii=False, indent=2, default=str))
            archive.writestr("session.json", json.dumps({"current_session_id": self.session_id, "exported_session_id": session_id, "exported_at": _iso_now()}, ensure_ascii=False, indent=2))
            # Export the complete local central-log set, including rotated backups, so
            # an online diagnostic download matches what support staff could inspect on
            # the workstation itself.
            central_names = {
                self.text_path.name, self.jsonl_path.name, self.audit_path.name, self.native_path.name,
                self.qualification_path.name, self.plugin_path.name, self.trace_path.name,
            }
            candidates = []
            for path in sorted(self.root.iterdir() if self.root.exists() else []):
                if not path.is_file():
                    continue
                if path.name in central_names or path.name.startswith(("studio.", "audit.", "native.", "qualification.", "plugins.", "traces.")):
                    candidates.append(path)
            seen = set()
            for path in candidates:
                if path.resolve() in seen:
                    continue
                seen.add(path.resolve())
                archive.write(path, arcname=f"raw/{path.name}")
        return target


def new_request_id() -> str:
    return f"REQ-{uuid.uuid4().hex[:12].upper()}"
