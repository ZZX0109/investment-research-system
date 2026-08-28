"""Read-only quality and eligibility view for the free CN research edition.

The project deliberately keeps a broad raw-price archive.  That does *not*
mean every symbol can enter a return backtest or a model cohort: those paths
need a matching front-adjusted series, and the free edition is scoped to
Shanghai/Shenzhen A shares (plus the explicit ETF benchmarks).  This module is
the single place that exposes that distinction to the API and build pipeline.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_research.training.cn_free_providers import ETF_RESEARCH_SYMBOLS


QUALITY_SCHEMA_VERSION = "free-cn-research-data-quality-v1"
CURRENT_DISCOVERY_SCHEMA_VERSION = "free-cn-research-current-discovery-v1"
_BROAD_PRICE_DATASETS = {"daily_bars_raw", "daily_bars_qfq"}


@dataclass(frozen=True)
class PriceBatchReference:
    """The only raw-batch fields needed to compute public price coverage."""

    dataset: str
    symbol: str | None


def normalise_symbol(symbol: str) -> str:
    """Return the six-digit local code used by the public CN collectors."""
    return str(symbol).strip().upper().rsplit(".", 1)[-1].zfill(6)


def is_free_research_model_scope(symbol: str) -> bool:
    """Whether a symbol is in the no-cost model/backtest scope.

    The free product permits only Shanghai/Shenzhen A shares, together with
    the five disclosed benchmark ETFs.  A raw BSE archive remains queryable,
    but is deliberately outside the model/backtest scope until its adjustment
    and commercial-use contracts are complete.
    """
    value = normalise_symbol(symbol)
    return value.startswith(("0", "3", "6")) or value in ETF_RESEARCH_SYMBOLS


def eligibility_for_symbol(
    symbol: str,
    *,
    raw_symbols: set[str],
    qfq_symbols: set[str],
) -> dict[str, Any]:
    """Describe symbol-level permissions without silently falling back to raw."""
    value = normalise_symbol(symbol)
    quote_available = value in raw_symbols
    reasons: list[str] = []
    if not quote_available:
        reasons.append("raw_price_series_missing")
    if not is_free_research_model_scope(value):
        reasons.append("outside_free_model_scope_bse_or_non_a_share")
    if value not in qfq_symbols:
        reasons.append("front_adjusted_price_series_missing")
    model_backtest_eligible = (
        quote_available
        and value in qfq_symbols
        and is_free_research_model_scope(value)
    )
    return {
        "symbol": value,
        "quote_research_eligible": quote_available,
        "return_backtest_eligible": model_backtest_eligible,
        "model_eligible": model_backtest_eligible,
        "scope": "hushen_a_share_or_benchmark_etf"
        if is_free_research_model_scope(value)
        else "raw_quote_only",
        "blocking_reasons": reasons,
    }


def build_free_research_data_quality(
    *,
    project_root: Path,
    raw_batches: Iterable[PriceBatchReference | object],
) -> dict[str, Any]:
    """Build an honest product-facing data inventory from persisted facts.

    Artifact fields are read only when present and valid.  Missing or malformed
    reports stay unavailable/blocked; the function never derives a completion
    claim from an absent report.
    """
    raw_symbols, qfq_symbols = _price_symbol_sets(raw_batches)
    hushen_raw = {symbol for symbol in raw_symbols if is_free_research_model_scope(symbol)}
    hushen_qfq = hushen_raw & qfq_symbols
    outside_scope_raw = raw_symbols - hushen_raw
    outside_scope_qfq = outside_scope_raw & qfq_symbols
    missing_outside_scope_qfq = sorted(outside_scope_raw - qfq_symbols)

    lifecycle = _read_artifact(project_root, "cn_security_lifecycle_akshare")
    universe = _read_artifact(project_root, "cn_security_master_universe")
    financials = _read_artifact(project_root, "cn_financial_coverage")
    actions = _read_artifact(project_root, "cn_corporate_actions_detailed")
    events = _read_artifact(project_root, "cn_event_backfill_full")
    macro = _read_artifact(project_root, "cn_macro_actual_release_nbs")
    # Prefer the unified macro PIT audit when it exists.  The legacy NBS
    # artifact only covers the small candidate-release subset and otherwise
    # makes the UI under-report the official PBC/CFETS/SHIBOR evidence that is
    # already normalized in ``cn_research_auxiliary/macro_pit_latest.json``.
    macro_pit = _read_exact_artifact(project_root / "artifacts/cn_research_auxiliary/macro_pit_latest.json")
    if _int(macro_pit, "record_count") > 0:
        macro = {
            **macro_pit,
            "verified_pubdate_count": round(
                _int(macro_pit, "record_count") * _number(macro_pit, "published_at_coverage")
            ),
            "blocking_reasons": [
                macro_pit.get("missing_reason_code") or "published_time_unverified"
            ],
        }
    financial_ratio_progress = _financial_ratio_progress(project_root)
    financial_core_bulk_progress = _financial_core_bulk_progress(project_root)
    financial_statement_bulk_progress = _financial_statement_bulk_progress(project_root)
    research_sample_progress = _research_sample_progress(project_root)

    raw_target = _int(universe, "equity_count") + _int(universe, "etf_count")
    if raw_target <= 0:
        raw_target = int(lifecycle.get("target_equity_count") or len(raw_symbols))
    raw_coverage = _ratio(len(raw_symbols), raw_target)
    datasets = [
        _dataset(
            "raw_prices",
            status="available" if raw_symbols else "unavailable",
            target_count=raw_target,
            available_count=len(raw_symbols),
            coverage_ratio=raw_coverage,
            as_of=_artifact_timestamp(lifecycle),
            purpose="quote_research",
            detail="Raw daily prices are available for quote and chart research; raw prices are never substituted for adjusted return labels.",
        ),
        _dataset(
            "hushen_qfq_prices",
            status="available" if hushen_raw and len(hushen_qfq) == len(hushen_raw) else ("partial" if hushen_qfq else "blocked"),
            target_count=len(hushen_raw),
            available_count=len(hushen_qfq),
            coverage_ratio=_ratio(len(hushen_qfq), len(hushen_raw)),
            as_of=_artifact_timestamp(lifecycle),
            purpose="return_backtest_and_model",
            detail="Only symbols with both raw and front-adjusted prices in the Shanghai/Shenzhen A-share or benchmark-ETF scope can enter return backtests or model cohorts.",
        ),
        _dataset(
            "outside_scope_adjusted_prices",
            status="blocked" if outside_scope_raw else "unavailable",
            target_count=len(outside_scope_raw),
            available_count=len(outside_scope_qfq),
            coverage_ratio=_ratio(len(outside_scope_qfq), len(outside_scope_raw)),
            as_of=_artifact_timestamp(lifecycle),
            purpose="raw_quote_only",
            detail="BSE/non-A-share symbols may be browsed when raw prices exist, but are excluded from the free model and return-backtest scope even if an adjusted series later appears.",
            missing_symbol_count=len(missing_outside_scope_qfq),
            sample_missing_symbols=missing_outside_scope_qfq[:12],
        ),
        _dataset(
            "financial_fields",
            status=_artifact_status(financials, default="unavailable"),
            target_count=_int(financials, "target_field_count"),
            available_count=_int(financials, "observed_field_count"),
            coverage_ratio=_number(financials, "coverage"),
            as_of=_artifact_timestamp(financials),
            purpose="fundamental_research",
            detail="Financial field completeness is distinct from historical publication-time proof. Historical model/backtest use remains restricted when published_at is unverified.",
            published_at_coverage=_number(financials, "published_at_coverage"),
            pit_verified=bool(financials.get("pit_verified")) if financials else False,
            blocking_reasons=_artifact_reasons(financials),
        ),
        _dataset(
            "financial_ratio_backfill",
            status=financial_ratio_progress["status"],
            target_count=financial_ratio_progress["target_count"],
            available_count=financial_ratio_progress["completed_count"],
            coverage_ratio=financial_ratio_progress["coverage_ratio"],
            as_of=financial_ratio_progress["as_of"],
            purpose="full_market_financial_metric_backfill",
            detail="Public Sina financial metrics are being backfilled for the full current equity universe. They remain research-only until each report period is reconciled to authoritative publication and revision evidence.",
            dimensions={"metric_contract_version": financial_ratio_progress["metric_contract_version"]},
            blocking_reasons=financial_ratio_progress["blocking_reasons"],
        ),
        _dataset(
            "financial_core_bulk_backfill",
            status=financial_core_bulk_progress["status"],
            target_count=financial_core_bulk_progress["target_count"],
            available_count=financial_core_bulk_progress["completed_count"],
            coverage_ratio=financial_core_bulk_progress["coverage_ratio"],
            as_of=financial_core_bulk_progress["as_of"],
            purpose="full_market_quarterly_core_financial_backfill",
            detail="Quarterly all-market core reports are landed with provider publication dates and raw payload hashes. They require reconciliation with authoritative CNINFO first-publication and revision evidence before formal PIT use.",
            published_at_coverage=financial_core_bulk_progress["published_at_coverage"],
            dimensions={
                "row_count": financial_core_bulk_progress["row_count"],
                "invalid_page_count": financial_core_bulk_progress["invalid_page_count"],
            },
            blocking_reasons=financial_core_bulk_progress["blocking_reasons"],
        ),
        _dataset(
            "financial_statement_bulk_backfill",
            status=financial_statement_bulk_progress["status"],
            target_count=financial_statement_bulk_progress["target_count"],
            available_count=financial_statement_bulk_progress["completed_count"],
            coverage_ratio=financial_statement_bulk_progress["coverage_ratio"],
            as_of=financial_statement_bulk_progress["as_of"],
            purpose="full_market_income_cashflow_balance_backfill",
            detail="The all-market performance, income, cashflow and balance landing jobs are tracked independently. No value is promoted to formal PIT until it is reconciled to official publication and revision evidence.",
            published_at_coverage=financial_statement_bulk_progress["published_at_coverage"],
            dimensions={
                "row_count": financial_statement_bulk_progress["row_count"],
                "invalid_page_count": financial_statement_bulk_progress["invalid_page_count"],
            },
            blocking_reasons=financial_statement_bulk_progress["blocking_reasons"],
        ),
        _dataset(
            "research_sample_layer",
            status=research_sample_progress["status"],
            target_count=research_sample_progress["target_count"],
            available_count=research_sample_progress["available_count"],
            coverage_ratio=research_sample_progress["coverage_ratio"],
            as_of=research_sample_progress["as_of"],
            purpose="research_training_and_inference",
            detail="Research samples must be generated from the same immutable rebuild snapshot as the sample manifests; an older snapshot cannot be reused for current inference.",
            dimensions={
                "sample_manifest_count": research_sample_progress["sample_manifest_count"],
                "bound_manifest_count": research_sample_progress["bound_manifest_count"],
                "staging_manifest_count": research_sample_progress["staging_manifest_count"],
                "staging_symbol_count": research_sample_progress["staging_symbol_count"],
                "snapshot_id": research_sample_progress["snapshot_id"],
                "snapshot_hash": research_sample_progress["snapshot_hash"],
            },
            blocking_reasons=research_sample_progress["blocking_reasons"],
        ),
        _dataset(
            "corporate_actions",
            status=_artifact_status(actions, default="unavailable"),
            target_count=_int(actions, "target_equity_count"),
            available_count=_int(actions, "completed_equity_count"),
            coverage_ratio=_ratio(_int(actions, "completed_equity_count"), _int(actions, "target_equity_count")),
            as_of=_artifact_timestamp(actions),
            purpose="long_horizon_return_validation",
            detail="Dividend and rights-issue history is incomplete. It cannot be used to assert full-market long-horizon total-return coverage.",
            blocking_reasons=_artifact_reasons(actions),
        ),
        _dataset(
            "security_lifecycle",
            status=_artifact_status(lifecycle, default="unavailable"),
            target_count=_int(lifecycle, "target_equity_count"),
            available_count=_int(lifecycle, "industry_history_symbol_count"),
            coverage_ratio=_number(lifecycle, "industry_history_coverage"),
            as_of=_artifact_timestamp(lifecycle),
            purpose="historical_universe_and_state",
            detail="Listing, delisting, ST, industry and code-change histories are not a complete historical universe contract, so survivorship-safe full-market claims stay blocked.",
            dimensions={
                key: _number(lifecycle, key)
                for key in (
                    "listing_date_coverage",
                    "delisting_date_coverage",
                    "industry_history_coverage",
                    "st_status_coverage",
                    "code_change_coverage",
                    "published_at_coverage",
                )
            },
            blocking_reasons=_artifact_reasons(lifecycle),
        ),
        _dataset(
            "events_and_disclosures",
            status=_artifact_status(events, default="unavailable"),
            target_count=_int(events, "target_equity_count"),
            available_count=_int(events, "completed_equity_count"),
            coverage_ratio=_ratio(_int(events, "completed_equity_count"), _int(events, "target_equity_count")),
            as_of=_artifact_timestamp(events),
            purpose="event_research",
            detail="The completed public event backfill is a scoped 162-equity research pool, not a complete full-market event history.",
            blocking_reasons=_artifact_reasons(events),
        ),
        _dataset(
            "macro_release_times",
            status=_artifact_status(macro, default="unavailable"),
            target_count=_int(macro, "record_count"),
            available_count=_int(macro, "verified_pubdate_count"),
            coverage_ratio=_number(macro, "published_at_coverage"),
            as_of=_artifact_timestamp(macro),
            purpose="macro_context",
            detail="Macro records without a verified actual publication time are context only, not point-in-time model features.",
            dimensions={
                "source_release_date_coverage": _number(macro, "source_release_date_coverage"),
                "planned_published_at_coverage": _number(macro, "planned_published_at_coverage"),
                "revision_coverage": _number(macro, "revision_coverage"),
                "evidence_levels": macro.get("evidence_levels"),
            },
            blocking_reasons=_artifact_reasons(macro),
        ),
    ]
    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "status": "research_only",
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "generated_from": "append_only_catalog_and_quality_artifacts",
        "model_backtest_scope": {
            "name": "Shanghai/Shenzhen A shares + disclosed benchmark ETFs",
            "eligible_symbol_count": len(hushen_qfq),
            "raw_symbol_count": len(hushen_raw),
            "coverage_ratio": _ratio(len(hushen_qfq), len(hushen_raw)),
            "policy": "matching_raw_and_qfq_required",
        },
        "quote_only_scope": {
            "name": "BSE and other symbols outside the free model scope",
            "raw_symbol_count": len(outside_scope_raw),
            "adjusted_symbol_count": len(outside_scope_qfq),
            "qfq_missing_symbol_count": len(missing_outside_scope_qfq),
            "sample_qfq_missing_symbols": missing_outside_scope_qfq[:12],
            "policy": "quote_research_only_no_model_or_return_backtest",
        },
        "capabilities": [
            {
                "id": "quote_research",
                "status": "available" if raw_symbols else "unavailable",
                "scope": "All symbols with persisted raw daily prices",
                "requirement": "raw_daily_price",
            },
            {
                "id": "return_backtest",
                "status": "available" if hushen_raw and len(hushen_qfq) == len(hushen_raw) else "partial",
                "scope": "Shanghai/Shenzhen A shares and disclosed benchmark ETFs with matching raw + qfq prices",
                "requirement": "raw_and_qfq_and_in_free_model_scope",
            },
            {
                "id": "model_cohort",
                "status": "available" if hushen_raw and len(hushen_qfq) == len(hushen_raw) else "partial",
                "scope": "Same as return backtest; further history, liquidity and quality gates still apply",
                "requirement": "raw_and_qfq_and_cohort_quality_gates",
            },
            {
                "id": "full_market_historical_claim",
                "status": "blocked",
                "scope": "Not available in the free edition",
                "requirement": "complete_lifecycle_actions_and_publication_time_proof",
            },
        ],
        "datasets": datasets,
        "blocking_reasons": _unique(
            [
                "research_only_no_investment_advice_or_production_deployment",
                "free_model_scope_excludes_bse_and_non_a_shares",
                *[reason for dataset in datasets for reason in dataset.get("blocking_reasons", [])],
            ]
        ),
    }


def build_current_research_discovery(
    *,
    project_root: Path,
    raw_batches: Iterable[PriceBatchReference | object],
    query: str = "",
    limit: int = 60,
    asset_type: str = "all",
    eligibility: str = "all",
) -> dict[str, Any]:
    """List the current public market enumeration with product permissions.

    This is intentionally a *discovery* catalogue, not a historical research
    universe.  It lets users find every currently enumerated A-share/ETF and
    immediately see whether the selected security has quote-only access or is
    eligible to enter the free return/model path.  The source never provides
    historical membership, delisting history, or formal PIT proof.
    """
    requested_asset_type = asset_type if asset_type in {"all", "equity", "etf"} else "all"
    requested_eligibility = eligibility if eligibility in {"all", "model", "quote_only", "unavailable"} else "all"
    unavailable = {
        "schema_version": CURRENT_DISCOVERY_SCHEMA_VERSION,
        "status": "unavailable",
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "as_of": None,
        "source": {
            "provider": "akshare_cn_security_master",
            "kind": "current_public_enumeration",
            "historical_membership_proven": False,
        },
        "filters": {
            "query": query.strip(),
            "asset_type": requested_asset_type,
            "eligibility": requested_eligibility,
        },
        "symbols": [],
        "counts": {
            "current_universe": 0,
            "quote_research_eligible": 0,
            "return_backtest_eligible": 0,
            "model_eligible": 0,
            "quote_only": 0,
            "matched": 0,
            "displayed": 0,
        },
        "blocking_reasons": ["current_security_master_unavailable"],
    }
    master_path = project_root / "artifacts" / "cn_security_master_universe" / "security_master_current.json"
    latest = _read_artifact(project_root, "cn_security_master_universe")
    try:
        payload = json.loads(master_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return unavailable
    if not isinstance(payload, list):
        return {**unavailable, "blocking_reasons": ["current_security_master_invalid"]}

    raw_symbols, qfq_symbols = _price_symbol_sets(raw_batches)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not isinstance(code, (str, int)):
            continue
        symbol = normalise_symbol(str(code))
        if symbol in seen:
            continue
        seen.add(symbol)
        instrument_type = str(item.get("instrument_type") or "equity")
        if instrument_type not in {"equity", "etf"}:
            instrument_type = "equity"
        eligibility_result = eligibility_for_symbol(
            symbol,
            raw_symbols=raw_symbols,
            qfq_symbols=qfq_symbols,
        )
        records.append(
            {
                "symbol": symbol,
                "name": str(item.get("code_name") or "名称待补充").strip() or "名称待补充",
                "exchange": _cn_exchange(symbol),
                "asset_type": instrument_type,
                "provider": str(item.get("provider_as_of") or latest.get("provider") or "current_public_enumeration"),
                **eligibility_result,
            }
        )

    records.sort(key=lambda item: (item["asset_type"] == "etf", item["symbol"]))
    normalized_query = query.strip().lower()
    matched = [
        item for item in records
        if (requested_asset_type == "all" or item["asset_type"] == requested_asset_type)
        and (
            requested_eligibility == "all"
            or (requested_eligibility == "model" and item["model_eligible"])
            or (
                requested_eligibility == "quote_only"
                and item["quote_research_eligible"]
                and not item["model_eligible"]
            )
            or (requested_eligibility == "unavailable" and not item["quote_research_eligible"])
        )
        and (not normalized_query or normalized_query in f"{item['symbol']} {item['name']}".lower())
    ]
    bounded_limit = max(1, min(int(limit), 100))
    visible = matched[:bounded_limit]
    quote_eligible = sum(bool(item["quote_research_eligible"]) for item in records)
    return_eligible = sum(bool(item["return_backtest_eligible"]) for item in records)
    model_eligible = sum(bool(item["model_eligible"]) for item in records)
    return {
        "schema_version": CURRENT_DISCOVERY_SCHEMA_VERSION,
        "status": "research_only",
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "as_of": _artifact_timestamp(latest),
        "source": {
            "provider": latest.get("provider") or "akshare_cn_security_master",
            "kind": "current_public_enumeration",
            "source_uri": latest.get("source_uri"),
            "historical_membership_proven": False,
        },
        "filters": {
            "query": query.strip(),
            "asset_type": requested_asset_type,
            "eligibility": requested_eligibility,
        },
        "symbols": visible,
        "counts": {
            "current_universe": len(records),
            "quote_research_eligible": quote_eligible,
            "return_backtest_eligible": return_eligible,
            "model_eligible": model_eligible,
            "quote_only": max(0, quote_eligible - model_eligible),
            "matched": len(matched),
            "displayed": len(visible),
        },
        "blocking_reasons": _unique(
            [
                "current_enumeration_only_not_historical_membership_or_pit_proof",
                "research_only_no_investment_advice_or_production_deployment",
                *(_artifact_reasons(latest)),
            ]
        ),
    }


def load_free_research_catalog_batches(database: Path) -> list[PriceBatchReference]:
    """Read the dedicated collection catalog without migrating or mutating it."""
    if not database.is_file():
        return []
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "SELECT dataset,payload_json FROM raw_data_batches WHERE data_tier=? AND dataset IN (?,?)",
            ("research_pit", "daily_bars_raw", "daily_bars_qfq"),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    output: list[PriceBatchReference] = []
    for dataset, payload in rows:
        try:
            document = json.loads(str(payload))
            symbol = document.get("symbol") if isinstance(document, dict) else None
            output.append(PriceBatchReference(dataset=str(dataset), symbol=None if symbol is None else str(symbol)))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return output


def _price_symbol_sets(raw_batches: Iterable[PriceBatchReference | object]) -> tuple[set[str], set[str]]:
    raw_symbols: set[str] = set()
    qfq_symbols: set[str] = set()
    for batch in raw_batches:
        dataset = getattr(batch, "dataset", None)
        symbol_value = getattr(batch, "symbol", None)
        if dataset not in _BROAD_PRICE_DATASETS or not symbol_value:
            continue
        symbol = normalise_symbol(str(symbol_value))
        if dataset == "daily_bars_raw":
            raw_symbols.add(symbol)
        else:
            qfq_symbols.add(symbol)
    return raw_symbols, qfq_symbols


def _cn_exchange(symbol: str) -> str:
    value = normalise_symbol(symbol)
    if value.startswith(("5", "6")):
        return "XSHG"
    if value.startswith(("0", "1", "3")):
        return "XSHE"
    return "XBSE"


def _read_artifact(project_root: Path, name: str) -> dict[str, Any]:
    path = project_root / "artifacts" / name / "latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_exact_artifact(path: Path) -> dict[str, Any]:
    """Read an artifact whose filename is not ``<dataset>/latest.json``."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _financial_ratio_progress(project_root: Path) -> dict[str, Any]:
    """Read the checkpointed full-market metric backfill without mutating it."""
    progress_path = project_root / "artifacts" / "cn_financial_ratios_akshare" / "progress.json"
    latest = _read_artifact(project_root, "cn_financial_ratios_akshare")
    try:
        progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        progress_payload = {}
    progress = progress_payload if isinstance(progress_payload, dict) else {}
    contract_version = _int(progress, "metric_contract_version")
    states = progress.get("symbols")
    completed = 0
    if isinstance(states, dict):
        for value in states.values():
            if not isinstance(value, dict) or value.get("status") != "complete":
                continue
            if contract_version and _int(value, "metric_contract_version") != contract_version:
                continue
            completed += 1
    target = _int(progress, "target_equity_count") or _int(latest, "target_equity_count")
    if not progress and latest:
        completed = _int(latest, "completed_equity_count")
        contract_version = _int(latest, "metric_contract_version")
    coverage = _ratio(completed, target)
    if target and completed >= target:
        status = "complete" if _artifact_status(latest, default="partial") == "complete" else "partial"
    elif completed:
        status = "partial"
    else:
        status = _artifact_status(latest, default="unavailable")
    return {
        "status": status,
        "target_count": target,
        "completed_count": completed,
        "coverage_ratio": coverage,
        "as_of": progress.get("updated_at") or _artifact_timestamp(latest),
        "metric_contract_version": contract_version or None,
        "blocking_reasons": [
            "financial_metric_backfill_in_progress" if target and completed < target else "financial_publication_and_revision_reconciliation_required",
            "research_only_no_formal_pit_or_deployment",
        ] if target else ["financial_metric_backfill_progress_unavailable"],
    }


