#!/usr/bin/env python3
"""Collect official NBS CPI/PPI/PMI article publication timestamps.

The release calendar is only a plan.  This collector crawls the official
``数据发布`` archive, follows the original article, and records its ``PubDate``
meta tag as the actual publication timestamp.  A missing meta tag is kept as
unverified rather than falling back to the crawler time or the planned date.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

LIST_URL = "https://www.stats.gov.cn/sj/zxfb/"
SERIES_RE = {
    "cpi_monthly": re.compile(r"(\d{4})年(\d{1,2})月份居民消费价格"),
    "ppi_monthly": re.compile(r"(\d{4})年(\d{1,2})月份工业生产者出厂价格"),
    "pmi_monthly": re.compile(r"(\d{4})年(\d{1,2})月中国采购经理指数"),
}
DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


def _fetch(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, headers={"User-Agent": "InvestmentResearch-NBS-PIT/1.0"}, timeout=(10, 30))
    response.raise_for_status()
    response.encoding = "utf-8"
    return response


def _series_period(title: str) -> tuple[str, str] | None:
    for series, pattern in SERIES_RE.items():
        match = pattern.search(title)
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        return series, f"{year:04d}-{month:02d}"
    return None


def _listing_rows(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    for item in soup.select("li"):
        anchor = item.find("a", href=True)
        if anchor is None:
            continue
        title = " ".join((anchor.get("title") or anchor.get_text(" ", strip=True)).split())
        parsed = _series_period(title)
        if parsed is None:
            continue
        date_match = DATE_RE.search(" ".join(item.get_text(" ", strip=True).split()))
        rows.append({
            "series": parsed[0],
            "observation_period": parsed[1],
            "title": title,
            "source_url": urljoin(base_url, anchor["href"]),
            "listing_date": date_match.group(0) if date_match else None,
        })
    return rows


def _parse_pubdate(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        if str(meta.get("name") or "").lower() != "pubdate":
            continue
        value = str(meta.get("content") or "").strip()
        for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
            except ValueError:
                pass
    # Older NBS article templates do not expose a ``PubDate`` meta tag but do
    # render the official publication timestamp immediately below the title,
    # e.g. ``2021/10/14 09:30``.  Parse only an explicit date *and time* from
    # the rendered article text; never fall back to the listing date or fetch
    # time because those are not proof of historical availability.
    text = " ".join(soup.get_text(" ", strip=True).split())
    match = re.search(
        r"(?<!\d)(20\d{2})\s*[/\-年]\s*(\d{1,2})\s*[/\-月]\s*(\d{1,2})\s*(?:日)?\s+(\d{1,2}):(\d{2})",
        text,
    )
    if match:
        year, month, day, hour, minute = (int(value) for value in match.groups())
        try:
            return datetime(
                year, month, day, hour, minute,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ).isoformat()
        except ValueError:
            return None
    return None


def _deduplicate(rows: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row["series"]), str(row["observation_period"]))
        previous = by_key.get(key)
        # Prefer a page with a verified PubDate.  If there are multiple
        # official pages, retain the earliest actual release for PIT use.
        if previous is None or (not previous.get("published_at") and row.get("published_at")):
            by_key[key] = row
    return [by_key[key] for key in sorted(by_key)]


def _period_key(value: object) -> str:
    text = str(value or "")
    return text[:7] if len(text) >= 7 else text


def _release_key(row: dict) -> tuple[str, str]:
    return str(row.get("series") or ""), _period_key(row.get("observation_period"))


def _load_previous_records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict) and _release_key(row) != ("", "")]


def _merge_previous_records(previous: list[dict], fresh: list[dict]) -> list[dict]:
    """Merge a refresh without allowing an unresolved row to erase proof."""
    merged = {_release_key(row): dict(row) for row in previous}
    for row in fresh:
        key = _release_key(row)
        if key == ("", ""):
            continue
        old = merged.get(key)
        if old is None or (not old.get("published_at") and row.get("published_at")):
            merged[key] = dict(row)
        elif old.get("published_at") and not row.get("published_at"):
            continue
        else:
            merged[key] = dict(row)
    return [merged[key] for key in sorted(merged)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_macro_actual_release_nbs")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--page-count", type=int, default=67)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.page_count <= 0 or args.workers <= 0:
        raise SystemExit("page-count and workers must be positive")

    listing_pages: list[tuple[str, str]] = []
    with requests.Session() as session:
        for index in range(args.page_count):
            page = "index.html" if index == 0 else f"index_{index}.html"
            url = urljoin(LIST_URL, page)
            try:
                response = _fetch(session, url)
            except Exception:
                continue
            listing_pages.append((url, response.text))
    listing = _deduplicate([row for url, html in listing_pages for row in _listing_rows(html, url)])

    fetched: list[dict] = []
    failures: list[dict] = []

    def fetch_article(row: dict) -> dict:
        with requests.Session() as session:
            response = _fetch(session, row["source_url"])
            return {
                **row,
                "published_at": _parse_pubdate(response.text),
                "publication_time_method": "meta_pubdate_or_rendered_article_timestamp",
                "article_sha256": hashlib.sha256(response.content).hexdigest(),
                "http_status": response.status_code,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "_body": response.content,
            }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_article, row): row for row in listing}
        for future in as_completed(futures):
            row = futures[future]
            try:
                fetched.append(future.result())
            except Exception as exc:
                failures.append({"source_url": row["source_url"], "reason": f"{type(exc).__name__}:{exc}"})

    fetched = _deduplicate(fetched)
    # Keep the historical evidence set append-only across refreshes.  Older
    # NBS templates can lose a parseable timestamp or disappear from a page;
    # an unresolved fresh response must not erase a verified prior value.
    previous = _load_previous_records(args.output_root / "actual_releases.json")
    merged = _merge_previous_records(previous, fetched)
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(args.database)
    try:
        service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
        for row in fetched:
            body = row.pop("_body", b"")
            digest = str(row.get("article_sha256") or hashlib.sha256(body).hexdigest())
            service.persist(
                provider="nbs_official_actual_release",
                request_id=f"nbs-actual-release-{digest}",
                dataset="cn_macro_actual_releases_nbs",
                payload=body,
                schema_version="cn-macro-actual-release-nbs-v1",
                symbol="CN-MACRO",
                source_time=datetime.fromisoformat(row["published_at"]) if row.get("published_at") else None,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
    finally:
        uow.close()

    args.output_root.mkdir(parents=True, exist_ok=True)
    verified = sum(bool(row.get("published_at")) for row in merged)
    records = [{key: value for key, value in row.items() if key != "_body"} for row in merged]
    records.sort(key=lambda item: (item["series"], item["observation_period"]))
    coverage = verified / len(records) if records else 0.0
    report = {
        "schema_version": "cn-macro-actual-release-nbs-v1",
        "status": "complete" if records and not failures and coverage >= 0.98 else "partial" if records else "failed",
        "research_only": True,
        "deployment_ready": False,
        "generated_at": now.isoformat(),
        "listing_page_count": len(listing_pages),
        "candidate_count": len(merged),
        "record_count": len(records),
        "verified_pubdate_count": verified,
        "published_at_coverage": coverage,
        "failures": failures,
        "source_url": LIST_URL,
        "records_ref": "actual_releases.json",
    }
    (args.output_root / "actual_releases.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_root / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "listing_page_count", "candidate_count", "record_count", "verified_pubdate_count", "published_at_coverage")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" and report["published_at_coverage"] >= 0.98 else 1


if __name__ == "__main__":
    raise SystemExit(main())
