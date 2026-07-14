from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.market_models import MarketQuote, MarketQuoteAttempt
from investment_research.domain.models import Asset, PricePoint, PriceSeries, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.workers.paper_validation import PaperValidationWorker

PROVIDER = "akshare/eastmoney-delayed"
DAILY_PROVIDER = "akshare/eastmoney-daily"


class QuoteProvider(Protocol):
    def fetch(self, asset: Asset, fetched_at: datetime) -> tuple[float, float | None, datetime, dict]: ...
    def fetch_daily_close(self, asset: Asset, fetched_at: datetime) -> tuple[float, float, float, float, float | None, datetime, dict]: ...


class AkshareEastMoneyQuoteProvider:
    def fetch(self, asset: Asset, fetched_at: datetime) -> tuple[float, float | None, datetime, dict]:
        import akshare as ak  # type: ignore
        frame = ak.stock_zh_a_spot_em()
        code = asset.ticker.split(".")[0]
        row = frame[frame["代码"].astype(str).str.zfill(6) == code.zfill(6)].iloc[0]
        payload = {str(key): (value.item() if hasattr(value, "item") else value) for key, value in row.to_dict().items()}
        return float(row["最新价"]), _optional_float(row.get("昨收")), fetched_at, payload

    def fetch_daily_close(self, asset: Asset, fetched_at: datetime) -> tuple[float, float, float, float, float | None, datetime, dict]:
        import akshare as ak  # type: ignore
        local_date = fetched_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
        compact = local_date.strftime("%Y%m%d")
        frame = ak.stock_zh_a_hist(symbol=asset.ticker.split(".")[0], period="daily", start_date=compact, end_date=compact, adjust="")
        if frame.empty:
            raise LookupError("Daily close is not available")
        row = frame.iloc[-1]
        payload = {str(key): (value.item() if hasattr(value, "item") else value) for key, value in row.to_dict().items()}
        close_at = datetime.combine(local_date, time(15), tzinfo=ZoneInfo("Asia/Shanghai"))
        return float(row["开盘"]), float(row["最高"]), float(row["最低"]), float(row["收盘"]), _optional_float(row.get("成交量")), close_at, payload


class CnTradingCalendar:
    def status(self, now: datetime) -> str:
        local = now.astimezone(ZoneInfo("Asia/Shanghai"))
        try:
            import exchange_calendars as xcals  # type: ignore
            calendar = xcals.get_calendar("XSHG")
            if not calendar.is_session(local.date().isoformat()):
                return "holiday"
        except Exception:
            return "calendar_unavailable"
        return self.session_phase(local.time())

    @staticmethod
    def session_phase(moment: time) -> str:
        if moment < time(9, 15):
            return "pre_open"
        if time(9, 15) <= moment < time(9, 25):
            return "opening_auction"
        if time(9, 25) <= moment < time(9, 30):
            return "pre_open"
        if time(9, 30) <= moment < time(11, 30):
            return "open"
        if time(11, 30) <= moment < time(13):
            return "lunch_break"
        if time(13) <= moment < time(14, 57):
            return "open"
        if time(14, 57) <= moment < time(15):
            return "closing_auction"
        return "closed"

    @staticmethod
    def _status_for_session_time(moment: time) -> str:
        # Compatibility alias retained for callers and historical tests.
        return CnTradingCalendar.session_phase(moment)


class MarketObservation(BaseModel):
    asset_id: str
    market_status: str
    provider: str = PROVIDER
    provider_status: str = "unavailable"
    latest_price: float | None = None
    latest_price_at: datetime | None = None
    last_close: float | None = None
    quote_delay_seconds: int | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    stale: bool = True
    degraded_reasons: list[str] = Field(default_factory=list)
    outcomes: list[dict] = Field(default_factory=list)


