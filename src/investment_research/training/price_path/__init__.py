"""§1 step-6 price-path adapter (the §1 row-5 mandated location).

This package is the integration layer for the price-path forecast — the single
entry point the snapshot builder (``service/asset_snapshot.py``) + the
``get_price_path_forecast`` LLM tool both route through.

Default forecast = the EXISTING trained long-term model's q10/q50/q90 fan
(delegates to ``build_price_path_projection`` — real data, no synthesis).
When the kittenCN temporal port is vendored at ``vendor/kittencn`` + trained +
torch is available, ``kittencn_adapter`` produces a daily temporal path
instead; until then the runner degrades to the quantile projection.

The principle (§1): don't swallow the whole kittenCN repo — only its strongest
piece (the temporal architecture) lives behind this adapter, isolated from the
core pipeline.
"""

from investment_research.training.price_path.runner import forecast

__all__ = ["forecast"]
