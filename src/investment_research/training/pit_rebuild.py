from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from investment_research.domain.pit import (
    CorporateActionRevision,
    EventCoverageStatus,
    HistoricalUniverseMembership,
    PITDataQualityStatus,
    PITFeatureRecord,
    PITSampleRecord,
    StandardEventRevision,
)
from investment_research.domain.trusted_market import MarketSnapshot, RawDataBatch
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.models import CanonicalInstrument, PointInTimeEvent, PreparedPriceBar, TrainingSample
from investment_research.training.pit_pipeline import PITDatasetPublisher


@dataclass(frozen=True)
class PITRawPayload:
    """Provider response bytes to be persisted before any normalization."""

    provider: str
    request_id: str
    dataset: str
    payload: bytes
    schema_version: str
    available_at: datetime
    symbol: str | None = None
    interval: str | None = None
    source_time: datetime | None = None
    exchange_time: datetime | None = None
    received_at: datetime | None = None
    market_session: str | None = None


FORMAL_TASKS = ("drawdown_20d", "direction_1d", "direction_5d", "return_20d")


class ProviderPreflightResult(BaseModel):
    market: str
    authorized: bool
    sla_name: str | None = None
    raw_payload_complete: bool = False
    historical_time_fields_complete: bool = False
    revision_support: bool = False
    reasons: list[str] = []

    @property
    def passed(self) -> bool:
        return (
            self.authorized
            and bool(self.sla_name)
            and self.raw_payload_complete
            and self.historical_time_fields_complete
            and self.revision_support
            and not self.reasons
        )


@dataclass(frozen=True)
class PITRebuildInput:
    market: str
    instrument: CanonicalInstrument
    price_bars: list[PreparedPriceBar]
    feature_events: list[PointInTimeEvent]
    standard_events: list[StandardEventRevision]
    universe: list[HistoricalUniverseMembership]
    corporate_actions: list[CorporateActionRevision]
    raw_batches: list[RawDataBatch]
    preflight: ProviderPreflightResult
    generated_at: datetime
    trade_year: int
    historical_universe_version: str
    adjustment_policy: str
    event_coverage_status: str = "confirmed_none"
    synthetic_count: int = 0
    raw_payloads: list[PITRawPayload] = field(default_factory=list)


@dataclass
class PITRebuildResult:
    manifests: dict[str, object] = field(default_factory=dict)
    leakage_reports: dict[str, object] = field(default_factory=dict)
    blocked_scopes: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class PITRebuildBatchResult:
    """Result for a deterministic market/context rebuild batch.

    `by_scope` deliberately retains a result even for a fully blocked market.
    Operators can therefore distinguish a provider preflight failure from a
    market that was accidentally omitted from an otherwise successful run.
    """

    by_scope: dict[str, PITRebuildResult] = field(default_factory=dict)

    @property
    def manifests(self) -> dict[str, object]:
        return {
            key: manifest
            for result in self.by_scope.values()
            for key, manifest in result.manifests.items()
        }

    @property
    def blocked_scopes(self) -> dict[str, list[str]]:
        return {
            key: reasons
            for result in self.by_scope.values()
            for key, reasons in result.blocked_scopes.items()
        }


