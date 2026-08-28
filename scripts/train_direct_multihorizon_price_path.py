"""Train the independent direct 20-session price-path model.

Usage: ``NODE_ENV=development python3 -m scripts.train_direct_multihorizon_price_path``.
It writes only ``artifacts/price_path/direct_multihorizon`` and never replaces
the older temporal model artifacts.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.training.price_path.direct_multihorizon_runner import DirectMultiHorizonPricePathRunner


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    root = Path(__file__).resolve().parent.parent
    uow = SQLiteUnitOfWork(get_default_database_path())
    try:
        cursor = uow.connection.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM versioned_market_bars WHERE interval = '1d' ORDER BY symbol")
        symbols = [row[0] for row in cursor.fetchall()]
        cursor.close()
        runner = DirectMultiHorizonPricePathRunner(root)
        print(f"[direct-path] building 60d -> 20d samples from {len(symbols)} symbols ...")
        samples, market_features, _ = runner.build_dataset(uow.trusted_market, symbols)
        print(f"[direct-path] samples: {len(samples)}")
        print(json.dumps(runner.train(samples, market_features), ensure_ascii=False, indent=2))
    finally:
        uow.close()


if __name__ == "__main__":
    main()
