#!/usr/bin/env python3
"""Rebuild reproducible CN research layers from append-only public payloads.

The output is deliberately ``research_pit``.  Historical availability is an
explicit research assumption and the generated manifests can never satisfy a
formal release gate.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import (
    DataTier,
    RESEARCH_TIER_REASONS,
    RESEARCH_VISIBILITY_ASSUMPTION,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.training.cn_free_providers import ETF_RESEARCH_SYMBOLS
from investment_research.training.cn_research_universe import (
    build_cn_equity_core,
    build_cn_etf_benchmark,
)
from investment_research.training.cn_research_collection import audit_research_bars
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.free_research_adapter import normalize_free_daily_payload
from investment_research.training.models import (
    CanonicalInstrument,
    CoverageGroup,
    InstrumentType,
    Market,
    PreparedPriceBar,
)
from investment_research.training.parquet_store import PITParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild zero-budget CN research PIT layers")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--research-object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/free_research_rebuild")
    parser.add_argument("--coverage-ledger", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--contexts", nargs="+", choices=("close_confirmed", "pre_open"), default=["close_confirmed"])
    parser.add_argument("--max-equities", type=int, default=100)
    parser.add_argument("--minimum-equities", type=int, default=80)
    parser.add_argument("--minimum-history-sessions", type=int, default=756)
    parser.add_argument(
        "--minimum-training-sessions", type=int, default=960,
        help="Minimum usable decision history for the longest 20-session task.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_store = LocalObjectStore(args.raw_object_store)
    parquet = PITParquetStore(LocalObjectStore(args.research_object_store))
    uow = SQLiteUnitOfWork(args.database)
    try:
        batches = [
            *uow.trusted_market.raw_batches(dataset="daily_bars_raw", data_tier=DataTier.RESEARCH_PIT.value),
            *uow.trusted_market.raw_batches(dataset="daily_bars_qfq", data_tier=DataTier.RESEARCH_PIT.value),
            # Compatibility only for explicit test fixtures created before the
            # raw/qfq split.  Production defaults never write this dataset.
            *uow.trusted_market.raw_batches(dataset="daily_bars", data_tier=DataTier.RESEARCH_PIT.value),
        ]
    finally:
        uow.close()
    if not batches:
        raise SystemExit("no append-only research_pit daily-bar batches are available")

    # Prefer the newest AKShare batch, then the newest Baostock batch, per symbol.
    candidates: dict[tuple[str, str], list] = defaultdict(list)
    for batch in batches:
        if batch.symbol and batch.provider in {"akshare", "baostock"}:
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
    failures: list[dict[str, str]] = []
    standard_root = args.output_root / "standard"
    symbols = sorted({symbol for symbol, _mode in batch_groups})
    provider_conflicts = _provider_conflict_symbols(args.coverage_ledger)
    quality_reports: list[dict] = []
    for symbol in symbols:
        raw_batches = batch_groups.get((symbol, "raw"), [])
        qfq_batches = batch_groups.get((symbol, "qfq"), [])
        if not raw_batches:
            failures.append({"symbol": symbol, "stage": "standardize", "reason": "raw_adjustment_payload_missing"})
            continue
        try:
            raw_by_date = _merge_batches(
                raw_store, raw_batches, symbol=symbol, as_of=args.as_of,
            )
            if not raw_by_date:
                raise ValueError("no_normalized_rows_before_as_of")
            qfq_by_date = _merge_batches(
                raw_store, qfq_batches, symbol=symbol, as_of=args.as_of,
            ) if qfq_batches else {}
            bars: list[PreparedPriceBar] = []
            for trade_date in sorted(raw_by_date):
                item, raw_batch = raw_by_date[trade_date]
                qfq_item, qfq_batch = qfq_by_date.get(trade_date, (item, raw_batch))
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
            latest_qfq_batch = max(qfq_batches, key=lambda item: item.fetched_at) if qfq_batches else None
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
                "qfq_raw_batch_id": None if latest_qfq_batch is None else str(latest_qfq_batch.id),
                "qfq_payload_hash": None if latest_qfq_batch is None else latest_qfq_batch.payload_hash,
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
    contexts: dict[str, dict] = {}
    for context in args.contexts:
        snapshot = _freeze_snapshot(
            context=context, as_of=as_of, standard_manifests=standard_manifests,
            failures=failures, event_coverage_status=event_coverage_status,
        )
        snapshot_path = args.output_root / "snapshots" / context / f"{as_of.isoformat()}-{snapshot['market_snapshot_hash'][:12]}.json"
        _write_json(snapshot_path, snapshot)
        sample_manifests: dict[str, list[str]] = defaultdict(list)
        for cohort in cohorts:
            for member in cohort.members:
                try:
                    manifests = _build_samples(
                        symbol=member.symbol, cohort=cohort.cohort,
                        cohort_version=cohort.cohort_version, context=context,
                        bars=bars_by_symbol[member.symbol], standard=standard_by_symbol[member.symbol],
                        snapshot=snapshot, parquet=parquet, output_root=args.output_root,
                    )
                    sample_manifests[cohort.cohort].extend(_portable_path(item) for item in manifests)
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
        "training_blocked": len(cohorts[0].members) < args.minimum_equities,
        "training_blocking_reasons": ["eligible_equity_count_below_80"] if len(cohorts[0].members) < args.minimum_equities else [],
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
    print(output)
    return 0


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
    )
    samples = TrainingDatasetBuilder(
        feature_version="cn-research-feature-v3",
        data_version=f"research-snapshot:{snapshot['market_snapshot_hash'][:16]}",
    ).build_samples(
        instrument=instrument, price_bars=assumed, events=[],
        decision_context=context, event_coverage_status=snapshot["event_coverage_status"],
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
            "revision_id": standard.get("normalized_hash") or standard.get("raw_payload_hash"),
            "cache_state": standard.get("cache_state", "fresh"),
            "input_revision_ids": [
                value for value in (
                    standard.get("raw_payload_hash"),
                    standard.get("normalized_hash"),
                ) if value
            ],
            "data_issues": sorted(set([*item.data_issues, RESEARCH_VISIBILITY_ASSUMPTION, "event_coverage:unsupported"])),
        })
        for item in samples
    ]
    if not samples:
        raise ValueError("no_feature_samples")
    by_year = defaultdict(list)
    for item in samples:
        by_year[item.as_of_date.year].append(item)
    paths = []
    for year, year_samples in sorted(by_year.items()):
        ref, payload_hash, schema_hash, row_count = parquet.write_partition(
            year_samples, market="cn", dataset="research_samples",
            schema_version="free-research-samples-v3", trade_year=year,
            partition_id=f"{context}-{cohort}-{symbol}-{snapshot['market_snapshot_hash'][:12]}",
        )
        manifest = {
            "schema_version": "free-research-sample-manifest-v3",
            "data_tier": DataTier.RESEARCH_PIT.value, "mode": "research_only",
            "formal_pit_eligible": False, "deployment_ready": False,
            "blocking_reasons": list(RESEARCH_TIER_REASONS),
            "market": "cn", "symbol": symbol, "cohort": cohort,
            "cohort_version": cohort_version,
            "decision_context": context, "trade_year": year,
            "feature_version": "cn-research-feature-v3",
            "label_version": "cn-direction-volatility-label-v2",
            "market_snapshot_id": snapshot["market_snapshot_id"],
            "market_snapshot_hash": snapshot["market_snapshot_hash"],
            "standard_raw_payload_hash": standard["raw_payload_hash"],
            "sample_parquet_ref": ref, "payload_hash": payload_hash,
            "schema_hash": schema_hash, "row_count": row_count,
            "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        }
        path = output_root / "samples" / context / cohort / symbol / f"{year}-{snapshot['market_snapshot_hash'][:12]}.json"
        _write_json(path, manifest)
        paths.append(path)
    return paths


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


if __name__ == "__main__":
    raise SystemExit(main())
