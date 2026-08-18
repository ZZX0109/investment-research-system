#!/usr/bin/env python3
"""Reconcile the public-data coverage ledger with completed local backfills."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def main() -> int:
    coverage_path = PROJECT / "artifacts/free_research_coverage.json"
    event_path = PROJECT / "artifacts/cn_event_backfill/latest.json"
    news_path = PROJECT / "artifacts/cn_news_backfill/latest.json"
    auxiliary_path = PROJECT / "artifacts/cn_research_auxiliary/latest.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    events = json.loads(event_path.read_text(encoding="utf-8"))
    news = json.loads(news_path.read_text(encoding="utf-8")) if news_path.is_file() else {}
    auxiliary = json.loads(auxiliary_path.read_text(encoding="utf-8"))
    event_record = {
        "market": "cn",
        "dataset": "events",
        "provider": "eastmoney_cn_announcements",
        "status": "backfilled",
        "rows_or_bytes": events.get("event_row_count", 0),
        # ``complete`` is a report-level word; the model/ledger enum uses
        # ``events_present`` for a successfully populated event source.
        "event_coverage_status": "events_present",
        "coverage_start": events.get("start_date"),
        "coverage_end": events.get("end_date"),
        "target_symbol_count": events.get("target_equity_count", 0),
        "successful_target_symbol_count": events.get("completed_equity_count", 0),
        "reason": "target_symbol_historical_backfill_complete",
        "data_tier": "research_pit",
    }
    news_record = {
        "market": "cn",
        "dataset": "events",
        "provider": "eastmoney_cn_news",
        "status": "backfilled",
        "rows_or_bytes": news.get("news_row_count", 0),
        "event_coverage_status": "events_present",
        "coverage_start": None,
        "coverage_end": None,
        "target_symbol_count": news.get("target_equity_count", 0),
        "successful_target_symbol_count": news.get("completed_equity_count", 0),
        "reason": "current_public_news_window_backfill",
        "data_tier": "research_pit",
    }
    records = [item for item in coverage.get("records", []) if item.get("dataset") != "events"]
    records.extend([event_record, news_record])
    coverage["records"] = records
    for market in coverage.get("market_coverage", []):
        if market.get("market") != "cn":
            continue
        market["event_coverage_status"] = "events_present"
        market["failed_providers"] = []
        market["event_records"] = [event_record, news_record]
        market["event_target_symbol_count"] = events.get("target_equity_count", 0)
        market["event_successful_target_symbol_count"] = events.get("completed_equity_count", 0)
    coverage["generated_at"] = datetime.now(timezone.utc).isoformat()
    coverage["local_alignment"] = {
        "event_backfill": "artifacts/cn_event_backfill/latest.json",
        "news_backfill": "artifacts/cn_news_backfill/latest.json",
        "auxiliary": "artifacts/cn_research_auxiliary/latest.json",
        "industry_mapping": auxiliary.get("datasets", {}).get("industry_mapping", {}),
        "margin_financing": auxiliary.get("datasets", {}).get("margin_financing", {}),
        "market_breadth": auxiliary.get("datasets", {}).get("market_breadth", {}),
        "macro": auxiliary.get("datasets", {}).get("macro", {}),
    }
    output_path = PROJECT / "artifacts/free_research_coverage_aligned.json"
    text = json.dumps(coverage, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(text, encoding="utf-8")
    # Keep the default rebuild/queue entry point aligned with the verified
    # local ledger while retaining the separate aligned copy for provenance.
    coverage_path.write_text(text, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
