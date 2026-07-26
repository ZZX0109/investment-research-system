from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from investment_research.config import get_app_settings
from investment_research.repository.postgres_compat import PostgresConnection
from investment_research.repository.sqlite_auth import SQLiteRefreshSessionRepository, SQLiteUserRepository
from investment_research.repository.sqlite_base import named_tuple_row_factory
from investment_research.repository.sqlite_pipeline import (
    SQLiteAnalysisSnapshotRepository,
    SQLiteJudgeScoreRepository,
    SQLiteModelPredictionRepository,
    SQLiteRecommendationRepository,
    SQLiteRiskConclusionRepository,
)
from investment_research.repository.sqlite_research import (
    SQLiteAnalysisRunRepository,
    SQLiteAssetRepository,
    SQLiteAuditRecordRepository,
    SQLiteEvidenceRepository,
    SQLitePositionRepository,
    SQLitePriceSeriesRepository,
    SQLiteResearchReportRepository,
    SQLiteWatchlistRepository,
)
from investment_research.repository.sqlite_advanced import (
    SQLiteDocumentArtifactRepository,
    SQLiteHistoricalScenarioRepository,
    SQLitePaperObservationRepository,
    SQLitePortfolioRiskRepository,
    SQLiteRefreshRunRepository,
    SQLiteReportScheduleRepository,
    SQLiteResearchAuditRepository,
)
from investment_research.repository.relational_domain import RelationalDomainRepository
from investment_research.repository.agent_runtime import AgentRuntimeRepository
from investment_research.service.document_evaluation import DocumentEvaluationRepository
from investment_research.repository.market_observation import MarketObservationRepository
from investment_research.repository.trusted_market import IngestionJobRepository, TrustedMarketRepository
from investment_research.repository.forecasts import ResearchForecastRepository
from investment_research.repository.pit_catalog import PITCatalogRepository
from investment_research.repository.shadow_runs import ShadowRunOutcomeRepository, ShadowRunRepository
from investment_research.repository.knowledge import FinancialKnowledgeRepository

_MIGRATED_DATABASES: set[str] = set()


def get_default_database_path() -> Path:
    return get_app_settings().database_path


def get_database_url() -> str:
    return get_app_settings().database_url


class SQLiteMigrator:
    def __init__(self, database_path: Path, alembic_ini_path: Path | None = None) -> None:
        self.database_path = database_path
        self.alembic_ini_path = alembic_ini_path or Path(__file__).resolve().parents[3] / "alembic.ini"

    def apply(self) -> None:
        cache_key = str(self.database_path.resolve())
        if cache_key in _MIGRATED_DATABASES:
            return
        config = Config(str(self.alembic_ini_path))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.database_path}")
        command.upgrade(config, "head")
        _MIGRATED_DATABASES.add(cache_key)


class PostgresMigrator:
    def __init__(self, database_url: str, alembic_ini_path: Path | None = None) -> None:
        self.database_url = database_url
        self.alembic_ini_path = alembic_ini_path or Path(__file__).resolve().parents[3] / "alembic.ini"

    def apply(self) -> None:
        cache_key = self.database_url
        if cache_key in _MIGRATED_DATABASES:
            return
        config = Config(str(self.alembic_ini_path))
        config.set_main_option("sqlalchemy.url", self.database_url)
        command.upgrade(config, "head")
        _MIGRATED_DATABASES.add(cache_key)


