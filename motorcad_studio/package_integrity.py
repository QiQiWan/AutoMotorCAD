"""Build and verify the distribution content manifest.

The verifier is intentionally fail-closed for immutable distribution content: it
checks declared files, rejects undeclared application files, and validates sizes
and SHA-256 hashes. Mutable runtime-state roots are deliberately outside the
distribution hash boundary so normal diagnostics, databases, logs and results do
not invalidate the installed application after the first successful run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .release import BUILD_ID, PRODUCT_VERSION, RELEASE_TRAIN

MANIFEST_NAME = "PACKAGE_CONTENT_MANIFEST.json"
IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
# Runtime-owned state is mutable by design and must never be part of the immutable
# package hash boundary. Exact top-level matching prevents a directory named
# ``motorcad_studio/data`` from being silently ignored.
MUTABLE_RUNTIME_ROOTS = frozenset({"data", "runtime", "results", "logs", "baselines", "factory"})


def _ignored(relative: Path) -> bool:
    if relative.parts and relative.parts[0] in MUTABLE_RUNTIME_ROOTS:
        return True
    return any(part in IGNORED_PARTS for part in relative.parts) or relative.suffix.lower() in IGNORED_SUFFIXES


def _included_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.as_posix() == MANIFEST_NAME or _ignored(relative):
            continue
        yield path


def _distribution_symlinks(root: Path) -> list[str]:
    rows: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        if path.is_symlink():
            rows.append(relative.as_posix())
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_relative(value: Any) -> str | None:
    text = str(value or "").replace("\\", "/")
    candidate = PurePosixPath(text)
    if not text or candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    normalized = candidate.as_posix()
    return normalized if normalized == text else None


def build_manifest(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    symlinks = _distribution_symlinks(root)
    if symlinks:
        raise RuntimeError(f"distribution symlinks are not supported: {', '.join(symlinks)}")
    for path in _included_files(root):
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        entries.append({
            "path": relative,
            "size_bytes": size,
            "sha256": _sha256(path),
        })
    return {
        "authority": "MotorCADStudioPackageContentManifestV1",
        "product_version": PRODUCT_VERSION,
        "release_train": RELEASE_TRAIN,
        "build_id": BUILD_ID,
        "algorithm": "SHA-256",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "immutable distribution files; excludes this manifest, mutable runtime-state roots, virtual environments, VCS metadata and bytecode/test caches",
        "unexpected_file_policy": "reject",
        "mutable_runtime_roots": sorted(MUTABLE_RUNTIME_ROOTS),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "entries": entries,
    }


def write_manifest(root: Path) -> Path:
    root = Path(root).resolve()
    target = root / MANIFEST_NAME
    target.write_text(json.dumps(build_manifest(root), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def verify_manifest(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / MANIFEST_NAME
    issues: list[dict[str, Any]] = []
    if not path.is_file():
        return {
            "authority": "MotorCADStudioPackageIntegrityV1",
            "product_version": PRODUCT_VERSION,
            "compatible": False,
            "declared_file_count": 0,
            "actual_file_count": 0,
            "checked": 0,
            "issues": [{"code": "MANIFEST_MISSING", "path": MANIFEST_NAME}],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "authority": "MotorCADStudioPackageIntegrityV1",
            "product_version": PRODUCT_VERSION,
            "compatible": False,
            "declared_file_count": 0,
            "actual_file_count": 0,
            "checked": 0,
            "issues": [{"code": "MANIFEST_INVALID", "path": MANIFEST_NAME, "detail": str(exc)}],
        }

    expected_metadata = {
        "authority": "MotorCADStudioPackageContentManifestV1",
        "product_version": PRODUCT_VERSION,
        "release_train": RELEASE_TRAIN,
        "build_id": BUILD_ID,
        "algorithm": "SHA-256",
        "unexpected_file_policy": "reject",
        "mutable_runtime_roots": sorted(MUTABLE_RUNTIME_ROOTS),
    }
    for key, expected in expected_metadata.items():
        actual = payload.get(key)
        if actual != expected:
            issues.append({
                "code": "MANIFEST_METADATA_MISMATCH",
                "path": MANIFEST_NAME,
                "field": key,
                "expected": expected,
                "actual": actual,
            })

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raw_entries = []
        issues.append({"code": "MANIFEST_ENTRIES_INVALID", "path": MANIFEST_NAME})

    declared: dict[str, dict[str, Any]] = {}
    declared_bytes = 0
    for index, row in enumerate(raw_entries):
        if not isinstance(row, dict):
            issues.append({"code": "MANIFEST_ENTRY_INVALID", "path": MANIFEST_NAME, "index": index})
            continue
        relative = _canonical_relative(row.get("path"))
        if relative is None:
            issues.append({"code": "MANIFEST_PATH_INVALID", "path": str(row.get("path") or ""), "index": index})
            continue
        if relative in declared:
            issues.append({"code": "MANIFEST_PATH_DUPLICATE", "path": relative})
            continue
        try:
            size = int(row.get("size_bytes"))
        except (TypeError, ValueError):
            size = -1
        digest = str(row.get("sha256") or "")
        if size < 0:
            issues.append({"code": "MANIFEST_SIZE_INVALID", "path": relative, "actual": row.get("size_bytes")})
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            issues.append({"code": "MANIFEST_HASH_INVALID", "path": relative, "actual": digest})
        declared[relative] = {"size_bytes": size, "sha256": digest.lower()}
        if size >= 0:
            declared_bytes += size

    actual_paths: dict[str, Path] = {}
    symlink_paths = _distribution_symlinks(root)
    for candidate in _included_files(root):
        relative = candidate.relative_to(root).as_posix()
        actual_paths[relative] = candidate
    for relative in symlink_paths:
        issues.append({"code": "DISTRIBUTION_SYMLINK_UNSUPPORTED", "path": relative})

    for relative in sorted(set(actual_paths) - set(declared)):
        issues.append({"code": "UNEXPECTED_FILE", "path": relative})
    for relative in sorted(set(declared) - set(actual_paths)):
        issues.append({"code": "FILE_MISSING", "path": relative})

    checked = 0
    actual_bytes = 0
    for relative in sorted(set(declared) & set(actual_paths)):
        row = declared[relative]
        candidate = actual_paths[relative]
        checked += 1
        size = candidate.stat().st_size
        actual_bytes += size
        if size != row["size_bytes"]:
            issues.append({
                "code": "FILE_SIZE_MISMATCH",
                "path": relative,
                "expected": row["size_bytes"],
                "actual": size,
            })
            continue
        digest = _sha256(candidate)
        if digest != row["sha256"]:
            issues.append({
                "code": "FILE_HASH_MISMATCH",
                "path": relative,
                "expected": row["sha256"],
                "actual": digest,
            })

    declared_count = len(declared)
    actual_count = len(actual_paths)
    if declared_count != int(payload.get("file_count") or -1):
        issues.append({
            "code": "MANIFEST_COUNT_MISMATCH",
            "path": MANIFEST_NAME,
            "expected": declared_count,
            "actual": payload.get("file_count"),
        })
    if declared_bytes != int(payload.get("total_bytes") or -1):
        issues.append({
            "code": "MANIFEST_TOTAL_BYTES_MISMATCH",
            "path": MANIFEST_NAME,
            "expected": declared_bytes,
            "actual": payload.get("total_bytes"),
        })

    return {
        "authority": "MotorCADStudioPackageIntegrityV1",
        "product_version": PRODUCT_VERSION,
        "compatible": not issues,
        "declared_file_count": declared_count,
        "actual_file_count": actual_count,
        "declared_total_bytes": declared_bytes,
        "actual_total_bytes": sum(path.stat().st_size for path in actual_paths.values()),
        "checked": checked,
        "unexpected_file_count": len(set(actual_paths) - set(declared)),
        "missing_file_count": len(set(declared) - set(actual_paths)),
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    if args.write:
        target = write_manifest(args.root)
        report = verify_manifest(args.root)
        report["written"] = str(target)
    else:
        report = verify_manifest(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("compatible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
