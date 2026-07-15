#!/usr/bin/env python3
"""Collect public research data without pretending it is licensed PIT data.

Every response is persisted through ``RawPayloadIngestionService`` before a
future normalizer can consume it.  The produced coverage ledger is explicit:
failure, unsupported and empty-success are different states.  This command
never creates synthetic values and never writes a formal-ready manifest.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from investment_research.service.free_research_ledger import build_coverage_ledgers
from investment_research.training.cn_free_providers import (
    AkshareDailyResearchProvider,
    BaostockDailyResearchProvider,
    ETF_RESEARCH_SYMBOLS,
    compare_public_daily_payloads,
    deterministic_cross_check,
)
from investment_research.training.cn_research_collection import (
    CollectionCursor,
    CursorStore,
    ProviderPolicy,
    SerialRateLimiter,
    call_with_retry,
)


DEFAULT_SYMBOLS = {
    "cn": ["600519", "000001", "300750", "510300"],
    "us": ["AAPL", "MSFT", "SPY", "QQQ"],
    "hk": ["0700.HK", "9988.HK", "2800.HK"],
    "jp": ["7203.T", "6758.T", "1306.T"],
}

# Public CSV endpoints.  These are macro research inputs, not tradable prices.
FRED_SERIES = ("DFF", "DGS10", "DTWEXBGS", "VIXCLS", "USRECM")


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect free public research data")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--cursor-store", type=Path, default=PROJECT / "var/cn-research/cursors.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--markets", nargs="+", choices=sorted(DEFAULT_SYMBOLS), default=["cn"])
    parser.add_argument("--only", nargs="+", choices=["prices", "events", "macro"], default=["prices", "events", "macro"], help="Dataset groups to collect; use this for retrying one source without re-downloading all groups.")
    parser.add_argument("--catalog", type=Path, default=PROJECT / "config/free_research_data_catalog.yaml")
    parser.add_argument("--symbols-file", type=Path, help="JSON/YAML mapping of market to a publicly enumerated research universe.")
    parser.add_argument("--max-symbols-per-market", type=int, default=None, help="Optional safety cap; the coverage ledger keeps the exact capped target set.")
    parser.add_argument("--no-discover-cn-universe", action="store_true", help="Use the configured fallback CN symbols instead of enumerating the public current universe.")
    parser.add_argument("--full-history", action="store_true", help="Backfill all available history; daily runs use a bounded lookback by default.")
    parser.add_argument("--lookback-days", type=int, default=None, help="Calendar-day lookback for incremental daily collection.")
    parser.add_argument("--cross-check-ratio", type=float, default=None, help="Deterministic daily AKShare/Baostock comparison ratio.")
    parser.add_argument("--list-catalog", action="store_true", help="Print the complete supported free-data inventory and exit without network or database access.")
    return parser.parse_args()


def main() -> int:
    options = args()
    if options.list_catalog:
        print(options.catalog.read_text(encoding="utf-8"), end="")
        return 0
    config = yaml.safe_load((PROJECT / "config/free_research_sources.yaml").read_text())
    symbols_by_market = _symbols_by_market(
        options.symbols_file, options.max_symbols_per_market,
        discover_cn=not options.no_discover_cn_universe,
    )
    uow = SQLiteUnitOfWork(options.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(options.object_store))
    ledger: list[dict] = []
    try:
        for market in options.markets:
            if "prices" in options.only:
                if market == "cn":
                    ledger.extend(_collect_cn_prices(
                        service, symbols_by_market[market],
                        full_history=options.full_history,
                        lookback_days=options.lookback_days or int(config["collection"]["incremental_lookback_calendar_days"]),
                        cross_check_ratio=(options.cross_check_ratio if options.cross_check_ratio is not None else float(config["collection"]["cross_check_daily_ratio"])),
                        cursor_store=CursorStore(options.cursor_store),
                        config=config["collection"],
                    ))
                else:
                    for symbol in symbols_by_market[market]:
                        ledger.append(_collect_price(service, market, symbol, config))
            if "events" in options.only:
                ledger.extend(_collect_events(service, market, config, symbols_by_market[market]))
            if market == "us" and "macro" in options.only:
                ledger.extend(_collect_fred_macro(service))
    finally:
        uow.close()
    prior_records: list[dict] = []
    if options.output.is_file():
        try:
            prior_records = list(json.loads(options.output.read_text(encoding="utf-8")).get("records", []))
        except (ValueError, TypeError):
            prior_records = []
    # A partial retry replaces only the requested dataset groups, retaining
    # successful coverage records from groups that were not run this time.
    group_by_dataset = {
        "daily_bars": "prices", "daily_bars_raw": "prices", "daily_bars_qfq": "prices",
        "security_master": "events", "filings": "events",
        "companyfacts": "events", "events": "events", "macro_series_bundle": "macro",
    }
    retained = [
        item for item in prior_records
        if item.get("market") not in options.markets
        or group_by_dataset.get(item.get("dataset"), "events") not in options.only
    ]
    generated_at = datetime.now(timezone.utc)
    coverage_ledgers = build_coverage_ledgers(
        records=[*retained, *ledger],
        targets={market: set(symbols_by_market[market]) for market in symbols_by_market},
        generated_at=generated_at,
    )
    output = {
        "schema_version": "free-research-coverage-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "catalog_ref": str(options.catalog.relative_to(PROJECT)) if options.catalog.is_relative_to(PROJECT) else str(options.catalog),
        "generated_at": generated_at.isoformat(),
        "mode": "research_only",
        "formal_deployment_allowed": False,
        "synthetic_count": 0,
        "records": [*retained, *ledger],
        "market_coverage": [item.model_dump(mode="json") for item in coverage_ledgers],
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _collect_cn_prices(
    service, symbols: list[str], *, full_history: bool, lookback_days: int,
    cross_check_ratio: float, cursor_store: CursorStore, config: dict,
) -> list[dict]:
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if not 0 <= cross_check_ratio <= 1:
        raise ValueError("cross_check_ratio must be between zero and one")
    end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    configured_start = None if full_history else end - timedelta(days=lookback_days)
    primary = AkshareDailyResearchProvider()
    primary_policy = ProviderPolicy(
        requests_per_second=float(config.get("primary_requests_per_second", 2)),
        max_attempts=int(config.get("max_attempts", 4)),
        backoff_seconds=tuple(float(value) for value in config.get("retry_backoff_seconds", [1, 2, 4, 8])),
    )
    backup_policy = ProviderPolicy(
        requests_per_second=float(config.get("backup_requests_per_second", 1)),
        max_attempts=int(config.get("max_attempts", 4)),
        backoff_seconds=tuple(float(value) for value in config.get("retry_backoff_seconds", [1, 2, 4, 8])),
    )
    primary_limiter = SerialRateLimiter(primary_policy.requests_per_second)
    backup_limiter = SerialRateLimiter(backup_policy.requests_per_second)
    primary_failed_modes: set[str] = set()
    output: list[dict] = []
    try:
        backup_context = BaostockDailyResearchProvider()
        backup = backup_context.__enter__()
    except Exception as exc:
        backup_context = nullcontext()
        backup = None
        backup_unavailable = f"{type(exc).__name__}:{exc}"
    else:
        backup_unavailable = None
    try:
        for symbol in symbols:
          for adjustment_mode in ("raw", "qfq"):
            cursor = cursor_store.get(primary.name, symbol, adjustment_mode)
            start = configured_start if cursor is None else cursor.overlap_start
            if configured_start is not None and start < configured_start:
                start = configured_start
            try:
                if adjustment_mode in primary_failed_modes:
                    raise RuntimeError(f"akshare_circuit_open:{adjustment_mode}")
                primary_payload, primary_attempts = call_with_retry(
                    lambda: primary.fetch(symbol, start=start, end=end, adjustment_mode=adjustment_mode),
                    policy=primary_policy, limiter=primary_limiter,
                )
                primary_batch = _persist(
                    service, primary.name, f"daily_bars_{adjustment_mode}", symbol,
                    primary_payload.payload, coverage_start=start, coverage_end=end,
                )
                cursor_store.put(CollectionCursor(
                    provider=primary.name, symbol=symbol, adjustment_mode=adjustment_mode,
                    last_successful_trade_date=end, updated_at=datetime.now(timezone.utc),
                    payload_hash=primary_batch.payload_hash,
                ))
            except Exception as primary_exc:
                primary_failed_modes.add(adjustment_mode)
                if backup is None:
                    output.append({
                        "market": "cn", "dataset": f"daily_bars_{adjustment_mode}", "symbol": symbol,
                        "adjustment_mode": adjustment_mode,
                        "provider": primary.name, "provider_chain": [primary.name, "baostock"],
                        "status": "fetch_failed",
                        "reason": f"primary={type(primary_exc).__name__}:{primary_exc};backup={backup_unavailable}",
                    })
                    continue
                try:
                    fallback, backup_attempts = call_with_retry(
                        lambda: backup.fetch(symbol, start=start, end=end, adjustment_mode=adjustment_mode),
                        policy=backup_policy, limiter=backup_limiter,
                    )
                    batch = _persist(
                        service, backup.name, f"daily_bars_{adjustment_mode}", symbol,
                        fallback.payload, coverage_start=start, coverage_end=end,
                    )
                    cursor_store.put(CollectionCursor(
                        provider=backup.name, symbol=symbol, adjustment_mode=adjustment_mode,
                        last_successful_trade_date=end, updated_at=datetime.now(timezone.utc),
                        payload_hash=batch.payload_hash,
                    ))
                    output.append({
                        "market": "cn", "dataset": f"daily_bars_{adjustment_mode}", "symbol": symbol,
                        "adjustment_mode": adjustment_mode,
                        "provider": backup.name, "provider_chain": [primary.name, backup.name],
                        "status": "backfilled", "rows_or_bytes": fallback.row_count,
                        "payload_hash": batch.payload_hash,
                        "attempts": backup_attempts, "cache_state": "fresh",
                        "degraded_reason": f"akshare_failed:{type(primary_exc).__name__}",
                    })
                except Exception as fallback_exc:
                    output.append({
                        "market": "cn", "dataset": f"daily_bars_{adjustment_mode}", "symbol": symbol,
                        "adjustment_mode": adjustment_mode,
                        "provider": primary.name, "provider_chain": [primary.name, backup.name],
                        "status": "fetch_failed",
                        "reason": f"primary={type(primary_exc).__name__}:{primary_exc};backup={type(fallback_exc).__name__}:{fallback_exc}",
                    })
                continue
            should_compare = symbol in ETF_RESEARCH_SYMBOLS or deterministic_cross_check(symbol, end, ratio=cross_check_ratio)
            if not should_compare or backup is None:
                output.append({
                    "market": "cn", "dataset": f"daily_bars_{adjustment_mode}", "symbol": symbol,
                    "adjustment_mode": adjustment_mode,
                    "provider": primary.name, "provider_chain": [primary.name],
                    "status": "backfilled", "rows_or_bytes": primary_payload.row_count,
                    "payload_hash": primary_batch.payload_hash,
                    "attempts": primary_attempts, "cache_state": "fresh",
                    **({"degraded_reason": f"baostock_unavailable:{backup_unavailable}"} if backup is None else {}),
                })
                continue
            try:
                fallback, backup_attempts = call_with_retry(
                    lambda: backup.fetch(symbol, start=start, end=end, adjustment_mode=adjustment_mode),
                    policy=backup_policy, limiter=backup_limiter,
                )
                backup_batch = _persist(
                    service, backup.name, f"daily_bars_{adjustment_mode}", symbol,
                    fallback.payload, coverage_start=start, coverage_end=end,
                )
                cursor_store.put(CollectionCursor(
                    provider=backup.name, symbol=symbol, adjustment_mode=adjustment_mode,
                    last_successful_trade_date=end, updated_at=datetime.now(timezone.utc),
                    payload_hash=backup_batch.payload_hash,
                ))
                comparison = compare_public_daily_payloads(primary_payload.payload, fallback.payload)
                output.append({
                    "market": "cn", "dataset": f"daily_bars_{adjustment_mode}", "symbol": symbol,
                    "adjustment_mode": adjustment_mode,
                    "provider": primary.name, "provider_chain": [primary.name, backup.name],
                    "status": "partial" if comparison.severe else "backfilled",
                    "rows_or_bytes": primary_payload.row_count,
                    "payload_hash": primary_batch.payload_hash,
                    "backup_payload_hash": backup_batch.payload_hash,
                    "attempts": {"primary": primary_attempts, "backup": backup_attempts},
                    "cache_state": "fresh",
                    "provider_comparison": comparison.__dict__,
                    **({"degraded_reason": "provider_conflict"} if comparison.severe else {}),
                })
            except Exception as comparison_exc:
                output.append({
                    "market": "cn", "dataset": f"daily_bars_{adjustment_mode}", "symbol": symbol,
                    "adjustment_mode": adjustment_mode,
                    "provider": primary.name, "provider_chain": [primary.name, "baostock"],
                    "status": "backfilled", "rows_or_bytes": primary_payload.row_count,
                    "payload_hash": primary_batch.payload_hash,
                    "degraded_reason": f"baostock_cross_check_failed:{type(comparison_exc).__name__}",
                })
    finally:
        if backup is not None:
            backup_context.__exit__(None, None, None)
    return output


def _collect_price(service, market: str, symbol: str, config: dict) -> dict:
    # CN is collected by ``_collect_cn_prices``. Keep this compatibility path
    # fail-closed so an AKShare error can never become a yfinance CN record.
    if market == "cn":
        return {
            "market": "cn", "dataset": "daily_bars", "symbol": symbol,
            "provider": "akshare", "provider_chain": ["akshare", "baostock"],
            "status": "fetch_failed",
            "reason": "cn_generic_price_path_disabled_use_akshare_baostock_adapter",
        }
    provider = config["markets"][market]["prices"]
    try:
        if provider == "akshare":
            import akshare as ak
            raw = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="")
            payload = raw.to_json(orient="records", force_ascii=False).encode()
        else:
            import yfinance as yf
            raw = yf.download(symbol, period="max", interval="1d", progress=False, auto_adjust=False)
            payload = raw.reset_index().to_json(orient="records", date_format="iso").encode()
        _persist(service, provider, "daily_bars", symbol, payload)
        return {"market": market, "dataset": "daily_bars", "symbol": symbol, "provider": provider, "status": "backfilled", "rows_or_bytes": len(payload)}
    except Exception as exc:
        return {"market": market, "dataset": "daily_bars", "symbol": symbol, "provider": provider, "status": "fetch_failed", "reason": f"{type(exc).__name__}:{exc}"}


def _collect_events(service, market: str, config: dict, symbols: list[str]) -> list[dict]:
    # Event sources differ sharply by market. The explicit unsupported statuses
    # prevent zero-event features from being inferred when no collector exists.
    output = []
    for provider in config["markets"][market]["events"]:
        try:
            if provider == "akshare_cninfo_notices":
                output.append(_collect_cninfo_notices(service))
                continue
            import requests
            if provider == "sec_edgar":
                url = "https://www.sec.gov/files/company_tickers.json"
                dataset = "security_master"
                headers = {"User-Agent": "investment-research research@example.invalid"}
            elif provider == "hkexnews":
                url = "https://www.hkexnews.hk/ncms/json/eds/lcisehk7relsde_1.json"
                dataset = "events"
                headers = {"User-Agent": "Mozilla/5.0 (compatible; FreeResearch/1.0)"}
            elif provider == "edinet":
                result = _collect_edinet_recent(service, market)
                output.append(result)
                continue
            else:
                output.append({"market": market, "dataset": "events", "provider": provider, "status": "unsupported", "reason": "public_adapter_not_implemented"})
                continue
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            _persist(service, provider, dataset, None, response.content)
            output.append({"market": market, "dataset": dataset, "provider": provider, "status": "backfilled", "rows_or_bytes": len(response.content)})
            if provider == "sec_edgar":
                output.extend(_collect_sec_company_records(service, response.json(), symbols))
        except Exception as exc:
            output.append({"market": market, "dataset": "security_master", "provider": provider, "status": "fetch_failed", "reason": f"{type(exc).__name__}:{exc}"})
    return output


def _collect_cninfo_notices(service) -> dict:
    """Persist a rolling public announcement window without claiming completeness."""
    import akshare as ak

    rows: list[dict] = []
    successes = 0
    failures: list[str] = []
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    for offset in range(0, 8):
        candidate = today - timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        try:
            frame = ak.stock_notice_report(symbol="全部", date=candidate.strftime("%Y%m%d"))
            successes += 1
            if not frame.empty:
                rows.extend(json.loads(frame.to_json(orient="records", force_ascii=False, date_format="iso")))
        except Exception as exc:
            failures.append(f"{candidate.isoformat()}:{type(exc).__name__}")
    if successes == 0:
        return {
            "market": "cn", "dataset": "events", "provider": "akshare_cninfo_notices",
            "status": "fetch_failed", "reason": "rolling_window_failed:" + ",".join(failures),
        }
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    batch = _persist(service, "akshare_cninfo_notices", "events", None, payload)
    return {
        "market": "cn", "dataset": "events", "provider": "akshare_cninfo_notices",
        # The endpoint is useful evidence but cannot prove complete historical
        # exchange coverage, so it remains partial even when rows are present.
        "status": "partial", "rows_or_bytes": len(rows), "payload_hash": batch.payload_hash,
        "reason": "rolling_public_window_not_complete" + (":" + ",".join(failures) if failures else ""),
    }


def _collect_sec_company_records(service, tickers: dict, symbols: list[str]) -> list[dict]:
    """Fetch free SEC filing indexes and XBRL facts for the configured US set.

    These payloads preserve SEC acceptance/disclosure timestamps for a later
    normalizer.  They are *not* promoted to formal PIT data merely because the
    endpoints are public.
    """
    import requests

    by_ticker = {
        str(item.get("ticker", "")).upper(): int(item["cik_str"])
        for item in tickers.values()
        if item.get("ticker") and item.get("cik_str")
    }
    headers = {"User-Agent": "investment-research research@example.invalid"}
    results: list[dict] = []
    for symbol in symbols:
        cik = by_ticker.get(symbol)
        if cik is None:
            results.append({"market": "us", "dataset": "filings", "symbol": symbol, "provider": "sec_edgar", "status": "partial", "reason": "ticker_missing_from_sec_master"})
            continue
        cik_text = f"CIK{cik:010d}"
        for dataset, url in (
            ("filings", f"https://data.sec.gov/submissions/{cik_text}.json"),
            ("companyfacts", f"https://data.sec.gov/api/xbrl/companyfacts/{cik_text}.json"),
        ):
            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                _persist(service, "sec_edgar", dataset, symbol, response.content)
                results.append({"market": "us", "dataset": dataset, "symbol": symbol, "provider": "sec_edgar", "status": "backfilled", "rows_or_bytes": len(response.content), "cik": str(cik)})
            except Exception as exc:
                status = "unsupported" if getattr(getattr(exc, "response", None), "status_code", None) == 404 else "fetch_failed"
                results.append({"market": "us", "dataset": dataset, "symbol": symbol, "provider": "sec_edgar", "status": status, "cik": str(cik), "reason": f"{type(exc).__name__}:{exc}"})
    return results


def _collect_edinet_recent(service, market: str) -> dict:
    """Probe recent business days, avoiding an assumed 'today' availability."""
    import requests

    headers = {"User-Agent": "FreeResearch/1.0"}
    errors: list[str] = []
    today = datetime.now(timezone.utc).date()
    for offset in range(1, 8):
        candidate = today - timedelta(days=offset)
        url = f"https://disclosure2dl.edinet-fsa.go.jp/api/v2/documents.json?date={candidate.isoformat()}&type=2"
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            _persist(service, "edinet", "events", None, response.content)
            return {"market": market, "dataset": "events", "provider": "edinet", "status": "backfilled", "source_date": candidate.isoformat(), "rows_or_bytes": len(response.content)}
        except Exception as exc:
            errors.append(f"{candidate.isoformat()}:{type(exc).__name__}")
    return {"market": market, "dataset": "events", "provider": "edinet", "status": "fetch_failed", "reason": "recent_dates_unavailable:" + ",".join(errors)}


def _collect_fred_macro(service) -> list[dict]:
    """Persist a small, documented public macro set without an API key.

    FRED returns a ZIP when multiple series are requested.  Keeping that
    original bundle is deliberate: extraction/normalization happens later and
    can be replayed against exactly the fetched source bytes.
    """
    import requests

    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + ",".join(FRED_SERIES)
        response = requests.get(
            url,
            headers={"User-Agent": "FreeResearch/1.0"}, timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        # Some local Python TLS/proxy stacks time out against the same public
        # endpoint while libcurl succeeds.  Preserve that degradation in the
        # ledger; the provider and payload remain exactly the same.
        try:
            from curl_cffi import requests as curl_requests
            response = curl_requests.get(url, timeout=20, impersonate="chrome")
            response.raise_for_status()
            transport = "curl_cffi_fallback"
        except Exception as fallback_exc:
            return [{"market": "us", "dataset": "macro_series_bundle", "symbol": "+".join(FRED_SERIES), "provider": "fred_public_csv", "status": "fetch_failed", "reason": f"primary={type(exc).__name__}:{exc};fallback={type(fallback_exc).__name__}:{fallback_exc}"}]
    else:
        transport = "requests"
    _persist(service, "fred_public_csv", "macro_series_bundle", "+".join(FRED_SERIES), response.content)
    return [{"market": "us", "dataset": "macro_series_bundle", "symbol": "+".join(FRED_SERIES), "provider": "fred_public_csv", "status": "backfilled", "rows_or_bytes": len(response.content), "content_encoding": "zip", "transport": transport}]


def _persist(
    service, provider: str, dataset: str, symbol: str | None, payload: bytes,
    *, coverage_start: date | None = None, coverage_end: date | None = None,
):
    now = datetime.now(timezone.utc)
    return service.persist(
        provider=provider, request_id=f"free-{provider}-{dataset}-{symbol or 'all'}-{uuid4()}",
        dataset=dataset, payload=payload, schema_version="free-research-v1",
        symbol=symbol, available_at=now, received_at=now, source_time=None,
        market_session="research_backfill", data_tier=DataTier.RESEARCH_PIT,
        coverage_start=None if coverage_start is None else datetime.combine(coverage_start, datetime.min.time(), timezone.utc),
        coverage_end=None if coverage_end is None else datetime.combine(coverage_end, datetime.max.time(), timezone.utc),
    )


def _symbols_by_market(path: Path | None, limit: int | None, *, discover_cn: bool = False) -> dict[str, list[str]]:
    if limit is not None and limit <= 0:
        raise ValueError("--max-symbols-per-market must be positive")
    values = {market: list(symbols) for market, symbols in DEFAULT_SYMBOLS.items()}
    if path is not None:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("symbols file must map market codes to symbol lists")
        for market in values:
            supplied = payload.get(market, values[market])
            if not isinstance(supplied, list) or not all(isinstance(item, str) and item for item in supplied):
                raise ValueError(f"symbols file has invalid {market} universe")
            values[market] = list(dict.fromkeys(supplied))
    elif discover_cn:
        try:
            values["cn"] = AkshareDailyResearchProvider().enumerate_symbols()
        except Exception:
            try:
                with BaostockDailyResearchProvider() as provider:
                    values["cn"] = provider.enumerate_symbols(as_of=date.today())
            except Exception:
                # The explicit fallback list keeps a zero-budget demo runnable;
                # the coverage ledger still reveals that discovery was partial.
                values["cn"] = list(DEFAULT_SYMBOLS["cn"])
        values["cn"] = sorted(set(values["cn"]) | set(ETF_RESEARCH_SYMBOLS))
    return {market: symbols[:limit] if limit else symbols for market, symbols in values.items()}


if __name__ == "__main__":
    raise SystemExit(main())
