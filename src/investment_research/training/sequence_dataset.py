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
from math import isfinite
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from investment_research.training.models import TrainingSample
from investment_research.training.research_evaluation import classify_market_regime


VALID_EVENT_STATES = {"events_present", "confirmed_none"}


class SequenceExample(BaseModel):
    symbol: str
    # Historical industry at the decision date.  It is metadata for
    # cross-sectional diagnostics, never a feature channel, so changing the
    # current classification cannot rewrite past evaluation buckets.
    industry_key: str | None = None
    market: str
    decision_context: str
    decision_time: str
    feature_cutoff: str
    window_sessions: int = Field(ge=1)
    feature_order: list[str]
    # Sequence windows are held as compact NumPy arrays during one training
    # run.  ``Any`` is intentional here: Pydantic's list coercion would copy
    # every 60x333 window into Python float objects and exhaust system RAM.
    values: Any
    data_quality_mask: Any
    event_missing_mask: Any
    provider_ids: Any
    revision_ids: Any
    source_delay_seconds: Any
    cache_states: Any
    missing_mask: Any
    target: float | str
    label_start: str | None = None
    label_end: str | None = None
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = None
    label_version: str = "unknown"
    data_tier: str = "research_pit"
    market_regime: str = "unknown"
    sequence_hash: str


class SequenceShapeError(ValueError):
    """Raised when a SequenceExample violates the fixed-width contract.

    Replaces the previous bare ``IndexError: list index out of range`` so the
    training monitor and stderr tail expose the real symbol / sequence / width
    rather than an opaque stack trace.
    """


