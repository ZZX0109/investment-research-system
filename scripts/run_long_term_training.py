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
from datetime import date
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


# The long-term loader needs the canonical sample contract, but not every
# column carried by the PIT object (for example, some legacy provenance
# extensions).  Projecting these columns keeps a research-only run bounded
# when the manifest list contains thousands of small immutable partitions.
_SAMPLE_LOAD_COLUMNS = [
    "symbol", "market", "instrument_type", "coverage_group", "industry_key",
    "benchmark_symbol", "sector_reference_symbol", "style_reference_symbol",
    "as_of_date", "as_of_time", "feature_cutoff", "decision_context",
    "prediction_start_date", "market_snapshot_id", "market_snapshot_hash",
    "feature_version", "label_version", "data_version", "features",
    "feature_coverage", "core_feature_coverage", "missing_features", "labels",
    "point_in_time_event_count", "event_source_available", "event_coverage_status",
    "event_count_1d", "event_count_7d", "event_count_30d", "event_provider_count",
    "event_semantic_coverage", "data_issues", "provider", "published_at", "as_of",
    "payload_ref", "source_url", "raw_hash", "normalized_hash", "data_tier",
    "data_quality_status", "data_quality_mask", "event_missing_mask", "provider_id",
    "revision_id", "source_delay_seconds", "cache_state", "input_revision_ids",
]


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
    parser.add_argument(
        "--minimum-feature-coverage", type=float, default=None,
        help=(
            "Research-only override for the sample feature-coverage floor. "
            "The configured formal floor remains the default and cannot be "
            "lowered without --allow-research-only."
        ),
    )
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/long_term_training/latest.json")
    parser.add_argument("--predictions-output", type=Path, default=None, help="compressed Parquet row predictions; omitted when blocked")
    parser.add_argument("--checkpoint-dir", type=Path, default=None, help="per-model/per-fold checkpoint directory")
    parser.add_argument("--no-resume", action="store_true", help="ignore existing fold checkpoints")
    parser.add_argument(
        "--enrich-liquidity-from-rebuild", action="store_true",
        help=(
            "Research-only compatibility path: join same-date amount and "
            "turnover fields from the immutable standard layer referenced by "
            "--rebuild-index. No values are inferred when the bar is missing."
        ),
    )
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
    minimum_feature_coverage = (
        config.minimum_financial_coverage
        if args.minimum_feature_coverage is None
        else float(args.minimum_feature_coverage)
    )
    if not 0.0 <= minimum_feature_coverage <= 1.0:
        _write_blocked(args.output, ["minimum_feature_coverage_must_be_between_0_and_1"])
        return 2
    if minimum_feature_coverage < config.minimum_financial_coverage:
        if not args.allow_research_only:
            _write_blocked(args.output, ["lower_feature_coverage_requires_research_only"])
            return 2
        gate_reasons.append(
            "research_only_feature_coverage_override:"
            f"{minimum_feature_coverage:.6f}<{config.minimum_financial_coverage:.6f}"
        )
    loaded_samples = _load_samples(
        args.samples,
        object_store=args.object_store,
        target=args.target,
        snapshot_frequency=snapshot_frequency,
    )
    feature_enrichment = None
    if args.enrich_liquidity_from_rebuild:
        if args.rebuild_index is None:
            _write_blocked(args.output, ["liquidity_enrichment_requires_rebuild_index"])
            return 2
        loaded_samples, feature_enrichment = _enrich_liquidity_features(
            loaded_samples,
            rebuild_index=args.rebuild_index,
            object_store=args.object_store,
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
        minimum_feature_coverage=minimum_feature_coverage,
        snapshot_frequency=snapshot_frequency,
    )
    target_label_count = sum(
        1 for sample in samples if getattr(sample.labels, args.target, None) is not None
    )
    coverage_eligible_count = sum(
        1 for sample in samples if sample.feature_coverage >= minimum_feature_coverage
    )
    target_and_coverage_count = sum(
        1 for sample in samples
        if getattr(sample.labels, args.target, None) is not None
        and sample.feature_coverage >= minimum_feature_coverage
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
    if not observations:
        _write_blocked(
            args.output,
            ["no_mature_long_term_observations"],
            target=args.target,
            snapshot_id=snapshot_id,
            data_tier=data_tier,
            gate_reasons=gate_reasons,
            minimum_feature_coverage=minimum_feature_coverage,
            configured_formal_feature_coverage=config.minimum_financial_coverage,
            loaded_sample_count=len(loaded_samples),
            ranking_sample_count=len(samples),
            target_label_available_count=target_label_count,
            coverage_eligible_count=coverage_eligible_count,
            target_and_coverage_count=target_and_coverage_count,
        )
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
        "minimum_feature_coverage": minimum_feature_coverage,
        "configured_formal_feature_coverage": config.minimum_financial_coverage,
        "target_label_available_count": target_label_count,
        "coverage_eligible_count": coverage_eligible_count,
        "target_and_coverage_count": target_and_coverage_count,
        "mature_observation_count": len(observations),
        "mature_decision_date_count": len({item.decision_date for item in observations}),
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
    if feature_enrichment is not None:
        report["feature_enrichment"] = feature_enrichment
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


def _enrich_liquidity_features(
    samples: list[TrainingSample], *, rebuild_index: Path, object_store: Path,
) -> tuple[list[TrainingSample], dict]:
    """Join explicit same-date bar liquidity inputs without inventing values."""
    rebuild_path = rebuild_index if rebuild_index.is_absolute() else PROJECT / rebuild_index
    if not rebuild_path.is_file():
        raise SystemExit(f"rebuild index is missing for liquidity enrichment: {rebuild_path}")
    rebuild = json.loads(rebuild_path.read_text(encoding="utf-8"))
    try:
        from investment_research.service.object_store import LocalObjectStore
        from investment_research.training.parquet_store import PITParquetStore
        parquet_store = PITParquetStore(LocalObjectStore(object_store))
    except ImportError as exc:
        raise SystemExit("liquidity enrichment requires the local PIT parquet dependencies") from exc
    bars: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    manifest_count = 0
    partition_count = 0
    for ref in rebuild.get("standard_manifest_refs") or []:
        manifest_path = Path(ref)
        if not manifest_path.is_absolute():
            manifest_path = PROJECT / manifest_path
        if not manifest_path.is_file():
            continue
        manifest_count += 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for partition in manifest.get("partitions") or []:
            partition_count += 1
            rows = parquet_store.read_partition(
                partition["parquet_ref"],
                expected_payload_hash=partition.get("payload_hash"),
            )
            for row in rows:
                if not row.get("symbol") or not row.get("trade_date"):
                    continue
                amount = row.get("amount")
                turnover = row.get("turnover_rate")
                bars[(str(row["symbol"]), str(row["trade_date"])[:10])] = (
                    None if amount is None else float(amount),
                    None if turnover is None else float(turnover),
                )
    enriched_count = 0
    amount_count = 0
    turnover_count = 0
    output: list[TrainingSample] = []
    for sample in samples:
        features = dict(sample.features)
        amount, turnover = bars.get((sample.symbol, sample.as_of_date.isoformat()), (None, None))
        changed = False
        if features.get("amount_1d") is None and amount is not None and amount >= 0:
            features["amount_1d"] = amount
            amount_count += 1
            changed = True
        if features.get("turnover_rate_1d") is None and turnover is not None and turnover >= 0:
            features["turnover_rate_1d"] = turnover
            turnover_count += 1
            changed = True
        if changed:
            enriched_count += 1
            output.append(sample.model_copy(update={"features": features}))
        else:
            output.append(sample)
    return output, {
        "status": "complete",
        "mode": "research_only_same_date_standard_bar_join",
        "standard_manifest_count": manifest_count,
        "standard_partition_count": partition_count,
        "loaded_liquidity_bar_count": len(bars),
        "sample_count": len(samples),
        "enriched_sample_count": enriched_count,
        "amount_1d_enriched_count": amount_count,
        "turnover_rate_1d_enriched_count": turnover_count,
        "missing_liquidity_is_preserved": True,
    }


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
    # Keep raw rows until period-end selection is complete.  The research
    # manifest contains roughly one million daily rows; validating every row
    # with Pydantic before discarding all but one row per symbol/quarter is a
    # large, avoidable cost.  We still validate the selected rows below before
    # they enter the canonical training pipeline.
    selected: dict[tuple[str, object], dict] = {}
    try:
        from investment_research.service.object_store import LocalObjectStore
        from investment_research.training.parquet_store import PITParquetStore
        parquet_store = PITParquetStore(LocalObjectStore(object_store))
    except ImportError:
        parquet_store = None
    def consider_rows(rows) -> None:
        """Select period-end raw rows without retaining a whole partition set."""
        for row in rows:
            if isinstance(row, dict) and "labels" in row and "features" in row:
                row = dict(row)
                raw_date = row.get("as_of_date")
                if raw_date is None:
                    continue
                if isinstance(raw_date, date):
                    as_of_date = raw_date
                else:
                    try:
                        as_of_date = date.fromisoformat(str(raw_date)[:10])
                    except ValueError:
                        continue
                symbol = str(row.get("symbol") or "")
                if not symbol:
                    continue
                period = _period_key(as_of_date, snapshot_frequency)
                key = (symbol, period)
                previous = selected.get(key)
                previous_date = previous.get("as_of_date") if previous else None
                if previous is None or str(raw_date)[:10] > str(previous_date)[:10]:
                    selected[key] = row

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
                    rows = parquet_store.read_partition_columns(
                        payload["sample_parquet_ref"],
                        columns=_SAMPLE_LOAD_COLUMNS,
                        expected_payload_hash=payload.get("payload_hash"),
                    )
                elif isinstance(payload, dict) and "sample_manifests" in payload:
                    for value in payload["sample_manifests"]:
                        manifest_path = Path(value)
                        if not manifest_path.is_absolute():
                            manifest_path = PROJECT / manifest_path
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if parquet_store is None:
                            raise SystemExit("manifest input requires the local PIT parquet dependencies")
                        consider_rows(parquet_store.read_partition_columns(
                            manifest["sample_parquet_ref"],
                            columns=_SAMPLE_LOAD_COLUMNS,
                            expected_payload_hash=manifest.get("payload_hash"),
                        ))
                    continue
                else:
                    rows = payload if isinstance(payload, list) else payload.get("samples", []) if isinstance(payload, dict) else []
        else:
            continue
        consider_rows(rows)
    validated: list[TrainingSample] = []
    for row in selected.values():
        for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
            if isinstance(row.get(key), str):
                row[key] = json.loads(row[key])
        validated.append(TrainingSample.model_validate(row))
    return sorted(validated, key=lambda item: (item.as_of_date, item.symbol))


def _period_key(value, frequency: str):
    from datetime import date
    if frequency == "monthly":
        return date(value.year, value.month, 1)
    quarter = (value.month - 1) // 3
    return date(value.year, quarter * 3 + 1, 1)


def _write_blocked(path: Path, reasons: list[str], **details) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "long-term-training-report-v1",
        "status": "blocked",
        "deployment_ready": False,
        "blocking_reasons": sorted(set(reasons)),
        **details,
    }
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
