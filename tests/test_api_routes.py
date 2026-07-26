import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from investment_research.api.auth_routes import get_auth_service, get_auth_settings
from investment_research.api.routes import (
    _load_latest_research_prediction,
    _load_latest_research_universe,
    get_analysis_provider_registry,
    get_analysis_provider_settings,
    get_unit_of_work,
)
from investment_research.auth.security import AuthSettings
from investment_research.auth.service import AuthService
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, Evidence
from investment_research.main import app
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import AnalysisProviderSettings, build_provider_registry


def _attach_csrf_header(client: TestClient, settings: AuthSettings) -> None:
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert csrf_token is not None
    client.headers[settings.csrf_header_name] = csrf_token


def configure_authenticated_client(
    tmp_path,
    filename: str,
    *,
    email: str = "investor@example.com",
    display_name: str = "Investor",
) -> TestClient:
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
            "email": email,
            "display_name": display_name,
            "password": "supersecret123",
        },
    )
    assert register_response.status_code == 201
    _attach_csrf_header(client, settings)
    return client


def test_asset_routes_round_trip_with_sqlite(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "api.db")

    create_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "aapl",
            "name": "Apple",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "iex-cloud-demo",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.97,
        },
    )
    list_response = client.get("/api/v1/assets?source_type=real")

    app.dependency_overrides.clear()

    assert create_response.status_code == 201
    assert create_response.json()["ticker"] == "AAPL"
    assert list_response.status_code == 200
    assert list_response.json()[0]["provenance"]["source_name"] == "iex-cloud-demo"


def test_agent_function_tool_contract_is_authenticated_and_read_only(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "agent-tools.db")

    response = client.get("/api/v1/agent-function-tools")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    tools = response.json()
    assert [tool["name"] for tool in tools] == [
        "collect_pit_evidence",
        "build_29_features",
        "approved_model_inference",
        "historical_analogy",
        "quality_gate",
        "get_price_trend",
        "get_four_task_forecasts",
        "get_company_announcements",
        "get_shadow_performance",
        "search_financial_knowledge",
    ]
    assert all(tool["parameters"]["additionalProperties"] is False for tool in tools)


def test_asset_can_be_removed_from_owner_workspace_without_erasing_history(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "remove-asset.db")
    create_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "510300",
            "name": "沪深300ETF",
            "asset_type": AssetType.ETF.value,
            "currency": "CNY",
            "exchange": "XSHG",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "cn-research-pit-ui",
            "observed_at": datetime(2026, 7, 23, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.95,
        },
    )
    asset_id = create_response.json()["id"]
    remove_response = client.delete(f"/api/v1/assets/{asset_id}")
    list_response = client.get("/api/v1/assets")

    uow = SQLiteUnitOfWork(tmp_path / "remove-asset.db")
    retained_asset = uow.assets.get(asset_id)
    audit_actions = [
        str(row[0])
        for row in uow.connection.execute(
            "SELECT action FROM audit_records ORDER BY observed_at"
        ).fetchall()
    ]
    uow.close()
    app.dependency_overrides.clear()

    assert remove_response.status_code == 204
    assert list_response.json() == []
    assert retained_asset is not None
    assert "asset.removed_from_workspace" in audit_actions


