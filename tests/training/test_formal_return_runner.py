from datetime import datetime, timezone
from types import SimpleNamespace

from investment_research.training.formal_return_runner import _metrics
from investment_research.training.formal_training import balanced_panel_fit_samples


def test_return_runner_reports_pinball_and_interval_coverage() -> None:
    result = _metrics(
        "candidate",
        [(-0.1, 0.0, 0.1), (-0.2, -0.1, 0.0)],
        [0.05, -0.15],
        "fold",
    )
    assert result.mean_pinball_loss >= 0
    assert result.interval_coverage == 1.0


def test_return_fit_budget_keeps_every_symbol_and_is_deterministic() -> None:
    rows = [
        SimpleNamespace(
            symbol=symbol,
            as_of_time=datetime(2026, 1, day, tzinfo=timezone.utc),
            label_end=None,
        )
        for symbol in ("000001", "600519", "300750")
        for day in range(1, 11)
    ]

    first = balanced_panel_fit_samples(rows, max_rows=12)
    second = balanced_panel_fit_samples(rows, max_rows=12)

    assert len(first) <= 12
    assert {row.symbol for row in first} == {"000001", "600519", "300750"}
    assert [(row.symbol, row.as_of_time) for row in first] == [
        (row.symbol, row.as_of_time) for row in second
    ]
