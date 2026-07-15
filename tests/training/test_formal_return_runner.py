from investment_research.training.formal_return_runner import _metrics


def test_return_runner_reports_pinball_and_interval_coverage() -> None:
    result = _metrics(
        "candidate",
        [(-0.1, 0.0, 0.1), (-0.2, -0.1, 0.0)],
        [0.05, -0.15],
        "fold",
    )
    assert result.mean_pinball_loss >= 0
    assert result.interval_coverage == 1.0
