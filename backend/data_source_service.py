from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable


def build_authority_sources(symbol: str, market: str) -> list[dict[str, Any]]:
    if market == "us":
        return [
            {"name": "SEC EDGAR Company Search", "url": f"https://www.sec.gov/edgar/search/#/q={symbol}", "authority": "regulator", "status": "权威检索入口"},
            {"name": "NASDAQ Quote & Filings", "url": f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}", "authority": "exchange/data", "status": "行情与披露交叉检查"},
            {"name": f"{symbol} Investor Relations", "url": f"https://www.google.com/search?q={symbol}+investor+relations+quarterly+results", "authority": "company_ir", "status": "公司 IR 检索"},
        ]
    return [
        {"name": "巨潮资讯公告检索", "url": f"http://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyWord={symbol}", "authority": "exchange_disclosure", "status": "公告检索入口"},
        {"name": "上海证券交易所 / 深圳证券交易所", "url": f"https://www.google.com/search?q={symbol}+交易所+公告", "authority": "exchange", "status": "交易所交叉检查"},
        {"name": f"{symbol} 公司投资者关系", "url": f"https://www.google.com/search?q={symbol}+投资者关系+财报", "authority": "company_ir", "status": "公司 IR 检索"},
    ]


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
    return os.getenv("SEC_USER_AGENT", "InvestmentResearchDemo/0.2 contact@example.com")


def try_fetch_sec_filings(symbol: str) -> dict[str, Any]:
    headers = {"User-Agent": sec_user_agent(), "Host": "www.sec.gov"}
    try:
        ticker_data = fetch_json_url("https://www.sec.gov/files/company_tickers.json", headers=headers)
        ticker_match = next(
            (
                item
                for item in ticker_data.values()
                if str(item.get("ticker", "")).upper() == symbol.upper()
            ),
            None,
        )
        if not ticker_match:
            return {"ok": False, "sourceName": "SEC EDGAR company_tickers", "error": f"{symbol} not found in SEC ticker map"}
        cik = str(ticker_match["cik_str"]).zfill(10)
        data_headers = {"User-Agent": sec_user_agent(), "Host": "data.sec.gov"}
        submissions = fetch_json_url(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=data_headers)
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
            accession = accession_numbers[index]
            accession_path = accession.replace("-", "")
            primary_doc = documents[index]
            filings.append(
                {
                    "form": form,
                    "filingDate": filing_dates[index],
                    "reportDate": report_dates[index] if index < len(report_dates) else "",
                    "accessionNumber": accession,
                    "primaryDocument": primary_doc,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_doc}",
                }
            )
            if len(filings) >= 5:
                break
        if not filings:
            return {"ok": False, "sourceName": "SEC EDGAR submissions", "error": "No recent 10-K/10-Q/8-K/20-F/6-K filings found"}
        return {"ok": True, "sourceName": "SEC EDGAR submissions", "cik": cik, "companyName": submissions.get("name", symbol), "filings": filings, "count": len(filings)}
    except Exception as exc:
        return {"ok": False, "sourceName": "SEC EDGAR submissions", "error": str(exc)}


def try_fetch_cninfo_disclosures(symbol: str) -> dict[str, Any]:
    try:
        import akshare as ak  # type: ignore

        fn = getattr(ak, "stock_zh_a_disclosure_report_cninfo", None)
        if fn is None:
            return {"ok": False, "sourceName": "AkShare cninfo disclosure", "error": "AkShare function stock_zh_a_disclosure_report_cninfo is unavailable"}
        try:
            frame = fn(symbol=symbol)
        except TypeError:
            frame = fn(symbol)
        disclosures = []
        for _, row in frame.head(5).iterrows():
            title = str(row.get("公告标题") or row.get("标题") or row.get("announcementTitle") or "")
            if title:
                disclosures.append(
                    {
                        "form": str(row.get("公告类型") or row.get("类型") or "公告"),
                        "filingDate": str(row.get("公告日期") or row.get("日期") or row.get("publishTime") or ""),
                        "reportDate": str(row.get("报告期") or row.get("reportDate") or ""),
                        "primaryDocument": title,
                        "url": str(row.get("公告链接") or row.get("链接") or row.get("adjunctUrl") or ""),
                    }
                )
        if not disclosures:
            return {"ok": False, "sourceName": "AkShare cninfo disclosure", "error": "No CNInfo disclosure rows returned"}
        return {"ok": True, "sourceName": "AkShare cninfo disclosure", "filings": disclosures, "count": len(disclosures)}
    except Exception as exc:
        return {"ok": False, "sourceName": "AkShare cninfo disclosure", "error": str(exc)}


