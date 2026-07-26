"""Reproducible research cohorts for the zero-budget A-share workflow."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median

from pydantic import BaseModel, Field

from investment_research.domain.data_tier import DataTier, RESEARCH_TIER_REASONS
from investment_research.training.cn_free_providers import ETF_RESEARCH_SYMBOLS
from investment_research.training.models import PreparedPriceBar


class ResearchCohortMember(BaseModel):
    symbol: str
    cohort: str
    as_of: date
    observed_sessions: int
    training_eligible_sessions: int = 0
    minimum_training_sessions: int = 960
    coverage_ratio: float = Field(ge=0, le=1)
    median_amount_120d: float = Field(ge=0)


class ResearchCohortManifest(BaseModel):
    schema_version: str = "cn-research-cohort-v1"
    data_tier: DataTier = DataTier.RESEARCH_PIT
    cohort: str
    as_of: date
    members: list[ResearchCohortMember]
    excluded: dict[str, str] = Field(default_factory=dict)
    minimum_required_members: int = 80
    eligible_candidate_count: int = 0
    selection_limit: int | None = None
    cohort_version: str = ""
    content_hash: str = ""
    blocking_reasons: list[str] = Field(default_factory=lambda: list(RESEARCH_TIER_REASONS))


def build_cn_equity_core(
    bars: list[PreparedPriceBar], *, as_of: date, max_symbols: int | None = None,
    lookback_sessions: int = 120, minimum_history_sessions: int = 756,
    minimum_training_sessions: int | None = None,
    minimum_coverage_ratio: float = 0.98, minimum_median_amount: float = 100_000_000,
    minimum_required_members: int = 80,
) -> ResearchCohortManifest:
    minimum_training_sessions = minimum_training_sessions or minimum_history_sessions
    by_symbol: dict[str, list[PreparedPriceBar]] = defaultdict(list)
    for bar in bars:
        if bar.trade_date <= as_of and bar.symbol not in ETF_RESEARCH_SYMBOLS:
            by_symbol[bar.symbol].append(bar)
    ranked: list[ResearchCohortMember] = []
    excluded: dict[str, str] = {}
    for symbol, values in by_symbol.items():
        ordered = sorted(values, key=lambda item: item.trade_date)
        if len(ordered) < minimum_history_sessions:
            excluded[symbol] = "listed_history_below_756_sessions"
            continue
        if len(ordered) < minimum_training_sessions:
            excluded[symbol] = f"training_history_below_{minimum_training_sessions}_sessions"
            continue
        window = ordered[-lookback_sessions:]
        coverage = len({item.trade_date for item in window}) / lookback_sessions
        if coverage < minimum_coverage_ratio:
            excluded[symbol] = "recent_120d_coverage_below_98pct"
            continue
        if any(not item.is_tradeable for item in window[-1:]):
            excluded[symbol] = "currently_suspended_or_untradeable"
            continue
        amounts = [float(item.amount or 0.0) for item in window]
        median_amount = median(amounts)
        if median_amount < minimum_median_amount:
            excluded[symbol] = "median_amount_120d_below_100m"
            continue
        ranked.append(ResearchCohortMember(
            symbol=symbol, cohort="cn_equity_core", as_of=as_of,
            observed_sessions=len(ordered), training_eligible_sessions=len(ordered),
            minimum_training_sessions=minimum_training_sessions,
            coverage_ratio=min(1.0, coverage),
            median_amount_120d=median_amount,
        ))
    ranked.sort(key=lambda item: (-item.median_amount_120d, item.symbol))
    selected = ranked if max_symbols is None else ranked[:max_symbols]
    if max_symbols is not None:
        for item in ranked[max_symbols:]:
            excluded[item.symbol] = f"liquidity_rank_below_top_{max_symbols}"
    import hashlib, json
    payload = {
        "as_of": as_of.isoformat(), "members": [item.symbol for item in selected],
        "quarter": f"{as_of.year}Q{(as_of.month - 1) // 3 + 1}",
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return ResearchCohortManifest(
        cohort="cn_equity_core", as_of=as_of, members=selected, excluded=excluded,
        minimum_required_members=minimum_required_members,
        eligible_candidate_count=len(ranked), selection_limit=max_symbols,
        cohort_version=f"cn-equity-core-{payload['quarter']}-{digest[:12]}",
        content_hash=digest,
        blocking_reasons=[*RESEARCH_TIER_REASONS, *(["eligible_equity_count_below_80"] if len(selected) < minimum_required_members else [])],
    )


def build_cn_etf_benchmark(
    bars: list[PreparedPriceBar], *, as_of: date, minimum_training_sessions: int = 1,
) -> ResearchCohortManifest:
    observed: dict[str, list[PreparedPriceBar]] = defaultdict(list)
    for bar in bars:
        if bar.trade_date <= as_of and bar.symbol in ETF_RESEARCH_SYMBOLS:
            observed[bar.symbol].append(bar)
    members = [
        ResearchCohortMember(
            symbol=symbol, cohort="cn_etf_benchmark", as_of=as_of,
            observed_sessions=len(values), training_eligible_sessions=len(values),
            minimum_training_sessions=minimum_training_sessions, coverage_ratio=1.0,
            median_amount_120d=median([float(item.amount or 0.0) for item in values[-120:]]),
        )
        for symbol in ETF_RESEARCH_SYMBOLS
        if (values := sorted(observed.get(symbol, []), key=lambda item: item.trade_date))
        and len(values) >= minimum_training_sessions
    ]
    excluded = {
        symbol: (
            "history_missing" if not observed.get(symbol)
            else f"training_history_below_{minimum_training_sessions}_sessions"
        )
        for symbol in ETF_RESEARCH_SYMBOLS
        if len(observed.get(symbol, [])) < minimum_training_sessions
    }
    import hashlib, json
    digest = hashlib.sha256(json.dumps([item.symbol for item in members], sort_keys=True).encode()).hexdigest()
    return ResearchCohortManifest(
        cohort="cn_etf_benchmark", as_of=as_of, members=members, excluded=excluded,
        minimum_required_members=5,
        eligible_candidate_count=len(members), selection_limit=5,
        cohort_version=f"cn-etf-benchmark-{digest[:12]}", content_hash=digest,
        blocking_reasons=[*RESEARCH_TIER_REASONS, *(["required_etf_missing"] if len(members) != 5 else [])],
    )