class SQLiteUnitOfWork:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        SQLiteMigrator(self.database_path).apply()
        self.connection = sqlite3.connect(
            database_path,
            timeout=30.0,
            check_same_thread=False,
        )
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.row_factory = named_tuple_row_factory
        self.assets = SQLiteAssetRepository(self.connection)
        self.evidence = SQLiteEvidenceRepository(self.connection)
        self.analysis_runs = SQLiteAnalysisRunRepository(self.connection)
        self.positions = SQLitePositionRepository(self.connection)
        self.watchlists = SQLiteWatchlistRepository(self.connection)
        self.price_series = SQLitePriceSeriesRepository(self.connection)
        self.audit_records = SQLiteAuditRecordRepository(self.connection)
        self.reports = SQLiteResearchReportRepository(self.connection)
        self.snapshots = SQLiteAnalysisSnapshotRepository(self.connection)
        self.predictions = SQLiteModelPredictionRepository(self.connection)
        self.risks = SQLiteRiskConclusionRepository(self.connection)
        self.recommendations = SQLiteRecommendationRepository(self.connection)
        self.judge_scores = SQLiteJudgeScoreRepository(self.connection)
        self.users = SQLiteUserRepository(self.connection)
        self.refresh_sessions = SQLiteRefreshSessionRepository(self.connection)
        self.refresh_runs = SQLiteRefreshRunRepository(self.connection)
        self.historical_scenarios = SQLiteHistoricalScenarioRepository(self.connection)
        self.portfolio_risks = SQLitePortfolioRiskRepository(self.connection)
        self.report_schedules = SQLiteReportScheduleRepository(self.connection)
        self.document_artifacts = SQLiteDocumentArtifactRepository(self.connection)
        self.research_audits = SQLiteResearchAuditRepository(self.connection)
        self.paper_observations = SQLitePaperObservationRepository(self.connection)
        self.domain = RelationalDomainRepository(self.connection)
        self.agent_runtime = AgentRuntimeRepository(self.connection)
        self.document_evaluations = DocumentEvaluationRepository(self.connection)
        self.market_observations = MarketObservationRepository(self.connection)
        self.trusted_market = TrustedMarketRepository(self.connection)
        self.ingestion_jobs = IngestionJobRepository(self.connection)
        self.research_forecasts = ResearchForecastRepository(self.connection)
        self.pit_catalog = PITCatalogRepository(self.connection)
        self.shadow_runs = ShadowRunRepository(self.connection)
        self.shadow_outcomes = ShadowRunOutcomeRepository(self.connection)
        self.financial_knowledge = FinancialKnowledgeRepository(self.connection)

    def close(self) -> None:
        self.connection.close()


class PostgresUnitOfWork(SQLiteUnitOfWork):
    """PostgreSQL runtime using the existing repository contract during cutover."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        PostgresMigrator(database_url).apply()
        self.connection = PostgresConnection(database_url)
        self.assets = SQLiteAssetRepository(self.connection)
        self.evidence = SQLiteEvidenceRepository(self.connection)
        self.analysis_runs = SQLiteAnalysisRunRepository(self.connection)
        self.positions = SQLitePositionRepository(self.connection)
        self.watchlists = SQLiteWatchlistRepository(self.connection)
        self.price_series = SQLitePriceSeriesRepository(self.connection)
        self.audit_records = SQLiteAuditRecordRepository(self.connection)
        self.reports = SQLiteResearchReportRepository(self.connection)
        self.snapshots = SQLiteAnalysisSnapshotRepository(self.connection)
        self.predictions = SQLiteModelPredictionRepository(self.connection)
        self.risks = SQLiteRiskConclusionRepository(self.connection)
        self.recommendations = SQLiteRecommendationRepository(self.connection)
        self.judge_scores = SQLiteJudgeScoreRepository(self.connection)
        self.users = SQLiteUserRepository(self.connection)
        self.refresh_sessions = SQLiteRefreshSessionRepository(self.connection)
        self.refresh_runs = SQLiteRefreshRunRepository(self.connection)
        self.historical_scenarios = SQLiteHistoricalScenarioRepository(self.connection)
        self.portfolio_risks = SQLitePortfolioRiskRepository(self.connection)
        self.report_schedules = SQLiteReportScheduleRepository(self.connection)
        self.document_artifacts = SQLiteDocumentArtifactRepository(self.connection)
        self.research_audits = SQLiteResearchAuditRepository(self.connection)
        self.paper_observations = SQLitePaperObservationRepository(self.connection)
        self.domain = RelationalDomainRepository(self.connection)
        self.agent_runtime = AgentRuntimeRepository(self.connection)
        self.document_evaluations = DocumentEvaluationRepository(self.connection)
        self.market_observations = MarketObservationRepository(self.connection)
        self.trusted_market = TrustedMarketRepository(self.connection)
        self.ingestion_jobs = IngestionJobRepository(self.connection)
        self.research_forecasts = ResearchForecastRepository(self.connection)
        self.pit_catalog = PITCatalogRepository(self.connection)
        self.shadow_runs = ShadowRunRepository(self.connection)
        self.shadow_outcomes = ShadowRunOutcomeRepository(self.connection)
        self.financial_knowledge = FinancialKnowledgeRepository(self.connection)


def create_unit_of_work() -> SQLiteUnitOfWork:
    url = get_database_url()
    if url.startswith(("postgresql://", "postgresql+psycopg://")):
        return PostgresUnitOfWork(url)
    return SQLiteUnitOfWork(get_default_database_path())
