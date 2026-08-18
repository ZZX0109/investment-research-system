#!/usr/bin/env python3
"""Download official NBS statistical release schedules and derive research links.

The NBS pages publish a planned release calendar.  It is useful evidence for
macro availability, but it is deliberately stored as ``planned`` rather than
pretending that a planned date is the actual publication timestamp.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin
import warnings
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

ARCHIVE_URL = "https://www.stats.gov.cn/sj/fbrc/ljxxfb/"
CURRENT_URL = "https://www.stats.gov.cn/sj/fbrc/bnxxfb/"
OUTPUT = PROJECT / "artifacts/cn_macro_release_calendar_nbs"
YEARS = range(2013, 2027)
MONTHS = {f"{i}月": i for i in range(1, 13)}
DATE_RE = re.compile(r"(\d{1,2})/")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ResearchBackfill/1.0)"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        archive = _get(session, ARCHIVE_URL)
        current = _get(session, CURRENT_URL)
    links = _collect_links(archive.url, archive.text)
    links.update(_collect_links(current.url, current.text))
    links.setdefault("2026", current.url)
    schedule_pages: dict[str, str] = {}
    failures: dict[str, str] = {}
    for year in YEARS:
        url = links.get(str(year))
        if not url:
            failures[str(year)] = "official_schedule_link_missing"
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                response = _get(session, url)
            response.encoding = "utf-8"
            schedule_pages[str(year)] = response.text
        except Exception as exc:
            failures[str(year)] = f"{type(exc).__name__}:{exc}"

    records: list[dict] = []
    for year, html in schedule_pages.items():
        try:
            records.extend(_parse_schedule(int(year), links[year], html))
        except Exception as exc:
            failures[year] = f"parse:{type(exc).__name__}:{exc}"

    _persist_raw(schedule_pages, links)
    _write(OUTPUT / "nbs_release_calendar.json", records)
    assumptions = _build_macro_assumptions(records)
    _persist_assumptions(assumptions)
    _write(OUTPUT / "macro_release_assumptions.json", assumptions)
    report = {
        "schema_version": "cn-macro-release-calendar-nbs-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "source": "国家统计局主要统计信息发布日程表",
        "schedule_semantics": "planned_release_time_not_actual_publication_time",
        "years_requested": [min(YEARS), max(YEARS)],
        "years_downloaded": sorted(schedule_pages),
        "row_count": len(records),
        "macro_series": sorted({r["series"] for r in records}),
        "failures": failures,
        "status": "complete" if not failures and records else "partial" if records else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "normalized_ref": "nbs_release_calendar.json",
        "assumption_ref": "macro_release_assumptions.json",
        "assumption_row_count": len(assumptions),
        "assumption_coverage": _coverage(assumptions),
        "source_url": ARCHIVE_URL,
    }
    _write(OUTPUT / "latest.json", report)
    print(json.dumps({k: report[k] for k in ("status", "years_downloaded", "row_count", "macro_series")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _get(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=(10, 40), verify=False)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response


def _collect_links(base_url: str, html: str) -> dict[str, str]:
    output: dict[str, str] = {}
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        match = re.search(r"(20\d{2})年国家统计局主要统计信息发布日程表", title)
        if match:
            output[match.group(1)] = urljoin(base_url, anchor["href"])
    return output


def _parse_schedule(year: int, url: str, html: str) -> list[dict]:
    from io import StringIO

    tables = pd.read_html(StringIO(html))
    if not tables:
        raise RuntimeError("schedule_table_missing")
    table = tables[0]
    columns = list(table.columns)
    month_columns = {str(table.iloc[0, i]).strip(): i for i in range(2, min(14, table.shape[1]))}
    rows: list[dict] = []
    for row_index in range(1, table.shape[0] - 1, 2):
        name = str(table.iloc[row_index, 1]).strip()
        if not name or name.startswith("注"):
            continue
        for month_label, column_index in month_columns.items():
            month = MONTHS.get(month_label)
            if not month:
                continue
            date_cell = str(table.iloc[row_index, column_index]).strip()
            time_cell = str(table.iloc[row_index + 1, column_index]).strip()
            date_match = DATE_RE.search(date_cell)
            if not date_match or "……" in date_cell or "……" in time_cell:
                continue
            day = int(date_match.group(1))
            time_match = re.search(r"(\d{1,2}):(\d{2})", time_cell)
            if not time_match:
                continue
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
            try:
                release = datetime.combine(date(year, month, day), time(hour, minute), tzinfo=ZoneInfo("Asia/Shanghai"))
            except ValueError:
                continue
            series = _series_for_name(name)
            if not series:
                continue
            data_period = _period_for_release(series, year, month)
            rows.append({
                "calendar_year": year,
                "release_month": month,
                "release_date": release.date().isoformat(),
                "planned_published_at": release.isoformat(),
                "report_name": name,
                "series": series,
                "data_period": data_period,
                "schedule_semantics": "planned_release_time",
                "source_url": url,
                "provider": "nbs_official_release_schedule",
                "data_tier": DataTier.RESEARCH_PIT.value,
            })
    return rows


def _series_for_name(name: str) -> str | None:
    if "采购经理指数" in name:
        return "pmi_monthly"
    if "居民消费价格指数" in name:
        return "cpi_monthly"
    if "工业生产者价格指数" in name:
        return "ppi_monthly"
    return None


def _period_for_release(series: str, year: int, month: int) -> str:
    if series == "pmi_monthly":
        return f"{year:04d}-{month:02d}"
    previous = date(year, month, 1).replace(day=1)
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def _persist_raw(pages: dict[str, str], links: dict[str, str]) -> None:
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(PROJECT / "var/cn-research/catalog.db")
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(PROJECT / "var/cn-research/raw"))
    try:
        for year, html in pages.items():
            service.persist(
                provider="nbs_official_release_schedule",
                request_id=f"nbs-release-calendar-{year}",
                dataset="cn_macro_release_calendar_nbs_research",
                payload=html.encode("utf-8"),
                schema_version="cn-macro-release-calendar-nbs-v1",
                symbol=year,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
    finally:
        uow.close()


def _build_macro_assumptions(records: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for record in records:
        key = (record["series"], record["data_period"])
        by_key.setdefault(key, record)
    sources = {
        "cpi_monthly": OUTPUT.parent / "cn_research_auxiliary/macro_cpi_monthly.json",
        "ppi_monthly": OUTPUT.parent / "cn_research_auxiliary/macro_ppi_monthly.json",
        "pmi_monthly": OUTPUT.parent / "cn_research_auxiliary/macro_pmi_monthly.json",
    }
    output: list[dict] = []
    for series, path in sources.items():
        if not path.is_file():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        for index, row in enumerate(rows):
            period = _row_period(series, row)
            schedule = by_key.get((series, period)) if period else None
            output.append({
                "series": series,
                "data_period": period,
                "source_path": str(path.relative_to(PROJECT)),
                "source_row_index": index,
                "planned_published_at": schedule.get("planned_published_at") if schedule else None,
                "published_at": None,
                "available_at": schedule.get("planned_published_at") if schedule else None,
                "revision": 1,
                "schedule_semantics": "planned_release_time_not_actual_publication_time",
                "formal_pit_verified": False,
                "provider": "nbs_official_release_schedule",
                "data_tier": DataTier.RESEARCH_PIT.value,
            })
    return output


def _row_period(series: str, row: dict) -> str | None:
    value = row.get("日期") if series == "cpi_monthly" else row.get("月份")
    if value is None:
        return None
    text = str(value)
    if series == "cpi_monthly":
        match = re.search(r"(\d{4})[-年](\d{1,2})", text)
        if match:
            release_month = date(int(match.group(1)), int(match.group(2)), 1)
            period = release_month - timedelta(days=1)
            return f"{period.year:04d}-{period.month:02d}"
    else:
        match = re.search(r"(\d{4})年?(\d{1,2})月", text)
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}" if match else None


def _coverage(rows: list[dict]) -> dict:
    by_series: dict[str, list[dict]] = {}
    for row in rows:
        by_series.setdefault(row["series"], []).append(row)
    return {
        series: {
            "rows": len(items),
            "planned_release_matched": sum(bool(item.get("planned_published_at")) for item in items),
            "coverage": sum(bool(item.get("planned_published_at")) for item in items) / len(items) if items else 0.0,
        }
        for series, items in sorted(by_series.items())
    }


def _persist_assumptions(rows: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    request_suffix = hashlib.sha256(payload).hexdigest()[:16]
    uow = SQLiteUnitOfWork(PROJECT / "var/cn-research/catalog.db")
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(PROJECT / "var/cn-research/raw"))
    try:
        service.persist(
            provider="nbs_official_release_schedule",
            request_id=f"nbs-macro-release-assumptions-v1-{request_suffix}",
            dataset="cn_macro_release_assumptions_nbs_research",
            payload=payload,
            schema_version="cn-macro-release-calendar-nbs-v1",
            symbol="CN-MACRO",
            available_at=now,
            received_at=now,
            market_session="research_backfill",
            data_tier=DataTier.RESEARCH_PIT,
        )
    finally:
        uow.close()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
