#!/usr/bin/env python3
"""Backfill immutable 1/5/20-day outcomes for CN research shadow sessions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import UUID

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore
from investment_research.service.research_shadow import FileResearchShadowStore, ResearchShadowController
from investment_research.training.models import PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill CN research shadow outcomes")
    parser.add_argument("--session-id", type=UUID, required=True)
    parser.add_argument("--standard-manifest", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--shadow-directory", type=Path, default=PROJECT / "artifacts" / "research_shadow")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = FileResearchShadowStore(args.shadow_directory)
    session = store.get_session(args.session_id)
    if session is None:
        raise SystemExit("research shadow session not found")
    manifest = json.loads(args.standard_manifest.read_text(encoding="utf-8"))
    if manifest.get("data_tier") != "research_pit" or manifest.get("symbol") != session.symbol:
        raise SystemExit("standard manifest does not match the research session")
    parquet = PITParquetStore(LocalObjectStore(args.object_store))
    rows = [
        row
        for partition in manifest.get("partitions", [])
        for row in parquet.read_partition(partition["parquet_ref"])
    ]
    bars = sorted(
        (PreparedPriceBar.model_validate(row) for row in rows if row.get("symbol") == session.symbol),
        key=lambda item: item.trade_date,
    )
    future = [item for item in bars if item.trade_date > session.trade_date and item.is_tradeable]
    if not future:
        print("no effective trading-day outcome is due")
        return 0
    controller = ResearchShadowController(store)
    existing = {item.horizon_sessions for item in store.list_outcomes(session.id)}
    for horizon in (1, 5, 20, 60):
        if horizon in existing or len(future) < horizon:
            continue
        window = future[:horizon]
        outcome = controller.backfill_prices(
            session=session, horizon_sessions=horizon,
            filled_at=datetime.now(timezone.utc),
            entry_price=window[0].open_normalized or window[0].close_normalized,
            closes=[item.close_normalized for item in window],
            lows=[item.low_normalized or item.close_normalized for item in window],
            drawdown_entry_price=window[0].open_native or window[0].close_native,
            drawdown_lows=[item.low_native or item.close_native for item in window],
            suspended_during_window=any(item.is_suspended for item in window),
            limit_event_during_window=any(item.is_limit_up or item.is_limit_down for item in window),
        )
        print(outcome.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
