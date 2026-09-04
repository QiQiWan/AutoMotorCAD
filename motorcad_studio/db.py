from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class Database:
    SCHEMA_VERSION = 56

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._change_generation = 0
        self._active_connections = 0
        self._peak_connections = 0
        self._total_connections = 0
        self._last_connection_opened_at: str | None = None
        self._last_connection_closed_at: str | None = None
        self.initialize()

    @contextmanager
    def connect(self, *, commit: bool = True) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        with self._lifecycle_lock:
            self._active_connections += 1
            self._total_connections += 1
            self._peak_connections = max(self._peak_connections, self._active_connections)
            self._last_connection_opened_at = self.now()
        try:
            # Keep connection configuration inside the ownership boundary too: if a
            # PRAGMA/configuration call fails, the same finally block still closes and
            # decrements the lifecycle counter.
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            before_changes = conn.total_changes
            yield conn
            if commit:
                conn.commit()
                if conn.total_changes > before_changes:
                    self._change_generation += 1
        finally:
            try:
                conn.close()
            finally:
                with self._lifecycle_lock:
                    self._active_connections = max(0, self._active_connections - 1)
                    self._last_connection_closed_at = self.now()

    def lifecycle_snapshot(self) -> dict[str, Any]:
        """Return connection ownership evidence without opening another SQLite connection.

        V0.87-F-A uses this to prove that shutdown/restart boundaries do not retain
        hidden SQLite handles. The counters are process-local observability only; they
        never replace SQLite transaction semantics.
        """
        with self._lifecycle_lock:
            return {
                "authority": "SQLiteLifecycleV1",
                "path": str(self.path),
                "active_connections": int(self._active_connections),
                "peak_connections": int(self._peak_connections),
                "total_connections": int(self._total_connections),
                "idle": self._active_connections == 0,
                "last_connection_opened_at": self._last_connection_opened_at,
                "last_connection_closed_at": self._last_connection_closed_at,
            }

    @staticmethod
    def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    @classmethod
    def _ensure_column(cls, conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
        if name not in cls._column_names(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    @staticmethod
    def _object_type(conn: sqlite3.Connection, name: str) -> str | None:
        row = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
        return str(row[0]) if row else None

    @classmethod
    def _migrate_solution_vocabulary(cls, conn: sqlite3.Connection) -> None:
        """Upgrade V0.77 Design persistence names to the canonical Solution vocabulary.

        SQLite table renames preserve row ids and rewrite dependent foreign-key targets.
        Legacy names are reintroduced later as compatibility views, so old workspaces and
        historical tests remain readable while new persistence code can use canonical names.
        """
        for old, new in (("designs", "solutions"), ("design_revisions", "motor_revisions"), ("design_drafts", "solution_drafts")):
            if cls._object_type(conn, new) is None and cls._object_type(conn, old) == "table":
                conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
        if cls._object_type(conn, "motor_revisions") == "table":
            cols = cls._column_names(conn, "motor_revisions")
            if "design_id" in cols and "solution_id" not in cols:
                conn.execute("ALTER TABLE motor_revisions RENAME COLUMN design_id TO solution_id")
        if cls._object_type(conn, "solution_drafts") == "table":
            cols = cls._column_names(conn, "solution_drafts")
            if "design_id" in cols and "solution_id" not in cols:
                conn.execute("ALTER TABLE solution_drafts RENAME COLUMN design_id TO solution_id")
                cols = cls._column_names(conn, "solution_drafts")
            if "base_revision_id" in cols and "base_motor_revision_id" not in cols:
                conn.execute("ALTER TABLE solution_drafts RENAME COLUMN base_revision_id TO base_motor_revision_id")
        for legacy_index in ("idx_designs_project", "idx_design_revisions_design", "idx_design_drafts_base_revision"):
            conn.execute(f"DROP INDEX IF EXISTS {legacy_index}")

    @classmethod
    def _install_legacy_solution_views(cls, conn: sqlite3.Connection) -> None:
        """Expose V0.77 Design SQL names as compatibility views with write-through triggers."""
        specs = {
            "designs": ("solutions", {}),
            "design_revisions": ("motor_revisions", {"solution_id": "design_id"}),
            "design_drafts": ("solution_drafts", {"solution_id": "design_id", "base_motor_revision_id": "base_revision_id"}),
        }
        for legacy, (canonical, aliases) in specs.items():
            if cls._object_type(conn, canonical) != "table":
                continue
            for suffix in ("insert", "update", "delete"):
                conn.execute(f"DROP TRIGGER IF EXISTS compat_{legacy}_{suffix}")
            if cls._object_type(conn, legacy) == "view":
                conn.execute(f"DROP VIEW {legacy}")
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({canonical})").fetchall()]
            legacy_name = lambda col: aliases.get(col, col)
            select_list = ",".join(f"{col} AS {legacy_name(col)}" if legacy_name(col) != col else col for col in cols)
            conn.execute(f"CREATE VIEW {legacy} AS SELECT {select_list} FROM {canonical}")
            info = {row[1]: row for row in conn.execute(f"PRAGMA table_info({canonical})").fetchall()}
            values = []
            for col in cols:
                newref = f"NEW.{legacy_name(col)}"
                default = info[col][4]
                values.append(f"COALESCE({newref},{default})" if default is not None else newref)
            conn.execute(
                f"CREATE TRIGGER compat_{legacy}_insert INSTEAD OF INSERT ON {legacy} BEGIN "
                f"INSERT INTO {canonical} ({','.join(cols)}) VALUES ({','.join(values)}); END"
            )
            pk_cols = [row[1] for row in info.values() if int(row[5] or 0) > 0]
            if not pk_cols:
                pk_cols = [cols[0]]
            where = " AND ".join(f"{col}=OLD.{legacy_name(col)}" for col in pk_cols)
            assignments = ",".join(f"{col}=NEW.{legacy_name(col)}" for col in cols)
            conn.execute(
                f"CREATE TRIGGER compat_{legacy}_update INSTEAD OF UPDATE ON {legacy} BEGIN "
                f"UPDATE {canonical} SET {assignments} WHERE {where}; END"
            )
            conn.execute(
                f"CREATE TRIGGER compat_{legacy}_delete INSTEAD OF DELETE ON {legacy} BEGIN "
                f"DELETE FROM {canonical} WHERE {where}; END"
            )

    @classmethod
    def _install_lineage_generation_triggers(cls, conn: sqlite3.Connection) -> None:
        """Persist a cross-connection lineage generation for cache invalidation.

        The in-memory change counter is useful inside one Python process, but a
        Windows deployment may be inspected by another process or future Uvicorn
        worker.  These triggers make cache invalidation part of the SQLite
        transaction that changes a lineage-bearing object.
        """
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('lineage_generation','0')"
        )
        update_specs = {
            "projects": "name,description,status,deleted_at,updated_at",
            "solutions": "project_id,name,motor_family,template_id,motor_type_id,source_kind,source_reference,geometry_mode,updated_at",
            "motor_revisions": "solution_id,revision,content_hash,motor_snapshot_hash",
            "analysis_definitions": "project_id,design_revision_id,name,module,recipe_id,status,updated_at",
            "analysis_definition_revisions": "analysis_definition_id,revision,content_hash,analysis_snapshot_hash",
            "execution_plans": "project_id,design_revision_id,analysis_definition_revision_id,content_hash,motor_snapshot_hash,analysis_snapshot_hash,traceability_status",
            "tasks": "project_id,design_revision_id,execution_plan_id,execution_plan_hash,name,status",
            "cases": "task_id,execution_plan_id,execution_plan_hash,result_bundle_id,result_bundle_hash,status",
            "result_bundles": "case_id,task_id,execution_plan_id,execution_plan_hash,content_hash,quality_status,qualification_status",
        }
        for table, columns in update_specs.items():
            if cls._object_type(conn, table) != "table":
                continue
            for operation in ("insert", "delete", "update"):
                trigger = f"lineage_generation_{table}_{operation}"
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
                if operation == "update":
                    event = f"UPDATE OF {columns}"
                else:
                    event = operation.upper()
                conn.execute(
                    f"CREATE TRIGGER {trigger} AFTER {event} ON {table} BEGIN "
                    "UPDATE schema_meta SET value=CAST(value AS INTEGER)+1 WHERE key='lineage_generation'; END"
                )

    @property
    def change_generation(self) -> int:
        return int(self._change_generation)

    def lineage_generation(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is not None:
            row = conn.execute("SELECT value FROM schema_meta WHERE key='lineage_generation'").fetchone()
            return int((row[0] if row else 0) or 0)
        row = self.query_one("SELECT value FROM schema_meta WHERE key='lineage_generation'")
        return int((row or {}).get("value") or 0)

    def vocabulary_status(self) -> dict[str, Any]:
        """Report whether the V0.78 Solution persistence vocabulary is fully installed.

        This is intentionally read-only and suitable for deployment/preflight checks.
        Physical canonical tables are required for new code; the old Design names must
        remain compatibility views during the migration window.
        """
        canonical_names = ("solutions", "motor_revisions", "solution_drafts")
        legacy_names = ("designs", "design_revisions", "design_drafts")
        with self.connect(commit=False) as conn:
            schema_row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            objects = {
                str(row[0]): str(row[1])
                for row in conn.execute(
                    "SELECT name,type FROM sqlite_master WHERE name IN (?,?,?,?,?,?)",
                    canonical_names + legacy_names,
                ).fetchall()
            }
            generation = self.lineage_generation(conn)
        canonical = {name: objects.get(name) for name in canonical_names}
        compatibility = {name: objects.get(name) for name in legacy_names}
        return {
            "schema_version": int((schema_row[0] if schema_row else 0) or 0),
            "expected_schema_version": int(self.SCHEMA_VERSION),
            "canonical": canonical,
            "compatibility": compatibility,
            "canonical_ready": all(kind == "table" for kind in canonical.values()),
            "compatibility_ready": all(kind == "view" for kind in compatibility.values()),
            "migration_complete": (
                all(kind == "table" for kind in canonical.values())
                and all(kind == "view" for kind in compatibility.values())
                and int((schema_row[0] if schema_row else 0) or 0) >= int(self.SCHEMA_VERSION)
            ),
            "lineage_generation": generation,
        }

    @contextmanager
    def read_snapshot(self) -> Iterator[sqlite3.Connection]:
        """Hold one consistent SQLite read snapshot across a multi-query resolver."""
        # WAL gives this connection a stable read snapshot while permitting unrelated
        # readers and writers to progress. A process-wide Python lock here turned one
        # slow filesystem/commit operation into head-of-line blocking for every route.
        with self.connect(commit=False) as conn:
            conn.execute("BEGIN")
            try:
                yield conn
            finally:
                conn.rollback()

    @classmethod
    def _install_v091_control_plane_schema(cls, conn: sqlite3.Connection) -> None:
        """Install command, optimization, qualification, native and requirement contracts.

        These tables are deliberately separate from historical optimization tables. They
        provide deterministic idempotency, optimistic concurrency, immutable evidence and
        fencing-token safety while preserving existing project databases in place.
        """
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS command_ledger_v2 (
                command_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL DEFAULT '{}',
                error_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(scope,idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_command_ledger_v2_status
                ON command_ledger_v2(status,updated_at);

            CREATE TABLE IF NOT EXISTS outbox_events_v2 (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                aggregate_version INTEGER,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                published_at TEXT,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_events_v2_pending
                ON outbox_events_v2(status,created_at);

            CREATE TABLE IF NOT EXISTS optimization_campaigns_v2 (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                objectives_json TEXT NOT NULL DEFAULT '[]',
                constraints_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                content_hash TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_optimization_campaigns_v2_project
                ON optimization_campaigns_v2(project_id,updated_at DESC);

            CREATE TABLE IF NOT EXISTS optimization_candidates_v2 (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                parameters_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PROPOSED',
                evaluation_json TEXT NOT NULL DEFAULT '{}',
                result_bundle_id TEXT,
                result_content_hash TEXT,
                qualification_decision_id TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(campaign_id,parameters_hash),
                FOREIGN KEY(campaign_id) REFERENCES optimization_campaigns_v2(id)
            );
            CREATE INDEX IF NOT EXISTS idx_optimization_candidates_v2_campaign
                ON optimization_candidates_v2(campaign_id,status,updated_at DESC);

            CREATE TABLE IF NOT EXISTS optimization_promotions_v2 (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL UNIQUE,
                source_version INTEGER NOT NULL,
                evidence_json TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(campaign_id) REFERENCES optimization_campaigns_v2(id),
                FOREIGN KEY(candidate_id) REFERENCES optimization_candidates_v2(id)
            );

            CREATE TABLE IF NOT EXISTS replay_plans_v2 (
                id TEXT PRIMARY KEY,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                environment_hash TEXT NOT NULL,
                contract_versions_json TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                plan_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS datasets_v2 (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                current_version_id TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_datasets_v2_project
                ON datasets_v2(project_id,updated_at DESC);

            CREATE TABLE IF NOT EXISTS dataset_versions_v2 (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                manifest_json TEXT NOT NULL,
                artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(dataset_id,revision),
                UNIQUE(dataset_id,content_hash),
                FOREIGN KEY(dataset_id) REFERENCES datasets_v2(id)
            );

            CREATE TABLE IF NOT EXISTS dataset_build_jobs_v2 (
                id TEXT PRIMARY KEY,
                dataset_version_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'QUEUED',
                progress REAL NOT NULL DEFAULT 0,
                worker_ref TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                error_json TEXT NOT NULL DEFAULT '{}',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions_v2(id)
            );
            CREATE INDEX IF NOT EXISTS idx_dataset_build_jobs_v2_version
                ON dataset_build_jobs_v2(dataset_version_id,updated_at DESC);

            CREATE TABLE IF NOT EXISTS dataset_quality_reports_v2 (
                id TEXT PRIMARY KEY,
                dataset_version_id TEXT NOT NULL,
                build_job_id TEXT NOT NULL,
                status TEXT NOT NULL,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                report_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions_v2(id),
                FOREIGN KEY(build_job_id) REFERENCES dataset_build_jobs_v2(id)
            );
            CREATE INDEX IF NOT EXISTS idx_dataset_quality_reports_v2_version
                ON dataset_quality_reports_v2(dataset_version_id,created_at DESC);

            CREATE TABLE IF NOT EXISTS dataset_publications_v2 (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                dataset_version_id TEXT NOT NULL UNIQUE,
                quality_report_id TEXT NOT NULL,
                publication_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dataset_id) REFERENCES datasets_v2(id),
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions_v2(id),
                FOREIGN KEY(quality_report_id) REFERENCES dataset_quality_reports_v2(id)
            );

            CREATE TABLE IF NOT EXISTS qualification_campaigns_v2 (
                id TEXT PRIMARY KEY,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                name TEXT NOT NULL,
                required_evidence_kinds_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'OPEN',
                head_hash TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qualification_campaigns_v2_subject
                ON qualification_campaigns_v2(subject_type,subject_id,updated_at DESC);

            CREATE TABLE IF NOT EXISTS qualification_evidence_v2 (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                artifact_hashes_json TEXT NOT NULL DEFAULT '[]',
                previous_hash TEXT NOT NULL,
                envelope_hash TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(campaign_id,sequence),
                FOREIGN KEY(campaign_id) REFERENCES qualification_campaigns_v2(id)
            );

            CREATE TABLE IF NOT EXISTS qualification_decisions_v2 (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                evidence_head_hash TEXT NOT NULL,
                decision_hash TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(campaign_id) REFERENCES qualification_campaigns_v2(id)
            );

            CREATE TABLE IF NOT EXISTS native_runtime_leases_v2 (
                resource_key TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL UNIQUE,
                owner_id TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                released_at TEXT
            );

            CREATE TABLE IF NOT EXISTS native_artifact_locks_v2 (
                path_hash TEXT PRIMARY KEY,
                canonical_path TEXT NOT NULL,
                lease_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                released_at TEXT
            );

            CREATE TABLE IF NOT EXISTS native_process_observations_v2 (
                id TEXT PRIMARY KEY,
                pid INTEGER NOT NULL,
                parent_pid INTEGER,
                executable_path TEXT NOT NULL,
                resource_key TEXT,
                lease_id TEXT,
                owner_id TEXT,
                process_state TEXT NOT NULL DEFAULT 'OBSERVED',
                observed_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_native_process_observations_v2_pid
                ON native_process_observations_v2(pid,observed_at DESC);

            CREATE TABLE IF NOT EXISTS native_snapshots_v2 (
                id TEXT PRIMARY KEY,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                artifact_path TEXT,
                artifact_hash TEXT NOT NULL,
                readback_json TEXT NOT NULL,
                readback_hash TEXT NOT NULL,
                environment_hash TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS requirement_sets_v2 (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                name TEXT NOT NULL,
                current_revision_id TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS requirement_revisions_v2 (
                id TEXT PRIMARY KEY,
                requirement_set_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                parent_revision_id TEXT,
                parent_hash TEXT NOT NULL DEFAULT '',
                requirements_json TEXT NOT NULL,
                revision_hash TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(requirement_set_id,revision),
                FOREIGN KEY(requirement_set_id) REFERENCES requirement_sets_v2(id)
            );

            CREATE TABLE IF NOT EXISTS tolerance_revisions_v2 (
                id TEXT PRIMARY KEY,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                parent_revision_id TEXT,
                parent_hash TEXT NOT NULL DEFAULT '',
                tolerances_json TEXT NOT NULL,
                correlations_json TEXT NOT NULL DEFAULT '[]',
                revision_hash TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(subject_type,subject_id,revision)
            );

            CREATE TABLE IF NOT EXISTS probabilistic_qualifications_v2 (
                id TEXT PRIMARY KEY,
                requirement_revision_id TEXT NOT NULL,
                tolerance_revision_id TEXT,
                sample_count INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                result_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY(requirement_revision_id) REFERENCES requirement_revisions_v2(id)
            );
            """
        )
        immutable_tables = (
            "optimization_promotions_v2",
            "replay_plans_v2",
            "dataset_versions_v2",
            "dataset_quality_reports_v2",
            "dataset_publications_v2",
            "qualification_evidence_v2",
            "qualification_decisions_v2",
            "native_snapshots_v2",
            "requirement_revisions_v2",
            "tolerance_revisions_v2",
            "probabilistic_qualifications_v2",
        )
        for table in immutable_tables:
            for action in ("UPDATE", "DELETE"):
                trigger = f"immutable_{table}_{action.lower()}"
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
                conn.execute(
                    f"CREATE TRIGGER {trigger} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END"
                )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('control_plane_schema_version','3')"
        )

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._migrate_solution_vocabulary(conn)
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
                CREATE TABLE IF NOT EXISTS solutions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    motor_family TEXT NOT NULL DEFAULT '',
                    template_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS motor_revisions (
                    id TEXT PRIMARY KEY,
                    solution_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    parameters_json TEXT NOT NULL,
                    materials_json TEXT NOT NULL,
                    explicit_parameter_ids_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(solution_id, revision),
                    FOREIGN KEY(solution_id) REFERENCES solutions(id)
                );
                CREATE TABLE IF NOT EXISTS solution_drafts (
                    solution_id TEXT PRIMARY KEY,
                    base_motor_revision_id TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    materials_json TEXT NOT NULL,
                    explicit_parameter_ids_json TEXT NOT NULL DEFAULT '[]',
                    active_view TEXT NOT NULL DEFAULT 'radial',
                    notes TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(solution_id) REFERENCES solutions(id),
                    FOREIGN KEY(base_motor_revision_id) REFERENCES motor_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS design_transactions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    solution_id TEXT NOT NULL,
                    base_revision_id TEXT NOT NULL,
                    base_revision_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    parameter_patch_json TEXT NOT NULL DEFAULT '{}',
                    material_patch_json TEXT NOT NULL DEFAULT '{}',
                    explicit_parameter_ids_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    intent_hash TEXT NOT NULL DEFAULT '',
                    commit_key TEXT NOT NULL,
                    committed_revision_id TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    committed_at TEXT,
                    aborted_at TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(solution_id) REFERENCES solutions(id),
                    FOREIGN KEY(base_revision_id) REFERENCES motor_revisions(id),
                    FOREIGN KEY(committed_revision_id) REFERENCES motor_revisions(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_design_transactions_commit_key
                    ON design_transactions(commit_key);
                CREATE INDEX IF NOT EXISTS idx_design_transactions_solution_status
                    ON design_transactions(solution_id,status,updated_at);
                CREATE INDEX IF NOT EXISTS idx_design_transactions_project
                    ON design_transactions(project_id,updated_at);
                CREATE TABLE IF NOT EXISTS analysis_definitions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    design_revision_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    module TEXT NOT NULL,
                    recipe_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'READY',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(design_revision_id) REFERENCES motor_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS analysis_definition_revisions (
                    id TEXT PRIMARY KEY,
                    analysis_definition_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    definition_json TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(analysis_definition_id,revision),
                    FOREIGN KEY(analysis_definition_id) REFERENCES analysis_definitions(id)
                );
                CREATE TABLE IF NOT EXISTS analysis_workflow_checks (
                    id TEXT PRIMARY KEY,
                    analysis_definition_id TEXT NOT NULL,
                    analysis_revision_id TEXT NOT NULL,
                    analysis_revision_hash TEXT NOT NULL,
                    design_revision_id TEXT NOT NULL,
                    design_revision_hash TEXT NOT NULL,
                    check_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(analysis_definition_id) REFERENCES analysis_definitions(id),
                    FOREIGN KEY(analysis_revision_id) REFERENCES analysis_definition_revisions(id),
                    FOREIGN KEY(design_revision_id) REFERENCES motor_revisions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_workflow_checks_latest
                    ON analysis_workflow_checks(analysis_definition_id,check_kind,created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_analysis_workflow_checks_revisions
                    ON analysis_workflow_checks(analysis_revision_id,design_revision_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS execution_command_ledger (
                    command_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    command_kind TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_execution_command_ledger_task
                    ON execution_command_ledger(task_id,created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_execution_command_ledger_status
                    ON execution_command_ledger(status,updated_at);
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
                    FOREIGN KEY(design_revision_id) REFERENCES motor_revisions(id),
                    FOREIGN KEY(scenario_revision_id) REFERENCES scenario_revisions(id),
                    FOREIGN KEY(solver_profile_revision_id) REFERENCES solver_profile_revisions(id),
                    FOREIGN KEY(output_profile_revision_id) REFERENCES output_profile_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS execution_plans (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    design_revision_id TEXT NOT NULL,
                    analysis_definition_revision_id TEXT,
                    motor_snapshot_hash TEXT NOT NULL,
                    analysis_snapshot_hash TEXT NOT NULL,
                    scenario_set_hash TEXT NOT NULL,
                    solver_profile_hash TEXT NOT NULL,
                    result_contract_hash TEXT NOT NULL,
                    binding_version TEXT NOT NULL,
                    target_motorcad_version TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 2,
                    traceability_status TEXT NOT NULL DEFAULT 'FULLY_PINNED',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(design_revision_id) REFERENCES motor_revisions(id),
                    FOREIGN KEY(analysis_definition_revision_id) REFERENCES analysis_definition_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS result_bundles (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    execution_plan_id TEXT,
                    execution_plan_hash TEXT,
                    bundle_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    contract_version TEXT NOT NULL DEFAULT '0.73-C',
                    quality_status TEXT NOT NULL DEFAULT 'NOT_ASSESSED',
                    qualification_status TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(case_id) REFERENCES cases(id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id),
                    FOREIGN KEY(execution_plan_id) REFERENCES execution_plans(id)
                );
                CREATE TABLE IF NOT EXISTS result_data_objects (
                    content_hash TEXT PRIMARY KEY,
                    storage_key TEXT NOT NULL UNIQUE,
                    encoding TEXT NOT NULL DEFAULT 'json-gzip',
                    media_type TEXT NOT NULL DEFAULT 'application/json',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    stored_bytes INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_verified_at TEXT,
                    layout TEXT NOT NULL DEFAULT 'monolithic',
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    chunk_size_items INTEGER,
                    manifest_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS result_data_chunks (
                    parent_content_hash TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_hash TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    offset_items INTEGER NOT NULL DEFAULT 0,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    stored_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(parent_content_hash,chunk_index),
                    FOREIGN KEY(parent_content_hash) REFERENCES result_data_objects(content_hash) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS result_bundle_data_refs (
                    result_bundle_id TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    result_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(result_bundle_id,result_id),
                    FOREIGN KEY(result_bundle_id) REFERENCES result_bundles(id) ON DELETE CASCADE,
                    FOREIGN KEY(content_hash) REFERENCES result_data_objects(content_hash)
                );
                CREATE TABLE IF NOT EXISTS engineering_requirement_sets (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    current_revision INTEGER NOT NULL DEFAULT 0,
                    current_revision_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(current_revision_id) REFERENCES engineering_requirement_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS engineering_requirement_revisions (
                    id TEXT PRIMARY KEY,
                    requirement_set_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    requirements_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(requirement_set_id,revision),
                    FOREIGN KEY(requirement_set_id) REFERENCES engineering_requirement_sets(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS qualification_campaigns (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    current_revision INTEGER NOT NULL DEFAULT 0,
                    current_revision_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(current_revision_id) REFERENCES qualification_campaign_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS qualification_campaign_revisions (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    campaign_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(campaign_id,revision),
                    FOREIGN KEY(campaign_id) REFERENCES qualification_campaigns(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS manufacturing_tolerance_sets (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    current_revision INTEGER NOT NULL DEFAULT 0,
                    current_revision_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(current_revision_id) REFERENCES manufacturing_tolerance_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS manufacturing_tolerance_revisions (
                    id TEXT PRIMARY KEY,
                    tolerance_set_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    tolerance_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(tolerance_set_id,revision),
                    FOREIGN KEY(tolerance_set_id) REFERENCES manufacturing_tolerance_sets(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS probabilistic_qualification_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    tolerance_revision_id TEXT NOT NULL,
                    requirement_revision_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    formal_qualified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(tolerance_revision_id) REFERENCES manufacturing_tolerance_revisions(id),
                    FOREIGN KEY(requirement_revision_id) REFERENCES engineering_requirement_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS active_learning_proposals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    design_revision_id TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(design_revision_id) REFERENCES motor_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS project_baseline_references (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    result_bundle_id TEXT NOT NULL,
                    result_bundle_hash TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'ACTIVE',
                    eligibility_status TEXT NOT NULL DEFAULT 'REVIEW_ONLY',
                    fingerprint_json TEXT NOT NULL,
                    fingerprint_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    supersedes_id TEXT,
                    created_at TEXT NOT NULL,
                    deactivated_at TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(result_bundle_id) REFERENCES result_bundles(id),
                    FOREIGN KEY(case_id) REFERENCES cases(id),
                    FOREIGN KEY(supersedes_id) REFERENCES project_baseline_references(id)
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
                    FOREIGN KEY(design_revision_id) REFERENCES motor_revisions(id),
                    FOREIGN KEY(scenario_revision_id) REFERENCES scenario_revisions(id)
                );
                CREATE TABLE IF NOT EXISTS candidate_result_sets (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    motor_patch_hash TEXT NOT NULL,
                    operating_point_set_hash TEXT NOT NULL,
                    result_set_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    complete INTEGER NOT NULL DEFAULT 0,
                    feasible INTEGER NOT NULL DEFAULT 0,
                    representative_case_id TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id,candidate_id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS robust_candidate_evaluations (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    motor_patch_hash TEXT NOT NULL,
                    uncertainty_scenario_set_hash TEXT NOT NULL,
                    robustness_plan_hash TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    complete INTEGER NOT NULL DEFAULT 0,
                    robust_feasible INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id,candidate_id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS candidate_validation_reports (
                    report_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    source_case_id TEXT NOT NULL,
                    validation_task_id TEXT,
                    report_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    promotion_allowed INTEGER NOT NULL DEFAULT 0,
                    formal_validation INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id),
                    FOREIGN KEY(source_case_id) REFERENCES cases(id),
                    FOREIGN KEY(validation_task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS optimization_decision_snapshots (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    snapshot_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id,generation),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS optimization_evidence_ledgers (
                    ledger_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    source_case_id TEXT,
                    promoted_revision_id TEXT,
                    entry_count INTEGER NOT NULL DEFAULT 0,
                    head_chain_hash TEXT,
                    content_hash TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'OPEN',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id,candidate_id)
                );
                CREATE TABLE IF NOT EXISTS optimization_evidence_ledger_entries (
                    entry_id TEXT PRIMARY KEY,
                    ledger_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL,
                    previous_chain_hash TEXT,
                    chain_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(ledger_id,sequence),
                    FOREIGN KEY(ledger_id) REFERENCES optimization_evidence_ledgers(ledger_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS optimization_replay_plans (
                    replay_plan_id TEXT PRIMARY KEY,
                    ledger_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    source_sequence INTEGER NOT NULL,
                    source_entry_hash TEXT NOT NULL,
                    source_chain_hash TEXT NOT NULL,
                    source_evidence_hash TEXT NOT NULL,
                    compare_policy TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    plan_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(ledger_id) REFERENCES optimization_evidence_ledgers(ledger_id)
                );
                CREATE TABLE IF NOT EXISTS optimization_replay_runs (
                    replay_run_id TEXT PRIMARY KEY,
                    replay_plan_id TEXT NOT NULL,
                    ledger_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(replay_plan_id) REFERENCES optimization_replay_plans(replay_plan_id),
                    FOREIGN KEY(ledger_id) REFERENCES optimization_evidence_ledgers(ledger_id)
                );
                CREATE TABLE IF NOT EXISTS reproducibility_environment_capsules (
                    capsule_id TEXT PRIMARY KEY,
                    capture_mode TEXT NOT NULL DEFAULT 'standard',
                    capsule_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signed_evidence_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    ledger_id TEXT NOT NULL,
                    ledger_head_hash TEXT NOT NULL,
                    capsule_id TEXT NOT NULL,
                    capsule_hash TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    key_source TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    anchor_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(ledger_id,ledger_head_hash,capsule_hash),
                    FOREIGN KEY(ledger_id) REFERENCES optimization_evidence_ledgers(ledger_id),
                    FOREIGN KEY(capsule_id) REFERENCES reproducibility_environment_capsules(capsule_id)
                );
                CREATE TABLE IF NOT EXISTS optimization_decision_timeline_entries (
                    entry_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    subject_hash TEXT,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    previous_chain_hash TEXT,
                    chain_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id,sequence),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS workstation_acceptance_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    target_motorcad_version TEXT NOT NULL,
                    licensed_motorcad_evidence INTEGER NOT NULL DEFAULT 0,
                    mock_disabled INTEGER NOT NULL DEFAULT 1,
                    formal_qualified INTEGER NOT NULL DEFAULT 0,
                    evidence_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sensitivity_studies (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    output_id TEXT NOT NULL,
                    methods_json TEXT NOT NULL,
                    study_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id,output_id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
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
                CREATE TABLE IF NOT EXISTS material_databases (
                    path TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'mixed',
                    file_hash TEXT NOT NULL DEFAULT '',
                    material_count INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT '',
                    last_scanned_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS material_library_records (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    material_type TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_database_path TEXT,
                    source_database_hash TEXT,
                    motorcad_version TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS native_parity_runs (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    motorcad_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    qualified INTEGER NOT NULL DEFAULT 0,
                    evidence_json TEXT NOT NULL,
                    artifact_dir TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cases_task ON cases(task_id);
                CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, case_id);
                CREATE INDEX IF NOT EXISTS idx_stages_case ON case_stages(case_id, id);
                CREATE INDEX IF NOT EXISTS idx_solutions_project ON solutions(project_id);
                CREATE INDEX IF NOT EXISTS idx_motor_revisions_solution ON motor_revisions(solution_id, revision);
                CREATE INDEX IF NOT EXISTS idx_analysis_definitions_project ON analysis_definitions(project_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_analysis_definitions_design_revision ON analysis_definitions(design_revision_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_analysis_definition_revisions_parent ON analysis_definition_revisions(analysis_definition_id,revision);
                CREATE INDEX IF NOT EXISTS idx_scenarios_project ON scenarios(project_id);
                CREATE INDEX IF NOT EXISTS idx_scenario_revisions_scenario ON scenario_revisions(scenario_id, revision);
                CREATE INDEX IF NOT EXISTS idx_solver_profiles_project ON solver_profiles(project_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_solver_profile_revisions_profile ON solver_profile_revisions(solver_profile_id,revision);
                CREATE INDEX IF NOT EXISTS idx_output_profiles_project ON output_profiles(project_id,updated_at);
                CREATE INDEX IF NOT EXISTS idx_output_profile_revisions_profile ON output_profile_revisions(output_profile_id,revision);
                CREATE INDEX IF NOT EXISTS idx_run_configurations_project ON run_configurations(project_id,created_at);
                CREATE INDEX IF NOT EXISTS idx_execution_plans_project ON execution_plans(project_id,created_at);
                CREATE INDEX IF NOT EXISTS idx_execution_plans_analysis_revision ON execution_plans(analysis_definition_revision_id,created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_plans_content ON execution_plans(project_id,content_hash);

                CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset ON dataset_versions(dataset_id, version);
                CREATE INDEX IF NOT EXISTS idx_dataset_members_case ON dataset_members(case_id);
                CREATE INDEX IF NOT EXISTS idx_qualification_template ON qualification_records(template_id,motorcad_version,analysis,created_at);
                CREATE INDEX IF NOT EXISTS idx_material_bindings_template ON material_bindings(template_id,motorcad_version,status);
                CREATE INDEX IF NOT EXISTS idx_result_calibrations_template ON result_calibrations(template_id,motorcad_version,status);
                CREATE INDEX IF NOT EXISTS idx_material_library_name ON material_library_records(name,material_type);
                CREATE INDEX IF NOT EXISTS idx_material_library_source ON material_library_records(source_kind,source_database_path);
                CREATE INDEX IF NOT EXISTS idx_native_parity_profile ON native_parity_runs(profile_id,motorcad_version,created_at);
                """
            )
            # V0.73-A: native qualification is scoped to the exact binding contract.
            # Existing databases are upgraded in-place; historical evidence remains
            # readable but cannot satisfy a new scope until re-qualified.
            for name, ddl in {
                "topology_id": "TEXT NOT NULL DEFAULT ''",
                "binding_version": "TEXT NOT NULL DEFAULT ''",
                "binding_plan_hash": "TEXT NOT NULL DEFAULT ''",
                "qualification_key": "TEXT NOT NULL DEFAULT ''",
                "required_pymotorcad_version": "TEXT NOT NULL DEFAULT ''",
                "pymotorcad_version": "TEXT NOT NULL DEFAULT ''",
                "qualification_contract_version": "INTEGER NOT NULL DEFAULT 1",
                "evidence_sha256": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(conn, "native_parity_runs", name, ddl)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_native_parity_scope ON native_parity_runs(profile_id,motorcad_version,qualification_key,created_at)")
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
                "analysis_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "analysis_snapshot_schema_version": "INTEGER NOT NULL DEFAULT 1",
                "analysis_snapshot_hash": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(conn, "analysis_definition_revisions", name, ddl)
            for name, ddl in {
                "execution_plan_id": "TEXT",
                "execution_plan_hash": "TEXT",
                "execution_plan_schema_version": "INTEGER",
            }.items():
                self._ensure_column(conn, "run_configurations", name, ddl)
            for name, ddl in {
                "task_id": "TEXT",
                "analysis_definition_revision_id": "TEXT",
                "execution_plan_id": "TEXT",
                "execution_plan_hash": "TEXT",
                "lifecycle_state": "TEXT NOT NULL DEFAULT 'DEFINED'",
                "last_route": "TEXT",
                "started_at": "TEXT",
                "finished_at": "TEXT",
                "optimization_space_json": "TEXT",
                "optimization_space_hash": "TEXT",
                "optimization_space_schema_version": "INTEGER",
                "experiment_plan_json": "TEXT",
                "experiment_plan_hash": "TEXT",
                "experiment_plan_schema_version": "INTEGER",
                "operating_point_set_json": "TEXT",
                "operating_point_set_hash": "TEXT",
                "operating_point_set_schema_version": "INTEGER",
                "uncertainty_scenario_set_json": "TEXT",
                "uncertainty_scenario_set_hash": "TEXT",
                "uncertainty_scenario_set_schema_version": "INTEGER",
                "robustness_plan_json": "TEXT",
                "robustness_plan_hash": "TEXT",
                "robustness_plan_schema_version": "INTEGER",
            }.items():
                self._ensure_column(conn, "experiments", name, ddl)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_task ON experiments(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_execution_plan ON experiments(execution_plan_id)")
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
                "execution_plan_id": "TEXT",
                "execution_plan_hash": "TEXT",
                "execution_plan_schema_version": "INTEGER",
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
                "scenario_json": "TEXT",
                "execution_plan_id": "TEXT",
                "execution_plan_hash": "TEXT",
                "result_bundle_id": "TEXT",
                "result_bundle_hash": "TEXT",
                "result_bundle_schema_version": "INTEGER",
                "motor_patch_json": "TEXT",
                "motor_patch_hash": "TEXT",
                "motor_patch_schema_version": "INTEGER",
                "candidate_id": "TEXT",
                "operating_point_id": "TEXT",
                "operating_point_index": "INTEGER",
                "uncertainty_sample_id": "TEXT",
                "uncertainty_sample_index": "INTEGER",
                "is_nominal_uncertainty": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                self._ensure_column(conn, "cases", name, ddl)
            self._ensure_column(conn, "motorcad_sessions", "reuse_effective", "INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_run_configuration ON tasks(run_configuration_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_result_bundles_task ON result_bundles(task_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_result_bundles_execution_plan ON result_bundles(execution_plan_id,created_at)")
            for name, ddl in {
                "layout": "TEXT NOT NULL DEFAULT 'monolithic'",
                "chunk_count": "INTEGER NOT NULL DEFAULT 0",
                "chunk_size_items": "INTEGER",
                "manifest_hash": "TEXT",
            }.items():
                self._ensure_column(conn, "result_data_objects", name, ddl)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_result_data_refs_hash ON result_bundle_data_refs(content_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_result_data_refs_bundle ON result_bundle_data_refs(result_bundle_id,result_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_engineering_requirement_sets_project ON engineering_requirement_sets(project_id,updated_at)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_engineering_requirement_active_project ON engineering_requirement_sets(project_id) WHERE state='ACTIVE'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_engineering_requirement_revisions_set ON engineering_requirement_revisions(requirement_set_id,revision)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qualification_campaigns_project ON qualification_campaigns(project_id,updated_at)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_qualification_campaign_active_project ON qualification_campaigns(project_id) WHERE state='ACTIVE'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qualification_campaign_revisions_campaign ON qualification_campaign_revisions(campaign_id,revision)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_manufacturing_tolerance_sets_project ON manufacturing_tolerance_sets(project_id,updated_at)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_manufacturing_tolerance_active_project ON manufacturing_tolerance_sets(project_id) WHERE state='ACTIVE'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_manufacturing_tolerance_revisions_set ON manufacturing_tolerance_revisions(tolerance_set_id,revision)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_probabilistic_qualification_project ON probabilistic_qualification_runs(project_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_active_learning_project ON active_learning_proposals(project_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_baseline_history ON project_baseline_references(project_id,created_at)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_project_baseline_active ON project_baseline_references(project_id) WHERE state='ACTIVE'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_optimization_decision_timeline_task ON optimization_decision_timeline_entries(task_id,sequence)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workstation_acceptance_updated ON workstation_acceptance_runs(updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_result_data_chunks_parent ON result_data_chunks(parent_content_hash,chunk_index)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_result_data_chunks_hash ON result_data_chunks(chunk_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_execution_plan ON tasks(execution_plan_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_execution_plan ON cases(execution_plan_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_candidate_point ON cases(task_id,candidate_id,operating_point_id,generation)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_result_sets_task ON candidate_result_sets(task_id,generation,candidate_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_candidate_uncertainty_point ON cases(task_id,candidate_id,uncertainty_sample_id,operating_point_id,generation)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_robust_candidate_evaluations_task ON robust_candidate_evaluations(task_id,generation,candidate_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_validation_reports_candidate ON candidate_validation_reports(task_id,candidate_id,updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_validation_reports_validation_task ON candidate_validation_reports(validation_task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_optimization_decision_snapshots_task ON optimization_decision_snapshots(task_id,generation,updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_optimization_evidence_ledgers_task ON optimization_evidence_ledgers(task_id,candidate_id,updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_optimization_evidence_entries_ledger ON optimization_evidence_ledger_entries(ledger_id,sequence)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_optimization_replay_plans_ledger ON optimization_replay_plans(ledger_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_optimization_replay_runs_plan ON optimization_replay_runs(replay_plan_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reproducibility_capsules_created ON reproducibility_environment_capsules(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signed_evidence_anchors_ledger ON signed_evidence_anchors(ledger_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signed_evidence_anchors_head ON signed_evidence_anchors(ledger_id,ledger_head_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sensitivity_studies_task ON sensitivity_studies(task_id,output_id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_submission_key ON tasks(submission_key) WHERE submission_key IS NOT NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_hash ON cases(input_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_execution_quality ON cases(execution_status,quality_status,cache_eligible)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_runtime_resource_lease ON cases(runtime_resource_lease_id)")
            self._ensure_column(conn, "motor_revisions", "explicit_parameter_ids_json", "TEXT NOT NULL DEFAULT '[]'")
            for name, ddl in {
                "candidate_validation_report_id": "TEXT",
                "candidate_validation_report_hash": "TEXT",
                "promotion_source_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                self._ensure_column(conn, "motor_revisions", name, ddl)
            for name, ddl in {
                "motor_type_id": "TEXT NOT NULL DEFAULT ''",
                "source_kind": "TEXT NOT NULL DEFAULT 'template'",
                "source_reference": "TEXT NOT NULL DEFAULT ''",
                "geometry_mode": "TEXT NOT NULL DEFAULT 'dimensions'",
                "source_mot_path": "TEXT",
                "capability_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                self._ensure_column(conn, "solutions", name, ddl)
            for name, ddl in {
                "automation_parameters_json": "TEXT NOT NULL DEFAULT '{}'",
                "capability_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "source_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "mot_artifact_path": "TEXT",
                "motor_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "motor_snapshot_schema_version": "INTEGER NOT NULL DEFAULT 1",
                "motor_snapshot_hash": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(conn, "motor_revisions", name, ddl)
            self._ensure_column(conn, "solution_drafts", "version", "INTEGER NOT NULL DEFAULT 1")
            for name, ddl in {
                "motor_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "motor_snapshot_schema_version": "INTEGER NOT NULL DEFAULT 1",
                "motor_snapshot_hash": "TEXT NOT NULL DEFAULT ''",
                "editor_transaction_id": "TEXT NOT NULL DEFAULT ''",
                "editor_intent_hash": "TEXT NOT NULL DEFAULT ''",
                "editor_intent_version": "INTEGER NOT NULL DEFAULT 0",
                "native_reconciliation_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                self._ensure_column(conn, "solution_drafts", name, ddl)
            for name, ddl in {
                "editor_transaction_json": "TEXT NOT NULL DEFAULT '{}'",
                "native_reconciliation_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                self._ensure_column(conn, "motor_revisions", name, ddl)
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_motor_revisions_commit_key
                   ON motor_revisions(solution_id, json_extract(editor_transaction_json,'$.commit_key'))"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_solution_drafts_base_revision ON solution_drafts(base_motor_revision_id)")
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
            self._install_legacy_solution_views(conn)
            self._install_v091_control_plane_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )
            self._install_lineage_generation_triggers(conn)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize a multi-call domain operation across nested database helpers."""
        with self._lock:
            yield

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
                # SQLite WAL supports concurrent readers. Avoid the process-wide
                # write lock and an unnecessary commit for pure SELECT requests.
                with self.connect(commit=False) as conn:
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
                with self.connect(commit=False) as conn:
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
