from datetime import datetime, timezone

from investment_research.training.free_research_adapter import normalize_free_daily_payload


def test_public_backfill_normalization_preserves_received_time_as_available_at() -> None:
    payload = b'''[{"('Date', '')":"2024-01-02T00:00:00.000","('Open', 'AAPL')":100,"('High', 'AAPL')":102,"('Low', 'AAPL')":99,"('Close', 'AAPL')":101,"('Volume', 'AAPL')":1200}]'''
    received_at = datetime(2026, 7, 14, 8, 45, tzinfo=timezone.utc)
    result = normalize_free_daily_payload(
        payload, market="us", symbol="AAPL", provider="yfinance", received_at=received_at,
    )
    assert len(result.bars) == 1
    bar = result.bars[0]
    assert bar.trade_date.isoformat() == "2024-01-02"
    assert bar.close_native == 101
    assert bar.available_at == received_at
    assert not result.formal_pit_eligible
    assert "historical_available_at_unproven_public_backfill" in result.blocking_reasons


def test_public_backfill_normalization_skips_invalid_rows() -> None:
    result = normalize_free_daily_payload(
        '[{"日期":"2024-01-02","开盘":10,"最高":11,"最低":9,"收盘":10,"成交量":100},{"日期":"bad","收盘":0}]'.encode(),
        market="cn", symbol="600519", provider="akshare",
        received_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    assert len(result.bars) == 1
    assert result.skipped_rows == 1
    assert result.bars[0].currency == "CNY"