class PITRebuildOrchestrator:
    """Build four task datasets per market/context without cross-scope fallback."""

    def __init__(
        self,
        *,
        publisher: PITDatasetPublisher,
        trusted_market_repository=None,
        raw_ingestion_service=None,
    ) -> None:
        self.publisher = publisher
        self.trusted_market_repository = trusted_market_repository
        self.raw_ingestion_service = raw_ingestion_service

    def rebuild(
        self,
        *,
        training_run_id: str,
        request: PITRebuildInput,
        decision_context: str,
    ) -> PITRebuildResult:
        result = PITRebuildResult()
        scope_prefix = f"{request.market}:{decision_context}"
        try:
            request = self._persist_raw_payloads(request)
        except Exception as exc:
            reason = f"raw_payload_persistence_failed:{type(exc).__name__}:{exc}"
            for task in FORMAL_TASKS:
                result.blocked_scopes[f"{scope_prefix}:{task}"] = [reason]
            return result
        basic_reasons = self._validate_input(request)
        if basic_reasons:
            for task in FORMAL_TASKS:
                result.blocked_scopes[f"{scope_prefix}:{task}"] = basic_reasons
            return result
        try:
            standard_partitions = self.publisher.publish_standard_layers(
                market=request.market,
                trade_year=request.trade_year,
                generated_at=request.generated_at,
                bars=request.price_bars,
                events=request.standard_events,
                universe=request.universe,
                corporate_actions=request.corporate_actions,
            )
        except Exception as exc:
            reason = f"standard_layer_persistence_failed:{type(exc).__name__}:{exc}"
            for task in FORMAL_TASKS:
                result.blocked_scopes[f"{scope_prefix}:{task}"] = [reason]
            return result
        samples = TrainingDatasetBuilder(
            feature_version="investment-risk-features-v2",
            data_version=_data_version(request.raw_batches),
        ).build_samples(
            instrument=request.instrument,
            price_bars=request.price_bars,
            events=request.feature_events,
            decision_context=decision_context,
            event_coverage_status=request.event_coverage_status,
        )
        if not samples:
            for task in FORMAL_TASKS:
                result.blocked_scopes[f"{scope_prefix}:{task}"] = ["no_pit_training_samples"]
            return result
        feature_records, base_samples = self._freeze_records(
            samples=samples,
            request=request,
            decision_context=decision_context,
        )
        for task in FORMAL_TASKS:
            key = f"{scope_prefix}:{task}"
            task_samples = [_for_task(item, task) for item in base_samples]
            try:
                manifest, leakage = self.publisher.publish_task_dataset(
                    training_run_id=training_run_id,
                    market=request.market,
                    decision_context=decision_context,
                    task=task,
                    decision_time=max(item.feature_cutoff for item in task_samples),
                    generated_at=request.generated_at,
                    trade_year=request.trade_year,
                    feature_records=feature_records,
                    sample_records=task_samples,
                    bars=request.price_bars,
                    events=request.standard_events,
                    universe=request.universe,
                    corporate_actions=request.corporate_actions,
                    feature_version="investment-risk-features-v2",
                    label_version="four-market-tradeable-label-v1",
                    historical_universe_version=request.historical_universe_version,
                    standard_partitions=standard_partitions,
                )
                result.manifests[key] = manifest
                result.leakage_reports[key] = leakage
            except Exception as exc:
                result.blocked_scopes[key] = [f"{type(exc).__name__}:{exc}"]
        return result


    def _persist_raw_payloads(self, request: PITRebuildInput) -> PITRebuildInput:
        if not request.raw_payloads:
            return request
        if self.raw_ingestion_service is None:
            raise ValueError("raw payloads require append-only ingestion service")
        batches = list(request.raw_batches)
        for raw in request.raw_payloads:
            batches.append(self.raw_ingestion_service.persist(
                provider=raw.provider, request_id=raw.request_id, dataset=raw.dataset,
                payload=raw.payload, schema_version=raw.schema_version,
                available_at=raw.available_at, symbol=raw.symbol, interval=raw.interval,
                source_time=raw.source_time, exchange_time=raw.exchange_time,
                received_at=raw.received_at, market_session=raw.market_session,
            ))
        # Request ids are idempotent at ingestion; duplicated batch references
        # are collapsed before they become snapshot lineage.
        unique = {str(item.id): item for item in batches}
        return replace(request, raw_batches=list(unique.values()), raw_payloads=[])

    def _freeze_records(
        self,
        *,
        samples: list[TrainingSample],
        request: PITRebuildInput,
        decision_context: str,
    ) -> tuple[list[PITFeatureRecord], list[PITSampleRecord]]:
        features: list[PITFeatureRecord] = []
        samples_out: list[PITSampleRecord] = []
        status = EventCoverageStatus(request.event_coverage_status)
        for sample in samples:
            snapshot = self._snapshot(sample, request, decision_context)
            if self.trusted_market_repository is not None:
                self.trusted_market_repository.add_market_snapshot(snapshot)
            values = {key: float(value) for key, value in sample.features.items()}
            missing = {key: True for key in sample.missing_features}
            feature = PITFeatureRecord(
                symbol=sample.symbol,
                market=request.market,
                decision_context=decision_context,
                decision_time=sample.as_of_time,
                feature_cutoff=sample.feature_cutoff,
                market_snapshot_id=snapshot.id,
                market_snapshot_hash=snapshot.content_hash,
                feature_version="investment-risk-features-v2",
                historical_universe_version=request.historical_universe_version,
                adjustment_policy=request.adjustment_policy,
                event_coverage_status=status,
                data_quality_status=PITDataQualityStatus.PASSED,
                coverage_ratio=sample.feature_coverage,
                missing_mask=missing,
                input_revision_ids=[batch.payload_hash for batch in request.raw_batches],
                features=values,
                feature_hash=PITFeatureRecord.hash_features(values),
            )
            features.append(feature)
            samples_out.append(
                PITSampleRecord(
                    symbol=sample.symbol,
                    market=request.market,
                    decision_context=decision_context,
                    decision_time=sample.as_of_time,
                    feature_cutoff=sample.feature_cutoff,
                    market_snapshot_id=snapshot.id,
                    market_snapshot_hash=snapshot.content_hash,
                    feature_version="investment-risk-features-v2",
                    label_version="four-market-tradeable-label-v1",
                    event_coverage_status=status,
                    data_quality_status=PITDataQualityStatus.PASSED,
                    historical_universe_version=request.historical_universe_version,
                    adjustment_policy=request.adjustment_policy,
                    label_start=_at_midnight(sample.labels.label_start, sample.as_of_time),
                    label_end=_at_midnight(sample.labels.label_end, sample.as_of_time),
                    label_available=sample.labels.label_available,
                    label_unavailable_reason=sample.labels.label_unavailable_reason,
                    entry_delay_trading_days=sample.labels.entry_delay_sessions or 0,
                    input_revision_ids=[batch.payload_hash for batch in request.raw_batches],
                    missing_mask=missing,
                    features=values,
                    labels=sample.labels.model_dump(mode="json"),
                    sample_hash=_sample_hash(sample, snapshot.content_hash),
                )
            )
        return features, samples_out

    def _snapshot(self, sample: TrainingSample, request: PITRebuildInput, context: str) -> MarketSnapshot:
        # Snapshot identity must cover normalized revisions as well as raw
        # batches. A provider correction with the same raw request lineage is
        # still a different historical world for PIT replay purposes.
        payload = {
            "symbol": sample.symbol,
            "market": request.market,
            "context": context,
            "decision_time": sample.feature_cutoff.isoformat(),
            "raw_hashes": sorted(item.payload_hash for item in request.raw_batches),
            "price_revisions": [
                {
                    "symbol": item.symbol,
                    "trade_date": item.trade_date.isoformat(),
                    "revision": item.revision,
                    "available_at": (item.available_at or item.published_at).isoformat(),
                    "normalized_hash": item.normalized_hash,
                }
                for item in request.price_bars
                if (item.available_at or item.published_at) <= sample.feature_cutoff
            ],
            "event_revisions": [
                {
                    "logical_event_id": item.logical_event_id,
                    "revision": item.revision,
                    "available_at": item.available_at.isoformat(),
                    "normalized_hash": item.normalized_hash,
                }
                for item in request.standard_events
                if item.available_at <= sample.feature_cutoff
            ],
            "universe_revisions": [
                {
                    "symbol": item.symbol,
                    "revision": item.revision,
                    "effective_from": item.effective_from.isoformat(),
                    "available_at": item.available_at.isoformat(),
                }
                for item in request.universe
                if item.effective_from <= sample.feature_cutoff and item.available_at <= sample.feature_cutoff
            ],
            "corporate_action_revisions": [
                {
                    "symbol": item.symbol,
                    "ex_date": item.ex_date.isoformat(),
                    "revision": item.revision,
                    "available_at": item.available_at.isoformat(),
                    "payload_hash": item.payload_hash,
                }
                for item in request.corporate_actions
                if item.available_at <= sample.feature_cutoff
            ],
            "event_coverage_status": request.event_coverage_status,
            "universe": request.historical_universe_version,
            "adjustment": request.adjustment_policy,
        }
        content_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return MarketSnapshot(
            id=uuid5(NAMESPACE_URL, content_hash),
            symbol=sample.symbol,
            decision_context=context,
            trade_date=sample.as_of_date,
            decision_time=sample.feature_cutoff,
            prediction_start_date=sample.prediction_start_date or sample.as_of_date,
            feature_built_at=request.generated_at,
            security_universe_version=request.historical_universe_version,
            trading_calendar_version="exchange-calendar-v1",
            adjustment_policy=request.adjustment_policy,
            data_version=_data_version(request.raw_batches),
            quality_status="passed",
            content_hash=content_hash,
        )

    @staticmethod
    def _validate_input(request: PITRebuildInput) -> list[str]:
        reasons = list(request.preflight.reasons)
        if not request.preflight.passed:
            reasons.append("provider_preflight_failed")
        if request.synthetic_count:
            reasons.append("formal_synthetic_input_nonzero")
        if not request.raw_batches:
            reasons.append("raw_payload_batches_missing")
        if not request.universe:
            reasons.append("historical_universe_missing")
        if any(bar.available_at is None for bar in request.price_bars):
            reasons.append("price_available_at_unproven")
        return sorted(set(reasons))


