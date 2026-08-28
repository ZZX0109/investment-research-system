"""Train the vendored kittenCN ``TemporalHybridNet`` (§1 row-5 named model)
price-only on the universe's real daily bars.

Round 31.  Usage::

    NODE_ENV=development python3 -m scripts.train_temporal_vendored

Reads all symbols present in ``versioned_market_bars``, builds the 20-return /
next-return panel, fits the vendored ``TemporalHybridNet``, and writes
``artifacts/price_path/temporal_hybrid.pt`` + ``temporal_hybrid_accuracy.json``.
The trained model is served by ``TemporalVendoredRunner.forecast_path_for_symbol``
(the ``kittencn_adapter`` routes to it FIRST when available).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.training.price_path.temporal_vendored_runner import (
    TemporalVendoredRunner,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    root = Path(__file__).resolve().parent.parent
    uow = SQLiteUnitOfWork(get_default_database_path())
    repo = uow.trusted_market
    try:
        cur = uow.connection.cursor()
        cur.execute("SELECT DISTINCT symbol FROM versioned_market_bars ORDER BY symbol")
        symbols = [r[0] for r in cur.fetchall()]
        cur.close()
        runner = TemporalVendoredRunner(root)
        print(f"[vendored] building dataset from {len(symbols)} symbols ...")
        rows = runner.build_dataset(repo, symbols)
        print(f"[vendored] dataset: {len(rows)} (sequence, next-return) pairs")
        if not rows:
            print("[vendored] no rows — aborting (need bars with >= 22 closes)")
            return
        acc = runner.train(rows, epochs=3)
        print("[vendored] accuracy:", json.dumps(acc, indent=2, ensure_ascii=False))
    finally:
        uow.close()


if __name__ == "__main__":
    main()
