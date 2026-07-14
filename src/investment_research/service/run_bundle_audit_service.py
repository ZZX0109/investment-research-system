from __future__ import annotations

import sqlite3
from typing import Any

from investment_research.service.run_bundle_models import RunBundleAuditRunDetail
from investment_research.service.run_bundle_models import RunBundleAuditRunSummary
from investment_research.service.run_bundle_models import RunBundleAuditStatus
from investment_research.service.run_bundle_store import RunBundleFileStore


class RunBundleAuditService:
    """Read-only access to the persisted Test Officer audit database."""

    def __init__(self, store: RunBundleFileStore) -> None:
        self.store = store

    def get_audit_status(self) -> RunBundleAuditStatus:
        database_path = self.store.runs_root / "audit" / "audit.sqlite"
        if not database_path.exists():
            return RunBundleAuditStatus(
                databasePath=str(database_path),
                schemaVersion="missing",
                schemaMigrationCount=0,
                schemaAppliedAt=None,
                exists=False,
                runs=0,
                evidence=0,
                artifacts=0,
                findings=0,
                judgeResults=0,
                gateResults=0,
                sourceContexts=0,
                failureAttributions=0,
                runtimeLifecycle=0,
                events=0,
                journalMode="unknown",
            )

        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            return RunBundleAuditStatus.model_validate(
                {
                    "databasePath": str(database_path),
                    "schemaVersion": self._read_audit_schema_version(connection),
                    "schemaMigrationCount": self._count(connection, "audit_schema_migrations"),
                    "schemaAppliedAt": self._read_audit_schema_applied_at(connection),
                    "exists": True,
                    "runs": self._count(connection, "runs"),
                    "evidence": self._count(connection, "evidence"),
                    "artifacts": self._count(connection, "artifacts"),
                    "findings": self._count(connection, "findings"),
                    "judgeResults": self._count(connection, "judge_results"),
                    "gateResults": self._count(connection, "gate_results"),
                    "sourceContexts": self._count(connection, "source_contexts"),
                    "failureAttributions": self._count(connection, "failure_attributions"),
                    "runtimeLifecycle": self._count(connection, "runtime_lifecycle"),
                    "events": self._count(connection, "audit_events"),
                    "journalMode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
                }
            )
        finally:
            connection.close()

    def list_audit_runs(
        self,
        *,
        project_id: str | None = None,
        target_app_id: str | None = None,
        mission_id: str | None = None,
        status: str | None = None,
        review_status: str | None = None,
        limit: int = 50,
    ) -> list[RunBundleAuditRunSummary]:
        database_path = self.store.runs_root / "audit" / "audit.sqlite"
        if not database_path.exists():
            return []

        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            clauses: list[str] = []
            values: list[Any] = []
            self._add_audit_filter(clauses, values, "project_id", project_id)
            self._add_audit_filter(clauses, values, "target_app_id", target_app_id)
            self._add_audit_filter(clauses, values, "mission_id", mission_id)
            self._add_audit_filter(clauses, values, "status", status)
            self._add_audit_filter(clauses, values, "review_status", review_status)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(
                f"""
                SELECT
                  run_id,
                  project_id,
                  mission_id,
                  mission_name,
                  target_app_id,
                  target_app_name,
                  status,
                  review_status,
                  started_at,
                  finished_at,
                  bundle_uri,
                  created_at,
                  updated_at
                FROM runs
                {where}
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                [*values, max(1, min(limit, 500))],
            ).fetchall()
            return [
                RunBundleAuditRunSummary.model_validate(
                    {
                        "runId": row["run_id"],
                        "projectId": row["project_id"],
                        "missionId": row["mission_id"],
                        "missionName": row["mission_name"],
                        "targetAppId": row["target_app_id"],
                        "targetAppName": row["target_app_name"],
                        "status": row["status"],
                        "reviewStatus": row["review_status"],
                        "startedAt": row["started_at"],
                        "finishedAt": row["finished_at"],
                        "bundleUri": row["bundle_uri"],
                        "createdAt": row["created_at"],
                        "updatedAt": row["updated_at"],
                    }
                )
                for row in rows
            ]
        finally:
            connection.close()

    def get_audit_run_detail(self, run_id: str) -> RunBundleAuditRunDetail:
        database_path = self.store.runs_root / "audit" / "audit.sqlite"
        if not database_path.exists():
            raise FileNotFoundError(f"Audit database not found for {run_id}")

        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            run_exists = connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
            if run_exists is None:
                raise FileNotFoundError(f"Audit run not found: {run_id}")

            source_context_rows = connection.execute(
                """
                SELECT
                  source_context_id,
                  kind,
                  read_state,
                  source_ref,
                  failure_reason,
                  permissions_json,
                  usage_scopes_json
                FROM source_contexts
                WHERE run_id = ?
                ORDER BY kind, source_context_id
                """,
                [run_id],
            ).fetchall()
            attribution_rows = connection.execute(
                """
                SELECT
                  attribution_id,
                  finding_id,
                  scenario_id,
                  step_id,
                  rank,
                  category,
                  confidence,
                  likely_cause,
                  recommendation,
                  signals_json
                FROM failure_attributions
                WHERE run_id = ?
                ORDER BY rank ASC, attribution_id
                """,
                [run_id],
            ).fetchall()
            artifact_metadata_column = self._has_table_column(connection, "artifacts", "metadata_json")
            artifact_metadata_select = "metadata_json" if artifact_metadata_column else "'{}' AS metadata_json"
            artifact_rows = connection.execute(
                f"""
                SELECT
                  artifact_id,
                  evidence_id,
                  kind,
                  status,
                  artifact_uri,
                  media_type,
                  size_bytes,
                  {artifact_metadata_select}
                FROM artifacts
                WHERE run_id = ?
                ORDER BY kind, artifact_id
                """,
                [run_id],
            ).fetchall()
            try:
                gate_rows = connection.execute(
                    """
                    SELECT
                      gate_id,
                      passed,
                      exit_code,
                      reasons_json,
                      diagnostics_json,
                      generated_at
                    FROM gate_results
                    WHERE run_id = ?
                    ORDER BY generated_at DESC, gate_id
                    """,
                    [run_id],
                ).fetchall()
            except sqlite3.OperationalError:
                gate_rows = []
            runtime_rows = connection.execute(
                """
                SELECT
                  phase_id,
                  phase,
                  status,
                  summary
                FROM runtime_lifecycle
                WHERE run_id = ?
                ORDER BY phase_id
                """,
                [run_id],
            ).fetchall()
            return RunBundleAuditRunDetail.model_validate(
                {
                    "runId": run_id,
                    "sourceContexts": [
                        {
                            "id": row["source_context_id"],
                            "kind": row["kind"],
                            "readState": row["read_state"],
                            "sourceRef": row["source_ref"],
                            "failureReason": row["failure_reason"],
                            "permissions": self.store.read_json_value(row["permissions_json"], []),
                            "usageScopes": self.store.read_json_value(row["usage_scopes_json"], []),
                        }
                        for row in source_context_rows
                    ],
                    "failureAttributions": [
                        {
                            "id": row["attribution_id"],
                            "findingId": row["finding_id"],
                            "scenarioId": row["scenario_id"],
                            "stepId": row["step_id"],
                            "rank": row["rank"],
                            "category": row["category"],
                            "confidence": row["confidence"],
                            "likelyCause": row["likely_cause"] or None,
                            "recommendation": row["recommendation"] or None,
                            "signals": self.store.read_json_value(row["signals_json"], {}),
                        }
                        for row in attribution_rows
                    ],
                    "artifacts": [
                        {
                            "id": row["artifact_id"],
                            "evidenceId": row["evidence_id"],
                            "kind": row["kind"],
                            "status": row["status"],
                            "artifactUri": row["artifact_uri"],
                            "mediaType": row["media_type"],
                            "sizeBytes": row["size_bytes"],
                            "metadata": self.store.read_json_value(row["metadata_json"], {}),
                        }
                        for row in artifact_rows
                    ],
                    "gateResults": [
                        {
                            "id": row["gate_id"],
                            "passed": bool(row["passed"]),
                            "exitCode": row["exit_code"],
                            "reasons": self.store.read_json_value(row["reasons_json"], []),
                            "diagnostics": self.store.read_json_value(row["diagnostics_json"], {}),
                            "generatedAt": row["generated_at"],
                        }
                        for row in gate_rows
                    ],
                    "runtimeLifecycle": [
                        {
                            "id": row["phase_id"],
                            "phase": row["phase"],
                            "status": row["status"],
                            "summary": row["summary"],
                        }
                        for row in runtime_rows
                    ],
                }
            )
        finally:
            connection.close()

    def get_audit_run_project_id(self, run_id: str) -> str:
        database_path = self.store.runs_root / "audit" / "audit.sqlite"
        if not database_path.exists():
            raise FileNotFoundError(f"Audit database not found for {run_id}")

        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT project_id FROM runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Audit run not found: {run_id}")
            return str(row["project_id"])
        finally:
            connection.close()

    def _has_table_column(self, connection: sqlite3.Connection, table: str, column: str) -> bool:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _count(self, connection: sqlite3.Connection, table: str) -> int:
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.OperationalError:
            return 0

    def _read_audit_schema_version(self, connection: sqlite3.Connection) -> str:
        try:
            row = connection.execute(
                """
                SELECT version
                FROM audit_schema_migrations
                ORDER BY version DESC
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.OperationalError:
            return "unknown"
        return str(row[0]) if row else "unknown"

    def _read_audit_schema_applied_at(self, connection: sqlite3.Connection) -> str | None:
        try:
            row = connection.execute(
                """
                SELECT applied_at
                FROM audit_schema_migrations
                ORDER BY version DESC
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return str(row[0]) if row else None

    @staticmethod
    def _add_audit_filter(
        clauses: list[str],
        values: list[Any],
        column: str,
        value: str | None,
    ) -> None:
        if not value:
            return
        clauses.append(f"{column} = ?")
        values.append(value)