def test_latest_research_prediction_exposes_inputs_outputs_and_scope_miss(tmp_path) -> None:
    prediction_path = tmp_path / "artifacts" / "predictions" / "latest.json"
    prediction_path.parent.mkdir(parents=True)
    prediction_path.write_text(
        json.dumps(
            {
                "data_tier": "research_pit",
                "deployment_ready": False,
                "predictions": [
                    {
                        "symbol": "600519",
                        "task": "drawdown_20d",
                        "cohort": "cn_equity_core",
                        "trade_date": "2026-07-21",
                        "decision_context": "close_confirmed",
                        "market_snapshot_id": "snapshot-1",
                        "market_snapshot_hash": "a" * 64,
                        "prediction_price": 1500.0,
                        "coverage_ratio": 0.9,
                        "core_feature_coverage": 1.0,
                        "optional_feature_coverage": 0.5,
                        "event_coverage_status": "unsupported",
                        "data_status": "degraded",
                        "provider_chain": ["baostock"],
                        "cache_state": "fresh",
                        "prediction": {
                            "raw_probability": 0.62,
                            "calibrated_probability": 0.58,
                            "risk_level": "medium",
                            "threshold_drawdown": -0.08,
                        },
                        "model_candidate": "linear-baseline",
                        "model_role": "primary",
                        "research_status": "exploratory",
                        "roster_hash": "b" * 64,
                        "model_disagreement": 0.03,
                        "model_artifact_hashes": {"model": "c" * 64},
                        "research_limitations": ["research_only"],
                        "influence_facts": ["vol_20d=0.02"],
                        "gating_reasons": [],
                        "abstained": False,
                        "abstain_reasons": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "artifacts" / "cn_research_demo" / "latest.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "data_tier": "research_pit",
                "deployment_ready": False,
                "inference": {
                    "cn_equity_core": {
                        "prediction_ref": "artifacts/predictions/latest.json"
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    available = _load_latest_research_prediction(
        project_root=tmp_path,
        symbol="600519",
        task="drawdown_20d",
    )
    unavailable = _load_latest_research_prediction(
        project_root=tmp_path,
        symbol="000001",
        task="drawdown_20d",
    )

    assert available["status"] == "research_only"
    assert available["input"]["provider_chain"] == ["baostock"]
    assert available["output"]["calibrated_probability"] == 0.58
    assert available["deployment_ready"] is False
    assert unavailable["status"] == "unavailable"
    assert unavailable["blocking_reasons"] == ["symbol_absent_from_frozen_research_cohort"]
    assert unavailable["supported_symbols"] == ["600519"]


def test_latest_research_universe_lists_history_separately_from_frozen_predictions(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    standard = artifacts / "standard" / "600519.json"
    cohort = artifacts / "cohorts" / "equities.json"
    prediction = artifacts / "predictions" / "latest.json"
    rebuild = artifacts / "rebuild.json"
    for path in (standard, cohort, prediction):
        path.parent.mkdir(parents=True, exist_ok=True)
    standard.write_text(
        json.dumps(
            {
                "data_tier": "research_pit",
                "symbol": "600519",
                "provider": "baostock",
                "row_count": 5961,
                "quality_report": {"quality_status": "degraded"},
            }
        ),
        encoding="utf-8",
    )
    cohort.write_text(
        json.dumps({"members": [{"symbol": "600519"}]}),
        encoding="utf-8",
    )
    prediction.write_text(
        json.dumps(
            {
                "data_tier": "research_pit",
                "deployment_ready": False,
                "predictions": [{"symbol": "600519", "task": "drawdown_20d"}],
            }
        ),
        encoding="utf-8",
    )
    rebuild.write_text(
        json.dumps(
            {
                "data_tier": "research_pit",
                "deployment_ready": False,
                "as_of": "2026-07-21",
                "standard_manifest_refs": ["artifacts/standard/600519.json"],
                "cohort_refs": {"cn_equity_core": "artifacts/cohorts/equities.json"},
                "blocking_reasons": ["historical_available_at_unproven_public_backfill"],
            }
        ),
        encoding="utf-8",
    )
    report = artifacts / "cn_research_demo" / "latest.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "data_tier": "research_pit",
                "deployment_ready": False,
                "rebuild_index": "artifacts/rebuild.json",
                "inference": {
                    "cn_equity_core": {
                        "prediction_ref": "artifacts/predictions/latest.json"
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    payload = _load_latest_research_universe(project_root=tmp_path)

    assert payload["status"] == "research_only"
    assert payload["counts"] == {
        "historical": 1,
        "training_eligible": 1,
        "frozen_result_available": 1,
    }
    assert payload["symbols"][0] == {
        "symbol": "600519",
        "name": "600519",
        "exchange": "XSHG",
        "asset_type": "equity",
        "provider": "baostock",
        "row_count": 5961,
        "quality_status": "degraded",
        "training_eligible": True,
        "cohort": "cn_equity_core",
        "frozen_result_available": True,
    }


def test_domain_catalog_exposes_provider_configuration(tmp_path) -> None:
    provider_settings = AnalysisProviderSettings()
    provider_settings.market_data_provider = "persisted"
    provider_settings.evidence_provider = "persisted"

    def override_provider_settings() -> AnalysisProviderSettings:
        return provider_settings

    app.dependency_overrides[get_analysis_provider_settings] = override_provider_settings
    client = TestClient(app)
    response = client.get("/api/v1/domain/catalog")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["analysis_provider_config"] == {
        "market_data_provider": "persisted",
        "evidence_provider": "persisted",
    }


def test_domain_catalog_can_expose_stub_provider_configuration() -> None:
    provider_settings = AnalysisProviderSettings()
    provider_settings.market_data_provider = "stub_realtime"
    provider_settings.evidence_provider = "stub"

    def override_provider_settings() -> AnalysisProviderSettings:
        return provider_settings

    app.dependency_overrides[get_analysis_provider_settings] = override_provider_settings
    client = TestClient(app)
    response = client.get("/api/v1/domain/catalog")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["analysis_provider_config"] == {
        "market_data_provider": "stub_realtime",
        "evidence_provider": "stub",
    }
    assert response.json()["analysis_providers"][0]["provider_name"] == "stub-realtime-market-data-provider"


def test_real_mode_rejects_synthetic_asset_source(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "invalid-mode.db")

    create_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "snow",
            "name": "Snowflake",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.SYNTHETIC.value,
            "source_name": "demo-seed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.81,
        },
    )

    app.dependency_overrides.clear()

    assert create_response.status_code == 400
    assert "not allowed in real mode" in create_response.json()["detail"]


def test_write_routes_require_csrf_header(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    provider_settings = AnalysisProviderSettings()

    def override_settings() -> AuthSettings:
        return settings

    def override_provider_settings() -> AnalysisProviderSettings:
        return provider_settings

    def override_uow() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(tmp_path / "csrf-route.db")

    def override_provider_registry():
        return build_provider_registry(provider_settings)

    def override_auth_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / "csrf-route.db"), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_analysis_provider_settings] = override_provider_settings
    app.dependency_overrides[get_analysis_provider_registry] = override_provider_registry
    app.dependency_overrides[get_auth_service] = override_auth_service
    app.dependency_overrides[get_unit_of_work] = override_uow
    client = TestClient(app)
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf-route@example.com",
            "display_name": "CSRF Route",
            "password": "supersecret123",
        },
    )
    assert register_response.status_code == 201

    create_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "meta",
            "name": "Meta",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.95,
        },
    )

    app.dependency_overrides.clear()

    assert create_response.status_code == 403
    assert "CSRF" in create_response.json()["detail"]


def test_write_routes_reject_csrf_pair_not_bound_to_access_token(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    provider_settings = AnalysisProviderSettings()
    database_path = tmp_path / "csrf-route-bound.db"

    def override_settings() -> AuthSettings:
        return settings

    def override_provider_settings() -> AnalysisProviderSettings:
        return provider_settings

    def override_uow() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(database_path)

    def override_provider_registry():
        return build_provider_registry(provider_settings)

    def override_auth_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(database_path), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_analysis_provider_settings] = override_provider_settings
    app.dependency_overrides[get_analysis_provider_registry] = override_provider_registry
    app.dependency_overrides[get_auth_service] = override_auth_service
    app.dependency_overrides[get_unit_of_work] = override_uow
    client = TestClient(app)
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf-route-bound@example.com",
            "display_name": "CSRF Route Bound",
            "password": "supersecret123",
        },
    )
    access_token = client.cookies.get(settings.access_cookie_name)
    assert register_response.status_code == 201
    assert access_token is not None

    forged_client = TestClient(app)
    forged_client.cookies.set(settings.access_cookie_name, access_token)
    forged_client.cookies.set(settings.csrf_cookie_name, "forged-csrf-token")
    create_response = forged_client.post(
        "/api/v1/assets",
        headers={settings.csrf_header_name: "forged-csrf-token"},
        json={
            "ticker": "meta",
            "name": "Meta",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.95,
        },
    )

    app.dependency_overrides.clear()

    assert create_response.status_code == 403
    assert create_response.json()["detail"] == "Invalid CSRF token"


def test_demo_analysis_run_can_be_persisted_and_reloaded(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "demo.db")

    persist_response = client.post("/api/v1/analysis-runs/demo/persist")
    run_id = persist_response.json()["id"]
    get_response = client.get(f"/api/v1/analysis-runs/{run_id}")

    app.dependency_overrides.clear()

    assert persist_response.status_code == 201
    assert get_response.status_code == 200
    assert get_response.json()["provenance"]["data_mode"] == "demo"
    assert get_response.json()["triggered_by"].startswith("user:")


def test_positions_and_audit_records_follow_authenticated_user(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "portfolio.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "msft",
            "name": "Microsoft",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "manual-curation",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.99,
        },
    )
    asset_id = asset_response.json()["id"]
    position_response = client.post(
        "/api/v1/positions",
        json={
            "asset_id": asset_id,
            "quantity": 10,
            "cost_basis": 450.25,
            "opened_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
        },
    )
    positions_response = client.get("/api/v1/positions/me")
    audit_response = client.get("/api/v1/audit-records/me")

    app.dependency_overrides.clear()

    assert position_response.status_code == 201
    assert positions_response.status_code == 200
    assert positions_response.json()[0]["asset_id"] == asset_id
    assert audit_response.status_code == 200
    assert {record["action"] for record in audit_response.json()} >= {"asset.created", "position.created"}


