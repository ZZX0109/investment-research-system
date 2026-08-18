#!/usr/bin/env python3
"""Backfill target CN announcement events into the local research catalog.

The public Eastmoney announcement API is queried per target equity and date
range.  Progress is written after every symbol so an interrupted run can
resume without losing completed downloads.  The rows are normalized to the
same fields consumed by ``rebuild_cn_research_pit.py`` while the original
per-symbol response is also persisted through the append-only raw catalog.
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

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
ETF_SYMBOLS = {"510050", "510300", "510500", "159915", "512100"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill CN target announcement events")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_event_backfill")
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-years", type=int, default=0, help="split long history requests into year-sized chunks")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    options.output_root.mkdir(parents=True, exist_ok=True)
    target = json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text(encoding="utf-8"))
    symbols = [str(item).zfill(6) for item in target["cn"] if str(item).zfill(6) not in ETF_SYMBOLS]
    if options.max_symbols is not None:
        symbols = symbols[: options.max_symbols]
    progress_path = options.output_root / "progress.json"
    progress = _read_json(progress_path) if progress_path.exists() and not options.no_resume else {
        "schema_version": "cn-target-events-progress-v1",
        "start_date": options.start_date,
        "end_date": options.end_date,
        "symbols": {},
    }
    progress.setdefault("symbols", {})
    pending = [symbol for symbol in symbols if progress["symbols"].get(symbol, {}).get("status") != "complete"]
    print(f"target_equities={len(symbols)} pending={len(pending)} range={options.start_date}:{options.end_date}", flush=True)

    uow = SQLiteUnitOfWork(options.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(options.object_store))
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(options.workers, 8))) as pool:
            futures = {
                pool.submit(_fetch_symbol, symbol, options.start_date, options.end_date, options.chunk_years): symbol
                for symbol in pending
            }
            for index, future in enumerate(as_completed(futures), start=1):
                symbol = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
                if result.get("status") == "complete":
                    payload = json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode()
                    now = datetime.now(timezone.utc)
                    batch = service.persist(
                        provider="eastmoney_cn_announcements",
                        request_id=f"cn-target-events-{symbol}-{options.start_date}-{options.end_date}",
                        dataset="events",
                        payload=payload,
                        schema_version="cn-target-events-v1",
                        symbol=symbol,
                        available_at=now,
                        received_at=now,
                        market_session="research_backfill",
                        data_tier=DataTier.RESEARCH_PIT,
                    )
                    progress["symbols"][symbol] = {
                        "status": "complete",
                        "row_count": len(result["rows"]),
                        "page_count": result.get("page_count"),
                        "payload_hash": batch.payload_hash,
                        "raw_batch_id": str(batch.id),
                    }
                else:
                    progress["symbols"][symbol] = result
                # Persist progress after every symbol so interruption never loses completed downloads.
                _write_json(progress_path, progress)
                print(f"fetched+persistent {index}/{len(pending)} {symbol} {result.get('status')}", flush=True)
    finally:
        uow.close()

    completed = [item for item in progress["symbols"].values() if item.get("status") == "complete"]
    failures = {key: value for key, value in progress["symbols"].items() if value.get("status") != "complete"}
    report = {
        "schema_version": "cn-target-events-backfill-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "start_date": options.start_date,
        "end_date": options.end_date,
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(failures),
        "event_row_count": sum(int(item.get("row_count", 0)) for item in completed),
        "failures": failures,
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(options.output_root / "latest.json", report)
    print(options.output_root / "latest.json")
    return 0 if report["status"] == "complete" else 1


def _fetch_symbol(symbol: str, start_date: str, end_date: str, chunk_years: int = 0) -> dict[str, Any]:
    if chunk_years and chunk_years > 0:
        merged: dict[str, dict[str, Any]] = {}
        for chunk_start, chunk_end in _date_chunks(start_date, end_date, chunk_years):
            result = _fetch_range(symbol, chunk_start, chunk_end)
            if result.get("status") != "complete":
                return result
            for row in result.get("rows", []):
                key = str(row.get("网址") or row.get("公告标题") or row)
                merged[key] = row
        return {"status": "complete", "rows": list(merged.values()), "page_count": None}
    return _fetch_range(symbol, start_date, end_date)


def _fetch_range(symbol: str, start_date: str, end_date: str) -> dict[str, Any]:
    import requests

    params = {
        "sr": "-1", "page_size": "100", "page_index": "1", "ann_type": "A",
        "client_source": "web", "f_node": "0", "s_node": "0",
        "begin_time": start_date, "end_time": end_date, "stock_list": symbol,
    }
    last_error = "unknown"
    for attempt in range(4):
        try:
            session = requests.Session()
            session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ResearchBackfill/1.0)"})
            first = _get_json(session, params)
            data = first.get("data") or {}
            total_hits = int(data.get("total_hits") or 0)
            total_pages = max(1, (total_hits + 99) // 100)
            rows = _normalize_items(data.get("list") or [], symbol)
            for page in range(2, total_pages + 1):
                page_params = dict(params, page_index=str(page))
                payload = _get_json(session, page_params)
                rows.extend(_normalize_items((payload.get("data") or {}).get("list") or [], symbol))
                time.sleep(0.05)
            return {"status": "complete", "rows": rows, "page_count": total_pages}
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            time.sleep(1.0 + attempt)
    return {"status": "failed", "reason": last_error}


def _date_chunks(start_date: str, end_date: str, chunk_years: int):
    from datetime import date

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while start <= end:
        chunk_end_year = start.year + chunk_years - 1
        chunk_end = date(chunk_end_year, 12, 31)
        if chunk_end > end:
            chunk_end = end
        yield start.isoformat(), chunk_end.isoformat()
        start = chunk_end.replace(year=chunk_end.year + 1, month=1, day=1)


def _get_json(session, params: dict[str, str]) -> dict[str, Any]:
    response = session.get(URL, params=params, timeout=40)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("data") is None:
        raise RuntimeError("eastmoney_invalid_response")
    return payload


def _normalize_items(items: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        codes = item.get("codes") or []
        code = symbol
        if codes:
            selected = next((value for value in codes if str(value.get("ann_type", "")).startswith("A")), codes[0])
            code = str(selected.get("stock_code") or symbol).zfill(6)
        columns = item.get("columns") or []
        column = columns[0] if columns else {}
        notice_date = str(item.get("notice_date") or item.get("sort_date") or "")[:10]
        title = str(item.get("title") or item.get("title_ch") or "")
        output.append({
            "代码": code,
            "名称": str(item.get("short_name") or ""),
            "公告标题": title,
            "公告类型": str(column.get("column_name") or ""),
            "公告日期": notice_date,
            "网址": f"https://data.eastmoney.com/notices/detail/{code}/{item.get('art_code', '')}.html",
            "event_category": _category(title, str(column.get("column_name") or "")),
            "first_published_at": notice_date,
            "published_at": item.get("display_time") or item.get("eiTime") or notice_date,
            "source_collected_at": datetime.now(timezone.utc).isoformat(),
            "event_source": "eastmoney_public_announcement",
        })
    return output


def _category(title: str, column: str) -> str:
    text = f"{title} {column}"
    for needles, category in (
        (("年度报告", "半年度报告", "季度报告"), "financial_report"),
        (("业绩预告", "业绩快报"), "earnings_guidance"),
        (("回购",), "repurchase"), (("减持",), "share_reduction"),
        (("质押",), "share_pledge"), (("监管", "处罚"), "regulatory"),
        (("诉讼", "仲裁"), "litigation"), (("重组", "收购", "合并"), "mna"),
    ):
        if any(needle in text for needle in needles):
            return category
    return "material"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
