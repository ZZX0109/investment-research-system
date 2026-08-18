#!/usr/bin/env python3
"""Audit effective values, event semantics, PIT metadata and label maturity."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


FINANCIAL_FEATURES = (
    "fundamental_gross_margin",
    "fundamental_receivable_turnover",
    "fundamental_inventory_turnover",
    "fundamental_current_ratio",
    "fundamental_quick_ratio",
    "fundamental_cash_ratio",
    "fundamental_cfo_to_net_profit",
)
LONG_LABELS = (
    "excess_return_120d",
    "excess_return_240d",
    "future_max_drawdown_120d",
    "future_max_drawdown_240d",
    "future_quality_persistence_4q",
    "future_quality_persistence_8q",
)


def _finite(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _json_object(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def audit(source_root: Path) -> dict:
    import pyarrow.dataset as ds

    dataset = ds.dataset(source_root, format="parquet", partitioning="hive")
    columns = [
        "symbol", "as_of_date", "features", "labels", "published_at", "as_of",
        "feature_cutoff", "available_at", "collected_at", "revision_id",
        "input_revision_ids", "source_delay_seconds", "event_source_available",
        "event_coverage_status", "point_in_time_event_count", "event_count_1d",
        "event_count_7d", "event_count_30d", "event_provider_count",
        "event_semantic_coverage", "event_missing_mask", "data_quality_mask",
    ]
    available_columns = set(dataset.schema.names)
    selected = [name for name in columns if name in available_columns]
    scanner = dataset.scanner(columns=selected, batch_size=32768, use_threads=True)
    total = 0
    symbols: set[str] = set()
    counters = Counter()
    feature_counts = Counter()
    label_counts = Counter()
    field_counts = Counter()
    symbol_feature_counts: dict[str, Counter] = defaultdict(Counter)
    event_reason_counts = Counter()
    status_counts = Counter()
    time_contract = {name: {"present": name in available_columns, "non_empty": 0} for name in ("published_at", "as_of", "feature_cutoff", "available_at", "collected_at", "revision_id", "input_revision_ids", "source_delay_seconds")}

    for batch in scanner.to_batches():
      for row in batch.to_pylist():
        total += 1
        symbol = str(row.get("symbol") or "")
        symbols.add(symbol)
        features = _json_object(row.get("features"))
        labels = _json_object(row.get("labels"))
        for name in FINANCIAL_FEATURES:
            if _finite(features.get(name)):
                feature_counts[name] += 1
                symbol_feature_counts[symbol][name] += 1
        for name in LONG_LABELS:
            if _finite(labels.get(name)):
                label_counts[name] += 1
        for name in time_contract:
            if name in available_columns and row.get(name) not in (None, "", [], {}):
                time_contract[name]["non_empty"] += 1

        status = str(row.get("event_coverage_status") or "missing")
        status_counts[status] += 1
        source_available = bool(row.get("event_source_available"))
        event_count = any((int(row.get(name) or 0) > 0) for name in ("point_in_time_event_count", "event_count_1d", "event_count_7d", "event_count_30d"))
        counters["event_source_available"] += int(source_available)
        counters["event_with_count"] += int(event_count)
        counters["event_source_available_but_no_event"] += int(source_available and not event_count)
        counters["event_source_unavailable"] += int(not source_available)
        reasons = _json_object(row.get("event_missing_mask"))
        for reason, value in reasons.items():
            if _finite(value) and float(value) > 0:
                event_reason_counts[reason] += 1

    per_symbol = {}
    for symbol, counts in symbol_feature_counts.items():
        per_symbol[symbol] = {name: counts[name] / max(1, total) for name in FINANCIAL_FEATURES}
    return {
        "schema_version": "cn-sample-evidence-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "row_count": total,
        "symbol_count": len(symbols),
        "columns_present": sorted(available_columns),
        "financial_finite_coverage": {name: feature_counts[name] / total if total else 0.0 for name in FINANCIAL_FEATURES},
        "financial_finite_counts": dict(feature_counts),
        "label_finite_coverage": {name: label_counts[name] / total if total else 0.0 for name in LONG_LABELS},
        "label_finite_counts": dict(label_counts),
        "event": {
            "status_counts": dict(status_counts),
            "source_available_count": counters["event_source_available"],
            "source_available_coverage": counters["event_source_available"] / total if total else 0.0,
            "with_event_count": counters["event_with_count"],
            "with_event_count_coverage": counters["event_with_count"] / total if total else 0.0,
            "source_available_but_no_event_count": counters["event_source_available_but_no_event"],
            "source_unavailable_count": counters["event_source_unavailable"],
            "missing_reason_counts": dict(event_reason_counts),
        },
        "time_contract": {
            name: {**value, "coverage": value["non_empty"] / total if total else 0.0}
            for name, value in time_contract.items()
        },
        "note": "Finite coverage is computed from parsed feature/label values; file or key presence is not counted as valid data.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "row_count": report["row_count"],
        "financial_finite_coverage": report["financial_finite_coverage"],
        "event": report["event"],
        "time_contract": report["time_contract"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
