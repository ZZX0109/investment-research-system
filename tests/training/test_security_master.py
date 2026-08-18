from pathlib import Path
import json
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.build_cn_security_master import build_security_rows


def test_security_master_marks_unobserved_lifecycle_fields_degraded(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pq.write_table(pa.Table.from_pylist([
        {"symbol": "000001", "trade_date": "2020-01-02", "available_at": "2026-01-01T00:00:00Z", "provider": "x"},
        {"symbol": "000001", "trade_date": "2021-01-04", "available_at": "2026-01-01T00:00:00Z", "provider": "x"},
    ]), source / "part.parquet")
    industry = tmp_path / "industry.json"
    industry.write_text('{"symbols":{"000001":"bank"}}', encoding="utf-8")
    rows = build_security_rows(source, industry)
    assert len(rows) == 1
    assert rows[0]["effective_from"] == "2020-01-02"
    assert rows[0]["industry_key"] == "bank"
    assert rows[0]["missing_reason_code"] == "provider_not_covered"


def test_security_master_preserves_source_lifecycle_fields(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pq.write_table(pa.Table.from_pylist([
        {"symbol": "000001", "trade_date": "2020-01-02", "available_at": "2026-01-01T00:00:00Z", "provider": "x"},
    ]), source / "part.parquet")
    industry = tmp_path / "industry.json"
    industry.write_text('{"symbols":{}}', encoding="utf-8")
    raw_root = tmp_path / "raw"
    payload = raw_root / "raw-market" / "master.json"
    payload.parent.mkdir(parents=True)
    payload.write_text(json.dumps([{
        "code": "sz.000001", "code_name": "测试银行", "ipoDate": "1991-04-03",
        "outDate": "", "type": "1", "status": "1", "industry": "J66",
    }]), encoding="utf-8")
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (dataset TEXT, payload_json TEXT)")
    connection.execute("INSERT INTO raw_data_batches VALUES (?, ?)", (
        "cn_security_master_research",
        json.dumps({"symbol": "000001", "payload_ref": "file-object://raw-market/master.json"}),
    ))
    connection.commit()
    connection.close()

    rows = build_security_rows(source, industry, database, raw_root)

    assert rows[0]["listed_on"] == "1991-04-03"
    assert rows[0]["security_name"] == "测试银行"
    assert rows[0]["source_industry"] == "J66"
