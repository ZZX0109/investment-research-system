from __future__ import annotations

from datetime import date, timedelta

from ml.common import artifact_path, connect
from ml.data.build_dataset import build_dataset


def run() -> None:
    symbol = "ZZREALTEST"
    start = date(2021, 1, 1)
    synthetic_rows = []
    real_rows = []
    for idx in range(220):
        synthetic_rows.append((symbol, (start + timedelta(days=idx)).isoformat(), 100 + idx * 0.1, 1000, "synthetic_demo_price_path"))
        real_rows.append((symbol, (start + timedelta(days=400 + idx)).isoformat(), 150 + idx * 0.2, 2000, "yfinance historical"))
    with connect() as conn:
        conn.execute(
            """
            create table if not exists historical_prices (
              symbol text not null,
              trade_date text not null,
              close_price real not null,
              volume real not null,
              source_name text not null default 'synthetic_demo_price_path',
              primary key(symbol, trade_date)
            )
            """
        )
        conn.executemany(
            "insert or replace into historical_prices(symbol, trade_date, close_price, volume, source_name) values(?, ?, ?, ?, ?)",
            [*synthetic_rows, *real_rows],
        )
        conn.commit()
    dataset = build_dataset([symbol], artifact_path("datasets", "test_real_only_filter"), allow_synthetic=False, smoke=True)
    assert dataset["sampleCount"] > 0
    with open(artifact_path("datasets", "test_real_only_filter", "dataset.json"), encoding="utf-8") as handle:
        text = handle.read()
    assert "synthetic_demo_price_path" not in text
    assert "yfinance historical" in text


if __name__ == "__main__":
    run()
    print("test_real_only_filter ok")
