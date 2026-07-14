from __future__ import annotations

import zipfile
from datetime import datetime

from investment_research.service.run_bundle_manifest_service import RunBundleManifestService
from investment_research.service.run_bundle_models import RunBundleRetentionCleanupCandidate
from investment_research.service.run_bundle_models import RunBundleRetentionCleanupPlan
from investment_research.service.run_bundle_models import RunBundleRetentionJobRecord
from investment_research.service.run_bundle_models import RunBundleRetentionJobResult
from investment_research.service.run_bundle_registry_service import RunBundleRegistryService
from investment_research.service.run_bundle_store import RunBundleFileStore


class RunBundleRetentionService:
    """Executes retention cleanup plans for persisted run bundles."""

    def __init__(
        self,
        store: RunBundleFileStore,
        manifests: RunBundleManifestService,
        registry: RunBundleRegistryService,
    ) -> None:
        self.store = store
        self.manifests = manifests
        self.registry = registry

    def execute_retention_job(
        self,
        run_id: str,
        *,
        apply: bool = False,
        now: str | None = None,
    ) -> RunBundleRetentionJobResult:
        manifest = self.manifests.get_manifest(run_id)
        plan = manifest.retentionCleanupPlan
        if plan is None:
            plan = self.registry.get_registry_resource(run_id, "retention-cleanup-plan")
        if not isinstance(plan, RunBundleRetentionCleanupPlan):
            plan = RunBundleRetentionCleanupPlan.model_validate(plan)

        now_dt = self.store.parse_timestamp(now)
        reports_dir = self.store.safe_run_root(run_id) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        archive_root = self.store.safe_run_root(run_id) / "archives" / "retention"
        records = [
            self._execute_retention_candidate(
                run_id,
                candidate,
                now_dt=now_dt,
                apply=apply,
                archive_root=archive_root,
            )
            for candidate in plan.candidates
        ]

        summary: dict[str, int] = {}
        for record in records:
            summary[record.status] = summary.get(record.status, 0) + 1

        report_path = reports_dir / "retention-job.json"
        result = RunBundleRetentionJobResult.model_validate(
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": now_dt.isoformat().replace("+00:00", "Z"),
                "dryRun": not apply,
                "archiveRoot": str(archive_root),
                "reportPath": str(report_path),
                "summary": summary,
                "records": records,
            }
        )
        report_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def _execute_retention_candidate(
        self,
        run_id: str,
        candidate: RunBundleRetentionCleanupCandidate,
        *,
        now_dt: datetime,
        apply: bool,
        archive_root,
    ) -> RunBundleRetentionJobRecord:
        record = RunBundleRetentionJobRecord(
            candidateId=candidate.id,
            kind=candidate.kind,
            action=candidate.action,
            status="skipped",
            path=candidate.path,
            reason=candidate.reason,
            archivedPath=None,
            originalDeleted=False,
            sizeBytes=getattr(candidate, "sizeBytes", None),
        )

        if candidate.protected or candidate.action == "retain":
            record.status = "protected"
            return record

        expires_at = candidate.expiresAt
        if expires_at and self.store.parse_timestamp(expires_at) > now_dt:
            record.status = "not-expired"
            return record

        try:
            target_path = self.store.resolve_run_path(run_id, candidate.path)
        except FileNotFoundError as exc:
            record.status = "path-escaped"
            record.reason = str(exc)
            return record

        if not target_path.exists():
            record.status = "missing"
            return record

        record.path = str(target_path)
        record.sizeBytes = target_path.stat().st_size
        if not apply:
            record.status = "planned"
            return record

        if candidate.action == "delete-after-retention":
            target_path.unlink()
            record.status = "deleted"
            record.originalDeleted = True
            return record

        if candidate.action == "archive-after-retention":
            archive_root.mkdir(parents=True, exist_ok=True)
            archive_path = archive_root / f"{candidate.id}.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(target_path, target_path.relative_to(self.store.safe_run_root(run_id)).as_posix())
            target_path.unlink()
            record.status = "archived"
            record.archivedPath = str(archive_path)
            record.originalDeleted = True
            return record

        record.status = "unsupported-action"
        return record
