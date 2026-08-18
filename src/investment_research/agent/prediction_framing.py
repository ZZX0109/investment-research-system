"""Compliance-safe framing for the directional-forecast tile (Phase 5).

The dashboard's "涨跌预测" tile and the AI answer must share ONE wording, and
that wording must pass ``ResearchTextComplianceChecker`` — otherwise the tile
is a裸的合规风险 (the checker only ran on the AI answer before).  This module
is the single source for that wording: it converts a ``ResearchForecastBundle``
into a research-framed observation (direction probabilities / relative-benchmark
return quantiles / drawdown probability) with an explicit
``research_demonstration_not_validated`` disclaimer and no buy/sell/target-price/
guaranteed-return language.

Used by:

* ``AssetSnapshotService`` — the snapshot's ``directional_forecast.tile_text``;
* ``AgentOrchestrator._build_plain_answer`` — the AI answer surfaces the same
  ``tile_text`` so the dashboard and the answer cannot drift on forecast wording.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from investment_research.domain.forecasts import ResearchForecastBundle

RESEARCH_DEMONSTRATION_NOT_VALIDATED = "research_demonstration_not_validated"

# Shared, compliance-safe disclaimer appended to every forecast tile.  Mentions
# the prohibited concepts only to forbid them; contains none of the blocked
# trade verbs (买入/卖出/持有/加仓/减仓), no 目标价, no 必涨/必跌/保证收益.
PREDICTION_DISCLAIMER = "（研究展示，未经验证，非涨跌预测或买卖建议。）"


def frame_tile_text(bundle: "ResearchForecastBundle | None", *, symbol: str | None = None) -> str:
    """Compliance-safe, human-readable forecast wording.

    Describes the model output as direction *probabilities* and
    relative-benchmark *return quantiles* — never a directional verdict or a
    trade instruction.  ``symbol`` is accepted for API parity but deliberately
    NOT embedded in the text so the wording stays non-individualized and the
    dashboard renders the symbol separately.
    """
    if bundle is None:
        return f"研究预测尚未生成或未通过门禁，暂不下方向性结论。{PREDICTION_DISCLAIMER}"
    parts: list[str] = []
    d5 = bundle.direction_5d
    if d5 is not None:
        parts.append(
            f"5 日相对基准上行概率约 {d5.up * 100:.0f}%、下行概率约 {d5.down * 100:.0f}%"
        )
    r20 = bundle.return_20d
    if r20 is not None:
        parts.append(
            f"20 日相对基准预期收益中位约 {r20.p50 * 100:+.1f}%"
            f"（10%–90% 区间 {r20.p10 * 100:+.1f}% 至 {r20.p90 * 100:+.1f}%）"
        )
    dd20 = bundle.drawdown_20d
    if dd20 is not None:
        parts.append(
            f"20 日回撤超 {abs(dd20.threshold) * 100:.0f}% 的概率约 {dd20.threshold_probability * 100:.0f}%"
        )
    if not parts:
        return f"研究预测已生成但方向与收益分布尚未披露。{PREDICTION_DISCLAIMER}"
    return "；".join(parts) + "。" + PREDICTION_DISCLAIMER


def frame_prediction_as_observation(
    bundle: "ResearchForecastBundle | None",
    *,
    research_run_id: str | None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Convert a research forecast bundle into a compliance-safe observation.

    Returns the structured fields the dashboard tile and the AI answer consume,
    plus ``tile_text`` (the shared, compliance-safe wording) and
    ``framing_status`` (always ``research_demonstration_not_validated`` so
    consumers never mistake this for a validated model output).
    """
    available = bundle is not None
    return {
        "available": available,
        "research_run_id": research_run_id,
        "tile_text": frame_tile_text(bundle, symbol=symbol),
        "framing_status": RESEARCH_DEMONSTRATION_NOT_VALIDATED,
        "direction_1d": (
            None if bundle is None or bundle.direction_1d is None
            else bundle.direction_1d.model_dump(mode="json")
        ),
        "direction_5d": (
            None if bundle is None or bundle.direction_5d is None
            else bundle.direction_5d.model_dump(mode="json")
        ),
        "return_20d": (
            None if bundle is None or bundle.return_20d is None
            else bundle.return_20d.model_dump(mode="json")
        ),
        "drawdown_20d": (
            None if bundle is None or bundle.drawdown_20d is None
            else bundle.drawdown_20d.model_dump(mode="json")
        ),
        "gating_reasons": [] if bundle is None else list(bundle.gating_reasons or []),
    }


__all__ = [
    "PREDICTION_DISCLAIMER",
    "RESEARCH_DEMONSTRATION_NOT_VALIDATED",
    "frame_prediction_as_observation",
    "frame_tile_text",
]