def _research_sample_progress(project_root: Path) -> dict[str, Any]:
    """Report current rebuild sample coverage without trusting old snapshots."""
    index_path = project_root / "artifacts" / "free_research_rebuild_all_raw_standard" / "latest.json"
    index = _read_json_file(index_path)
    context = index.get("contexts", {}).get("close_confirmed", {}) if isinstance(index, dict) else {}
    if not isinstance(context, dict):
        context = {}
    target_symbols: set[str] = set()
    for value in (index.get("cohort_refs", {}) or {}).values() if isinstance(index, dict) else []:
        path = Path(str(value))
        if not path.is_absolute():
            path = project_root / path
        cohort = _read_json_file(path)
        for member in cohort.get("members", []) if isinstance(cohort, dict) else []:
            if isinstance(member, dict) and member.get("symbol"):
                target_symbols.add(normalise_symbol(str(member["symbol"])))
    refs = [
        str(value)
        for values in (context.get("sample_manifests", {}) or {}).values()
        if isinstance(values, list)
        for value in values
    ]
    sample_symbols: set[str] = set()
    bound_count = 0
    for value in refs:
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        manifest = _read_json_file(path)
        symbol = manifest.get("symbol")
        if symbol:
            sample_symbols.add(normalise_symbol(str(symbol)))
        if (
            manifest.get("market_snapshot_id") == context.get("snapshot_id")
            and manifest.get("market_snapshot_hash") == context.get("snapshot_hash")
        ):
            bound_count += 1
    # Batch generation deliberately lives outside the canonical index until
    # the merge validator sees every cohort member.  Surface its progress for
    # the Data Center, but keep it separate from available_count so neither
    # training nor inference can accidentally consume staging files.
    staging_symbols: set[str] = set()
    staging_manifest_count = 0
    staging_root = project_root / "artifacts" / "free_research_sample_batches"
    if staging_root.is_dir() and context.get("snapshot_hash"):
        for path in staging_root.glob("*/samples/*/*/*/*.json"):
            manifest = _read_json_file(path)
            if (
                manifest.get("market_snapshot_id") == context.get("snapshot_id")
                and manifest.get("market_snapshot_hash") == context.get("snapshot_hash")
                and manifest.get("sample_parquet_ref")
            ):
                staging_manifest_count += 1
                if manifest.get("symbol"):
                    staging_symbols.add(normalise_symbol(str(manifest["symbol"])))
    target_count = len(target_symbols)
    available_count = len(sample_symbols & target_symbols) if target_symbols else len(sample_symbols)
    coverage = _ratio(available_count, target_count)
    complete = bool(
        index
        and index.get("status") == "research_only"
        and target_count > 0
        and available_count >= target_count
        and bound_count == len(refs)
    )
    status = "available" if complete else ("partial" if index else "unavailable")
    return {
        "status": status,
        "target_count": target_count,
        "available_count": available_count,
        "coverage_ratio": coverage,
        "sample_manifest_count": len(refs),
        "bound_manifest_count": bound_count,
        "staging_manifest_count": staging_manifest_count,
        "staging_symbol_count": len(staging_symbols & target_symbols) if target_symbols else len(staging_symbols),
        "snapshot_id": context.get("snapshot_id"),
        "snapshot_hash": context.get("snapshot_hash"),
        "as_of": index.get("as_of") if isinstance(index, dict) else None,
        "blocking_reasons": [] if complete else [
            "research_sample_manifests_missing_or_unbound",
            *(["sample_batches_staging_not_promoted"] if staging_manifest_count else []),
        ],
    }


