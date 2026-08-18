from pathlib import Path

from scripts.audit_download_output import (
    _audit_manifest_files,
    _audit_manifest_references,
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
