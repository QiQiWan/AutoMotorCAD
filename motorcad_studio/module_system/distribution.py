"""Fail-closed product distribution and static-asset compatibility validation."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..release import (
    API_CONTRACT_VERSION,
    BUILD_ID,
    BUILTIN_MODULE_CONTRACTS,
    FRONTEND_MODULE_DESCRIPTORS,
    MODULE_CATALOG_VERSION,
    PRODUCT_VERSION,
    RELEASE_TRAIN,
    STATIC_ASSET_VERSION,
)


def _issue(code: str, message: str, *, path: str = "") -> dict[str, Any]:
    return {"code": code, "message": message, "path": path, "blocking": True}


def _extract_js_string(text: str, key: str) -> str:
    match = re.search(rf'["\']?{re.escape(key)}["\']?\s*:\s*["\']([^"\']*)["\']', text)
    return match.group(1) if match else ""




_STATIC_IMPLEMENTATION_HEADER_RE = re.compile(
    r"MotorCAD Studio V?(?P<version>\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)"
)


def _extract_release_manifest(text: str) -> dict[str, Any]:
    match = re.search(r"const\s+manifest\s*=\s*(\{.*?\})\s*;", text, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _static_implementation_headers(static_dir: Path, legacy_source_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for root, label in ((static_dir, "static"), (legacy_source_dir, "frontend_legacy")):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.js")):
            try:
                header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:5])
            except Exception:
                continue
            match = _STATIC_IMPLEMENTATION_HEADER_RE.search(header)
            if match:
                rows.append({
                    "path": f"{label}/{path.relative_to(root).as_posix()}",
                    "implementation_version": match.group("version"),
                })
    return rows


def _runtime_capsule_catalog(static_dir: Path) -> dict[str, Any]:
    catalog_path = Path(static_dir) / "core" / "classic-runtime.catalog.json"
    if not catalog_path.is_file():
        return {}
    try:
        value = json.loads(catalog_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def validate_distribution(static_dir: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Validate that one package supplies one coherent product release.

    This guard compares only distribution-scoped values. Historical module contract
    identifiers are deliberately excluded from direct equality with the product
    version.
    """
    static_dir = Path(static_dir)
    package_dir = static_dir.parent
    legacy_source_dir = package_dir / "frontend_legacy"
    issues: list[dict[str, Any]] = []
    index_path = static_dir / "index.html"
    scripts: list[tuple[str, str]] = []
    styles: list[tuple[str, str]] = []
    document_version = ""
    document_release_train = ""
    capsule_catalog: dict[str, Any] = {}
    runtime_paths: list[str] = []

    if not index_path.is_file():
        issues.append(_issue("INDEX_HTML_MISSING", "static/index.html is missing", path=str(index_path)))
        html = ""
    else:
        html = index_path.read_text(encoding="utf-8")
        scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', html)
        styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', html)
        version_match = re.search(r'<html\b[^>]*\bdata-studio-version="([^"]+)"', html, re.IGNORECASE)
        train_match = re.search(r'<body\b[^>]*\bdata-release-train="([^"]+)"', html, re.IGNORECASE)
        document_version = version_match.group(1) if version_match else ""
        document_release_train = train_match.group(1) if train_match else ""
        if document_version != PRODUCT_VERSION:
            issues.append(_issue(
                "DOCUMENT_PRODUCT_VERSION_MISMATCH",
                f"index product version {document_version!r} does not match package {PRODUCT_VERSION!r}",
                path=str(index_path),
            ))
        if document_release_train != RELEASE_TRAIN:
            issues.append(_issue(
                "DOCUMENT_RELEASE_TRAIN_MISMATCH",
                f"index release train {document_release_train!r} does not match package {RELEASE_TRAIN!r}",
                path=str(index_path),
            ))

        asset_rows = scripts + styles
        if not asset_rows:
            issues.append(_issue("STATIC_ASSET_CATALOG_EMPTY", "index contains no versioned static assets", path=str(index_path)))
        mismatched_versions = sorted({version for _, version in asset_rows if version != STATIC_ASSET_VERSION})
        if mismatched_versions:
            issues.append(_issue(
                "STATIC_ASSET_VERSION_MISMATCH",
                f"expected asset version {STATIC_ASSET_VERSION!r}; found {mismatched_versions}",
                path=str(index_path),
            ))
        direct_expected = {("core/bootstrap.js", STATIC_ASSET_VERSION), ("app.css", STATIC_ASSET_VERSION)}
        if set(asset_rows) != direct_expected or len(asset_rows) != 2:
            issues.append(_issue(
                "FRONTEND_DIRECT_ASSET_MISMATCH",
                f"expected bootstrap.js and app.css only; found {asset_rows!r}",
                path=str(index_path),
            ))
        paths = [path for path, _ in asset_rows]
        duplicates = sorted(path for path, count in Counter(paths).items() if count > 1)
        if duplicates:
            issues.append(_issue("STATIC_ASSET_DUPLICATE", f"duplicate index assets: {duplicates}", path=str(index_path)))
        missing = sorted(path for path in paths if not (static_dir / path).is_file())
        if missing:
            issues.append(_issue("STATIC_ASSET_MISSING", f"missing static assets: {missing}", path=str(index_path)))

        capsule_catalog = _runtime_capsule_catalog(static_dir)
        runtime_catalog_path = static_dir / "core" / "classic-runtime.catalog.json"
        runtime_source_path = static_dir / "core" / "classic-runtime-source.js"
        source_rows = capsule_catalog.get("sources") if isinstance(capsule_catalog, dict) else []
        runtime_paths = [str(row.get("runtime_path") or "") for row in source_rows if isinstance(row, dict)]
        if not runtime_paths or int(capsule_catalog.get("source_count") or 0) != len(runtime_paths):
            issues.append(_issue("FRONTEND_RUNTIME_CAPSULE_EMPTY", "classic runtime capsule is missing or inconsistent", path=str(runtime_catalog_path)))
        if not runtime_source_path.is_file():
            issues.append(_issue("FRONTEND_RUNTIME_CAPSULE_SOURCE_MISSING", "classic-runtime-source.js is missing", path=str(runtime_source_path)))
        if len(runtime_paths) != len(set(runtime_paths)):
            issues.append(_issue("FRONTEND_RUNTIME_SOURCE_DUPLICATE", "classic runtime capsule contains duplicate sources", path=str(runtime_catalog_path)))
        for required, position in (("/static/release-manifest.js", 0), ("/static/module-registry.js", -1)):
            count = runtime_paths.count(required)
            if count != 1:
                issues.append(_issue("RELEASE_BOOTSTRAP_SOURCE_COUNT", f"{required} must occur once; found {count}", path=str(runtime_catalog_path)))
            elif runtime_paths[position] != required:
                issues.append(_issue("RELEASE_BOOTSTRAP_SOURCE_ORDER", f"{required} is in the wrong capsule position", path=str(runtime_catalog_path)))
        runtime_missing = sorted(
            item for item in runtime_paths
            if not (legacy_source_dir / item.removeprefix("/static/")).is_file()
        )
        if runtime_missing:
            issues.append(_issue("FRONTEND_RUNTIME_SOURCE_MISSING", f"missing legacy sources: {runtime_missing}", path=str(runtime_catalog_path)))


    release_js_path = legacy_source_dir / "release-manifest.js"
    release_js_values: dict[str, str] = {}
    release_js_payload: dict[str, Any] = {}
    if not release_js_path.is_file():
        issues.append(_issue("STATIC_RELEASE_MANIFEST_MISSING", "release-manifest.js is missing", path=str(release_js_path)))
    else:
        release_js = release_js_path.read_text(encoding="utf-8")
        release_js_payload = _extract_release_manifest(release_js)
        if not release_js_payload:
            issues.append(_issue(
                "STATIC_RELEASE_MANIFEST_INVALID",
                "release-manifest.js does not contain a parseable generated manifest",
                path=str(release_js_path),
            ))
        expected_js = {
            "productVersion": PRODUCT_VERSION,
            "assetVersion": STATIC_ASSET_VERSION,
            "releaseTrain": RELEASE_TRAIN,
            "buildId": BUILD_ID,
            "apiContractVersion": API_CONTRACT_VERSION,
            "moduleCatalogVersion": MODULE_CATALOG_VERSION,
        }
        for key, expected in expected_js.items():
            actual = release_js_payload.get(key) if release_js_payload else _extract_js_string(release_js, key)
            release_js_values[key] = str(actual or "")
            if actual != expected:
                issues.append(_issue(
                    "STATIC_RELEASE_MANIFEST_MISMATCH",
                    f"{key} is {actual!r}; expected {expected!r}",
                    path=str(release_js_path),
                ))
        if release_js_payload.get("moduleContracts") != BUILTIN_MODULE_CONTRACTS:
            issues.append(_issue(
                "STATIC_MODULE_CONTRACT_CATALOG_MISMATCH",
                "release-manifest.js moduleContracts differ from motorcad_studio.release",
                path=str(release_js_path),
            ))

    module_registry_path = legacy_source_dir / "module-registry.js"
    frontend_module_ids: list[str] = []
    frontend_module_globals: list[str] = []
    if not module_registry_path.is_file():
        issues.append(_issue("STATIC_MODULE_REGISTRY_MISSING", "module-registry.js is missing", path=str(module_registry_path)))
    else:
        module_registry_text = module_registry_path.read_text(encoding="utf-8")
        frontend_module_ids = re.findall(r'"id"\s*:\s*"([^"]+)"', module_registry_text)
        frontend_module_globals = re.findall(r'"global"\s*:\s*"([^"]+)"', module_registry_text)
        expected_frontend_ids = [str(row["module_id"]) for row in FRONTEND_MODULE_DESCRIPTORS]
        expected_frontend_globals = [str(row["global"]) for row in FRONTEND_MODULE_DESCRIPTORS]
        if frontend_module_ids != expected_frontend_ids:
            issues.append(_issue(
                "STATIC_FRONTEND_MODULE_CATALOG_MISMATCH",
                f"module ids are {frontend_module_ids!r}; expected {expected_frontend_ids!r}",
                path=str(module_registry_path),
            ))
        if frontend_module_globals != expected_frontend_globals:
            issues.append(_issue(
                "STATIC_FRONTEND_MODULE_GLOBALS_MISMATCH",
                f"module globals are {frontend_module_globals!r}; expected {expected_frontend_globals!r}",
                path=str(module_registry_path),
            ))
        version_match = re.search(
            r"Generated frontend module catalog for MotorCAD Studio ([0-9]+\.[0-9]+\.[0-9]+)\.",
            module_registry_text,
        )
        module_registry_version = version_match.group(1) if version_match else ""
        if module_registry_version != PRODUCT_VERSION:
            issues.append(_issue(
                "STATIC_FRONTEND_MODULE_IMPLEMENTATION_VERSION_MISMATCH",
                f"module registry version {module_registry_version!r}; expected {PRODUCT_VERSION!r}",
                path=str(module_registry_path),
            ))

    static_implementation_headers = _static_implementation_headers(static_dir, legacy_source_dir)
    for row in static_implementation_headers:
        actual = row["implementation_version"]
        if actual != PRODUCT_VERSION:
            issues.append(_issue(
                "STATIC_IMPLEMENTATION_HEADER_VERSION_MISMATCH",
                f"{row['path']} implementation header is {actual!r}; expected {PRODUCT_VERSION!r}",
                path=str(static_dir / row["path"]),
            ))

    distribution_manifest: dict[str, Any] = {}
    product_module_catalog_file: dict[str, Any] = {}
    if manifest_path is not None:
        manifest_path = Path(manifest_path)
        if not manifest_path.is_file():
            issues.append(_issue("DISTRIBUTION_MANIFEST_MISSING", "RELEASE_MANIFEST.json is missing", path=str(manifest_path)))
        else:
            try:
                parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
                distribution_manifest = parsed if isinstance(parsed, dict) else {}
            except Exception as exc:
                issues.append(_issue("DISTRIBUTION_MANIFEST_INVALID", f"cannot parse manifest: {exc}", path=str(manifest_path)))
            expected_manifest = {
                "authority": "MotorCADStudioDistributionManifestV1",
                "version": PRODUCT_VERSION,
                "release_train": RELEASE_TRAIN,
                "build_id": BUILD_ID,
                "static_asset_version": STATIC_ASSET_VERSION,
                "api_contract_version": API_CONTRACT_VERSION,
                "module_catalog_version": MODULE_CATALOG_VERSION,
            }
            for key, expected in expected_manifest.items():
                actual = distribution_manifest.get(key)
                if actual != expected:
                    issues.append(_issue(
                        "DISTRIBUTION_MANIFEST_MISMATCH",
                        f"{key} is {actual!r}; expected {expected!r}",
                        path=str(manifest_path),
                    ))
            if distribution_manifest.get("module_contracts") != BUILTIN_MODULE_CONTRACTS:
                issues.append(_issue(
                    "DISTRIBUTION_MODULE_CONTRACT_CATALOG_MISMATCH",
                    "RELEASE_MANIFEST.json module_contracts differ from motorcad_studio.release",
                    path=str(manifest_path),
                ))

        product_catalog_path = manifest_path.parent / "MODULE_CATALOG.json"
        if not product_catalog_path.is_file():
            issues.append(_issue(
                "PRODUCT_MODULE_CATALOG_FILE_MISSING",
                "MODULE_CATALOG.json is missing",
                path=str(product_catalog_path),
            ))
        else:
            try:
                parsed = json.loads(product_catalog_path.read_text(encoding="utf-8"))
                product_module_catalog_file = parsed if isinstance(parsed, dict) else {}
            except Exception as exc:
                issues.append(_issue(
                    "PRODUCT_MODULE_CATALOG_FILE_INVALID",
                    f"cannot parse module catalog: {exc}",
                    path=str(product_catalog_path),
                ))
            expected_catalog_values = {
                "authority": "StudioProductModuleCatalogV1",
                "catalog_version": MODULE_CATALOG_VERSION,
                "product_version": PRODUCT_VERSION,
                "compatible": True,
                "module_count": len(BUILTIN_MODULE_CONTRACTS),
            }
            for key, expected in expected_catalog_values.items():
                actual = product_module_catalog_file.get(key)
                if actual != expected:
                    issues.append(_issue(
                        "PRODUCT_MODULE_CATALOG_FILE_MISMATCH",
                        f"{key} is {actual!r}; expected {expected!r}",
                        path=str(product_catalog_path),
                    ))
            file_modules = product_module_catalog_file.get("modules") or []
            module_rows = {str(row.get("module_id") or ""): row for row in file_modules if isinstance(row, dict)}
            if set(module_rows) != set(BUILTIN_MODULE_CONTRACTS):
                issues.append(_issue(
                    "PRODUCT_MODULE_CATALOG_IDS_MISMATCH",
                    f"module ids differ; found {sorted(module_rows)!r}",
                    path=str(product_catalog_path),
                ))
            for module_id, contract_version in BUILTIN_MODULE_CONTRACTS.items():
                row = module_rows.get(module_id) or {}
                if row.get("implementation_version") != PRODUCT_VERSION:
                    issues.append(_issue(
                        "PRODUCT_MODULE_IMPLEMENTATION_VERSION_MISMATCH",
                        f"{module_id} implementation is {row.get('implementation_version')!r}; expected {PRODUCT_VERSION!r}",
                        path=str(product_catalog_path),
                    ))
                if row.get("contract_version") != contract_version:
                    issues.append(_issue(
                        "PRODUCT_MODULE_CONTRACT_VERSION_MISMATCH",
                        f"{module_id} contract is {row.get('contract_version')!r}; expected {contract_version!r}",
                        path=str(product_catalog_path),
                    ))

    return {
        "authority": "StudioDistributionCompatibilityV1",
        "compatible": not issues,
        "product_version": PRODUCT_VERSION,
        "asset_version": STATIC_ASSET_VERSION,
        "release_train": RELEASE_TRAIN,
        "build_id": BUILD_ID,
        "module_catalog_version": MODULE_CATALOG_VERSION,
        "document_version": document_version,
        "document_release_train": document_release_train,
        "script_count": len(scripts),
        "style_count": len(styles),
        "runtime_asset_count": 1,
        "classic_runtime_source_count": len(runtime_paths),
        "classic_runtime_source_sha256": capsule_catalog.get("source_sha256") if 'capsule_catalog' in locals() else None,
        "release_manifest_values": release_js_values,
        "frontend_module_descriptor_count": len(frontend_module_ids),
        "frontend_module_descriptor_ids": frontend_module_ids,
        "static_implementation_header_count": len(static_implementation_headers),
        "static_implementation_headers": static_implementation_headers,
        "product_module_catalog_file": {
            "authority": product_module_catalog_file.get("authority"),
            "catalog_version": product_module_catalog_file.get("catalog_version"),
            "product_version": product_module_catalog_file.get("product_version"),
            "compatible": product_module_catalog_file.get("compatible"),
            "module_count": product_module_catalog_file.get("module_count"),
        },
        "blocking_issue_count": len(issues),
        "issues": issues,
    }


__all__ = ["validate_distribution"]
