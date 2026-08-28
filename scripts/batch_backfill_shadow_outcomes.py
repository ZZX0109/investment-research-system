#!/usr/bin/env python3
"""Batch-backfill 1/5/20/60-day outcomes for CN research shadow sessions that have
real (non-empty) frozen predictions.

Sessions with real predictions live under runs/*/sessions/ (not sessions/).
This script scans those directories, finds each session's standard manifest,
reads future price bars from the parquet store, and computes outcomes for
every horizon that has enough future trade days.

Research-only: no active snapshot is created, no PIT assertion is made.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore
from investment_research.service.research_shadow import (
    FileResearchShadowStore,
    ResearchShadowController,
    ResearchShadowSession,
)
from investment_research.training.models import PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore


def _find_real_prediction_sessions(runs_root: Path) -> list[ResearchShadowSession]:
    """Scan runs/*/sessions/ for sessions with non-empty frozen_prediction."""
    sessions: list[ResearchShadowSession] = []
    for f in runs_root.rglob("*.json"):
        if "/sessions/" not in str(f):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pred = d.get("frozen_prediction", {})
        if not pred or not isinstance(pred, dict) or len(pred) == 0:
            continue
        try:
            session = ResearchShadowSession.model_validate(d)
            sessions.append(session)
        except Exception:
            continue
    return sessions


def _find_manifest(symbol: str, std_dir: Path) -> dict | None:
    """Find the standard manifest for a symbol."""
    for f in std_dir.glob(f"{symbol}-*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            if m.get("data_tier") == "research_pit":
                return m
        except (OSError, ValueError):
            continue
    return None


def _read_future_bars(manifest: dict, symbol: str, after_date: str,
                      parquet: PITParquetStore) -> list[PreparedPriceBar]:
    """Read future tradeable bars for a symbol after a given date."""
    rows: list[dict] = []
    for partition in manifest.get("partitions", []):
        rows.extend(parquet.read_partition(partition["parquet_ref"]))
    bars = sorted(
        (PreparedPriceBar.model_validate(r) for r in rows
         if r.get("symbol") == symbol and str(r.get("trade_date", "")) > str(after_date)
         and r.get("is_tradeable")),
        key=lambda item: str(item.trade_date),
    )
    return bars


def main() -> int:
    shadow_dir = PROJECT / "artifacts" / "research_shadow"
    runs_root = shadow_dir / "runs"
    std_dir = PROJECT / "artifacts" / "free_research_rebuild_all_raw_standard" / "standard"
    parquet = PITParquetStore(LocalObjectStore(PROJECT / "var" / "cn-research" / "parquet"))
    store = FileResearchShadowStore(shadow_dir)
    controller = ResearchShadowController(store)

    sessions = _find_real_prediction_sessions(runs_root)
    print(f"[backfill] real-prediction sessions: {len(sessions)}")

    # Group by symbol to avoid re-reading manifests
    by_symbol: dict[str, list[ResearchShadowSession]] = {}
    for s in sessions:
        by_symbol.setdefault(s.symbol, []).append(s)
    print(f"[backfill] distinct symbols: {len(by_symbol)}")

    total_outcomes = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for symbol, sym_sessions in sorted(by_symbol.items()):
        manifest = _find_manifest(symbol, std_dir)
        if manifest is None:
            print(f"  {symbol}: no standard manifest, skipping {len(sym_sessions)} sessions")
            skipped += len(sym_sessions)
            continue

        # Cache future bars per trade_date (sessions may share dates)
        bars_cache: dict[str, list[PreparedPriceBar]] = {}
        for session in sym_sessions:
            future = bars_cache.get(session.trade_date)
            if future is None:
                future = _read_future_bars(manifest, symbol, session.trade_date, parquet)
                bars_cache[session.trade_date] = future

            if not future:
                skipped += 1
                continue

            existing = {item.horizon_sessions for item in store.list_outcomes(session.id)}
            for horizon in (1, 5, 20, 60):
                if horizon in existing or len(future) < horizon:
                    continue
                window = future[:horizon]
                try:
                    outcome = controller.backfill_prices(
                        session=session,
                        horizon_sessions=horizon,
                        filled_at=now,
                        entry_price=window[0].open_normalized or window[0].close_normalized,
                        closes=[item.close_normalized for item in window],
                        lows=[item.low_normalized or item.close_normalized for item in window],
                        drawdown_entry_price=window[0].open_native or window[0].close_native,
                        drawdown_lows=[item.low_native or item.close_native for item in window],
                        suspended_during_window=any(item.is_suspended for item in window),
                        limit_event_during_window=any(
                            item.is_limit_up or item.is_limit_down for item in window
                        ),
                    )
                    total_outcomes += 1
                except Exception as exc:
                    print(f"  {symbol} {session.trade_date} h={horizon}: error: {exc}")

        print(f"  {symbol}: {len(sym_sessions)} sessions, future bars={len(future) if future else 0}")

    print(f"[backfill] total outcomes written: {total_outcomes}")
    print(f"[backfill] sessions skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
