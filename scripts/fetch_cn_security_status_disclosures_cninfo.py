#!/usr/bin/env python3
"""Download CNINFO special-treatment and delisting announcements."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from fetch_cn_financial_disclosures_cninfo import _fetch_symbol, _load_org_ids

ETF = {"159915", "510050", "510300", "510500", "512100"}
CATEGORY = "特别处理和退市"
CATEGORY_CODE = "category_tbclts_szsh"


def main() -> int:
    target = json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text())
    symbols = sorted({str(x).zfill(6) for x in target["cn"] if str(x).zfill(6) not in ETF})
    org_ids = _load_org_ids()
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_status, symbol, org_ids.get(symbol)): symbol for symbol in symbols}
        for index, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                results[symbol] = future.result()
            except Exception as exc:
                results[symbol] = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
            print(f"fetched {index}/{len(symbols)} {symbol} {results[symbol].get('status')}", flush=True)
    uow = SQLiteUnitOfWork(PROJECT / "var/cn-research/catalog.db")
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(PROJECT / "var/cn-research/raw"))
    output = PROJECT / "artifacts/cn_security_status_disclosures_cninfo"
    output.mkdir(parents=True, exist_ok=True)
    try:
        for symbol, result in sorted(results.items()):
            if result.get("status") != "complete":
                continue
            now = datetime.now(timezone.utc)
            service.persist(
                provider="cninfo_security_status_disclosures",
                request_id=f"cn-security-status-disclosures-{symbol}-{uuid4()}",
                dataset="cn_security_status_disclosures_cninfo_research",
                payload=json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode(),
                schema_version="cn-security-status-disclosures-cninfo-v1",
                symbol=symbol,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
    finally:
        uow.close()
    completed = {s: r for s, r in results.items() if r.get("status") == "complete"}
    rows = sum(len(r.get("rows", [])) for r in completed.values())
    report = {
        "schema_version": "cn-security-status-disclosures-cninfo-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "category": CATEGORY,
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(symbols) - len(completed),
        "row_count": rows,
        "published_at_coverage": 1.0 if rows else 0.0,
        "available_at_coverage": 1.0 if completed else 0.0,
        "failures": {s: r for s, r in results.items() if r.get("status") != "complete"},
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "missing_reason": "announcement evidence does not by itself establish every trading-day ST/suspension state",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "completed_equity_count", "row_count")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _fetch_status(symbol: str, org_id: str | None) -> dict:
    import requests
    if not org_id:
        return {"status": "failed", "reason": "cninfo_org_id_missing"}
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ResearchBackfill/1.0)"})
    base = {
        "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext", "plate": "",
        "stock": f"{symbol},{org_id}", "searchkey": "", "secid": "", "category": CATEGORY_CODE,
        "trade": "", "seDate": "2010-01-01~2026-08-17", "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    try:
        first = _post_retry(session, base)
        total = int(first.get("totalAnnouncement") or 0)
        pages = max(1, (total + 29) // 30)
        rows = []
        for page in range(1, pages + 1):
            data = first if page == 1 else _post_retry(session, dict(base, pageNum=str(page)))
            for item in data.get("announcements") or []:
                row = _normalize_status(item, symbol)
                if row:
                    rows.append(row)
        unique = {str(r.get("announcement_id") or r): r for r in rows}
        return {"status": "complete", "rows": list(unique.values())}
    except Exception as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}


def _post_retry(session, payload):
    import time
    last = None
    for attempt in range(4):
        try:
            return __import__('fetch_cn_financial_disclosures_cninfo')._post(session, payload)
        except Exception as exc:
            last = exc
            time.sleep(1 + attempt)
    raise last or RuntimeError('cninfo_request_failed')


def _normalize_status(item, symbol):
    from datetime import datetime, timezone
    value = item.get("announcementTime")
    if not value:
        return None
    timestamp = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).astimezone().isoformat()
    return {
        "symbol": str(item.get("secCode") or symbol).zfill(6),
        "security_name": item.get("secName"),
        "title": item.get("announcementTitle"),
        "published_at": timestamp,
        "announcement_id": item.get("announcementId"),
        "org_id": item.get("orgId"),
        "source_provider": "cninfo",
        "status_category": CATEGORY,
    }


if __name__ == "__main__":
    raise SystemExit(main())
