"""Phase 5 — compliance-safe framing for the directional-forecast tile.

Guards the承重 compliance gap the spec flagged: "现在合规只管 AI，仪表盘
'涨跌预测'是裸的合规风险".  ``frame_prediction_as_observation`` is the single
source for the forecast wording, shared by the snapshot tile and the AI answer,
and the wording must pass ``ResearchTextComplianceChecker`` (no
买入/卖出/持有/加仓/减仓/目标价/必涨/必跌/保证收益).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from investment_research.agent.prediction_framing import (
    PREDICTION_DISCLAIMER,
    RESEARCH_DEMONSTRATION_NOT_VALIDATED,
    frame_prediction_as_observation,
    frame_tile_text,
)
from investment_research.agent.plain_answer import PlainAnswerBuilder
from investment_research.agent.service import AgentOrchestrator
from investment_research.domain.forecasts import (
    DirectionDistribution,
    DrawdownDistribution,
    ReturnDistribution,
)
from investment_research.service.asset_snapshot import DirectionalForecastObservation
from investment_research.service.compliance import ResearchTextComplianceChecker

BLOCKED_SUBSTRINGS = ("买入", "卖出", "持有", "加仓", "减仓", "目标价", "必涨", "必跌", "保证收益", "稳赚")
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _bundle():
    # Duck-typed bundle: the framing reads only the distribution attributes +
    # gating_reasons, so a SimpleNamespace with real Distribution objects is
    # exactly what frame_prediction_as_observation consumes in production.
    return SimpleNamespace(
        direction_1d=None,
        direction_5d=DirectionDistribution(horizon_days=5, up=0.62, down=0.30, flat=0.08),
        return_20d=ReturnDistribution(horizon_days=20, p10=-0.05, p50=0.02, p90=0.08),
        drawdown_20d=DrawdownDistribution(horizon_days=20, threshold=-0.08, threshold_probability=0.25),
        gating_reasons=["feature_coverage_below_threshold"],
    )


def _assert_compliance_safe(text: str) -> None:
    for term in BLOCKED_SUBSTRINGS:
        assert term not in text, f"blocked term '{term}' in tile text: {text}"
    result = ResearchTextComplianceChecker().check(text, subject_symbol="600519")
    assert result.allowed, f"compliance blocked: {result.reason_codes} :: {text}"


def test_none_forecast_is_compliance_safe() -> None:
    text = frame_tile_text(None, symbol="600519")
    assert "暂不下方向性结论" in text
    assert PREDICTION_DISCLAIMER in text
    _assert_compliance_safe(text)


def test_real_forecast_wording_is_compliance_safe() -> None:
    text = frame_tile_text(_bundle(), symbol="600519")
    # Describes probabilities / quantiles, never a verdict.
    assert "上行概率约 62%" in text
    assert "下行概率约 30%" in text
    assert "预期收益中位约 +2.0%" in text
    assert "回撤超 8% 的概率约 25%" in text
    assert PREDICTION_DISCLAIMER in text
    _assert_compliance_safe(text)


def test_snapshot_forecast_uses_single_source_framing() -> None:
    """The snapshot's DirectionalForecastObservation is built from the same
    framing function, so the dashboard tile and a direct call agree."""
    bundle = _bundle()
    framed = frame_prediction_as_observation(bundle, research_run_id="run-1", symbol="600519")
    obs = DirectionalForecastObservation(**framed)
    assert obs.available is True
    assert obs.research_run_id == "run-1"
    assert obs.framing_status == RESEARCH_DEMONSTRATION_NOT_VALIDATED
    assert obs.tile_text == framed["tile_text"] == frame_tile_text(bundle, symbol="600519")
    assert obs.direction_5d == bundle.direction_5d.model_dump(mode="json")
    _assert_compliance_safe(obs.tile_text)


def test_build_plain_answer_surfaces_forecast_note_in_business_condition() -> None:
    """The AI answer appends the shared forecast wording to the
    business-condition section (and it goes through the compliance check)."""
    bundle = _bundle()
    note = frame_tile_text(bundle, symbol="600519")
    answer = PlainAnswerBuilder().build(
        symbol="600519",
        asset_name="示例白酒",
        task_text="经营变化",
        scorecard=None,
        model_readings=None,
        knowledge_results=None,
        web_results=None,
        price_facts=None,
        data_as_of=AS_OF.isoformat(),
        forecast_note=note,
    )
    assert note in answer.business_condition
    assert answer.compliance_allowed is True

    # Without a forecast note, the business condition carries no forecast text.
    plain = PlainAnswerBuilder().build(
        symbol="600519",
        asset_name="示例白酒",
        task_text="经营变化",
        scorecard=None,
        model_readings=None,
        knowledge_results=None,
        web_results=None,
        price_facts=None,
        data_as_of=AS_OF.isoformat(),
    )
    assert "上行概率" not in plain.business_condition


def test_snapshot_forecast_note_helper_is_duck_typed() -> None:
    """_snapshot_forecast_note surfaces the tile_text when the snapshot has an
    available forecast, and is None otherwise — so _build_plain_answer only
    appends the forecast wording when the snapshot actually has one."""
    tile = frame_tile_text(_bundle(), symbol="600519")
    with_forecast = SimpleNamespace(
        directional_forecast=SimpleNamespace(available=True, tile_text=tile),
    )
    unavailable = SimpleNamespace(
        directional_forecast=SimpleNamespace(available=False, tile_text=tile),
    )
    none_forecast = SimpleNamespace(directional_forecast=None)
    assert AgentOrchestrator._snapshot_forecast_note(with_forecast) == tile
    assert AgentOrchestrator._snapshot_forecast_note(unavailable) is None
    assert AgentOrchestrator._snapshot_forecast_note(none_forecast) is None
    assert AgentOrchestrator._snapshot_forecast_note(None) is None
