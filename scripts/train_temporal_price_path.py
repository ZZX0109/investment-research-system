"""§1 row-5 kittenCN temporal training (round 29) — price-only temporal LSTM.

Reads ALL daily bars from ``versioned_market_bars`` (round 26), builds per-symbol
(20-return sequence, next-day return) pairs, trains the 1-layer LSTM with MSE,
and writes the ``.pt`` weight + an accuracy artifact.  The trained model is
served by ``TemporalPricePathRunner.forecast_path_for_symbol`` (the
``kittencn_adapter`` routes to it when available).

Usage:
    NODE_ENV=development python3 -m scripts.train_temporal_price_path
"""
from __future__ import annotations

import logging

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.training.price_path.temporal_runner import TemporalPricePathRunner


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
        runner = TemporalPricePathRunner(root)
        print(f"building dataset from {len(symbols)} symbols ...")
        rows = runner.build_dataset(repo, symbols)
        print(f"dataset: {len(rows)} (sequence, next-return) pairs")
        if not rows:
            print("no rows — aborting (need bars with >= 22 closes)")
            return
        acc = runner.train(rows, epochs=3)
        import json

        print("accuracy:", json.dumps(acc, indent=2))
    finally:
        uow.close()


if __name__ == "__main__":
    main()