class PITRebuildBatchOrchestrator:
    """Run formal PIT rebuilds sequentially without cross-market pollution.

    The individual rebuild operation remains intentionally small and is safe
    to retry. This coordinator supplies the production-shaped contract: each
    market and decision context is independently attempted, and an unexpected
    exception becomes an explicit block for only that scope's four tasks.
    """

    def __init__(self, orchestrator: PITRebuildOrchestrator) -> None:
        self.orchestrator = orchestrator

    def rebuild_all(
        self,
        *,
        training_run_id: str,
        requests: list[PITRebuildInput],
        decision_contexts: tuple[str, ...] = ("close_confirmed", "pre_open"),
    ) -> PITRebuildBatchResult:
        result = PITRebuildBatchResult()
        seen_markets: set[str] = set()
        for request in requests:
            if request.market in seen_markets:
                raise ValueError(f"duplicate market PIT rebuild request: {request.market}")
            seen_markets.add(request.market)
            for context in decision_contexts:
                scope_key = f"{request.market}:{context}"
                try:
                    result.by_scope[scope_key] = self.orchestrator.rebuild(
                        training_run_id=training_run_id,
                        request=request,
                        decision_context=context,
                    )
                except Exception as exc:  # Defensive isolation at the worker boundary.
                    result.by_scope[scope_key] = PITRebuildResult(
                        blocked_scopes={
                            f"{scope_key}:{task}": [
                                f"rebuild_worker_failed:{type(exc).__name__}:{exc}"
                            ]
                            for task in FORMAL_TASKS
                        }
                    )
        return result


def _for_task(record: PITSampleRecord, task: str) -> PITSampleRecord:
    target = {
        "drawdown_20d": "future_max_drawdown_20d",
        "direction_1d": "direction_1d",
        "direction_5d": "direction_5d",
        "return_20d": "future_return_20d",
    }[task]
    available = record.label_available and record.labels.get(target) is not None
    return record.model_copy(
        update={
            "label_available": available,
            "label_unavailable_reason": (
                record.label_unavailable_reason if available else f"task_target_unavailable:{target}"
            ),
        }
    )


def _data_version(batches: list[RawDataBatch]) -> str:
    return sha256("".join(sorted(item.payload_hash for item in batches)).encode()).hexdigest()


def _sample_hash(sample: TrainingSample, snapshot_hash: str) -> str:
    return sha256(
        json.dumps(
            {"symbol": sample.symbol, "time": sample.feature_cutoff.isoformat(), "snapshot": snapshot_hash,
             "features": sample.features, "labels": sample.labels.model_dump(mode="json")},
            sort_keys=True, separators=(",", ":"), default=str,
        ).encode()
    ).hexdigest()


def _at_midnight(value, reference: datetime) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, datetime.min.time(), reference.tzinfo)
