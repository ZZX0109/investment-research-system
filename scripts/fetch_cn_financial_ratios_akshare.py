#!/usr/bin/env python3
"""Backfill missing CN financial ratios from AkShare's public Sina table.

This collector improves value coverage but deliberately does not claim PIT:
the source exposes report dates, not a verified first-publication timestamp.
Rows are stored as a separate append-only dataset until that timestamp can be
joined to an authoritative disclosure record.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

ETF_SYMBOLS = {"159915", "510050", "510300", "510500", "512100"}
METRIC_MAP = {
    "毛利率": ("profit", "gpMargin", 0.01, "ratio"),
    "应收账款周转率": ("operation", "NRTurnRatio", 1.0, "times"),
    "存货周转率": ("operation", "INVTurnRatio", 1.0, "times"),
    "流动比率": ("balance", "currentRatio", 1.0, "ratio"),
    "速动比率": ("balance", "quickRatio", 1.0, "ratio"),
    "现金比率": ("balance", "cashRatio", 0.01, "ratio"),
    "经营活动净现金/归属母公司的净利润": ("cash_flow", "CFOToNP", 1.0, "ratio"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_financial_ratios_akshare")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.target_symbols.read_text(encoding="utf-8"))
    symbols = sorted({str(item).zfill(6) for item in payload.get("cn", []) if str(item).zfill(6) not in ETF_SYMBOLS})
    progress_path = args.output_root / "progress.json"
    progress = _read(progress_path) if progress_path.exists() and not args.no_resume else {"symbols": {}}
    progress.setdefault("symbols", {})
    pending = [symbol for symbol in symbols if progress["symbols"].get(symbol, {}).get("status") != "complete"]
    print(f"target_equities={len(symbols)} pending={len(pending)}", flush=True)

    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        futures = {pool.submit(_fetch_symbol, symbol): symbol for symbol in pending}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                fetched[symbol] = future.result()
            except Exception as exc:
                fetched[symbol] = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
            print(f"fetched {len(fetched)}/{len(pending)} {symbol} {fetched[symbol].get('status')}", flush=True)

    uow = SQLiteUnitOfWork(args.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
    try:
        for symbol, result in sorted(fetched.items()):
            if result.get("status") != "complete":
                progress["symbols"][symbol] = result
                _write(progress_path, progress)
                continue
            now = datetime.now(timezone.utc)
            raw = json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode()
            batch = service.persist(
                provider="akshare_sina_financial_abstract",
                request_id=f"cn-financial-ratios-akshare-{symbol}-{uuid4()}",
                dataset="cn_financial_ratios_akshare_research",
                payload=raw,
                schema_version="cn-financial-ratios-akshare-v1",
                symbol=symbol,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
            progress["symbols"][symbol] = {
                "status": "complete", "row_count": len(result["rows"]),
                "metric_count": result["metric_count"], "payload_hash": batch.payload_hash,
                "raw_batch_id": str(batch.id),
            }
            _write(progress_path, progress)
    finally:
        uow.close()

    completed = [item for item in progress["symbols"].values() if item.get("status") == "complete"]
    failures = {key: value for key, value in progress["symbols"].items() if value.get("status") != "complete"}
    report = {
        "schema_version": "cn-financial-ratios-akshare-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "provider": "akshare_sina_financial_abstract",
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(failures),
        "row_count": sum(int(item.get("row_count", 0)) for item in completed),
        "metric_count": sum(int(item.get("metric_count", 0)) for item in completed),
        "failures": failures,
        "published_at_coverage": 0.0,
        "available_at_coverage": 1.0 if completed else 0.0,
        "revision_coverage": 1.0 if completed else 0.0,
        "missing_reason": "source provides report period but not verified first publication time",
        "missing_reason_code": "published_time_unverified",
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(args.output_root / "latest.json", report)
    print(json.dumps({k: report[k] for k in ("status", "completed_equity_count", "row_count", "metric_count")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _fetch_symbol(symbol: str) -> dict[str, Any]:
    import math
    import akshare as ak

    frame = ak.stock_financial_abstract(symbol=symbol)
    if frame is None or frame.empty:
        return {"status": "failed", "reason": "empty_financial_abstract"}
    columns = [str(value) for value in frame.columns if str(value).isdigit() and len(str(value)) == 8]
    rows: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        metric = str(source.get("指标") or "").strip()
        spec = METRIC_MAP.get(metric)
        if spec is None:
            continue
        family, field, scale, unit = spec
        for report_date in columns:
            value = source.get(report_date)
            try:
                value = float(value)
                if not math.isfinite(value):
                    continue
            except (TypeError, ValueError):
                continue
            rows.append({
                "code": ("sh." if symbol.startswith(("6", "9")) else "sz.") + symbol,
                "statDate": f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}",
                "report_period": report_date,
                "feature_family": family,
                field: value * scale,
                "unit": unit,
                "basis": "cumulative_or_report_period_as_provided_by_source",
                "pubDate": None,
                "available_at": None,
                "revision_id": None,
                "source_publication_status": "unverified",
                "source_provider": "sina_financial_abstract_via_akshare",
            })
    return {"status": "complete", "rows": rows, "metric_count": len({row["feature_family"] + row["statDate"] for row in rows})}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
