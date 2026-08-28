#!/usr/bin/env python3
"""Download public CN listing, delisting, name and industry history tables."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

ETF_SYMBOLS = {"159915", "510050", "510300", "510500", "512100"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument(
        "--all-current-universe",
        action="store_true",
        help="Use artifacts/cn_security_master_universe/security_master_current.json instead of the frozen research target.",
    )
    parser.add_argument(
        "--skip-industry-history",
        action="store_true",
        help="Persist broad listing/delisting/name tables without one-request-per-symbol industry calls.",
    )
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_security_lifecycle_akshare")
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Discard the per-symbol industry-history checkpoint and fetch every symbol again.",
    )
    parser.add_argument(
        "--bse-code-mapping", type=Path,
        default=PROJECT / "artifacts/cn_bse_code_mapping/mapping.json",
        help="Official BSE 920-to-legacy mapping downloaded by fetch_cn_bse_code_mapping.py.",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.all_current_universe:
        universe_path = PROJECT / "artifacts/cn_security_master_universe/security_master_current.json"
        target = json.loads(universe_path.read_text(encoding="utf-8"))
    else:
        target = json.loads(args.target_symbols.read_text(encoding="utf-8"))
    if isinstance(target, list):
        values = [item.get("code") if isinstance(item, dict) else item for item in target]
    else:
        values = target.get("cn", []) if isinstance(target, dict) else []
    symbols = sorted({str(item).rsplit(".", 1)[-1].zfill(6) for item in values if str(item).rsplit(".", 1)[-1].zfill(6) not in ETF_SYMBOLS})
    import akshare as ak

    progress_path = args.output_root / "progress.json"
    progress = _read_json(progress_path) if progress_path.exists() and not args.no_resume else {
        "schema_version": "cn-security-lifecycle-progress-v1",
        "symbols": {},
    }
    progress.setdefault("symbols", {})
    pending_symbols = [
        symbol
        for symbol in symbols
        if not (
            isinstance(progress["symbols"].get(symbol), dict)
            and progress["symbols"][symbol].get("status") == "complete"
        )
    ]

    one_shot = {}
    failures = {}
    for name in ("stock_info_sh_delist", "stock_info_sz_delist", "stock_info_sh_name_code", "stock_info_sz_name_code", "stock_info_sz_change_name", "stock_report_disclosure"):
        try:
            frame = getattr(ak, name)()
            one_shot[name] = _records(frame)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}:{exc}"

    history: dict[str, list[dict]] = {
        symbol: list(value.get("rows", []))
        for symbol, value in progress["symbols"].items()
        if isinstance(value, dict)
        and value.get("status") == "complete"
        and isinstance(value.get("rows"), list)
    }
    if not args.skip_industry_history:
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            futures = {pool.submit(_industry_history, ak, symbol): symbol for symbol in pending_symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    rows = future.result()
                    history[symbol] = rows
                    progress["symbols"][symbol] = {
                        "status": "complete",
                        "row_count": len(rows),
                        "rows": rows,
                    }
                except Exception as exc:
                    history[symbol] = []
                    reason = f"{type(exc).__name__}:{exc}"
                    failures[f"industry:{symbol}"] = reason
                    progress["symbols"][symbol] = {"status": "failed", "reason": reason}
                _write(progress_path, progress)
                print(f"industry {len(history)}/{len(symbols)} {symbol}", flush=True)
    else:
        for symbol in pending_symbols:
            history[symbol] = []
            progress["symbols"][symbol] = {"status": "complete", "row_count": 0, "rows": []}
        _write(progress_path, progress)

    uow = SQLiteUnitOfWork(args.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
    now = datetime.now(timezone.utc)
    try:
        for dataset, rows in one_shot.items():
            _persist(service, dataset, "CN", rows, now)
        for symbol, rows in history.items():
            _persist(service, "cn_security_industry_history_akshare", symbol, rows, now)
    finally:
        uow.close()

    bse_mapping = _load_bse_mapping(args.bse_code_mapping)
    normalized = _normalize(symbols, one_shot, history, now, bse_mapping)
    _write(args.output_root / "security_lifecycle.json", normalized)
    listing_coverage = sum(bool(row.get("listed_on")) for row in normalized) / len(normalized) if normalized else 0.0
    st_status_coverage = sum(bool(row.get("st_status")) for row in normalized) / len(normalized) if normalized else 0.0
    listing_status_coverage = sum(bool(row.get("listing_status")) for row in normalized) / len(normalized) if normalized else 0.0
    publication_coverage = 0.0
    report = {
        "schema_version": "cn-security-lifecycle-akshare-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "target_equity_count": len(symbols),
        "industry_history_symbol_count": sum(bool(rows) for rows in history.values()),
        "bse_code_mapping_count": len(bse_mapping),
        "listing_date_coverage": sum(bool(row.get("listed_on")) for row in normalized) / len(normalized) if normalized else 0.0,
        "listing_status_coverage": listing_status_coverage,
        "delisting_date_coverage": sum(bool(row.get("delisted_on")) for row in normalized) / len(normalized) if normalized else 0.0,
        "industry_history_coverage": sum(bool(row.get("industry_history")) for row in normalized) / len(normalized) if normalized else 0.0,
        "st_status_coverage": st_status_coverage,
        "code_change_coverage": sum(bool(row.get("code_changes")) for row in normalized) / len(normalized) if normalized else 0.0,
        "code_change_record_coverage": (
            sum(bool(row.get("code_changes")) for row in normalized)
            / sum(bool(row.get("code_changes")) for row in normalized)
            if any(row.get("code_changes") for row in normalized)
            else 0.0
        ),
        "published_at_coverage": publication_coverage,
        "available_at_coverage": 1.0 if normalized else 0.0,
        "failures": failures,
        "missing_reason": "public tables provide effective dates but not a complete historical ST/availability publication contract",
        "missing_reason_code": "historical_lifecycle_partial",
        # A clean HTTP run is not the same as a complete lifecycle contract:
        # ST, publication time and historical effective intervals may still be
        # absent.  Keep the artifact explicitly partial until field-level
        # coverage gates prove otherwise.
        "status": "complete" if (
            not failures and listing_coverage >= 0.98
            and st_status_coverage >= 0.98
            and listing_status_coverage >= 0.98
            and publication_coverage >= 0.98
        ) else "partial",
        "generated_at": now.isoformat(),
    }
    _write(progress_path, progress)
    _write(args.output_root / "latest.json", report)
    print(json.dumps({k: report[k] for k in ("status", "target_equity_count", "industry_history_symbol_count", "listing_date_coverage", "listing_status_coverage", "delisting_date_coverage", "industry_history_coverage", "st_status_coverage", "code_change_coverage")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _industry_history(ak, symbol: str) -> list[dict]:
    frame = ak.stock_industry_change_cninfo(symbol=symbol, start_date="19900101", end_date=datetime.now().strftime("%Y%m%d"))
    return _records(frame)


def _records(frame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", force_ascii=False, date_format="iso"))


def _persist(service, dataset: str, symbol: str, rows: list[dict], now: datetime) -> None:
    service.persist(
        provider="akshare_cn_lifecycle",
        request_id=f"cn-lifecycle-{dataset}-{symbol}-{uuid4()}",
        dataset=dataset,
        payload=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(),
        schema_version="cn-security-lifecycle-akshare-v1",
        symbol=symbol,
        available_at=now,
        received_at=now,
        market_session="research_backfill",
        data_tier=DataTier.RESEARCH_PIT,
    )


def _load_bse_mapping(path: Path) -> dict[str, dict]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return {
        str(row.get("new_code")).zfill(6): row
        for row in rows if isinstance(row, dict) and row.get("new_code") and row.get("old_code")
    }


def _normalize(
    symbols: list[str], tables: dict[str, list[dict]], history: dict[str, list[dict]],
    now: datetime, bse_mapping: dict[str, dict],
) -> list[dict]:
    listed: dict[str, dict] = {}
    for name in ("stock_info_sh_name_code", "stock_info_sz_name_code"):
        for row in tables.get(name, []):
            code = str(row.get("证券代码") or row.get("A股代码") or "").zfill(6)
            if code in symbols:
                listed[code] = row
    delisted: dict[str, dict] = {}
    for name in ("stock_info_sh_delist", "stock_info_sz_delist"):
        for row in tables.get(name, []):
            code = str(row.get("公司代码") or row.get("证券代码") or "").zfill(6)
            if code in symbols:
                delisted[code] = row
    names = {}
    for row in tables.get("stock_info_sz_change_name", []):
        code = str(row.get("证券代码") or "").zfill(6)
        if code in symbols:
            names.setdefault(code, []).append(row)
    output = []
    for symbol in symbols:
        base = listed.get(symbol, {})
        end = delisted.get(symbol, {})
        industry = history.get(symbol, [])
        bse = bse_mapping.get(symbol, {})
        code_changes = ([] if not bse else [{
            "旧代码": bse.get("old_code"), "新代码": symbol,
            "证券简称": bse.get("security_name"),
            "上市日期": bse.get("listed_on"),
            "source_url": bse.get("source_url"),
            "effective_date": "2025-10-09",
        }])
        listed_on_value = (
            str(base.get("上市日期") or base.get("A股上市日期") or "")[:10]
            or str(end.get("上市日期") or "")[:10]
            or bse.get("listed_on") or None
        )
        delisted_on_value = (
            str(end.get("终止上市日期") or end.get("暂停上市日期") or "")[:10] or None
        )
        security_name_value = (
            base.get("证券简称") or base.get("A股简称")
            or end.get("公司简称") or bse.get("security_name")
        )
        # Derive lifecycle status and ST flag from the already-fetched public
        # name_code tables.  The name column carries *ST / ST prefixes for risk-
        # warned securities, so we can label ST status without an extra network
        # request.  listing_status follows from the delisting-date presence.
        # Both stay None only when the underlying name_code row is missing.
        st_status_value: str | None
        if security_name_value and ("ST" in str(security_name_value) or "*ST" in str(security_name_value)):
            st_status_value = "st_risk_warning"
        elif security_name_value:
            st_status_value = "normal"
        else:
            st_status_value = None
        listing_status_value: str | None
        if delisted_on_value:
            listing_status_value = "delisted"
        elif listed_on_value:
            listing_status_value = "listed"
        else:
            listing_status_value = None
        output.append({
            "symbol": symbol,
            "listed_on": listed_on_value,
            "delisted_on": delisted_on_value,
            "security_name": security_name_value,
            "st_status": st_status_value,
            "listing_status": listing_status_value,
            "industry_current": base.get("所属行业"),
            "industry_history": industry,
            # A code migration is not a legal-name change. Keep both event
            # types available to the security-master builder.
            "name_changes": names.get(symbol, []),
            "code_changes": code_changes,
            "available_at": now.isoformat(),
            "published_at": None,
            "revision_id": None,
            "data_tier": DataTier.RESEARCH_PIT.value,
            "quality_status": "degraded",
            "missing_reason_code": "historical_lifecycle_partial",
        })
    return output


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"schema_version": "cn-security-lifecycle-progress-v1", "symbols": {}}
    return value if isinstance(value, dict) else {"schema_version": "cn-security-lifecycle-progress-v1", "symbols": {}}


if __name__ == "__main__":
    raise SystemExit(main())
