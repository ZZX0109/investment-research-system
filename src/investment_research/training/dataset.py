from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from investment_research.domain.decision_context import (
    DecisionContextType,
    build_market_decision_context,
)
from investment_research.training.data_quality import (
    detect_future_leakage,
)
from investment_research.feature_contract import (
    asof_aligned_values,
    asof_aligned_optional_values,
    build_structured_event_features,
    count_recent_events,
    realized_volatility,
    window_return,
    zscore,
)
from investment_research.training.labels import (
    TradeableLabelPolicy,
    build_label_generation_context,
    generate_multitask_labels,
    generate_tradeable_labels,
)
from investment_research.domain.pit import EventCoverageStatus
from investment_research.training.models import (
    CanonicalInstrument,
    Market,
    PointInTimeEvent,
    PreparedPriceBar,
    TrainingSample,
)
from investment_research.training.research_feature_coverage import (
    core_feature_coverage,
)


_DEFAULT_CALENDAR = {
    Market.CN: "XSHG",
    Market.US: "XNYS",
    Market.HK: "XHKG",
    Market.JP: "XTKS",
}


class TrainingDatasetBuilder:
    def __init__(self, *, feature_version: str, data_version: str) -> None:
        self.feature_version = feature_version
        self.data_version = data_version

    def build_samples(
        self,
        *,
        instrument: CanonicalInstrument,
        price_bars: list[PreparedPriceBar],
        benchmark_bars: list[PreparedPriceBar] | None = None,
        sector_reference_bars: list[PreparedPriceBar] | None = None,
        style_reference_bars: list[PreparedPriceBar] | None = None,
        events: list[PointInTimeEvent] | None = None,
        decision_context: DecisionContextType
        | str = DecisionContextType.CLOSE_CONFIRMED,
        event_coverage_status: str = "unknown",
    ) -> list[TrainingSample]:
        samples: list[TrainingSample] = []
        ordered = sorted(price_bars, key=lambda item: item.trade_date)
        events = sorted(events or [], key=_event_available_at)
        benchmark_bars = benchmark_bars or []
        sector_reference_bars = sector_reference_bars or []
        style_reference_bars = style_reference_bars or []
        benchmark_returns = _asof_reference_returns(ordered, benchmark_bars)
        sector_returns = _asof_reference_returns(ordered, sector_reference_bars)
        style_returns = _asof_reference_returns(ordered, style_reference_bars)
        label_context = build_label_generation_context(
            price_bars=ordered,
            benchmark_bars=benchmark_bars,
            industry_reference_bars=sector_reference_bars,
            events=events,
        )
        event_cursor = 0
        recent_events: deque[PointInTimeEvent] = deque()
        trading_dates = [item.trade_date for item in ordered]
        next_trading_dates = {
            current: following for current, following in zip(trading_dates, trading_dates[1:])
        }

        for index, bar in enumerate(ordered):
            if index + 1 < 21:
                continue
            # Feature V2 uses at most 20 sessions (60 retained as headroom for
            # compatible feature contracts).  Avoid copying and rescanning the
            # entire listing history for every decision date.
            prior_bars = ordered[max(0, index - 59) : index + 1]
            context = build_market_decision_context(
                bar.trade_date,
                decision_context,
                calendar_code=(
                    instrument.exchange
                    or (
                        _DEFAULT_CALENDAR[instrument.market]
                        if bar.calendar_code == "XNYS"
                        and instrument.market != Market.US
                        else bar.calendar_code
                    )
                ),
                trading_dates=trading_dates,
                next_trading_date=next_trading_dates.get(bar.trade_date),
            )
            feature_cutoff = context.decision_time
            while (
                event_cursor < len(events)
                and _event_available_at(events[event_cursor]) <= feature_cutoff
            ):
                event = events[event_cursor]
                recent_events.append(event)
                event_cursor += 1
            oldest_relevant = bar.trade_date - timedelta(days=30)
            while (
                recent_events
                and _event_available_at(recent_events[0]).date() < oldest_relevant
            ):
                recent_events.popleft()
            feature_events = list(recent_events)
            event_count_1d = _window_event_count(feature_events, feature_cutoff, 1)
            event_count_7d = _window_event_count(feature_events, feature_cutoff, 7)
            event_count_30d = len(feature_events)
            visible_provider_names = {
                event.provider or event.source_name for event in feature_events
            }
            visible_semantic_count = sum(
                int(_event_has_semantics(event)) for event in feature_events
            )
            leakage_issues = detect_future_leakage(
                bars=[bar], events=feature_events, as_of=feature_cutoff
            )
            if leakage_issues:
                continue

            features, missing_features = self._build_features(
                prior_bars=prior_bars,
                benchmark_return=benchmark_returns[index],
                sector_reference_return=sector_returns[index],
                style_reference_return=style_returns[index],
                visible_events=feature_events,
                benchmark_symbol=instrument.benchmark_symbol,
                sector_reference_symbol=instrument.sector_reference_symbol,
                style_reference_symbol=instrument.style_reference_symbol,
                market=instrument.market,
            )
            labels = generate_multitask_labels(
                symbol=instrument.symbol,
                as_of_date=bar.trade_date,
                price_bars=ordered,
                benchmark_bars=benchmark_bars,
                industry_reference_bars=sector_reference_bars,
                events=events,
                context=label_context,
            )
            policy = (
                TradeableLabelPolicy(
                    version="cn-direction-volatility-label-v2",
                    minimum_cost_boundary=0.0,
                )
                if self.feature_version.endswith("features-v3")
                else None
            )
            tradeable_labels = generate_tradeable_labels(
                symbol=instrument.symbol,
                as_of_date=bar.trade_date,
                price_bars=ordered,
                context=label_context,
                policy=policy,
                instrument_is_etf=instrument.instrument_type.value == "etf",
            )
            tradeable_owned = {
                "future_return_1d",
                "future_return_5d",
                "future_return_20d",
                "future_return_20d_from_open",
                "future_max_drawdown_20d",
                "future_max_drawdown_60d",
                "future_max_drawdown_120d",
                "entry_trade_date",
                "entry_delay_sessions",
                "label_available",
                "label_unavailable_reason",
                "maximum_adverse_excursion_20d",
                "maximum_favorable_excursion_20d",
                "encountered_suspension_20d",
                "direction_1d",
                "direction_5d",
                "direction_20d",
                "label_start",
                "label_end",
                "touched_limit_up_20d",
                "touched_limit_down_20d",
            }
            labels = labels.model_copy(
                update={
                    name: getattr(tradeable_labels, name) for name in tradeable_owned
                }
            )
            resolved_event_status = _resolve_event_coverage_status(
                event_coverage_status, event_count_30d
            )
            if not resolved_event_status.permits_zero_features:
                event_feature_names = [
                    name for name in features if _is_event_feature(name)
                ]
                for name in event_feature_names:
                    features.pop(name, None)
                missing_features = sorted(
                    set([*missing_features, *event_feature_names])
                )
            samples.append(
                TrainingSample(
                    symbol=instrument.symbol,
                    market=instrument.market,
                    instrument_type=instrument.instrument_type,
                    coverage_group=instrument.coverage_group,
                    industry_key=instrument.industry_key,
                    benchmark_symbol=instrument.benchmark_symbol,
                    sector_reference_symbol=instrument.sector_reference_symbol,
                    style_reference_symbol=instrument.style_reference_symbol,
                    as_of_date=bar.trade_date,
                    as_of_time=bar.published_at,
                    feature_cutoff=feature_cutoff,
                    decision_context=context.context_type.value,
                    prediction_start_date=context.prediction_start_date,
                    feature_version=self.feature_version,
                    data_version=self.data_version,
                    features=features,
                    feature_coverage=_feature_coverage(features, missing_features),
                    core_feature_coverage=core_feature_coverage(features, missing_features),
                    missing_features=missing_features,
                    labels=labels,
                    point_in_time_event_count=event_count_30d,
                    event_source_available=resolved_event_status.permits_zero_features,
                    event_coverage_status=resolved_event_status.value,
                    event_count_1d=event_count_1d,
                    event_count_7d=event_count_7d,
                    event_count_30d=event_count_30d,
                    event_provider_count=len(visible_provider_names),
                    event_semantic_coverage=(
                        visible_semantic_count / event_count_30d
                        if event_count_30d
                        else 0.0
                    ),
                    data_issues=[],
                    provider=bar.provider,
                    published_at=bar.published_at,
                    as_of=feature_cutoff,
                    payload_ref=bar.payload_ref,
                    source_url=bar.source_url,
                    raw_hash=bar.raw_hash,
                    normalized_hash=bar.normalized_hash,
                )
            )
        return samples

    def _build_features(
        self,
        *,
        prior_bars: list[PreparedPriceBar],
        benchmark_return: float | None,
        sector_reference_return: float | None,
        style_reference_return: float | None,
        visible_events: list[PointInTimeEvent],
        benchmark_symbol: str | None,
        sector_reference_symbol: str | None,
        style_reference_symbol: str | None,
        market: Market,
    ) -> tuple[dict[str, float], list[str]]:
        closes = [bar.close_normalized for bar in prior_bars]
        volumes = [bar.volume for bar in prior_bars]
        latest = prior_bars[-1]
        trailing_5 = closes[-5:]
        trailing_20 = closes[-20:]
        event_counts = count_recent_events(visible_events, latest.trade_date)
        event_features = build_structured_event_features(
            visible_events, latest.trade_date
        )

        missing_features: list[str] = []
        features = {
            "ret_5d": window_return(trailing_5),
            "ret_20d": window_return(trailing_20),
            "vol_5d": realized_volatility(trailing_5),
            "vol_20d": realized_volatility(trailing_20),
            "volume_z_20d": zscore(volumes[-1], volumes[-20:]),
            "halted_flag": 1.0 if latest.is_halted or latest.is_suspended else 0.0,
            "news_count_7d": float(event_counts["news_count_7d"]),
            "filing_count_30d": float(event_counts["filing_count_30d"]),
            "earnings_count_30d": float(event_counts["earnings_count_30d"]),
            "market_cn_flag": 1.0 if market == Market.CN else 0.0,
            "market_us_flag": 1.0 if market == Market.US else 0.0,
            "market_hk_flag": 1.0 if market == Market.HK else 0.0,
            "market_jp_flag": 1.0 if market == Market.JP else 0.0,
        }
        features.update(event_features)
        if (
            self.feature_version in {"cn-research-feature-v3", "investment-risk-features-v3"}
            or self.feature_version.endswith(("features-v2", "features-v3"))
        ):
            self._add_v2_features(
                features,
                missing_features,
                prior_bars,
                visible_events,
                sector_reference_return,
            )
        if benchmark_symbol and benchmark_return is not None:
            features["benchmark_ret_20d"] = benchmark_return
            features["relative_strength_20d"] = features["ret_20d"] - benchmark_return
        else:
            features["benchmark_ret_20d"] = 0.0
            features["relative_strength_20d"] = 0.0
            missing_features.extend(["benchmark_ret_20d", "relative_strength_20d"])
        if sector_reference_symbol and sector_reference_return is not None:
            features["sector_ret_20d"] = sector_reference_return
            features["sector_relative_strength_20d"] = (
                features["ret_20d"] - sector_reference_return
            )
        else:
            features["sector_ret_20d"] = 0.0
            features["sector_relative_strength_20d"] = 0.0
            missing_features.extend(["sector_ret_20d", "sector_relative_strength_20d"])
        if style_reference_symbol and style_reference_return is not None:
            features["style_ret_20d"] = style_reference_return
            features["style_relative_strength_20d"] = (
                features["ret_20d"] - style_reference_return
            )
        else:
            features["style_ret_20d"] = 0.0
            features["style_relative_strength_20d"] = 0.0
            missing_features.extend(["style_ret_20d", "style_relative_strength_20d"])
        return features, sorted(set(missing_features))

    @staticmethod
    def _add_v2_features(
        features, missing_features, prior_bars, visible_events, sector_reference_return
    ) -> None:
        latest = prior_bars[-1]
        turnover = [
            bar.turnover_rate
            for bar in prior_bars[-20:]
            if bar.turnover_rate is not None
        ]
        if latest.turnover_rate is not None and turnover:
            features["turnover_percentile_20d"] = sum(
                value <= latest.turnover_rate for value in turnover
            ) / len(turnover)
        else:
            missing_features.append("turnover_percentile_20d")
        amounts = [
            bar.amount
            for bar in prior_bars[-20:]
            if bar.amount is not None and bar.amount > 0
        ]
        if latest.amount is not None and amounts:
            features["relative_liquidity_20d"] = latest.amount / (
                sum(amounts) / len(amounts)
            )
        else:
            missing_features.append("relative_liquidity_20d")
        if latest.market_breadth_5d is not None:
            features["market_breadth_5d"] = latest.market_breadth_5d
        else:
            missing_features.append("market_breadth_5d")
        if sector_reference_return is not None:
            features["industry_strength_20d"] = (
                features["ret_20d"] - sector_reference_return
            )
        else:
            missing_features.append("industry_strength_20d")
        features["limit_up_flag"] = 1.0 if latest.is_limit_up else 0.0
        features["limit_down_flag"] = 1.0 if latest.is_limit_down else 0.0
        margin = [
            bar.margin_financing_balance
            for bar in prior_bars[-6:]
            if bar.margin_financing_balance is not None
        ]
        if len(margin) >= 2 and margin[0] > 0:
            features["margin_financing_change_5d"] = margin[-1] / margin[0] - 1.0
        else:
            missing_features.append("margin_financing_change_5d")
        features["announcement_regulatory_count_30d"] = float(
            sum(
                event.event_type.value in {"regulation", "policy", "litigation"}
                for event in visible_events
            )
        )
        features["announcement_shareholder_action_count_30d"] = float(
            sum(
                (event.filing_subtype or "").lower()
                in {"buyback", "shareholder_change", "insider_sale", "pledge"}
                for event in visible_events
            )
        )