def test_research_workflow_routes_cover_watchlists_prices_evidence_and_reports(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "research.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "nvda",
            "name": "NVIDIA",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "research-fixture",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.95,
        },
    )
    asset_id = asset_response.json()["id"]

    watchlist_response = client.post(
        "/api/v1/watchlists",
        json={"name": "AI Leaders", "asset_ids": [asset_id]},
    )
    price_series_response = client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "fixture-prices",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.88,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 2, tzinfo=timezone.utc).isoformat(),
                    "open": 120.0,
                    "high": 125.0,
                    "low": 119.5,
                    "close": 124.5,
                    "volume": 1000000,
                }
            ],
        },
    )
    evidence_response = client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Demand remains strong",
            "summary": "Datacenter demand remains resilient in the sandbox scenario.",
            "source_url": "https://example.test/evidence/nvda",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.SYNTHETIC.value,
            "source_name": "sandbox-analyst",
            "confidence": 0.76,
        },
    )
    analysis_run_response = client.post("/api/v1/analysis-runs/demo/persist")
    run_id = analysis_run_response.json()["id"]
    evidence_id = evidence_response.json()["id"]
    report_response = client.post(
        f"/api/v1/assets/{asset_id}/reports",
        json={
            "asset_id": asset_id,
            "analysis_run_id": run_id,
            "title": "NVDA Sandbox Memo",
            "thesis": "Sandbox scenario still supports a constructive long-term thesis.",
            "evidence_ids": [evidence_id],
            "report_version": "1.0.0",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.SYNTHETIC.value,
            "source_name": "report-builder",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.72,
        },
    )

    watchlists_get = client.get("/api/v1/watchlists/me")
    price_series_get = client.get(f"/api/v1/assets/{asset_id}/price-series")
    evidence_get = client.get(f"/api/v1/assets/{asset_id}/evidence")
    reports_get = client.get(f"/api/v1/assets/{asset_id}/reports")
    audit_get = client.get("/api/v1/audit-records/me")

    app.dependency_overrides.clear()

    assert watchlist_response.status_code == 201
    assert watchlists_get.status_code == 200
    assert watchlists_get.json()[0]["asset_ids"] == [asset_id]
    assert price_series_response.status_code == 201
    assert price_series_get.json()[0]["points"][0]["close"] == 124.5
    assert evidence_response.status_code == 201
    assert evidence_get.json()[0]["evidence_type"] == "research_note"
    assert report_response.status_code == 201
    assert reports_get.json()[0]["analysis_run_id"] == run_id
    assert {record["action"] for record in audit_get.json()} >= {
        "watchlist.created",
        "price-series.created",
        "evidence.created",
        "report.created",
    }


