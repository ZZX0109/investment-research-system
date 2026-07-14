from __future__ import annotations

from investment_research.pipeline.run_view_builders import (
    build_asset_refresh_status_summary,
    build_run_refresh_status_summary,
)
from investment_research.pipeline.run_views import AssetRefreshStatusSummary, RunRefreshStatusSummary
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import AnalysisProviderRegistry
from investment_research.service.run_views import RunViewsService


class RefreshStatusService:
    """Read-only refresh boundary for stale-input and reproducibility status."""

    def __init__(self, uow: SQLiteUnitOfWork, *, provider_registry: AnalysisProviderRegistry | None = None) -> None:
        self.uow = uow
        self.provider_registry = provider_registry

    def get_run_refresh_status(self, run_id: str) -> RunRefreshStatusSummary:
        bundle = RunViewsService(self.uow, provider_registry=self.provider_registry)._get_bundle_or_raise(run_id)
        return build_run_refresh_status_summary(bundle)

    def get_run_refresh_status_for_user(self, run_id: str, *, user: User) -> RunRefreshStatusSummary:
        bundle = RunViewsService(self.uow, provider_registry=self.provider_registry)._get_bundle_for_user_or_raise(
            run_id,
            user=user,
        )
        return build_run_refresh_status_summary(bundle)

    def get_asset_refresh_status(self, asset_id: str) -> AssetRefreshStatusSummary:
        runs = self.uow.analysis_runs.list_for_asset(asset_id)
        latest_run = runs[0] if runs else None
        if latest_run is None:
            return build_asset_refresh_status_summary(asset_id, None)
        bundle = RunViewsService(self.uow, provider_registry=self.provider_registry)._get_bundle_or_raise(str(latest_run.id))
        return build_asset_refresh_status_summary(asset_id, bundle)

    def get_asset_refresh_status_for_user(self, asset_id: str, *, user: User) -> AssetRefreshStatusSummary:
        runs = [
            run
            for run in self.uow.analysis_runs.list_for_asset(asset_id)
            if run.triggered_by == user.auth_subject
        ]
        latest_run = runs[0] if runs else None
        if latest_run is None:
            return build_asset_refresh_status_summary(asset_id, None)
        bundle = RunViewsService(self.uow, provider_registry=self.provider_registry)._get_bundle_for_user_or_raise(
            str(latest_run.id),
            user=user,
        )
        return build_asset_refresh_status_summary(asset_id, bundle)
