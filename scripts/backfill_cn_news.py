#!/usr/bin/env python3
"""Backfill the currently available independent CN stock-news window."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill current CN stock news")
    p.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    p.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    p.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_news_backfill")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--no-resume", action="store_true")
    return p.parse_args()


def main() -> int:
    o = parse_args(); o.output_root.mkdir(parents=True, exist_ok=True)
    target = json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text())
    symbols = [str(x).zfill(6) for x in target["cn"] if not str(x).zfill(6).startswith(("1", "5"))]
    progress_path = o.output_root / "progress.json"
    progress = _read(progress_path) if progress_path.exists() and not o.no_resume else {"symbols": {}}
    progress.setdefault("symbols", {})
    pending = [s for s in symbols if progress["symbols"].get(s, {}).get("status") != "complete"]
    print(f"target_equities={len(symbols)} pending={len(pending)}", flush=True)
    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(o.workers, 6))) as pool:
        futures = {pool.submit(_fetch, s): s for s in pending}
        for f in as_completed(futures):
            s = futures[f]
            try: fetched[s] = f.result()
            except Exception as exc: fetched[s] = {"status":"failed", "reason":f"{type(exc).__name__}:{exc}"}
            print(f"fetched {len(fetched)}/{len(pending)} {s} {fetched[s].get('status')}", flush=True)
    uow = SQLiteUnitOfWork(o.database); service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(o.object_store))
    try:
        for s, result in sorted(fetched.items()):
            if result.get("status") != "complete":
                progress["symbols"][s] = result; _write(progress_path, progress); continue
            now = datetime.now(timezone.utc)
            batch = service.persist(
                provider="eastmoney_cn_news", request_id=f"cn-news-{s}-{uuid4()}", dataset="events",
                payload=json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode(),
                schema_version="cn-news-v1", symbol=s, available_at=now, received_at=now,
                market_session="research_backfill", data_tier=DataTier.RESEARCH_PIT,
            )
            progress["symbols"][s] = {"status":"complete", "row_count":len(result["rows"]), "raw_batch_id":str(batch.id), "payload_hash":batch.payload_hash}
            _write(progress_path, progress)
    finally: uow.close()
    done = [x for x in progress["symbols"].values() if x.get("status")=="complete"]
    failures = {k:v for k,v in progress["symbols"].items() if v.get("status")!="complete"}
    report = {"schema_version":"cn-news-backfill-v1", "data_tier":"research_pit", "research_only":True,
              "target_equity_count":len(symbols), "completed_equity_count":len(done), "failed_equity_count":len(failures),
              "news_row_count":sum(int(x.get("row_count",0)) for x in done), "failures":failures,
              "status":"complete" if len(done)==len(symbols) else "partial", "generated_at":datetime.now(timezone.utc).isoformat()}
    _write(o.output_root/"latest.json", report); print(o.output_root/"latest.json")
    return 0 if report["status"]=="complete" else 1


def _fetch(symbol: str) -> dict[str, Any]:
    import akshare as ak
    frame = ak.stock_news_em(symbol=symbol)
    rows=[]; collected=datetime.now(timezone.utc).isoformat()
    if frame is None or frame.empty: return {"status":"complete", "rows":[]}
    for raw in frame.to_dict(orient="records"):
        published = str(raw.get("发布时间") or "")
        title = str(raw.get("新闻标题") or "")
        rows.append({"代码":symbol, "symbol":symbol, "公告标题":title, "title":title,
                     "公告日期":published[:10], "first_published_at":published,
                     "published_at":published, "新闻内容":str(raw.get("新闻内容") or ""),
                     "文章来源":str(raw.get("文章来源") or ""), "网址":raw.get("新闻链接"),
                     "event_category":_category(title), "event_source":"eastmoney_news",
                     "source_collected_at":collected, "available_at":collected, "revision":1})
    return {"status":"complete", "rows":rows}


def _category(title: str) -> str:
    for needles, value in [(('年报','中报','季报'), 'financial_report'), (('业绩','盈利','预告'), 'earnings_guidance'),
                           (('监管','处罚'), 'regulatory'), (('回购','减持','质押'), 'material')]:
        if any(x in title for x in needles): return value
    return 'material'


def _read(p: Path) -> dict: return json.loads(p.read_text(encoding='utf-8'))
def _write(p: Path, value: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__': raise SystemExit(main())