def test_watchlist_rejects_mixed_data_modes(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "mixed-watchlist.db")

    demo_asset = client.post(
        "/api/v1/assets",
        json={
            "ticker": "demo1",
            "name": "Demo Seed One",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.DEMO.value,
            "source_type": DataSourceType.SYNTHETIC.value,
            "source_name": "demo-seed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.77,
        },
    )
    real_asset = client.post(
        "/api/v1/assets",
        json={
            "ticker": "real1",
            "name": "Real Feed One",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.97,
        },
    )
    watchlist_response = client.post(
        "/api/v1/watchlists",
        json={
            "name": "Mixed Sources",
            "asset_ids": [demo_asset.json()["id"], real_asset.json()["id"]],
        },
    )

    app.dependency_overrides.clear()

    assert watchlist_response.status_code == 400
    assert "cannot mix data modes transparently" in watchlist_response.json()["detail"]


def test_analysis_pipeline_creates_reproducible_bundle_from_persisted_data(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "pipeline.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "amd",
            "name": "AMD",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.99,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.99,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 104.0,
                    "volume": 2000000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Channel checks improve",
            "summary": "Field checks show healthy backlog and better margins.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "analyst-desk",
            "confidence": 0.91,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    runs_response = client.get(f"/api/v1/assets/{asset_id}/analysis-runs")
    bundle_response = client.get(f"/api/v1/analysis-runs/{run_id}/bundle")

    app.dependency_overrides.clear()

    assert analysis_response.status_code == 201
    assert analysis_response.json()["snapshot"]["latest_close"] == 104.0
    assert analysis_response.json()["run"]["input_snapshot_ref"].endswith(run_id)
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["id"] == run_id
    assert bundle_response.status_code == 200
    assert bundle_response.json()["predictions"]
    assert bundle_response.json()["judge_scores"][0]["verdict"] in {"pass", "warn", "hold", "block"}


def test_analysis_run_views_are_isolated_between_users(tmp_path) -> None:
    database_name = "run-user-isolation.db"
    alice = configure_authenticated_client(
        tmp_path,
        database_name,
        email="alice-isolation@example.com",
        display_name="Alice Isolation",
    )

    asset_response = alice.post(
        "/api/v1/assets",
        json={
            "ticker": "team",
            "name": "Atlassian",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.96,
        },
    )
    asset_id = asset_response.json()["id"]
    alice.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.91,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 180.0,
                    "high": 186.0,
                    "low": 179.0,
                    "close": 185.0,
                    "volume": 500000,
                }
            ],
        },
    )
    alice.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Enterprise demand remains stable",
            "summary": "Enterprise cloud demand supports the isolation test analysis run.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "analyst-desk",
            "confidence": 0.86,
        },
    )
    analysis_response = alice.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]

    bob = configure_authenticated_client(
        tmp_path,
        database_name,
        email="bob-isolation@example.com",
        display_name="Bob Isolation",
    )
    bob_run_list = bob.get(f"/api/v1/assets/{asset_id}/analysis-runs")
    bob_lineage = bob.get(f"/api/v1/assets/{asset_id}/lineage")
    blocked_reads = [
        bob.get(f"/api/v1/analysis-runs/{run_id}"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/bundle"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/comparison"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/replay-summary"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/dossier"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/lineage-detail"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/scope"),
        bob.get(f"/api/v1/analysis-runs/{run_id}/refresh-status"),
        bob.post(f"/api/v1/analysis-runs/{run_id}/report"),
    ]
    alice_run = alice.get(f"/api/v1/analysis-runs/{run_id}")

    app.dependency_overrides.clear()

    assert analysis_response.status_code == 201
    assert bob_run_list.status_code == 200
    assert bob_run_list.json() == []
    assert bob_lineage.status_code == 200
    assert bob_lineage.json()["entries"] == []
    assert [response.status_code for response in blocked_reads] == [404] * len(blocked_reads)
    assert alice_run.status_code == 200
    assert alice_run.json()["id"] == run_id


