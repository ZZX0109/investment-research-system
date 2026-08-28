from pathlib import Path
import hashlib
import json
import sqlite3

from scripts.audit_download_output import (
    _audit_manifest_files,
    _audit_manifest_references,
    _database_records,
    _coverage_record,
    _event_semantics_errors,
)


def test_download_manifest_reference_and_content_audit_fail_closed(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    payload = raw_root / "bars.json"
    payload.write_text(
        '[{"symbol":"000001","trade_date":"2026-08-17","open":10,"high":11,"low":9,"close":10, '
        '"published_at":"2026-08-17T08:00:00+00:00","available_at":"2026-08-17T08:01:00+00:00"}]',
        encoding="utf-8",
    )
    records = [{
        "dataset": "daily_bars_raw",
        "output_path": str(payload),
        "sha256": "0" * 64,
        "status": "complete",
    }, {
        "dataset": "daily_bars_qfq",
        "output_path": None,
        "sha256": None,
        "status": "complete",
    }]
    _audit_manifest_references(records, raw_root)
    _audit_manifest_files(records, raw_root)
    assert records[0]["reference_error_count"] == 1
    assert records[0]["schema_valid"] is True
    assert records[1]["reference_error_count"] == 1
    assert records[1]["schema_valid"] is False


def test_download_audit_rejects_ambiguous_event_absence() -> None:
    assert _event_semantics_errors([
        {
            "category": "events",
            "dataset": "events",
            "quality_status": "degraded",
            "missing_reason": "no events",
        },
    ]) == ["unqualified_no_event_statement"]

    assert _event_semantics_errors([
        {
            "category": "events",
            "dataset": "events",
            "quality_status": "degraded",
            "missing_reason": "provider has no historical coverage",
            "missing_reason_code": "provider_not_covered",
        },
    ]) == []

    assert _event_semantics_errors([
        {
            "category": "events",
            "dataset": "events",
            "quality_status": "complete",
            "missing_reason_code": "pending_backfill",
        },
    ]) == ["complete_event_record_has_missing_reason"]

    assert _event_semantics_errors([
        {
            "category": "events",
            "dataset": "events",
            "quality_status": "complete",
            "missing_reason": "no_events_confirmed",
            "missing_reason_code": "no_events_confirmed",
        },
    ]) == []


def test_download_coverage_does_not_promote_unknown_collection_time_to_full_coverage() -> None:
    record = _coverage_record(
        {"dataset": "daily_bars_raw", "status": "complete", "rows_or_bytes": 1},
        Path("/tmp/raw"),
    )
    assert record["collected_at_coverage"] is None


def test_completed_event_operational_note_is_not_missing_semantics() -> None:
    record = _coverage_record(
        {
            "dataset": "events",
            "status": "backfilled",
            "reason": "target_symbol_historical_backfill_complete",
            "rows_or_bytes": 12,
        },
        Path("/tmp/raw"),
    )
    assert record["quality_status"] == "complete"
    assert record["missing_reason"] is None
    assert record["missing_reason_code"] is None
    assert _event_semantics_errors([record]) == []


def test_passed_catalog_event_batch_has_no_pending_missing_reason(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    payload_path = raw_root / "events.json"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_text("[]", encoding="utf-8")
    digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (provider TEXT, dataset TEXT, available_at TEXT, quality_status TEXT, payload_json TEXT)")
    connection.execute(
        "INSERT INTO raw_data_batches VALUES (?, ?, ?, ?, ?)",
        ("provider", "events", "2026-08-20T08:00:00Z", "passed", json.dumps({"payload_ref": "file-object://events.json", "payload_hash": digest, "row_count": 0})),
    )
    connection.commit()
    connection.close()

    record = _database_records(database, raw_root)[0]
    assert record["quality_status"] == "complete"
    assert record["missing_reason"] is None
    assert record["missing_reason_code"] is None
