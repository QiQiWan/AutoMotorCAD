from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    config_dir: Path
    templates_dir: Path
    results_dir: Path
    runtime_dir: Path
    baselines_dir: Path
    factory_dir: Path
    logs_dir: Path
    db_path: Path
    host: str
    port: int
    default_solver: str
    motorcad_visible: bool
    max_workers: int
    mock_stage_delay_s: float
    enable_mock_solver: bool
    solver_timeout_s: int
    solver_cancel_grace_s: int
    motorcad_version: str
    strict_parameter_mapping: bool
    model_policy: str
    case_parallelism: int
    reuse_motorcad_instances: bool
    motorcad_worker_mode: str
    motorcad_pool_size: int
    motorcad_worker_recycle_jobs: int
    motorcad_worker_recycle_rss_mb: float
    motorcad_worker_acquire_timeout_s: int
    motorcad_worker_fallback_isolated: bool
    motorcad_exe: str | None
    use_blackbox_licence: bool | None
    license_emag: int
    license_thermal: int
    license_lab: int
    license_mechanical: int
    license_wait_timeout_s: int
    runtime_min_free_memory_mb: float
    runtime_case_memory_reservation_mb: float
    runtime_scheduler_wait_timeout_s: int
    runtime_contract_stale_hours: int
    runtime_shutdown_grace_s: float
    runtime_shutdown_force_grace_s: float
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    log_retention_days: int


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _installed_user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or Path.home())
        return base / "MotorCADStudio" / "data"
    if os.sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MotorCADStudio" / "data"
    base = Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "motorcad-studio" / "data"


def _materialize_packaged_seed(package_root: Path, data_dir: Path) -> None:
    seed_root = package_root / "seed_data"
    if not (seed_root / "inventory.json").is_file():
        return
    for name in ("inventory.json", "catalog.generated.json"):
        source = seed_root / name
        target = data_dir / name
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    seed_templates = seed_root / "templates"
    target_templates = data_dir / "templates"
    target_templates.mkdir(parents=True, exist_ok=True)
    for source in seed_templates.glob("*.mtt"):
        target = target_templates / source.name
        if not target.exists():
            shutil.copy2(source, target)


