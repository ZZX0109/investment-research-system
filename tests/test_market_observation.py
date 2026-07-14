from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone

import pytest

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.market_models import ObservationRevision
from investment_research.domain.models import AnalysisRun, Asset, PaperObservation, PricePoint, PriceSeries
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.market_observation import CnTradingCalendar, MarketObservationService
from investment_research.workers.paper_validation import PaperValidationWorker


def _provenance(at: datetime) -> Provenance:
    return Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="test", observed_at=at)


def _context(tmp_path):
    now = datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "market.db")
    asset = Asset(ticker="600519.SH", name="Kweichow Moutai", asset_type=AssetType.EQUITY, exchange="XSHG", provenance=_provenance(now))
    uow.assets.add(asset)
    run = AnalysisRun(asset_id=asset.id, triggered_by="test", input_snapshot_ref="frozen", input_snapshot_hash="a" * 64, as_of=now, provenance=_provenance(now))
    uow.analysis_runs.add(run)
    return uow, asset, run, now


class _OpenCalendar:
    def status(self, now: datetime) -> str:
        del now
        return "open"


class _ClosedCalendar:
    def status(self, now: datetime) -> str:
        del now
        return "closed"


class _Provider:
    def __init__(self) -> None:
        self.calls = 0
        self.failure = False

    def fetch(self, asset: Asset, fetched_at: datetime):
        del asset
        self.calls += 1
        if self.failure:
            raise RuntimeError("provider unavailable")
        return 101.5, 100.0, fetched_at - timedelta(seconds=20), {"price": 101.5}

    def fetch_daily_close(self, asset: Asset, fetched_at: datetime):
        del asset
        self.calls += 1
        local_date = fetched_at.astimezone().date()
        return 100.0, 102.0, 99.0, 101.0, 1000.0, datetime.combine(local_date, time(15), tzinfo=timezone.utc), {"close": 101.0}


def test_cn_calendar_has_explicit_intraday_states() -> None:
    status = CnTradingCalendar._status_for_session_time
    assert status(time(9, 0)) == "pre_open"
    assert status(time(9, 30)) == "open"
    assert status(time(11, 30)) == "lunch_break"
    assert status(time(13, 0)) == "open"
    assert status(time(15, 0)) == "closed"


def test_quote_refresh_throttles_and_provider_failure_returns_last_success(tmp_path) -> None:
    uow, asset, _, now = _context(tmp_path)
    provider = _Provider()
    clock = [now]
    service = MarketObservationService(uow, provider=provider, calendar=_OpenCalendar(), clock=lambda: clock[0])

    first = service.refresh(str(asset.id))
    clock[0] += timedelta(minutes=2)
    throttled = service.refresh(str(asset.id))
    clock[0] += timedelta(minutes=4)
    provider.failure = True
    degraded = service.refresh(str(asset.id))

    assert provider.calls == 2
    assert first.latest_price == throttled.latest_price == degraded.latest_price == 101.5
    assert first.quote_delay_seconds == 20
    assert degraded.provider_status == "degraded"
    assert degraded.consecutive_failures == 1
    assert "provider_degraded" in degraded.degraded_reasons


def test_closed_market_solidifies_daily_close_at_most_once(tmp_path) -> None:
    uow, asset, _, now = _context(tmp_path)
    provider = _Provider()
    service = MarketObservationService(uow, provider=provider, calendar=_ClosedCalendar(), clock=lambda: now)
    result = service.refresh(str(asset.id))
    service.refresh(str(asset.id))
    attempts = uow.connection.execute("SELECT COUNT(*) FROM market_quote_attempts").fetchone()[0]
    assert result.market_status == "closed"
    assert provider.calls == 1
    assert attempts == 1
    assert result.last_close == 101.0


def test_paper_observation_settles_only_after_twenty_unique_daily_closes(tmp_path) -> None:
    uow, asset, run, now = _context(tmp_path)
    observation = PaperObservation(
        asset_id=asset.id,
        analysis_run_id=run.id,
        prediction_as_of=now,
        prediction_price=100.0,
        predicted_risk=0.85,
        evaluation_due_at=now + timedelta(days=30),
        provenance=_provenance(now),
    )
    uow.paper_observations.add(observation)
    intraday = []
    for index in range(40):
        at = now + timedelta(minutes=5 * index)
        intraday.append(PricePoint(asset_id=asset.id, timestamp=at, open=100, high=101, low=99, close=100, provenance=_provenance(at)))
    uow.price_series.add(PriceSeries(asset_id=asset.id, interval="5m", points=intraday, provenance=_provenance(now)))
    daily = []
    for index in range(19):
        at = now + timedelta(days=index)
        close = 100 if index < 10 else 90
        daily.append(PricePoint(asset_id=asset.id, timestamp=at, open=close, high=close, low=close, close=close, provenance=_provenance(at)))
    daily_series = PriceSeries(asset_id=asset.id, interval="1d", points=daily, provenance=_provenance(daily[-1].timestamp))
    uow.price_series.add(daily_series)

    PaperValidationWorker(uow).evaluate_observations(now + timedelta(days=25))
    pending = uow.paper_observations.list_for_asset(str(asset.id))[0]
    assert pending.outcome == "pending"
    assert pending.observed_trading_days == 19

    final_at = now + timedelta(days=19)
    daily_series.points.append(PricePoint(asset_id=asset.id, timestamp=final_at, open=90, high=90, low=90, close=90, provenance=_provenance(final_at)))
    uow.price_series.add(daily_series)
    PaperValidationWorker(uow).evaluate_observations(now + timedelta(days=26))
    settled = uow.paper_observations.list_for_asset(str(asset.id))[0]
    assert settled.outcome == "risk_hit"
    assert settled.observed_trading_days == 20
    assert settled.realized_max_drawdown == pytest.approx(-0.10)


def test_observation_revisions_cannot_be_overwritten(tmp_path) -> None:
    uow, _, run, now = _context(tmp_path)
    revision = ObservationRevision(
        observation_id=run.id,
        revision=1,
        reason="corporate_action",
        payload_hash=hashlib.sha256(b"adjusted").hexdigest(),
        payload={"adjustment": "split"},
        created_at=now,
    )
    uow.market_observations.add_revision(revision)
    with pytest.raises(ValueError, match="immutable"):
        uow.market_observations.add_revision(revision)
