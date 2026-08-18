#!/usr/bin/env python3
"""Backfill detailed public CN corporate actions for the target equities.

This is a research-only supplement.  The source exposes historical dividend
and rights-issue details; each symbol is persisted independently so an
interrupted run can resume without discarding completed downloads.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


ETF_SYMBOLS = {"510050", "510300", "510500", "159915", "512100"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill detailed CN corporate actions")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_corporate_actions_detailed")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    options.output_root.mkdir(parents=True, exist_ok=True)
    target = json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text(encoding="utf-8"))
    symbols = [str(item).zfill(6) for item in target["cn"] if str(item).zfill(6) not in ETF_SYMBOLS]
    if options.max_symbols is not None:
        symbols = symbols[: options.max_symbols]
    progress_path = options.output_root / "progress.json"
    progress = _read_json(progress_path) if progress_path.exists() and not options.no_resume else {
        "schema_version": "cn-corporate-actions-detailed-progress-v1",
        "symbols": {},
    }
    progress.setdefault("symbols", {})
    pending = [s for s in symbols if progress["symbols"].get(s, {}).get("status") != "complete"]
    print(f"target_equities={len(symbols)} pending={len(pending)}", flush=True)

    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(options.workers, 8))) as pool:
        futures = {pool.submit(_fetch_symbol, symbol): symbol for symbol in pending}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                fetched[symbol] = future.result()
            except Exception as exc:
                fetched[symbol] = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
            print(f"fetched {len(fetched)}/{len(pending)} {symbol} {fetched[symbol].get('status')}", flush=True)

    uow = SQLiteUnitOfWork(options.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(options.object_store))
    try:
        for symbol in sorted(fetched):
            result = fetched[symbol]
            if result.get("status") != "complete":
                progress["symbols"][symbol] = result
                _write_json(progress_path, progress)
                continue
            now = datetime.now(timezone.utc)
            payload = json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode()
            batch = service.persist(
                provider="akshare_cn_corporate_actions_detailed",
                request_id=f"cn-corporate-actions-detailed-{symbol}-{uuid4()}",
                dataset="cn_corporate_actions_detailed",
                payload=payload,
                schema_version="cn-corporate-actions-detailed-v1",
                symbol=symbol,
                available_at=now,
                received_at=now,
                market_session="research_backfill",
                data_tier=DataTier.RESEARCH_PIT,
            )
            progress["symbols"][symbol] = {
                "status": "complete",
                "row_count": len(result["rows"]),
                "dividend_rows": result["dividend_rows"],
                "rights_issue_rows": result["rights_issue_rows"],
                "payload_hash": batch.payload_hash,
                "raw_batch_id": str(batch.id),
            }
            _write_json(progress_path, progress)
    finally:
        uow.close()

    completed = [v for v in progress["symbols"].values() if v.get("status") == "complete"]
    failures = {k: v for k, v in progress["symbols"].items() if v.get("status") != "complete"}
    report = {
        "schema_version": "cn-corporate-actions-detailed-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(failures),
        "row_count": sum(int(v.get("row_count", 0)) for v in completed),
        "dividend_row_count": sum(int(v.get("dividend_rows", 0)) for v in completed),
        "rights_issue_row_count": sum(int(v.get("rights_issue_rows", 0)) for v in completed),
        "failures": failures,
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(options.output_root / "latest.json", report)
    print(options.output_root / "latest.json")
    return 0 if report["status"] == "complete" else 1


def _fetch_symbol(symbol: str) -> dict[str, Any]:
    import akshare as ak

    dividend = _frame_rows(ak.stock_history_dividend_detail(symbol=symbol, indicator="分红"), symbol, "dividend")
    rights = _frame_rows(ak.stock_history_dividend_detail(symbol=symbol, indicator="配股"), symbol, "rights_issue")
    return {
        "status": "complete",
        "rows": [*dividend, *rights],
        "dividend_rows": len(dividend),
        "rights_issue_rows": len(rights),
    }


def _frame_rows(frame: Any, symbol: str, action_type: str) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    collected = datetime.now(timezone.utc).isoformat()
    for raw in frame.to_dict(orient="records"):
        row = {str(k): _json_value(v) for k, v in raw.items()}
        announcement = row.get("公告日期")
        ex_date = row.get("除权除息日") or row.get("除权日")
        row.update({
            "symbol": symbol,
            "action_type": action_type,
            "announced_at": _date_text(announcement),
            "effective_at": _date_text(ex_date),
            "source_collected_at": collected,
            "available_at": collected,
            "revision": 1,
            "event_source": "akshare_public_corporate_action_detail",
        })
        rows.append(row)
    return rows


def _date_text(value: Any) -> str | None:
    if value in (None, "", "NaT", "nan"):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return None if text in {"NaT", "nan", "None"} else text[:10]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        if hasattr(value, "item"):
            return _json_value(value.item())
    except Exception:
        pass
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
