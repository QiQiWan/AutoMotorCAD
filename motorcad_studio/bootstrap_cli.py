"""Dependency bootstrap used by the root ``start.bat`` launcher.

This module intentionally uses only the Python standard library.  It creates one
local virtual environment with access to system site packages, installs only
missing web/runtime dependencies, then transfers control to the real launcher.
The system-site-packages setting allows a workstation-managed PyMotorCAD install
to remain visible without bundling or replacing it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import site
import subprocess
import sys
import venv
from pathlib import Path
from typing import Iterable

from .release import PRODUCT_VERSION

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
CORE_IMPORTS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "PyYAML": "yaml",
    "psutil": "psutil",
    "pandas": "pandas",
    "httpx": "httpx",
}

_MUTABLE_DIR_ENV_VARS = (
    "MOTORCAD_STUDIO_DATA_DIR",
    "MOTORCAD_STUDIO_RUNTIME_DIR",
    "MOTORCAD_STUDIO_RESULTS_DIR",
    "MOTORCAD_STUDIO_BASELINES_DIR",
    "MOTORCAD_STUDIO_FACTORY_DIR",
    "MOTORCAD_STUDIO_LOG_DIR",
)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _sanitize_installed_runtime_environment() -> list[str]:
    """Remove stale in-program mutable-directory overrides from installed builds.

    Old installations could leave environment variables such as ``data`` or
    ``runtime``. Keeping those values would make a clean replacement deployment
    self-modifying again. Direct source checkouts and explicit portable-mode opt-in
    retain in-tree paths.
    """
    if (ROOT / "pyproject.toml").is_file() or os.getenv("MOTORCAD_STUDIO_ALLOW_IN_TREE_STATE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return []
    cleared: list[str] = []
    for name in _MUTABLE_DIR_ENV_VARS:
        raw = os.getenv(name)
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if _path_is_within(candidate, ROOT):
            os.environ.pop(name, None)
            cleared.append(name)
    return cleared


def _distribution_issues(limit: int = 8) -> list[str]:
    """Return concise package-integrity failures before touching local state."""
    from .package_integrity import verify_manifest

    report = verify_manifest(ROOT)
    if report.get("compatible"):
        return []
    rows: list[str] = []
    for issue in (report.get("issues") or [])[: max(1, int(limit))]:
        code = str(issue.get("code") or "PACKAGE_INTEGRITY_ERROR")
        path = str(issue.get("path") or "")
        rows.append(f"{code}{f' ({path})' if path else ''}")
    remaining = max(0, len(report.get("issues") or []) - len(rows))
    if remaining:
        rows.append(f"and {remaining} additional issue(s)")
    return rows


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_configuration_valid() -> bool:
    """Require the local runtime to expose workstation-managed site packages."""
    config = VENV_DIR / "pyvenv.cfg"
    python = _venv_python()
    if not config.is_file() or not python.is_file():
        return False
    values: dict[str, str] = {}
    try:
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip().lower()
    except OSError:
        return False
    if values.get("include-system-site-packages") != "true":
        return False
    probe = subprocess.run(
        [str(python), "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return probe.returncode == 0


def _rebuild_environment() -> None:
    """Rebuild a stale or incompatible local runtime deterministically."""
    if VENV_DIR.exists():
        try:
            shutil.rmtree(VENV_DIR)
        except OSError:
            # EnvBuilder(clear=True) provides a second, platform-aware cleanup path.
            pass
    venv.EnvBuilder(with_pip=True, system_site_packages=True, clear=True).create(VENV_DIR)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, check=check)


def _unique_existing_directories(values: Iterable[str | os.PathLike[str]]) -> list[Path]:
    rows: list[Path] = []
    seen: set[str] = set()
    local_venv = VENV_DIR.resolve(strict=False)
    for value in values:
        try:
            candidate = Path(value).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if not candidate.is_dir():
            continue
        try:
            candidate.relative_to(local_venv)
        except ValueError:
            pass
        else:
            continue
        lowered = candidate.as_posix().lower()
        if "site-packages" not in lowered and "dist-packages" not in lowered:
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        rows.append(candidate)
    return rows


def _parent_site_packages() -> list[Path]:
    """Return import roots visible to the interpreter that launched start.bat.

    ``venv --system-site-packages`` exposes packages from the base interpreter,
    but a Python chosen from Conda or another virtual environment can have useful
    packages outside that base prefix.  A small .pth overlay preserves access to
    those workstation-managed packages, including PyMotorCAD, without copying them.
    """
    candidates: list[str | os.PathLike[str]] = []
    try:
        candidates.extend(site.getsitepackages())
    except (AttributeError, OSError):
        pass
    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            candidates.append(user_site)
        else:
            candidates.extend(user_site)
    except (AttributeError, OSError):
        pass
    candidates.extend(
        entry for entry in sys.path
        if isinstance(entry, str) and entry
    )
    return _unique_existing_directories(candidates)


def _venv_site_packages(python: Path) -> Path:
    code = (
        "import json,site,sys; "
        "paths=[p for p in site.getsitepackages() if p.startswith(sys.prefix)]; "
        "print(json.dumps(paths))"
    )
    completed = subprocess.run(
        [str(python), "-c", code],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "local site-packages inspection failed")
    paths = json.loads(completed.stdout.strip() or "[]")
    for value in paths:
        candidate = Path(value)
        if candidate.is_dir():
            return candidate
    raise RuntimeError("local site-packages directory was not found")


def _write_parent_site_overlay(python: Path) -> Path | None:
    """Expose packages from the selected parent interpreter in the local venv.

    The overlay is refreshed on every startup so replacing the program directory or
    selecting a different Python cannot leave a stale hard-coded import root.
    """
    target_directory = _venv_site_packages(python)
    target = target_directory / "motorcad_studio_parent_site.pth"
    rows = [str(path) for path in _parent_site_packages()]
    if rows:
        target.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return target
    if target.exists():
        target.unlink()
    return None


def _missing_imports(python: Path) -> list[str]:
    code = (
        "import importlib.util,json; "
        f"mods={json.dumps(CORE_IMPORTS)}; "
        "print(json.dumps([pkg for pkg,mod in mods.items() if importlib.util.find_spec(mod) is None]))"
    )
    completed = subprocess.run(
        [str(python), "-c", code],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "dependency inspection failed")
    value = json.loads(completed.stdout.strip() or "[]")
    return [str(item) for item in value]


def _ensure_environment(*, skip_install: bool) -> Path:
    python = _venv_python()
    if not _venv_configuration_valid():
        print(f"[setup] Creating local runtime: {VENV_DIR}")
        _rebuild_environment()
        python = _venv_python()
    try:
        _write_parent_site_overlay(python)
        missing = _missing_imports(python)
    except RuntimeError:
        print("[setup] Existing local runtime is invalid; rebuilding it.")
        _rebuild_environment()
        python = _venv_python()
        _write_parent_site_overlay(python)
        missing = _missing_imports(python)
    if missing:
        if skip_install:
            raise RuntimeError(f"missing required packages: {', '.join(missing)}")
        if not REQUIREMENTS.is_file():
            raise RuntimeError(f"requirements file is missing: {REQUIREMENTS}")
        print(f"[setup] Installing missing runtime packages: {', '.join(missing)}")
        _run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)])
        remaining = _missing_imports(python)
        if remaining:
            raise RuntimeError(f"packages remain unavailable after installation: {', '.join(remaining)}")
    else:
        print("[setup] Python runtime dependencies are ready.")
    return python


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 10):
        print("[setup:error] Python 3.10 or newer is required.", file=sys.stderr)
        return 2
    print(f"[setup] MotorCAD Studio {PRODUCT_VERSION}")
    cleared = _sanitize_installed_runtime_environment()
    if cleared:
        print(
            "[setup:warning] Ignored legacy runtime-directory override(s) inside the program folder: "
            + ", ".join(cleared)
            + ". Mutable state will use the user-profile data directory."
        )
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--skip-install", action="store_true")
    known, forwarded = parser.parse_known_args(argv)
    try:
        issues = _distribution_issues()
        if issues:
            raise RuntimeError(
                "package integrity check failed: " + "; ".join(issues)
            )
        print("[setup] Package integrity is valid.")
        python = _ensure_environment(skip_install=known.skip_install)
    except Exception as exc:
        print(f"[setup:error] {exc}", file=sys.stderr)
        return 2
    return _run([str(python), "-m", "motorcad_studio.launcher", *forwarded], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
