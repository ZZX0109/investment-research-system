from __future__ import annotations

from investment_research.domain.models import AuditRecord
from investment_research.domain.models import User
from investment_research.pipeline.models import AnalysisBundle, RunComparisonSummary, RunLineageTimeline
from investment_research.pipeline.run_view_builders import (
    build_run_comparison_summary,
    build_run_dossier_summary,
    build_run_lineage_detail_summary,
    build_run_lineage_timeline,
    build_run_replay_summary,
    build_run_scope_summary,
)
from investment_research.pipeline.run_views import (
    RunDossierSummary,
    RunLineageDetailSummary,
    RunReplaySummary,
    RunScopeSummary,
    RunMarketObservation,
    RunDirectionalForecastStatus,
)
from investment_research.pipeline.service import AnalysisPipelineService
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import AnalysisProviderRegistry
from investment_research.service.directional_forecast import DirectionalForecastService
from investment_research.service.market_observation import MarketObservationService


class RunViewsService:
    """Read-only service for immutable analysis-run view contracts."""

    def __init__(self, uow: SQLiteUnitOfWork, *, provider_registry: AnalysisProviderRegistry | None = None) -> None:
        self.uow = uow
        self.provider_registry = provider_registry

    def get_run_replay_summary(self, run_id: str) -> RunReplaySummary:
        bundle = self._get_bundle_or_raise(run_id)
        return self._attach_run_observation(build_run_replay_summary(bundle), bundle)

    def get_run_replay_summary_for_user(self, run_id: str, *, user: User) -> RunReplaySummary:
        bundle = self._get_bundle_for_user_or_raise(run_id, user=user)
        return self._attach_run_observation(build_run_replay_summary(bundle), bundle)

    def get_run_comparison(self, run_id: str, *, baseline_run_id: str | None = None) -> RunComparisonSummary:
        current = self._get_bundle_or_raise(run_id)
        baseline = self._get_baseline_bundle(current=current, baseline_run_id=baseline_run_id)
        if baseline is None:
            raise ValueError("Baseline analysis run not found")
        return build_run_comparison_summary(current, baseline)

    def get_run_comparison_for_user(
        self,
        run_id: str,
        *,
        user: User,
        baseline_run_id: str | None = None,
    ) -> RunComparisonSummary:
        current = self._get_bundle_for_user_or_raise(run_id, user=user)
        baseline = self._get_baseline_bundle_for_user(
            current=current,
            user=user,
            baseline_run_id=baseline_run_id,
        )
        if baseline is None:
            raise ValueError("Baseline analysis run not found")
        return build_run_comparison_summary(current, baseline)

    def get_run_dossier_summary(self, run_id: str) -> RunDossierSummary:
        bundle = self._get_bundle_or_raise(run_id)
        return self._attach_run_observation(build_run_dossier_summary(bundle), bundle)

    def get_run_dossier_summary_for_user(self, run_id: str, *, user: User) -> RunDossierSummary:
        bundle = self._get_bundle_for_user_or_raise(run_id, user=user)
        return self._attach_run_observation(build_run_dossier_summary(bundle), bundle)

    def _attach_run_observation(self, summary, bundle: AnalysisBundle):
        observation = MarketObservationService(self.uow).get(str(bundle.asset.id))
        direction = DirectionalForecastService(self.uow).for_run(str(bundle.run.id))
        run_outcomes = [item for item in observation.outcomes if item.get("run_id") == str(bundle.run.id)]
        observation_payload = observation.model_dump()
        observation_payload["outcomes"] = run_outcomes
        return summary.model_copy(update={
            "market_observation": RunMarketObservation.model_validate(observation_payload),
            "directional_forecast_status": RunDirectionalForecastStatus(status=direction.status, gating_reasons=direction.gating_reasons),
        })

    def get_run_lineage_detail_summary(self, run_id: str) -> RunLineageDetailSummary:
        bundle = self._get_bundle_or_raise(run_id)
        return build_run_lineage_detail_summary(bundle)

    def get_run_lineage_detail_summary_for_user(self, run_id: str, *, user: User) -> RunLineageDetailSummary:
        bundle = self._get_bundle_for_user_or_raise(run_id, user=user)
        return build_run_lineage_detail_summary(bundle)

    def get_run_scope_summary(self, run_id: str) -> RunScopeSummary:
        run = self.uow.analysis_runs.get(run_id)
        if run is None:
            raise ValueError("Analysis run not found")
        return build_run_scope_summary(run)

    def get_run_scope_summary_for_user(self, run_id: str, *, user: User) -> RunScopeSummary:
        run = self.uow.analysis_runs.get(run_id)
        if run is None or not self._run_belongs_to_user(run, user):
            raise ValueError("Analysis run not found")
        return build_run_scope_summary(run)

    def get_run_lineage_timeline(self, asset_id: str) -> RunLineageTimeline:
        pipeline = self._pipeline()
        runs = self.uow.analysis_runs.list_for_asset(asset_id)
        audit_records = self._list_lineage_audit_records(runs)
        bundles: list[AnalysisBundle] = []
        for run in runs:
            bundle = pipeline.get_bundle(str(run.id))
            if bundle is None:
                continue
            bundles.append(bundle)
        return build_run_lineage_timeline(asset_id, bundles, audit_records)

    def get_run_lineage_timeline_for_user(self, asset_id: str, *, user: User) -> RunLineageTimeline:
        pipeline = self._pipeline()
        runs = [
            run
            for run in self.uow.analysis_runs.list_for_asset(asset_id)
            if self._run_belongs_to_user(run, user)
        ]
        audit_records = self._list_lineage_audit_records(runs)
        bundles: list[AnalysisBundle] = []
        for run in runs:
            bundle = pipeline.get_bundle(str(run.id))
            if bundle is None:
                continue
            bundles.append(bundle)
        return build_run_lineage_timeline(asset_id, bundles, audit_records)

    def _get_bundle_or_raise(self, run_id: str) -> AnalysisBundle:
        bundle = self._pipeline().get_bundle(run_id)
        if bundle is None:
            raise ValueError("Analysis run not found")
        return bundle

    def _get_bundle_for_user_or_raise(self, run_id: str, *, user: User) -> AnalysisBundle:
        bundle = self._pipeline().get_bundle(run_id)
        if bundle is None or not self._run_belongs_to_user(bundle.run, user):
            raise ValueError("Analysis run not found")
        return bundle

    def _pipeline(self) -> AnalysisPipelineService:
        return AnalysisPipelineService(self.uow, provider_registry=self.provider_registry)

    def _list_lineage_audit_records(self, runs) -> list[AuditRecord]:
        actors = {run.triggered_by for run in runs}
        return [record for actor in actors for record in self.uow.audit_records.list_for_actor(actor)]

    def _get_baseline_bundle(
        self,
        *,
        current: AnalysisBundle,
        baseline_run_id: str | None,
    ) -> AnalysisBundle | None:
        if baseline_run_id:
            return self._pipeline().get_bundle(baseline_run_id)

        runs = self.uow.analysis_runs.list_for_asset(str(current.asset.id))
        for index, run in enumerate(runs):
            if str(run.id) != str(current.run.id):
                continue
            previous = runs[index + 1] if index + 1 < len(runs) else None
            return None if previous is None else self._pipeline().get_bundle(str(previous.id))
        return None

    def _get_baseline_bundle_for_user(
        self,
        *,
        current: AnalysisBundle,
        user: User,
        baseline_run_id: str | None,
    ) -> AnalysisBundle | None:
        if baseline_run_id:
            baseline = self._pipeline().get_bundle(baseline_run_id)
            if baseline is None or not self._run_belongs_to_user(baseline.run, user):
                return None
            return baseline

        runs = [
            run
            for run in self.uow.analysis_runs.list_for_asset(str(current.asset.id))
            if self._run_belongs_to_user(run, user)
        ]
        for index, run in enumerate(runs):
            if str(run.id) != str(current.run.id):
                continue
            previous = runs[index + 1] if index + 1 < len(runs) else None
            return None if previous is None else self._pipeline().get_bundle(str(previous.id))
        return None

    def _run_belongs_to_user(self, run, user: User) -> bool:
        return run.triggered_by == user.auth_subject
