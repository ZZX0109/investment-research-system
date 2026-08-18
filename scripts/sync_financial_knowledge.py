#!/usr/bin/env python3
"""Incrementally synchronize official-public A-share knowledge metadata."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.knowledge import KnowledgeCoverageLedger
from investment_research.repository.sqlite import create_unit_of_work
from investment_research.service.knowledge_ingestion import OfficialKnowledgeIngestionService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize research-only financial knowledge")
    parser.add_argument("--mode", choices=("incremental", "backfill"), default="incremental")
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--max-days", type=int, default=30)
    parser.add_argument("--include-official-references", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-official-documents", type=int, default=20)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/financial_knowledge/latest-sync.json")
    return parser.parse_args()


def _dates(args: argparse.Namespace, latest_cursor: date | None) -> list[date]:
    today = args.end_date or datetime.now().date()
    if args.mode == "incremental":
        start = args.start_date or today - timedelta(days=8)
        return [start + timedelta(days=i) for i in range((today - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    end = latest_cursor - timedelta(days=1) if latest_cursor else today
    start = args.start_date or max(date(1990, 1, 1), end - timedelta(days=max(1, args.max_days) - 1))
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    return list(reversed(dates))[: args.max_days]


def _sync_cninfo(uow, service: OfficialKnowledgeIngestionService, args: argparse.Namespace) -> list[dict]:
    try:
        import akshare as ak
    except Exception as exc:
        service.record_source_failure(provider="cninfo", dataset="announcement_metadata", reason=f"akshare_unavailable:{exc}")
        return [{"provider": "cninfo", "status": "unsupported", "reason": f"akshare_unavailable:{exc}"}]
    universe_symbols = None
    try:
        universe = ak.stock_info_a_code_name()
        if universe is not None and not universe.empty:
            code_column = next((name for name in ("code", "证券代码", "代码") if name in universe.columns), None)
            if code_column:
                universe_symbols = [str(item).zfill(6) for item in universe[code_column].tolist()]
    except Exception:
        universe_symbols = None
    latest = uow.financial_knowledge.latest_fetch_run("cninfo")
    cursor = None
    if latest and latest.request_params.get("date"):
        try:
            cursor = date.fromisoformat(str(latest.request_params["date"]))
        except ValueError:
            cursor = None
    output: list[dict] = []
    for current in _dates(args, cursor):
        try:
            frame = ak.stock_notice_report(symbol="全部", date=current.strftime("%Y%m%d"))
            rows = [] if frame is None or frame.empty else json.loads(frame.to_json(orient="records", force_ascii=False, date_format="iso"))
            output.append(service.ingest_cninfo_metadata(rows, requested_date=current, universe_symbols=universe_symbols))
        except Exception as exc:
            service.record_source_failure(
                provider="cninfo", dataset="announcement_metadata",
                requested_date=current, reason=f"{type(exc).__name__}:{exc}",
            )
            output.append({"provider": "cninfo", "date": current.isoformat(), "status": "fetch_failed", "reason": f"{type(exc).__name__}:{exc}"})
        time.sleep(0.5)
    return output


def _sync_official_references(uow, ingestion: OfficialKnowledgeIngestionService, *, max_documents: int) -> list[dict]:
    import requests

    output: list[dict] = []
    for source in uow.financial_knowledge.list_sources():
        if source.provider == "cninfo" or not source.enabled:
            continue
        try:
            response = requests.get(source.base_url, timeout=20, headers={"User-Agent": "A-Share-Research-Knowledge/1.0"})
            response.raise_for_status()
            if not response.encoding or response.encoding.lower() in {"iso-8859-1", "ascii"}:
                response.encoding = response.apparent_encoding
            text = response.text
            title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else source.name
            ingestion.ingest_official_document(
                provider=source.provider, url=source.base_url, title=title,
                data=response.content, content_type=response.headers.get("content-type", "text/html").split(";", 1)[0],
            )
            source_host = (urlparse(source.base_url).hostname or "").lower()
            discovered: list[tuple[str, str]] = []
            for href, label in re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", text, flags=re.I | re.S):
                url = urljoin(source.base_url, href)
                host = (urlparse(url).hostname or "").lower()
                clean_label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", label)).strip()
                if not clean_label or not (host == source_host or host.endswith(f".{source_host}")):
                    continue
                if not any(term in clean_label for term in ("规则", "办法", "规定", "公告", "报告", "政策", "统计", "处罚", "监管", "指引")):
                    continue
                if url not in {item[0] for item in discovered}:
                    discovered.append((url, clean_label))
                if len(discovered) >= max_documents:
                    break
            indexed = 1
            failures: list[str] = []
            for url, label in discovered:
                try:
                    item = requests.get(url, timeout=20, headers={"User-Agent": "A-Share-Research-Knowledge/1.0"})
                    item.raise_for_status()
                    ingestion.ingest_official_document(
                        provider=source.provider, url=url, title=label,
                        data=item.content, content_type=item.headers.get("content-type", "text/html").split(";", 1)[0],
                    )
                    indexed += 1
                except Exception as exc:
                    failures.append(f"{url}:{type(exc).__name__}:{exc}")
                time.sleep(0.2)
            uow.financial_knowledge.add_coverage(KnowledgeCoverageLedger(
                provider=source.provider, market="CN", dataset="official_rules_and_macro",
                metadata_status="complete" if not failures else "partial",
                full_text_status="complete" if discovered and not failures else "partial",
                target_count=1 + len(discovered), metadata_count=indexed, full_text_count=indexed,
                reasons=failures[:20] or (["no_matching_same_domain_links_discovered"] if not discovered else []),
            ))
            output.append({"provider": source.provider, "status": "complete" if not failures else "partial", "title": title, "discovered": len(discovered), "indexed": indexed, "failures": failures})
        except Exception as exc:
            uow.financial_knowledge.add_coverage(KnowledgeCoverageLedger(
                provider=source.provider, market="CN", dataset="official_catalog",
                metadata_status="fetch_failed", full_text_status="fetch_failed",
                reasons=[f"{type(exc).__name__}:{exc}"],
            ))
            output.append({"provider": source.provider, "status": "fetch_failed", "reason": f"{type(exc).__name__}:{exc}"})
    return output


def main() -> int:
    args = parse_args()
    uow = create_unit_of_work()
    try:
        ingestion = OfficialKnowledgeIngestionService(uow)
        cninfo = _sync_cninfo(uow, ingestion, args)
        references = _sync_official_references(uow, ingestion, max_documents=max(0, args.max_official_documents)) if args.include_official_references else []
        report = {
            "schema_version": "financial-knowledge-sync-v1", "mode": args.mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_tier": "research_pit", "deployment_ready": False,
            "cninfo": cninfo, "official_references": references,
        }
    finally:
        uow.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if any(item.get("status") in {"complete", "partial"} for item in [*cninfo, *references]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
