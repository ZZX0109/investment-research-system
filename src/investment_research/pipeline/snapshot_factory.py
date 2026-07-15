from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from investment_research.domain.base import utc_now
from investment_research.domain.decision_context import (
    DecisionContext,
    DecisionContextType,
    EXCHANGE_SESSIONS,
    build_market_decision_context,
)
from investment_research.domain.enums import DataSourceType
from investment_research.domain.models import Asset, Evidence, PriceSeries
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.pipeline.source_meta import SourceLayerMetadata
from investment_research.service.analysis_intake import AnalysisIntakeResolution
from investment_research.service.data_lifecycle import AnalysisLifecycleService
from investment_research.service.data_mode import DataModePolicyService


@dataclass(frozen=True)
class SnapshotSourceMix:
    data_modes: list[str]
    source_types: list[str]
    synthetic_count: int
    real_count: int

    @property
    def total(self) -> int:
        return max(1, len(self.source_types))

    @property
    def synthetic_ratio(self) -> float:
        return self.synthetic_count / self.total

    @property
    def real_ratio(self) -> float:
        return self.real_count / self.total


class AnalysisSnapshotFactory:
    """Freeze selected inputs and source metadata into a reproducible run snapshot."""

    def __init__(
        self,
        *,
        mode_policy: DataModePolicyService | None = None,
        lifecycle: AnalysisLifecycleService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.mode_policy = mode_policy or DataModePolicyService()
        self.lifecycle = lifecycle or AnalysisLifecycleService()
        self.clock = clock or utc_now

    def build_snapshot(
        self,
        asset: Asset,
        resolution: AnalysisIntakeResolution,
        *,
        decision_context: DecisionContext | None = None,
    ) -> AnalysisSnapshot:
        captured_at = self.clock()
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("AnalysisSnapshotFactory clock must return an aware datetime")
        captured_at = captured_at.astimezone(timezone.utc)
        price_series = resolution.price_series
        raw_evidence = resolution.evidence
        asset_series = [
            series for series in price_series if series.series_role == "asset"
        ]
        latest_series = asset_series[0] if asset_series else None
        latest_point = (
            latest_series.points[-1] if latest_series and latest_series.points else None
        )
        calendar_code = _asset_calendar_code(asset)
        local_timezone = ZoneInfo(EXCHANGE_SESSIONS[calendar_code].timezone)
        trade_date = (
            (
                latest_point.timestamp
                if latest_point is not None
                else asset.provenance.observed_at
            )
            .astimezone(local_timezone)
            .date()
        )
        context = decision_context or build_market_decision_context(
            trade_date, DecisionContextType.CLOSE_CONFIRMED, calendar_code=calendar_code
        )
        if (
            latest_point is None
            and context.context_type == DecisionContextType.CLOSE_CONFIRMED
            and context.decision_time > captured_at
        ):
            previous = trade_date - timedelta(days=1)
            while previous.weekday() >= 5:
                previous -= timedelta(days=1)
            context = build_market_decision_context(
                previous,
                DecisionContextType.CLOSE_CONFIRMED,
                calendar_code=calendar_code,
            )
        evidence = [
            item
            for item in raw_evidence
            if _evidence_available_at(item) <= context.decision_time
        ]
        source_mix = self._source_mix(
            asset=asset, price_series=price_series, evidence=evidence
        )
        data_mode = self.mode_policy.ensure_uniform_mode(
            data_modes=[
                asset.provenance.data_mode,
                *[series.provenance.data_mode for series in price_series],
                *[item.provenance.data_mode for item in raw_evidence],
            ],
            label="Analysis snapshot",
        )
        as_of = (
            latest_point.timestamp
            if latest_point is not None
            else context.decision_time
        )
        overrides = list(dict.fromkeys(resolution.fallback_reasons))
        provider = (
            f"{resolution.price_selection.provider_name}@{resolution.price_selection.provider_version}"
            f" | {resolution.evidence_selection.provider_name}@{resolution.evidence_selection.provider_version}"
        )
        lifecycle = self.lifecycle.assess(
            data_mode=data_mode,
            price_series=price_series,
            evidence=evidence,
        )
        source_meta = SourceLayerMetadata(
            mode=data_mode.value,
            provider=provider,
            as_of=as_of,
            overrides=overrides,
            synthetic_ratio=source_mix.synthetic_ratio,
        )
        feature_built_at = captured_at
        snapshot_payload = {
            "asset_id": str(asset.id),
            "decision_context": context.context_type.value,
            "decision_time": context.decision_time.isoformat(),
            "price_series_ids": [str(item.id) for item in price_series],
            "evidence_ids": [str(item.id) for item in evidence],
            "providers": provider,
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        market_snapshot_id = str(uuid5(NAMESPACE_URL, snapshot_hash))
        return AnalysisSnapshot(
            market_snapshot_id=market_snapshot_id,
            market_snapshot_hash=snapshot_hash,
            decision_context=context.context_type.value,
            decision_time=context.decision_time,
            prediction_start_date=datetime.combine(
                context.prediction_start_date,
                datetime.min.time(),
                context.decision_time.tzinfo,
            ),
            feature_built_at=feature_built_at,
            asset_id=str(asset.id),
            asset_snapshot=asset,
            captured_at=captured_at,
            mode=data_mode.value,
            provider=provider,
            as_of=as_of,
            overrides=overrides,
            synthetic_ratio=source_mix.synthetic_ratio,
            data_modes=sorted(set(source_mix.data_modes)),
            source_types=sorted(set(source_mix.source_types)),
            intake_strategy="persisted_repository_with_policy_fallback",
            price_provider_name=resolution.price_selection.provider_name,
            price_provider_version=resolution.price_selection.provider_version,
            price_provider_status=resolution.price_selection.status,
            evidence_provider_name=resolution.evidence_selection.provider_name,
            evidence_provider_version=resolution.evidence_selection.provider_version,
            evidence_provider_status=resolution.evidence_selection.status,
            event_coverage_status=(
                "events_present"
                if resolution.evidence_selection.status == "real_fresh" and evidence
                else "confirmed_none"
                if resolution.evidence_selection.status == "real_fresh"
                else "partial"
                if evidence
                else "fetch_failed"
            ),
            fallback_reasons=resolution.fallback_reasons,
            latest_close=None if latest_point is None else latest_point.close,
            latest_price_timestamp=None
            if latest_point is None
            else latest_point.timestamp,
            price_freshness_status=lifecycle.price.status,
            evidence_freshness_status=lifecycle.evidence.status,
            refresh_recommendation=lifecycle.refresh_recommendation,
            stale_reasons=lifecycle.stale_reasons,
            evidence_citation_ids=lifecycle.evidence_citation_ids,
            evidence_ids=[str(item.id) for item in evidence],
            price_series_snapshot=price_series,
            evidence_snapshot=evidence,
            synthetic_share=source_mix.synthetic_ratio,
            real_share=source_mix.real_ratio,
            source_meta=source_meta,
        )

    def _source_mix(
        self,
        *,
        asset: Asset,
        price_series: list[PriceSeries],
        evidence: list[Evidence],
    ) -> SnapshotSourceMix:
        data_modes = [asset.provenance.data_mode.value]
        source_types = [asset.provenance.source_type.value]
        synthetic_count = (
            1 if asset.provenance.source_type == DataSourceType.SYNTHETIC else 0
        )
        real_count = 1 if asset.provenance.source_type == DataSourceType.REAL else 0

        for series in price_series:
            data_modes.append(series.provenance.data_mode.value)
            source_types.append(series.provenance.source_type.value)
            synthetic_count += (
                1 if series.provenance.source_type == DataSourceType.SYNTHETIC else 0
            )
            real_count += (
                1 if series.provenance.source_type == DataSourceType.REAL else 0
            )

        for item in evidence:
            data_modes.append(item.provenance.data_mode.value)
            source_types.append(item.provenance.source_type.value)
            synthetic_count += (
                1 if item.provenance.source_type == DataSourceType.SYNTHETIC else 0
            )
            real_count += 1 if item.provenance.source_type == DataSourceType.REAL else 0

        return SnapshotSourceMix(
            data_modes=data_modes,
            source_types=source_types,
            synthetic_count=synthetic_count,
            real_count=real_count,
        )


def _evidence_available_at(evidence: Evidence):
    return evidence.published_at or evidence.collected_at


def _asset_calendar_code(asset: Asset) -> str:
    exchange = (asset.exchange or "").upper()
    if exchange in {"XSHG", "XSHE", "XBSE", "XNYS", "XNAS", "XHKG", "XTKS"}:
        return exchange
    ticker = asset.ticker.upper()
    if ticker.endswith(".HK"):
        return "XHKG"
    if ticker.endswith(".T"):
        return "XTKS"
    if ticker.endswith(".SH"):
        return "XSHG"
    if ticker.endswith(".SZ"):
        return "XSHE"
    if ticker.endswith(".BJ"):
        return "XBSE"
    return "XNYS"
