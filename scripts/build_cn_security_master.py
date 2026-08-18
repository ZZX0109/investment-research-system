#!/usr/bin/env python3
"""Build a conservative CN security/master-membership artifact from bars."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ETF_SYMBOLS = {"510050", "510300", "510500", "159915", "512100"}


def _canonical_symbol(value: object) -> str:
    return str(value or "").strip().rsplit(".", 1)[-1].zfill(6)


def _load_source_master(database: Path | None, raw_root: Path | None) -> dict[str, dict]:
    """Read the append-only security-master payloads without changing them."""
    if database is None or raw_root is None or not database.is_file():
        return {}
    try:
        connection = sqlite3.connect(database)
        rows = connection.execute(
            "SELECT payload_json FROM raw_data_batches "
            "WHERE dataset='cn_security_master_research'"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    latest: dict[str, dict] = {}
    for (payload_json,) in rows:
        try:
            metadata = json.loads(payload_json)
            reference = str(metadata.get("payload_ref") or "")
            path = raw_root / reference.removeprefix("file-object://")
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
            if isinstance(records, dict):
                records = [records]
            for record in records or []:
                symbol = _canonical_symbol(record.get("code") or metadata.get("symbol"))
                if symbol:
                    latest[symbol] = record
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return latest


def build_security_rows(
    source_root: Path,
    industry_map_path: Path,
    database: Path | None = None,
    raw_root: Path | None = None,
) -> list[dict]:
    import pyarrow.dataset as ds

    table = ds.dataset(source_root, format="parquet", partitioning="hive").to_table(
        columns=["symbol", "trade_date", "available_at", "provider"]
    )
    grouped: dict[str, dict] = {}
    for row in table.to_pylist():
        symbol = str(row.get("symbol") or "").strip()
        trade_date = str(row.get("trade_date") or "")[:10]
        if not symbol or not trade_date:
            continue
        item = grouped.setdefault(symbol, {
            "symbol": symbol,
            "instrument_type": "etf" if symbol in ETF_SYMBOLS else "equity",
            "listed_on_observed": trade_date,
            "last_observed_on": trade_date,
            "available_at": row.get("available_at"),
            "provider": row.get("provider") or "derived_standard_daily_bars",
        })
        item["listed_on_observed"] = min(item["listed_on_observed"], trade_date)
        item["last_observed_on"] = max(item["last_observed_on"], trade_date)
        if row.get("available_at"):
            item["available_at"] = max(str(item.get("available_at") or ""), str(row["available_at"]))
    source_master = _load_source_master(database, raw_root)
    try:
        mapping = json.loads(industry_map_path.read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, json.JSONDecodeError):
        mapping = {}
    output: list[dict] = []
    for symbol in sorted(grouped):
        item = grouped[symbol]
        source = source_master.get(symbol, {})
        listed_on = str(source.get("ipoDate") or item["listed_on_observed"])[:10]
        out_date = str(source.get("outDate") or "").strip()
        delisted_on = out_date[:10] if out_date else None
        source_industry = source.get("industry")
        item.update({
            "effective_from": listed_on,
            "effective_to": delisted_on,
            "listed_on": listed_on,
            "delisted_on": delisted_on,
            "security_name": source.get("code_name"),
            "security_type_code": source.get("type"),
            "listing_status": source.get("status"),
            "source_industry": source_industry,
            "industry_classification": source.get("industryClassification"),
            "industry_updated_on": source.get("industryUpdateDate"),
            "industry_key": mapping.get(symbol) or source_industry,
            "st_status": None,
            "code_change_from": None,
            "quality_status": "degraded",
            "missing_reason": "historical delisting/ST/code-change and publication-time records are not covered by the public backfill",
            "missing_reason_code": "provider_not_covered",
            "data_tier": "research_pit",
            "deployment_ready": False,
        })
        output.append(item)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=PROJECT / "var/cn-research/parquet/pit/cn/standard_daily_bars_research/free-research-standard-v1")
    parser.add_argument("--industry-map", type=Path, default=PROJECT / "config/cn_industry_map.json")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_security_master")
    args = parser.parse_args()
    rows = build_security_rows(args.source_root, args.industry_map, args.database, args.raw_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    output = args.output_root / "security_master.parquet"
    memberships = args.output_root / "historical_universe_memberships.parquet"
    pq.write_table(pa.Table.from_pylist(rows), output.with_suffix(".tmp.parquet"), compression="zstd", use_dictionary=True)
    os.replace(output.with_suffix(".tmp.parquet"), output)
    pq.write_table(pa.Table.from_pylist([
        {"symbol": row["symbol"], "market": "cn", "effective_from": row["effective_from"], "effective_to": row["effective_to"], "available_at": row["available_at"], "revision": 1, "quality_status": row["quality_status"], "missing_reason_code": row["missing_reason_code"]}
        for row in rows
    ]), memberships.with_suffix(".tmp.parquet"), compression="zstd", use_dictionary=True)
    os.replace(memberships.with_suffix(".tmp.parquet"), memberships)
    report = {
        "schema_version": "cn-security-master-derived-v1",
        "dataset": "cn_historical_universe_memberships",
        "provider": "derived_standard_daily_bars",
        "status": "degraded" if rows else "unavailable",
        "quality_status": "degraded" if rows else "unavailable",
        "row_count": len(rows),
        "symbol_count": len(rows),
        "industry_mapped_count": sum(row.get("industry_key") is not None for row in rows),
        "listed_on_coverage": sum(bool(row.get("listed_on")) for row in rows) / len(rows) if rows else 0.0,
        "listing_status_coverage": sum(bool(row.get("listing_status")) for row in rows) / len(rows) if rows else 0.0,
        "security_name_coverage": sum(bool(row.get("security_name")) for row in rows) / len(rows) if rows else 0.0,
        "st_status_coverage": 0.0,
        "delisting_coverage": 0.0,
        "code_change_coverage": 0.0,
        "published_at_coverage": 0.0,
        "available_at_coverage": sum(bool(row.get("available_at")) for row in rows) / len(rows) if rows else 0.0,
        "missing_reason": "historical delisting/ST/code-change and publication-time records are not covered by the public backfill",
        "missing_reason_code": "provider_not_covered",
        "output_path": str(memberships),
        "security_master_path": str(output),
        "sha256": hashlib.sha256(memberships.read_bytes()).hexdigest(),
        "sha256_verified": True,
        "data_tier": "research_pit",
        "deployment_ready": False,
    }
    (args.output_root / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
