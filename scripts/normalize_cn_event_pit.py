#!/usr/bin/env python3
"""Materialize row-level PIT metadata for locally downloaded CN events."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore


def main() -> int:
    database = PROJECT / "var/cn-research/catalog.db"
    raw_store = LocalObjectStore(PROJECT / "var/cn-research/raw")
    output_root = PROJECT / "artifacts/cn_event_backfill"
    output_root.mkdir(parents=True, exist_ok=True)
    uow = SQLiteUnitOfWork(database)
    rows_out: list[dict] = []
    batch_count = 0
    symbols: set[str] = set()
    try:
        batches = uow.trusted_market.raw_batches(dataset="events", data_tier="research_pit")
        for batch in sorted(batches, key=lambda item: (item.fetched_at, item.payload_hash)):
            if batch.provider not in {"eastmoney_cn_announcements", "eastmoney_cn_news"}:
                continue
            payload = raw_store.get(batch.payload_ref.removeprefix("file-object://"))
            if __import__("hashlib").sha256(payload).hexdigest() != batch.payload_hash:
                raise ValueError(f"raw_payload_hash_mismatch:{batch.id}")
            raw_rows = json.loads(payload)
            batch_count += 1
            available_at = _iso(batch.available_at)
            received_at = _iso(getattr(batch, "received_at", None))
            persisted_at = _iso(getattr(batch, "persisted_at", None))
            for item in raw_rows if isinstance(raw_rows, list) else []:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("代码") or item.get("symbol") or "").zfill(6)
                if not symbol or symbol == "000000":
                    continue
                normalized = dict(item)
                normalized.update({
                    "symbol": symbol,
                    "available_at": item.get("available_at") or available_at,
                    "received_at": item.get("received_at") or received_at,
                    "persisted_at": item.get("persisted_at") or persisted_at,
                    "revision": int(item.get("revision") or 1),
                    "raw_batch_id": str(batch.id),
                    "raw_payload_hash": batch.payload_hash,
                    "raw_payload_ref": batch.payload_ref,
                    "pit_normalized_at": datetime.now(timezone.utc).isoformat(),
                })
                rows_out.append(normalized)
                symbols.add(symbol)
    finally:
        uow.close()

    normalized_path = output_root / "events_pit_normalized.jsonl"
    with normalized_path.open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    report = {
        "schema_version": "cn-events-pit-normalized-v1",
        "data_tier": "research_pit",
        "research_only": True,
        "batch_count": batch_count,
        "row_count": len(rows_out),
        "symbol_count": len(symbols),
        "symbols": sorted(symbols),
        "available_at_present": sum(bool(row.get("available_at")) for row in rows_out),
        "revision_present": sum(row.get("revision") is not None for row in rows_out),
        "normalized_ref": "artifacts/cn_event_backfill/events_pit_normalized.jsonl",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
    }
    (output_root / "pit_normalized.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
