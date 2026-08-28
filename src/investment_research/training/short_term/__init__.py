"""§1 row-2 fortune CatBoost short-term direction runner package.

Mirrors fortune's ``ml_trading_model.py`` idea (a CatBoost short-term
direction model) adapted to this repo's archived OOF predictions.  The runner
is the §1 row-2 mandated ``training/short_term/catboost_runner`` module; it
trains a CatBoostClassifier that maps (existing-model score, regime,
industry, coverage, data-quality) → actual direction, + saves/loads ``.cbm``
artifacts at ``artifacts/short_term/``.

Degrades gracefully: ``is_available()`` is False until a trained ``.cbm``
exists, so callers (``get_four_task_forecasts``) fall back to the persisted
research_forecasts.
"""

from investment_research.training.short_term.catboost_runner import (
    CatBoostShortTermRunner,
)

__all__ = ["CatBoostShortTermRunner"]