class MarketObservationService:
    def __init__(self, uow: SQLiteUnitOfWork, *, provider: QuoteProvider | None = None, calendar: CnTradingCalendar | None = None, clock=None) -> None:
        self.uow, self.provider, self.calendar = uow, provider or AkshareEastMoneyQuoteProvider(), calendar or CnTradingCalendar()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def get(self, asset_id: str) -> MarketObservation:
        asset = self._asset(asset_id)
        now = self.clock()
        quote = self.uow.market_observations.latest_quote(asset_id)
        failures = self.uow.market_observations.consecutive_failures(asset_id, PROVIDER)
        status = self.calendar.status(now) if self._is_cn_asset(asset) else "unsupported_market"
        daily_points = sorted([p for s in self.uow.price_series.list_for_asset(asset_id) if s.interval == "1d" and s.series_role in {None, "asset"} for p in s.points], key=lambda p: p.timestamp)
        last_close = daily_points[-1].close if daily_points else None
        stale = quote is None or now - quote.fetched_at > timedelta(minutes=10)
        outcomes = []
        for item in self.uow.paper_observations.list_for_asset(asset_id):
            live_price = quote.last_price if quote else item.latest_price or last_close
            live_return = None if live_price is None or item.prediction_price in {None, 0} else live_price / item.prediction_price - 1
            outcomes.append({"run_id": str(item.analysis_run_id), "predicted_risk": item.predicted_risk, "prediction_price": item.prediction_price, "latest_price": live_price, "cumulative_return": live_return, "realized_max_drawdown": item.realized_max_drawdown, "observed_trading_days": item.observed_trading_days, "remaining_trading_days": max(0, 60 - item.observed_trading_days), "outcome": item.outcome, "judge_verdict": self._judge(item.analysis_run_id), "evaluation_due_at": item.evaluation_due_at, "milestones": {key: value.model_dump(mode="json") for key, value in item.milestones.items()}, "error_category": item.error_category, "abstained": item.abstained})
        reasons = (["provider_degraded"] if failures else []) + (["quote_stale"] if stale and quote else [])
        return MarketObservation(asset_id=asset_id, market_status=status, provider_status="degraded" if reasons else "available" if quote else "unavailable", latest_price=quote.last_price if quote else last_close, latest_price_at=quote.quote_at if quote else daily_points[-1].timestamp if daily_points else None, last_close=last_close, quote_delay_seconds=None if quote is None else max(0, int((quote.fetched_at - quote.quote_at).total_seconds())), last_success_at=None if quote is None else quote.fetched_at, consecutive_failures=failures, stale=stale, degraded_reasons=reasons, outcomes=outcomes)

    def refresh(self, asset_id: str, *, user: User | None = None) -> MarketObservation:
        del user
        asset = self._asset(asset_id)
        now = self.clock()
        status = self.calendar.status(now)
        if not self._is_cn_asset(asset):
            return self.get(asset_id)
        if status == "closed":
            self._solidify_daily_close(asset, now)
            return self.get(asset_id)
        if status not in {"open", "opening_auction", "closing_auction"}:
            return self.get(asset_id)
        latest = self.uow.market_observations.latest_quote(asset_id)
        if latest and now - latest.fetched_at < timedelta(minutes=5):
            return self.get(asset_id)
        try:
            price, previous_close, quote_at, payload = self.provider.fetch(asset, now)
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
            self.uow.market_observations.add_quote(MarketQuote(asset_id=asset.id, provider=PROVIDER, quote_at=quote_at, fetched_at=now, last_price=price, previous_close=previous_close, payload_hash=hashlib.sha256(raw.encode()).hexdigest()), payload)
            self._attempt(asset, "succeeded", now, provider=PROVIDER)
            PaperValidationWorker(self.uow).evaluate_observations(now)
        except Exception as exc:
            self._attempt(asset, "failed", now, provider=PROVIDER, error_code=type(exc).__name__, error_message=str(exc))
        return self.get(asset_id)

    def _solidify_daily_close(self, asset: Asset, now: datetime) -> None:
        local_date = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        latest_attempt = self.uow.market_observations.latest_attempt(str(asset.id), DAILY_PROVIDER)
        if latest_attempt and latest_attempt.attempted_at.astimezone(ZoneInfo("Asia/Shanghai")).date() == local_date:
            return
        daily_points = [point for series in self.uow.price_series.list_for_asset(str(asset.id)) if series.interval == "1d" and series.series_role == "asset" for point in series.points]
        if any(point.timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date() == local_date for point in daily_points):
            return
        try:
            open_price, high, low, close, volume, close_at, payload = self.provider.fetch_daily_close(asset, now)
            provenance = Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name=DAILY_PROVIDER, observed_at=close_at)
            point = PricePoint(asset_id=asset.id, timestamp=close_at, open=open_price, high=high, low=low, close=close, volume=volume, provenance=provenance)
            self.uow.price_series.add(PriceSeries(asset_id=asset.id, interval="1d", points=[point], provenance=provenance))
            self._attempt(asset, "succeeded", now, provider=DAILY_PROVIDER)
            PaperValidationWorker(self.uow).evaluate_observations(now)
        except Exception as exc:
            self._attempt(asset, "failed", now, provider=DAILY_PROVIDER, error_code=type(exc).__name__, error_message=str(exc))

    def _attempt(self, asset: Asset, state: str, now: datetime, *, provider: str, **errors) -> None:
        self.uow.market_observations.add_attempt(MarketQuoteAttempt(asset_id=asset.id, provider=provider, state=state, attempted_at=now, **errors))

    def _asset(self, asset_id: str) -> Asset:
        asset = self.uow.assets.get(asset_id)
        if asset is None: raise ValueError("Asset not found")
        return asset

    def _judge(self, run_id) -> str | None:
        items = self.uow.judge_scores.list_for_run(str(run_id))
        return None if not items else items[0].verdict.value

    @staticmethod
    def _is_cn_asset(asset: Asset) -> bool:
        return asset.ticker.upper().endswith((".SH", ".SZ"))


def _optional_float(value) -> float | None:
    try: return float(value)
    except (TypeError, ValueError): return None
