"""Audit built-in module and distribution compatibility without starting the server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..module_system import build_builtin_module_registry, product_module_catalog_report, validate_distribution
from ..release import BUILD_ID, PRODUCT_VERSION, RELEASE_TRAIN


def audit(package_root: Path | None = None) -> dict:
    package_root = Path(package_root or Path(__file__).resolve().parents[1]).resolve()
    distribution_root = package_root.parent
    module_report = build_builtin_module_registry().validate()
    product_catalog_report = product_module_catalog_report()
    distribution_report = validate_distribution(
        package_root / "static",
        distribution_root / "RELEASE_MANIFEST.json",
    )
    return {
        "authority": "StudioModuleAuditV1",
        "product_version": PRODUCT_VERSION,
        "release_train": RELEASE_TRAIN,
        "build_id": BUILD_ID,
        "compatible": bool(
            module_report.get("compatible")
            and product_catalog_report.get("compatible")
            and distribution_report.get("compatible")
        ),
        "product_module_catalog": product_catalog_report,
        "module_compatibility": module_report,
        "distribution_compatibility": distribution_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, help="path to the motorcad_studio package")
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args(argv)
    report = audit(args.package_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["compatible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
