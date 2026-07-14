from __future__ import annotations

from typing import Protocol

from investment_research.auth.models import AuthenticatedUser, RefreshSession
from investment_research.domain.models import (
    AnalysisRun,
    Asset,
    AuditRecord,
    Evidence,
    InvestmentRecommendation,
    JudgeScore,
    ModelPrediction,
    Position,
    PriceSeries,
    ResearchReport,
    RiskConclusion,
    Watchlist,
)


class AssetRepository(Protocol):
    def add(self, asset: Asset) -> Asset:
        ...

    def list(self, *, source_type: str | None = None) -> list[Asset]:
        ...

    def get(self, asset_id: str) -> Asset | None:
        ...


class EvidenceRepository(Protocol):
    def add(self, evidence: Evidence) -> Evidence:
        ...

    def list_for_asset(self, asset_id: str) -> list[Evidence]:
        ...


class AnalysisRunRepository(Protocol):
    def add(self, run: AnalysisRun) -> AnalysisRun:
        ...

    def get(self, run_id: str) -> AnalysisRun | None:
        ...

    def list_for_asset(self, asset_id: str) -> list[AnalysisRun]:
        ...


class PositionRepository(Protocol):
    def add(self, position: Position) -> Position:
        ...

    def list_for_user(self, user_id: str) -> list[Position]:
        ...


class WatchlistRepository(Protocol):
    def add(self, watchlist: Watchlist) -> Watchlist:
        ...

    def list_for_user(self, user_id: str) -> list[Watchlist]:
        ...


class PriceSeriesRepository(Protocol):
    def add(self, series: PriceSeries) -> PriceSeries:
        ...

    def list_for_asset(self, asset_id: str) -> list[PriceSeries]:
        ...


class AuditRecordRepository(Protocol):
    def add(self, record: AuditRecord) -> AuditRecord:
        ...

    def list_for_actor(self, actor: str) -> list[AuditRecord]:
        ...


class ResearchReportRepository(Protocol):
    def add(self, report: ResearchReport) -> ResearchReport:
        ...

    def list_for_asset(self, asset_id: str) -> list[ResearchReport]:
        ...

    def list_for_run(self, run_id: str) -> list[ResearchReport]:
        ...


class ModelPredictionRepository(Protocol):
    def add(self, prediction: ModelPrediction) -> ModelPrediction:
        ...

    def list_for_run(self, run_id: str) -> list[ModelPrediction]:
        ...


class RiskConclusionRepository(Protocol):
    def add(self, conclusion: RiskConclusion) -> RiskConclusion:
        ...

    def list_for_run(self, run_id: str) -> list[RiskConclusion]:
        ...


class RecommendationRepository(Protocol):
    def add(self, recommendation: InvestmentRecommendation) -> InvestmentRecommendation:
        ...

    def list_for_run(self, run_id: str) -> list[InvestmentRecommendation]:
        ...


class JudgeScoreRepository(Protocol):
    def add(self, judge_score: JudgeScore) -> JudgeScore:
        ...

    def list_for_run(self, run_id: str) -> list[JudgeScore]:
        ...


class UserRepository(Protocol):
    def add(self, user, *, password_hash: str) -> None:
        ...

    def get_by_email(self, email: str) -> AuthenticatedUser | None:
        ...

    def get_by_id(self, user_id: str) -> AuthenticatedUser | None:
        ...


class RefreshSessionRepository(Protocol):
    def add(self, session: RefreshSession) -> None:
        ...

    def get_active(self, token_id: str) -> RefreshSession | None:
        ...

    def revoke(self, token_id: str, *, revoked_at) -> None:
        ...
