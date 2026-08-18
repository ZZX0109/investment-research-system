#!/usr/bin/env python3
"""Run the guarded long-term cross-sectional baseline suite.

Input samples must come from an immutable snapshot and use the canonical
TrainingSample schema. The script refuses to train without an active snapshot
and mature long-horizon labels; it writes only a compact summary JSON
and optional compressed prediction artifact. Mixed CN partitions are allowed,
but only ``instrument_type=equity`` rows enter stock ranking labels; ETF rows
remain benchmark/market-feature inputs and are reported as excluded.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.long_term_pipeline import (
    build_long_term_observations,
    run_long_term_baselines,
    score_long_term_snapshot,
)
from investment_research.training.models import InstrumentType, Market, TrainingSample
from investment_research.training.artifacts import register_artifact
from investment_research.training.snapshot_landing import SnapshotGateConfig, evaluate_snapshot_gate, load_active_manifest
from investment_research.training.active_snapshot_guard import ActiveSnapshotInputError, assert_training_sources, require_active_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True, help="JSON/JSONL/Parquet samples or a directory containing them")
    parser.add_argument("--config", type=Path, default=PROJECT / "config/long_term_training.yaml")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--rebuild-index", type=Path, default=None, help="research-only rebuild index when no formal active pointer exists")
    parser.add_argument("--allow-research-only", action="store_true", help="run against the immutable research rebuild without claiming activation")
    parser.add_argument("--target", default="excess_return_240d")
    parser.add_argument("--snapshot-frequency", choices=("quarterly", "monthly"), default=None)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/long_term_training/latest.json")
    parser.add_argument("--predictions-output", type=Path, default=None, help="compressed Parquet row predictions; omitted when blocked")
    parser.add_argument("--checkpoint-dir", type=Path, default=None, help="per-model/per-fold checkpoint directory")
    parser.add_argument("--no-resume", action="store_true", help="ignore existing fold checkpoints")
    args = parser.parse_args()
    if args.predictions_output is None:
        args.predictions_output = args.output.with_suffix(".predictions.parquet")
    return args


def main() -> int:
    args = parse_args()
    config = load_long_term_training_config(args.config)
    if args.target not in config.targets:
        raise SystemExit(f"target is not in long-term config: {args.target}")
    manifest = None
    snapshot_id = None
    data_tier = "research_pit"
    gate_reasons: list[str] = []
    try:
        active = require_active_snapshot(args.data_root)
        manifest = active.manifest
        snapshot_id = manifest.snapshot_id
        data_tier = manifest.data_tier
        assert_training_sources(active, args.samples.resolve(), args.object_store.resolve())
    except (ValueError, ActiveSnapshotInputError) as exc:
        if not args.allow_research_only or args.rebuild_index is None:
            _write_blocked(args.output, [f"active_snapshot_unavailable:{exc}"])
            return 2
        rebuild_path = args.rebuild_index if args.rebuild_index.is_absolute() else PROJECT / args.rebuild_index
        rebuild = json.loads(rebuild_path.read_text(encoding="utf-8"))
        snapshot_id = rebuild.get("as_of") or rebuild.get("snapshot_id") or rebuild_path.stem
        gate_reasons.extend([
            f"research_only_active_snapshot_unavailable:{exc}",
            "formal_pit_activation_not_claimed",
        ])
    snapshot_frequency = args.snapshot_frequency or config.snapshot_frequency
    loaded_samples = _load_samples(
        args.samples,
        object_store=args.object_store,
        target=args.target,
        snapshot_frequency=snapshot_frequency,
    )
    # Long-term cross-sectional labels are stock-only.  ETF rows may be
    # present in the same PIT partitions because they provide benchmark and
    # market-state features, but they must never become ranked observations or
    # inflate the stock universe.  Keep the exclusion explicit in the report
    # so a mixed manifest cannot silently change the label population.
    excluded_instrument_counts: dict[str, int] = {}
    samples: list[TrainingSample] = []
    for sample in loaded_samples:
        if sample.market == Market.CN and sample.instrument_type == InstrumentType.EQUITY:
            samples.append(sample)
            continue
        key = f"{sample.market.value}:{sample.instrument_type.value}"
        excluded_instrument_counts[key] = excluded_instrument_counts.get(key, 0) + 1
    if not samples:
        _write_blocked(args.output, ["stock_ranking_universe_empty_after_etf_exclusion"])
        return 2
    observations = build_long_term_observations(
        samples,
        target=args.target,
        minimum_feature_coverage=config.minimum_financial_coverage,
        snapshot_frequency=snapshot_frequency,
    )
    if manifest is not None:
        gate = evaluate_snapshot_gate(
            manifest,
            config=SnapshotGateConfig(
                required_datasets=set(config.required_snapshot_datasets),
                minimum_financial_coverage=config.minimum_financial_coverage,
            ),
            labels_mature=bool(observations),
        )
        if not gate.passed:
            _write_blocked(args.output, gate.reasons)
            return 2
    prediction_rows: list[dict] = []
    report = run_long_term_baselines(
        observations,
        config=config,
        prediction_rows=prediction_rows,
        checkpoint_dir=args.checkpoint_dir,
        resume=not args.no_resume,
    )
    prediction_record = None
    if args.predictions_output and prediction_rows:
        prediction_record = _write_predictions(args.predictions_output, prediction_rows)
    report.update({
        "schema_version": "long-term-training-report-v1",
        "target": args.target,
        "snapshot_id": snapshot_id,
        "training_contract_hash": config.canonical_hash(),
        "feature_contract_version": _single_contract_version(samples, "feature_version"),
        "feature_contract_versions": sorted({str(sample.feature_version) for sample in samples if sample.feature_version}),
        "label_version": config.label_version,
        "label_policy": config.label_policy,
        "data_tier": data_tier,
        "gate_reasons": gate_reasons,
        "deployment_ready": False,
        "snapshot_frequency": snapshot_frequency,
        "decision_unit": config.primary_decision_unit,
        "primary_output_contract": config.score_outputs,
        "scorecards": _latest_scorecards(samples, config),
        "ranking_universe": {
            "market": "cn",
            "instrument_type": "equity",
            "included_sample_count": len(samples),
            "loaded_sample_count": len(loaded_samples),
            "excluded_instrument_counts": excluded_instrument_counts,
            "etf_role": "benchmark_and_market_features_only",
        },
    })
    if prediction_record is not None:
        report["predictions_ref"] = str(args.predictions_output)
        report["predictions_sha256"] = prediction_record.sha256
        report["prediction_row_count"] = len(prediction_rows)
    _atomic_write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("status") == "research_only" else 2


def _latest_scorecards(samples: list[TrainingSample], config) -> list[dict]:
    latest: dict[str, TrainingSample] = {}
    for sample in samples:
        previous = latest.get(sample.symbol)
        if previous is None or sample.as_of_date > previous.as_of_date:
            latest[sample.symbol] = sample
    rows = []
    for symbol, sample in sorted(latest.items()):
        score = score_long_term_snapshot(
            {name: float(value) for name, value in sample.features.items() if value is not None},
            feature_coverage=sample.feature_coverage,
            status_bands=config.status_bands,
        )
        rows.append({"symbol": symbol, "as_of_date": sample.as_of_date.isoformat(), **score})
    return rows


def _single_contract_version(samples: list[TrainingSample], field: str) -> str:
    """Return a version only when the input cohort has one explicit value.

    ``mixed`` and ``not_recorded`` are deliberate diagnostics; they prevent a
    training report from silently deriving a feature contract from a model
    version or from the first row in a mixed snapshot.
    """
    values = sorted({str(getattr(sample, field, "")) for sample in samples if getattr(sample, field, None)})
    if len(values) == 1:
        return values[0]
    return "mixed" if values else "not_recorded"


def _load_samples(
    path: Path,
    *,
    object_store: Path,
    target: str,
    snapshot_frequency: str,
) -> list[TrainingSample]:
    """Load direct rows or manifest references, keeping one period-end row.

    The manifest form is the normal server input. Selecting the period-end row
    while reading each partition keeps the long-term run small enough for a
    CPU baseline and avoids pretending every daily row is independent.
    """
    paths = sorted(path.rglob("*") if path.is_dir() else [path])
    selected: dict[tuple[str, object], TrainingSample] = {}
    try:
        from investment_research.service.object_store import LocalObjectStore
        from investment_research.training.parquet_store import PITParquetStore
        parquet_store = PITParquetStore(LocalObjectStore(object_store))
    except ImportError:
        parquet_store = None
    for item in paths:
        if not item.is_file() or item.name == "manifest.json":
            continue
        if item.suffix == ".parquet":
            try:
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise SystemExit("Parquet input requires pyarrow") from exc
            rows = pq.read_table(item).to_pylist()
        elif item.suffix in {".json", ".jsonl"}:
            text = item.read_text(encoding="utf-8")
            if item.suffix == ".jsonl":
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            else:
                payload = json.loads(text)
                if isinstance(payload, dict) and "sample_parquet_ref" in payload:
                    if parquet_store is None:
                        raise SystemExit("manifest input requires the local PIT parquet dependencies")
                    rows = parquet_store.read_partition(
                        payload["sample_parquet_ref"],
                        expected_payload_hash=payload.get("payload_hash"),
                    )
                elif isinstance(payload, dict) and "sample_manifests" in payload:
                    rows = []
                    for value in payload["sample_manifests"]:
                        manifest_path = Path(value)
                        if not manifest_path.is_absolute():
                            manifest_path = PROJECT / manifest_path
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if parquet_store is None:
                            raise SystemExit("manifest input requires the local PIT parquet dependencies")
                        rows.extend(parquet_store.read_partition(
                            manifest["sample_parquet_ref"],
                            expected_payload_hash=manifest.get("payload_hash"),
                        ))
                else:
                    rows = payload if isinstance(payload, list) else payload.get("samples", []) if isinstance(payload, dict) else []
        else:
            continue
        for row in rows:
            if isinstance(row, dict) and "labels" in row and "features" in row:
                row = dict(row)
                for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
                sample = TrainingSample.model_validate(row)
                period = _period_key(sample.as_of_date, snapshot_frequency)
                key = (sample.symbol, period)
                previous = selected.get(key)
                if previous is None or sample.as_of_date > previous.as_of_date:
                    selected[key] = sample
    return sorted(selected.values(), key=lambda item: (item.as_of_date, item.symbol))


def _period_key(value, frequency: str):
    from datetime import date
    if frequency == "monthly":
        return date(value.year, value.month, 1)
    quarter = (value.month - 1) // 3
    return date(value.year, quarter * 3 + 1, 1)


def _write_blocked(path: Path, reasons: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "long-term-training-report-v1", "status": "blocked", "deployment_ready": False, "blocking_reasons": sorted(set(reasons))}
    _atomic_write_json(path, payload)
    print(json.dumps(payload, ensure_ascii=False))


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_predictions(path: Path, rows: list[dict]):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("long-term prediction output requires pyarrow") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd", use_dictionary=True)
    return register_artifact(path.parent.resolve(), path.resolve(), kind="long_term_predictions")


if __name__ == "__main__":
    raise SystemExit(main())
