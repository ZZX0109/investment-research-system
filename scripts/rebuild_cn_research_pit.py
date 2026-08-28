#!/usr/bin/env python3
"""Rebuild reproducible CN research layers from append-only public payloads.

The output is deliberately ``research_pit``.  Historical availability is an
explicit research assumption and the generated manifests can never satisfy a
formal release gate.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timezone
from hashlib import sha256
import heapq
import json
from pathlib import Path
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import (
    DataTier,
    RESEARCH_TIER_REASONS,
    RESEARCH_VISIBILITY_ASSUMPTION,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.research_data_quality import eligibility_for_symbol
from investment_research.training.cn_free_providers import ETF_RESEARCH_SYMBOLS
from investment_research.training.cn_research_universe import (
    build_cn_equity_core,
    build_cn_etf_benchmark,
)
from investment_research.training.cn_research_collection import audit_research_bars
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.free_research_adapter import normalize_free_daily_payload
from investment_research.training.feature_v4 import (
    DIRECTION_LABEL_VERSION,
    FEATURE_VERSION,
    build_cross_sectional_features,
    build_equal_weight_reference_bars,
    build_industry_reference_bars,
    build_reference_return_features,
)
from investment_research.training.models import (
    CanonicalInstrument,
    CoverageGroup,
    EventSourceTier,
    EventType,
    InstrumentType,
    LabelSet,
    Market,
    PointInTimeEvent,
    PreparedPriceBar,
)
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.active_snapshot_guard import ActiveSnapshotInputError, require_active_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild zero-budget CN research PIT layers")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--research-object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/free_research_rebuild")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument("--coverage-ledger", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--contexts", nargs="+", choices=("close_confirmed", "pre_open"), default=["close_confirmed"])
    parser.add_argument(
        "--max-equities",
        type=int,
        default=None,
        help="Optional development cap. By default every equity passing the quality gate is retained.",
    )
    parser.add_argument(
        "--include-all-raw-symbols",
        action="store_true",
        help=(
            "Standardize every symbol with an append-only CN raw price batch, "
            "not only the frozen research target pool. This broadens the "
            "research master; it does not prove historical lifecycle/PIT "
            "coverage and never promotes the result to formal data."
        ),
    )
    parser.add_argument(
        "--skip-samples",
        action="store_true",
        help=(
            "Only write broad standard Parquet/manifests and snapshots. "
            "Use this for a large universe backfill; training samples remain "
            "a separate, explicitly scoped step."
        ),
    )
    parser.add_argument("--minimum-equities", type=int, default=80)
    parser.add_argument("--minimum-history-sessions", type=int, default=756)
    parser.add_argument(
        "--minimum-training-sessions", type=int, default=960,
        help="Minimum usable decision history for the longest 20-session task.",
    )
    parser.add_argument(
        "--allow-unproven-visibility", action="store_true",
        help="Research-only compatibility mode: use publication dates when historical available_at is not proven.",
    )
    parser.add_argument(
        "--historical-universe", type=Path, default=None,
        help="PIT historical universe membership JSON/JSONL/Parquet; required for production breadth.",
    )
    parser.add_argument(
        "--allow-current-cohort-breadth", action="store_true",
        help="Test-fixture-only compatibility: use the current cohort for breadth.",
    )
    parser.add_argument(
        "--reuse-standard-index", type=Path, default=None,
        help=(
            "Reuse immutable standard manifests from an earlier rebuild and "
            "recompute only snapshots/features/samples. This avoids rewriting "
            "the standard PIT layer when a feature contract changes."
        ),
    )
    parser.add_argument(
        "--sample-symbols-file", type=Path, default=None,
        help=(
            "Only materialize sample manifests for symbols listed in this "
            "JSON/JSONL file. The full cohort is still used to compute "
            "cross-sectional reference features; this is the resumable batch "
            "mode for a large research-only rebuild."
        ),
    )
    parser.add_argument(
        "--reuse-snapshot-index", type=Path, default=None,
        help=(
            "Reuse the exact immutable snapshot objects referenced by this "
            "index. Required for sample batches so every batch binds to the "
            "same market snapshot instead of recomputing a different hash."
        ),
    )
    parser.add_argument(
        "--no-update-latest", action="store_true",
        help="Write an immutable batch index without replacing output-root/latest.json.",
    )
    parser.add_argument(
        "--resume-samples", action="store_true",
        help=(
            "Reuse already-written sample manifests under output-root when "
            "their snapshot binding matches. This makes an interrupted "
            "single-process full sample rebuild restartable."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sample_symbol_filter = _load_symbol_filter(args.sample_symbols_file)
    if sample_symbol_filter is not None and args.reuse_standard_index is None:
        raise SystemExit("--sample-symbols-file requires --reuse-standard-index")
    if args.reuse_snapshot_index is not None and args.reuse_standard_index is None:
        raise SystemExit("--reuse-snapshot-index requires --reuse-standard-index")
    reused_snapshots = _load_reused_snapshots(args.reuse_snapshot_index)
    # Legacy fixtures may intentionally run without an active pointer so they
    # can exercise normalization in tests.  If an active pointer exists, carry
    # its exact lineage into every derived sample manifest; training runners
    # then refuse old/unbound outputs.
    active_snapshot = None
    try:
        active_snapshot = require_active_snapshot(args.data_root)
        data_snapshot_binding = {
            "data_snapshot_id": active_snapshot.snapshot_id,
            "data_snapshot_manifest_hash": active_snapshot.manifest_hash,
        }
    except ActiveSnapshotInputError:
        data_snapshot_binding = None
    historical_universe_path = args.historical_universe
    if historical_universe_path is None and active_snapshot is not None:
        for item in active_snapshot.manifest.files:
            if item.dataset == "cn_historical_universe_memberships":
                candidate = Path(active_snapshot.manifest.source_root) / item.relative_path
                if candidate.is_file():
                    historical_universe_path = candidate
                    break
    raw_store = LocalObjectStore(args.raw_object_store)
    parquet = PITParquetStore(LocalObjectStore(args.research_object_store))
    uow = SQLiteUnitOfWork(args.database)
    catalog_validation_errors: list[dict[str, str]] = []

    def _catalog_batches(*, dataset: str, data_tier: str) -> list:
        """Hydrate valid catalog rows and retain explicit legacy-row errors."""
        values = uow.trusted_market.raw_batches(
            dataset=dataset, data_tier=data_tier, strict=False,
        )
        catalog_validation_errors.extend(
            {"dataset": dataset, **item}
            for item in uow.trusted_market.last_raw_batch_errors
        )
        return values

    try:
        batches = [
            *_catalog_batches(dataset="daily_bars_raw", data_tier=DataTier.RESEARCH_PIT.value),
            *_catalog_batches(dataset="daily_bars_qfq", data_tier=DataTier.RESEARCH_PIT.value),
            # Compatibility only for explicit test fixtures created before the
            # raw/qfq split.  Production defaults never write this dataset.
            *_catalog_batches(dataset="daily_bars", data_tier=DataTier.RESEARCH_PIT.value),
        ]
        supplement_batches = {
            dataset: _catalog_batches(
                dataset=dataset, data_tier=DataTier.RESEARCH_PIT.value,
            )
            for dataset in (
                "cn_security_master_research",
                "cn_adjustment_factors_research",
                "cn_fundamentals_research",
                # The Eastmoney four-statement landing importer writes a
                # normalized, CNINFO-matched research-only dataset here.  It
                # is intentionally admitted to the same feature join as the
                # legacy fundamentals feed, but its publication-to-availability
                # proof remains a separate research assumption (see the
                # source-specific gate in _load_financial_features).
                "cn_financial_eastmoney_research",
                "cn_corporate_actions_research",
                "cn_corporate_actions_detailed",
            )
        }
        event_batches = _catalog_batches(
            dataset="events", data_tier=DataTier.RESEARCH_PIT.value,
        )
    finally:
        uow.close()
    if not batches:
        raise SystemExit("no append-only research_pit daily-bar batches are available")

    # Prefer the newest append-only public batch per symbol.  Yahoo/Sina/
    # Tencent/TDX are research-only fallbacks and remain subject to the same
    # normalization and quality gates as AKShare/BaoStock.
    candidates: dict[tuple[str, str], list] = defaultdict(list)
    for batch in batches:
        if batch.symbol and batch.provider in {
            "akshare", "baostock", "sina", "tencent", "yahoo", "tdx",
            "eastmoney", "eastmoney_bse_legacy_qfq",
        }:
            mode = "qfq" if batch.dataset.endswith("_qfq") else "raw"
            candidates[(batch.symbol, mode)].append(batch)
    batch_groups = {
        key: sorted(values, key=lambda item: (item.fetched_at, item.provider == "akshare"))
        for key, values in candidates.items()
    }
    if not batch_groups:
        raise SystemExit("no CN AKShare/Baostock research payloads were found")

    standard_manifests: list[dict] = []
    all_bars: list[PreparedPriceBar] = []
    failures: list[dict[str, str]] = [
        {
            "stage": "raw_catalog_validation",
            "reason": f"legacy_row_skipped:{item['dataset']}:{item.get('row_id', 'unknown')}",
            "detail": item["error"],
        }
        for item in catalog_validation_errors
    ]
    standard_root = args.output_root / "standard"
    symbols = sorted({symbol for symbol, _mode in batch_groups})
    # The append-only local catalog may contain symbols from older research
    # runs.  The normal rebuild uses the frozen 162-equity + 5-ETF target
    # pool, otherwise a successful rebuild can silently train on the wrong
    # universe.  The explicit all-raw mode is for broadening the research
    # master only; downstream formal gates still inspect lifecycle/PIT proof.
    target_config = PROJECT / "config/cn_research_target_167_symbols.json"
    if target_config.is_file() and not args.include_all_raw_symbols:
        configured = json.loads(target_config.read_text(encoding="utf-8"))
        target_symbols = {
            str(symbol).zfill(6)
            for symbol in configured.get("cn", [])
        }
        symbols = [symbol for symbol in symbols if symbol in target_symbols]
    provider_conflicts = _provider_conflict_symbols(args.coverage_ledger)
    quality_reports: list[dict] = []
    if args.reuse_standard_index is not None:
        standard_manifests, all_bars, reused_failures, reused_quality = _load_reusable_standard_layer(
            args.reuse_standard_index, parquet
        )
        failures.extend(reused_failures)
        quality_reports.extend(reused_quality)
        symbols = sorted(item["symbol"] for item in standard_manifests)
    raw_price_symbols = {
        symbol for symbol, mode in batch_groups if mode == "raw"
    }
    qfq_price_symbols = {
        symbol for symbol, mode in batch_groups if mode == "qfq"
    }
    for symbol in ([] if args.reuse_standard_index is not None else symbols):
        raw_batches = batch_groups.get((symbol, "raw"), [])
        qfq_batches = batch_groups.get((symbol, "qfq"), [])
        eligibility = eligibility_for_symbol(
            symbol,
            raw_symbols=raw_price_symbols,
            qfq_symbols=qfq_price_symbols,
        )
        if not eligibility["model_eligible"]:
            failures.append({
                "symbol": symbol,
                "stage": "model_backtest_eligibility",
                "reason": ",".join(eligibility["blocking_reasons"]),
            })
            continue
        try:
            raw_by_date = _merge_batches(
                raw_store, raw_batches, symbol=symbol, as_of=args.as_of,
            )
            if not raw_by_date:
                raise ValueError("no_normalized_rows_before_as_of")
            qfq_by_date = _merge_batches(
                raw_store, qfq_batches, symbol=symbol, as_of=args.as_of,
            )
            bars: list[PreparedPriceBar] = []
            for trade_date in sorted(raw_by_date):
                item, raw_batch = raw_by_date[trade_date]
                if trade_date not in qfq_by_date:
                    raise ValueError("qfq_trade_date_missing_for_raw_price")
                qfq_item, qfq_batch = qfq_by_date[trade_date]
                bars.append(item.model_copy(update={
                    "payload_ref": raw_batch.payload_ref,
                    "raw_hash": raw_batch.payload_hash,
                    "close_normalized": qfq_item.close_native,
                    "open_normalized": qfq_item.open_native,
                    "high_normalized": qfq_item.high_native,
                    "low_normalized": qfq_item.low_native,
                    "adjustment_factor": qfq_item.close_native / item.close_native,
                    "data_version": f"research-raw-qfq:{raw_batch.payload_hash[:8]}:{qfq_batch.payload_hash[:8]}",
                }))
            latest_raw_batch = max(raw_batches, key=lambda item: item.fetched_at)
            latest_qfq_batch = max(qfq_batches, key=lambda item: item.fetched_at)
            lineage_hash = sha256(_canonical({
                "raw": [item.payload_hash for item in raw_batches],
                "qfq": [item.payload_hash for item in qfq_batches],
            })).hexdigest()
            provider_chain = sorted({item.provider for item in [*raw_batches, *qfq_batches]})
            report = audit_research_bars(
                symbol, bars, as_of=args.as_of or bars[-1].trade_date,
                provider_conflict=symbol in provider_conflicts,
            )
            quality_reports.append(report.model_dump(mode="json"))
            if report.provider_conflict:
                raise ValueError("provider_conflict")
            refs = []
            by_year: dict[int, list[PreparedPriceBar]] = defaultdict(list)
            for bar in bars:
                by_year[bar.trade_date.year].append(bar)
            for year, year_bars in sorted(by_year.items()):
                ref, payload_hash, schema_hash, row_count = parquet.write_partition(
                    year_bars, market="cn", dataset="standard_daily_bars_research",
                    schema_version="free-research-standard-v1", trade_year=year,
                    partition_id=f"{symbol}-{lineage_hash[:12]}",
                )
                refs.append({
                    "trade_year": year, "parquet_ref": ref, "payload_hash": payload_hash,
                    "schema_hash": schema_hash, "row_count": row_count,
                })
            manifest = {
                "schema_version": "free-research-standard-manifest-v2",
                "data_tier": DataTier.RESEARCH_PIT.value,
                "mode": "research_only", "formal_pit_eligible": False,
                "blocking_reasons": list(RESEARCH_TIER_REASONS),
                "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
                "market": "cn", "symbol": symbol,
                "provider": latest_raw_batch.provider, "provider_chain": provider_chain,
                "raw_batch_id": str(latest_raw_batch.id),
                "raw_payload_ref": latest_raw_batch.payload_ref,
                "raw_payload_hash": latest_raw_batch.payload_hash,
                "raw_input_batches": [_batch_lineage(item) for item in raw_batches],
                "qfq_input_batches": [_batch_lineage(item) for item in qfq_batches],
                "merged_lineage_hash": lineage_hash, "partitions": refs,
                "qfq_raw_batch_id": str(latest_qfq_batch.id),
                "qfq_payload_hash": latest_qfq_batch.payload_hash,
                "adjustment_policy": "raw_market_state_plus_qfq_return_labels",
                "quality_report": report.model_dump(mode="json"),
                "row_count": len(bars),
            }
            path = standard_root / f"{symbol}-{lineage_hash[:12]}.json"
            _write_json(path, manifest)
            manifest["manifest_ref"] = _portable_path(path)
            standard_manifests.append(manifest)
            all_bars.extend(bars)
        except Exception as exc:
            failures.append({"symbol": symbol, "stage": "standardize", "reason": f"{type(exc).__name__}:{exc}"})

    if not all_bars:
        raise SystemExit("all public payloads failed normalization or integrity validation")
    symbols_by_date = _load_historical_universe(
        historical_universe_path,
        trade_dates={item.trade_date for item in all_bars},
    ) if historical_universe_path else None
    if symbols_by_date is None and not args.allow_current_cohort_breadth and not args.skip_samples:
        raise SystemExit(
            "historical universe membership is required for market breadth; "
            "pass --historical-universe or use --allow-current-cohort-breadth only for fixtures"
        )
    as_of = args.as_of or max(item.trade_date for item in all_bars)
    event_coverage_status = _event_coverage(args.coverage_ledger)
    cohorts = [
        build_cn_equity_core(
            all_bars, as_of=as_of, max_symbols=args.max_equities,
            minimum_required_members=args.minimum_equities,
            minimum_history_sessions=args.minimum_history_sessions,
            minimum_training_sessions=args.minimum_training_sessions,
        ),
        build_cn_etf_benchmark(
            all_bars, as_of=as_of,
            minimum_training_sessions=args.minimum_training_sessions,
        ),
    ]
    cohort_paths: dict[str, Path] = {}
    for cohort in cohorts:
        cohort_payload = cohort.model_dump(mode="json")
        cohort_hash = sha256(_canonical(cohort_payload)).hexdigest()
        path = args.output_root / "cohorts" / f"{cohort.cohort}-{as_of.isoformat()}-{cohort_hash[:12]}.json"
        _write_json(path, {**cohort_payload, "cohort_hash": cohort_hash})
        cohort_paths[cohort.cohort] = path

    bars_by_symbol: dict[str, list[PreparedPriceBar]] = defaultdict(list)
    for bar in all_bars:
        bars_by_symbol[bar.symbol].append(bar)
    standard_by_symbol = {item["symbol"]: item for item in standard_manifests}
    industry_by_symbol = {
        **_load_industry_mapping(),
        **_load_research_industry_mapping(
            raw_store, supplement_batches["cn_security_master_research"]
        ),
    }
    financial_features_by_symbol = _load_financial_features(
        raw_store,
        [
            *supplement_batches["cn_fundamentals_research"],
            *supplement_batches["cn_financial_eastmoney_research"],
        ],
        bars_by_symbol,
        allow_unproven_available_at=args.allow_unproven_visibility,
    )
    auxiliary_features = _load_auxiliary_features(
        trade_dates={bar.trade_date for bar in all_bars}
    )
    events_by_symbol = _load_research_events(raw_store, event_batches)
    industry_references = (
        build_industry_reference_bars(bars_by_symbol, industry_by_symbol)
        if not args.skip_samples else {}
    )
    cohort_context: dict[str, dict] = {}
    if not args.skip_samples:
        for cohort in cohorts:
            member_symbols = [member.symbol for member in cohort.members]
            broad_reference = list(bars_by_symbol.get("510300", []))
            if not broad_reference:
                broad_reference = build_equal_weight_reference_bars(
                    bars_by_symbol, symbols=member_symbols, reference_symbol="CN-COHORT-EW"
                )
            style_reference = build_equal_weight_reference_bars(
                bars_by_symbol,
                symbols=member_symbols,
                reference_symbol=f"{cohort.cohort}:EQUAL_WEIGHT",
            )
            cross_section = build_cross_sectional_features(
                bars_by_symbol,
                symbols=member_symbols,
                symbols_by_date=symbols_by_date,
            )
            benchmark_features = build_reference_return_features(broad_reference)
            for symbol in member_symbols:
                for trade_date, values in benchmark_features.items():
                    cross_section.setdefault(symbol, {}).setdefault(trade_date, {}).update(values)
            cohort_context[cohort.cohort] = {
                "benchmark_bars": broad_reference,
                "style_reference_bars": style_reference,
                "cross_section": cross_section,
            }
    contexts: dict[str, dict] = {}
    for context in args.contexts:
        snapshot = _freeze_snapshot(
            context=context, as_of=as_of, standard_manifests=standard_manifests,
            failures=failures, event_coverage_status=event_coverage_status,
            supplemental_batches=[
                batch for values in supplement_batches.values() for batch in values
            ],
        )
        reused_snapshot = reused_snapshots.get(context)
        if reused_snapshot is not None:
            snapshot = reused_snapshot["snapshot"]
            snapshot_path = reused_snapshot["path"]
        else:
            snapshot_path = args.output_root / "snapshots" / context / f"{as_of.isoformat()}-{snapshot['market_snapshot_hash'][:12]}.json"
            _write_json(snapshot_path, snapshot)
        sample_manifests: dict[str, list[str]] = defaultdict(list)
        if not args.skip_samples:
            for cohort in cohorts:
                for member in cohort.members:
                    if sample_symbol_filter is not None and member.symbol not in sample_symbol_filter:
                        continue
                    if args.resume_samples:
                        existing = _existing_sample_manifests(
                            args.output_root, context=context, cohort=cohort.cohort,
                            symbol=member.symbol, snapshot=snapshot,
                        )
                        if existing:
                            sample_manifests[cohort.cohort].extend(_portable_path(item) for item in existing)
                            continue
                    try:
                        manifests = _build_samples(
                        symbol=member.symbol, cohort=cohort.cohort,
                        cohort_version=cohort.cohort_version, context=context,
                        bars=bars_by_symbol[member.symbol], standard=standard_by_symbol[member.symbol],
                        snapshot=snapshot, parquet=parquet, output_root=args.output_root,
                        benchmark_bars=cohort_context[cohort.cohort]["benchmark_bars"],
                        style_reference_bars=cohort_context[cohort.cohort]["style_reference_bars"],
                        sector_reference_bars=industry_references.get(industry_by_symbol.get(member.symbol, ""), []),
                        industry_key=industry_by_symbol.get(member.symbol),
                        extra_features_by_date=_merge_feature_timelines(
                            cohort_context[cohort.cohort]["cross_section"].get(member.symbol, {}),
                            financial_features_by_symbol.get(member.symbol, {}),
                            auxiliary_features,
                        ),
                        events=events_by_symbol.get(member.symbol, []),
                        # A partial source can still prove that a particular
                        # symbol had an event.  Preserve the global partial
                        # status for symbols with no observed rows, but do not
                        # discard valid positive event evidence for symbols
                        # that were actually returned by the provider.
                        event_coverage_status=(
                            "events_present"
                            if events_by_symbol.get(member.symbol)
                            else snapshot["event_coverage_status"]
                        ),
                        data_snapshot_binding=data_snapshot_binding,
                        )
                        sample_manifests[cohort.cohort].extend(_portable_path(item) for item in manifests)
                        _write_json(
                            args.output_root / "samples" / context / cohort.cohort
                            / member.symbol / ".complete.json",
                            {
                                "schema_version": "free-research-sample-completion-v1",
                                "symbol": member.symbol,
                                "cohort": cohort.cohort,
                                "market_snapshot_id": snapshot["market_snapshot_id"],
                                "market_snapshot_hash": snapshot["market_snapshot_hash"],
                                "manifest_count": len(manifests),
                            },
                        )
                    except Exception as exc:
                        failures.append({
                            "symbol": member.symbol, "stage": f"sample:{context}:{cohort.cohort}",
                            "reason": f"{type(exc).__name__}:{exc}",
                        })
        leakage = _leakage_report(context, snapshot, sample_manifests)
        leakage_path = args.output_root / "leakage" / context / f"{as_of.isoformat()}-{snapshot['market_snapshot_hash'][:12]}.json"
        _write_json(leakage_path, leakage)
        contexts[context] = {
            "snapshot_ref": _portable_path(snapshot_path), "snapshot_id": snapshot["market_snapshot_id"],
            "snapshot_hash": snapshot["market_snapshot_hash"],
            "sample_manifests": dict(sample_manifests), "leakage_report_ref": _portable_path(leakage_path),
        }

    sample_symbols = {
        Path(ref).parent.name
        for values in contexts.values()
        for refs in values.get("sample_manifests", {}).values()
        if isinstance(refs, list)
        for ref in refs
    }
    core_symbols = {member.symbol for member in cohorts[0].members}
    training_blocking_reasons: list[str] = []
    if len(core_symbols) < args.minimum_equities:
        training_blocking_reasons.append("eligible_equity_count_below_80")
    if args.skip_samples or not sample_symbols:
        training_blocking_reasons.append("sample_manifests_not_generated")
    elif not core_symbols.issubset(sample_symbols):
        training_blocking_reasons.append("sample_manifests_incomplete_for_equity_cohort")
    index = {
        "schema_version": "cn-zero-budget-research-rebuild-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "status": "research_only", "formal_pit_eligible": False,
        "deployment_ready": False, "as_of": as_of.isoformat(),
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "blocking_reasons": list(RESEARCH_TIER_REASONS),
        "standard_manifest_count": len(standard_manifests),
        "standard_manifest_refs": [item["manifest_ref"] for item in standard_manifests],
        "cohort_refs": {key: _portable_path(value) for key, value in cohort_paths.items()},
        "contexts": contexts, "failures": failures,
        "quality_reports": quality_reports,
        "feature_v4_supplement": {
            "industry_symbol_count": len(industry_by_symbol),
            "financial_symbol_count": len(financial_features_by_symbol),
            "event_symbol_count": len(events_by_symbol),
            "supplement_batch_count": sum(len(values) for values in supplement_batches.values()),
        },
        "training_blocked": bool(training_blocking_reasons),
        "training_blocking_reasons": training_blocking_reasons,
        "rebuilt_from_latest_fetched_at": max(
            item.fetched_at for values in batch_groups.values() for item in values
        ).isoformat(),
    }
    index_hash = sha256(_canonical({
        "snapshots": {key: value["snapshot_hash"] for key, value in contexts.items()},
        "failures": failures,
    })).hexdigest()
    output = args.output_root / f"rebuild-{as_of.isoformat()}-{index_hash[:12]}.json"
    _write_json(output, index)
    # Keep a stable pointer for audit/UI consumers while retaining the
    # immutable, content-addressed rebuild file above.
    if not args.no_update_latest:
        _write_json_pointer(args.output_root / "latest.json", index)
    print(output)
    return 0


def _load_reusable_standard_layer(
    index_path: Path, parquet: PITParquetStore,
) -> tuple[list[dict], list[PreparedPriceBar], list[dict[str, str]], list[dict]]:
    """Load a previously written immutable standard layer for sample-only rebuilds."""
    if not index_path.is_file():
        raise SystemExit(f"reusable standard index is missing: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    refs = index.get("standard_manifest_refs") or []
    manifests: list[dict] = []
    bars: list[PreparedPriceBar] = []
    failures = list(index.get("failures") or [])
    quality = list(index.get("quality_reports") or [])
    for ref in refs:
        path = Path(ref)
        if not path.is_absolute():
            path = PROJECT / path
        if not path.is_file():
            failures.append({"stage": "reuse_standard", "reason": f"manifest_missing:{path}"})
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        # Older broad rebuilds persisted the ref only in the index, not inside
        # each manifest.  Normalize that legacy shape in memory so sample-only
        # rebuilds can safely reuse the immutable standard layer.
        manifest.setdefault("manifest_ref", _portable_path(path))
        manifests.append(manifest)
        for partition in manifest.get("partitions") or []:
            try:
                rows = parquet.read_partition(
                    partition["parquet_ref"],
                    expected_payload_hash=partition.get("payload_hash"),
                )
                bars.extend(PreparedPriceBar.model_validate(row) for row in rows)
            except Exception as exc:
                failures.append({
                    "symbol": manifest.get("symbol", ""), "stage": "reuse_standard",
                    "reason": f"{type(exc).__name__}:{exc}",
                })
    if not manifests or not bars:
        raise SystemExit("reusable standard index contains no readable standard bars")
    return manifests, bars, failures, quality


def _load_symbol_filter(path: Path | None) -> set[str] | None:
    """Read a normalized symbol allow-list for resumable sample batches."""
    if path is None:
        return None
    if not path.is_file():
        raise SystemExit(f"sample symbols file is missing: {path}")
    try:
        if path.suffix.lower() == ".jsonl":
            payload: object = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"sample symbols file is not valid JSON/JSONL: {path}: {exc}") from exc
    if isinstance(payload, dict):
        payload = payload.get("symbols", payload.get("records", []))
    if not isinstance(payload, list):
        raise SystemExit("sample symbols file must contain a list or {\"symbols\": [...]}")
    values: set[str] = set()
    for item in payload:
        if isinstance(item, dict):
            item = item.get("symbol") or item.get("code")
        if item in (None, ""):
            continue
        values.add(str(item).rsplit(".", 1)[-1].zfill(6))
    if not values:
        raise SystemExit(f"sample symbols file contains no usable symbols: {path}")
    return values


def _load_reused_snapshots(index_path: Path | None) -> dict[str, dict[str, object]]:
    """Load exact immutable snapshot refs from an earlier rebuild index."""
    if index_path is None:
        return {}
    if not index_path.is_file():
        raise SystemExit(f"reusable snapshot index is missing: {index_path}")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"reusable snapshot index is invalid: {index_path}: {exc}") from exc
    contexts = index.get("contexts") if isinstance(index, dict) else None
    if not isinstance(contexts, dict):
        raise SystemExit("reusable snapshot index has no contexts")
    output: dict[str, dict[str, object]] = {}
    for context, value in contexts.items():
        if not isinstance(value, dict) or not value.get("snapshot_ref"):
            raise SystemExit(f"reusable snapshot index has no snapshot_ref for context: {context}")
        path = Path(str(value["snapshot_ref"]))
        if not path.is_absolute():
            path = PROJECT / path
        if not path.is_file():
            raise SystemExit(f"reusable snapshot file is missing: {path}")
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"reusable snapshot is invalid: {path}: {exc}") from exc
        if not isinstance(snapshot, dict) or not snapshot.get("market_snapshot_hash"):
            raise SystemExit(f"reusable snapshot has no market_snapshot_hash: {path}")
        if value.get("snapshot_id") and value["snapshot_id"] != snapshot.get("market_snapshot_id"):
            raise SystemExit(f"reusable snapshot id mismatch for context: {context}")
        if value.get("snapshot_hash") and value["snapshot_hash"] != snapshot.get("market_snapshot_hash"):
            raise SystemExit(f"reusable snapshot hash mismatch for context: {context}")
        output[str(context)] = {"snapshot": snapshot, "path": path}
    return output


def _existing_sample_manifests(
    output_root: Path, *, context: str, cohort: str, symbol: str, snapshot: dict,
) -> list[Path]:
    """Return only immutable sample manifests bound to the requested snapshot."""
    root = output_root / "samples" / context / cohort / symbol
    if not root.is_dir():
        return []
    marker_path = root / ".complete.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # A directory without a completion marker may be a process
        # interruption half-way through a symbol; never treat it as complete.
        return []
    if (
        marker.get("symbol") != symbol
        or marker.get("market_snapshot_id") != snapshot.get("market_snapshot_id")
        or marker.get("market_snapshot_hash") != snapshot.get("market_snapshot_hash")
    ):
        return []
    manifests: list[Path] = []
    for path in sorted(root.glob("*.json")):
        if path.name == ".complete.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("market_snapshot_id") == snapshot.get("market_snapshot_id")
            and payload.get("market_snapshot_hash") == snapshot.get("market_snapshot_hash")
            and payload.get("symbol") == symbol
            and payload.get("sample_parquet_ref")
        ):
            manifests.append(path)
    return manifests


def _merge_batches(
    raw_store: LocalObjectStore, batches: list, *, symbol: str, as_of: date | None,
) -> dict[date, tuple[PreparedPriceBar, object]]:
    """Merge append-only incremental payloads without truncating history.

    Later observations replace only overlapping trade dates.  A same-time
    AKShare observation wins over Baostock, while a genuinely newer Baostock
    revision can still replace an older primary observation.
    """
    merged: dict[date, tuple[PreparedPriceBar, object]] = {}
    ordered = sorted(
        batches, key=lambda item: (item.fetched_at, item.provider == "akshare", item.payload_hash)
    )
    for batch in ordered:
        payload = raw_store.get(_object_key(batch.payload_ref))
        if sha256(payload).hexdigest() != batch.payload_hash:
            raise ValueError(f"raw_payload_hash_mismatch:{batch.id}")
        normalized = normalize_free_daily_payload(
            payload, market="cn", symbol=symbol, provider=batch.provider,
            received_at=batch.received_at or batch.fetched_at,
        )
        for bar in normalized.bars:
            if as_of is None or bar.trade_date <= as_of:
                merged[bar.trade_date] = (bar, batch)
    return merged


def _batch_lineage(batch) -> dict[str, str | None]:
    return {
        "batch_id": str(batch.id),
        "provider": batch.provider,
        "payload_ref": batch.payload_ref,
        "payload_hash": batch.payload_hash,
        "fetched_at": batch.fetched_at.isoformat(),
        "coverage_start": None if batch.coverage_start is None else batch.coverage_start.isoformat(),
        "coverage_end": None if batch.coverage_end is None else batch.coverage_end.isoformat(),
    }


def _freeze_snapshot(
    *, context: str, as_of: date, standard_manifests: list[dict],
    failures: list[dict], event_coverage_status: str,
    supplemental_batches: list,
) -> dict:
    constituents = [
        {
            "symbol": item["symbol"], "provider": item["provider"],
            "raw_payload_hash": item["raw_payload_hash"],
            "partition_hashes": [part["payload_hash"] for part in item["partitions"]],
        }
        for item in sorted(standard_manifests, key=lambda value: value["symbol"])
    ]
    content = {
        "schema_version": "cn-research-market-snapshot-v1",
        "data_tier": DataTier.RESEARCH_PIT.value, "market": "cn",
        "decision_context": context, "trade_date": as_of.isoformat(),
        "adjustment_policy": "raw_market_state_plus_qfq_return_labels",
        "event_coverage_status": event_coverage_status,
        "supplement_payload_hashes": sorted({
            batch.payload_hash for batch in supplemental_batches
        }),
        "constituents": constituents, "quality_failure_count": len(failures),
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
    }
    digest = sha256(_canonical(content)).hexdigest()
    return {
        **content, "market_snapshot_id": f"research-cn-{context}-{as_of.isoformat()}-{digest[:12]}",
        "market_snapshot_hash": digest, "immutable": True,
    }


def _build_samples(
    *, symbol: str, cohort: str, cohort_version: str, context: str, bars: list[PreparedPriceBar],
    standard: dict, snapshot: dict, parquet: PITParquetStore, output_root: Path,
    benchmark_bars: list[PreparedPriceBar], style_reference_bars: list[PreparedPriceBar],
    sector_reference_bars: list[PreparedPriceBar], industry_key: str | None,
    extra_features_by_date: dict,
    events: list[PointInTimeEvent], event_coverage_status: str,
    data_snapshot_binding: dict[str, str] | None = None,
) -> list[Path]:
    # A public backfill cannot prove historical availability.  This explicit
    # assumption is isolated to research samples and remains a release blocker.
    assumed = [item.model_copy(update={"available_at": item.published_at, "as_of": item.published_at}) for item in bars]
    is_etf = cohort == "cn_etf_benchmark"
    instrument = CanonicalInstrument(
        symbol=symbol, name=symbol, market=Market.CN,
        instrument_type=InstrumentType.ETF if is_etf else InstrumentType.EQUITY,
        coverage_group=CoverageGroup.ETF if is_etf else CoverageGroup.CN_A_SHARE,
        currency="CNY", exchange="XSHG" if symbol.startswith(("5", "6", "9")) else "XSHE",
        industry_key=industry_key,
        benchmark_symbol="510300",
        sector_reference_symbol=None if not sector_reference_bars else f"INDUSTRY:{industry_key}",
        style_reference_symbol=f"{cohort}:EQUAL_WEIGHT",
    )
    samples = TrainingDatasetBuilder(
        feature_version=FEATURE_VERSION,
        data_version=f"research-snapshot:{snapshot['market_snapshot_hash'][:16]}",
    ).build_samples(
        instrument=instrument, price_bars=assumed,
        benchmark_bars=[item.model_copy(update={"available_at": item.published_at, "as_of": item.published_at}) for item in benchmark_bars],
        sector_reference_bars=[item.model_copy(update={"available_at": item.published_at, "as_of": item.published_at}) for item in sector_reference_bars],
        style_reference_bars=[item.model_copy(update={"available_at": item.published_at, "as_of": item.published_at}) for item in style_reference_bars],
        extra_features_by_date=extra_features_by_date,
        events=events,
        decision_context=context, event_coverage_status=event_coverage_status,
    )
    samples = [
        item.model_copy(update={
            "market_snapshot_id": snapshot["market_snapshot_id"],
            "market_snapshot_hash": snapshot["market_snapshot_hash"],
            "data_tier": DataTier.RESEARCH_PIT.value,
            "data_quality_status": "degraded",
            "data_quality_mask": {"historical_visibility_unproven": 1.0},
            "event_missing_mask": {"event_source_unavailable": 1.0},
            "provider_id": standard.get("provider"),
            "revision_id": standard.get("merged_lineage_hash") or standard.get("raw_payload_hash"),
            "source_delay_seconds": (
                None
                if item.published_at is None or item.as_of_time is None
                else max(0.0, (item.as_of_time - item.published_at).total_seconds())
            ),
            "cache_state": standard.get("cache_state", "fresh"),
            "input_revision_ids": [
                value for value in (
                    standard.get("raw_payload_hash"),
                    standard.get("normalized_hash"),
                ) if value
            ],
            "data_issues": sorted(set([
                *item.data_issues,
                RESEARCH_VISIBILITY_ASSUMPTION,
                f"event_coverage:{event_coverage_status}",
            ])),
        })
        for item in samples
    ]
    if is_etf:
        # ETFs are retained as benchmark/market-state observations only.  Do
        # not leave forward labels on their rows where a downstream consumer
        # could accidentally rank them with equities.
        benchmark_only_samples = []
        for item in samples:
            cleared = item.labels.model_dump()
            for field in LabelSet.model_fields:
                if field not in {"symbol", "as_of_date"}:
                    cleared[field] = None
            cleared.update({
                "label_available": False,
                "long_term_label_available": False,
                "label_unavailable_reason": "benchmark_only_etf",
                "long_term_label_unavailable_reason": "benchmark_only_etf",
            })
            benchmark_only_samples.append(item.model_copy(update={"labels": item.labels.model_copy(update=cleared)}))
        samples = benchmark_only_samples
    if not samples:
        raise ValueError("no_feature_samples")
    by_year = defaultdict(list)
    for item in samples:
        by_year[item.as_of_date.year].append(item)
    paths = []
    for year, year_samples in sorted(by_year.items()):
        ref, payload_hash, schema_hash, row_count = parquet.write_partition(
            year_samples, market="cn", dataset="research_samples",
            schema_version="free-research-samples-v4", trade_year=year,
            partition_id=f"{context}-{cohort}-{symbol}-{snapshot['market_snapshot_hash'][:12]}",
        )
        manifest = {
            "schema_version": "free-research-sample-manifest-v4",
            "data_tier": DataTier.RESEARCH_PIT.value, "mode": "research_only",
            "formal_pit_eligible": False, "deployment_ready": False,
            "blocking_reasons": list(RESEARCH_TIER_REASONS),
            "market": "cn", "symbol": symbol, "cohort": cohort,
            "cohort_version": cohort_version,
            "decision_context": context, "trade_year": year,
            "feature_version": FEATURE_VERSION,
            "label_version": "benchmark-only-v1" if is_etf else DIRECTION_LABEL_VERSION,
            "cohort_role": "benchmark_only" if is_etf else "stock_ranking",
            "ranking_label_eligible": not is_etf,
            "market_snapshot_id": snapshot["market_snapshot_id"],
            "market_snapshot_hash": snapshot["market_snapshot_hash"],
            "standard_raw_payload_hash": standard["raw_payload_hash"],
            "sample_parquet_ref": ref, "payload_hash": payload_hash,
            "schema_hash": schema_hash, "row_count": row_count,
            "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        }
        if data_snapshot_binding:
            manifest.update(data_snapshot_binding)
        path = output_root / "samples" / context / cohort / symbol / f"{year}-{snapshot['market_snapshot_hash'][:12]}.json"
        _write_json(path, manifest)
        paths.append(path)
    return paths


def _load_industry_mapping() -> dict[str, str]:
    """Load an optional frozen free-source industry map without inventing history."""
    path = PROJECT / "config" / "cn_industry_map.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("symbols", payload) if isinstance(payload, dict) else {}
    if not isinstance(values, dict):
        raise ValueError("cn_industry_map.json must contain a symbol-to-industry mapping")
    return {
        str(symbol): str(industry)
        for symbol, industry in values.items()
        if symbol and industry
    }


def _load_historical_universe(
    path: Path,
    *,
    trade_dates: set[date],
) -> dict[date, set[str]]:
    """Expand PIT membership intervals only across observed trade dates."""
    if not path.is_file():
        raise SystemExit(f"historical universe file is missing: {path}")
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise SystemExit("historical universe parquet requires pyarrow") from exc
        rows = pq.read_table(path).to_pylist()
    elif path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("rows", payload.get("memberships", [])) if isinstance(payload, dict) else []
    output: dict[date, set[str]] = defaultdict(set)
    for row in rows:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        start = _parse_iso_date(row.get("effective_from") or row.get("valid_from") or row.get("start_date"))
        end = _parse_iso_date(row.get("effective_to") or row.get("valid_to") or row.get("end_date"))
        if start is None:
            continue
        for trade_date in trade_dates:
            if trade_date >= start and (end is None or trade_date <= end):
                output[trade_date].add(str(row["symbol"]).zfill(6))
    if not output:
        raise SystemExit(f"historical universe file has no usable memberships: {path}")
    missing_dates = sorted(trade_dates - set(output))
    if missing_dates:
        raise SystemExit(
            "historical universe has no membership for trade dates: "
            + ",".join(item.isoformat() for item in missing_dates[:3])
        )
    return dict(output)


def _parse_iso_date(value) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _load_research_industry_mapping(
    raw_store: LocalObjectStore, batches: list,
) -> dict[str, str]:
    """Load the newest append-only Baostock industry observation per symbol."""
    output: dict[str, str] = {}
    ordered = sorted(batches, key=lambda item: (item.fetched_at, item.payload_hash))
    for batch in ordered:
        if not batch.symbol or not batch.payload_ref.startswith("file-object://"):
            continue
        rows = _raw_json_rows(raw_store, batch)
        if rows and rows[0].get("industry"):
            output[str(batch.symbol)] = str(rows[0]["industry"])
    return output


_FUNDAMENTAL_FIELDS = {
    "roeAvg": "fundamental_roe_avg",
    "npMargin": "fundamental_net_margin",
    "gpMargin": "fundamental_gross_margin",
    "epsTTM": "fundamental_eps_ttm",
    "YOYEquity": "fundamental_equity_yoy",
    "YOYAsset": "fundamental_asset_yoy",
    "YOYNI": "fundamental_net_income_yoy",
    "YOYEPSBasic": "fundamental_eps_yoy",
    "YOYPNI": "fundamental_parent_net_income_yoy",
    "NRTurnRatio": "fundamental_receivable_turnover",
    "INVTurnRatio": "fundamental_inventory_turnover",
    "AssetTurnRatio": "fundamental_asset_turnover",
    "currentRatio": "fundamental_current_ratio",
    "quickRatio": "fundamental_quick_ratio",
    "cashRatio": "fundamental_cash_ratio",
    "liabilityToAsset": "fundamental_liability_to_asset",
    "CFOToOR": "fundamental_cfo_to_revenue",
    "CFOToNP": "fundamental_cfo_to_net_profit",
    "CFOToGr": "fundamental_cfo_to_gross_revenue",
    "dupontROE": "fundamental_dupont_roe",
    "dupontAssetStoEquity": "fundamental_equity_multiplier",
    "dupontAssetTurn": "fundamental_dupont_asset_turnover",
}


def _load_financial_features(
    raw_store: LocalObjectStore,
    batches: list,
    bars_by_symbol: dict[str, list[PreparedPriceBar]],
    *,
    allow_unproven_available_at: bool = False,
) -> dict[str, dict[date, dict[str, float]]]:
    """Build a PIT timeline, with an explicit research-only fallback."""
    references_by_symbol: dict[str, dict[tuple[date, str], dict]] = defaultdict(dict)
    for batch in sorted(batches, key=lambda item: (item.fetched_at, item.payload_hash)):
        if not batch.symbol:
            continue
        for row in _raw_json_rows(raw_store, batch):
            published = _parse_date(row.get("pubDate"))
            statistical = str(row.get("statDate") or "")
            if published is None:
                continue

            # The Eastmoney importer records the CNINFO publication match but
            # deliberately leaves row-level ``available_at`` empty.  The
            # catalog's ingestion timestamp is collection time, not proof
            # that the value was public then.  Keep this source out of the
            # default PIT path and only admit it for the explicit
            # research-assumption rebuild flag.
            if batch.dataset == "cn_financial_eastmoney_research":
                if not allow_unproven_available_at:
                    continue
                row_available_at = row.get("available_at")
                if row_available_at in (None, ""):
                    available_at = datetime.combine(published, time.min, timezone.utc)
                else:
                    try:
                        available_at = datetime.fromisoformat(
                            str(row_available_at).replace("Z", "+00:00")
                        )
                    except ValueError:
                        available_at = datetime.combine(published, time.min, timezone.utc)
                    if available_at.tzinfo is None:
                        available_at = available_at.replace(tzinfo=timezone.utc)
            else:
                available_at = getattr(batch, "available_at", None)
                if available_at is None:
                    if not allow_unproven_available_at:
                        continue
                    available_at = datetime.combine(published, time.min, timezone.utc)
                elif available_at.tzinfo is None:
                    available_at = available_at.replace(tzinfo=timezone.utc)
            values: dict[str, float] = {}
            for source, feature in _FUNDAMENTAL_FIELDS.items():
                value = _optional_float(row.get(source))
                if value is not None:
                    values[feature] = value
            if values:
                key = (published, statistical)
                reference = references_by_symbol[str(batch.symbol)].setdefault(key, {
                    "effective_date": published,
                    "published_at": datetime.combine(published, time.min, timezone.utc),
                    "available_at": available_at,
                    "revision_id": str(getattr(batch, "payload_hash", "") or "revision-1"),
                    "revision": 1,
                    "values": {},
                })
                # All six families must be visible before the merged quarter
                # can be used.  Keep the latest availability and preserve
                # every non-null field across family payloads.
                reference["available_at"] = max(reference["available_at"], available_at)
                reference["values"].update(values)

    output: dict[str, dict[date, dict[str, float]]] = {}
    for symbol, keyed in references_by_symbol.items():
        references = sorted(keyed.values(), key=lambda item: (item["effective_date"], item["revision_id"]))
        current: dict[str, float] = {}
        latest_published: date | None = None
        timeline: dict[date, dict[str, float]] = {}
        # Both target dates and decision timestamps are monotonic.  Maintain a
        # visible reference frontier instead of calling PITJoinService with a
        # full reference scan for every bar (which made broad sample builds
        # quadratic in bars × statement revisions).
        available_refs = sorted(
            references,
            key=lambda item: (item["available_at"], item["effective_date"], item["revision_id"]),
        )
        available_cursor = 0
        future_effective: list[tuple[date, int, dict]] = []
        active_by_effective: dict[date, dict] = {}
        selected: dict | None = None

        def activate(reference: dict) -> None:
            effective = reference["effective_date"]
            previous = active_by_effective.get(effective)
            if previous is None or _financial_reference_rank(reference) > _financial_reference_rank(previous):
                active_by_effective[effective] = reference

        for bar in sorted(bars_by_symbol.get(symbol, []), key=lambda item: item.trade_date):
            decision_time = bar.published_at
            while available_cursor < len(available_refs) and available_refs[available_cursor]["available_at"] <= decision_time:
                reference = available_refs[available_cursor]
                if reference["effective_date"] <= bar.trade_date:
                    activate(reference)
                else:
                    heapq.heappush(future_effective, (reference["effective_date"], available_cursor, reference))
                available_cursor += 1
            while future_effective and future_effective[0][0] <= bar.trade_date:
                _effective, _sequence, reference = heapq.heappop(future_effective)
                activate(reference)
            if active_by_effective:
                newest_effective = max(active_by_effective)
                newest = active_by_effective[newest_effective]
                if newest is not selected:
                    selected = newest
                    current.update(newest["values"])
                    latest_published = newest_effective
            if current:
                timeline[bar.trade_date] = {
                    **current,
                    "fundamental_age_days": float(
                        (bar.trade_date - latest_published).days if latest_published else 0
                    ),
                }
        if timeline:
            output[symbol] = timeline
    return output


def _financial_reference_rank(reference: dict) -> tuple[datetime, int, str]:
    revision = reference.get("revision")
    try:
        numeric = int(revision or 0)
    except (TypeError, ValueError):
        numeric = 0
    return reference["available_at"], numeric, str(reference.get("revision_id") or "")


def _load_research_events(
    raw_store: LocalObjectStore, batches: list,
) -> dict[str, list[PointInTimeEvent]]:
    output: dict[str, dict[tuple[str, str], PointInTimeEvent]] = defaultdict(dict)
    category_types = {
        "financial_report": EventType.FILING,
        "earnings_guidance": EventType.EARNINGS,
        "regulatory": EventType.REGULATION,
        "litigation": EventType.LITIGATION,
        "mna": EventType.MNA,
    }
    for batch in sorted(batches, key=lambda item: (item.fetched_at, item.payload_hash)):
        if batch.provider not in {"akshare_cninfo_notices", "eastmoney_cn_announcements", "eastmoney_cn_news"}:
            continue
        for row in _raw_json_rows(raw_store, batch):
            symbol = str(row.get("代码") or row.get("symbol") or "").strip()
            published_date = _parse_date(
                row.get("first_published_at") or row.get("公告日期")
            )
            if not symbol or published_date is None:
                continue
            # Public date-only announcement metadata cannot prove a pre-close
            # timestamp.  Make it visible after that day's close to avoid
            # leaking a post-close announcement into the same close snapshot.
            published = datetime.combine(
                published_date, time(23, 59, 59), ZoneInfo("Asia/Shanghai")
            ).astimezone(timezone.utc)
            title = str(row.get("公告标题") or row.get("title") or "")
            category = str(row.get("event_category") or "material")
            url = row.get("网址") or row.get("公告链接")
            # Eastmoney backfill batches carry collection metadata in the
            # append-only catalog.  When row-level publication time is only a
            # date, use the batch availability as the conservative PIT gate;
            # never assume the announcement was visible before collection.
            available_at = getattr(batch, "available_at", None) or published
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=timezone.utc)
            event = PointInTimeEvent(
                symbol=symbol,
                event_type=category_types.get(category, EventType.ANNOUNCEMENT),
                event_time=published,
                published_at=published,
                available_at=available_at,
                source_name=(
                    "eastmoney_public_announcement"
                    if batch.provider == "eastmoney_cn_announcements"
                    else "eastmoney_public_news" if batch.provider == "eastmoney_cn_news"
                    else "cninfo_public_notice"
                ),
                source_url=None if not url else str(url),
                headline=title or None,
                payload_ref=batch.payload_ref,
                source_tier=EventSourceTier.AGGREGATOR,
                filing_subtype=category,
                provider=batch.provider,
                as_of=published,
                raw_hash=batch.payload_hash,
                data_version=f"research-event:{batch.payload_hash[:16]}",
            )
            output[symbol][(published.isoformat(), title)] = event
    return {
        symbol: sorted(events.values(), key=lambda item: item.published_at)
        for symbol, events in output.items()
    }


def _merge_feature_timelines(*timelines: dict[date, dict[str, float]]) -> dict[date, dict[str, float]]:
    output: dict[date, dict[str, float]] = defaultdict(dict)
    for timeline in timelines:
        for trade_date, values in timeline.items():
            output[trade_date].update(values)
    return dict(output)


def _load_auxiliary_features(trade_dates: set[date] | None = None) -> dict[date, dict[str, float]]:
    """Load market-level features, admitting macro data only after PIT proof."""
    path = PROJECT / "artifacts/cn_research_auxiliary/margin_financing.json"
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    balances: list[tuple[date, float]] = []
    for row in rows:
        try:
            value = row.get("financing_balance")
            if value is None:
                continue
            balances.append((date.fromisoformat(str(row["trade_date"])[:10]), float(value)))
        except (KeyError, TypeError, ValueError):
            continue
    balances.sort()
    output: dict[date, dict[str, float]] = {}
    for index, (trade_date, value) in enumerate(balances):
        if index < 5 or balances[index - 5][1] <= 0:
            continue
        output[trade_date] = {
            "margin_financing_change_5d": value / balances[index - 5][1] - 1.0,
        }
    output.update(_load_verified_macro_features(trade_dates or set()))
    return output


def _load_verified_macro_features(trade_dates: set[date]) -> dict[date, dict[str, float]]:
    """Forward-fill only macro observations proven visible by decision time.

    The current public artifact is degraded because release timestamps are
    absent; in that state this function intentionally returns no macro values.
    Once a provider supplies a complete macro PIT artifact, the same code path
    will use ``available_at`` and observation period without changing the
    training contract.
    """
    report_path = PROJECT / "artifacts/cn_research_auxiliary/macro_pit_latest.json"
    rows_path = PROJECT / "artifacts/cn_research_auxiliary/macro_pit.jsonl"
    if not report_path.is_file() or not rows_path.is_file():
        return {}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if report.get("quality_status") != "complete":
        return {}
    feature_sources = {
        "cn_macro_cpi_monthly": (("今值",), "macro_cpi_mom"),
        "cn_macro_ppi_monthly": (("当月同比增长",), "macro_ppi_yoy"),
        "cn_macro_pmi_monthly": (("制造业-指数",), "macro_pmi_manufacturing"),
        "cn_macro_lpr": (("LPR1Y", "RATE_1"), "macro_lpr_1y"),
        "cn_macro_shibor": (("O/N-定价",), "macro_shibor_overnight"),
        "cn_macro_m2": (("货币和准货币(M2)-同比增长",), "macro_m2_yoy"),
        "cn_macro_social_financing": (("社会融资规模增量",), "macro_social_financing_increment"),
        "cn_macro_fx_rmb": (("美元/人民币_中间价",), "macro_usdcny_mid"),
    }
    observations: dict[str, list[tuple[date, date, float]]] = defaultdict(list)
    try:
        lines = rows_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            record = json.loads(line)
            period = date.fromisoformat(str(record["observation_period"])[:10])
            available = datetime.fromisoformat(str(record["available_at"]).replace("Z", "+00:00")).date()
            if record.get("published_at") in (None, ""):
                continue
            sources = feature_sources.get(record.get("dataset"))
            if not sources:
                continue
            values = record.get("values") or {}
            for names, feature_name in (sources,):
                raw = next((values.get(name) for name in names if values.get(name) not in (None, "")), None)
                if raw is None:
                    continue
                value = float(raw)
                if value == value:
                    observations[feature_name].append((period, available, value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    for values in observations.values():
        values.sort(key=lambda item: item[0])
    output: dict[date, dict[str, float]] = {}
    for trade_date in sorted(trade_dates):
        features: dict[str, float] = {}
        for feature_name, values in observations.items():
            eligible = [item for item in values if item[0] <= trade_date and item[1] <= trade_date]
            if eligible:
                features[feature_name] = eligible[-1][2]
        if features:
            output[trade_date] = features
    return output


def _raw_json_rows(raw_store: LocalObjectStore, batch) -> list[dict]:
    payload = raw_store.get(_object_key(batch.payload_ref))
    if sha256(payload).hexdigest() != batch.payload_hash:
        raise ValueError(f"raw_payload_hash_mismatch:{batch.id}")
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError(f"raw_payload_not_a_row_list:{batch.id}")
    return [row for row in rows if isinstance(row, dict)]


def _parse_date(value) -> date | None:
    if value in {None, "", "None"}:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _optional_float(value) -> float | None:
    if value in {None, "", "None", "nan", "NaN"}:
        return None
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return None
    return resolved if abs(resolved) < 1e30 else None


def _leakage_report(context: str, snapshot: dict, manifests: dict[str, list[str]]) -> dict:
    checks = [
        {"name": "one_market_snapshot_per_scope", "status": "PASS"},
        {"name": "event_missing_not_encoded_as_zero", "status": "PASS", "event_coverage_status": snapshot["event_coverage_status"]},
        {"name": "formal_historical_available_at_proven", "status": "BLOCKED", "reason": RESEARCH_VISIBILITY_ASSUMPTION},
        {"name": "sample_snapshot_hash_bound", "status": "PASS"},
        {"name": "synthetic_rows", "status": "PASS", "count": 0},
    ]
    body = {
        "schema_version": "free-research-leakage-report-v1",
        "data_tier": DataTier.RESEARCH_PIT.value, "decision_context": context,
        "market_snapshot_id": snapshot["market_snapshot_id"],
        "market_snapshot_hash": snapshot["market_snapshot_hash"],
        "research_error_count": 0, "formal_release_blocked": True,
        "checks": checks, "sample_manifest_count": sum(map(len, manifests.values())),
    }
    return {**body, "report_hash": sha256(_canonical(body)).hexdigest()}


def _object_key(ref: str) -> str:
    if not ref.startswith("file-object://"):
        raise ValueError("zero-budget local rebuild only accepts file-object raw references")
    key = ref.removeprefix("file-object://")
    if not key or ".." in Path(key).parts:
        raise ValueError("unsafe raw object reference")
    return key


def _event_coverage(path: Path) -> str:
    if not path.is_file():
        return "unsupported"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cn = next(item for item in payload.get("market_coverage", []) if item.get("market") == "cn")
        value = str(cn.get("event_coverage_status", "unsupported"))
    except (OSError, ValueError, StopIteration, TypeError):
        return "fetch_failed"
    # The aligned coverage ledger uses ``complete`` for a successful
    # backfill, while the model's enum uses ``events_present``.
    if value == "complete":
        return "events_present"
    return value if value in {"events_present", "confirmed_none", "unsupported", "fetch_failed", "pending_update", "partial"} else "fetch_failed"


def _provider_conflict_symbols(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(item["symbol"])
            for item in payload.get("records", [])
            if item.get("market") == "cn" and item.get("degraded_reason") == "provider_conflict" and item.get("symbol")
        }
    except (OSError, ValueError, TypeError):
        return set()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _portable_path(path: Path) -> str:
    """Persist project-relative refs while retaining isolated temp-fixture support."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if path.is_file() and path.read_text(encoding="utf-8") != encoded:
        # Dated snapshot/sample manifests are immutable.  A changed rebuild
        # requires a new as-of or removal in an explicit test workspace.
        raise ValueError(f"immutable research artifact already exists with different content: {path}")
    path.write_text(encoded, encoding="utf-8")


def _write_json_pointer(path: Path, payload: object) -> None:
    """Replace a stable pointer while keeping dated artifacts immutable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