def try_fetch_disclosures(symbol: str, market: str) -> dict[str, Any]:
    if market == "us":
        return try_fetch_sec_filings(symbol)
    if market == "cn":
        return try_fetch_cninfo_disclosures(symbol)
    return {"ok": False, "sourceName": "disclosure provider", "error": f"Unsupported market {market}"}


def try_fetch_market_snapshot(
    symbol: str,
    market: str,
    *,
    build_source_meta: Callable[..., dict[str, Any]],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
) -> dict[str, Any]:
    if market == "us":
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(symbol)
            history = ticker.history(period="5d", auto_adjust=True)
            if not history.empty:
                latest = history.iloc[-1]
                previous = history.iloc[-2] if len(history) > 1 else latest
                close = float(latest["Close"])
                change = ((close - float(previous["Close"])) / float(previous["Close"])) * 100 if float(previous["Close"]) else 0
                observed_at = iso(now_utc())
                return {
                    "ok": True,
                    "marketValueHint": close,
                    "dayChange": round(change, 2),
                    "sourceName": "yfinance",
                    "observedAt": observed_at,
                    "sourceMeta": build_source_meta(provider="yfinance", as_of=observed_at, overrides=[], synthetic_ratio=0.0),
                }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "sourceName": "yfinance",
                "sourceMeta": build_source_meta(provider="yfinance", as_of=iso(now_utc()), overrides=["failed"], synthetic_ratio=0.0),
            }
    if market == "cn":
        try:
            import akshare as ak  # type: ignore

            spot = ak.stock_zh_a_spot_em()
            row = spot[spot["代码"].astype(str) == symbol]
            if not row.empty:
                latest = row.iloc[0]
                observed_at = iso(now_utc())
                return {
                    "ok": True,
                    "marketValueHint": float(latest["最新价"]),
                    "dayChange": float(latest["涨跌幅"]),
                    "sourceName": "AkShare",
                    "observedAt": observed_at,
                    "sourceMeta": build_source_meta(provider="AkShare", as_of=observed_at, overrides=[], synthetic_ratio=0.0),
                }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "sourceName": "AkShare",
                "sourceMeta": build_source_meta(provider="AkShare", as_of=iso(now_utc()), overrides=["failed"], synthetic_ratio=0.0),
            }
    return {
        "ok": False,
        "error": "unsupported or unavailable source",
        "sourceName": "local cache",
        "sourceMeta": build_source_meta(provider="local cache", as_of=iso(now_utc()), overrides=["manual_override"], synthetic_ratio=0.0),
    }


def try_fetch_news_events(symbol: str, market: str) -> dict[str, Any]:
    if market == "us":
        try:
            import yfinance as yf  # type: ignore

            raw_news = yf.Ticker(symbol).news or []
            articles = []
            for item in raw_news[:5]:
                content = item.get("content", item) if isinstance(item, dict) else {}
                title = content.get("title") or item.get("title") if isinstance(item, dict) else None
                link = content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("link")
                publisher = content.get("provider", {}).get("displayName") if isinstance(content.get("provider"), dict) else content.get("publisher")
                published = content.get("pubDate") or content.get("providerPublishTime") or item.get("providerPublishTime") if isinstance(item, dict) else None
                if title:
                    articles.append({"title": title, "url": link, "publisher": publisher or "Yahoo Finance", "publishedAt": str(published or "")})
            if articles:
                return {"ok": True, "articles": articles, "sourceName": "yfinance news", "count": len(articles)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sourceName": "yfinance news"}
    if market == "cn":
        try:
            import akshare as ak  # type: ignore

            news = ak.stock_news_em(symbol=symbol)
            articles = []
            for _, row in news.head(5).iterrows():
                title = str(row.get("新闻标题") or row.get("标题") or row.get("title") or "")
                if title:
                    articles.append(
                        {
                            "title": title,
                            "url": str(row.get("新闻链接") or row.get("链接") or ""),
                            "publisher": str(row.get("文章来源") or row.get("来源") or "东方财富新闻"),
                            "publishedAt": str(row.get("发布时间") or row.get("时间") or ""),
                        }
                    )
            if articles:
                return {"ok": True, "articles": articles, "sourceName": "AkShare stock_news_em", "count": len(articles)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sourceName": "AkShare stock_news_em"}
    return {"ok": False, "error": "unsupported market for news provider", "sourceName": "news provider"}
