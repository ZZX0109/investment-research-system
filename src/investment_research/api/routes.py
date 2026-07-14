import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from investment_research.api.auth_routes import get_authenticated_user
from investment_research.config import AppEnvironment, get_app_settings
from investment_research.api.pipeline_schemas import GeneratedReportResponse
from investment_research.api.schemas import (
    AssetCreateRequest,
    EvidenceCreateRequest,
    PositionCreateRequest,
    PriceSeriesCreateRequest,
    ResearchReportCreateRequest,
    WatchlistCreateRequest,
    AssetRefreshRequest,
    ClaimCreateRequest,
    ClaimReviewRequest,
    ReportScheduleCreateRequest,
    ReportScheduleUpdateRequest,
    ResourceShareCreateRequest,
)
from investment_research.domain.catalog import DomainCatalog
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
    DocumentArtifact,
    HistoricalScenario,
    PortfolioRiskSnapshot,
    ReportSchedule,
    ResearchAudit,
)
from investment_research.domain.long_term_models import Claim, ResourceShare
from investment_research.pipeline.models import (
    AnalysisBundle,
    RunComparisonSummary,
    RunLineageTimeline,
)
from investment_research.pipeline.run_views import (
    AssetRefreshStatusSummary,
    RunDossierSummary,
    RunLineageDetailSummary,
    RunRefreshStatusSummary,
    RunReplaySummary,
    RunScopeSummary,
)
from investment_research.repository.sqlite import (
    SQLiteUnitOfWork,
    create_unit_of_work,
)
from investment_research.service.analysis_runs import AnalysisRunsService
from investment_research.service.analysis_intake import (
    AnalysisProviderRegistry,
    AnalysisProviderSettings,
    build_provider_registry,
)
from investment_research.service.catalog import DomainCatalogService
from investment_research.service.portfolio_research import PortfolioResearchService
from investment_research.service.run_views import RunViewsService
from investment_research.service.workbench import WorkbenchService
from investment_research.service.advanced_research import (
    AssetRefreshService,
    HistoricalAnalogyService,
    PortfolioRiskService,
    RefreshAnalysisResult,
    ResearchAuditService,
    ResearchCard,
    ResearchCardService,
)
from investment_research.service.documents import DocumentService
from investment_research.service.scheduling import ReportScheduleService
from investment_research.service.long_term_domain import LongTermDomainService
from investment_research.service.market_observation import MarketObservation, MarketObservationService
from investment_research.service.directional_forecast import DirectionalForecastResponse, DirectionalForecastService
from investment_research.domain.trusted_market import IngestionJob
from investment_research.service.ingestion_jobs import IngestionJobService
from investment_research.domain.forecasts import ResearchForecastBundle
from investment_research.service.research_forecasts import ResearchForecastService
from investment_research.service.research_review import ResearchReviewService, ResearchReviewSummary

router = APIRouter()


def get_analysis_provider_settings() -> AnalysisProviderSettings:
    return AnalysisProviderSettings()


def get_unit_of_work() -> Iterator[SQLiteUnitOfWork]:
    uow = create_unit_of_work()
    try:
        yield uow
    finally:
        uow.close()


def get_analysis_provider_registry(
    settings: AnalysisProviderSettings = Depends(get_analysis_provider_settings),
) -> AnalysisProviderRegistry:
    return build_provider_registry(settings)


def get_workbench_service(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    provider_registry: AnalysisProviderRegistry = Depends(
        get_analysis_provider_registry
    ),
) -> WorkbenchService:
    return WorkbenchService(uow, provider_registry=provider_registry)


def get_portfolio_research_service(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
) -> PortfolioResearchService:
    return PortfolioResearchService(uow)


def get_analysis_runs_service(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    provider_registry: AnalysisProviderRegistry = Depends(
        get_analysis_provider_registry
    ),
) -> AnalysisRunsService:
    return AnalysisRunsService(uow, provider_registry=provider_registry)


