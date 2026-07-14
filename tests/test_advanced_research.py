from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from investment_research.domain.base import Provenance
from investment_research.domain.enums import (
    AssetType,
    DataMode,
    DataSourceType,
    EvidenceType,
)
from investment_research.domain.models import (
    Asset,
    Evidence,
    Position,
    PricePoint,
    PriceSeries,
    User,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.advanced_research import (
    AssetRefreshService,
    HistoricalAnalogyService,
    PortfolioRiskService,
)
from investment_research.service.documents import DocumentService
from investment_research.service.scheduling import ReportScheduleService, next_run


def provenance(observed_at: datetime | None = None) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="authoritative-test-cache",
        observed_at=observed_at or datetime.now(timezone.utc),
        confidence=0.95,
    )


def build_context(tmp_path, *, point_count: int = 180):
    uow = SQLiteUnitOfWork(tmp_path / "advanced.db")
    user = User(
        email="advanced@example.com",
        display_name="Advanced",
        auth_subject="user:advanced@example.com",
        provenance=provenance(),
    )
    asset = Asset(
        ticker="AAPL",
        name="Apple",
        asset_type=AssetType.EQUITY,
        provenance=provenance(),
    )
    uow.assets.add(asset)
    start = datetime.now(timezone.utc) - timedelta(days=point_count - 1)
    points = [
        PricePoint(
            asset_id=asset.id,
            timestamp=start + timedelta(days=index),
            open=100 + index * 0.1,
            high=101 + index * 0.1,
            low=99 + index * 0.1,
            close=100 + index * 0.1 + (index % 7) * 0.2,
            volume=1_000_000 + index * 100,
            provenance=provenance(start + timedelta(days=index)),
        )
        for index in range(point_count)
    ]
    series = PriceSeries(
        asset_id=asset.id,
        interval="1d",
        points=points,
        provenance=provenance(points[-1].timestamp),
    )
    return uow, user, asset, series


def test_historical_analogies_keep_63_future_observations_before_as_of(
    tmp_path,
) -> None:
    uow, _, asset, series = build_context(tmp_path)
    uow.price_series.add(series)

    scenarios = HistoricalAnalogyService(uow).find(
        str(asset.id), as_of=series.points[-1].timestamp, limit=4
    )

    assert scenarios
    point_dates = [point.timestamp for point in series.points]
    for scenario in scenarios:
        candidate_index = point_dates.index(scenario.candidate_date)
        assert candidate_index + 63 < len(point_dates)
        assert scenario.candidate_date < scenario.as_of


def test_portfolio_risk_uses_user_positions_and_real_prices(tmp_path) -> None:
    uow, user, asset, series = build_context(tmp_path)
    uow.price_series.add(series)
    uow.positions.add(
        Position(
            user_id=user.id,
            asset_id=asset.id,
            quantity=10,
            cost_basis=90,
            opened_at=series.points[0].timestamp,
            provenance=provenance(),
        )
    )

    snapshot = PortfolioRiskService(uow).calculate(user=user)

    assert snapshot.total_market_value == pytest.approx(10 * series.points[-1].close)
    assert snapshot.concentration_hhi == pytest.approx(1.0)
    assert snapshot.position_risk_contributions[str(asset.id)] > 0
    assert snapshot.stress_scenarios["market_minus_10pct"] < 0


def test_refresh_explicitly_marks_real_cache_fallback_as_degraded(tmp_path) -> None:
    uow, user, asset, series = build_context(tmp_path)
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.FILING,
        title="Quarterly filing",
        summary="Official filing available.",
        collected_at=series.points[-1].timestamp,
        published_at=series.points[-1].timestamp,
        source_url="https://www.sec.gov/example",
        provenance=provenance(series.points[-1].timestamp),
    )

    class Store:
        def price_series_for_asset(self, _asset):
            return [series]

        def evidence_for_asset(self, _asset):
            return [evidence]

    class FailingLiveStore:
        def price_series_for_asset(self, _asset):
            raise RuntimeError("network unavailable")

    result = AssetRefreshService(
        uow, bundle_store=Store(), live_store=FailingLiveStore()
    ).refresh_and_analyze(str(asset.id), user=user)

    assert result.refresh_run.state == "degraded"
    assert result.refresh_run.cache_hit is True
    assert result.refresh_run.provider_attempts[0]["status"] == "failed"
    assert result.analysis_bundle is not None
    assert result.analysis_bundle.run.refresh_run_id == result.refresh_run.id


def test_schedule_crud_and_next_run_are_persisted(tmp_path) -> None:
    uow, user, asset, _ = build_context(tmp_path)
    service = ReportScheduleService(uow)
    schedule = service.create(user=user, frequency="weekly", asset_id=str(asset.id))

    assert schedule.next_run_at is not None
    assert next_run("manual", datetime.now(timezone.utc)) is None
    assert service.list(user=user)[0].frequency == "weekly"
    updated = service.update(
        str(schedule.id), user=user, frequency="monthly", enabled=True
    )
    assert updated.frequency == "monthly"
    service.delete(str(schedule.id), user=user)
    assert service.list(user=user) == []


def test_pdf_pipeline_preserves_page_and_table_provenance(tmp_path) -> None:
    fitz = pytest.importorskip("fitz")
    uow, user, asset, _ = build_context(tmp_path)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Revenue 2026 100\nRisk factors updated")
    data = pdf.tobytes()
    pdf.close()

    artifact = DocumentService(uow, root=tmp_path / "documents").create(
        user=user,
        asset_id=str(asset.id),
        filename="filing.pdf",
        content_type="application/pdf",
        data=data,
        source_url="https://www.sec.gov/example.pdf",
    )

    assert artifact.page_count == 1
    assert artifact.parse_status == "parsed"
    assert "[page 1]" in (artifact.text_summary or "")
    assert (
        DocumentService(uow, root=tmp_path / "documents").get_for_user(
            str(artifact.id), user=user
        )
        == artifact
    )


def test_pdf_pipeline_rejects_non_allowlisted_source_url(tmp_path) -> None:
    fitz = pytest.importorskip("fitz")
    uow, user, _, _ = build_context(tmp_path)
    pdf = fitz.open()
    pdf.new_page()
    data = pdf.tobytes()
    pdf.close()

    with pytest.raises(ValueError, match="not allowlisted"):
        DocumentService(uow, root=tmp_path / "documents").create(
            user=user,
            filename="unknown.pdf",
            content_type="application/pdf",
            data=data,
            source_url="https://example.com/unknown.pdf",
        )
