#!/usr/bin/env python3
"""Consolidate the locally-fetched CSI index-constituent snapshots (11106 rows)
and historical adjustment records (718 rows) into the
historical_universe_memberships table of the catalog database.

Until now these JSONL artifacts lived as orphan files under
artifacts/subagent_membership_retry/normalized/ while the catalog table's
index_memberships field stayed an empty list for every symbol.  This script
closes that gap so the historical-membership data layer is queryable from the
catalog and feeds the lifecycle / historical-membership audit.

Research-only: effective_on dates come from the CSI snapshot xls files
(actual_historical_snapshot fidelity).  No future-dated or backfilled
effective_at is invented; rows without effective_on keep null.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT / "var/cn-research/catalog.db"
DEFAULT_SNAPSHOTS = PROJECT / "artifacts/subagent_membership_retry/normalized/index_membership_snapshots.jsonl"
DEFAULT_ADJUSTMENTS = PROJECT / "artifacts/subagent_membership_retry/normalized/historical_adjustment_records.jsonl"


def _canonical_symbol(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith(("sh.", "sz.", "bj.")):
        text = text[3:]
    return text if (text.isdigit() and len(text) == 6) else None


def _load_snapshots(path: Path) -> dict[str, list[dict]]:
    """Aggregate per-symbol index membership snapshot records."""
    out: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sym = _canonical_symbol(d.get("security_code"))
            if sym:
                out[sym].append({
                    "index_code": d.get("index_code"),
                    "index_name": d.get("index_name"),
                    "effective_on": d.get("effective_on"),
                    "membership_status": d.get("membership_status"),
                    "evidence_fidelity": d.get("evidence_fidelity"),
                    "source_url": d.get("source_url"),
                    "available_at": d.get("available_at"),
                    "evidence_type": "index_constituent_snapshot",
                })
    return dict(out)


def _load_adjustments(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sym = _canonical_symbol(d.get("security_code"))
            if sym:
                out[sym].append({
                    "index_code": d.get("index_code"),
                    "index_name": d.get("index_name"),
                    "action": d.get("action"),
                    "published_on": d.get("published_on"),
                    "effective_on": d.get("effective_on"),
                    "effective_date_basis": d.get("effective_date_basis"),
                    "source_notice_id": d.get("source_notice_id"),
                    "source_notice_url": d.get("source_notice_url"),
                    "evidence_type": "index_constituent_adjustment",
                })
    return dict(out)


def _merge_memberships(existing: list, snapshots: list, adjustments: list) -> list:
    """Merge existing index_memberships with new CSI snapshot + adjustment records."""
    merged = list(existing) if isinstance(existing, list) else []
    # Snapshot records (deduplicated by index_code + effective_on)
    seen = {(m.get("index_code"), m.get("effective_on"), m.get("evidence_type")) for m in merged}
    for rec in snapshots:
        key = (rec.get("index_code"), rec.get("effective_on"), rec.get("evidence_type"))
        if key not in seen:
            merged.append(rec)
            seen.add(key)
    for rec in adjustments:
        key = (rec.get("index_code"), rec.get("effective_on"), rec.get("evidence_type"), rec.get("action"))
        if key not in seen:
            merged.append(rec)
            seen.add(key)
    return merged


def consolidate(catalog: Path, snapshots_path: Path, adjustments_path: Path) -> dict:
    snapshots = _load_snapshots(snapshots_path)
    adjustments = _load_adjustments(adjustments_path)

    conn = sqlite3.connect(catalog)
    conn.row_factory = sqlite3.Row

    # Load existing rows keyed by symbol
    existing_rows = {
        row["symbol"]: dict(row) for row in conn.execute(
            "SELECT id, market, symbol, effective_from, effective_to, available_at, revision, payload_json "
            "FROM historical_universe_memberships"
        ).fetchall()
    }

    # All symbols: existing + those appearing in CSI data
    all_symbols = set(existing_rows) | set(snapshots) | set(adjustments)

    updated = 0
    inserted = 0
    sym_with_membership = 0
    total_membership_records = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for sym in all_symbols:
        snap_list = snapshots.get(sym, [])
        adj_list = adjustments.get(sym, [])
        existing = existing_rows.get(sym)
        existing_payload = {}
        if existing and existing.get("payload_json"):
            try:
                existing_payload = json.loads(existing["payload_json"])
            except (TypeError, json.JSONDecodeError):
                existing_payload = {}

        current_memberships = existing_payload.get("index_memberships") or []
        new_memberships = _merge_memberships(current_memberships, snap_list, adj_list)
        if new_memberships:
            sym_with_membership += 1
            total_membership_records += len(new_memberships)

        # Determine effective_from: prefer earliest snapshot effective_on, else existing
        eff_dates = [m.get("effective_on") for m in new_memberships if m.get("effective_on")]
        eff_dates = [d for d in eff_dates if d and d != "None"]
        # CSI snapshots use YYYYMMDD; normalise to ISO so min() sorts correctly
        iso_dates = []
        for d in eff_dates:
            if isinstance(d, str) and len(d) == 8 and d.isdigit():
                iso_dates.append(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
            elif isinstance(d, str) and len(d) >= 10:
                iso_dates.append(d[:10])
        earliest_eff = min(iso_dates) if iso_dates else None
        # effective_from is NOT NULL in the schema; fall back to the existing
        # value, then the snapshot available_at, then now.
        if not earliest_eff:
            earliest_eff = existing.get("effective_from") if existing else None
        if not earliest_eff:
            avail = existing_payload.get("available_at") or now_iso
            earliest_eff = avail

        payload = dict(existing_payload)
        payload.update({
            "symbol": sym,
            "market": existing_payload.get("market", "cn"),
            "exchange": existing_payload.get("exchange", "CN"),
            "instrument_type": existing_payload.get("instrument_type", "equity"),
            "effective_from": earliest_eff or existing_payload.get("effective_from"),
            "effective_to": existing_payload.get("effective_to"),
            "listed_on": existing_payload.get("listed_on"),
            "delisted_on": existing_payload.get("delisted_on"),
            "index_memberships": new_memberships,
            "industry": existing_payload.get("industry"),
            "size_bucket": existing_payload.get("size_bucket"),
            "liquidity_bucket": existing_payload.get("liquidity_bucket"),
            "is_st": existing_payload.get("is_st", False),
            "is_suspended": existing_payload.get("is_suspended", False),
            "is_tradeable": existing_payload.get("is_tradeable", True),
            "available_at": existing_payload.get("available_at") or now_iso,
            "provider": existing_payload.get("provider", "csi_index_constituent_snapshot"),
            "revision": (existing_payload.get("revision", 0) or 0) + 1,
        })

        if existing:
            conn.execute(
                "UPDATE historical_universe_memberships SET payload_json=?, effective_from=?, available_at=?, revision=? WHERE symbol=?",
                (json.dumps(payload, ensure_ascii=False), payload["effective_from"], payload["available_at"], payload["revision"], sym),
            )
            updated += 1
        else:
            conn.execute(
                "INSERT INTO historical_universe_memberships (id, market, symbol, effective_from, effective_to, available_at, revision, payload_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid4()), "cn", sym, payload["effective_from"], payload.get("effective_to"), payload["available_at"], payload["revision"], json.dumps(payload, ensure_ascii=False)),
            )
            inserted += 1

    conn.commit()
    stats = {
        "existing_rows_before": len(existing_rows),
        "symbols_total": len(all_symbols),
        "updated": updated,
        "inserted": inserted,
        "symbols_with_index_membership": sym_with_membership,
        "total_membership_records": total_membership_records,
        "snapshot_symbols": len(snapshots),
        "adjustment_symbols": len(adjustments),
    }
    conn.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--adjustments", type=Path, default=DEFAULT_ADJUSTMENTS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        # dry run still reads + aggregates but does not write
        snapshots = _load_snapshots(args.snapshots)
        adjustments = _load_adjustments(args.adjustments)
        conn = sqlite3.connect(args.catalog)
        existing = conn.execute("SELECT COUNT(*) FROM historical_universe_memberships").fetchone()[0]
        conn.close()
        all_syms = set(snapshots) | set(adjustments)
        print(f"[consolidate-membership] dry-run: existing={existing} snapshot_syms={len(snapshots)} adj_syms={len(adjustments)} union={len(all_syms)}")
        return 0

    stats = consolidate(args.catalog, args.snapshots, args.adjustments)
    print(f"[consolidate-membership] {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
