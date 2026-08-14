from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class Database:
    SCHEMA_VERSION = 17

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    @classmethod
    def _ensure_column(cls, conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
        if name not in cls._column_names(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    solver_mode TEXT NOT NULL,
                    analysis TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    current_stage TEXT NOT NULL DEFAULT '',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    request_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    case_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    parameters_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    case_id TEXT,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    severity TEXT NOT NULL DEFAULT 'INFO',
                    progress REAL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    case_id TEXT,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    size_bytes INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(case_id, path),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS case_stages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    checkpoint_path TEXT,
                    payload_json TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(case_id, stage),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS designs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    motor_family TEXT NOT NULL DEFAULT '',
                    template_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS design_revisions (
                    id TEXT PRIMARY KEY,
                    design_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    parameters_json TEXT NOT NULL,
                    materials_json TEXT NOT NULL,
                    explicit_parameter_ids_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(design_id, revision),
                    FOREIGN KEY(design_id) REFERENCES designs(id)
                );
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS scenario_revisions (
                    id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    scenario_json TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(scenario_id, revision),
                    FOREIGN KEY(scenario_id) REFERENCES scenarios(id)
                );
                CREATE TABLE IF NOT EXISTS solver_profiles (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS solver_profile_revisions (
                    id TEXT PRIMARY KEY,
                    solver_profile_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    analysis TEXT NOT NULL,
                    quality_profile TEXT NOT NULL DEFAULT 'standard',
                    solver_settings_json TEXT NOT NULL DEFAULT '{}',
                    automation_overrides_json TEXT NOT NULL DEFAULT '{}',
                    solver_timeout_s INTEGER,
                    notes TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(solver_profile_id, revision),
                    FOREIGN KEY(solver_profile_id) REFERENCES solver_profiles(id)
                );
                CREATE TABLE IF NOT EXISTS output_profiles (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS output_profile_revisions (
                    id TEXT PRIMARY KEY,
                    output_profile_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    requested_outputs_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(output_profile_id, revision),
                    FOREIGN KEY(output_profile_id) REFERENCES output_profiles(id)
                );
                CREATE TABLE IF NOT EXISTS motorcad_sessions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    case_id TEXT,
                    worker_pid INTEGER,
                    motorcad_pid INTEGER,
                    state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    motorcad_version TEXT,
                    pymotorcad_version TEXT,
                    ownership_mode TEXT NOT NULL DEFAULT 'isolated_case',
                    reuse_requested INTEGER NOT NULL DEFAULT 0,
                    reuse_effective INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    last_heartbeat TEXT,
                    released_at TEXT,
                    jobs_completed INTEGER NOT NULL DEFAULT 0,
                    memory_peak_mb REAL,
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(task_id) REFERENCES tasks(id),
                    FOREIGN KEY(case_id) REFERENCES cases(id)
                );
                CREATE INDEX IF NOT EXISTS idx_motorcad_sessions_case ON motorcad_sessions(case_id);
                CREATE INDEX IF NOT EXISTS idx_motorcad_sessions_state ON motorcad_sessions(state);
                CREATE TABLE IF NOT EXISTS run_configurations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    design_revision_id TEXT NOT NULL,
                    scenario_revision_id TEXT,
                    solver_profile_revision_id TEXT,
                    output_profile_revision_id TEXT,
                    snapshot_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    traceability_status TEXT NOT NULL DEFAULT 'PARTIAL_INLINE',
                    snapshot_schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(design_revision_id) REFERENCES design_revisions(id),
                    FOREIGN KEY(scenario_revision_id) REFERENCES scenario_revisions(id),
                    FOREIGN KEY(solver_profile_revision_id) REFERENCES solver_profile_revisions(id),
                    FOREIGN KEY(output_profile_revision_id) REFERENCES output_profile_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    design_revision_id TEXT,
                    scenario_revision_id TEXT,
                    name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(design_revision_id) REFERENCES design_revisions(id),
                    FOREIGN KEY(scenario_revision_id) REFERENCES scenario_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS optimizer_runs (
                    task_id TEXT PRIMARY KEY,
                    algorithm TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    state_json TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS data_ingestions (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    raw_path TEXT,
                    curated_path TEXT,
                    feature_path TEXT,
                    quality_report_path TEXT,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    schema_hash TEXT,
                    content_hash TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(dataset_id, version),
                    FOREIGN KEY(dataset_id) REFERENCES datasets(id)
                );
                CREATE TABLE IF NOT EXISTS dataset_members (
                    dataset_version_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    member_hash TEXT,
                    partition_name TEXT,
                    PRIMARY KEY(dataset_version_id, case_id),
                    FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
                    FOREIGN KEY(case_id) REFERENCES cases(id)
                );
                CREATE TABLE IF NOT EXISTS qualification_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id TEXT NOT NULL,
                    motorcad_version TEXT NOT NULL,
                    analysis TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    solver_smoke INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS material_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id TEXT NOT NULL,
                    motorcad_version TEXT NOT NULL,
                    component TEXT NOT NULL,
                    studio_material TEXT NOT NULL,
                    motorcad_material TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(template_id,motorcad_version,component,studio_material)
                );
                CREATE TABLE IF NOT EXISTS result_calibrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id TEXT NOT NULL,
                    motorcad_version TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    extractor TEXT NOT NULL,
                    graph_name TEXT NOT NULL,
                    section_number INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(template_id,motorcad_version,result_id)
                );
                CREATE INDEX IF NOT EXISTS idx_cases_task ON cases(task_id);
                CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, case_id);
                CREATE INDEX IF NOT EXISTS idx_stages_case ON case_stages(case_id, id);
                CREATE INDEX IF NOT EXISTS idx_designs_project ON designs(project_id);
                CREATE INDEX IF NOT EXISTS idx_design_revisions_design ON design_revisions(design_id, revision);
                CREATE INDEX IF NOT EXISTS idx_scenarios_project ON scenarios(project_id);
                CREATE INDEX IF NOT EXISTS idx_scenario_revisions_scenario ON scenario_revisions(scenario_id, revision);
                CREATE INDEX IF NOT EXISTS idx_solver_profiles_project ON solver_profiles(project_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_solver_profile_revisions_profile ON solver_profile_revisions(solver_profile_id,revision);
                CREATE INDEX IF NOT EXISTS idx_output_profiles_project ON output_profiles(project_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_output_profile_revisions_profile ON output_profile_revisions(output_profile_id,revision);
                CREATE INDEX IF NOT EXISTS idx_run_configurations_project ON run_configurations(project_id,created_at);

                CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset ON dataset_versions(dataset_id, version);
                CREATE INDEX IF NOT EXISTS idx_dataset_members_case ON dataset_members(case_id);
                CREATE INDEX IF NOT EXISTS idx_qualification_template ON qualification_records(template_id,motorcad_version,analysis,created_at);
                CREATE INDEX IF NOT EXISTS idx_material_bindings_template ON material_bindings(template_id,motorcad_version,status);
                CREATE INDEX IF NOT EXISTS idx_result_calibrations_template ON result_calibrations(template_id,motorcad_version,status);
                """
            )
            for name, ddl in {
                "status": "TEXT NOT NULL DEFAULT 'ACTIVE'",
                "deleted_at": "TEXT",
            }.items():
                self._ensure_column(conn, "projects", name, ddl)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_status_updated ON projects(status,updated_at)")
            for name, ddl in {
                "traceability_status": "TEXT NOT NULL DEFAULT 'PARTIAL_INLINE'",
                "snapshot_schema_version": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                self._ensure_column(conn, "run_configurations", name, ddl)
            for name, ddl in {
                "updated_at": "TEXT",
                "case_count": "INTEGER NOT NULL DEFAULT 0",
                "quality_profile": "TEXT NOT NULL DEFAULT 'standard'",
                "recovered": "INTEGER NOT NULL DEFAULT 0",
                "cancel_mode": "TEXT NOT NULL DEFAULT 'stop_after_current'",
                "project_id": "TEXT",
                "design_revision_id": "TEXT",
                "scenario_revision_id": "TEXT",
                "experiment_id": "TEXT",
                "run_configuration_id": "TEXT",
                "submission_key": "TEXT",
                "submission_hash": "TEXT",
            }.items():
                self._ensure_column(conn, "tasks", name, ddl)
            for name, ddl in {
                "attempt": "INTEGER NOT NULL DEFAULT 0",
                "input_hash": "TEXT",
                "fingerprint_json": "TEXT",
                "work_dir": "TEXT",
                "warnings_json": "TEXT",
                "quality_json": "TEXT",
                "updated_at": "TEXT",
                "cached_from_case_id": "TEXT",
                "execution_status": "TEXT NOT NULL DEFAULT 'PENDING'",
                "quality_status": "TEXT NOT NULL DEFAULT 'NOT_ASSESSED'",
                "cache_eligible": "INTEGER NOT NULL DEFAULT 0",
                "worker_pid": "INTEGER",
                "solver_version": "TEXT",
                "last_heartbeat": "TEXT",
                "worker_create_time": "REAL",
                "generation": "INTEGER NOT NULL DEFAULT 0",
                "case_source": "TEXT NOT NULL DEFAULT 'static'",
                "parent_ids_json": "TEXT",
                "motorcad_worker_id": "TEXT",
                "execution_lease_id": "TEXT",
                "validation_evidence_hash": "TEXT",
                "runtime_resource_lease_id": "TEXT",
                "resource_wait_ms": "REAL",
            }.items():
                self._ensure_column(conn, "cases", name, ddl)
            self._ensure_column(conn, "motorcad_sessions", "reuse_effective", "INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_run_configuration ON tasks(run_configuration_id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_submission_key ON tasks(submission_key) WHERE submission_key IS NOT NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_hash ON cases(input_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_execution_quality ON cases(execution_status,quality_status,cache_eligible)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_runtime_resource_lease ON cases(runtime_resource_lease_id)")
            self._ensure_column(conn, "design_revisions", "explicit_parameter_ids_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "datasets", "project_id", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_project ON datasets(project_id,updated_at)")
            # Backfill legacy dataset ownership when all members resolve to one project.
            conn.execute("""
                UPDATE datasets
                   SET project_id = (
                       SELECT MIN(t.project_id)
                         FROM dataset_versions dv
                         JOIN dataset_members dm ON dm.dataset_version_id=dv.id
                         JOIN cases c ON c.id=dm.case_id
                         JOIN tasks t ON t.id=c.task_id
                        WHERE dv.dataset_id=datasets.id AND t.project_id IS NOT NULL
                   )
                 WHERE project_id IS NULL
                   AND 1 = (
                       SELECT COUNT(DISTINCT t.project_id)
                         FROM dataset_versions dv
                         JOIN dataset_members dm ON dm.dataset_version_id=dv.id
                         JOIN cases c ON c.id=dm.case_id
                         JOIN tasks t ON t.id=c.task_id
                        WHERE dv.dataset_id=datasets.id AND t.project_id IS NOT NULL
                   )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run several related statements in one database transaction.

        Workspace creation flows use this to avoid leaving a Design without its
        initial Revision when a later insert fails. The existing ``connect``
        context commits only after the body completes successfully.
        """
        with self._lock, self.connect() as conn:
            yield conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(sql, params)

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        with self._lock, self.connect() as conn:
            conn.executemany(sql, params)

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        for attempt in range(2):
            try:
                with self._lock, self.connect() as conn:
                    row = conn.execute(sql, params).fetchone()
                    return dict(row) if row else None
            except sqlite3.OperationalError as exc:
                if attempt == 0 and "no such table" in str(exc).lower():
                    # A development deployment can replace the SQLite file while an
                    # existing browser/service is still alive. Recreate/migrate the
                    # schema once instead of flooding the monitoring stream with errors.
                    self.initialize()
                    continue
                raise
        return None

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        for attempt in range(2):
            try:
                with self._lock, self.connect() as conn:
                    return [dict(row) for row in conn.execute(sql, params).fetchall()]
            except sqlite3.OperationalError as exc:
                if attempt == 0 and "no such table" in str(exc).lower():
                    self.initialize()
                    continue
                raise
        return []

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def loads(value: str | None, default: Any = None) -> Any:
        if not value:
            return default
        return json.loads(value)
