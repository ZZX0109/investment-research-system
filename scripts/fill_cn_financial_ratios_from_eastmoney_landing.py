#!/usr/bin/env python3
"""Fill symbol-level ratio coverage from already downloaded performance pages.

This is a local, research-only fallback for provider throttling.  It uses only
the immutable Eastmoney performance landing files, preserves report dates and
the landing payload hash in each row, and maps fields whose semantics are
explicit.  It does not invent liquidity/turnover fields that are absent from
the performance family.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.cn_universe import load_cn_symbols
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

METRIC_CONTRACT_VERSION = 3


def _period(value: Any) -> str | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _rows_for(symbol: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    period = _period(source.get("REPORTDATE") or source.get("UPDATE_DATE"))
    if period is None:
        return []
    metrics = (
        ("profit", "epsTTM", "BASIC_EPS", 1.0, "currency_per_share"),
        ("profit", "roeAvg", "WEIGHTAVG_ROE", 0.01, "ratio"),
        ("dupont", "dupontROE", "WEIGHTAVG_ROE", 0.01, "ratio"),
        ("profit", "gpMargin", "XSMLL", 0.01, "ratio"),
        ("growth", "YOYNI", "SJLTZ", 0.01, "ratio"),
        ("growth", "YOYPNI", "SJLTZ", 0.01, "ratio"),
    )
    rows: list[dict[str, Any]] = []
    for family, field, source_field, scale, unit in metrics:
        value = _number(source.get(source_field))
        if value is None:
            continue
        rows.append({
            "code": ("sh." if symbol.startswith(("6", "9")) else "sz.") + symbol,
            "statDate": f"{period[:4]}-{period[4:6]}-{period[6:8]}",
            "report_period": period,
            "feature_family": family,
            field: value * scale,
            "unit": unit,
            "basis": "eastmoney_performance_report_period",
            "source_metric_label": source_field,
            "source_value_field": source_field,
            "pubDate": source.get("NOTICE_DATE"),
            "available_at": None,
            "revision_id": source.get("UPDATE_DATE"),
            "source_publication_status": "report_notice_date_only",
            "source_provider": "eastmoney_performance_landing",
            "source_mode": "eastmoney_performance_landing_fallback",
            "landing_payload_sha256": source.get("_landing_payload_sha256"),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--landing-root", type=Path, default=PROJECT / "artifacts/cn_financial_reports_eastmoney")
    parser.add_argument("--progress", type=Path, default=PROJECT / "artifacts/cn_financial_ratios_akshare/progress.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_financial_ratios_akshare/landing_fallback.json")
    parser.add_argument("--latest", type=Path, default=PROJECT / "artifacts/cn_financial_ratios_akshare/latest.json")
    args = parser.parse_args()

    universe = load_cn_symbols(
        PROJECT / "artifacts/cn_security_master_universe/security_master_current.json",
        exclude_etf=True,
    )
    progress = json.loads(args.progress.read_text(encoding="utf-8")) if args.progress.exists() else {"symbols": {}}
    states = progress.setdefault("symbols", {})

    latest: dict[str, dict[str, Any]] = {}
    files = sorted((args.landing_root / "landing").glob("eastmoney-performance-*/**/page-*.json"))
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            payload = document.get("payload", {})
            rows = payload.get("result", {}).get("data", [])
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            continue
        if not isinstance(rows, list):
            continue
        digest = document.get("raw_payload_sha256")
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("SECURITY_CODE") or "").zfill(6)
            if symbol not in universe:
                continue
            candidate = {**row, "_landing_payload_sha256": digest}
            period = _period(row.get("REPORTDATE") or row.get("UPDATE_DATE")) or ""
            previous = latest.get(symbol)
            previous_period = _period(previous.get("REPORTDATE") or previous.get("UPDATE_DATE")) if previous else ""
            if previous is None or period > (previous_period or ""):
                latest[symbol] = candidate

    pending = [symbol for symbol in universe if states.get(symbol, {}).get("status") != "complete"]
    uow = SQLiteUnitOfWork(args.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
    completed = 0
    failures: dict[str, str] = {}
    try:
        for symbol in pending:
            rows = _rows_for(symbol, latest.get(symbol, {}))
            if not rows:
                failures[symbol] = "eastmoney_performance_metrics_unavailable"
                states[symbol] = {"status": "failed", "reason": failures[symbol]}
                continue
            now = datetime.now(timezone.utc)
            batch = service.persist(
                provider="eastmoney_performance_landing",
                request_id=f"cn-financial-ratios-eastmoney-landing-{symbol}-{uuid4()}",
                dataset="cn_financial_ratios_akshare_research",
                payload=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(),
                schema_version="cn-financial-ratios-akshare-v1",
                symbol=symbol,
                available_at=now,
                received_at=now,
                market_session="research_backfill_landing_fallback",
                data_tier=DataTier.RESEARCH_PIT,
            )
            states[symbol] = {
                "status": "complete",
                "row_count": len(rows),
                "metric_count": len(rows),
                "payload_hash": batch.payload_hash,
                "raw_batch_id": str(batch.id),
                "metric_contract_version": METRIC_CONTRACT_VERSION,
                "source_mode": "eastmoney_performance_landing_fallback",
            }
            completed += 1
            if completed % 100 == 0:
                args.progress.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"filled {completed}/{len(pending)}", flush=True)
    finally:
        uow.close()
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    args.progress.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": "cn-financial-ratios-eastmoney-landing-fallback-v1",
        "status": "complete" if not failures else "partial",
        "target_equity_count": len(universe),
        "completed_equity_count": sum(
            1 for symbol in universe
            if states.get(symbol, {}).get("status") == "complete"
            and states.get(symbol, {}).get("metric_contract_version") == METRIC_CONTRACT_VERSION
        ),
        "filled_this_run": completed,
        "failed_equity_count": len(failures),
        "failures": failures,
        "research_only": True,
        "formal_pit_verified": False,
        "source_mode": "eastmoney_performance_landing_fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep the canonical ratio summary consistent with the resumable progress
    # ledger.  This is still research-only; it must not erase the PIT gate.
    canonical = {
        "schema_version": "cn-financial-ratios-akshare-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "provider": "akshare_sina_financial_abstract+eastmoney_performance_landing",
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "target_equity_count": len(universe),
        "completed_equity_count": report["completed_equity_count"],
        "failed_equity_count": report["failed_equity_count"],
        "row_count": sum(int(value.get("row_count", 0) or 0) for value in states.values() if value.get("status") == "complete"),
        "metric_count": sum(int(value.get("metric_count", 0) or 0) for value in states.values() if value.get("status") == "complete"),
        "failures": failures,
        "published_at_coverage": 0.0,
        "available_at_coverage": 1.0,
        "revision_coverage": 1.0,
        "missing_reason": "source provides report period but not verified first publication time",
        "missing_reason_code": "published_time_unverified",
        "status": report["status"],
        "generated_at": report["generated_at"],
    }
    args.latest.parent.mkdir(parents=True, exist_ok=True)
    args.latest.write_text(json.dumps(canonical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
