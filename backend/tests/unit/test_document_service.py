from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.document_service import analyze_document_content, get_latest_document_analysis


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def build_source_meta(**kwargs):
    return {
        "mode": kwargs.get("mode", "demo"),
        "provider": kwargs["provider"],
        "as_of": kwargs["as_of"],
        "overrides": kwargs.get("overrides", []),
        "synthetic_ratio": kwargs.get("synthetic_ratio", 0.0),
    }


def test_get_latest_document_analysis_returns_demo_schema(app, test_db_path):
    fixed_now = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)

    analysis = get_latest_document_analysis(
        "UNIT",
        connect=make_connect(test_db_path),
        now_utc=lambda: fixed_now,
        iso=iso,
        build_source_meta=build_source_meta,
    )

    assert analysis["documentId"] == "demo-multimodal-pipeline"
    assert analysis["sourceType"] == "demo_cache"
    assert analysis["sourceMeta"]["synthetic_ratio"] == 1.0
    assert analysis["metrics"][0]["metric_value"] == "demo placeholder"
    assert analysis["blockPreviews"][0]["block_type"] == "text"


def test_analyze_document_content_persists_and_reads_uploaded_report(app, test_db_path):
    fixed_now = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
    connect = make_connect(test_db_path)
    content = b"Revenue,Gross margin,Free cash flow\n123,45%,67\nFootnote: unaudited sample values\n"

    analysis = analyze_document_content(
        "UNIT",
        "unit-report.csv",
        content,
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        build_source_meta=build_source_meta,
    )

    assert analysis["documentId"].startswith("UNIT-")
    assert analysis["filename"] == "unit-report.csv"
    assert analysis["uploadedAt"] == "2026-07-07T10:00:00Z"
    assert analysis["sourceType"] == "uploaded_report"
    assert analysis["sourceMeta"]["synthetic_ratio"] == 0.0
    assert any(item["metric_name"] == "Revenue" for item in analysis["metrics"])
    assert any(item["block_type"] in {"table", "footnote"} for item in analysis["blockPreviews"])

    with connect() as conn:
        document_count = conn.execute("select count(*) as count from multimodal_documents where symbol = 'UNIT'").fetchone()["count"]
        metric_count = conn.execute("select count(*) as count from financial_metrics where symbol = 'UNIT'").fetchone()["count"]
        block_count = conn.execute("select count(*) as count from document_blocks where symbol = 'UNIT'").fetchone()["count"]

    assert document_count == 1
    assert metric_count >= 1
    assert block_count >= 1
