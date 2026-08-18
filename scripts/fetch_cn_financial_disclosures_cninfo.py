#!/usr/bin/env python3
"""Download CNINFO financial-report announcement timestamps for the target pool.

CNINFO exposes an announcement timestamp, which is stronger PIT evidence than a
report period alone.  This collector stores the original announcement metadata
as a research-only dataset; it does not claim that every announcement can be
perfectly joined to every provider's financial statement row.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STOCK_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
ETF_SYMBOLS = {"159915", "510050", "510300", "510500", "512100"}
CATEGORIES = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
    "补充更正": "category_bcgz_szsh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_financial_disclosures_cninfo")
    parser.add_argument("--start-date", default="2010-01-01")
    parser.add_argument("--end-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    target = json.loads(args.target_symbols.read_text(encoding="utf-8"))
    symbols = sorted({str(value).zfill(6) for value in target["cn"] if str(value).zfill(6) not in ETF_SYMBOLS})
    if args.max_symbols is not None:
        symbols = symbols[: args.max_symbols]
    progress_path = args.output_root / "progress.json"
    progress = _read(progress_path) if progress_path.exists() and not args.no_resume else {"symbols": {}}
    progress.setdefault("symbols", {})
    pending = [symbol for symbol in symbols if progress["symbols"].get(symbol, {}).get("status") != "complete"]
    print(f"target_equities={len(symbols)} pending={len(pending)}", flush=True)

    org_ids = _load_org_ids()
    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        futures = {
            pool.submit(_fetch_symbol, symbol, org_ids.get(symbol), args.start_date, args.end_date): symbol
            for symbol in pending
        }
        for index, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
            fetched[symbol] = result
            print(f"fetched {index}/{len(pending)} {symbol} {result.get('status')}", flush=True)

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
                provider="cninfo_financial_disclosures",
                request_id=f"cn-financial-disclosures-{symbol}-{args.start_date}-{args.end_date}-{uuid4()}",
                dataset="cn_financial_disclosures_cninfo_research",
                payload=raw,
                schema_version="cn-financial-disclosures-cninfo-v1",
                symbol=symbol,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
            progress["symbols"][symbol] = {
                "status": "complete",
                "row_count": len(result["rows"]),
                "published_at_count": sum(bool(row.get("published_at")) for row in result["rows"]),
                "payload_hash": batch.payload_hash,
                "raw_batch_id": str(batch.id),
            }
            _write(progress_path, progress)
    finally:
        uow.close()

    completed = [item for item in progress["symbols"].values() if item.get("status") == "complete"]
    failures = {key: value for key, value in progress["symbols"].items() if value.get("status") != "complete"}
    total_rows = sum(int(item.get("row_count", 0)) for item in completed)
    published_rows = sum(int(item.get("published_at_count", 0)) for item in completed)
    report = {
        "schema_version": "cn-financial-disclosures-cninfo-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "provider": "cninfo_financial_disclosures",
        "categories": list(CATEGORIES),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(failures),
        "row_count": total_rows,
        "published_at_count": published_rows,
        "published_at_coverage": published_rows / total_rows if total_rows else 0.0,
        "available_at_coverage": 1.0 if completed else 0.0,
        "revision_coverage": 1.0 if completed else 0.0,
        "failures": failures,
        "missing_reason": "announcement timestamps are available, but statement-period joins and historical source visibility still require an explicit reconciliation step",
        "missing_reason_code": "financial_period_join_unverified",
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(args.output_root / "latest.json", report)
    print(json.dumps({k: report[k] for k in ("status", "completed_equity_count", "row_count", "published_at_count")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _load_org_ids() -> dict[str, str]:
    import requests

    response = requests.get(STOCK_URL, timeout=40)
    response.raise_for_status()
    return {str(item.get("code")).zfill(6): str(item.get("orgId")) for item in response.json().get("stockList", [])}


def _fetch_symbol(symbol: str, org_id: str | None, start_date: str, end_date: str) -> dict[str, Any]:
    import requests

    if not org_id:
        return {"status": "failed", "reason": "cninfo_org_id_missing"}
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ResearchBackfill/1.0)"})
    rows: list[dict[str, Any]] = []
    try:
        for category, category_code in CATEGORIES.items():
            base = {
                "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
                "plate": "", "stock": f"{symbol},{org_id}", "searchkey": "", "secid": "",
                "category": category_code, "trade": "", "seDate": f"{start_date}~{end_date}",
                "sortName": "", "sortType": "", "isHLtitle": "true",
            }
            first = _post(session, base)
            total = int(first.get("totalAnnouncement") or 0)
            pages = max(1, (total + 29) // 30)
            for page in range(1, pages + 1):
                payload = dict(base, pageNum=str(page))
                data = first if page == 1 else _post(session, payload)
                for item in data.get("announcements") or []:
                    row = _normalize(item, symbol, category)
                    if row:
                        rows.append(row)
                time.sleep(0.03)
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            unique[str(row.get("announcement_id") or row)] = row
        return {"status": "complete", "rows": list(unique.values())}
    except Exception as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}


def _post(session, payload: dict[str, str]) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(4):
        try:
            response = session.post(URL, params=payload, data=payload, timeout=40)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or "announcements" not in data:
                raise RuntimeError("cninfo_invalid_response")
            return data
        except Exception as exc:
            last = exc
            time.sleep(1.0 + attempt)
    raise last or RuntimeError("cninfo_request_failed")


def _normalize(item: dict[str, Any], symbol: str, category: str) -> dict[str, Any] | None:
    value = item.get("announcementTime")
    try:
        timestamp = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).astimezone().isoformat() if value else None
    except (TypeError, ValueError, OverflowError):
        timestamp = None
    if not timestamp:
        return None
    code = str(item.get("secCode") or symbol).zfill(6)
    return {
        "symbol": code,
        "security_name": item.get("secName"),
        "category": category,
        "title": item.get("announcementTitle"),
        "published_at": timestamp,
        "announcement_id": item.get("announcementId"),
        "org_id": item.get("orgId"),
        "url": f"http://www.cninfo.com.cn/new/disclosure/detail?stockCode={code}&announcementId={item.get('announcementId')}&orgId={item.get('orgId')}&announcementTime={timestamp}",
        "source_provider": "cninfo",
    }


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
