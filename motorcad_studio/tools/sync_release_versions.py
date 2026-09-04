"""Synchronize and audit MotorCAD Studio product-release metadata.

Only product/distribution metadata is synchronized. Module contract, schema, plugin,
and Motor-CAD runtime versions remain independently versioned compatibility
boundaries.

Usage::

    python -m motorcad_studio.tools.sync_release_versions --write
    python -m motorcad_studio.tools.sync_release_versions --check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..module_system.catalog import product_module_catalog_report
from ..package_integrity import MUTABLE_RUNTIME_ROOTS
from ..release import (
    API_CONTRACT_VERSION,
    BUILD_ID,
    BUILTIN_MODULE_CONTRACTS,
    FRONTEND_MODULE_DESCRIPTORS,
    MODULE_CATALOG_VERSION,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    RELEASE_TRAIN,
    REQUIRED_PYMOTORCAD_VERSION,
    STATIC_ASSET_VERSION,
    TARGET_MOTORCAD_VERSION,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION_ROOT = PACKAGE_ROOT.parent
STATIC_ROOT = PACKAGE_ROOT / "static"
LEGACY_SOURCE_ROOT = PACKAGE_ROOT / "frontend_legacy"


@dataclass
class SyncReport:
    mode: str
    changed: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)

    @property
    def compatible(self) -> bool:
        return not self.issues

    def issue(self, code: str, path: Path | str, detail: str) -> None:
        self.issues.append({"code": code, "path": str(path), "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "StudioReleaseSyncV1",
            "mode": self.mode,
            "product_version": PRODUCT_VERSION,
            "release_train": RELEASE_TRAIN,
            "build_id": BUILD_ID,
            "compatible": self.compatible,
            "changed": list(dict.fromkeys(self.changed)),
            "checked": list(dict.fromkeys(self.checked)),
            "issues": self.issues,
        }


def _write_if_changed(path: Path, content: str, report: SyncReport) -> None:
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    if previous == content:
        report.checked.append(str(path.relative_to(DISTRIBUTION_ROOT)))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    report.changed.append(str(path.relative_to(DISTRIBUTION_ROOT)))


def _expect_exact(path: Path, expected: str, report: SyncReport) -> None:
    report.checked.append(str(path.relative_to(DISTRIBUTION_ROOT)))
    if not path.is_file():
        report.issue("FILE_MISSING", path, "required generated release file is missing")
        return
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        report.issue("GENERATED_FILE_OUT_OF_SYNC", path, "run --write to regenerate from motorcad_studio.release")


def _render_release_manifest_js() -> str:
    payload = {
        "authority": "StudioReleaseAuthorityV1",
        "productName": PRODUCT_NAME,
        "productVersion": PRODUCT_VERSION,
        "releaseTrain": RELEASE_TRAIN,
        "buildId": BUILD_ID,
        "assetVersion": STATIC_ASSET_VERSION,
        "apiContractVersion": API_CONTRACT_VERSION,
        "moduleCatalogVersion": MODULE_CATALOG_VERSION,
        "compatibilityPolicy": {
            "productRelease": "exact",
            "staticAssets": "exact",
            "builtInImplementation": "exact",
            "moduleContracts": "declared-boundary",
            "externalRuntime": "capability-qualified",
        },
        "externalRuntime": {
            "targetMotorcadVersion": TARGET_MOTORCAD_VERSION,
            "requiredPymotorcadVersion": REQUIRED_PYMOTORCAD_VERSION,
        },
        "moduleContracts": BUILTIN_MODULE_CONTRACTS,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    return (
        f"/* Generated from motorcad_studio.release for the V{PRODUCT_VERSION} distribution. */\n"
        "(() => {\n"
        f"  const manifest = {serialized.replace(chr(10), chr(10) + '  ')};\n"
        "  window.MCS_RELEASE = Object.freeze(manifest);\n"
        "})();\n"
    )


def _render_module_registry_js() -> str:
    descriptors = [
        {
            "id": row["module_id"],
            "contractKey": row["module_id"],
            "global": row["global"],
            "required": bool(row.get("required", True)),
            "dependencies": list(row.get("dependencies") or ()),
        }
        for row in FRONTEND_MODULE_DESCRIPTORS
    ]
    serialized = json.dumps(descriptors, ensure_ascii=False, indent=2, sort_keys=False)
    return f"""/* Generated frontend module catalog for MotorCAD Studio {PRODUCT_VERSION}. */
