#!/usr/bin/env python3
"""Merge deterministic public-data coverage shards into one research ledger.

The collector can be split by symbol to make a full-universe backfill
restartable.  This command merges only explicit shard artifacts, preserves the
raw-record hashes and recomputes market coverage against the supplied universe;
it never upgrades a research record to formal PIT.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.service.free_research_ledger import build_coverage_ledgers


def _symbols(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        values = [item.get("code") if isinstance(item, dict) else item for item in payload]
    elif isinstance(payload, dict):
        values = payload.get("cn", [])
    else:
        raise ValueError("symbols file must be a current-universe list or market mapping")
    return {
        str(value).rsplit(".", 1)[-1].zfill(6)
        for value in values
        if value not in (None, "")
    }


def _record_key(item: dict) -> tuple:
    return (
        *("" if item.get(key) is None else str(item.get(key)) for key in (
            "market", "dataset", "symbol", "provider", "payload_hash", "status",
        )),
    )


def merge(inputs: list[Path], *, symbols_file: Path, output: Path) -> dict:
    records_by_key: dict[tuple, dict] = {}
    generated_at = datetime.min.replace(tzinfo=timezone.utc)
    data_tier = DataTier.RESEARCH_PIT.value
    for path in inputs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"coverage shard is not an object: {path}")
        if payload.get("data_tier") not in (None, data_tier):
            raise ValueError(f"non-research shard is not mergeable: {path}")
        raw_generated = str(payload.get("generated_at") or "")
        try:
            observed = datetime.fromisoformat(raw_generated.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            generated_at = max(generated_at, observed)
        except ValueError:
            pass
        for item in payload.get("records", []):
            if isinstance(item, dict):
                records_by_key[_record_key(item)] = item
    if generated_at == datetime.min.replace(tzinfo=timezone.utc):
        generated_at = datetime.now(timezone.utc)
    records = sorted(records_by_key.values(), key=lambda item: _record_key(item))
    ledgers = build_coverage_ledgers(
        records=records,
        targets={"cn": _symbols(symbols_file), "us": set(), "hk": set(), "jp": set()},
        generated_at=generated_at,
    )
    merged = {
        "schema_version": "free-research-coverage-v1",
        "data_tier": data_tier,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "catalog_ref": "merged_from_explicit_shards",
        "generated_at": generated_at.isoformat(),
        "mode": "research_only",
        "formal_deployment_allowed": False,
        "synthetic_count": 0,
        "records": records,
        "market_coverage": [item.model_dump(mode="json") for item in ledgers],
        "merged_inputs": [str(path) for path in inputs],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--symbols-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    merged = merge(args.inputs, symbols_file=args.symbols_file, output=args.output)
    cn = next(item for item in merged["market_coverage"] if item["market"] == "cn")
    print(json.dumps({
        "status": "research_only",
        "record_count": len(merged["records"]),
        "target_count": cn["target_count"],
        "successful_target_count": cn["successful_target_count"],
        "coverage_ratio": cn["coverage_ratio"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