def load_settings() -> Settings:
    package_root = Path(__file__).resolve().parent
    root = package_root.parent
    packaged_config_dir = package_root / "config"
    source_checkout = (root / "pyproject.toml").is_file()
    config_override = os.getenv("MOTORCAD_STUDIO_CONFIG_DIR")
    if config_override:
        config_dir = Path(config_override).expanduser().resolve()
    else:
        config_dir = packaged_config_dir
    default_data_dir = root / "data" if source_checkout else _installed_user_data_dir()
    data_dir = Path(os.getenv("MOTORCAD_STUDIO_DATA_DIR", str(default_data_dir))).expanduser().resolve()
    _materialize_packaged_seed(package_root, data_dir)
    templates_dir = data_dir / "templates"
    results_dir = Path(os.getenv("MOTORCAD_STUDIO_RESULTS_DIR", str(data_dir / "results"))).resolve()
    runtime_dir = Path(os.getenv("MOTORCAD_STUDIO_RUNTIME_DIR", str(data_dir / "runtime"))).resolve()
    baselines_dir = Path(os.getenv("MOTORCAD_STUDIO_BASELINES_DIR", str(data_dir / "baselines"))).resolve()
    factory_dir = Path(os.getenv("MOTORCAD_STUDIO_FACTORY_DIR", str(data_dir / "factory"))).resolve()
    # Source checkouts keep live operational logs at <project-root>/logs so engineers
    # can tail one stable location while a validation/calculation is running. Installed
    # packages keep their writable per-user data location unless explicitly overridden.
    default_logs_dir = root / "logs" if source_checkout else data_dir / "logs"
    logs_dir = Path(os.getenv("MOTORCAD_STUDIO_LOG_DIR", str(default_logs_dir))).expanduser().resolve()
    for directory in (data_dir, templates_dir, results_dir, runtime_dir, baselines_dir, factory_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return Settings(
        root_dir=root,
        data_dir=data_dir,
        config_dir=config_dir,
        templates_dir=templates_dir,
        results_dir=results_dir,
        runtime_dir=runtime_dir,
        baselines_dir=baselines_dir,
        factory_dir=factory_dir,
        logs_dir=logs_dir,
        db_path=runtime_dir / "motorcad_studio.sqlite3",
        host=os.getenv("MOTORCAD_STUDIO_HOST", "127.0.0.1"),
        port=int(os.getenv("MOTORCAD_STUDIO_PORT", "8765")),
        default_solver=os.getenv("MOTORCAD_STUDIO_DEFAULT_SOLVER", "motorcad"),
        motorcad_visible=_env_bool("MOTORCAD_STUDIO_MOTORCAD_VISIBLE", False),
        max_workers=max(1, int(os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1"))),
        mock_stage_delay_s=max(0.0, float(os.getenv("MOTORCAD_STUDIO_MOCK_DELAY", "0.08"))),
        enable_mock_solver=_env_bool("MOTORCAD_STUDIO_ENABLE_MOCK", False),
        solver_timeout_s=max(1, int(os.getenv("MOTORCAD_STUDIO_SOLVER_TIMEOUT", "7200"))),
        solver_cancel_grace_s=max(1, int(os.getenv("MOTORCAD_STUDIO_CANCEL_GRACE", "5"))),
        motorcad_version=os.getenv("MOTORCAD_STUDIO_MOTORCAD_VERSION", "2026R1"),
        strict_parameter_mapping=_env_bool("MOTORCAD_STUDIO_STRICT_MAPPING", True),
        model_policy=os.getenv("MOTORCAD_STUDIO_MODEL_POLICY", "development").strip().lower(),
        case_parallelism=max(1, int(os.getenv("MOTORCAD_STUDIO_CASE_PARALLELISM", os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1")))),
        reuse_motorcad_instances=_env_bool("MOTORCAD_STUDIO_REUSE_INSTANCES", True),
        motorcad_worker_mode=(os.getenv("MOTORCAD_STUDIO_WORKER_MODE", "persistent").strip().lower() if os.getenv("MOTORCAD_STUDIO_WORKER_MODE", "persistent").strip().lower() in {"persistent", "isolated"} else "persistent"),
        motorcad_pool_size=max(1, int(os.getenv("MOTORCAD_STUDIO_MOTORCAD_POOL_SIZE", os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1")))),
        motorcad_worker_recycle_jobs=max(1, int(os.getenv("MOTORCAD_STUDIO_WORKER_RECYCLE_JOBS", "20"))),
        motorcad_worker_recycle_rss_mb=max(256.0, float(os.getenv("MOTORCAD_STUDIO_WORKER_RECYCLE_RSS_MB", "4096"))),
        motorcad_worker_acquire_timeout_s=max(1, int(os.getenv("MOTORCAD_STUDIO_WORKER_ACQUIRE_TIMEOUT", os.getenv("MOTORCAD_STUDIO_LICENSE_WAIT_TIMEOUT", "1800")))),
        motorcad_worker_fallback_isolated=_env_bool("MOTORCAD_STUDIO_WORKER_FALLBACK_ISOLATED", True),
        motorcad_exe=os.getenv("MOTORCAD_STUDIO_MOTORCAD_EXE") or None,
        use_blackbox_licence=(None if os.getenv("MOTORCAD_STUDIO_USE_BLACKBOX_LICENCE") is None else _env_bool("MOTORCAD_STUDIO_USE_BLACKBOX_LICENCE", False)),
        license_emag=max(0, int(os.getenv("MOTORCAD_STUDIO_LICENSE_EMAG", os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1")))),
        license_thermal=max(0, int(os.getenv("MOTORCAD_STUDIO_LICENSE_THERMAL", os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1")))),
        license_lab=max(0, int(os.getenv("MOTORCAD_STUDIO_LICENSE_LAB", os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1")))),
        license_mechanical=max(0, int(os.getenv("MOTORCAD_STUDIO_LICENSE_MECHANICAL", os.getenv("MOTORCAD_STUDIO_MAX_WORKERS", "1")))),
        license_wait_timeout_s=max(1, int(os.getenv("MOTORCAD_STUDIO_LICENSE_WAIT_TIMEOUT", "1800"))),
        runtime_min_free_memory_mb=max(0.0, float(os.getenv("MOTORCAD_STUDIO_RUNTIME_MIN_FREE_MEMORY_MB", "1536"))),
        runtime_case_memory_reservation_mb=max(0.0, float(os.getenv("MOTORCAD_STUDIO_RUNTIME_CASE_MEMORY_MB", "1024"))),
        runtime_scheduler_wait_timeout_s=max(1, int(os.getenv("MOTORCAD_STUDIO_RUNTIME_SCHEDULER_TIMEOUT", os.getenv("MOTORCAD_STUDIO_LICENSE_WAIT_TIMEOUT", "1800")))),
        runtime_contract_stale_hours=max(1, int(os.getenv("MOTORCAD_STUDIO_RUNTIME_CONTRACT_STALE_HOURS", "168"))),
        runtime_shutdown_grace_s=max(0.0, float(os.getenv("MOTORCAD_STUDIO_RUNTIME_SHUTDOWN_GRACE", "8"))),
        runtime_shutdown_force_grace_s=max(0.0, float(os.getenv("MOTORCAD_STUDIO_RUNTIME_FORCE_SHUTDOWN_GRACE", "5"))),
        log_level=os.getenv("MOTORCAD_STUDIO_LOG_LEVEL", "INFO").strip().upper(),
        log_max_bytes=max(262144, int(os.getenv("MOTORCAD_STUDIO_LOG_MAX_BYTES", str(20 * 1024 * 1024)))),
        log_backup_count=max(1, int(os.getenv("MOTORCAD_STUDIO_LOG_BACKUP_COUNT", "8"))),
        log_retention_days=max(1, int(os.getenv("MOTORCAD_STUDIO_LOG_RETENTION_DAYS", "14"))),
    )


settings = load_settings()
