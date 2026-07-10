from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ml.common import artifact_path, connect, now_iso, read_json, write_json
from ml.data.ingest_history import yahoo_symbol_for_cn
from ml.pipelines.common import CN_SCALE_UNIVERSE_300, US_SCALE_UNIVERSE_300, parse_symbols, symbol_market


def parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        if len(text) == 10 and text[4] == "-":
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_evidence_schema() -> None:
    with connect() as conn:
        conn.execute(
            """
            create table if not exists evidence_records (
              id integer primary key autoincrement,
              symbol text not null,
              claim text not null,
              source_type text not null,
              source_name text not null,
              source_url text,
              observed_at text not null,
              valid_until text not null,
              confidence real not null,
              is_model_inferred integer not null,
              superseded_by integer,
              archived_at text
            )
            """
        )
        conn.commit()


def fetch_json_url(url: str, headers: dict[str, str] | None = None, timeout: int = 8) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))


def sec_user_agent() -> str:
    return os.getenv("SEC_USER_AGENT", "InvestmentResearchDemo/0.2 zzxin@example.com")


def sec_ticker_map() -> dict[str, dict[str, Any]]:
    cache_path = artifact_path("cache", "sec_company_tickers.json")
    if cache_path.exists():
        return read_json(cache_path)
    headers = {"User-Agent": sec_user_agent(), "Host": "www.sec.gov"}
    raw = fetch_json_url("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=15)
    mapping = {str(item.get("ticker", "")).upper(): item for item in raw.values()}
    write_json(cache_path, mapping)
    return mapping


def fetch_sec_filings(symbol: str, limit: int = 5) -> dict[str, Any]:
    try:
        mapping = sec_ticker_map()
        match = mapping.get(symbol.upper())
        if not match:
            return {"ok": False, "sourceName": "SEC EDGAR company_tickers", "error": f"{symbol} not found in SEC ticker map"}
        cik = str(match["cik_str"]).zfill(10)
        headers = {"User-Agent": sec_user_agent(), "Host": "data.sec.gov"}
        submissions = fetch_json_url(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers, timeout=12)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        documents = recent.get("primaryDocument", [])
        filings = []
        for index, form in enumerate(forms):
            if form not in {"10-K", "10-Q", "8-K", "20-F", "6-K"}:
                continue
            filing_date = filing_dates[index] if index < len(filing_dates) else ""
            filing_dt = parse_time(filing_date)
            if not filing_dt:
                continue
            accession = accession_numbers[index]
            accession_path = accession.replace("-", "")
            primary_doc = documents[index] if index < len(documents) else ""
            filings.append(
                {
                    "form": form,
                    "filingDate": filing_date,
                    "availableAt": iso(filing_dt),
                    "reportDate": report_dates[index] if index < len(report_dates) else "",
                    "accessionNumber": accession,
                    "primaryDocument": primary_doc,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_doc}",
                }
            )
            if len(filings) >= limit:
                break
        return {
            "ok": bool(filings),
            "sourceName": "SEC EDGAR submissions",
            "cik": cik,
            "companyName": submissions.get("name", symbol),
            "filings": filings,
            "count": len(filings),
            "error": None if filings else "No recent filings found",
        }
    except Exception as exc:
        return {"ok": False, "sourceName": "SEC EDGAR submissions", "error": str(exc), "filings": []}