def test_analysis_bundle_and_report_replay_frozen_input_snapshots(tmp_path) -> None:
    db_path = tmp_path / "frozen-snapshot.db"
    client = configure_authenticated_client(tmp_path, db_path.name)

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "adbe",
            "name": "Adobe",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.96,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.96,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 510.0,
                    "high": 522.0,
                    "low": 506.0,
                    "close": 519.5,
                    "volume": 720000,
                }
            ],
        },
    )
    evidence_response = client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Original run evidence",
            "summary": "This note should remain attached to the historical run.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "analyst-desk",
            "confidence": 0.89,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]

    uow = SQLiteUnitOfWork(db_path)
    try:
        current_asset = Asset.model_validate(asset_response.json())
        uow.assets.add(current_asset.model_copy(update={"ticker": "MUTD", "name": "Mutated Adobe"}))
        current_evidence = Evidence.model_validate(evidence_response.json())
        uow.evidence.add(
            current_evidence.model_copy(
                update={
                    "title": "Mutated current evidence",
                    "summary": "This mutation must not alter the already-created run.",
                }
            )
        )
    finally:
        uow.close()

    bundle_response = client.get(f"/api/v1/analysis-runs/{run_id}/bundle")
    report_response = client.post(f"/api/v1/analysis-runs/{run_id}/report")

    app.dependency_overrides.clear()

    assert analysis_response.status_code == 201
    assert bundle_response.status_code == 200
    bundle = bundle_response.json()
    assert bundle["asset"]["ticker"] == "ADBE"
    assert bundle["snapshot"]["asset_snapshot"]["ticker"] == "ADBE"
    assert bundle["evidence"][0]["title"] == "Original run evidence"
    assert bundle["snapshot"]["evidence_snapshot"][0]["title"] == "Original run evidence"
    assert bundle["snapshot"]["price_series_snapshot"][0]["points"][0]["close"] == 519.5
    assert report_response.status_code == 201
    report_body = report_response.json()["report"]["body_markdown"]
    assert "# ADBE Analysis Run" in report_body
    assert "Original run evidence" in report_body
    assert "Mutated current evidence" not in report_body
    assert "MUTD" not in report_body


def test_real_mode_analysis_surfaces_provider_fallback_when_live_inputs_are_missing(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "real-fallback.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "orcl",
            "name": "Oracle",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
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
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.84,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 2, tzinfo=timezone.utc).isoformat(),
                    "open": 172.0,
                    "high": 174.0,
                    "low": 171.5,
                    "close": 173.8,
                    "volume": 940000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Curated field note",
            "summary": "Analyst note remains available even while live evidence ingestion is offline.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.MANUAL_OVERRIDE.value,
            "source_name": "research-desk",
            "confidence": 0.78,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    report_response = client.post(f"/api/v1/analysis-runs/{run_id}/report")

    app.dependency_overrides.clear()

    snapshot = analysis_response.json()["snapshot"]
    judge = analysis_response.json()["judge_scores"][0]
    recommendation = analysis_response.json()["recommendations"][0]
    report_body = report_response.json()["report"]["body_markdown"]

    assert analysis_response.status_code == 201
    assert snapshot["price_provider_status"] == "backfilled"
    assert snapshot["price_provider_name"] == "persisted-market-data-provider"
    assert snapshot["price_provider_version"] == "1.0.0"
    assert snapshot["evidence_provider_status"] == "backfilled"
    assert snapshot["evidence_provider_name"] == "persisted-evidence-provider"
    assert snapshot["evidence_provider_version"] == "1.0.0"
    assert "Real-time market data unavailable" in snapshot["fallback_reasons"][0]
    assert judge["verdict"] == "block"
    assert "Prediction model is not approved for deployment" in judge["gating_reasons"]
    assert recommendation["action"] == "avoid"
    assert any("No real-time evidence feed available" in reason for reason in judge["gating_reasons"])
    assert any("Real-time market data unavailable" in item for item in recommendation["guardrails"])
    assert snapshot["provider"]
    assert snapshot["mode"] == "real"
    assert snapshot["as_of"]
    assert "- Price provider: persisted-market-data-provider@1.0.0" in report_body
    assert "- Price provider status: backfilled" in report_body


