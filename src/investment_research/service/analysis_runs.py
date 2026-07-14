from __future__ import annotations

from investment_research.domain.base import utc_now
from investment_research.domain.enums import DataMode
from investment_research.domain.models import AnalysisRun
from investment_research.domain.decision_context import DecisionContextType
from investment_research.domain.models import AuditRecord
from investment_research.domain.models import User
from investment_research.pipeline.models import AnalysisBundle
from investment_research.pipeline.service import AnalysisPipelineService
from investment_research.report.service import ReportService
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import AnalysisProviderRegistry
from investment_research.service.catalog import DomainCatalogService
from investment_research.service.data_mode import DataModePolicyService


class AnalysisRunsService:
    """Application service for immutable analysis-run lifecycle operations."""

    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        provider_registry: AnalysisProviderRegistry | None = None,
    ) -> None:
        self.uow = uow
        self.provider_registry = provider_registry
        self.catalog = DomainCatalogService(provider_registry=provider_registry)
        self.mode_policy = DataModePolicyService()

    def persist_demo_analysis_run(self) -> AnalysisRun:
        try:
            run = self.catalog.build_demo_analysis_run()
            self.uow.analysis_runs.add(run)
            return run
        finally:
            self.uow.close()

    def persist_demo_analysis_run_for_user(self, *, user: User) -> AnalysisRun:
        try:
            run = self.catalog.build_demo_analysis_run_for_user(user)
            stored = self.uow.analysis_runs.add(run)
            self._record_audit(
                actor=user.auth_subject,
                action="analysis-run.persisted",
                target_type="analysis_run",
                target_id=stored.id,
                details={"asset_id": str(stored.asset_id), "mode": stored.provenance.data_mode.value},
                data_mode=stored.provenance.data_mode,
            )
            return stored
        finally:
            self.uow.close()

    def get_analysis_run(self, run_id: str) -> AnalysisRun | None:
        try:
            return self.uow.analysis_runs.get(run_id)
        finally:
            self.uow.close()

    def get_analysis_run_for_user(self, run_id: str, *, user: User) -> AnalysisRun | None:
        try:
            run = self.uow.analysis_runs.get(run_id)
            if run is None or not self._run_belongs_to_user(run, user):
                return None
            return run
        finally:
            self.uow.close()

    def list_analysis_runs_for_asset(self, asset_id: str) -> list[AnalysisRun]:
        try:
            return self.uow.analysis_runs.list_for_asset(asset_id)
        finally:
            self.uow.close()

    def list_analysis_runs_for_asset_for_user(self, asset_id: str, *, user: User) -> list[AnalysisRun]:
        try:
            return [
                run
                for run in self.uow.analysis_runs.list_for_asset(asset_id)
                if self._run_belongs_to_user(run, user)
            ]
        finally:
            self.uow.close()

    def trigger_analysis_for_asset(
        self,
        asset_id: str,
        *,
        user: User,
        decision_context: DecisionContextType | str = DecisionContextType.CLOSE_CONFIRMED,
    ) -> AnalysisBundle:
        try:
            bundle = AnalysisPipelineService(self.uow, provider_registry=self.provider_registry).build_analysis_for_asset(
                asset_id, user=user, decision_context=decision_context
            )
            self._record_audit(
                actor=user.auth_subject,
                action="analysis-run.created",
                target_type="analysis_run",
                target_id=bundle.run.id,
                details={
                    "asset_id": asset_id,
                    "evidence_count": str(len(bundle.evidence)),
                    "mode": bundle.run.provenance.data_mode.value,
                    "decision_context": bundle.snapshot.decision_context,
                    "market_snapshot_id": bundle.snapshot.market_snapshot_id or "unknown",
                },
                data_mode=bundle.run.provenance.data_mode,
            )
            return bundle
        finally:
            self.uow.close()

    def get_analysis_bundle(self, run_id: str) -> AnalysisBundle | None:
        try:
            return AnalysisPipelineService(self.uow, provider_registry=self.provider_registry).get_bundle(run_id)
        finally:
            self.uow.close()

    def get_analysis_bundle_for_user(self, run_id: str, *, user: User) -> AnalysisBundle | None:
        try:
            bundle = AnalysisPipelineService(self.uow, provider_registry=self.provider_registry).get_bundle(run_id)
            if bundle is None or not self._run_belongs_to_user(bundle.run, user):
                return None
            return bundle
        finally:
            self.uow.close()

    def generate_report_for_run(self, run_id: str, *, user: User | None = None) -> AnalysisBundle:
        try:
            bundle = AnalysisPipelineService(self.uow, provider_registry=self.provider_registry).get_bundle(run_id)
            if bundle is None:
                raise ValueError("Analysis run not found")
            if user is not None and not self._run_belongs_to_user(bundle.run, user):
                raise ValueError("Analysis run not found")
            report = ReportService(self.uow).create_report_from_bundle(bundle)
            self._record_audit(
                actor=bundle.run.triggered_by,
                action="report.generated",
                target_type="research_report",
                target_id=report.id,
                details={"analysis_run_id": run_id, "asset_id": str(bundle.asset.id)},
                data_mode=bundle.run.provenance.data_mode,
            )
            refreshed = AnalysisPipelineService(self.uow, provider_registry=self.provider_registry).get_bundle(run_id)
            if refreshed is None:
                return bundle.model_copy(
                    update={
                        "run": bundle.run.model_copy(update={"report_ids": [*bundle.run.report_ids, report.id], "report_version": report.report_version}),
                        "reports": [*bundle.reports, report],
                    }
                )
            return refreshed
        finally:
            self.uow.close()

    def _record_audit(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id,
        details: dict[str, str],
        data_mode: DataMode,
    ) -> None:
        record = AuditRecord(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            provenance=self.mode_policy.build_audit_provenance(data_mode=data_mode, observed_at=utc_now()),
        )
        self.uow.audit_records.add(record)

    def _run_belongs_to_user(self, run: AnalysisRun, user: User) -> bool:
        return run.triggered_by == user.auth_subject
