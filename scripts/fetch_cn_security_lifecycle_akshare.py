#!/usr/bin/env python3
"""Download public CN listing, delisting, name and industry history tables."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_security_lifecycle_akshare")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    target = json.loads(args.target_symbols.read_text(encoding="utf-8"))
    symbols = sorted({str(item).zfill(6) for item in target.get("cn", []) if str(item).zfill(6) not in ETF_SYMBOLS})
    import akshare as ak

    one_shot = {}
    failures = {}
    for name in ("stock_info_sh_delist", "stock_info_sz_delist", "stock_info_sh_name_code", "stock_info_sz_name_code", "stock_info_sz_change_name", "stock_report_disclosure"):
        try:
            frame = getattr(ak, name)()
            one_shot[name] = _records(frame)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}:{exc}"

    history: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        futures = {pool.submit(_industry_history, ak, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                history[symbol] = future.result()
            except Exception as exc:
                history[symbol] = []
                failures[f"industry:{symbol}"] = f"{type(exc).__name__}:{exc}"
            print(f"industry {len(history)}/{len(symbols)} {symbol}", flush=True)

    uow = SQLiteUnitOfWork(args.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
    now = datetime.now(timezone.utc)
    try:
        for dataset, rows in one_shot.items():
            _persist(service, dataset, "CN", rows, now)
        for symbol, rows in history.items():
            _persist(service, "cn_security_industry_history_akshare", symbol, rows, now)
    finally:
        uow.close()

    normalized = _normalize(symbols, one_shot, history, now)
    _write(args.output_root / "security_lifecycle.json", normalized)
    report = {
        "schema_version": "cn-security-lifecycle-akshare-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "target_equity_count": len(symbols),
        "industry_history_symbol_count": sum(bool(rows) for rows in history.values()),
        "listing_date_coverage": sum(bool(row.get("listed_on")) for row in normalized) / len(normalized) if normalized else 0.0,
        "delisting_date_coverage": sum(bool(row.get("delisted_on")) for row in normalized) / len(normalized) if normalized else 0.0,
        "industry_history_coverage": sum(bool(row.get("industry_history")) for row in normalized) / len(normalized) if normalized else 0.0,
        "st_status_coverage": 0.0,
        "code_change_coverage": sum(bool(row.get("name_changes")) for row in normalized) / len(normalized) if normalized else 0.0,
        "published_at_coverage": 0.0,
        "available_at_coverage": 1.0 if normalized else 0.0,
        "failures": failures,
        "missing_reason": "public tables provide effective dates but not a complete historical ST/availability publication contract",
        "missing_reason_code": "historical_lifecycle_partial",
        "status": "complete" if not failures else "partial",
        "generated_at": now.isoformat(),
    }
    _write(args.output_root / "latest.json", report)
    print(json.dumps({k: report[k] for k in ("status", "target_equity_count", "industry_history_symbol_count", "listing_date_coverage", "delisting_date_coverage", "industry_history_coverage", "code_change_coverage")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _industry_history(ak, symbol: str) -> list[dict]:
    frame = ak.stock_industry_change_cninfo(symbol=symbol, start_date="19900101", end_date=datetime.now().strftime("%Y%m%d"))
    return _records(frame)


def _records(frame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", force_ascii=False, date_format="iso"))


def _persist(service, dataset: str, symbol: str, rows: list[dict], now: datetime) -> None:
    service.persist(
        provider="akshare_cn_lifecycle",
        request_id=f"cn-lifecycle-{dataset}-{symbol}-{uuid4()}",
        dataset=dataset,
        payload=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(),
        schema_version="cn-security-lifecycle-akshare-v1",
        symbol=symbol,
        available_at=now,
        received_at=now,
        market_session="research_backfill",
        data_tier=DataTier.RESEARCH_PIT,
    )


def _normalize(symbols: list[str], tables: dict[str, list[dict]], history: dict[str, list[dict]], now: datetime) -> list[dict]:
    listed: dict[str, dict] = {}
    for name in ("stock_info_sh_name_code", "stock_info_sz_name_code"):
        for row in tables.get(name, []):
            code = str(row.get("证券代码") or row.get("A股代码") or "").zfill(6)
            if code in symbols:
                listed[code] = row
    delisted: dict[str, dict] = {}
    for name in ("stock_info_sh_delist", "stock_info_sz_delist"):
        for row in tables.get(name, []):
            code = str(row.get("公司代码") or row.get("证券代码") or "").zfill(6)
            if code in symbols:
                delisted[code] = row
    names = {}
    for row in tables.get("stock_info_sz_change_name", []):
        code = str(row.get("证券代码") or "").zfill(6)
        if code in symbols:
            names.setdefault(code, []).append(row)
    output = []
    for symbol in symbols:
        base = listed.get(symbol, {})
        end = delisted.get(symbol, {})
        industry = history.get(symbol, [])
        output.append({
            "symbol": symbol,
            "listed_on": str(base.get("上市日期") or base.get("A股上市日期") or "")[:10] or str(end.get("上市日期") or "")[:10] or None,
            "delisted_on": str(end.get("终止上市日期") or end.get("暂停上市日期") or "")[:10] or None,
            "security_name": base.get("证券简称") or base.get("A股简称") or end.get("公司简称"),
            "industry_current": base.get("所属行业"),
            "industry_history": industry,
            "name_changes": names.get(symbol, []),
            "available_at": now.isoformat(),
            "published_at": None,
            "revision_id": None,
            "data_tier": DataTier.RESEARCH_PIT.value,
            "quality_status": "degraded",
            "missing_reason_code": "historical_lifecycle_partial",
        })
    return output


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