def test_run_comparison_summarizes_delta_against_prior_frozen_run(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "run-comparison.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "intc",
            "name": "Intel",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
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
            "observed_at": datetime(2026, 7, 2, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.83,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 2, tzinfo=timezone.utc).isoformat(),
                    "open": 31.0,
                    "high": 31.5,
                    "low": 30.5,
                    "close": 31.2,
                    "volume": 950000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Fallback-only evidence",
            "summary": "Manual desk note exists before the live evidence source returns.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.MANUAL_OVERRIDE.value,
            "source_name": "research-desk",
            "confidence": 0.77,
        },
    )

    first_analysis = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    first_run_id = first_analysis.json()["run"]["id"]
    first_report = client.post(f"/api/v1/analysis-runs/{first_run_id}/report")
    assert first_report.status_code == 201

    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.96,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 31.4,
                    "high": 32.7,
                    "low": 31.1,
                    "close": 32.4,
                    "volume": 1210000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Live evidence feed recovered",
            "summary": "Wire-backed evidence is now available and should clear the fallback gate.",
            "collected_at": datetime(2026, 7, 3, 1, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "news-wire",
            "confidence": 0.9,
        },
    )

    second_analysis = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    second_run_id = second_analysis.json()["run"]["id"]
    second_report = client.post(f"/api/v1/analysis-runs/{second_run_id}/report")
    comparison_response = client.get(f"/api/v1/analysis-runs/{second_run_id}/comparison")
    timeline_response = client.get(f"/api/v1/assets/{asset_id}/lineage")

    assert second_report.status_code == 201
    assert comparison_response.status_code == 200
    payload = comparison_response.json()
    assert payload["current_run_id"] == second_run_id
    assert payload["baseline_run_id"] == first_run_id
    assert payload["judge_score_delta"] >= 0
    assert payload["confidence_delta"] >= 0
    assert round(payload["latest_close_delta"], 2) == 1.20
    assert "Real-time market data unavailable; analysis fell back to backfilled price history." in payload["removed_fallbacks"]
    assert "No real-time evidence feed available; analysis fell back to curated persisted evidence." in payload["removed_gates"]
    assert payload["thesis_changed"] is True

    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert timeline["asset_id"] == asset_id
    assert len(timeline["entries"]) == 2
    assert timeline["entries"][0]["report_version"] == "auto-1.0.0"
    assert timeline["entries"][0]["judge_verdict"] in {"pass", "warn", "hold", "block"}
    assert timeline["entries"][0]["provider"]
    assert timeline["entries"][0]["mode"]
    assert timeline["entries"][0]["evidence_count"] >= 1
    assert timeline["entries"][0]["evidence_items"][0]["title"]
    assert timeline["entries"][0]["evidence_items"][0]["summary"]
    assert timeline["entries"][0]["report_thesis"]
    assert timeline["entries"][0]["recommendation_reasoning"]
    assert "analysis-run.created" in timeline["entries"][0]["audit_actions"]

    app.dependency_overrides.clear()


