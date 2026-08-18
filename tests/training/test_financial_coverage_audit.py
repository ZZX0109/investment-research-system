import json
import sqlite3
from pathlib import Path

from scripts.audit_cn_financial_coverage import REQUIRED_FIELDS, audit


def test_financial_audit_counts_field_cells_and_keeps_pit_blocked(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    payload_dir = raw_root / "raw-market"
    payload_dir.mkdir(parents=True)
    database = tmp_path / "catalog.db"
    target = tmp_path / "targets.json"
    target.write_text(json.dumps({"cn": ["000001"]}), encoding="utf-8")
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE raw_data_batches (dataset TEXT, available_at TEXT, payload_json TEXT)"
    )
    for family, fields in REQUIRED_FIELDS.items():
        payload_path = payload_dir / f"{family}.json"
        record = {
            "code": "sz.000001",
            "pubDate": "2026-04-30",
            "statDate": "2026-03-31",
            "feature_family": family,
            **{field: "1" for field in fields},
        }
        payload_path.write_text(json.dumps([record]), encoding="utf-8")
        metadata = {
            "symbol": "000001",
            "payload_ref": f"file-object://raw-market/{family}.json",
        }
        connection.execute(
            "INSERT INTO raw_data_batches VALUES (?, ?, ?)",
            ("cn_fundamentals_research", "2026-08-01T00:00:00Z", json.dumps(metadata)),
        )
    connection.commit()
    connection.close()

    report = audit(database, raw_root, target, minimum_coverage=0.95)

    assert report["target_field_count"] == report["observed_field_count"]
    assert report["coverage"] == 1.0
    assert report["pit_verified"] is False
    assert report["quality_status"] == "degraded"