def _feature_coverage(features: dict[str, float], missing_features: list[str]) -> float:
    names = set(features) | set(missing_features)
    if not names:
        return 0.0
    return max(0.0, 1.0 - (len(set(missing_features)) / len(names)))


def _event_available_at(event: PointInTimeEvent) -> datetime:
    return event.available_at or event.published_at


def _resolve_event_coverage_status(value: str, event_count: int) -> EventCoverageStatus:
    if value in {"complete", "unknown"}:
        if value == "unknown":
            return (
                EventCoverageStatus.EVENTS_PRESENT
                if event_count
                else EventCoverageStatus.UNSUPPORTED
            )
        return (
            EventCoverageStatus.EVENTS_PRESENT
            if event_count
            else EventCoverageStatus.CONFIRMED_NONE
        )
    status = EventCoverageStatus(value)
    if status == EventCoverageStatus.CONFIRMED_NONE and event_count:
        return EventCoverageStatus.EVENTS_PRESENT
    return status


def _is_event_feature(name: str) -> bool:
    return any(
        marker in name
        for marker in ("event", "news", "filing", "earnings", "guidance", "surprise")
    )


def _window_event_count(
    events: list[PointInTimeEvent], cutoff: datetime, days: int
) -> int:
    lower = cutoff - timedelta(days=days)
    return sum(1 for event in events if lower < _event_available_at(event) <= cutoff)


