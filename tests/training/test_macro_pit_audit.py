import json
import sqlite3
from pathlib import Path

from scripts.build_cn_macro_pit import build_report


def test_macro_audit_preserves_observation_and_blocks_missing_release_time(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    payload = raw_root / "raw-market" / "macro.json"
    payload.parent.mkdir(parents=True)
    payload.write_text(json.dumps([{"月份": "2026年07月份", "M2": 7.7}]), encoding="utf-8")
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (provider TEXT, dataset TEXT, available_at TEXT, payload_json TEXT)")
    connection.execute("INSERT INTO raw_data_batches VALUES (?, ?, ?, ?)", (
        "provider", "cn_macro_m2", "2026-08-01T00:00:00Z",
        json.dumps({"payload_ref": "file-object://raw-market/macro.json", "payload_hash": "a" * 64, "fetched_at": "2026-08-01T00:00:00Z"}),
    ))
    connection.commit()
    connection.close()

    report = build_report(database, raw_root, tmp_path / "out")

    assert report["record_count"] == 1
    assert report["published_at_coverage"] == 0.0
    assert report["quality_status"] == "degraded"
    row = json.loads((tmp_path / "out/macro_pit.jsonl").read_text().splitlines()[0])
    assert row["observation_period"] == "2026-07-01"
    assert row["missing_reason_code"] == "published_time_unverified"
