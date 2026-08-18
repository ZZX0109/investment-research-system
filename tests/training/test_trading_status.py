import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.build_cn_trading_status import build_status_rows


def test_build_status_rows_deduplicates_symbol_date(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pq.write_table(pa.Table.from_pylist([
        {"symbol": "000001", "trade_date": "2026-01-02", "is_halted": False, "is_suspended": False, "is_limit_up": False, "is_limit_down": False, "is_one_price_limit": False, "is_tradeable": True, "published_at": "2026-01-02T00:00:00Z", "available_at": "2026-01-03T00:00:00Z", "revision": 1, "provider": "x", "raw_hash": "a" * 64},
        {"symbol": "000001", "trade_date": "2026-01-02", "is_halted": True, "is_suspended": True, "is_limit_up": False, "is_limit_down": False, "is_one_price_limit": False, "is_tradeable": False, "published_at": "2026-01-02T00:00:00Z", "available_at": "2026-01-04T00:00:00Z", "revision": 2, "provider": "x", "raw_hash": "b" * 64},
    ]), source / "part.parquet")
    rows = build_status_rows(source)
    assert len(rows) == 1
    assert rows[0]["is_suspended"] is True
    assert rows[0]["missing_reason_code"] == "published_time_unverified"