def fetch_cn_disclosures(symbol: str, limit: int = 5) -> dict[str, Any]:
    def row_value(row: Any, names: list[str]) -> str:
        for name in names:
            try:
                value = row.get(name)
            except Exception:
                value = None
            if value is not None and str(value).strip() and str(value).strip().lower() != "nan":
                return str(value)
        return ""

    def filings_from_frame(frame: Any, source_name: str, url_fallback: str = "") -> list[dict[str, Any]]:
        filings = []
        if frame is None or getattr(frame, "empty", True):
            return filings
        for _, row in frame.iterrows():
            title = row_value(row, ["公告标题", "标题", "announcementTitle"])
            filing_date = row_value(row, ["公告时间", "公告日期", "日期", "publishTime"])
            filing_dt = parse_time(filing_date)
            if title and filing_dt:
                report_id = row_value(row, ["报告ID", "reportId"])
                source_url = row_value(row, ["公告链接", "链接", "网址", "adjunctUrl"]) or url_fallback
                if report_id and not source_url:
                    source_url = f"https://fundf10.eastmoney.com/jjgg_{symbol}_3.html"
                filings.append(
                    {
                        "form": row_value(row, ["公告类型", "类型"]) or ("基金定期报告" if report_id else "公告"),
                        "filingDate": filing_date,
                        "availableAt": iso(filing_dt),
                        "reportDate": row_value(row, ["报告期", "reportDate"]),
                        "primaryDocument": title,
                        "url": source_url,
                        "sourceName": source_name,
                    }
                )
        return sorted(filings, key=lambda item: item.get("availableAt", ""), reverse=True)[:limit]

    try:
        import akshare as ak  # type: ignore

        start_date = (datetime.now(timezone.utc) - timedelta(days=1095)).strftime("%Y%m%d")
        end_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        fn = getattr(ak, "stock_zh_a_disclosure_report_cninfo", None)
        errors: list[str] = []
        if fn is not None:
            try:
                frame = fn(symbol=symbol, market="沪深京", start_date=start_date, end_date=end_date)
                filings = filings_from_frame(frame, "AkShare cninfo disclosure")
                if filings:
                    return {"ok": True, "sourceName": "AkShare cninfo disclosure", "filings": filings, "count": len(filings), "error": None}
            except Exception as exc:
                errors.append(f"cninfo={exc}")
        individual_fn = getattr(ak, "stock_individual_notice_report", None)
        if individual_fn is not None:
            try:
                frame = individual_fn(security=symbol, symbol="全部", begin_date=start_date, end_date=end_date)
                filings = filings_from_frame(frame, "AkShare Eastmoney stock notices")
                if filings:
                    return {"ok": True, "sourceName": "AkShare Eastmoney stock notices", "filings": filings, "count": len(filings), "error": None}
            except Exception as exc:
                errors.append(f"eastmoney_stock={exc}")
        fund_fn = getattr(ak, "fund_announcement_report_em", None)
        if fund_fn is not None:
            try:
                frame = fund_fn(symbol=symbol)
                filings = filings_from_frame(frame, "AkShare Eastmoney fund announcements", f"https://fundf10.eastmoney.com/jjgg_{symbol}_3.html")
                if filings:
                    return {"ok": True, "sourceName": "AkShare Eastmoney fund announcements", "filings": filings, "count": len(filings), "error": None}
            except Exception as exc:
                errors.append(f"eastmoney_fund={exc}")
        return {"ok": False, "sourceName": "AkShare CN disclosure fallbacks", "error": "; ".join(errors) or "No CN disclosure rows", "filings": []}
    except Exception as exc:
        return {"ok": False, "sourceName": "AkShare cninfo disclosure", "error": str(exc), "filings": []}


def fetch_disclosures(symbol: str, market: str) -> dict[str, Any]:
    return fetch_sec_filings(symbol) if market == "us" else fetch_cn_disclosures(symbol)


def fetch_yfinance_news(symbol: str, market: str, limit: int = 5) -> dict[str, Any]:
    try:
        import yfinance as yf  # type: ignore

        ticker = symbol if market == "us" else yahoo_symbol_for_cn(symbol)
        raw_news = yf.Ticker(ticker).news or []
        articles = []
        for item in raw_news[:limit]:
            content = item.get("content", item) if isinstance(item, dict) else {}
            title = content.get("title") or (item.get("title") if isinstance(item, dict) else None)
            link = content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("link")
            publisher = content.get("provider", {}).get("displayName") if isinstance(content.get("provider"), dict) else content.get("publisher")
            published = content.get("pubDate") or content.get("displayTime") or content.get("providerPublishTime")
            published_dt = parse_time(published)
            if title and published_dt:
                articles.append(
                    {
                        "title": title,
                        "url": link,
                        "publisher": publisher or "Yahoo Finance",
                        "publishedAt": iso(published_dt),
                    }
                )
        return {"ok": bool(articles), "sourceName": "yfinance news", "articles": articles, "count": len(articles), "error": None if articles else "No timestamped news returned"}
    except Exception as exc:
        return {"ok": False, "sourceName": "yfinance news", "error": str(exc), "articles": []}


def supersede_open_evidence(conn: Any, symbol: str, source_type: str, new_id: int) -> None:
    rows = conn.execute(
        "select id from evidence_records where symbol = ? and source_type = ? and archived_at is null and superseded_by is null and id != ?",
        (symbol.upper(), source_type, new_id),
    ).fetchall()
    for row in rows:
        conn.execute("update evidence_records set superseded_by = ? where id = ?", (new_id, row["id"]))


