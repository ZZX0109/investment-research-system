#!/usr/bin/env python3
"""Download historical security-name/ST evidence for the target CN equities."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from investment_research.service.cn_universe import load_cn_symbols

ETF = {"159915", "510050", "510300", "510500", "512100"}
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument("--all-current-universe", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_security_name_history_sina")
    args = parser.parse_args()
    target_path = PROJECT / "artifacts/cn_security_master_universe/security_master_current.json" if args.all_current_universe else args.target_symbols
    symbols = load_cn_symbols(target_path, exclude_etf=True)
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 16))) as pool:
        futures = {pool.submit(_fetch, symbol): symbol for symbol in symbols}
        for index, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                results[symbol] = future.result()
            except Exception as exc:
                results[symbol] = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
            print(f"name_history {index}/{len(symbols)} {symbol} {results[symbol].get('status')}", flush=True)

    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(PROJECT / "var/cn-research/catalog.db")
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(PROJECT / "var/cn-research/raw"))
    try:
        for symbol, result in sorted(results.items()):
            if result.get("status") != "complete":
                continue
            service.persist(
                provider="sina_security_name_history",
                request_id=f"sina-security-name-history-{symbol}-{uuid4()}",
                dataset="cn_security_name_history_sina_research",
                payload=json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode(),
                schema_version="cn-security-name-history-sina-v1",
                symbol=symbol,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
    finally:
        uow.close()

    completed = {s: r for s, r in results.items() if r.get("status") == "complete"}
    rows = [row for result in completed.values() for row in result.get("rows", [])]
    output = args.output_root
    output.mkdir(parents=True, exist_ok=True)
    (output / "security_name_history.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    report = {
        "schema_version": "cn-security-name-history-sina-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(symbols) - len(completed),
        "row_count": len(rows),
        "st_name_evidence_symbol_count": sum(any(row.get("is_st_name") for row in result.get("rows", [])) for result in completed.values()),
        "dated_status_coverage": 0.0,
        "failures": {s: r for s, r in results.items() if r.get("status") != "complete"},
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "missing_reason": "Sina provides name history without effective dates; this is evidence, not daily ST status",
        "generated_at": now.isoformat(),
        "normalized_ref": "security_name_history.json",
    }
    (output / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "completed_equity_count", "row_count", "st_name_evidence_symbol_count", "dated_status_coverage")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _fetch(symbol: str) -> dict:
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{symbol}.phtml"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ResearchBackfill/1.0)"}, timeout=(10, 30))
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    cell = soup.find(string=re.compile("证券简称更名历史"))
    text = ""
    if cell and cell.parent:
        value_cell = cell.parent.find_next("td", class_="ccl")
        text = " ".join(value_cell.get_text(" ", strip=True).split()) if value_cell else ""
    names = [name for name in text.split() if name]
    return {
        "status": "complete",
        "rows": [{
            "symbol": symbol,
            "sequence": index,
            "security_name": name,
            "is_st_name": bool(re.search(r"(?:^|[A-Z*])ST", name.upper()) or name.upper().startswith("S")),
            "effective_date": None,
            "source_url": url,
            "provider": "sina_security_name_history",
            "data_tier": DataTier.RESEARCH_PIT.value,
        } for index, name in enumerate(names, 1)],
    }


if __name__ == "__main__":
    raise SystemExit(main())