def get_run_views_service(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    provider_registry: AnalysisProviderRegistry = Depends(
        get_analysis_provider_registry
    ),
) -> RunViewsService:
    return RunViewsService(uow, provider_registry=provider_registry)


def get_catalog_service(
    settings: AnalysisProviderSettings = Depends(get_analysis_provider_settings),
) -> DomainCatalogService:
    return DomainCatalogService(provider_settings=settings)


def get_long_term_domain_service(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
) -> LongTermDomainService:
    return LongTermDomainService(uow)


@router.get("/api/v1/assets/{asset_id}/claims", response_model=list[Claim])
def list_claims(
    asset_id: str,
    domain: LongTermDomainService = Depends(get_long_term_domain_service),
    user: User = Depends(get_authenticated_user),
) -> list[Claim]:
    try:
        return domain.list_claims(asset_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc


@router.post("/api/v1/claims", response_model=Claim, status_code=201)
def create_claim(
    payload: ClaimCreateRequest,
    domain: LongTermDomainService = Depends(get_long_term_domain_service),
    user: User = Depends(get_authenticated_user),
) -> Claim:
    try:
        return domain.submit_claim(payload, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc


@router.patch("/api/v1/claims/{claim_id}/review", response_model=Claim)
def review_claim(
    claim_id: str,
    payload: ClaimReviewRequest,
    domain: LongTermDomainService = Depends(get_long_term_domain_service),
    user: User = Depends(get_authenticated_user),
) -> Claim:
    try:
        return domain.review_claim(claim_id, status=payload.status, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc


@router.get("/api/v1/resources/{resource_type}/{resource_id}/shares", response_model=list[ResourceShare])
def list_resource_shares(
    resource_type: str,
    resource_id: str,
    domain: LongTermDomainService = Depends(get_long_term_domain_service),
    user: User = Depends(get_authenticated_user),
) -> list[ResourceShare]:
    try:
        return domain.list_shares(resource_type=resource_type, resource_id=resource_id, owner=user)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc


@router.post("/api/v1/resources/{resource_type}/{resource_id}/shares", response_model=ResourceShare, status_code=201)
def create_resource_share(
    resource_type: str,
    resource_id: str,
    payload: ResourceShareCreateRequest,
    domain: LongTermDomainService = Depends(get_long_term_domain_service),
    user: User = Depends(get_authenticated_user),
) -> ResourceShare:
    try:
        return domain.create_share(resource_type=resource_type, resource_id=resource_id, payload=payload, owner=user)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc


@router.delete("/api/v1/resources/{resource_type}/{resource_id}/shares/{viewer_user_id}", status_code=204)
def revoke_resource_share(
    resource_type: str,
    resource_id: str,
    viewer_user_id: str,
    domain: LongTermDomainService = Depends(get_long_term_domain_service),
    user: User = Depends(get_authenticated_user),
):
    try:
        domain.revoke_share(resource_type=resource_type, resource_id=resource_id, viewer_user_id=viewer_user_id, owner=user)
    except ValueError as exc:
        raise HTTPException(status_code=_http_status_for_value_error(exc), detail=str(exc)) from exc


@router.post("/api/v1/assets/{asset_id}/refresh", response_model=RefreshAnalysisResult)
def refresh_asset(
    asset_id: str,
    payload: AssetRefreshRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> RefreshAnalysisResult:
    result = AssetRefreshService(uow).refresh_and_analyze(
        asset_id, user=user, refresh_mode=payload.refresh_mode
    )
    if result.refresh_run.state == "failed":
        raise HTTPException(
            status_code=503, detail=result.refresh_run.model_dump(mode="json")
        )
    return result


@router.get("/api/v1/ingestion-jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(
    job_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> IngestionJob:
    try:
        return IngestionJobService(uow).get(job_id, requested_by=user.auth_subject)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/ingestion-jobs/{job_id}/cancel", response_model=IngestionJob)
def cancel_ingestion_job(
    job_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> IngestionJob:
    try:
        return IngestionJobService(uow).cancel(job_id, requested_by=user.auth_subject)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/assets/{asset_id}/market-observation", response_model=MarketObservation)
def market_observation(asset_id: str, uow: SQLiteUnitOfWork = Depends(get_unit_of_work), user: User = Depends(get_authenticated_user)) -> MarketObservation:
    del user
    try:
        return MarketObservationService(uow).get(asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/assets/{asset_id}/market-observation/refresh", response_model=MarketObservation)
def refresh_market_observation(asset_id: str, uow: SQLiteUnitOfWork = Depends(get_unit_of_work), user: User = Depends(get_authenticated_user)) -> MarketObservation:
    try:
        return MarketObservationService(uow).refresh(asset_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/analysis-runs/{run_id}/directional-forecast", response_model=DirectionalForecastResponse)
def directional_forecast(run_id: str, uow: SQLiteUnitOfWork = Depends(get_unit_of_work), user: User = Depends(get_authenticated_user)) -> DirectionalForecastResponse:
    del user
    if uow.analysis_runs.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return DirectionalForecastService(uow).for_run(run_id)


@router.get("/api/v1/analysis-runs/{run_id}/research-forecast", response_model=ResearchForecastBundle)
def research_forecast(
    run_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ResearchForecastBundle:
    run = uow.analysis_runs.get(run_id)
    if run is None or run.triggered_by != user.auth_subject:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    try:
        return ResearchForecastService(uow).for_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/research-reviews", response_model=ResearchReviewSummary)
def research_reviews(
    group_by: Literal["month", "model", "industry", "symbol", "market_state"] = Query(default="month"),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ResearchReviewSummary:
    return ResearchReviewService(uow).summarize(user=user, group_by=group_by)


@router.get(
    "/api/v1/assets/{asset_id}/historical-analogies",
    response_model=list[HistoricalScenario],
)
def historical_analogies(
    asset_id: str,
    as_of: datetime | None = Query(default=None),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[HistoricalScenario]:
    del user
    try:
        return HistoricalAnalogyService(uow).find(asset_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/portfolio/me/risk", response_model=PortfolioRiskSnapshot)
def portfolio_risk(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> PortfolioRiskSnapshot:
    return PortfolioRiskService(uow).calculate(user=user)


@router.get("/api/v1/assets/{asset_id}/research-card", response_model=ResearchCard)
def research_card(
    asset_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ResearchCard:
    try:
        return ResearchCardService(uow).get(asset_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.post("/api/v1/analysis-runs/{run_id}/audit", response_model=ResearchAudit)
def create_research_audit(
    run_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ResearchAudit:
    try:
        return ResearchAuditService(uow).audit(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/analysis-runs/{run_id}/audit", response_model=ResearchAudit)
def get_research_audit(
    run_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ResearchAudit:
    item = uow.research_audits.get_for_run(run_id)
    run = uow.analysis_runs.get(run_id)
    if item is None or run is None or run.triggered_by != user.auth_subject:
        raise HTTPException(status_code=404, detail="Research audit not found")
    return item


@router.get("/api/v1/report-schedules", response_model=list[ReportSchedule])
def list_report_schedules(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[ReportSchedule]:
    return ReportScheduleService(uow).list(user=user)


@router.post("/api/v1/report-schedules", response_model=ReportSchedule, status_code=201)
def create_report_schedule(
    payload: ReportScheduleCreateRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ReportSchedule:
    try:
        return ReportScheduleService(uow).create(
            user=user,
            frequency=payload.frequency,
            asset_id=payload.asset_id,
            enabled=payload.enabled,
            timezone_name=payload.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/v1/report-schedules/{schedule_id}", response_model=ReportSchedule)
def update_report_schedule(
    schedule_id: str,
    payload: ReportScheduleUpdateRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ReportSchedule:
    try:
        return ReportScheduleService(uow).update(
            schedule_id, user=user, frequency=payload.frequency, enabled=payload.enabled
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.delete("/api/v1/report-schedules/{schedule_id}", status_code=204)
def delete_report_schedule(
    schedule_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
):
    try:
        ReportScheduleService(uow).delete(schedule_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.post("/api/v1/documents", response_model=DocumentArtifact, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    asset_id: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> DocumentArtifact:
    data = await file.read()
    try:
        return DocumentService(uow).create(
            user=user,
            filename=file.filename or "document.pdf",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            asset_id=asset_id,
            source_url=source_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/documents/{document_id}", response_model=DocumentArtifact)
def get_document(
    document_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> DocumentArtifact:
    item = DocumentService(uow).get_for_user(document_id, user=user)
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return item


@router.get("/api/v1/models/deployment-status")
def model_deployment_status(user: User = Depends(get_authenticated_user)) -> dict:
    del user
    root = Path(__file__).resolve().parents[3] / "output" / "models"
    artifact_root = root.parent
    manifest = root / "model_manifest.json"
    features = root / "feature_order.json"
    if not manifest.exists():
        raise HTTPException(status_code=503, detail="Model manifest unavailable")
    return {
        "manifest": json.loads(manifest.read_text()),
        "feature_contract": json.loads(features.read_text())
        if features.exists()
        else {},
        "trusted_risk_gate": (
            json.loads((artifact_root / "trusted_risk_gate_model_card.json").read_text())
            if (artifact_root / "trusted_risk_gate_model_card.json").exists()
            else {}
        ),
        "public_experiment": (
            json.loads((artifact_root / "public_experiment_manifest.json").read_text())
            if (artifact_root / "public_experiment_manifest.json").exists()
            else {}
        ),
    }


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


def _http_status_for_value_error(exc: ValueError) -> int:
    return 404 if "not found" in str(exc).lower() else 400


@router.get("/api/v1/domain/catalog", response_model=DomainCatalog)
def get_domain_catalog(
    catalog: DomainCatalogService = Depends(get_catalog_service),
) -> DomainCatalog:
    return catalog.describe_domain()


@router.get("/api/v1/analysis-runs/demo", response_model=AnalysisRun)
def get_demo_analysis_run(
    catalog: DomainCatalogService = Depends(get_catalog_service),
) -> AnalysisRun:
    return catalog.build_demo_analysis_run()


@router.get("/api/v1/assets", response_model=list[Asset])
def list_assets(
    source_type: str | None = Query(default=None),
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[Asset]:
    return portfolio.list_assets_for_user(user=user, source_type=source_type)


@router.get("/api/v1/assets/{asset_id}/price-series", response_model=list[PriceSeries])
def list_price_series_for_asset(
    asset_id: str,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[PriceSeries]:
    return portfolio.list_price_series_for_asset_for_user(asset_id, user=user)


@router.post(
    "/api/v1/assets/{asset_id}/price-series",
    response_model=PriceSeries,
    status_code=201,
)
def create_price_series_for_asset(
    asset_id: str,
    payload: PriceSeriesCreateRequest,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> PriceSeries:
    try:
        return portfolio.create_price_series(
            payload.model_copy(update={"asset_id": asset_id}), user=user
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/assets/{asset_id}/evidence", response_model=list[Evidence])
def list_evidence_for_asset(
    asset_id: str,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[Evidence]:
    return portfolio.list_evidence_for_asset_for_user(asset_id, user=user)


@router.post(
    "/api/v1/assets/{asset_id}/evidence", response_model=Evidence, status_code=201
)
def create_evidence_for_asset(
    asset_id: str,
    payload: EvidenceCreateRequest,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> Evidence:
    try:
        return portfolio.create_evidence(
            payload.model_copy(update={"asset_id": asset_id}), user=user
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/assets/{asset_id}/reports", response_model=list[ResearchReport])
def list_reports_for_asset(
    asset_id: str,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[ResearchReport]:
    return portfolio.list_reports_for_asset_for_user(asset_id, user=user)


@router.post(
    "/api/v1/assets/{asset_id}/reports", response_model=ResearchReport, status_code=201
)
def create_report_for_asset(
    asset_id: str,
    payload: ResearchReportCreateRequest,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> ResearchReport:
    try:
        return portfolio.create_research_report(
            payload.model_copy(update={"asset_id": asset_id}), user=user
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.post("/api/v1/assets", response_model=Asset, status_code=201)
def create_asset(
    payload: AssetCreateRequest,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> Asset:
    try:
        return portfolio.create_asset_for_user(payload, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/positions/me", response_model=list[Position])
def list_positions_for_current_user(
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[Position]:
    return portfolio.list_positions_for_user(user=user)


@router.get("/api/v1/watchlists/me", response_model=list[Watchlist])
def list_watchlists_for_current_user(
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[Watchlist]:
    return portfolio.list_watchlists_for_user(user=user)


@router.post("/api/v1/watchlists", response_model=Watchlist, status_code=201)
def create_watchlist(
    payload: WatchlistCreateRequest,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> Watchlist:
    try:
        return portfolio.create_watchlist_for_user(payload, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.post("/api/v1/positions", response_model=Position, status_code=201)
def create_position(
    payload: PositionCreateRequest,
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> Position:
    try:
        return portfolio.create_position_for_user(payload, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/audit-records/me", response_model=list[AuditRecord])
def list_my_audit_records(
    portfolio: PortfolioResearchService = Depends(get_portfolio_research_service),
    user: User = Depends(get_authenticated_user),
) -> list[AuditRecord]:
    return portfolio.list_audit_records_for_user(user=user)


@router.post(
    "/api/v1/analysis-runs/demo/persist", response_model=AnalysisRun, status_code=201
)
def persist_demo_analysis_run(
    analysis_runs: AnalysisRunsService = Depends(get_analysis_runs_service),
    user: User = Depends(get_authenticated_user),
) -> AnalysisRun:
    return analysis_runs.persist_demo_analysis_run_for_user(user=user)


@router.post(
    "/api/v1/assets/{asset_id}/analysis-runs",
    response_model=AnalysisBundle,
    status_code=201,
)
def trigger_analysis_for_asset(
    asset_id: str,
    decision_context: Literal["close_confirmed", "pre_open"] | None = Query(default=None),
    analysis_runs: AnalysisRunsService = Depends(get_analysis_runs_service),
    user: User = Depends(get_authenticated_user),
) -> AnalysisBundle:
    if decision_context is None and get_app_settings().environment == AppEnvironment.PRODUCTION:
        raise HTTPException(status_code=422, detail="decision_context is required in production")
    resolved_context = decision_context or "close_confirmed"
    try:
        return analysis_runs.trigger_analysis_for_asset(
            asset_id, user=user, decision_context=resolved_context
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/analysis-runs/{run_id}", response_model=AnalysisRun)
def get_analysis_run(
    run_id: str,
    analysis_runs: AnalysisRunsService = Depends(get_analysis_runs_service),
    user: User = Depends(get_authenticated_user),
) -> AnalysisRun:
    run = analysis_runs.get_analysis_run_for_user(run_id, user=user)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


@router.get("/api/v1/assets/{asset_id}/analysis-runs", response_model=list[AnalysisRun])
def list_analysis_runs_for_asset(
    asset_id: str,
    analysis_runs: AnalysisRunsService = Depends(get_analysis_runs_service),
    user: User = Depends(get_authenticated_user),
) -> list[AnalysisRun]:
    return analysis_runs.list_analysis_runs_for_asset_for_user(asset_id, user=user)


@router.get("/api/v1/assets/{asset_id}/lineage", response_model=RunLineageTimeline)
def get_run_lineage_timeline(
    asset_id: str,
    run_views: RunViewsService = Depends(get_run_views_service),
    user: User = Depends(get_authenticated_user),
) -> RunLineageTimeline:
    return run_views.get_run_lineage_timeline_for_user(asset_id, user=user)


@router.get(
    "/api/v1/assets/{asset_id}/refresh-status", response_model=AssetRefreshStatusSummary
)
def get_asset_refresh_status(
    asset_id: str,
    workbench: WorkbenchService = Depends(get_workbench_service),
    user: User = Depends(get_authenticated_user),
) -> AssetRefreshStatusSummary:
    return workbench.get_asset_refresh_status(asset_id, user=user)


@router.get("/api/v1/analysis-runs/{run_id}/bundle", response_model=AnalysisBundle)
def get_analysis_bundle(
    run_id: str,
    analysis_runs: AnalysisRunsService = Depends(get_analysis_runs_service),
    user: User = Depends(get_authenticated_user),
) -> AnalysisBundle:
    bundle = analysis_runs.get_analysis_bundle_for_user(run_id, user=user)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Analysis bundle not found")
    return bundle


@router.get(
    "/api/v1/analysis-runs/{run_id}/comparison", response_model=RunComparisonSummary
)
def get_run_comparison(
    run_id: str,
    baseline_run_id: str | None = Query(default=None),
    run_views: RunViewsService = Depends(get_run_views_service),
    user: User = Depends(get_authenticated_user),
) -> RunComparisonSummary:
    try:
        return run_views.get_run_comparison_for_user(
            run_id, user=user, baseline_run_id=baseline_run_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get(
    "/api/v1/analysis-runs/{run_id}/replay-summary", response_model=RunReplaySummary
)
def get_run_replay_summary(
    run_id: str,
    run_views: RunViewsService = Depends(get_run_views_service),
    user: User = Depends(get_authenticated_user),
) -> RunReplaySummary:
    try:
        return run_views.get_run_replay_summary_for_user(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/analysis-runs/{run_id}/dossier", response_model=RunDossierSummary)
def get_run_dossier_summary(
    run_id: str,
    run_views: RunViewsService = Depends(get_run_views_service),
    user: User = Depends(get_authenticated_user),
) -> RunDossierSummary:
    try:
        return run_views.get_run_dossier_summary_for_user(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get(
    "/api/v1/analysis-runs/{run_id}/lineage-detail",
    response_model=RunLineageDetailSummary,
)
def get_run_lineage_detail_summary(
    run_id: str,
    run_views: RunViewsService = Depends(get_run_views_service),
    user: User = Depends(get_authenticated_user),
) -> RunLineageDetailSummary:
    try:
        return run_views.get_run_lineage_detail_summary_for_user(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get("/api/v1/analysis-runs/{run_id}/scope", response_model=RunScopeSummary)
def get_run_scope_summary(
    run_id: str,
    run_views: RunViewsService = Depends(get_run_views_service),
    user: User = Depends(get_authenticated_user),
) -> RunScopeSummary:
    try:
        return run_views.get_run_scope_summary_for_user(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.get(
    "/api/v1/analysis-runs/{run_id}/refresh-status",
    response_model=RunRefreshStatusSummary,
)
def get_run_refresh_status(
    run_id: str,
    workbench: WorkbenchService = Depends(get_workbench_service),
    user: User = Depends(get_authenticated_user),
) -> RunRefreshStatusSummary:
    try:
        return workbench.get_run_refresh_status(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc


@router.post(
    "/api/v1/analysis-runs/{run_id}/report",
    response_model=GeneratedReportResponse,
    status_code=201,
)
def generate_report_for_run(
    run_id: str,
    analysis_runs: AnalysisRunsService = Depends(get_analysis_runs_service),
    user: User = Depends(get_authenticated_user),
) -> GeneratedReportResponse:
    try:
        bundle = analysis_runs.generate_report_for_run(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=_http_status_for_value_error(exc), detail=str(exc)
        ) from exc
    return GeneratedReportResponse(report=bundle.reports[-1], bundle=bundle)
