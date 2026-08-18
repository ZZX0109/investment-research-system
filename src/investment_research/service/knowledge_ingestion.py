"""Official-public, research-only ingestion for the A-share knowledge catalog."""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
from datetime import date, datetime, time, timezone
from typing import Iterable, Mapping
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from investment_research.domain.knowledge import (
    FinancialKnowledgeDocument,
    KnowledgeCoverageLedger,
    KnowledgeFetchRun,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService
from investment_research.service.object_store import ObjectStore, build_object_store


CNINFO_BASE = "https://www.cninfo.com.cn/"


class OfficialKnowledgeIngestionService:
    def __init__(self, uow: SQLiteUnitOfWork, *, object_store: ObjectStore | None = None, clock=None) -> None:
        self.uow = uow
        self.object_store = object_store or build_object_store()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.knowledge = FinancialKnowledgeService(uow)

    def ingest_cninfo_metadata(
        self, rows: Iterable[Mapping[str, object]], *, requested_date: date,
        status: str = "complete", failure_reasons: list[str] | None = None,
        universe_symbols: Iterable[str] | None = None,
    ) -> dict[str, object]:
        source = self.uow.financial_knowledge.get_source("cninfo")
        if source is None:
            raise RuntimeError("cninfo knowledge source is not configured")
        now = self.clock()
        values = list(rows)
        run = KnowledgeFetchRun(
            source_id=source.id, provider="cninfo",
            request_params={"date": requested_date.isoformat(), "scope": "all_a_share_metadata"},
            window_start=datetime.combine(requested_date, time.min, tzinfo=timezone.utc),
            window_end=datetime.combine(requested_date, time.max, tzinfo=timezone.utc),
            started_at=now, finished_at=now,
            status=status if status in {"complete", "partial", "fetch_failed", "unsupported"} else "partial",  # type: ignore[arg-type]
            target_count=len(values), success_count=0, failure_count=0,
            failure_reason=";".join(failure_reasons or []) or None,
        )
        successes = 0
        failures: list[str] = list(failure_reasons or [])
        raw = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str).encode()
        raw_hash = hashlib.sha256(raw).hexdigest()
        raw_ref = self.object_store.put(
            f"financial-knowledge/raw/cninfo/{requested_date.year}/{requested_date.isoformat()}/{raw_hash}.json",
            raw, content_type="application/json",
        )
        for row in values:
            try:
                self.knowledge.ingest(self._metadata_document(
                    row, requested_date=requested_date, observed_at=now,
                    raw_ref=raw_ref, raw_hash=raw_hash,
                ))
                successes += 1
            except Exception as exc:
                failures.append(f"{self._title(row)[:60]}:{type(exc).__name__}:{exc}")
        final_status = "complete" if not failures else "partial" if successes else "fetch_failed"
        run = run.model_copy(update={
            "status": final_status, "success_count": successes,
            "failure_count": len(failures), "failure_reason": ";".join(failures[:20]) or None,
        })
        self.uow.financial_knowledge.add_fetch_run(run)
        coverage = KnowledgeCoverageLedger(
            provider="cninfo", market="CN", dataset="announcement_metadata",
            window_start=run.window_start, window_end=run.window_end,
            metadata_status=final_status, full_text_status="partial",
            event_coverage_status="events_present" if successes else "confirmed_none" if final_status == "complete" else "partial",
            target_count=len(values), metadata_count=successes, full_text_count=0,
            checked_at=now, reasons=failures[:50] or ["full_text_downloaded_on_demand"],
        )
        self.uow.financial_knowledge.add_coverage(coverage)
        if universe_symbols is not None:
            counts: dict[str, int] = {}
            for row in values:
                symbol = self._field(row, "证券代码", "代码", "secCode", "symbol")
                if symbol:
                    counts[symbol] = counts.get(symbol, 0) + 1
            per_symbol = []
            for symbol in sorted({str(item).strip() for item in universe_symbols if str(item).strip()}):
                count = counts.get(symbol, 0)
                proven_complete = final_status == "complete"
                per_symbol.append(KnowledgeCoverageLedger(
                    provider="cninfo", market="CN", symbol=symbol,
                    dataset="announcement_metadata", window_start=run.window_start, window_end=run.window_end,
                    metadata_status="complete" if proven_complete else "partial",
                    full_text_status="partial",
                    event_coverage_status="events_present" if count else "confirmed_none" if proven_complete else "partial",
                    target_count=count, metadata_count=count, full_text_count=0, checked_at=now,
                    reasons=["metadata_catalog_complete_for_window"] if count else ["confirmed_none_for_requested_window"] if proven_complete else ["source_window_partial"],
                ))
            self.uow.financial_knowledge.add_coverages(per_symbol)
        return {
            "fetch_run_id": str(run.id), "coverage_id": str(coverage.id),
            "status": final_status, "target_count": len(values), "success_count": successes,
            "failure_count": len(failures), "raw_payload_ref": raw_ref, "raw_payload_hash": raw_hash,
        }

    def fetch_and_ingest_full_text(self, document_id: str, *, timeout: int = 30) -> FinancialKnowledgeDocument:
        document = self.uow.financial_knowledge.get(document_id)
        if document is None or not document.source_url:
            raise ValueError("knowledge document or official source URL is unavailable")
        if document.source_kind != "official_public":
            raise ValueError("on-demand fetch only supports official public documents")
        import requests

        response = requests.get(document.source_url, timeout=timeout, headers={"User-Agent": "A-Share-Research-Knowledge/1.0"})
        response.raise_for_status()
        data = response.content
        raw_hash = hashlib.sha256(data).hexdigest()
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        raw_ref = self.object_store.put(
            f"financial-knowledge/raw/documents/{raw_hash}", data, content_type=content_type,
        )
        content = self._extract_text(data, content_type=content_type, url=document.source_url)
        if not content:
            raise ValueError("official document contains no extractable text")
        now = self.clock()
        updated_hash = self.knowledge.content_hash(
            title=document.title, content=content, source_url=document.source_url,
        )
        return self.knowledge.ingest(document.model_copy(update={
            "id": uuid4(), "content": content, "content_hash": updated_hash,
            "content_scope": "full_text", "collected_at": now, "available_at": now,
            "first_observed_at": document.first_observed_at or now,
            "raw_payload_ref": raw_ref, "raw_payload_hash": raw_hash,
            "parser_version": "official-document-parser-v1",
        }))

    def ingest_official_document(
        self, *, provider: str, url: str, title: str, data: bytes,
        content_type: str, published_at: datetime | None = None,
    ) -> FinancialKnowledgeDocument:
        source = self.uow.financial_knowledge.get_source(provider)
        if source is None or not source.enabled:
            raise ValueError(f"official knowledge source is unavailable: {provider}")
        source_host = (urlparse(source.base_url).hostname or "").lower()
        document_host = (urlparse(url).hostname or "").lower()
        if not source_host or not document_host or not (
            document_host == source_host or document_host.endswith(f".{source_host}")
        ):
            raise ValueError("official document URL is outside the configured source domain")
        now = self.clock()
        published = published_at or now
        raw_hash = hashlib.sha256(data).hexdigest()
        raw_ref = self.object_store.put(
            f"financial-knowledge/raw/{provider}/{published.year}/{raw_hash}",
            data, content_type=content_type,
        )
        content = self._extract_text(data, content_type=content_type, url=url)
        if len(content.strip()) < 2:
            raise ValueError("official document contains no extractable text")
        normalized_title = re.sub(r"\s+", " ", title).strip()[:300] or source.name
        content_hash = self.knowledge.content_hash(
            title=normalized_title, content=content, source_url=url,
        )
        return self.knowledge.ingest(FinancialKnowledgeDocument(
            title=normalized_title, content=content, source_name=source.name,
            source_url=url, market="CN", document_type=self._official_document_type(provider, normalized_title),
            published_at=published, effective_from=published, collected_at=now,
            first_observed_at=now, available_at=max(published, now),
            content_hash=content_hash, data_tier="research_pit",
            source_kind="official_public", copyright_status="official_public",
            content_scope="full_text", authority_level=source.authority_level,
            raw_payload_ref=raw_ref, raw_payload_hash=raw_hash,
            visibility_assumption="historical_available_at_unproven_public_backfill"
            if published < now else None,
        ))

    def record_source_failure(
        self, *, provider: str, dataset: str, reason: str, requested_date: date | None = None,
    ) -> KnowledgeCoverageLedger:
        now = self.clock()
        value = KnowledgeCoverageLedger(
            provider=provider, market="CN", dataset=dataset,
            window_start=None if requested_date is None else datetime.combine(requested_date, time.min, tzinfo=timezone.utc),
            window_end=None if requested_date is None else datetime.combine(requested_date, time.max, tzinfo=timezone.utc),
            metadata_status="fetch_failed", full_text_status="fetch_failed",
            event_coverage_status="fetch_failed",
            checked_at=now, reasons=[reason],
        )
        return self.uow.financial_knowledge.add_coverage(value)

    def _metadata_document(
        self, row: Mapping[str, object], *, requested_date: date, observed_at: datetime,
        raw_ref: str, raw_hash: str,
    ) -> FinancialKnowledgeDocument:
        title = self._title(row)
        symbol = self._field(row, "证券代码", "代码", "secCode", "symbol")
        issuer = self._field(row, "证券简称", "简称", "secName", "name")
        url_value = self._field(row, "公告链接", "网址", "adjunctUrl", "url")
        source_url = None if not url_value else urljoin(CNINFO_BASE, url_value)
        if source_url is None or not source_url.startswith("https://"):
            source_url = CNINFO_BASE
        published = self._published_at(row, requested_date)
        summary = self._field(row, "摘要", "summary")
        content = title if not summary else f"{title}\n{summary}"
        category = self._category(title)
        content_hash = self.knowledge.content_hash(title=title, content=content, source_url=source_url)
        return FinancialKnowledgeDocument(
            title=title, content=content, source_name="巨潮资讯网", source_url=source_url,
            market="CN", symbol=symbol or None, issuer_name=issuer or None,
            exchange=self._exchange(symbol), document_type="announcement_metadata",
            announcement_category=category, published_at=published, effective_from=published,
            collected_at=observed_at, first_observed_at=observed_at,
            available_at=max(published, observed_at), content_hash=content_hash,
            data_tier="research_pit", source_kind="official_public",
            copyright_status="official_public", content_scope="metadata_excerpt",
            authority_level=5, raw_payload_ref=raw_ref, raw_payload_hash=raw_hash,
            visibility_assumption="historical_available_at_unproven_public_backfill"
            if published < observed_at else None,
        )

    @staticmethod
    def _extract_text(data: bytes, *, content_type: str, url: str) -> str:
        if content_type == "application/pdf" or url.lower().endswith(".pdf"):
            try:
                import fitz

                doc = fitz.open(stream=data, filetype="pdf")
                pages = [f"[page {index + 1}] {page.get_text('text').strip()}" for index, page in enumerate(doc)]
                doc.close()
                return "\n".join(item for item in pages if item.rsplit("]", 1)[-1].strip())[:2_000_000]
            except Exception as exc:
                raise ValueError(f"pdf_parse_failed:{exc}") from exc
        try:
            try:
                from charset_normalizer import from_bytes

                best = from_bytes(data).best()
                decoded = str(best) if best is not None else data.decode("utf-8", errors="replace")
            except Exception:
                decoded = data.decode("utf-8", errors="replace")
            decoded = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", decoded, flags=re.I | re.S)
            return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded))).strip()[:2_000_000]
        except Exception as exc:
            raise ValueError(f"text_parse_failed:{exc}") from exc

    @classmethod
    def _title(cls, row: Mapping[str, object]) -> str:
        return cls._field(row, "公告标题", "标题", "announcementTitle", "title") or "未命名公告"

    @staticmethod
    def _field(row: Mapping[str, object], *names: str) -> str:
        for name in names:
            value = row.get(name)
            if value is not None and str(value).strip() and str(value).lower() != "nan":
                return str(value).strip()
        return ""

    @classmethod
    def _published_at(cls, row: Mapping[str, object], requested_date: date) -> datetime:
        value = cls._field(row, "公告时间", "公告日期", "announcementTime", "published_at")
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.combine(requested_date, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _exchange(symbol: str) -> str | None:
        if not symbol:
            return None
        if symbol.startswith(("6", "5", "9")):
            return "XSHG"
        if symbol.startswith(("0", "1", "2", "3")):
            return "XSHE"
        if symbol.startswith(("4", "8")):
            return "XBSE"
        return None

    @staticmethod
    def _category(title: str) -> str:
        mappings = (
            (("年度报告", "半年度报告", "季度报告"), "financial_report"),
            (("业绩预告", "业绩快报"), "earnings_guidance"),
            (("回购",), "repurchase"), (("减持",), "share_reduction"),
            (("质押",), "share_pledge"), (("监管", "处罚", "问询函"), "regulatory"),
            (("诉讼", "仲裁"), "litigation"), (("重组", "收购", "合并"), "mna"),
            (("停牌", "复牌", "退市", "风险警示"), "listing_status"),
        )
        for needles, category in mappings:
            if any(needle in title for needle in needles):
                return category
        return "material"

    @staticmethod
    def _official_document_type(provider: str, title: str) -> str:
        if provider in {"sse", "szse", "bse"}:
            return "market_rule"
        if provider == "csrc" or any(value in title for value in ("监管", "处罚", "办法", "规定")):
            return "regulation"
        if provider in {"pbc", "stats", "mof"}:
            return "macro_policy"
        return "official_reference"
