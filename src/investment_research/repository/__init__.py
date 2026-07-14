"""Persistence adapters live here."""

from investment_research.repository.contracts import (
    AnalysisRunRepository,
    AuditRecordRepository,
    AssetRepository,
    EvidenceRepository,
    JudgeScoreRepository,
    ModelPredictionRepository,
    PositionRepository,
    PriceSeriesRepository,
    RecommendationRepository,
    RefreshSessionRepository,
    ResearchReportRepository,
    RiskConclusionRepository,
    UserRepository,
    WatchlistRepository,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork

__all__ = [
    "AnalysisRunRepository",
    "AuditRecordRepository",
    "AssetRepository",
    "EvidenceRepository",
    "JudgeScoreRepository",
    "ModelPredictionRepository",
    "PositionRepository",
    "PriceSeriesRepository",
    "RecommendationRepository",
    "RefreshSessionRepository",
    "ResearchReportRepository",
    "RiskConclusionRepository",
    "SQLiteUnitOfWork",
    "UserRepository",
    "WatchlistRepository",
]
