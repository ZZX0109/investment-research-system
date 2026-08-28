"""Agent evaluation package — walk-forward + performance surfacing (§1 step 7).

Mirrors fortune's ``walk_forward`` + ``performance_monitor`` idea but adapted
to this repo's archived predicted-vs-actual readings (``ModelHistoryPoint``),
so the per-asset daily accuracy + error is surfaced to the LLM + dashboard
("训练说清楚" for the walk-forward, mirroring the global accuracy-surface).
"""
from investment_research.agent.evaluation.fundamental_coverage import fundamental_coverage
from investment_research.agent.evaluation.price_path import build_price_path_projection
from investment_research.agent.evaluation.walk_forward import (
    load_model_prediction_history,
    summarize_walk_forward,
)

__all__ = [
    "summarize_walk_forward",
    "load_model_prediction_history",
    "fundamental_coverage",
    "build_price_path_projection",
]