def test_run_replay_summary_exposes_frozen_run_header_context(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "run-replay-summary.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "crm",
            "name": "Salesforce",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.97,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.97,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 265.0,
                    "high": 268.0,
                    "low": 263.4,
                    "close": 267.2,
                    "volume": 640000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Pipeline remains durable",
            "summary": "Enterprise renewal commentary remains resilient in the curated research note.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "analyst-desk",
            "confidence": 0.88,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    summary_response = client.get(f"/api/v1/analysis-runs/{run_id}/replay-summary")

    app.dependency_overrides.clear()

    assert summary_response.status_code == 200
    summary = summary_response.json()
    run = analysis_response.json()["run"]
    assert summary["run_id"] == run_id
    assert summary["asset_id"] == asset_id
    assert summary["asset_ticker"] == "CRM"
    assert summary["asset_name"] == "Salesforce"
    assert summary["report_version"] == "pending"
    assert summary["judge_verdict"] in {"pass", "warn", "hold", "block"}
    assert summary["recommendation_action"] in {"buy", "hold", "reduce", "avoid"}
    assert summary["provider"]
    assert summary["mode"] == "real"
    assert summary["as_of"]
    assert summary["source_name"] == run["provenance"]["source_name"]
    assert summary["confidence"] == run["provenance"]["confidence"]
    assert summary["observed_at"] == run["provenance"]["observed_at"]
    assert summary["evidence_count"] >= 1
    assert summary["fallback_count"] >= 0


def test_run_dossier_summary_exposes_fixed_run_conclusions(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "run-dossier-summary.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "shop",
            "name": "Shopify",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.94,
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
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.84,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 2, tzinfo=timezone.utc).isoformat(),
                    "open": 78.0,
                    "high": 80.4,
                    "low": 77.6,
                    "close": 79.8,
                    "volume": 510000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Merchant cohort remains durable",
            "summary": "Curated note suggests retention holds despite slower GMV growth.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.MANUAL_OVERRIDE.value,
            "source_name": "research-desk",
            "confidence": 0.79,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    report_response = client.post(f"/api/v1/analysis-runs/{run_id}/report")
    dossier_response = client.get(f"/api/v1/analysis-runs/{run_id}/dossier")

    app.dependency_overrides.clear()

    assert report_response.status_code == 201
    assert dossier_response.status_code == 200
    dossier = dossier_response.json()
    assert dossier["run_id"] == run_id
    assert dossier["asset_ticker"] == "SHOP"
    assert dossier["report_version"]
    assert dossier["report_title"]
    assert dossier["report_thesis"]
    assert dossier["judge_verdict"] in {"pass", "warn", "hold", "block"}
    assert dossier["gate_count"] >= 0
    assert isinstance(dossier["gating_reasons"], list)
    assert isinstance(dossier["fallback_reasons"], list)
    assert dossier["provider"]
    assert dossier["mode"] == "real"
    assert dossier["recommendation_action"] in {"buy", "hold", "sell", "reduce", "avoid"}
    assert dossier["risk_level"] in {"low", "medium", "high", "critical", "n/a"}


def test_run_scope_summary_exposes_immutable_run_research_links(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "run-scope-summary.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "adbe",
            "name": "Adobe",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
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
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.95,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 510.0,
                    "high": 517.0,
                    "low": 508.5,
                    "close": 515.6,
                    "volume": 420000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Subscription retention holds",
            "summary": "Curated note suggests subscription durability and steady enterprise demand.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "analyst-desk",
            "confidence": 0.87,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    scope_response = client.get(f"/api/v1/analysis-runs/{run_id}/scope")

    app.dependency_overrides.clear()

    assert scope_response.status_code == 200
    scope = scope_response.json()
    assert scope["run_id"] == run_id
    assert scope["asset_id"] == asset_id
    assert isinstance(scope["evidence_ids"], list)
    assert isinstance(scope["report_ids"], list)
    assert scope["evidence_count"] == len(scope["evidence_ids"])
    assert scope["report_count"] == len(scope["report_ids"])


def test_run_lineage_detail_summary_exposes_selected_run_snapshot_panels(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "run-lineage-detail.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "uber",
            "name": "Uber",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.94,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.94,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 83.4,
                    "high": 85.1,
                    "low": 82.7,
                    "close": 84.8,
                    "volume": 830000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Mobility margin stabilizes",
            "summary": "Curated research suggests take-rate and margin trends remain stable.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "analyst-desk",
            "confidence": 0.85,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    detail_response = client.get(f"/api/v1/analysis-runs/{run_id}/lineage-detail")

    app.dependency_overrides.clear()

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run_id"] == run_id
    assert detail["asset_id"] == asset_id
    assert detail["input_snapshot_ref"].endswith(run_id)
    assert detail["intake_strategy"]
    assert detail["captured_at"]
    assert isinstance(detail["data_modes"], list)
    assert isinstance(detail["source_types"], list)
    assert detail["price_provider_status"]
    assert detail["evidence_provider_status"]
    assert detail["judge_verdict"] in {"pass", "warn", "hold", "block"}
    assert detail["provider"]
    assert detail["mode"] == "real"
    assert detail["as_of"]
    assert detail["recommendation_action"] in {"buy", "hold", "sell", "reduce", "avoid"}
    assert isinstance(detail["fallback_reasons"], list)


def test_real_mode_analysis_can_use_stub_provider_configuration(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    provider_settings = AnalysisProviderSettings()
    provider_settings.market_data_provider = "stub_realtime"
    provider_settings.evidence_provider = "stub"

    def override_settings() -> AuthSettings:
        return settings

    def override_provider_settings() -> AnalysisProviderSettings:
        return provider_settings

    def override_uow() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(tmp_path / "stub-provider.db")

    def override_provider_registry():
        return build_provider_registry(provider_settings)

    def override_auth_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / "stub-provider.db"), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_analysis_provider_settings] = override_provider_settings
    app.dependency_overrides[get_analysis_provider_registry] = override_provider_registry
    app.dependency_overrides[get_auth_service] = override_auth_service
    app.dependency_overrides[get_unit_of_work] = override_uow
    client = TestClient(app)
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "stub@example.com",
            "display_name": "Stub Investor",
            "password": "supersecret123",
        },
    )
    assert register_response.status_code == 201
    _attach_csrf_header(client, settings)

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "crm",
            "name": "Salesforce",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NYSE",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.97,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "market-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.97,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 260.0,
                    "high": 264.5,
                    "low": 259.0,
                    "close": 263.9,
                    "volume": 810000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Pipeline-ready real note",
            "summary": "Stub provider path should see this as real-time evidence.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "news-wire",
            "confidence": 0.88,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")

    app.dependency_overrides.clear()

    snapshot = analysis_response.json()["snapshot"]
    assert analysis_response.status_code == 201
    assert snapshot["price_provider_name"] == "stub-realtime-market-data-provider"
    assert snapshot["price_provider_version"] == "0.1.0"
    assert snapshot["price_provider_status"] == "stub_real_time"
    assert snapshot["evidence_provider_name"] == "stub-realtime-evidence-provider"
    assert snapshot["evidence_provider_status"] == "stub_real_time"


