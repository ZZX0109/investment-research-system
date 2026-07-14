from __future__ import annotations

from investment_research.api.schemas import (
    AssetCreateRequest,
    EvidenceCreateRequest,
    PositionCreateRequest,
    PriceSeriesCreateRequest,
    ResearchReportCreateRequest,
    WatchlistCreateRequest,
)
from investment_research.domain.models import (
    AnalysisRun,
    Asset,
    AuditRecord,
    Evidence,
    Position,
    PriceSeries,
    ResearchReport,
    User,
    Watchlist,
)
from investment_research.pipeline.models import AnalysisBundle, RunComparisonSummary, RunLineageTimeline
from investment_research.pipeline.run_views import RunDossierSummary, RunLineageDetailSummary, RunReplaySummary, RunScopeSummary
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_runs import AnalysisRunsService
from investment_research.service.analysis_intake import AnalysisProviderRegistry
from investment_research.service.portfolio_research import PortfolioResearchService
from investment_research.service.refresh import RefreshStatusService
from investment_research.service.run_views import RunViewsService


class WorkbenchService:
    """Application service that coordinates domain models with persistence."""

    def __init__(self, uow: SQLiteUnitOfWork, *, provider_registry: AnalysisProviderRegistry | None = None) -> None:
        self.uow = uow
        self.provider_registry = provider_registry

    def list_assets(self, *, source_type: str | None = None) -> list[Asset]:
        return PortfolioResearchService(self.uow).list_assets(source_type=source_type)

    def create_asset(self, payload: AssetCreateRequest) -> Asset:
        return PortfolioResearchService(self.uow).create_asset(payload)

    def create_asset_for_user(self, payload: AssetCreateRequest, *, user: User) -> Asset:
        return PortfolioResearchService(self.uow).create_asset_for_user(payload, user=user)

    def create_position_for_user(self, payload: PositionCreateRequest, *, user: User) -> Position:
        return PortfolioResearchService(self.uow).create_position_for_user(payload, user=user)

    def list_positions_for_user(self, *, user: User) -> list[Position]:
        return PortfolioResearchService(self.uow).list_positions_for_user(user=user)

    def create_watchlist_for_user(self, payload: WatchlistCreateRequest, *, user: User) -> Watchlist:
        return PortfolioResearchService(self.uow).create_watchlist_for_user(payload, user=user)

    def list_watchlists_for_user(self, *, user: User) -> list[Watchlist]:
        return PortfolioResearchService(self.uow).list_watchlists_for_user(user=user)

    def create_price_series(self, payload: PriceSeriesCreateRequest, *, user: User) -> PriceSeries:
        return PortfolioResearchService(self.uow).create_price_series(payload, user=user)

    def list_price_series_for_asset(self, asset_id: str) -> list[PriceSeries]:
        return PortfolioResearchService(self.uow).list_price_series_for_asset(asset_id)

    def create_evidence(self, payload: EvidenceCreateRequest, *, user: User) -> Evidence:
        return PortfolioResearchService(self.uow).create_evidence(payload, user=user)

    def list_evidence_for_asset(self, asset_id: str) -> list[Evidence]:
        return PortfolioResearchService(self.uow).list_evidence_for_asset(asset_id)

    def create_research_report(self, payload: ResearchReportCreateRequest, *, user: User) -> ResearchReport:
        return PortfolioResearchService(self.uow).create_research_report(payload, user=user)

    def list_reports_for_asset(self, asset_id: str) -> list[ResearchReport]:
        return PortfolioResearchService(self.uow).list_reports_for_asset(asset_id)

    def list_audit_records_for_user(self, *, user: User) -> list[AuditRecord]:
        return PortfolioResearchService(self.uow).list_audit_records_for_user(user=user)

    def persist_demo_analysis_run(self) -> AnalysisRun:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).persist_demo_analysis_run()

    def persist_demo_analysis_run_for_user(self, *, user: User) -> AnalysisRun:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).persist_demo_analysis_run_for_user(
            user=user
        )

    def get_analysis_run(self, run_id: str) -> AnalysisRun | None:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).get_analysis_run(run_id)

    def list_analysis_runs_for_asset(self, asset_id: str) -> list[AnalysisRun]:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).list_analysis_runs_for_asset(asset_id)

    def trigger_analysis_for_asset(
        self, asset_id: str, *, user: User, decision_context: str = "close_confirmed"
    ) -> AnalysisBundle:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).trigger_analysis_for_asset(
            asset_id, user=user, decision_context=decision_context
        )

    def get_analysis_bundle(self, run_id: str) -> AnalysisBundle | None:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).get_analysis_bundle(run_id)

    def get_run_comparison(self, run_id: str, *, baseline_run_id: str | None = None) -> RunComparisonSummary:
        try:
            return RunViewsService(self.uow, provider_registry=self.provider_registry).get_run_comparison(
                run_id,
                baseline_run_id=baseline_run_id,
            )
        finally:
            self.uow.close()

    def get_run_replay_summary(self, run_id: str) -> RunReplaySummary:
        try:
            return RunViewsService(self.uow, provider_registry=self.provider_registry).get_run_replay_summary(run_id)
        finally:
            self.uow.close()

    def get_run_dossier_summary(self, run_id: str) -> RunDossierSummary:
        try:
            return RunViewsService(self.uow, provider_registry=self.provider_registry).get_run_dossier_summary(run_id)
        finally:
            self.uow.close()

    def get_run_lineage_detail_summary(self, run_id: str) -> RunLineageDetailSummary:
        try:
            return RunViewsService(self.uow, provider_registry=self.provider_registry).get_run_lineage_detail_summary(run_id)
        finally:
            self.uow.close()

    def get_run_scope_summary(self, run_id: str) -> RunScopeSummary:
        try:
            return RunViewsService(self.uow, provider_registry=self.provider_registry).get_run_scope_summary(run_id)
        finally:
            self.uow.close()

    def get_run_lineage_timeline(self, asset_id: str) -> RunLineageTimeline:
        try:
            return RunViewsService(self.uow, provider_registry=self.provider_registry).get_run_lineage_timeline(asset_id)
        finally:
            self.uow.close()

    def get_run_refresh_status(self, run_id: str, *, user: User | None = None):
        try:
            service = RefreshStatusService(self.uow, provider_registry=self.provider_registry)
            if user is not None:
                return service.get_run_refresh_status_for_user(run_id, user=user)
            return service.get_run_refresh_status(run_id)
        finally:
            self.uow.close()

    def get_asset_refresh_status(self, asset_id: str, *, user: User | None = None):
        try:
            service = RefreshStatusService(self.uow, provider_registry=self.provider_registry)
            if user is not None:
                return service.get_asset_refresh_status_for_user(asset_id, user=user)
            return service.get_asset_refresh_status(asset_id)
        finally:
            self.uow.close()

    def generate_report_for_run(self, run_id: str) -> AnalysisBundle:
        return AnalysisRunsService(self.uow, provider_registry=self.provider_registry).generate_report_for_run(run_id)
