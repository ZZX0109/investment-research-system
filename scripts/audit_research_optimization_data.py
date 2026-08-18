#!/usr/bin/env python3
"""Audit the frozen full CN research pool before expensive ranking experiments."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore
from investment_research.training.models import TrainingSample
from investment_research.training.parquet_store import PITParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-manifest-file", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--all-partitions", action="store_true",
        help="audit every frozen sample partition instead of one latest partition per symbol",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.sample_manifest_file.read_text(encoding="utf-8"))
    paths = payload if isinstance(payload, list) else payload["sample_manifests"]
    # The default is a fast schema/scope check. Long-horizon label coverage and
    # historical evidence claims require --all-partitions; latest partitions
    # near the data tail are expected to have immature 120/240-day labels.
    latest: dict[str, str] = {}
    for value in paths:
        path = Path(value)
        symbol = path.parent.name
        year = path.name.split("-", 1)[0]
        if symbol not in latest or year > latest[symbol].split("/", 1)[0]:
            latest[symbol] = f"{year}/{value}"
    selected_paths = list(paths)
    if not args.all_partitions:
        selected_paths = list(latest.values())
    else:
        selected_paths = [str(value) for value in paths]
    store = PITParquetStore(LocalObjectStore(args.object_store))
    row_count = 0
    feature_presence: Counter[str] = Counter()
    label_presence: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    event_status: Counter[str] = Counter()
    errors: list[str] = []
    feature_total = Counter()
    label_total = Counter()
    for encoded in selected_paths:
        value = encoded if args.all_partitions else encoded.split("/", 1)[1]
        manifest_path = PROJECT / value
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = store.read_partition(manifest["sample_parquet_ref"])
            for row in rows:
                row = dict(row)
                for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
                sample = TrainingSample.model_validate(row)
                row_count += 1
                symbol_counts[sample.symbol] += 1
                event_status[sample.event_coverage_status] += 1
                for key, item in sample.features.items():
                    feature_total[key] += 1
                    if item is not None:
                        feature_presence[key] += 1
                for key, item in sample.labels.model_dump().items():
                    label_total[key] += 1
                    if item is not None:
                        label_presence[key] += 1
        except Exception as exc:  # audit must report all broken partitions
            errors.append(f"{value}:{type(exc).__name__}:{exc}")
    result = {
        "schema_version": "research-optimization-data-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_partition_count": len(latest),
        "audited_partition_count": len(selected_paths),
        "audit_scope": "all_partitions" if args.all_partitions else "latest_partition_per_symbol",
        "observed_symbol_count": len(symbol_counts),
        "observed_symbols": sorted(symbol_counts),
        "sample_row_count": row_count,
        "feature_presence": {
            key: feature_presence[key] / feature_total[key]
            for key in sorted(feature_total)
        },
        "label_presence": {
            key: label_presence[key] / label_total[key]
            for key in sorted(label_total)
        },
        "event_coverage_status": dict(event_status),
        "required_labels": {
            key: {
                "present": label_presence[key],
                "total": label_total[key],
                "coverage": label_presence[key] / label_total[key] if label_total[key] else 0.0,
            }
            for key in (
                "excess_return_120d", "excess_return_240d",
                "future_max_drawdown_120d", "future_max_drawdown_240d",
            )
        },
        "errors": errors,
        "status": "blocked" if errors or len(symbol_counts) < 162 or any(
            not label_presence[key] for key in (
                "excess_return_120d", "excess_return_240d",
                "future_max_drawdown_120d", "future_max_drawdown_240d",
            )
        ) else "ready_for_full_pool_baseline",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("latest_partition_count", "observed_symbol_count", "sample_row_count", "required_labels", "status")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