def test_report_generation_uses_fixed_analysis_run_bundle(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "reports-from-run.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "meta",
            "name": "Meta Platforms",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "fixture-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.9,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "fixture-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.85,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 500.0,
                    "high": 509.0,
                    "low": 498.0,
                    "close": 507.0,
                    "volume": 1500000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Ads recovery continues",
            "summary": "Spend trends remain supportive in the sandbox dataset.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.SYNTHETIC.value,
            "source_name": "demo-research",
            "confidence": 0.73,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    run_id = analysis_response.json()["run"]["id"]
    report_response = client.post(f"/api/v1/analysis-runs/{run_id}/report")
    bundle_response = client.get(f"/api/v1/analysis-runs/{run_id}/bundle")

    app.dependency_overrides.clear()

    assert report_response.status_code == 201
    assert report_response.json()["report"]["analysis_run_id"] == run_id
    assert "# META Analysis Run" in report_response.json()["report"]["body_markdown"]
    assert bundle_response.status_code == 200
    assert bundle_response.json()["reports"][0]["id"] == report_response.json()["report"]["id"]


def test_sandbox_analysis_run_is_explicitly_warned_by_mode_policy(tmp_path) -> None:
    client = configure_authenticated_client(tmp_path, "sandbox-policy.db")

    asset_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "adbe",
            "name": "Adobe",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "fixture-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.9,
        },
    )
    asset_id = asset_response.json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/price-series",
        json={
            "asset_id": asset_id,
            "interval": "1d",
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.BACKFILLED.value,
            "source_name": "fixture-feed",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.86,
            "points": [
                {
                    "timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                    "open": 560.0,
                    "high": 568.0,
                    "low": 558.0,
                    "close": 566.0,
                    "volume": 1200000,
                }
            ],
        },
    )
    client.post(
        f"/api/v1/assets/{asset_id}/evidence",
        json={
            "asset_id": asset_id,
            "evidence_type": "research_note",
            "title": "Workflow test thesis",
            "summary": "Synthetic scenario exists to exercise the research flow rather than produce live recommendations.",
            "collected_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "data_mode": DataMode.SANDBOX.value,
            "source_type": DataSourceType.SYNTHETIC.value,
            "source_name": "sandbox-analyst",
            "confidence": 0.72,
        },
    )

    analysis_response = client.post(f"/api/v1/assets/{asset_id}/analysis-runs")
    judge = analysis_response.json()["judge_scores"][0]
    audit_response = client.get("/api/v1/audit-records/me")

    app.dependency_overrides.clear()

    assert analysis_response.status_code == 201
    assert judge["verdict"] == "block"
    assert "Prediction model is not approved for deployment" in judge["gating_reasons"]
    assert "Sandbox mode is intended for testing and training" in judge["gating_reasons"][0]
    assert "Real data share below 40%" in judge["gating_reasons"]
    assert any(record["provenance"]["data_mode"] == "sandbox" for record in audit_response.json())


def test_write_routes_require_authenticated_user(tmp_path) -> None:
    def override_uow() -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(tmp_path / "anon.db")

    app.dependency_overrides[get_unit_of_work] = override_uow
    client = TestClient(app)

    create_response = client.post(
        "/api/v1/assets",
        json={
            "ticker": "tsla",
            "name": "Tesla",
            "asset_type": AssetType.EQUITY.value,
            "currency": "usd",
            "exchange": "NASDAQ",
            "data_mode": DataMode.REAL.value,
            "source_type": DataSourceType.REAL.value,
            "source_name": "manual-entry",
            "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
            "confidence": 0.8,
        },
    )

    app.dependency_overrides.clear()

    assert create_response.status_code == 401
