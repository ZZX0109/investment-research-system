from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from investment_research.service.run_bundle_artifact_service import ArtifactDecryptionError
from investment_research.service.run_bundle_artifact_service import RunBundleArtifactDelivery
from investment_research.service.run_bundle_artifact_service import RunBundleArtifactService
from investment_research.service.run_bundle_audit_service import RunBundleAuditService
from investment_research.service.run_bundle_manifest_service import RunBundleManifestService
from investment_research.service.run_bundle_models import RunBundleArtifactIntegrityReport
from investment_research.service.run_bundle_models import RunBundleAuditRunDetail
from investment_research.service.run_bundle_models import RunBundleAuditRunSummary
from investment_research.service.run_bundle_models import RunBundleAuditStatus
from investment_research.service.run_bundle_models import RunBundleComparisonReport
from investment_research.service.run_bundle_models import RunBundleDownloadManifest
from investment_research.service.run_bundle_models import RunBundleHistoryEntry
from investment_research.service.run_bundle_models import RunBundleHistoryIndex
from investment_research.service.run_bundle_models import RunBundleManifest
from investment_research.service.run_bundle_models import RunBundleRegistryManifest
from investment_research.service.run_bundle_models import RunBundleRetentionJobResult
from investment_research.service.run_bundle_registry_service import RunBundleRegistryService
from investment_research.service.run_bundle_retention_service import RunBundleRetentionService
from investment_research.service.run_bundle_store import RunBundleFileStore


def get_default_runs_root() -> Path:
    configured = os.getenv("AI_TEST_OFFICER_RUNS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd() / "runs"


class RunBundleService:
    """Compatibility facade over the split run-bundle services."""

    def __init__(self, runs_root: Path | None = None) -> None:
        self.runs_root = (runs_root or get_default_runs_root()).resolve()
        self.store = RunBundleFileStore(self.runs_root)
        self.manifests = RunBundleManifestService(self.store)
        self.registry = RunBundleRegistryService(self.store, self.manifests)
        self.artifacts = RunBundleArtifactService(self.store, self.manifests)
        self.retention = RunBundleRetentionService(self.store, self.manifests, self.registry)
        self.audit = RunBundleAuditService(self.store)

    def get_history(self) -> RunBundleHistoryIndex:
        return self.manifests.get_history()

    def list_runs(self, *, mission_id: str | None = None) -> list[RunBundleHistoryEntry]:
        return self.manifests.list_runs(mission_id=mission_id)

    def get_manifest(self, run_id: str) -> RunBundleManifest:
        return self.manifests.get_manifest(run_id)

    def get_latest_manifest(self, *, mission_id: str | None = None) -> RunBundleManifest:
        return self.manifests.get_latest_manifest(mission_id=mission_id)

    def get_comparison(self, run_id: str) -> RunBundleComparisonReport | None:
        return self.manifests.get_comparison(run_id)

    def get_registry_manifest(self, run_id: str) -> RunBundleRegistryManifest:
        return self.registry.get_registry_manifest(run_id)

    def get_registry_resource(self, run_id: str, resource_name: str) -> Any:
        return self.registry.get_registry_resource(run_id, resource_name)

    def get_artifact_path(self, run_id: str, artifact_name: str) -> Path:
        return self.artifacts.get_artifact_path(run_id, artifact_name)

    def get_artifact_delivery(self, run_id: str, artifact_name: str) -> RunBundleArtifactDelivery:
        return self.artifacts.get_artifact_delivery(run_id, artifact_name)

    def get_report_path(self, run_id: str, report_name: str) -> Path:
        report_root = (self.store.safe_run_root(run_id) / "reports").resolve()
        report_path = (report_root / report_name).resolve()
        if not report_path.is_file() or report_root not in report_path.parents:
            raise FileNotFoundError(f"Report not found for {run_id}: {report_name}")
        return report_path

    def execute_retention_job(
        self,
        run_id: str,
        *,
        apply: bool = False,
        now: str | None = None,
    ) -> RunBundleRetentionJobResult:
        return self.retention.execute_retention_job(run_id, apply=apply, now=now)

    def verify_artifact_integrity(self, run_id: str) -> RunBundleArtifactIntegrityReport:
        return self.artifacts.verify_artifact_integrity(run_id)

    def create_download_bundle(self, run_id: str) -> RunBundleDownloadManifest:
        return self.artifacts.create_download_bundle(run_id)

    def get_audit_status(self) -> RunBundleAuditStatus:
        return self.audit.get_audit_status()

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
        return self.audit.list_audit_runs(
            project_id=project_id,
            target_app_id=target_app_id,
            mission_id=mission_id,
            status=status,
            review_status=review_status,
            limit=limit,
        )

    def get_audit_run_detail(self, run_id: str) -> RunBundleAuditRunDetail:
        return self.audit.get_audit_run_detail(run_id)

    def get_audit_run_project_id(self, run_id: str) -> str:
        return self.audit.get_audit_run_project_id(run_id)
