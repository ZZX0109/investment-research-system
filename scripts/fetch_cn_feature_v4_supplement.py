#!/usr/bin/env python3
"""Collect free Baostock metadata and PIT-shaped fundamentals for Feature V4.

The collector is deliberately research-only.  Every successful Baostock query
is persisted as an append-only raw payload with the query identity encoded in
the request id.  Publication dates remain row-level fields and are the only
dates the Feature V4 as-of join may use.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from time import sleep
from typing import Any, Callable
from uuid import uuid4


PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


FUNDAMENTAL_QUERIES = {
    "profit": "query_profit_data",
    "growth": "query_growth_data",
    "operation": "query_operation_data",
    "balance": "query_balance_data",
    "cash_flow": "query_cash_flow_data",
    "dupont": "query_dupont_data",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Baostock Feature V4 supplements")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--coverage-ledger", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_feature_v4_supplement/latest.json")
    parser.add_argument("--start-year", type=int, default=date.today().year - 7)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--resume", action="store_true", default=True)
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    symbols = _symbols(options.coverage_ledger)
    if options.max_symbols is not None:
        symbols = symbols[: options.max_symbols]
    if not symbols:
        raise SystemExit("no CN research symbols are available in the coverage ledger")

    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise SystemExit(f"baostock login failed:{login.error_code}:{login.error_msg}")
    uow = SQLiteUnitOfWork(options.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(options.object_store))
    report: dict[str, Any] = {
        "schema_version": "cn-feature-v4-supplement-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "provider": "baostock",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "target_symbol_count": len(symbols),
        "datasets": {},
        "symbols": {},
        "failures": [],
    }
    try:
        for index, symbol in enumerate(symbols, start=1):
            state: dict[str, Any] = {"status": "complete", "datasets": {}}
            report["symbols"][symbol] = state
            try:
                state["datasets"] = _collect_symbol(
                    bs, service, symbol,
                    start_year=options.start_year,
                    end_year=options.end_year,
                )
            except Exception as exc:
                state["status"] = "failed"
                report["failures"].append({
                    "symbol": symbol,
                    "reason": f"{type(exc).__name__}:{exc}",
                })

            if index % 10 == 0:
                print(f"feature-v4 supplement {index}/{len(symbols)}", flush=True)
            sleep(0.02)
    finally:
        uow.close()
        bs.logout()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["successful_symbol_count"] = sum(
        item.get("status") == "complete" for item in report["symbols"].values()
    )
    report["coverage_ratio"] = report["successful_symbol_count"] / max(1, len(symbols))
    report["datasets"] = _dataset_totals(report["symbols"])
    report["status"] = "complete" if not report["failures"] else "partial"
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(options.output.resolve())
    return 0 if report["status"] == "complete" else 1


def _collect_symbol(
    bs: Any,
    service: RawPayloadIngestionService,
    symbol: str,
    *,
    start_year: int,
    end_year: int,
) -> dict[str, int]:
    code = _code(symbol)
    basic_rows = _query_rows(bs.query_stock_basic(code=code))
    industry_rows = _query_rows(bs.query_stock_industry(code=code))
    master_rows = _merge_master(basic_rows, industry_rows)
    _persist_rows(service, "cn_security_master_research", symbol, "current", master_rows)

    adjust_rows = _query_rows(bs.query_adjust_factor(
        code=code,
        start_date=f"{start_year}-01-01",
        end_date=f"{end_year}-12-31",
    ))
    _persist_rows(
        service, "cn_adjustment_factors_research", symbol,
        f"{start_year}-{end_year}", adjust_rows,
    )

    dividend_rows: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        rows = _query_rows(bs.query_dividend_data(
            code=code, year=str(year), yearType="report",
        ))
        _persist_rows(service, "cn_corporate_actions_research", symbol, str(year), rows)
        dividend_rows.extend(rows)

    fundamental_count = 0
    if not symbol.startswith(("5", "1")):
        ipo_year = _ipo_year(master_rows) or start_year
        for year in range(max(start_year, ipo_year), end_year + 1):
            for quarter in range(1, 5):
                for family, method_name in FUNDAMENTAL_QUERIES.items():
                    method: Callable[..., Any] = getattr(bs, method_name)
                    rows = _query_rows(method(code=code, year=year, quarter=quarter))
                    _persist_rows(
                        service, "cn_fundamentals_research", symbol,
                        f"{family}-{year}q{quarter}",
                        [{**row, "feature_family": family} for row in rows],
                    )
                    fundamental_count += len(rows)
    return {
        "security_master": len(master_rows),
        "adjustment_factors": len(adjust_rows),
        "corporate_actions": len(dividend_rows),
        "fundamentals": fundamental_count,
    }


def _symbols(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = {
        str(item["symbol"])
        for item in payload.get("records", [])
        if item.get("market") == "cn"
        and item.get("dataset") in {"daily_bars_raw", "daily_bars_qfq"}
        and item.get("status") in {"backfilled", "complete", "partial"}
        and item.get("symbol")
    }
    return sorted(values)


def _query_rows(result: Any) -> list[dict[str, Any]]:
    if result.error_code != "0":
        raise RuntimeError(f"baostock query failed:{result.error_code}:{result.error_msg}")
    rows: list[dict[str, Any]] = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    return rows


def _merge_master(basic: list[dict[str, Any]], industry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = dict(basic[0]) if basic else {}
    if industry:
        base.update({
            "industry": industry[0].get("industry"),
            "industryClassification": industry[0].get("industryClassification"),
            "industryUpdateDate": industry[0].get("updateDate"),
        })
    return [base] if base else []


def _persist_rows(
    service: RawPayloadIngestionService,
    dataset: str,
    symbol: str,
    query_key: str,
    rows: list[dict[str, Any]],
) -> None:
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    now = datetime.now(timezone.utc)
    service.persist(
        provider="baostock",
        request_id=f"free-baostock-{dataset}-{symbol}-{query_key}-{uuid4()}",
        dataset=dataset,
        payload=payload,
        schema_version="cn-feature-v4-supplement-v1",
        symbol=symbol,
        available_at=now,
        received_at=now,
        source_time=None,
        market_session="research_backfill",
        data_tier=DataTier.RESEARCH_PIT,
    )


def _ipo_year(rows: list[dict[str, Any]]) -> int | None:
    try:
        return date.fromisoformat(str(rows[0].get("ipoDate"))).year
    except (IndexError, TypeError, ValueError):
        return None


def _code(symbol: str) -> str:
    return f"sh.{symbol}" if symbol.startswith(("5", "6", "9")) else f"sz.{symbol}"


def _dataset_totals(symbols: dict[str, dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for state in symbols.values():
        for name, count in state.get("datasets", {}).items():
            totals[name] = totals.get(name, 0) + int(count)
    return totals


if __name__ == "__main__":
    raise SystemExit(main())