def _asof_reference_closes(
    target_bars: list[PreparedPriceBar], reference_bars: list[PreparedPriceBar]
) -> list[float]:
    """Align target days to the latest already-published reference close."""
    return asof_aligned_values(
        [(bar.trade_date, bar.available_at or bar.published_at) for bar in target_bars],
        [
            (bar.trade_date, bar.available_at or bar.published_at, bar.close_normalized)
            for bar in reference_bars
        ],
    )


def _asof_reference_returns(
    target_bars: list[PreparedPriceBar], reference_bars: list[PreparedPriceBar]
) -> list[float | None]:
    if not reference_bars:
        return [None] * len(target_bars)
    aligned = asof_aligned_optional_values(
        [(bar.trade_date, bar.available_at or bar.published_at) for bar in target_bars],
        [
            (bar.trade_date, bar.available_at or bar.published_at, bar.close_normalized)
            for bar in reference_bars
        ],
    )
    returns: list[float | None] = []
    history: list[float] = []
    for value in aligned:
        if value is None:
            returns.append(None)
            continue
        history.append(value)
        returns.append(window_return(history[-20:]) if len(history) >= 20 else None)
    return returns


def _event_semantic_coverage(events: list[PointInTimeEvent]) -> float:
    if not events:
        return 0.0
    resolved = sum(
        1
        for event in events
        if event.event_direction.value != "unknown"
        or event.surprise_bucket.value != "unknown"
        or event.guidance_bucket.value != "unknown"
        or event.filing_subtype
    )
    return resolved / len(events)


def _event_has_semantics(event: PointInTimeEvent) -> bool:
    return bool(
        event.event_direction.value != "unknown"
        or event.surprise_bucket.value != "unknown"
        or event.guidance_bucket.value != "unknown"
        or event.filing_subtype
    )
