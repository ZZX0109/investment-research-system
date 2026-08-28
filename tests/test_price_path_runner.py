"""§1 step-6 price-path runner tests.

The runner is the §1 row-5 mandated adapter location. Its default delegates to
the existing-model quantile projection (real data); the kittenCN temporal hook
degrades until vendored + trained + torch present.
"""
from __future__ import annotations

from datetime import datetime, timezone

from investment_research.training.price_path import forecast
from investment_research.training.price_path import kittencn_adapter


_READINGS = {
    "excess_return_240d": {
        "q10": 0.95,
        "q50": 1.10,
        "q90": 1.35,
        "quantile_projection": {"horizon_days": 240, "points": []},
        "prediction_interval_width": 0.40,
        "horizon_days": 240,
    }
}


def test_runner_delegates_to_quantile_projection_by_default() -> None:
    """No vendored kittenCN → the runner degrades to the existing-model
    quantile projection (the round-9 real-data path), never synthesizes."""
    as_of = datetime(2026, 8, 19, tzinfo=timezone.utc)
    result = forecast("600519", _READINGS, 1341.99, as_of, realized_mae=0.2585, task="excess_return_240d")
    assert result["status"] == "ok"
    assert "quantile projection" in result["model"]
    assert result["horizon_days"] == 240
    assert result["mean_abs_error_pct"] == 0.2585
    # First point anchored at the latest close (predicted == actual == close).
    first = result["points"][0]
    assert first["predicted"] == 1341.99 and first["actual"] == 1341.99
    # Last forward point's p50 (predicted) above the base (q50=1.10 > 1.0).
    assert result["points"][-1]["predicted"] > 1341.99


def test_runner_returns_unavailable_when_no_readings_or_close() -> None:
    as_of = datetime(2026, 8, 19, tzinfo=timezone.utc)
    # No model reading → degrade path.
    assert forecast("600519", None, 1341.99, as_of)["status"] == "unavailable"
    # No latest close → degrade path.
    assert forecast("600519", _READINGS, None, as_of)["status"] == "unavailable"


def test_kittencn_temporal_hook_degrades_when_not_vendored() -> None:
    """The §1 row-5 kittenCN temporal hook returns None (degrade) until the
    source is vendored + trained + torch present — so the runner honestly
    falls back to the quantile projection."""
    # Default env: no vendored source, no weights → unavailable.
    assert kittencn_adapter.is_available() is False
    assert kittencn_adapter.forecast_temporal_path("600519", _READINGS, 1341.99, datetime.now(timezone.utc), 0.26, "excess_return_240d") is None


def test_runner_matches_direct_helper_output() -> None:
    """Routing through the runner produces the same dict the snapshot/tool
    previously got from ``build_price_path_projection`` directly (the runner
    is a pure facade over the default path). generated_at is a call-time
    stamp, so it is excluded from the comparison."""
    from investment_research.agent.evaluation import build_price_path_projection

    as_of = datetime(2026, 8, 19, tzinfo=timezone.utc)
    via_runner = forecast("600519", _READINGS, 1341.99, as_of, realized_mae=0.2585, task="excess_return_240d")
    direct = build_price_path_projection(_READINGS, 1341.99, as_of, realized_mae=0.2585, task="excess_return_240d")
    via_runner.pop("generated_at", None)
    direct.pop("generated_at", None)
    # The runner injects temporal_model_status (the kittenCN degrade reason)
    # when the temporal model is not ready — pop it before comparing the
    # core projection fields.
    via_runner.pop("temporal_model_status", None)
    assert via_runner == direct


def test_kittencn_prereq_status_reports_partial_availability() -> None:
    """§1 row-5 / 训练说清楚: prereq_status reports each kittenCN temporal
    prerequisite individually (vendored_source / torch / trained_weights) so
    the LLM can cite the honest partial state, never a silent degrade."""
    from investment_research.training.price_path.kittencn_adapter import prereq_status

    status = prereq_status()
    assert isinstance(status, dict)
    for key in ("vendored_source", "torch", "trained_weights", "ready", "blocking"):
        assert key in status, f"missing key {key}"
    assert isinstance(status["ready"], bool)
    assert isinstance(status["blocking"], list)
    # ready must be the AND of the three prereqs.
    assert status["ready"] == (
        status["vendored_source"] and status["torch"] and status["trained_weights"]
    )
    # blocking lists exactly the missing prereqs.
    expected_blocking = sorted(
        name
        for name, ok in (
            ("vendored_source", status["vendored_source"]),
            ("torch", status["torch"]),
            ("trained_weights", status["trained_weights"]),
        )
        if not ok
    )
    assert sorted(status["blocking"]) == expected_blocking


def test_price_path_runner_surfaces_temporal_model_status_when_degrading() -> None:
    """When the temporal model is not ready, the forecast result carries
    `temporal_model_status` (the honest degrade reason) — 训练说清楚."""
    from investment_research.training.price_path import forecast

    result = forecast("600519", None, None, "2026-08-19", None)
    assert "temporal_model_status" in result
    tms = result["temporal_model_status"]
    assert isinstance(tms, dict)
    assert "ready" in tms and "blocking" in tms