(() => {{
  const release = () => window.MCS_RELEASE || {{}};
  const descriptors = Object.freeze({serialized});

  function snapshot() {{
    const manifest = release();
    const productVersion = String(manifest.productVersion || '');
    const assetVersion = String(manifest.assetVersion || '');
    const documentVersion = String(document.documentElement.dataset.studioVersion || '');
    const contracts = manifest.moduleContracts || {{}};
    const moduleIds = new Set(descriptors.map(row => row.id));
    const contractIds = new Set(Object.keys(contracts));
    const loadedById = new Map();
    const issues = [];

    const modules = descriptors.map(row => {{
      const loaded = Boolean(window[row.global]);
      const contractVersion = String(contracts[row.contractKey] || '');
      loadedById.set(row.id, loaded);
      if (row.required && !loaded) {{
        issues.push({{code:'FRONTEND_MODULE_NOT_LOADED', module_id:row.id, detail:row.global}});
      }}
      if (!contractVersion) {{
        issues.push({{code:'FRONTEND_CONTRACT_NOT_DECLARED', module_id:row.id, detail:row.contractKey}});
      }}
      for (const dependency of row.dependencies) {{
        if (!moduleIds.has(dependency) && !contractIds.has(dependency)) {{
          issues.push({{code:'FRONTEND_DEPENDENCY_UNDECLARED', module_id:row.id, detail:dependency}});
        }}
      }}
      return {{
        module_id: row.id,
        implementation_version: productVersion,
        contract_version: contractVersion,
        global: row.global,
        loaded,
        dependencies: [...row.dependencies],
      }};
    }});

    for (const row of descriptors) {{
      if (!loadedById.get(row.id)) continue;
      for (const dependency of row.dependencies) {{
        if (moduleIds.has(dependency) && !loadedById.get(dependency)) {{
          issues.push({{code:'FRONTEND_DEPENDENCY_NOT_LOADED', module_id:row.id, detail:dependency}});
        }}
      }}
    }}
    if (!productVersion || documentVersion !== productVersion || assetVersion !== productVersion) {{
      issues.push({{
        code:'FRONTEND_RELEASE_VERSION_MISMATCH',
        module_id:'frontend.release',
        detail:`document=${{documentVersion || '-'}} manifest=${{productVersion || '-'}} assets=${{assetVersion || '-'}}`,
      }});
    }}
    return {{
      authority:'FrontendModuleRegistryV1',
      catalog_version:String(manifest.moduleCatalogVersion || ''),
      product_version:productVersion,
      asset_version:assetVersion,
      document_version:documentVersion,
      compatible:issues.length === 0,
      module_count:modules.length,
      issues,
      modules,
    }};
  }}

  function publish() {{
    const report = snapshot();
    document.documentElement.dataset.moduleCompatibility = report.compatible ? 'compatible' : 'incompatible';
    window.dispatchEvent(new CustomEvent('mcs:frontend-modules-validated', {{detail:report}}));
    return report;
  }}

  window.MCSFrontendModuleRegistry = Object.freeze({{descriptors, snapshot, publish}});
  document.addEventListener('DOMContentLoaded', publish, {{once:true}});
  window.addEventListener('mcs:bootstrap-ready', publish);
}})();
"""


def _sync_index_text(text: str) -> str:
    text = re.sub(
        r'(<html\b[^>]*\bdata-studio-version=")[^"]*(")',
        rf'\g<1>{PRODUCT_VERSION}\2',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'(<body\b[^>]*\bdata-release-train=")[^"]*(")',
        rf'\g<1>{RELEASE_TRAIN}\2',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'(<span\s+class="version">)[^<]*(</span>)',
        rf'\g<1>{PRODUCT_VERSION}\2',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'((?:src|href)="/static/[^"?]+\?v=)[^"]+("[^>]*>)',
        rf'\g<1>{STATIC_ASSET_VERSION}\2',
        text,
        flags=re.IGNORECASE,
    )
    return text


def _audit_index(path: Path, report: SyncReport) -> None:
    report.checked.append(str(path.relative_to(DISTRIBUTION_ROOT)))
    if not path.is_file():
        report.issue("INDEX_HTML_MISSING", path, "static index is missing")
        return
    text = path.read_text(encoding="utf-8")
    doc = re.search(r'<html\b[^>]*\bdata-studio-version="([^"]+)"', text, re.IGNORECASE)
    if not doc or doc.group(1) != PRODUCT_VERSION:
        report.issue("INDEX_PRODUCT_VERSION_MISMATCH", path, f"expected {PRODUCT_VERSION}")
    release_train = re.search(r'<body\b[^>]*\bdata-release-train="([^"]+)"', text, re.IGNORECASE)
    if not release_train or release_train.group(1) != RELEASE_TRAIN:
        report.issue("INDEX_RELEASE_TRAIN_MISMATCH", path, f"expected {RELEASE_TRAIN}")
    asset_versions = re.findall(r'(?:src|href)="/static/[^"?]+\?v=([^"]+)"', text, re.IGNORECASE)
    if not asset_versions:
        report.issue("STATIC_ASSET_REFERENCES_MISSING", path, "no versioned static assets found")
    mismatched = sorted({value for value in asset_versions if value != STATIC_ASSET_VERSION})
    if mismatched:
        report.issue("STATIC_ASSET_VERSION_MISMATCH", path, f"expected {STATIC_ASSET_VERSION}; found {mismatched}")
    direct_scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', text, re.IGNORECASE)
    direct_styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', text, re.IGNORECASE)
    if direct_scripts != [("core/bootstrap.js", STATIC_ASSET_VERSION)]:
        report.issue(
            "FRONTEND_ENTRYPOINT_MISMATCH",
            path,
            f"expected one core/bootstrap.js entry; found {direct_scripts!r}",
        )
    if direct_styles != [("app.css", STATIC_ASSET_VERSION)]:
        report.issue(
            "FRONTEND_STYLESHEET_MISMATCH",
            path,
            f"expected one app.css stylesheet; found {direct_styles!r}",
        )
    body_match = re.search(r'<body\b[^>]*\bclass="([^"]*)"', text, re.IGNORECASE)
    body_classes = set((body_match.group(1) if body_match else "").split())
    if "studio-shell" not in body_classes:
        report.issue("FRONTEND_SHELL_HOOK_MISSING", path, "body must declare the stable studio-shell class")
    if any(re.fullmatch(r"studio-v\d[0-9a-z]*", item, re.IGNORECASE) for item in body_classes):
        report.issue("FRONTEND_VERSIONED_SHELL_HOOK", path, f"versioned body classes are not allowed: {sorted(body_classes)!r}")
    capsule_catalog = STATIC_ROOT / "core" / "classic-runtime.catalog.json"
    capsule_source = STATIC_ROOT / "core" / "classic-runtime-source.js"
    for required_path in (capsule_catalog, capsule_source):
        report.checked.append(str(required_path.relative_to(DISTRIBUTION_ROOT)))
        if not required_path.is_file():
            report.issue("FRONTEND_RUNTIME_CAPSULE_MISSING", required_path, "sealed classic runtime output is missing")
    if capsule_catalog.is_file():
        try:
            capsule = json.loads(capsule_catalog.read_text(encoding="utf-8"))
        except Exception as exc:
            report.issue("FRONTEND_RUNTIME_CATALOG_INVALID", capsule_catalog, str(exc))
            capsule = {}
        source_rows = capsule.get("sources") if isinstance(capsule, dict) else []
        runtime_paths = [str(row.get("runtime_path") or "") for row in source_rows if isinstance(row, dict)]
        if int(capsule.get("source_count") or 0) != len(runtime_paths) or not runtime_paths:
            report.issue("FRONTEND_RUNTIME_CATALOG_COUNT", capsule_catalog, "classic runtime source count is inconsistent")
        if len(runtime_paths) != len(set(runtime_paths)):
            report.issue("FRONTEND_RUNTIME_SOURCE_DUPLICATE", capsule_catalog, "duplicate classic runtime sources declared")
        if runtime_paths and runtime_paths[0] != "/static/release-manifest.js":
            report.issue("RELEASE_MANIFEST_RUNTIME_ORDER_INVALID", capsule_catalog, "release manifest must be the first capsule source")
        if runtime_paths and runtime_paths[-1] != "/static/module-registry.js":
            report.issue("MODULE_REGISTRY_RUNTIME_ORDER_INVALID", capsule_catalog, "module registry must be the final capsule source")
        missing = [
            item for item in runtime_paths
            if not (LEGACY_SOURCE_ROOT / item.removeprefix("/static/")).is_file()
        ]
        if missing:
            report.issue("FRONTEND_RUNTIME_SOURCE_MISSING", capsule_catalog, str(missing))


_STATIC_IMPLEMENTATION_HEADER_RE = re.compile(
    r"(?P<prefix>MotorCAD Studio V?)"
    r"(?P<version>\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)"
)


def _javascript_source_paths() -> list[Path]:
    return sorted({*STATIC_ROOT.rglob("*.js"), *LEGACY_SOURCE_ROOT.rglob("*.js")})


def _sync_static_implementation_headers(report: SyncReport, *, write: bool) -> None:
    for path in _javascript_source_paths():
        original = path.read_text(encoding="utf-8")
        header_limit = min(len(original), 1024)
        match = _STATIC_IMPLEMENTATION_HEADER_RE.search(original, 0, header_limit)
        if not match:
            continue
        actual = match.group("version")
        updated = (
            original[:match.start("version")]
            + PRODUCT_VERSION
            + original[match.end("version"):]
        )
        if write:
            _write_if_changed(path, updated, report)
        else:
            report.checked.append(str(path.relative_to(DISTRIBUTION_ROOT)))
            if actual != PRODUCT_VERSION:
                report.issue(
                    "STATIC_IMPLEMENTATION_HEADER_VERSION_MISMATCH",
                    path,
                    f"expected {PRODUCT_VERSION}; found {actual}",
                )


def _walk_update_studio_version(value: Any) -> bool:
    changed = False
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "studio_version" and isinstance(item, str):
                if item != PRODUCT_VERSION:
                    value[key] = PRODUCT_VERSION
                    changed = True
            else:
                changed = _walk_update_studio_version(item) or changed
    elif isinstance(value, list):
        for item in value:
            changed = _walk_update_studio_version(item) or changed
    return changed


def _sync_acceptance_json(path: Path, report: SyncReport, *, write: bool) -> None:
    if not path.is_file():
        report.issue("FILE_MISSING", path, "acceptance template is missing")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report.issue("JSON_INVALID", path, str(exc))
        return
    changed = _walk_update_studio_version(payload)
    expected = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if write:
        _write_if_changed(path, expected, report)
    else:
        report.checked.append(str(path.relative_to(DISTRIBUTION_ROOT)))
        if changed:
            report.issue("ACCEPTANCE_STUDIO_VERSION_MISMATCH", path, f"expected {PRODUCT_VERSION}")


def _sync_product_module_catalog(path: Path, report: SyncReport, *, write: bool) -> None:
    payload = product_module_catalog_report()
    expected = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if write:
        _write_if_changed(path, expected, report)
    else:
        _expect_exact(path, expected, report)
    if not payload.get("compatible"):
        report.issue(
            "PRODUCT_MODULE_CATALOG_INCOMPATIBLE",
            path,
            f"{payload.get('blocking_issue_count', 0)} blocking catalog coverage issue(s)",
        )


def _sync_distribution_manifest(path: Path, report: SyncReport, *, write: bool) -> None:
    """Generate one compact current-release manifest from authoritative metadata.

    Historical validation dumps, archive names and stage-specific fields are never
    carried forward. This prevents a clean package from advertising evidence or
    filenames that are no longer present.
    """
    catalog = product_module_catalog_report()
    static_headers: list[str] = []
    for static_path in _javascript_source_paths():
        static_text = static_path.read_text(encoding="utf-8")
        header_limit = min(len(static_text), 1024)
        header_match = _STATIC_IMPLEMENTATION_HEADER_RE.search(static_text, 0, header_limit)
        if header_match:
            static_headers.append(header_match.group("version"))
    matching_static_headers = sum(version == PRODUCT_VERSION for version in static_headers)
    convergence_status = (
        "PASS"
        if catalog.get("compatible") and matching_static_headers == len(static_headers)
        else "FAIL"
    )
    module_version_convergence = {
        "authority": "StudioModuleVersionConvergenceV1",
        "status": convergence_status,
        "product_version": PRODUCT_VERSION,
        "implementation_version_policy": "all built-in modules equal product version",
        "contract_version_policy": "independent declared compatibility boundary",
        "product_module_count": len(BUILTIN_MODULE_CONTRACTS),
        "backend_catalog_count": int(catalog.get("backend_catalog_count") or 0),
        "frontend_catalog_count": int(catalog.get("frontend_catalog_count") or 0),
        "cross_surface_module_count": int(catalog.get("cross_surface_count") or 0),
        "unrepresented_contract_count": int(catalog.get("blocking_issue_count") or 0),
        "module_catalog_file": "MODULE_CATALOG.json",
        "static_implementation_headers": {
            "count": len(static_headers),
            "matching_product_version": matching_static_headers,
        },
    }
    payload: dict[str, Any] = {
        "authority": "MotorCADStudioDistributionManifestV1",
        "product_name": PRODUCT_NAME,
        "version": PRODUCT_VERSION,
        "release_train": RELEASE_TRAIN,
        "build_id": BUILD_ID,
        "static_asset_version": STATIC_ASSET_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "module_catalog_version": MODULE_CATALOG_VERSION,
        "module_contracts": BUILTIN_MODULE_CONTRACTS,
        "release_candidate_gate": {
            "authority": "ReleaseCandidateGateV1",
            "release_state": "INTEGRATION_VALIDATED",
            "formal_workstation_qualification": "PENDING",
        },
        "module_version_convergence": module_version_convergence,
        "distribution": {
            "windows_entrypoint": "start.bat",
            "python_entrypoint": "motorcad_studio.launcher",
            "frontend_entrypoint": "/static/core/bootstrap.js",
            "stylesheet": "/static/app.css",
            "content_manifest": "PACKAGE_CONTENT_MANIFEST.json",
            "data_directory_policy": "user-profile-default",
            "mutable_runtime_roots": sorted(MUTABLE_RUNTIME_ROOTS),
            "package_integrity_scope": "immutable-distribution-only",
            "unexpected_file_policy": "reject",
        },
        "current_artifacts": {
            "readme": "README.md",
            "architecture": "docs/ARCHITECTURE.md",
            "deployment": "docs/DEPLOYMENT.md",
            "validation_scope": "docs/VALIDATION.md",
            "validation_evidence": "validation/evidence.json",
            "openapi_baseline": "validation/openapi_baseline.json",
        },
        "qualification_boundary": {
            "local_integration": "VALIDATED",
            "browser_gpu_e2e": "PENDING_TARGET_WORKSTATION",
            "licensed_motorcad": "PENDING_TARGET_WORKSTATION",
            "long_duration_soak": "PENDING_TARGET_WORKSTATION",
        },
    }
    expected = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if write:
        _write_if_changed(path, expected, report)
    else:
        _expect_exact(path, expected, report)


def synchronize(*, write: bool) -> SyncReport:
    report = SyncReport(mode="write" if write else "check")
    release_js = LEGACY_SOURCE_ROOT / "release-manifest.js"
    module_js = LEGACY_SOURCE_ROOT / "module-registry.js"
    expected_release_js = _render_release_manifest_js()
    expected_module_js = _render_module_registry_js()
    if write:
        _write_if_changed(release_js, expected_release_js, report)
        _write_if_changed(module_js, expected_module_js, report)
    else:
        _expect_exact(release_js, expected_release_js, report)
        _expect_exact(module_js, expected_module_js, report)

    index_path = STATIC_ROOT / "index.html"
    if write:
        if not index_path.is_file():
            report.issue("INDEX_HTML_MISSING", index_path, "cannot synchronize")
        else:
            _write_if_changed(index_path, _sync_index_text(index_path.read_text(encoding="utf-8")), report)

    _sync_static_implementation_headers(report, write=write)

    from .build_frontend_capsule import build as build_frontend_capsule
    capsule_report = build_frontend_capsule(check=not write)
    for changed in capsule_report.get("changed") or []:
        report.changed.append(str(changed))
    for issue in capsule_report.get("issues") or []:
        report.issue(str(issue.get("code") or "FRONTEND_RUNTIME_CAPSULE_INVALID"), str(issue.get("path") or ""), str(issue.get("detail") or ""))

    _audit_index(index_path, report)

    for path in sorted((PACKAGE_ROOT / "acceptance").glob("*.json")):
        _sync_acceptance_json(path, report, write=write)

    _sync_distribution_manifest(DISTRIBUTION_ROOT / "RELEASE_MANIFEST.json", report, write=write)
    _sync_product_module_catalog(DISTRIBUTION_ROOT / "MODULE_CATALOG.json", report, write=write)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="synchronize generated/static release metadata")
    mode.add_argument("--check", action="store_true", help="fail if release metadata is inconsistent")
    parser.add_argument("--output", type=Path, help="also write the JSON report to this path")
    args = parser.parse_args(argv)
    report = synchronize(write=args.write)
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
