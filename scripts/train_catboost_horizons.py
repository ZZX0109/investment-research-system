"""§1 row-2 fortune CatBoost 1/5/20d horizon training (round 27).

Reads ALL daily bars from ``versioned_market_bars`` (populated round 26),
builds price-based technical features + 1/5/20d forward-direction labels per
(symbol, date), trains one ``CatBoostClassifier`` per horizon, and writes
artifacts + an accuracy JSON.  The trained model is served by
``CatBoostHorizonRunner.horizon_forecast_for_symbol`` (registered to
``get_four_task_forecasts`` as the additive ``catboost_short_term_horizons``
field).

Usage:
    NODE_ENV=development python3 -m scripts.train_catboost_horizons
"""
from __future__ import annotations

import logging

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.training.short_term.catboost_horizon_runner import CatBoostHorizonRunner


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    uow = SQLiteUnitOfWork(get_default_database_path())
    repo = uow.trusted_market
    try:
        cur = uow.connection.cursor()
        cur.execute("SELECT DISTINCT symbol FROM versioned_market_bars ORDER BY symbol")
        symbols = [r[0] for r in cur.fetchall()]
        cur.close()
        runner = CatBoostHorizonRunner(root)
        print(f"building dataset from {len(symbols)} symbols ...")
        rows = runner.build_dataset(repo, symbols)
        print(f"dataset: {len(rows)} labeled (symbol, date) rows")
        if not rows:
            print("no rows — aborting (need bars with >= 20 history + 20 forward)")
            return
        acc = runner.train(rows)
        import json

        print("accuracy:", json.dumps(acc, indent=2)[:600])
    finally:
        uow.close()


if __name__ == "__main__":
    main()