def _financial_core_bulk_progress(project_root: Path) -> dict[str, Any]:
    """Expose resumable Eastmoney performance-report landing progress."""
    return _financial_eastmoney_family_progress(project_root, "performance")


def _financial_statement_bulk_progress(project_root: Path) -> dict[str, Any]:
    """Aggregate all four separately resumable Eastmoney financial families."""
    family_progress = [
        _financial_eastmoney_family_progress(project_root, family)
        for family in ("performance", "income", "cashflow", "balance")
    ]
    known_targets = [item["target_count"] for item in family_progress if item["target_count"]]
    expected_per_family = max(known_targets, default=0)
    target = sum(item["target_count"] or expected_per_family for item in family_progress)
    completed = sum(item["completed_count"] for item in family_progress)
    rows = sum(item["row_count"] for item in family_progress)
    published_rows = sum(item["published_row_count"] for item in family_progress)
    timestamps = [item["as_of"] for item in family_progress if item["as_of"]]
    all_complete = bool(target and all(item["status"] == "complete" for item in family_progress))
    return {
        "status": "complete" if all_complete else ("partial" if completed else "unavailable"),
        "target_count": target,
        "completed_count": completed,
        "coverage_ratio": _ratio(completed, target),
        "row_count": rows,
        "published_row_count": published_rows,
        "published_at_coverage": _ratio(published_rows, rows),
        "invalid_page_count": sum(item["invalid_page_count"] for item in family_progress),
        "as_of": max(timestamps) if timestamps else None,
        "blocking_reasons": [
            "financial_statement_bulk_backfill_in_progress" if not all_complete else "official_publication_and_revision_reconciliation_required",
            "research_only_no_formal_pit_or_deployment",
        ] if target else ["financial_statement_bulk_backfill_progress_unavailable"],
    }


