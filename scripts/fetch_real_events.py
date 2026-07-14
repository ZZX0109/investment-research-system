#!/usr/bin/env python3
"""Fetch real point-in-time events with authority-first provider routing.

Outputs:
- output/events_{market}.pkl
- temp/fetch_events_validation.json
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import signal
import sys
import time
from contextlib import contextmanager
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = Path(os.environ.get("INVESTMENT_RESEARCH_OUTPUT_DIR", PROJECT / "output"))
TEMP = Path(os.environ.get("INVESTMENT_RESEARCH_TEMP_DIR", PROJECT / "temp"))
INTERMEDIATE = TEMP / "fetch_intermediate"

sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.catalog import UNIVERSE_PRESETS, market_symbols
from investment_research.training.models import DataProvider, EventSourceTier, EventType, PointInTimeEvent
from investment_research.training.sources import (
    infer_event_direction,
    infer_event_intensity,
    infer_event_type,
    infer_guidance_bucket,
    infer_surprise_bucket,
    normalize_cn_announcements,
    normalize_news_rows,
    normalize_sec_filings,
)

MARKET_SYMBOLS: dict[str, list[str]] = {
    "us": market_symbols("us"),
    "cn": market_symbols("cn"),
    "hk": market_symbols("hk"),
    "jp": market_symbols("jp"),
}
MAX_RETRIES = 3
TICKER_DELAY = 0.75
SEC_TIMEOUT = 20
YFINANCE_TIMEOUT = 20
SEC_TICKER_CACHE = INTERMEDIATE / "sec_company_tickers.json"
HKEX_NEWS_URL = "https://www.hkexnews.hk/ncms/json/eds/lcisehk7relsde_1.json"
_HKEX_NEWS_CACHE: dict | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_key(event: PointInTimeEvent) -> tuple[str, str, str, str]:
    return (
        event.symbol,
        event.event_type.value,
        event.published_at.isoformat(),
        event.payload_ref or event.source_url or "",
    )


def _security_code(symbol: str) -> str:
    clean = symbol.upper()
    for suffix in (".SH", ".SZ", ".HK", ".T"):
        if clean.endswith(suffix):
            return clean[:-len(suffix)]
    return clean.replace("^", "")


def _record_failure(provider_failures: list[dict], *, provider: str, symbol: str, attempt: int, error: Exception | str) -> None:
    provider_failures.append(
        {
            "provider": provider,
            "symbol": symbol,
            "attempt": attempt,
            "error": str(error),
            "at": _now(),
        }
    )


def _load_sec_ticker_map() -> dict[str, dict]:
    INTERMEDIATE.mkdir(parents=True, exist_ok=True)
    if SEC_TICKER_CACHE.exists():
        return json.loads(SEC_TICKER_CACHE.read_text(encoding="utf-8"))
    response = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": "Codex/1.0 zzxin@example.com"},
        timeout=SEC_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    mapping = {
        entry["ticker"].upper(): entry
        for entry in payload.values()
        if isinstance(entry, dict) and entry.get("ticker")
    }
    SEC_TICKER_CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping


def fetch_sec_filings(symbol: str, provider_failures: list[dict]) -> list[PointInTimeEvent]:
    ticker_map = _load_sec_ticker_map()
    entry = ticker_map.get(symbol.upper())
    if not entry:
        return []
    cik = str(entry["cik_str"]).zfill(10)
    headers = {"User-Agent": "Codex/1.0 zzxin@example.com"}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers=headers,
                timeout=SEC_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            recent = payload.get("filings", {}).get("recent", {})
            accession_numbers = recent.get("accessionNumber", [])
            forms = recent.get("form", [])
            filing_dates = recent.get("filingDate", [])
            acceptance_times = recent.get("acceptanceDateTime", [])
            primary_docs = recent.get("primaryDocument", [])
            rows: list[dict] = []
            for accession, form, filing_date, acceptance_time, primary_doc in zip(
                accession_numbers,
                forms,
                filing_dates,
                acceptance_times,
                primary_docs,
            ):
                accession_nodash = str(accession).replace("-", "")
                rows.append(
                    {
                        "form": form,
                        "acceptance_datetime": acceptance_time,
                        "filed_at": filing_date,
                        "accession_number": accession,
                        "url": (
                            f"https://www.sec.gov/Archives/edgar/data/"
                            f"{int(entry['cik_str'])}/{accession_nodash}/{quote(str(primary_doc))}"
                        ),
                    }
                )
            return normalize_sec_filings(symbol, rows)
        except Exception as exc:
            _record_failure(provider_failures, provider="sec_filings", symbol=symbol, attempt=attempt, error=exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return []


def _tag_pre_post_market(dt: datetime) -> str:
    hour_est = (dt.hour - 5) % 24 if dt.tzinfo else dt.hour
    return "post_market" if hour_est >= 16 else "pre_market"


def fetch_earnings(symbol: str, provider_failures: list[dict]) -> list[PointInTimeEvent]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            import yfinance as yf

            with _time_limit(YFINANCE_TIMEOUT):
                frame = yf.Ticker(symbol).earnings_dates
            if frame is None or frame.empty:
                return []
            events: list[PointInTimeEvent] = []
            for idx, row in frame.iterrows():
                dt = idx if isinstance(idx, datetime) else datetime.combine(idx, datetime.min.time())
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                tag = _tag_pre_post_market(dt)
                surprise_bucket = _earnings_surprise_bucket_from_row(row)
                events.append(
                    PointInTimeEvent(
                        symbol=symbol.upper(),
                        event_type=EventType.EARNINGS,
                        event_time=dt.astimezone(timezone.utc),
                        published_at=dt.astimezone(timezone.utc),
                        source_name="yfinance",
                        source_url=f"https://finance.yahoo.com/quote/{symbol}/analysis",
                        headline=f"Earnings ({tag})",
                        payload_ref=f"{symbol}:{dt.isoformat()}",
                        event_direction=_earnings_direction_from_surprise(surprise_bucket),
                        surprise_bucket=surprise_bucket,
                        provider=DataProvider.YFINANCE.value,
                        as_of=dt.astimezone(timezone.utc),
                        raw_hash=_hash_payload(
                            {
                                "symbol": symbol.upper(),
                                "published_at": dt.astimezone(timezone.utc).isoformat(),
                                "tag": tag,
                                "row": _jsonable_row(row),
                            }
                        ),
                        normalized_hash=_hash_payload(
                            {
                                "symbol": symbol.upper(),
                                "event_type": EventType.EARNINGS.value,
                                "published_at": dt.astimezone(timezone.utc).isoformat(),
                                "payload_ref": f"{symbol}:{dt.isoformat()}",
                            }
                        ),
                        data_version=f"{DataProvider.YFINANCE.value}:{dt.date().isoformat()}",
                    )
                )
            return events
        except Exception as exc:
            _record_failure(provider_failures, provider="earnings_yfinance", symbol=symbol, attempt=attempt, error=exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return []


def fetch_news(symbol: str, provider_failures: list[dict]) -> list[PointInTimeEvent]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            import yfinance as yf

            with _time_limit(YFINANCE_TIMEOUT):
                raw_items = yf.Ticker(symbol).news or []
            rows: list[dict] = []
            skipped_missing_time = 0
            for item in raw_items:
                published_at = _extract_news_published_at(item)
                if published_at is None:
                    skipped_missing_time += 1
                    continue
                rows.append(
                    {
                        "headline": _extract_news_title(item),
                        "published_at": published_at,
                        "id": _extract_news_id(item),
                        "url": _extract_news_url(item),
                    }
                )
            if skipped_missing_time:
                _record_failure(
                    provider_failures,
                    provider="news_yfinance_skipped",
                    symbol=symbol,
                    attempt=0,
                    error=f"skipped {skipped_missing_time} news items without published_at",
                )
            return normalize_news_rows(symbol, rows, provider=DataProvider.YFINANCE)
        except Exception as exc:
            _record_failure(provider_failures, provider="news_yfinance", symbol=symbol, attempt=attempt, error=exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return []


def fetch_cn_announcements(symbol: str, provider_failures: list[dict]) -> list[PointInTimeEvent]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            import akshare as ak

            code = _security_code(symbol)
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=code,
                market="沪深京",
                start_date="20240101",
                end_date=datetime.now().strftime("%Y%m%d"),
            )
            if frame is None or frame.empty:
                return []
            rows = [
                {
                    "title": row.get("公告标题"),
                    "published_at": row.get("公告时间"),
                    "id": row.get("公告链接"),
                    "url": row.get("公告链接"),
                }
                for _, row in frame.iterrows()
            ]
            return normalize_cn_announcements(symbol, rows)
        except Exception as exc:
            _record_failure(provider_failures, provider="cninfo_announcements", symbol=symbol, attempt=attempt, error=exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return []


def fetch_hk_announcements(symbol: str, provider_failures: list[dict]) -> list[PointInTimeEvent]:
    code = _security_code(symbol).zfill(5)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            payload = _load_hkex_news_payload()
            events: list[PointInTimeEvent] = []
            for item in payload.get("newsInfoLst", []):
                stocks = item.get("stock", []) if isinstance(item, dict) else []
                if not any(str(stock.get("sc", "")).zfill(5) == code for stock in stocks if isinstance(stock, dict)):
                    continue
                published_at = _parse_hkex_release_time(item.get("relTime"))
                title = item.get("title") or item.get("lTxt") or item.get("sTxt") or "HKEX announcement"
                event_type = infer_event_type(title)
                source_url = _hkex_url(item.get("webPath"))
                payload_ref = str(item.get("newsId") or source_url or f"{symbol}:{published_at.isoformat()}")
                events.append(
                    PointInTimeEvent(
                        symbol=symbol.upper(),
                        event_type=event_type,
                        event_time=published_at,
                        published_at=published_at,
                        source_name="hkexnews",
                        source_url=source_url,
                        headline=title,
                        payload_ref=payload_ref,
                        event_direction=infer_event_direction(title),
                        event_intensity=infer_event_intensity(title),
                        source_tier=EventSourceTier.EXCHANGE,
                        surprise_bucket=infer_surprise_bucket(title),
                        guidance_bucket=infer_guidance_bucket(title),
                        provider="hkex_announcements",
                        as_of=published_at,
                        raw_hash=_hash_payload(item),
                        normalized_hash=_hash_payload(
                            {
                                "symbol": symbol.upper(),
                                "event_type": event_type.value,
                                "published_at": published_at.isoformat(),
                                "payload_ref": payload_ref,
                                "headline": title,
                            }
                        ),
                        data_version=f"hkex_announcements:{published_at.date().isoformat()}",
                    )
                )
            return events
        except Exception as exc:
            _record_failure(provider_failures, provider="hkex_announcements", symbol=symbol, attempt=attempt, error=exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return []


def _load_hkex_news_payload() -> dict:
    global _HKEX_NEWS_CACHE
    if _HKEX_NEWS_CACHE is not None:
        return _HKEX_NEWS_CACHE
    response = requests.get(
        HKEX_NEWS_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WorkBuddyResearch/1.0)"},
        timeout=SEC_TIMEOUT,
    )
    response.raise_for_status()
    _HKEX_NEWS_CACHE = response.json()
    return _HKEX_NEWS_CACHE


def _extract_news_published_at(item: dict) -> str | None:
    candidates = [
        item.get("providerPublishTime"),
        item.get("published_at"),
        item.get("pubDate"),
        item.get("date"),
        item.get("displayTime"),
    ]
    content = item.get("content")
    if isinstance(content, dict):
        candidates.extend([content.get("providerPublishTime"), content.get("pubDate"), content.get("displayTime")])
    for value in candidates:
        parsed = _coerce_optional_datetime(value)
        if parsed is not None:
            return parsed.isoformat()
    return None


def _jsonable_row(row) -> dict:
    if hasattr(row, "to_dict"):
        return {str(key): _jsonable_value(value) for key, value in row.to_dict().items()}
    if isinstance(row, dict):
        return {str(key): _jsonable_value(value) for key, value in row.items()}
    return {}


def _jsonable_value(value):
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _earnings_surprise_bucket_from_row(row):
    payload = _jsonable_row(row)
    actual = _optional_float(
        payload.get("Reported EPS")
        or payload.get("reported_eps")
        or payload.get("epsActual")
        or payload.get("actual")
    )
    estimate = _optional_float(
        payload.get("EPS Estimate")
        or payload.get("eps_estimate")
        or payload.get("epsEstimate")
        or payload.get("estimate")
    )
    surprise_pct = _optional_float(
        payload.get("Surprise(%)")
        or payload.get("surprise_pct")
        or payload.get("surprisePercent")
        or payload.get("surprise")
    )
    if surprise_pct is None and actual is not None and estimate not in (None, 0):
        surprise_pct = ((actual - estimate) / abs(estimate)) * 100.0
    from investment_research.training.models import SurpriseBucket

    if surprise_pct is None:
        return SurpriseBucket.UNKNOWN
    if surprise_pct >= 10:
        return SurpriseBucket.BIG_BEAT
    if surprise_pct >= 1:
        return SurpriseBucket.BEAT
    if surprise_pct <= -10:
        return SurpriseBucket.BIG_MISS
    if surprise_pct <= -1:
        return SurpriseBucket.MISS
    return SurpriseBucket.INLINE


def _earnings_direction_from_surprise(surprise_bucket):
    from investment_research.training.models import EventDirection, SurpriseBucket

    if surprise_bucket in {SurpriseBucket.BIG_BEAT, SurpriseBucket.BEAT}:
        return EventDirection.POSITIVE
    if surprise_bucket in {SurpriseBucket.BIG_MISS, SurpriseBucket.MISS}:
        return EventDirection.NEGATIVE
    if surprise_bucket == SurpriseBucket.INLINE:
        return EventDirection.NEUTRAL
    return EventDirection.UNKNOWN


def _optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return None


def _coerce_optional_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            return datetime.fromtimestamp(int(stripped), tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _extract_news_title(item: dict) -> str | None:
    content = item.get("content")
    if isinstance(content, dict):
        return item.get("title") or item.get("headline") or content.get("title") or content.get("headline")
    return item.get("title") or item.get("headline")


def _extract_news_id(item: dict) -> str | None:
    content = item.get("content")
    if isinstance(content, dict):
        return item.get("uuid") or item.get("id") or content.get("id") or item.get("link")
    return item.get("uuid") or item.get("id") or item.get("link")


def _extract_news_url(item: dict) -> str | None:
    content = item.get("content")
    if isinstance(content, dict):
        canonical = content.get("canonicalUrl")
        if isinstance(canonical, dict):
            return canonical.get("url")
        return item.get("link") or item.get("url") or content.get("url")
    return item.get("link") or item.get("url")


def _parse_hkex_release_time(value: str | None) -> datetime:
    if not value:
        raise ValueError("HKEX release time is missing")
    local_time = datetime.strptime(value, "%d/%m/%Y %H:%M")
    return local_time.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)


def _hkex_url(path: str | None) -> str | None:
    if not path or path == "NaN":
        return None
    if path.startswith("http"):
        return path
    return f"https://www.hkexnews.hk{path}"


def fetch_market_events(market: str, symbols: list[str]) -> tuple[list[PointInTimeEvent], dict]:
    all_events: list[PointInTimeEvent] = []
    seen: set[tuple[str, str, str, str]] = set()
    provider_failures: list[dict] = []
    provider_counts: Counter[str] = Counter()
    event_type_counts: Counter[str] = Counter()
    symbol_density: Counter[str] = Counter()
    provider_symbol_coverage: dict[str, set[str]] = defaultdict(set)

    for index, symbol in enumerate(symbols, start=1):
        print(f"  [{index}/{len(symbols)}] {symbol}")
        provider_batches: list[tuple[str, list[PointInTimeEvent]]] = []
        preset = UNIVERSE_PRESETS.get(symbol)
        is_equity = preset is None or preset.instrument_type.value == "equity"
        if market == "us":
            provider_batches.append(("sec_filings", fetch_sec_filings(symbol, provider_failures)))
        elif market == "cn":
            provider_batches.append(("cninfo_announcements", fetch_cn_announcements(symbol, provider_failures)))
        elif market == "hk" and is_equity:
            provider_batches.append(("hkex_announcements", fetch_hk_announcements(symbol, provider_failures)))

        if is_equity:
            provider_batches.append(("earnings_yfinance", fetch_earnings(symbol, provider_failures)))
            provider_batches.append(("news_yfinance", fetch_news(symbol, provider_failures)))
        else:
            _record_failure(
                provider_failures,
                provider="yfinance_events_skipped",
                symbol=symbol,
                attempt=0,
                error="skipped earnings/news for non-equity instrument",
            )

        for provider_name, events in provider_batches:
            if events:
                provider_symbol_coverage[provider_name].add(symbol)
            for event in events:
                key = _event_key(event)
                if key in seen:
                    continue
                seen.add(key)
                all_events.append(event)
                provider_counts[provider_name] += 1
                event_type_counts[event.event_type.value] += 1
                symbol_density[event.symbol] += 1
        if index < len(symbols):
            time.sleep(TICKER_DELAY)

    report = {
        "symbol_count": len(symbols),
        "event_count": len(all_events),
        "provider_counts": dict(provider_counts),
        "event_type_counts": dict(event_type_counts),
        "event_density_by_symbol": dict(symbol_density),
        "provider_coverage": {
            provider: {
                "symbols_with_events": len(symbol_set),
                "event_count": provider_counts.get(provider, 0),
            }
            for provider, symbol_set in provider_symbol_coverage.items()
        },
        "provider_failures": provider_failures,
    }
    return all_events, report


@contextmanager
def _time_limit(seconds: int):
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _raise_timeout(_signum, _frame):
        raise TimeoutError(f"provider call exceeded {seconds}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    INTERMEDIATE.mkdir(parents=True, exist_ok=True)

    validation: dict[str, dict] = {}
    selected_markets = set(filter(None, os.environ.get("INVESTMENT_RESEARCH_MARKETS", "").split(",")))
    for market, symbols in MARKET_SYMBOLS.items():
        if selected_markets and market not in selected_markets:
            continue
        print(f"\n{'=' * 60}")
        print(f" Events: {market.upper()} ({len(symbols)} symbols)")
        print(f"{'=' * 60}")
        events, report = fetch_market_events(market, symbols)
        with open(OUTPUT / f"events_{market}.pkl", "wb") as f:
            pickle.dump(events, f)
        validation[market] = report
        print(
            f"  saved events_{market}.pkl: "
            f"events={report['event_count']} "
            f"types={report['event_type_counts']} "
            f"providers={report['provider_counts']}"
        )

    (TEMP / "fetch_events_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nValidation report written: {TEMP / 'fetch_events_validation.json'}")
    return 0


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
