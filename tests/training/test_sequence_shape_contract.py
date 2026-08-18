"""Shape-contract tests for research sequence challengers.

These guard the exact failure that made every deep model collapse with
``IndexError: list index out of range`` in ``fit_sequence_stats``: when
``build_sequence_examples`` derived ``feature_order`` per symbol, symbols with
fewer features produced shorter value vectors, and the global stats pass
indexed them out of range.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from investment_research.training.models import (
    InstrumentType,
    LabelSet,
    Market,
    TrainingSample,
)
from investment_research.training.sequence_dataset import (
    SequenceExample,
    SequenceShapeError,
    build_sequence_examples,
    validate_sequence_examples,
)
from investment_research.training.sequence_models import (
    SequenceModelConfig,
    _matrix,
    fit_sequence_stats,
    sequence_input_width,
)


SNAP_ID = "snapshot-2026-08"
SNAP_HASH = "a" * 64


def _sample(symbol: str, as_of: date, features: dict[str, float], *, direction: str = "up", ret: float = 0.05, dd: float = -0.1) -> TrainingSample:
    base = datetime(as_of.year, as_of.month, as_of.day, 15, 0, tzinfo=timezone.utc)
    return TrainingSample(
        symbol=symbol,
        market=Market.CN,
        instrument_type=InstrumentType.EQUITY,
        as_of_date=as_of,
        as_of_time=base,
        feature_cutoff=base,
        market_snapshot_id=SNAP_ID,
        market_snapshot_hash=SNAP_HASH,
        feature_version="v4",
        data_version="d1",
        features=features,
        labels=LabelSet(
            symbol=symbol,
            as_of_date=as_of,
            direction_1d=direction,
            future_return_20d=ret,
            future_max_drawdown_20d=dd,
            label_available=True,
            label_start=as_of,
            label_end=date(as_of.year, as_of.month, min(as_of.day + 20, 28)),
        ),
        data_tier="research_pit",
        data_quality_status="passed",
    )


def _example(feature_order, width, *, symbol="X", window=3):
    values = [[0.0] * width for _ in range(window)]
    missing = [[1.0 if v == 0 else 0.0 for v in row] for row in values]
    quality = [[1.0, 1.0, 1.0] for _ in range(window)]
    event = [[1.0, 0.0] for _ in range(window)]
    return SequenceExample(
        symbol=symbol, market="cn", decision_context="close_confirmed",
        decision_time="2026-01-01T15:00:00+00:00", feature_cutoff="2026-01-01T15:00:00+00:00",
        window_sessions=window, feature_order=list(feature_order), values=values,
        data_quality_mask=quality, event_missing_mask=event,
        provider_ids=[1] * window, revision_ids=[None] * window,
        source_delay_seconds=[0.0] * window, cache_states=["fresh"] * window,
        missing_mask=missing, target="up", sequence_hash="h",
    )


def test_validate_detects_mismatched_feature_order():
    good = _example(["a", "b", "c"], 3)
    bad = _example(["a", "b"], 2, symbol="Y")
    invalid = validate_sequence_examples([good, bad])
    assert invalid, "expected the narrower example to be flagged"
    sym, dt, h, reason = invalid[0]
    assert sym == "Y"
    assert "actual_feature_count" in reason or "feature_order len" in reason


def test_validate_passes_uniform_examples():
    a = _example(["a", "b", "c"], 3, symbol="A")
    b = _example(["a", "b", "c"], 3, symbol="B")
    assert validate_sequence_examples([a, b]) == []


def test_fit_sequence_stats_raises_shape_error_not_index():
    good = _example(["a", "b", "c"], 3)
    bad = _example(["a", "b"], 2, symbol="Y")
    try:
        fit_sequence_stats([good, bad])
    except SequenceShapeError:
        pass
    except IndexError as exc:
        raise AssertionError("fit_sequence_stats raised bare IndexError instead of SequenceShapeError") from exc
    else:
        raise AssertionError("expected SequenceShapeError for mismatched widths")


def test_matrix_raises_on_width_mismatch():
    good = _example(["a", "b", "c"], 3)
    bad = _example(["a", "b"], 2, symbol="Y")
    try:
        _matrix([good, bad], fit_sequence_stats([good]))
    except SequenceShapeError:
        pass
    except IndexError:
        raise AssertionError("_matrix raised bare IndexError instead of SequenceShapeError")
    else:
        raise AssertionError("expected SequenceShapeError for width mismatch")


def test_sequence_input_width_contract():
    ex = _example(["a", "b", "c"], 3)
    stats = fit_sequence_stats([ex])
    tensor = _matrix([ex], stats)
    assert sequence_input_width(ex) == len(tensor[0][0])


def test_build_sequence_examples_uniform_feature_order():
    a_rows = [_sample("600000", date(2026, 1, d), {"f1": 1.0, "f2": 2.0, "f3": 3.0}) for d in range(1, 25)]
    b_rows = [_sample("600001", date(2026, 1, d), {"f1": 1.0, "f2": 2.0}) for d in range(1, 25)]
    examples = build_sequence_examples(
        a_rows + b_rows, target_name="direction_1d", window_sessions=20,
    )
    assert examples, "expected windows to be built"
    widths = {len(ex.feature_order) for ex in examples}
    assert widths == {3}, f"all examples must share one feature_order width, got {widths}"
    for ex in examples:
        for row in ex.values:
            assert len(row) == len(ex.feature_order), "value width must match feature_order"
        assert ex.symbol in ("600000", "600001")


def test_build_sequence_examples_blocks_blacklisted_quality():
    rows = [_sample("600000", date(2026, 1, d), {"f1": 1.0}) for d in range(1, 25)]
    rows[0] = rows[0].model_copy(update={"data_quality_status": "blocked"})
    out = build_sequence_examples(rows, target_name="direction_1d", window_sessions=20)
    assert out


def test_5d_sequence_uses_target_availability_and_5d_label_end():
    start = date(2026, 1, 1)
    rows = []
    for index in range(25):
        day = start + timedelta(days=index)
        sample = _sample("A", day, {"ret_5d": index / 100.0})
        sample.labels.excess_return_5d = index / 100.0
        sample.labels.label_available = False
        sample.labels.entry_trade_date = day + timedelta(days=1)
        rows.append(sample)
    examples = build_sequence_examples(
        rows, target_name="excess_return_5d", window_sessions=20,
    )
    assert examples
    first = examples[0]
    assert first.decision_time[:10] == str(start + timedelta(days=19))
    assert first.label_end == str(start + timedelta(days=24))
