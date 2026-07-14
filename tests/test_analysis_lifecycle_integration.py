from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from investment_research.api.auth_routes import get_auth_service, get_auth_settings
from investment_research.api.routes import (
    get_analysis_provider_registry,
    get_analysis_provider_settings,
    get_unit_of_work,
)
from investment_research.auth.security import AuthSettings
from investment_research.auth.service import AuthService
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.main import app
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import AnalysisProviderSettings, build_provider_registry


def _attach_csrf_header(client: TestClient, settings: AuthSettings) -> None:
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert csrf_token is not None
    client.headers[settings.csrf_header_name] = csrf_token


def configure_authenticated_client(tmp_path, filename: str) -> TestClient:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    provider_settings = AnalysisProviderSettings()

    def override_settings() -> AuthSettings:
        return settings

    def override_provider_settings() -> AnalysisProviderSettings:
        return provider_settings

    def override_uow() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(tmp_path / filename)

    def override_provider_registry():
        return build_provider_registry(provider_settings)

    def override_auth_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / filename), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_analysis_provider_settings] = override_provider_settings
    app.dependency_overrides[get_analysis_provider_registry] = override_provider_registry
    app.dependency_overrides[get_auth_service] = override_auth_service
    app.dependency_overrides[get_unit_of_work] = override_uow
    client = TestClient(app)
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "investor@example.com",
            "display_name": "Investor",
            "password": "supersecret123",
        },
    )
    assert register_response.status_code == 201
    _attach_csrf_header(client, settings)
    return client


def test_analysis_lifecycle_flows_from_asset_inputs_into_report(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "analysis-lifecycle.db")
    now = datetime.now(timezone.utc)

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "ibm",
            "name": "IBM",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": now.isoformat(),
            "confidence": 0.95,
        },
    )
    asset_id = asset_response.json()["id"]

    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "historical-cache",
            "observed_at": (now - timedelta(days=8)).isoformat(),
            "confidence": 0.84,
            "points": [
                {
                    "timestamp": (now - timedelta(days=8)).isoformat(),
                    "open": 199.0,
                    "high": 201.0,
                    "low": 197.5,
                    "close": 200.4,
                    "volume": 810000,
                }
            ],
        },
    )
    evidence_response = client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
                "asset_id": asset_id,
                "evidence_type": "research_note",
                "title": "Legacy demand check",
                "summary": "Operator note still exists, but it is stale and should force a refresh recommendation.",
                "collected_at": (now - timedelta(days=8)).isoformat(),
                "data_mode": DataMode.REAL.value,
                "source_type": DataSourceType.MANUAL_OVERRIDE.value,
                "source_name": "research-desk",
            "confidence": 0.8,
        },
    )
    evidence_id = evidence_response.json()["id"]

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    report_response = client.post(f"/api/v1/analysis-runs/{run_id}/report")
    dossier_response = client.get(f"/api/v1/analysis-runs/{run_id}/dossier")
    lineage_response = client.get(f"/api/v1/analysis-runs/{run_id}/lineage-detail")
    run_refresh_response = client.get(f"/api/v1/analysis-runs/{run_id}/refresh-status")
    asset_refresh_response = client.get(f"/api/v1/assets/{asset_id}/refresh-status")

    snapshot = analysis_response.json()["snapshot"]
    judge = analysis_response.json()["judge_scores"][0]
    report_body = report_response.json()["report"]["body_markdown"]
    dossier = dossier_response.json()
    lineage = lineage_response.json()
    run_refresh = run_refresh_response.json()
    asset_refresh = asset_refresh_response.json()

    assert analysis_response.status_code == 201
    assert report_response.status_code == 201
    assert snapshot["price_freshness_status"] == "stale"
    assert snapshot["evidence_freshness_status"] == "stale"
    assert snapshot["refresh_recommendation"] == "refresh_recommended_before_action"
    assert len(snapshot["stale_reasons"]) >= 2
    assert evidence_id in snapshot["evidence_citation_ids"]
    assert judge["verdict"] == "block"
    assert "Prediction model is not approved for deployment" in judge["gating_reasons"]
    assert "Latest price data is older than 7 days" in judge["gating_reasons"]
    assert "Latest evidence data is older than freshness policy allows" in judge["gating_reasons"]
    assert "## Evidence References" in report_body
    assert evidence_id in report_body
    assert "Refresh recommendation: refresh_recommended_before_action" in report_body
    assert dossier["price_freshness_status"] == "stale"
    assert dossier["evidence_freshness_status"] == "stale"
    assert dossier["refresh_recommendation"] == "refresh_recommended_before_action"
    assert evidence_id in dossier["evidence_citation_ids"]
    assert lineage["price_freshness_status"] == "stale"
    assert lineage["evidence_freshness_status"] == "stale"
    assert run_refresh_response.status_code == 200
    assert run_refresh["run_id"] == run_id
    assert run_refresh["refresh_recommendation"] == "refresh_recommended_before_action"
    assert run_refresh["judge_verdict"] == "block"
    assert asset_refresh_response.status_code == 200
    assert asset_refresh["asset_id"] == asset_id
    assert asset_refresh["latest_run_id"] == run_id
    assert asset_refresh["status"] == "stale"
    assert asset_refresh["refresh_recommendation"] == "refresh_recommended_before_action"
    app.dependency_overrides.clear()
