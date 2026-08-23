from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import platform
import secrets
import sys
from pathlib import Path
from typing import Any, Callable

from ..analysis_domain.contracts import stable_hash


class ReproducibilityEnvironmentService:
    """Lightweight reproducibility capsule and local signed evidence anchor.

    V0.80-E deliberately keeps this workstation-friendly.  The default anchor is an
    HMAC key stored outside SQLite in the runtime directory.  It provides an independent
    tamper check without requiring PKI, certificate services, or network dependencies.
    A caller may provide MOTORCAD_STUDIO_EVIDENCE_ANCHOR_SECRET to manage the key outside
    the Studio process.
    """

    CONTRACT_VERSION = "0.80-E"
    CAPSULE_AUTHORITY = "ReproducibilityEnvironmentCapsuleV1"
    ANCHOR_AUTHORITY = "SignedEvidenceAnchorV1"
    PACKAGE_NAMES = (
        "motorcad-studio-mvp",
        "fastapi",
        "uvicorn",
        "pydantic",
        "PyYAML",
        "psutil",
        "ansys-motorcad-core",
    )

    def __init__(
        self,
        db,
        *,
        root_dir: Path,
        runtime_dir: Path,
        motorcad_exe: str | None,
        runtime_context_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.db = db
        self.root_dir = Path(root_dir)
        self.runtime_dir = Path(runtime_dir)
        self.motorcad_exe = str(motorcad_exe or "") or None
        self.runtime_context_provider = runtime_context_provider
        self.key_path = self.runtime_dir / "evidence_anchor.key"

    @staticmethod
    def _sha256_file(path: Path, *, max_bytes: int | None = None) -> str | None:
        try:
            if not path.is_file():
                return None
            if max_bytes is not None and path.stat().st_size > max_bytes:
                return None
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _file_metadata(path: Path | None, *, deep_hash: bool = False) -> dict[str, Any]:
        if path is None:
            return {"path": None, "exists": False}
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        payload: dict[str, Any] = {"path": str(resolved), "exists": resolved.is_file()}
        if not payload["exists"]:
            return payload
        try:
            stat = resolved.stat()
            payload.update({"size_bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
        except OSError:
            pass
        if deep_hash:
            payload["sha256"] = ReproducibilityEnvironmentService._sha256_file(resolved)
        return payload

    def _package_versions(self) -> dict[str, str | None]:
        versions: dict[str, str | None] = {}
        for name in self.PACKAGE_NAMES:
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = None
            except Exception:
                versions[name] = None
        return versions

    def _config_fingerprints(self) -> dict[str, Any]:
        config_dir = self.root_dir / "config"
        items: dict[str, str] = {}
        if config_dir.is_dir():
            for path in sorted(config_dir.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                    continue
                digest = self._sha256_file(path)
                if digest:
                    items[str(path.relative_to(self.root_dir)).replace("\\", "/")] = digest
        return {"files": items, "content_hash": stable_hash(items)}

    def inspect_current(self, *, capture_mode: str = "standard") -> dict[str, Any]:
        mode = "deep" if str(capture_mode).lower() == "deep" else "standard"
        runtime_context = dict(self.runtime_context_provider() if self.runtime_context_provider is not None else {})
        effective_exe = runtime_context.get("motorcad_exe_effective") or self.motorcad_exe
        exe = Path(str(effective_exe)) if effective_exe else None
        release_manifest = self.root_dir / "RELEASE_MANIFEST.json"
        pyproject = self.root_dir / "pyproject.toml"
        config = self._config_fingerprints()
        packages = self._package_versions()
        python_mm = f"{sys.version_info.major}.{sys.version_info.minor}"
        capsule_core = {
            "capture_mode": mode,
            "studio": {
                "version": runtime_context.get("studio_version"),
                "release_manifest_sha256": self._sha256_file(release_manifest),
                "pyproject_sha256": self._sha256_file(pyproject),
            },
            "runtime": {
                "python_version": platform.python_version(),
                "python_major_minor": python_mm,
                "python_implementation": platform.python_implementation(),
                "platform_system": platform.system(),
                "platform_release": platform.release(),
                "platform_machine": platform.machine(),
            },
            "motorcad": {
                "configured_version": runtime_context.get("motorcad_version"),
                "executable": self._file_metadata(exe, deep_hash=(mode == "deep")),
            },
            "model_policy": runtime_context.get("model_policy"),
            "default_solver": runtime_context.get("default_solver"),
            "plugin_catalog_hash": runtime_context.get("plugin_catalog_hash"),
            "plugin_api_version": runtime_context.get("plugin_api_version"),
            "packages": packages,
            "config": config,
        }
        capsule_core["compatibility_fingerprint"] = stable_hash({
            "python_major_minor": python_mm,
            "motorcad_version": capsule_core["motorcad"]["configured_version"],
            "model_policy": capsule_core["model_policy"],
            "plugin_api_version": capsule_core["plugin_api_version"],
            "plugin_catalog_hash": capsule_core["plugin_catalog_hash"],
            "config_hash": config["content_hash"],
        })
        capsule_core["environment_fingerprint"] = stable_hash(capsule_core)
        return capsule_core

    def capture(self, *, capture_mode: str = "standard") -> dict[str, Any]:
        current = self.inspect_current(capture_mode=capture_mode)
        content_hash = stable_hash(current)
        capsule_id = f"REC-{content_hash[:20].upper()}"
        row = self.db.query_one("SELECT capsule_json,content_hash,created_at FROM reproducibility_environment_capsules WHERE capsule_id=?", (capsule_id,))
        if row:
            payload = self.db.loads(row.get("capsule_json"), {}) or {}
            return {
                "authority": self.CAPSULE_AUTHORITY,
                "contract_version": self.CONTRACT_VERSION,
                "capsule_id": capsule_id,
                "content_hash": str(row.get("content_hash") or content_hash),
                "capsule": payload,
                "created_at": str(row.get("created_at") or ""),
                "reused": True,
            }
        created_at = self.db.now()
        self.db.execute(
            "INSERT INTO reproducibility_environment_capsules(capsule_id,capture_mode,capsule_json,content_hash,created_at) VALUES(?,?,?,?,?)",
            (capsule_id, current.get("capture_mode") or "standard", self.db.dumps(current), content_hash, created_at),
        )
        return {
            "authority": self.CAPSULE_AUTHORITY,
            "contract_version": self.CONTRACT_VERSION,
            "capsule_id": capsule_id,
            "content_hash": content_hash,
            "capsule": current,
            "created_at": created_at,
            "reused": False,
        }

    def get_capsule(self, capsule_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM reproducibility_environment_capsules WHERE capsule_id=?", (capsule_id,)) or {}
        if not row:
            raise KeyError(capsule_id)
        payload = self.db.loads(row.get("capsule_json"), {}) or {}
        content_hash = str(row.get("content_hash") or "")
        if stable_hash(payload) != content_hash:
            raise ValueError("REPRODUCIBILITY_CAPSULE_HASH_MISMATCH")
        return {
            "authority": self.CAPSULE_AUTHORITY,
            "contract_version": self.CONTRACT_VERSION,
            "capsule_id": capsule_id,
            "content_hash": content_hash,
            "capsule": payload,
            "created_at": str(row.get("created_at") or ""),
        }

    def compare(self, historical: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        historical_capsule = historical.get("capsule") if "capsule" in historical else historical
        current_capsule = current or self.inspect_current(capture_mode="standard")
        diffs: list[dict[str, Any]] = []

        def add(field: str, old: Any, new: Any, severity: str) -> None:
            if old != new:
                diffs.append({"field": field, "historical": old, "current": new, "severity": severity})

        old_motor = historical_capsule.get("motorcad") or {}
        new_motor = current_capsule.get("motorcad") or {}
        old_exe = old_motor.get("executable") or {}
        new_exe = new_motor.get("executable") or {}
        add("motorcad.configured_version", old_motor.get("configured_version"), new_motor.get("configured_version"), "CRITICAL")
        add("runtime.python_major_minor", (historical_capsule.get("runtime") or {}).get("python_major_minor"), (current_capsule.get("runtime") or {}).get("python_major_minor"), "CRITICAL")
        add("model_policy", historical_capsule.get("model_policy"), current_capsule.get("model_policy"), "CRITICAL")
        add("plugin_api_version", historical_capsule.get("plugin_api_version"), current_capsule.get("plugin_api_version"), "CRITICAL")
        add("plugin_catalog_hash", historical_capsule.get("plugin_catalog_hash"), current_capsule.get("plugin_catalog_hash"), "CRITICAL")
        add("config.content_hash", (historical_capsule.get("config") or {}).get("content_hash"), (current_capsule.get("config") or {}).get("content_hash"), "CRITICAL")
        add("studio.version", (historical_capsule.get("studio") or {}).get("version"), (current_capsule.get("studio") or {}).get("version"), "INFO")
        add("packages", historical_capsule.get("packages") or {}, current_capsule.get("packages") or {}, "INFO")
        add("platform.system", (historical_capsule.get("runtime") or {}).get("platform_system"), (current_capsule.get("runtime") or {}).get("platform_system"), "INFO")
        if old_exe.get("sha256") and new_exe.get("sha256"):
            add("motorcad.executable.sha256", old_exe.get("sha256"), new_exe.get("sha256"), "CRITICAL")
        elif old_exe.get("exists") and new_exe.get("exists"):
            add("motorcad.executable.size_bytes", old_exe.get("size_bytes"), new_exe.get("size_bytes"), "INFO")

        current_requires_motorcad = str(current_capsule.get("default_solver") or "").lower() == "motorcad"
        current_motorcad_available = bool(new_exe.get("exists")) if current_requires_motorcad else True
        if any(row["severity"] == "CRITICAL" for row in diffs):
            state = "CHANGED_ENVIRONMENT"
        elif diffs:
            state = "COMPATIBLE_ENVIRONMENT"
        else:
            state = "EXACT_ENVIRONMENT"
        return {
            "authority": "ReproducibilityEnvironmentComparisonV1",
            "contract_version": self.CONTRACT_VERSION,
            "status": state,
            "exact": state == "EXACT_ENVIRONMENT",
            "replay_recommended": state in {"EXACT_ENVIRONMENT", "COMPATIBLE_ENVIRONMENT"},
            "solver_available": current_motorcad_available,
            "difference_count": len(diffs),
            "differences": diffs,
            "historical_fingerprint": historical_capsule.get("environment_fingerprint"),
            "current_fingerprint": current_capsule.get("environment_fingerprint"),
        }

    def compare_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        historical = snapshot.get("reproducibility_environment") or {}
        if not historical:
            return {
                "authority": "ReproducibilityEnvironmentComparisonV1",
                "contract_version": self.CONTRACT_VERSION,
                "status": "LEGACY_ENVIRONMENT_UNKNOWN",
                "exact": False,
                "replay_recommended": False,
                "solver_available": False,
                "difference_count": 1,
                "differences": [{"field": "historical_capsule", "historical": None, "current": "available", "severity": "CRITICAL"}],
                "reason": "HISTORICAL_CAPSULE_MISSING",
            }
        return self.compare(historical)

    def _load_signing_key(self) -> tuple[bytes, str, str]:
        configured = os.getenv("MOTORCAD_STUDIO_EVIDENCE_ANCHOR_SECRET")
        if configured:
            key = configured.encode("utf-8")
            source = "environment"
        else:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            if self.key_path.exists():
                key = self.key_path.read_bytes()
            else:
                key = secrets.token_bytes(32)
                tmp = self.key_path.with_suffix(".tmp")
                tmp.write_bytes(key)
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                os.replace(tmp, self.key_path)
            source = "local_runtime_key"
        key_id = f"KEY-{hashlib.sha256(key).hexdigest()[:16].upper()}"
        return key, key_id, source

    @staticmethod
    def _anchor_message(core: dict[str, Any]) -> bytes:
        return json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def sign_ledger_head(self, *, ledger_id: str, ledger_head_hash: str, capsule: dict[str, Any], reason: str) -> dict[str, Any]:
        capsule_id = str(capsule.get("capsule_id") or "")
        capsule_hash = str(capsule.get("content_hash") or "")
        if not ledger_id or not ledger_head_hash or not capsule_id or not capsule_hash:
            raise ValueError("SIGNED_ANCHOR_SOURCE_INCOMPLETE")
        existing = self.db.query_one(
            "SELECT * FROM signed_evidence_anchors WHERE ledger_id=? AND ledger_head_hash=? AND capsule_hash=? ORDER BY created_at DESC LIMIT 1",
            (ledger_id, ledger_head_hash, capsule_hash),
        )
        if existing:
            return self.verify_anchor(str(existing.get("anchor_id") or ""))
        key, key_id, key_source = self._load_signing_key()
        created_at = self.db.now()
        core = {
            "ledger_id": ledger_id,
            "ledger_head_hash": ledger_head_hash,
            "capsule_id": capsule_id,
            "capsule_hash": capsule_hash,
            "algorithm": "HMAC-SHA256",
            "key_id": key_id,
            "key_source": key_source,
            "reason": str(reason or "evidence_capture"),
            "created_at": created_at,
        }
        signature = hmac.new(key, self._anchor_message(core), hashlib.sha256).hexdigest()
        anchor_id = f"SEA-{stable_hash({**core, 'signature': signature})[:20].upper()}"
        content_hash = stable_hash({**core, "signature": signature})
        self.db.execute(
            "INSERT INTO signed_evidence_anchors(anchor_id,ledger_id,ledger_head_hash,capsule_id,capsule_hash,algorithm,key_id,key_source,signature,reason,anchor_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (anchor_id, ledger_id, ledger_head_hash, capsule_id, capsule_hash, "HMAC-SHA256", key_id, key_source, signature, core["reason"], self.db.dumps(core), content_hash, created_at),
        )
        return self.verify_anchor(anchor_id)

    def verify_anchor(self, anchor_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM signed_evidence_anchors WHERE anchor_id=?", (anchor_id,)) or {}
        if not row:
            raise KeyError(anchor_id)
        core = self.db.loads(row.get("anchor_json"), {}) or {}
        signature = str(row.get("signature") or "")
        stored_hash = str(row.get("content_hash") or "")
        issues: list[str] = []
        if stable_hash({**core, "signature": signature}) != stored_hash:
            issues.append("ANCHOR_CONTENT_HASH_MISMATCH")
        try:
            key, key_id, _ = self._load_signing_key()
            if str(row.get("key_id") or "") != key_id:
                issues.append("ANCHOR_KEY_ID_MISMATCH")
            expected = hmac.new(key, self._anchor_message(core), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                issues.append("ANCHOR_SIGNATURE_MISMATCH")
        except Exception as exc:
            issues.append(f"ANCHOR_KEY_UNAVAILABLE:{type(exc).__name__}")
        capsule_issues: list[str] = []
        try:
            capsule = self.get_capsule(str(row.get("capsule_id") or ""))
            if capsule.get("content_hash") != row.get("capsule_hash"):
                capsule_issues.append("ANCHOR_CAPSULE_HASH_MISMATCH")
        except Exception as exc:
            capsule_issues.append(f"ANCHOR_CAPSULE_INVALID:{type(exc).__name__}")
        issues.extend(capsule_issues)
        return {
            "authority": self.ANCHOR_AUTHORITY,
            "contract_version": self.CONTRACT_VERSION,
            "anchor_id": str(row.get("anchor_id") or ""),
            "ledger_id": str(row.get("ledger_id") or ""),
            "ledger_head_hash": str(row.get("ledger_head_hash") or ""),
            "capsule_id": str(row.get("capsule_id") or ""),
            "capsule_hash": str(row.get("capsule_hash") or ""),
            "algorithm": str(row.get("algorithm") or ""),
            "key_id": str(row.get("key_id") or ""),
            "key_source": str(row.get("key_source") or ""),
            "signature": signature,
            "reason": str(row.get("reason") or ""),
            "content_hash": stored_hash,
            "created_at": str(row.get("created_at") or ""),
            "valid": not issues,
            "issues": issues,
        }

    def latest_anchor_for_head(self, ledger_id: str, ledger_head_hash: str, capsule_hash: str | None = None) -> dict[str, Any] | None:
        if capsule_hash:
            row = self.db.query_one(
                "SELECT anchor_id FROM signed_evidence_anchors WHERE ledger_id=? AND ledger_head_hash=? AND capsule_hash=? ORDER BY created_at DESC LIMIT 1",
                (ledger_id, ledger_head_hash, capsule_hash),
            )
        else:
            row = self.db.query_one(
                "SELECT anchor_id FROM signed_evidence_anchors WHERE ledger_id=? AND ledger_head_hash=? ORDER BY created_at DESC LIMIT 1",
                (ledger_id, ledger_head_hash),
            )
        if not row:
            return None
        return self.verify_anchor(str(row.get("anchor_id") or ""))

    def anchors_for_ledger(self, ledger_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all("SELECT anchor_id FROM signed_evidence_anchors WHERE ledger_id=? ORDER BY created_at DESC", (ledger_id,))
        items = []
        for row in rows:
            try:
                items.append(self.verify_anchor(str(row.get("anchor_id") or "")))
            except Exception:
                continue
        return items
