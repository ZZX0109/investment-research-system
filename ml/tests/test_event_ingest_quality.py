from __future__ import annotations

from datetime import date, timedelta

from ml.common import connect
from ml.data.ingest_events import insert_evidence
from ml.data.quality import symbol_quality_report


def run() -> None:
    symbol = "ZZEVENTTEST"
    start = date(2024, 1, 1)
    with connect() as conn:
        conn.execute("delete from evidence_records where symbol = ?", (symbol,))
        conn.execute("delete from historical_prices where symbol = ?", (symbol,))
        conn.execute("delete from point_in_time_features where symbol = ?", (symbol,))
        conn.executemany(
            "insert or replace into historical_prices(symbol, trade_date, close_price, volume, source_name) values(?, ?, ?, ?, ?)",
            [
                (symbol, (start + timedelta(days=idx)).isoformat(), 100 + idx, 1000 + idx, "yfinance historical")
                for idx in range(150)
            ],
        )
        conn.execute(
            """
            insert into evidence_records(symbol, claim, source_type, source_name, source_url, observed_at, valid_until, confidence, is_model_inferred)
            values(?, 'demo placeholder', 'news_event', 'demo placeholder', null, '2024-01-01T00:00:00Z', '2024-01-02T00:00:00Z', 0.9, 0)
            """,
            (symbol,),
        )
        conn.commit()

    before = symbol_quality_report(symbol)
    assert before["requirements"]["newsPublishedAt"] is False

    insert_evidence(
        symbol,
        "news_event",
        "ZZEVENTTEST news publishedAt=2024-02-01T00:00:00Z: real timestamped event",
        "yfinance news",
        "https://example.com/news",
        "2024-02-01T00:00:00Z",
        7,
        0.72,
    )
    insert_evidence(
        symbol,
        "disclosure",
        "ZZEVENTTEST authority disclosure availableAt=2024-02-02T00:00:00Z",
        "SEC EDGAR submissions",
        "https://example.com/filing",
        "2024-02-02T00:00:00Z",
        90,
        0.88,
    )
    insert_evidence(
        symbol,
        "financial_report",
        "ZZEVENTTEST financial report availableAt=2024-02-02T00:00:00Z",
        "SEC EDGAR submissions",
        "https://example.com/filing",
        "2024-02-02T00:00:00Z",
        120,
        0.84,
    )
    after = symbol_quality_report(symbol)
    assert after["requirements"]["newsPublishedAt"] is True
    assert after["requirements"]["announcementPublishedAt"] is True
    assert after["requirements"]["filingAvailableAt"] is True
    assert after["requirements"]["haltsMissingValues"] is True


if __name__ == "__main__":
    run()
    print("test_event_ingest_quality ok")
