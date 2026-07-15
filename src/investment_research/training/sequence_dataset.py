"""Deterministic, point-in-time sequence construction for research models.

The legacy deep trainers operate on one tabular row.  This module is the
research-only sequence boundary: it materializes fixed historical windows from
already frozen ``TrainingSample`` rows and carries data quality provenance as
first-class channels instead of turning missing data into market signals.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, Field

from investment_research.training.models import TrainingSample


VALID_EVENT_STATES = {"events_present", "confirmed_none"}


class SequenceExample(BaseModel):
    symbol: str
    market: str
    decision_context: str
    decision_time: str
    feature_cutoff: str
    window_sessions: int = Field(ge=1)
    feature_order: list[str]
    values: list[list[float]]
    data_quality_mask: list[list[float]]
    event_missing_mask: list[list[float]]
    provider_ids: list[int]
    revision_ids: list[str | None]
    source_delay_seconds: list[float]
    cache_states: list[str]
    missing_mask: list[list[bool]]
    target: float | str
    label_start: str | None = None
    label_end: str | None = None
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = None
    data_tier: str = "research_pit"
    sequence_hash: str


@dataclass(frozen=True)
class SequenceBuildConfig:
    window_sessions: int = 60
    target_name: str = "future_max_drawdown_20d"
    require_research_pit: bool = True
    allow_quality_degraded: bool = True


def build_sequence_examples(
    samples: list[TrainingSample],
    *,
    target_name: str,
    window_sessions: int,
    require_research_pit: bool = True,
    allow_quality_degraded: bool = True,
) -> list[SequenceExample]:
    """Build non-leaking same-symbol windows from a frozen snapshot.

    Rows are never sorted across symbols, decision contexts or snapshots.  A
    window may carry degraded event/quality masks, but critical quality issues
    and mixed snapshots are rejected.  The target belongs only to the final
    decision row, so callers can apply the existing task-specific label and
    purge rules without sharing thresholds across tasks.
    """
    if window_sessions not in {20, 60, 120}:
        raise ValueError("sequence window must be 20, 60 or 120 sessions")
    groups: dict[tuple[str, str, str, str | None, str | None], list[TrainingSample]] = {}
    for sample in samples:
        if require_research_pit and sample.data_tier not in {"research_pit", "formal_pit"}:
            raise ValueError("sequence training requires a known PIT data tier")
        if require_research_pit and (not sample.market_snapshot_id or not sample.market_snapshot_hash):
            raise ValueError("sequence training requires an immutable market snapshot reference")
        if sample.data_quality_status in {"blocked", "unavailable", "error"}:
            continue
        if not allow_quality_degraded and sample.data_quality_status != "passed":
            continue
        key = (
            sample.symbol,
            sample.market.value,
            sample.decision_context,
            sample.market_snapshot_id,
            sample.market_snapshot_hash,
        )
        groups.setdefault(key, []).append(sample)

    output: list[SequenceExample] = []
    for (symbol, market, context, snapshot_id, snapshot_hash), group in groups.items():
        ordered = sorted(group, key=lambda item: (item.as_of_time, item.as_of_date))
        feature_order = sorted({name for row in ordered for name in row.features})
        if not feature_order:
            continue
        for end in range(window_sessions - 1, len(ordered)):
            window = ordered[end - window_sessions + 1 : end + 1]
            final = window[-1]
            target = getattr(final.labels, target_name, None)
            if target is None or not final.labels.label_available:
                continue
            if any(row.feature_cutoff > row.as_of_time for row in window):
                continue
            if any(row.market_snapshot_hash != snapshot_hash for row in window):
                continue
            values = [[float(row.features.get(name, 0.0)) for name in feature_order] for row in window]
            missing = [[name in row.missing_features or name not in row.features for name in feature_order] for row in window]
            quality = [_quality_channels(row) for row in window]
            event_missing = [_event_channels(row) for row in window]
            provider_ids = [_stable_provider_id(row.provider_id or row.provider or "unknown") for row in window]
            revision_ids = [row.revision_id or (row.input_revision_ids[-1] if row.input_revision_ids else None) for row in window]
            delays = [float(row.source_delay_seconds or 0.0) for row in window]
            cache_states = [row.cache_state or "unknown" for row in window]
            payload = {
                "symbol": symbol,
                "market": market,
                "context": context,
                "decision_time": final.as_of_time.isoformat(),
                "feature_cutoff": final.feature_cutoff.isoformat(),
                "window_sessions": window_sessions,
                "features": feature_order,
                "values": values,
                "quality": quality,
                "event_missing": event_missing,
                "provider_ids": provider_ids,
                "revision_ids": revision_ids,
                "delays": delays,
                "missing": missing,
                "target": target,
                "snapshot_hash": snapshot_hash,
            }
            output.append(SequenceExample(
                symbol=symbol,
                market=market,
                decision_context=context,
                decision_time=final.as_of_time.isoformat(),
                feature_cutoff=final.feature_cutoff.isoformat(),
                window_sessions=window_sessions,
                feature_order=feature_order,
                values=values,
                data_quality_mask=quality,
                event_missing_mask=event_missing,
                provider_ids=provider_ids,
                revision_ids=revision_ids,
                source_delay_seconds=delays,
                cache_states=cache_states,
                missing_mask=missing,
                target=target,
                label_start=final.labels.label_start.isoformat() if final.labels.label_start else None,
                label_end=final.labels.label_end.isoformat() if final.labels.label_end else None,
                market_snapshot_id=snapshot_id,
                market_snapshot_hash=snapshot_hash,
                data_tier=final.data_tier,
                sequence_hash=sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            ))
    return output


def _quality_channels(sample: TrainingSample) -> list[float]:
    status = sample.data_quality_status
    passed = 1.0 if status in {"passed", "complete", "backfilled"} else 0.0
    coverage = max(0.0, min(1.0, float(sample.feature_coverage)))
    issues = 1.0 if sample.data_issues else 0.0
    return [passed, coverage, 1.0 - issues]


def _event_channels(sample: TrainingSample) -> list[float]:
    status = sample.event_coverage_status
    missing = 0.0 if status in VALID_EVENT_STATES else 1.0
    source_available = 1.0 if sample.event_source_available else 0.0
    return [missing, source_available]


def _stable_provider_id(provider: str) -> int:
    return int.from_bytes(sha256(provider.encode()).digest()[:4], "big")
