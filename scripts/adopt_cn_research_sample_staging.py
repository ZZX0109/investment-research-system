#!/usr/bin/env python3
"""Adopt legacy snapshot-bound sample directories into resumable markers.

An earlier sample run wrote valid manifests before completion markers existed.
This explicit migration validates every observed manifest against the immutable
base snapshot, then writes deterministic per-symbol markers.  It never updates
the rebuild index or active pointer and never claims missing years are present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON artifact must be an object: {path}")
    return value


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT / path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-index", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument(
        "--allow-unmarked", action="store_true", required=True,
        help="Explicitly acknowledge migration of pre-marker staging output.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    base_path = _resolve(args.base_index)
    sample_root = _resolve(args.sample_root)
    base = _read(base_path)
    if base.get("status") != "research_only" or base.get("data_tier") != "research_pit":
        raise SystemExit("base index is not a research_only research_pit rebuild")
    if not args.allow_unmarked:
        raise SystemExit("--allow-unmarked is required for this explicit legacy migration")
    contexts = base.get("contexts")
    if not isinstance(contexts, dict) or not contexts:
        raise SystemExit("base index has no contexts")

    reports: dict[str, dict[str, int]] = {}
    all_hashes: set[str] = set()
    for context, context_payload in contexts.items():
        expected_id = str(context_payload.get("snapshot_id") or "")
        expected_hash = str(context_payload.get("snapshot_hash") or "")
        if not expected_id or not expected_hash:
            raise SystemExit(f"base context has no snapshot binding: {context}")
        context_root = sample_root / "samples" / context
        if not context_root.is_dir():
            continue
        reports[context] = {}
        for cohort_root in sorted(path for path in context_root.iterdir() if path.is_dir()):
            for symbol_root in sorted(path for path in cohort_root.iterdir() if path.is_dir()):
                manifests = sorted(path for path in symbol_root.glob("*.json") if path.name != ".complete.json")
                if not manifests:
                    continue
                for path in manifests:
                    payload = _read(path)
                    if (
                        payload.get("market_snapshot_id") != expected_id
                        or payload.get("market_snapshot_hash") != expected_hash
                    ):
                        raise SystemExit(f"snapshot mismatch: {path}")
                    if payload.get("data_tier") != "research_pit":
                        raise SystemExit(f"sample is not research_pit: {path}")
                    if not payload.get("sample_parquet_ref") or int(payload.get("row_count", 0) or 0) <= 0:
                        raise SystemExit(f"sample has no readable partition evidence: {path}")
                    all_hashes.add(expected_hash)
                marker = {
                    "schema_version": "free-research-sample-completion-v1",
                    "symbol": symbol_root.name,
                    "cohort": cohort_root.name,
                    "market_snapshot_id": expected_id,
                    "market_snapshot_hash": expected_hash,
                    "manifest_count": len(manifests),
                    "completion_evidence": "legacy_manifest_scan",
                    "adopted_from": str(sample_root),
                }
                marker_path = symbol_root / ".complete.json"
                encoded = json.dumps(marker, ensure_ascii=False, indent=2)
                if marker_path.is_file() and marker_path.read_text(encoding="utf-8") != encoded:
                    raise SystemExit(f"completion marker already differs: {marker_path}")
                marker_path.write_text(encoded, encoding="utf-8")
                reports[context][f"{cohort_root.name}:{symbol_root.name}"] = len(manifests)

    report = {
        "schema_version": "cn-research-sample-legacy-adoption-v1",
        "base_index": str(base_path),
        "sample_root": str(sample_root),
        "snapshot_hashes": sorted(all_hashes),
        "symbol_count": sum(len(value) for value in reports.values()),
        "manifest_count": sum(sum(value.values()) for value in reports.values()),
        "completion_evidence": "legacy_manifest_scan",
        "training_blocked": True,
    }
    report_hash = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report["report_hash"] = report_hash
    report_path = sample_root / "legacy-adoption-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