def insert_evidence(symbol: str, source_type: str, claim: str, source_name: str, source_url: str | None, event_time: str, valid_days: int, confidence: float) -> int:
    ensure_evidence_schema()
    event_dt = parse_time(event_time) or datetime.now(timezone.utc)
    with connect() as conn:
        cursor = conn.execute(
            """
            insert into evidence_records(symbol, claim, source_type, source_name, source_url, observed_at, valid_until, confidence, is_model_inferred)
            values(?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (symbol.upper(), claim, source_type, source_name, source_url, iso(event_dt), iso(event_dt + timedelta(days=valid_days)), confidence),
        )
        new_id = int(cursor.lastrowid)
        supersede_open_evidence(conn, symbol, source_type, new_id)
        conn.commit()
    return new_id


def persist_symbol_events(symbol: str, market: str, *, fetch_news: bool = True, fetch_disclosure: bool = True) -> dict[str, Any]:
    symbol = symbol.upper()
    result: dict[str, Any] = {"symbol": symbol, "market": market, "inserted": {}, "errors": {}}
    if fetch_disclosure:
        disclosure = fetch_disclosures(symbol, market)
        if disclosure.get("ok") and disclosure.get("filings"):
            latest = disclosure["filings"][0]
            event_time = latest.get("availableAt") or latest.get("filingDate") or now_iso()
            source_name = latest.get("sourceName") or disclosure.get("sourceName", "disclosure provider")
            disclosure_id = insert_evidence(
                symbol,
                "disclosure",
                f"{symbol} authority disclosure publishedAt/availableAt={event_time}: {latest.get('form')} {latest.get('primaryDocument')}",
                source_name,
                latest.get("url"),
                event_time,
                90,
                0.88,
            )
            financial_id = insert_evidence(
                symbol,
                "financial_report",
                f"{symbol} financial report availableAt={event_time}: {latest.get('form')} filingDate={latest.get('filingDate')} reportDate={latest.get('reportDate') or 'n/a'}",
                source_name,
                latest.get("url"),
                event_time,
                120,
                0.84,
            )
            result["inserted"]["disclosure"] = disclosure_id
            result["inserted"]["financial_report"] = financial_id
        else:
            result["errors"]["disclosure"] = disclosure.get("error", "unknown disclosure error")
    if fetch_news:
        news = fetch_yfinance_news(symbol, market)
        if news.get("ok") and news.get("articles"):
            latest_article = news["articles"][0]
            event_time = latest_article.get("publishedAt") or now_iso()
            news_id = insert_evidence(
                symbol,
                "news_event",
                f"{symbol} news publishedAt={event_time}: {latest_article.get('title')}",
                news.get("sourceName", "news provider"),
                latest_article.get("url"),
                event_time,
                7,
                0.72,
            )
            result["inserted"]["news_event"] = news_id
        else:
            result["errors"]["news_event"] = news.get("error", "unknown news error")
    result["ok"] = bool(result["inserted"])
    return result


def run_event_ingest(symbols: list[str], *, workers: int = 4, fetch_news: bool = True, fetch_disclosure: bool = True) -> dict[str, Any]:
    selected = [symbol.upper() for symbol in symbols]

    def run_one(symbol: str) -> dict[str, Any]:
        return persist_symbol_events(symbol, symbol_market(symbol), fetch_news=fetch_news, fetch_disclosure=fetch_disclosure)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(run_one, selected))
    else:
        results = [run_one(symbol) for symbol in selected]
    inserted_counts: dict[str, int] = {}
    for item in results:
        for key in item.get("inserted", {}):
            inserted_counts[key] = inserted_counts.get(key, 0) + 1
    payload = {
        "ok": bool(inserted_counts),
        "requestedCount": len(selected),
        "successCount": sum(1 for item in results if item.get("ok")),
        "insertedCounts": inserted_counts,
        "results": results,
    }
    write_json(artifact_path("pipelines", "event_ingest_v1", "manifest.json"), payload)
    return payload


def symbols_from_large_manifest() -> list[str]:
    manifest = artifact_path("pipelines", "reliable_scale_v1", "manifest.json")
    if manifest.exists():
        payload = read_json(manifest)
        stats = payload.get("datasetStats", {})
        symbols = payload.get("usableSymbols") or payload.get("datasetStats", {}).get("symbols")
        if symbols and len(symbols) >= 100 and not stats.get("allowSynthetic"):
            return [str(symbol).upper() for symbol in symbols]
    return list(dict.fromkeys([*US_SCALE_UNIVERSE_300[:300], *CN_SCALE_UNIVERSE_300[:300]]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--large-universe", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-news", action="store_true")
    parser.add_argument("--no-disclosure", action="store_true")
    args = parser.parse_args()
    default_symbols = symbols_from_large_manifest() if args.large_universe else []
    symbols = parse_symbols(args.symbols, default_symbols)
    result = run_event_ingest(symbols, workers=args.workers, fetch_news=not args.no_news, fetch_disclosure=not args.no_disclosure)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
