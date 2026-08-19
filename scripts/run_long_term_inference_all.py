#!/usr/bin/env python3
"""Batch-generate the four long-term model readings for the whole cohort.

Wires the trained deep-run models (already registered via
register_long_term_model_artifacts.py) into the runtime artifact the API
reads: ``artifacts/long_term_model_readings/latest.json``.

It loads frozen PIT samples for every symbol in the rebuild-index cohort from
the parquet store, hands them to ``DeepLongTermInferenceService.predict_latest
_from_samples`` (which builds the aligned 20-session windows, runs the four
models and atomically writes the readings artifact), then prints the result.

This is the batch long-term path that no existing single script exposed; it
mirrors run_cn_research_inference.py's sample loading but targets the 120/240d
long-term models instead of the short-term shadow models.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore  # noqa: E402
from investment_research.service.deep_long_term import DeepLongTermInferenceService  # noqa: E402
from investment_research.training.parquet_store import PITParquetStore  # noqa: E402

# Reuse the proven sample loader from the short-term inference script rather
# than duplicating its manifest/parquet wiring.
_spec = importlib.util.spec_from_file_location(
    "_cn_research_inference", PROJECT / "scripts" / "run_cn_research_inference.py",
)
_rci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rci)
_samples_for_symbol = _rci._samples_for_symbol


def main() -> int:
    rebuild_index = PROJECT / "artifacts" / "server-run-auto-long-term-deep-20260817" / "rebuild" / "rebuild-2026-08-14-1563c6f013cb.json"
    index = json.loads(rebuild_index.read_text(encoding="utf-8"))
    if index.get("data_tier") != "research_pit" or index.get("deployment_ready"):
        print("inference requires a non-deployable research_pit rebuild index", file=sys.stderr)
        return 2
    context = index["contexts"]["close_confirmed"]
    cohort = "cn_equity_core"
    object_store = PROJECT / "var" / "cn-research" / "parquet"
    store = PITParquetStore(LocalObjectStore(object_store))

    manifest_paths = [Path(p) for p in context["sample_manifests"].get(cohort, [])]
    symbols = sorted({json.loads(p.read_text(encoding="utf-8"))["symbol"] for p in manifest_paths})
    print(f"cohort symbols: {len(symbols)}", flush=True)

    decision_time = datetime.fromisoformat("2026-08-18T15:00:00+08:00")
    # build_sequence_examples now accepts require_label=False, so inference
    # builds the latest feature window without a mature future label (predict()
    # never reads the target).  Pass the latest ~30 visible rows per symbol:
    # that yields ~6 windows/symbol -> ~4k total -> fast, no swap, and the
    # kept "latest" window ends at the most recent session (2026-08-14).
    all_samples: list = []
    skipped: list[str] = []
    short_symbols: list[str] = []
    for i, symbol in enumerate(symbols, 1):
        try:
            symbol_samples = _samples_for_symbol(context, cohort, symbol, store)
        except Exception as exc:  # noqa: BLE001 - per-symbol resilience
            skipped.append(f"{symbol}: {exc}")
            continue
        visible = [
            item for item in symbol_samples
            if item.as_of is not None
            and item.as_of <= decision_time
            and item.feature_cutoff <= decision_time
        ]
        visible.sort(key=lambda s: s.as_of)
        latest_30 = visible[-30:]
        if len(latest_30) < 20:
            short_symbols.append(f"{symbol}:{len(latest_30)}")
        all_samples.extend(latest_30)
        if i % 40 == 0:
            print(f"  loaded {i}/{len(symbols)} symbols, samples so far: {len(all_samples)}", flush=True)

    print(f"total latest samples: {len(all_samples)}; skipped {len(skipped)} symbols; short {len(short_symbols)}", flush=True)
    if skipped:
        print("skipped:\n  " + "\n  ".join(skipped[:20]), flush=True)
    if short_symbols:
        print("short(<20 visible rows, will yield no window):\n  " + "\n  ".join(short_symbols[:20]), flush=True)

    if not all_samples:
        print("no samples to infer; aborting", file=sys.stderr)
        return 2

    service = DeepLongTermInferenceService(PROJECT)
    try:
        out = service.predict_latest_from_samples(all_samples, as_of=decision_time)
    except Exception as exc:  # noqa: BLE001
        print(f"inference failed: {exc}", file=sys.stderr)
        return 3
    print(f"wrote readings artifact: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
