from __future__ import annotations

from investment_research.domain.models import ResearchReport
from investment_research.pipeline.models import AnalysisBundle
from investment_research.pipeline.replay_guard import FixedRunReplayGuard
from investment_research.report.factory import DEFAULT_REPORT_VERSION, ReportBuildOptions, ResearchReportFactory
from investment_research.repository.sqlite import SQLiteUnitOfWork


class ReportService:
    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        report_factory: ResearchReportFactory | None = None,
        replay_guard: FixedRunReplayGuard | None = None,
    ) -> None:
        self.uow = uow
        self.report_factory = report_factory or ResearchReportFactory()
        self.replay_guard = replay_guard or FixedRunReplayGuard()

    def create_report_from_bundle(
        self,
        bundle: AnalysisBundle,
        *,
        report_version: str = DEFAULT_REPORT_VERSION,
    ) -> ResearchReport:
        self.replay_guard.validate_report_bundle(bundle)
        report = self.report_factory.build_report(
            bundle,
            options=ReportBuildOptions(report_version=report_version),
        )
        stored = self.uow.reports.add(report)
        updated_run = bundle.run.model_copy(
            update={
                "report_ids": [*bundle.run.report_ids, stored.id],
                "report_version": stored.report_version,
            }
        )
        self.uow.analysis_runs.add(updated_run)
        return stored
