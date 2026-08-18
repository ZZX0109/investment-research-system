#!/usr/bin/env python3
"""Persist CN auxiliary research inputs beside the local raw market store.

This collector fills the data that cannot be obtained from the daily-bar
payloads alone: exchange-wide margin financing, public macro series, and a
derived cross-sectional breadth table.  All provider bytes are kept in the
append-only raw catalog before a small normalized artifact is written.  The
outputs are research-only and retain collection/PIT metadata; they are not a
claim of licensed or formally point-in-time data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


TARGET_PATH = PROJECT / "config/cn_research_target_167_symbols.json"
OUTPUT_ROOT = PROJECT / "artifacts/cn_research_auxiliary"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect CN research auxiliary inputs")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    options.output_root.mkdir(parents=True, exist_ok=True)
    target = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
    symbols = [str(value).zfill(6) for value in target["cn"]]
    equity_symbols = [symbol for symbol in symbols if symbol not in {"510050", "510300", "510500", "159915", "512100"}]
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(options.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(options.object_store))
    report: dict[str, Any] = {
        "schema_version": "cn-research-auxiliary-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "started_at": now.isoformat(),
        "target_symbol_count": len(symbols),
        "equity_symbol_count": len(equity_symbols),
        "datasets": {},
        "failures": [],
    }
    try:
        report["datasets"]["margin_financing"] = _collect_margin(service, options.output_root)
        report["datasets"]["macro"] = _collect_macro(service, options.output_root)
        report["datasets"]["market_breadth"] = _build_breadth(
            service, options.output_root, equity_symbols, options.database
        )
        report["datasets"]["industry_mapping"] = _build_industry_mapping(
            options.database, options.object_store, options.output_root, symbols
        )
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}:{exc}")
    finally:
        uow.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["status"] = "complete" if not report["failures"] else "partial"
    (options.output_root / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(options.output_root / "latest.json")
    return 0 if report["status"] == "complete" else 1


def _collect_margin(service, output_root: Path) -> dict[str, Any]:
    import akshare as ak

    frames: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for key, function_name in (
        ("sh", "macro_china_market_margin_sh"),
        ("sz", "macro_china_market_margin_sz"),
    ):
        try:
            frame = getattr(ak, function_name)()
            if frame is None or frame.empty:
                raise RuntimeError("empty_frame")
            frames[key] = frame
        except Exception as exc:
            failures[key] = f"{type(exc).__name__}:{exc}"

    normalized: dict[str, dict[str, Any]] = {}
    raw_refs: list[dict[str, Any]] = []
    for market, frame in frames.items():
        raw = frame.to_json(orient="records", force_ascii=False, date_format="iso").encode()
        dataset = f"cn_margin_financing_{market}"
        batch = _persist(service, dataset, market, raw)
        raw_refs.append({"market": market, "dataset": dataset, "rows": len(frame), "payload_hash": batch.payload_hash})
        for item in _frame_records(frame):
            trade_date = _first_value(item, ("日期", "date", "trade_date"))
            balance = _number(_first_value(item, ("融资余额", "financing_balance")))
            if not trade_date or balance is None:
                continue
            normalized.setdefault(str(trade_date)[:10], {})[f"{market}_financing_balance"] = balance

    rows: list[dict[str, Any]] = []
    for trade_date in sorted(normalized):
        item = normalized[trade_date]
        sh = item.get("sh_financing_balance")
        sz = item.get("sz_financing_balance")
        rows.append({
            "trade_date": trade_date,
            "sh_financing_balance": sh,
            "sz_financing_balance": sz,
            "financing_balance": None if sh is None and sz is None else (sh or 0.0) + (sz or 0.0),
            "source_time": f"{trade_date}T23:59:59+08:00",
            "available_at": datetime.now(timezone.utc).isoformat(),
            "revision": 1,
            "provider": "akshare_jin10_public",
            "data_tier": DataTier.RESEARCH_PIT.value,
        })
    _write_json(output_root / "margin_financing.json", rows)
    return {
        "status": "complete" if rows and not failures else "partial" if rows else "failed",
        "row_count": len(rows),
        "coverage_start": rows[0]["trade_date"] if rows else None,
        "coverage_end": rows[-1]["trade_date"] if rows else None,
        "raw_batches": raw_refs,
        "failures": failures,
        "normalized_ref": "margin_financing.json",
    }


def _collect_macro(service, output_root: Path) -> dict[str, Any]:
    import akshare as ak

    functions = {
        "cpi_monthly": "macro_china_cpi_monthly",
        "ppi_monthly": "macro_china_ppi",
        "pmi_monthly": "macro_china_pmi",
        "lpr": "macro_china_lpr",
        "shibor": "macro_china_shibor_all",
        "m2": "macro_china_money_supply",
        "social_financing": "macro_china_shrzgm",
        "fx_rmb": "macro_china_rmb",
    }
    datasets: dict[str, Any] = {}
    for key, function_name in functions.items():
        try:
            frame = getattr(ak, function_name)()
            if frame is None or frame.empty:
                raise RuntimeError("empty_frame")
            raw = frame.to_json(orient="records", force_ascii=False, date_format="iso").encode()
            batch = _persist(service, f"cn_macro_{key}", key, raw)
            rows = _frame_records(frame)
            path = output_root / f"macro_{key}.json"
            _write_json(path, rows)
            datasets[key] = {
                "status": "complete",
                "row_count": len(rows),
                "columns": [str(value) for value in frame.columns],
                "payload_hash": batch.payload_hash,
                "normalized_ref": path.name,
            }
        except Exception as exc:
            datasets[key] = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
    complete = sum(item.get("status") == "complete" for item in datasets.values())
    return {"status": "complete" if complete == len(functions) else "partial", "datasets": datasets}


def _build_breadth(
    service, output_root: Path, equity_symbols: list[str], database: Path = PROJECT / "var/cn-research/catalog.db"
) -> dict[str, Any]:
    import pandas as pd
    import pyarrow.dataset as ds

    root = PROJECT / "var/cn-research/parquet/pit/cn/standard_daily_bars_research/free-research-standard-v1"
    if not root.exists():
        raise RuntimeError("standard_daily_bars_partition_root_missing")
    memberships = _load_historical_memberships(database, set(equity_symbols))
    if not memberships:
        raise RuntimeError("historical_universe_membership_missing_for_breadth")
    table = ds.dataset(root, format="parquet").to_table(
        columns=["symbol", "trade_date", "close_normalized", "amount", "is_limit_up", "is_limit_down"],
        filter=ds.field("symbol").isin(equity_symbols),
    )
    frame = table.to_pandas()
    if frame.empty:
        raise RuntimeError("no_equity_bars_for_breadth")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
    frame["previous_close"] = frame.groupby("symbol")["close_normalized"].shift(1)
    frame["daily_return"] = frame["close_normalized"] / frame["previous_close"] - 1.0
    frame = frame.loc[frame["daily_return"].notna()].copy()
    grouped = frame.groupby("trade_date", sort=True)
    rows: list[dict[str, Any]] = []
    for trade_date, group in grouped:
        members = {
            symbol
            for symbol, effective_from, effective_to, available_at in memberships
            if effective_from <= trade_date
            and (effective_to is None or trade_date < effective_to)
            and (available_at is None or available_at.date() <= trade_date)
        }
        if not members:
            continue
        group = group.loc[group["symbol"].isin(members)]
        returns = group["daily_return"].dropna()
        if returns.empty:
            continue
        rows.append({
            "trade_date": trade_date.isoformat(),
            "equity_count": int(len(group)),
            "return_observation_count": int(len(returns)),
            "market_advance_ratio_1d": float((returns > 0).mean()),
            "market_median_return_1d": float(returns.median()),
            "market_return_mean_1d": float(returns.mean()),
            "market_return_volatility_1d": float(returns.std(ddof=0)),
            "market_amount_total": float(group["amount"].fillna(0).sum()),
            "market_limit_up_ratio_1d": float(group["is_limit_up"].fillna(False).mean()),
            "market_limit_down_ratio_1d": float(group["is_limit_down"].fillna(False).mean()),
            "market_cross_section_coverage": float(len(returns) / max(1, len(group))),
            "source_time": f"{trade_date.isoformat()}T23:59:59+08:00",
            "available_at": datetime.now(timezone.utc).isoformat(),
            "revision": 1,
            "provider": "derived_from_local_standard_daily_bars",
            "data_tier": DataTier.RESEARCH_PIT.value,
        })
    by_date = pd.DataFrame(rows)
    if by_date.empty:
        raise RuntimeError("no_breadth_rows")
    by_date["market_breadth_5d"] = by_date["market_advance_ratio_1d"].rolling(5, min_periods=5).mean()
    rows = by_date.where(pd.notna(by_date), None).to_dict(orient="records")
    rows = [{key: (value.item() if hasattr(value, "item") else value) for key, value in row.items()} for row in rows]
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    batch = _persist(service, "cn_market_breadth_derived", "CN-EQUITY-162", raw)
    _write_json(output_root / "market_breadth.json", rows)
    return {
        "status": "degraded",
        "quality_status": "degraded",
        "row_count": len(rows),
        "coverage_start": rows[0]["trade_date"],
        "coverage_end": rows[-1]["trade_date"],
        "payload_hash": batch.payload_hash,
        "normalized_ref": "market_breadth.json",
        "membership_dataset": "cn_historical_universe_memberships",
        "membership_policy": "effective_from_listing_date_assumption",
        "missing_reason_code": "historical_membership_assumption",
    }


def _load_historical_memberships(database: Path, symbols: set[str]) -> list[tuple[str, Any, Any, Any]]:
    """Load PIT universe memberships; never infer them from today's symbols."""
    if not database.is_file():
        return []
    con = sqlite3.connect(database)
    try:
        rows = con.execute(
            """SELECT symbol,effective_from,effective_to,available_at
               FROM historical_universe_memberships
               WHERE market='cn'"""
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    from datetime import date, datetime

    output: list[tuple[str, Any, Any, Any]] = []
    for symbol, effective_from, effective_to, available_at in rows:
        symbol = str(symbol).zfill(6)
        if symbol not in symbols:
            continue
        try:
            start = date.fromisoformat(str(effective_from)[:10])
            end = date.fromisoformat(str(effective_to)[:10]) if effective_to else None
            available = datetime.fromisoformat(str(available_at).replace("Z", "+00:00")) if available_at else None
        except ValueError:
            continue
        output.append((symbol, start, end, available))
    return output


def _build_industry_mapping(database: Path, object_store: Path, output_root: Path, symbols: list[str]) -> dict[str, Any]:
    store = LocalObjectStore(object_store)
    con = sqlite3.connect(database)
    latest: dict[str, tuple[str, str]] = {}
    query = """select json_extract(payload_json,'$.symbol'), json_extract(payload_json,'$.payload_ref'), fetched_at
               from raw_data_batches where dataset='cn_security_master_research'
               and json_extract(payload_json,'$.symbol') is not null order by fetched_at"""
    for symbol, ref, _fetched_at in con.execute(query):
        if str(symbol) not in symbols or not ref or not str(ref).startswith("file-object://"):
            continue
        try:
            rows = json.loads(store.get(str(ref).removeprefix("file-object://")))
            if rows and rows[0].get("industry"):
                latest[str(symbol)] = (str(rows[0]["industry"]), str(rows[0].get("industryClassification") or ""))
        except Exception:
            continue
    con.close()
    mapping = {symbol: value[0] for symbol, value in sorted(latest.items())}
    missing = sorted(set(symbols) - set(mapping))
    payload = {
        "schema_version": "cn-industry-map-research-v2",
        "source": "local_cn_security_master_research_raw",
        "classification": "证监会行业分类",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(symbols),
        "mapped": len(mapping),
        "missing": missing,
        "symbols": mapping,
    }
    _write_json(PROJECT / "config/cn_industry_map.json", payload)
    _write_json(output_root / "industry_mapping.json", payload)
    return {"status": "complete" if not missing or all(item.startswith(("1", "5")) for item in missing) else "partial", "universe_size": len(symbols), "mapped": len(mapping), "missing": missing, "normalized_ref": "industry_mapping.json"}


def _persist(service, dataset: str, symbol: str, payload: bytes):
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return service.persist(
        provider="akshare" if not dataset.endswith("derived") else "derived_from_local_standard_daily_bars",
        request_id=f"cn-aux-{dataset}-{symbol}-{digest}",
        dataset=dataset,
        payload=payload,
        schema_version="cn-research-auxiliary-v1",
        symbol=symbol,
        available_at=now,
        received_at=now,
        market_session="research_backfill",
        data_tier=DataTier.RESEARCH_PIT,
    )


def _frame_records(frame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", force_ascii=False, date_format="iso"))


def _first_value(item: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


def _number(value: Any) -> float | None:
    if value in (None, "", "-", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