def validate_sequence_examples(
    examples: list[SequenceExample],
    *,
    window_sessions: int | None = None,
    feature_order: list[str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Return invalid ``(symbol, decision_time, sequence_hash, reason)`` tuples.

    Pure inspection: it never mutates or drops examples, so callers decide how
    to act on the report (raise, block the task, or write a quality report).
    """
    if not examples:
        return [("(none)", "(none)", "(none)", "empty example set")]
    expected_features = list(feature_order or examples[0].feature_order)
    expected_len = len(expected_features)
    expected_window = window_sessions or examples[0].window_sessions
    invalid: list[tuple[str, str, str, str]] = []
    for ex in examples:
        sym, dt, h = ex.symbol, ex.decision_time, ex.sequence_hash
        if ex.window_sessions != expected_window:
            invalid.append((sym, dt, h, f"window_sessions {ex.window_sessions} != {expected_window}"))
            continue
        if len(ex.feature_order) != expected_len:
            invalid.append((sym, dt, h, f"feature_order len {len(ex.feature_order)} != {expected_len} (expected_feature_count)"))
            continue
        channels = {
            "values": ex.values,
            "missing_mask": ex.missing_mask,
            "data_quality_mask": ex.data_quality_mask,
            "event_missing_mask": ex.event_missing_mask,
            "provider_ids": ex.provider_ids,
            "revision_ids": ex.revision_ids,
            "source_delay_seconds": ex.source_delay_seconds,
            "cache_states": ex.cache_states,
        }
        for attr, vec in channels.items():
            if len(vec) != expected_window:
                invalid.append((sym, dt, h, f"{attr} len {len(vec)} != window {expected_window}"))
                break
        else:
            for t in range(expected_window):
                if len(ex.values[t]) != expected_len:
                    invalid.append((sym, dt, h, f"values[{t}] width {len(ex.values[t])} != {expected_len} (actual_feature_count)"))
                    break
                if len(ex.missing_mask[t]) != expected_len:
                    invalid.append((sym, dt, h, f"missing_mask[{t}] width {len(ex.missing_mask[t])} != {expected_len}"))
                    break
    return invalid


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

    # One global feature contract keeps every SequenceExample the same width.
    # The previous per-group union produced different ``feature_order`` lengths
    # per symbol, so ``fit_sequence_stats`` indexed out of range once examples
    # from multiple symbols were concatenated (the IndexError root cause).
    global_feature_order = sorted(
        {name for group in groups.values() for row in group for name in row.features}
    )
    if not global_feature_order:
        return []
    output: list[SequenceExample] = []
    for (symbol, market, context, snapshot_id, snapshot_hash), group in groups.items():
        ordered = sorted(group, key=lambda item: (item.as_of_time, item.as_of_date))
        feature_order = global_feature_order
        group_values = np.asarray(
            [[_finite_feature(row, name) for name in feature_order] for row in ordered],
            dtype=np.float32,
        )
        group_missing = np.asarray(
            [[
                name in row.missing_features
                or name not in row.features
                or not _is_finite_feature(row.features.get(name))
                for name in feature_order
            ] for row in ordered],
            dtype=np.bool_,
        )
        group_quality = np.asarray([_quality_channels(row) for row in ordered], dtype=np.float32)
        group_event = np.asarray([_event_channels(row) for row in ordered], dtype=np.float32)
        group_provider = np.asarray(
            [_stable_provider_id(row.provider_id or row.provider or "unknown") for row in ordered],
            dtype=np.int64,
        )
        group_revisions = [
            row.revision_id or (row.input_revision_ids[-1] if row.input_revision_ids else None)
            for row in ordered
        ]
        group_delays = np.asarray([float(row.source_delay_seconds or 0.0) for row in ordered], dtype=np.float32)
        group_cache = [row.cache_state or "unknown" for row in ordered]

        for end in range(window_sessions - 1, len(ordered)):
            start = end - window_sessions + 1
            window = ordered[end - window_sessions + 1 : end + 1]
            final = window[-1]
            target = getattr(final.labels, target_name, None)
            # Availability is task-specific. ``label_available`` is the
            # legacy 20-session execution flag and must not discard a valid
            # 1d/5d target merely because a 20-session future window is not
            # present. A non-null task target is the authoritative gate.
            if target is None:
                continue
            # ``as_of_time`` is the provider/source timestamp and may precede
            # the close-confirmed decision cutoff by design.  The PIT
            # availability timestamp is ``as_of`` when present; falling back
            # to the legacy source timestamp keeps old fixtures compatible.
            if any(
                row.feature_cutoff > (row.as_of or row.feature_cutoff or row.as_of_time)
                for row in window
            ):
                continue
            if any(row.market_snapshot_hash != snapshot_hash for row in window):
                continue
            values = group_values[start : end + 1]
            missing = group_missing[start : end + 1]
            quality = group_quality[start : end + 1]
            event_missing = group_event[start : end + 1]
            provider_ids = group_provider[start : end + 1]
            revision_ids = group_revisions[start : end + 1]
            delays = group_delays[start : end + 1]
            cache_states = group_cache[start : end + 1]
            hash_metadata = {
                "symbol": symbol,
                "industry_key": final.industry_key,
                "market": market,
                "context": context,
                "decision_time": final.as_of_time.isoformat(),
                "feature_cutoff": final.feature_cutoff.isoformat(),
                "window_sessions": window_sessions,
                "features": feature_order,
                "revision_ids": revision_ids,
                "cache_states": cache_states,
                "target": target,
                "snapshot_hash": snapshot_hash,
                "market_regime": classify_market_regime(final),
            }
            sequence_hasher = sha256(
                json.dumps(hash_metadata, sort_keys=True, separators=(",", ":")).encode()
            )
            # Hash compact array bytes directly.  Converting every 60x333
            # window back to nested JSON lists created hundreds of millions of
            # temporary Python objects during large cohort preparation.
            for array in (values, quality, event_missing, provider_ids, delays, missing):
                sequence_hasher.update(np.ascontiguousarray(array).tobytes())
            sequence_hash = sequence_hasher.hexdigest()
            target_label_end = _target_label_end(
                ordered=ordered,
                end=end,
                target_name=target_name,
                fallback=final.labels.label_end,
                entry_trade_date=final.labels.entry_trade_date,
            )
            output.append(SequenceExample(
                symbol=symbol,
                industry_key=final.industry_key,
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
                label_end=target_label_end.isoformat() if target_label_end else None,
                market_snapshot_id=snapshot_id,
                market_snapshot_hash=snapshot_hash,
                label_version=final.label_version,
                data_tier=final.data_tier,
                market_regime=classify_market_regime(final),
                sequence_hash=sequence_hash,
            ))
    return output


def _target_label_end(
    *,
    ordered: list[TrainingSample],
    end: int,
    target_name: str,
    fallback,
    entry_trade_date,
):
    """Resolve a task-specific label end for purge/embargo boundaries."""
    horizon = (
        1 if target_name.endswith("_1d")
        else 5 if target_name.endswith("_5d")
        else 20 if target_name.endswith("_20d")
        else 60 if target_name.endswith("_60d")
        else 120 if target_name.endswith("_120d")
        else None
    )
    if horizon is None or horizon >= 20:
        return fallback
    entry_index = end + 1
    if entry_trade_date is not None:
        entry_index = next(
            (index for index in range(end + 1, len(ordered)) if ordered[index].as_of_date == entry_trade_date),
            entry_index,
        )
    terminal_index = entry_index + horizon - 1
    return ordered[terminal_index].as_of_date if terminal_index < len(ordered) else fallback


def _quality_channels(sample: TrainingSample) -> list[float]:
    status = sample.data_quality_status
    passed = 1.0 if status in {"passed", "complete", "backfilled"} else 0.0
    coverage = max(0.0, min(1.0, float(sample.feature_coverage)))
    issues = 1.0 if sample.data_issues else 0.0
    return [passed, coverage, 1.0 - issues]


def _is_finite_feature(value: object) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _finite_feature(sample: TrainingSample, name: str) -> float:
    value = sample.features.get(name)
    return float(value) if _is_finite_feature(value) else 0.0


def _event_channels(sample: TrainingSample) -> list[float]:
    status = sample.event_coverage_status
    missing = 0.0 if status in VALID_EVENT_STATES else 1.0
    source_available = 1.0 if sample.event_source_available else 0.0
    return [missing, source_available]


def _stable_provider_id(provider: str) -> int:
    return int.from_bytes(sha256(provider.encode()).digest()[:4], "big")