def _financial_eastmoney_family_progress(project_root: Path, family: str) -> dict[str, Any]:
    root = project_root / "artifacts" / "cn_financial_reports_eastmoney"
    latest = _read_json_file(root / ("latest.json" if family == "performance" else f"{family}-latest.json"))
    manifest_ref = latest.get("landing_manifest") if isinstance(latest.get("landing_manifest"), str) else None
    manifest_path = project_root / manifest_ref if manifest_ref else None
    if manifest_path is None or not manifest_path.exists():
        matches = sorted((root / "landing").glob(f"eastmoney-{family}-*/manifest.json"))
        if not matches and family == "performance":
            matches = sorted((root / "landing").glob("*/manifest.json"))
        manifest_path = matches[-1] if matches else None
    manifest = _read_json_file(manifest_path) if manifest_path else {}
    periods = manifest.get("periods") if isinstance(manifest, dict) else None
    states = periods if isinstance(periods, dict) else {}
    target = len(states) or _int(latest, "target_period_count")
    completed_states = [state for state in states.values() if isinstance(state, dict) and state.get("status") == "complete"]
    completed = len(completed_states) if states else _int(latest, "completed_period_count")
    rows = sum(_int(state, "record_count") for state in completed_states) if states else _int(latest, "row_count")
    published_rows = sum(_int(state, "published_at_count") for state in completed_states)
    published_coverage = _ratio(published_rows, rows) if states else _number(latest, "published_at_coverage")
    audit = _read_json_file(root / f"{family}-audit.json")
    complete = bool(target and completed >= target and _artifact_status(latest, default="partial") == "complete")
    status = "complete" if complete else ("partial" if completed else _artifact_status(latest, default="unavailable"))
    timestamp = manifest.get("updated_at") if isinstance(manifest.get("updated_at"), str) else _artifact_timestamp(latest)
    if not timestamp and manifest_path:
        timestamp = datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "family": family,
        "status": status,
        "target_count": target,
        "completed_count": completed,
        "coverage_ratio": _ratio(completed, target),
        "row_count": rows,
        "published_row_count": published_rows,
        "published_at_coverage": published_coverage,
        "invalid_page_count": _int(audit, "invalid_page_count"),
        "as_of": timestamp,
        "blocking_reasons": [
            f"{family}_financial_bulk_backfill_in_progress" if target and completed < target else "official_publication_and_revision_reconciliation_required",
            "research_only_no_formal_pit_or_deployment",
        ] if target else [f"{family}_financial_bulk_backfill_progress_unavailable"],
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dataset(identifier: str, **values: Any) -> dict[str, Any]:
    return {"id": identifier, **values}


def _artifact_status(payload: dict[str, Any], *, default: str) -> str:
    status = payload.get("status") or payload.get("quality_status")
    return str(status) if status in {"available", "complete", "partial", "degraded", "blocked", "unavailable"} else default


def _artifact_timestamp(payload: dict[str, Any]) -> str | None:
    for key in ("generated_at", "rebuilt_from_latest_fetched_at", "created_at"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _artifact_reasons(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("missing_reason_code", "missing_reason"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    return values


def _int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
