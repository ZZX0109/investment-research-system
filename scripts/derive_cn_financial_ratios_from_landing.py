#!/usr/bin/env python3
"""Derive auditable financial ratios from landed Eastmoney statements.

The public financial-analysis endpoint is incomplete for a subset of fields.
The statement landing files contain the underlying amounts needed to derive
several of those fields.  This script writes *research-only* derived rows to
the existing append-only ratio dataset.  It never overwrites provider values,
and every row carries the source page hash plus an explicit formula.

The result is deliberately not a formal PIT promotion: the statement page's
publication date is preserved in the row, while the catalog availability time
remains the local ingestion time until provider revision ordering is proven.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.cn_universe import load_cn_symbols
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


DATASET = "cn_financial_ratios_akshare_research"
SCHEMA_VERSION = "cn-financial-ratios-derived-landing-v1"
FAMILIES = ("performance", "income", "cashflow", "balance")

# Only fields which are part of the stable coverage contract are emitted.
# Values are calculated from statement amounts, never invented for an empty
# denominator.  The field names match audit_cn_financial_coverage.py.
DERIVED_FIELDS = {
    "growth": ("YOYAsset", "YOYEquity", "YOYEPSBasic"),
    "operation": ("NRTurnRatio", "INVTurnRatio", "AssetTurnRatio"),
    "cash_flow": ("CFOToOR", "CFOToNP", "CFOToGr"),
    "dupont": ("dupontAssetStoEquity", "dupontAssetTurn"),
}

# These two contract fields are intentionally not derived from the current
# public landing feed: the feed exposes monetary funds/inventory, but not
# current-assets or current-liabilities.  Recording this explicitly prevents
# later jobs from treating a zero candidate count as a silent success.
BLOCKED_RATIO_INPUTS = {
    "balance.quickRatio": ("CURRENT_ASSETS", "CURRENT_LIABILITIES", "INVENTORY"),
    "balance.cashRatio": ("CURRENT_ASSETS", "CURRENT_LIABILITIES", "MONETARYFUNDS"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--landing-root", type=Path, default=PROJECT / "artifacts/cn_financial_reports_eastmoney")
    parser.add_argument(
        "--target-symbols",
        type=Path,
        default=PROJECT / "artifacts/cn_security_master_universe/security_master_current.json",
        help="Current universe used to avoid writing derived rows for out-of-scope symbols.",
    )
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_financial_ratios_akshare/derived_landing.json")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _number(value: Any) -> float | None:
    if value in (None, "", "nan", "NaN", "None"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def _average(current: float | None, previous: float | None) -> float | None:
    if current is not None and previous is not None:
        return (current + previous) / 2.0
    return current if current is not None else previous


def _symbol(value: Any) -> str:
    return str(value or "").rsplit(".", 1)[-1].zfill(6)


def _period(value: Any) -> str:
    return str(value or "")[:10]


def _latest_manifests(landing_root: Path) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for family in FAMILIES:
        paths = sorted((landing_root / "landing").glob(f"eastmoney-{family}-*/manifest.json"))
        if paths:
            output[family] = paths[-1]
    return output


def _load_statement_index(landing_root: Path) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    """Load normalized records and retain their landing-page evidence hash."""
    index = {family: {} for family in FAMILIES}
    for family, manifest_path in _latest_manifests(landing_root).items():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        periods = manifest.get("periods", {}) if isinstance(manifest, dict) else {}
        if not isinstance(periods, dict):
            continue
        for period_key, state in sorted(periods.items()):
            if not isinstance(state, dict) or state.get("status") != "complete":
                continue
            for page_path in sorted((manifest_path.parent / str(period_key)).glob("page-*.json")):
                try:
                    envelope = json.loads(page_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                page_hash = str(envelope.get("raw_payload_sha256") or "")
                for record in envelope.get("normalized_records", []):
                    if not isinstance(record, dict):
                        continue
                    symbol = _symbol(record.get("symbol"))
                    period = _period(record.get("report_period"))
                    metrics = record.get("metrics")
                    if not symbol or not period or not isinstance(metrics, dict):
                        continue
                    index[family][(symbol, period)] = {
                        "metrics": metrics,
                        "published_at": record.get("published_at"),
                        "source_uri": record.get("source_uri"),
                        "source_provider": record.get("source_provider"),
                        "raw_payload_sha256": page_hash,
                    }
    return index


def _existing_cells(database: Path) -> set[tuple[str, str, str, str]]:
    """Find provider/previously-derived cells so we never overwrite them."""
    result: set[tuple[str, str, str, str]] = set()
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT payload_json FROM raw_data_batches WHERE dataset=?",
            (DATASET,),
        ).fetchall()
    finally:
        connection.close()
    raw_root = PROJECT / "var/cn-research/raw"
    for (metadata_json,) in rows:
        try:
            metadata = json.loads(metadata_json)
            reference = str(metadata.get("payload_ref") or "")
            payload = json.loads((raw_root / reference.removeprefix("file-object://")).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        records = payload if isinstance(payload, list) else payload.get("rows", [])
        if not isinstance(records, list):
            continue
        for row in records:
            if not isinstance(row, dict):
                continue
            symbol = _symbol(row.get("code") or row.get("symbol") or metadata.get("symbol"))
            period = _period(row.get("statDate") or row.get("report_period"))
            family = str(row.get("feature_family") or "")
            if not symbol or not period or not family:
                continue
            for field in DERIVED_FIELDS.get(family, ()):
                if row.get(field) not in (None, "", "NA", "N/A", "NULL", "null"):
                    result.add((symbol, period, family, field))
    return result


def _derive(
    index: dict[str, dict[tuple[str, str], dict[str, Any]]],
    existing: set[tuple[str, str, str, str]],
    target_symbols: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    keys = set().union(*(set(index[family]) for family in FAMILIES))
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for symbol, period in sorted(keys):
        if target_symbols is not None and symbol not in target_symbols:
            continue
        try:
            year, month, day = period.split("-")
            previous_key = (symbol, f"{int(year) - 1:04d}-{month}-{day}")
        except ValueError:
            continue
        current = {family: index[family].get((symbol, period), {}) for family in FAMILIES}
        previous = {family: index[family].get(previous_key, {}) for family in FAMILIES}
        cm = {family: (current[family].get("metrics") or {}) for family in FAMILIES}
        pm = {family: (previous[family].get("metrics") or {}) for family in FAMILIES}

        total_assets, previous_assets = _number(cm["balance"].get("TOTAL_ASSETS")), _number(pm["balance"].get("TOTAL_ASSETS"))
        total_equity, previous_equity = _number(cm["balance"].get("TOTAL_EQUITY")), _number(pm["balance"].get("TOTAL_EQUITY"))
        receivable, previous_receivable = _number(cm["balance"].get("ACCOUNTS_RECE")), _number(pm["balance"].get("ACCOUNTS_RECE"))
        inventory, previous_inventory = _number(cm["balance"].get("INVENTORY")), _number(pm["balance"].get("INVENTORY"))
        revenue = _number(cm["income"].get("TOTAL_OPERATE_INCOME"))
        cost = _number(cm["income"].get("OPERATE_COST"))
        cfo = _number(cm["cashflow"].get("NETCASH_OPERATE"))
        net_profit = _number(cm["income"].get("PARENT_NETPROFIT"))
        eps, previous_eps = _number(cm["performance"].get("BASIC_EPS")), _number(pm["performance"].get("BASIC_EPS"))
        average_assets = _average(total_assets, previous_assets)
        average_equity = _average(total_equity, previous_equity)
        average_receivable = _average(receivable, previous_receivable)
        average_inventory = _average(inventory, previous_inventory)

        values: dict[tuple[str, str], float | None] = {
            ("growth", "YOYAsset"): _ratio(total_assets, previous_assets) - 1 if total_assets is not None and previous_assets not in (None, 0) else None,
            ("growth", "YOYEquity"): _ratio(total_equity, previous_equity) - 1 if total_equity is not None and previous_equity not in (None, 0) else None,
            ("growth", "YOYEPSBasic"): _ratio(eps, previous_eps) - 1 if eps is not None and previous_eps not in (None, 0) else None,
            ("operation", "NRTurnRatio"): _ratio(revenue, average_receivable),
            ("operation", "INVTurnRatio"): _ratio(cost, average_inventory),
            ("operation", "AssetTurnRatio"): _ratio(revenue, average_assets),
            ("cash_flow", "CFOToOR"): _ratio(cfo, revenue),
            ("cash_flow", "CFOToNP"): _ratio(cfo, net_profit),
            # CFOToGr is defined in the project contract as CFO / gross
            # revenue; the landing feed exposes total operating income as the
            # compatible denominator, so retain that formula explicitly.
            ("cash_flow", "CFOToGr"): _ratio(cfo, revenue),
            ("dupont", "dupontAssetStoEquity"): _ratio(average_assets, average_equity),
            ("dupont", "dupontAssetTurn"): _ratio(revenue, average_assets),
        }
        for (family, field), value in values.items():
            if value is None or (symbol, period, family, field) in existing:
                continue
            source = current.get("income") or current.get("balance") or current.get("cashflow") or current.get("performance") or {}
            published = next((current[f].get("published_at") for f in ("performance", "income", "cashflow", "balance") if current[f].get("published_at")), None)
            source_hashes = sorted({str(current[f].get("raw_payload_sha256")) for f in ("performance", "income", "cashflow", "balance") if current[f].get("raw_payload_sha256")})
            formula = _formula(family, field)
            output[symbol].append({
                "code": symbol,
                "symbol": symbol,
                "statDate": period,
                "report_period": period,
                "feature_family": family,
                field: value,
                "unit": "times" if family == "operation" or field.startswith("dupontAsset") else "ratio",
                "basis": "derived_from_statement_rows",
                "formula": formula,
                "pubDate": published,
                "available_at": None,
                "revision_id": hashlib.sha256((symbol + period + family + field + formula).encode()).hexdigest(),
                "source_publication_status": "cninfo_matched_research_assumption",
                "source_provider": "eastmoney_statement_landing_derived",
                "source_mode": "derived_from_statement_rows",
                "source_uri": source.get("source_uri") or "https://datacenter-web.eastmoney.com/api/data/v1/get",
                "source_page_hashes": source_hashes,
                "research_only": True,
            })
    return output


def _field_availability(index: dict[str, dict[tuple[str, str], dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Summarize raw statement inputs used by missing-ratio remediation."""
    balance = index.get("balance", {})
    total = len(balance)
    result: dict[str, dict[str, Any]] = {}
    for field in sorted({field for fields in BLOCKED_RATIO_INPUTS.values() for field in fields}):
        count = sum(1 for item in balance.values() if _number((item.get("metrics") or {}).get(field)) is not None)
        result[field] = {
            "record_count": total,
            "available_count": count,
            "coverage": count / total if total else 0.0,
        }
    return result


def _formula(family: str, field: str) -> str:
    return {
        ("growth", "YOYAsset"): "TOTAL_ASSETS_t / TOTAL_ASSETS_t-4 - 1",
        ("growth", "YOYEquity"): "TOTAL_EQUITY_t / TOTAL_EQUITY_t-4 - 1",
        ("growth", "YOYEPSBasic"): "BASIC_EPS_t / BASIC_EPS_t-4 - 1",
        ("operation", "NRTurnRatio"): "TOTAL_OPERATE_INCOME_t / avg(ACCOUNTS_RECE_t,ACCOUNTS_RECE_t-4)",
        ("operation", "INVTurnRatio"): "OPERATE_COST_t / avg(INVENTORY_t,INVENTORY_t-4)",
        ("operation", "AssetTurnRatio"): "TOTAL_OPERATE_INCOME_t / avg(TOTAL_ASSETS_t,TOTAL_ASSETS_t-4)",
        ("cash_flow", "CFOToOR"): "NETCASH_OPERATE_t / TOTAL_OPERATE_INCOME_t",
        ("cash_flow", "CFOToNP"): "NETCASH_OPERATE_t / PARENT_NETPROFIT_t",
        ("cash_flow", "CFOToGr"): "NETCASH_OPERATE_t / TOTAL_OPERATE_INCOME_t",
        ("dupont", "dupontAssetStoEquity"): "avg(TOTAL_ASSETS_t,TOTAL_ASSETS_t-4) / avg(TOTAL_EQUITY_t,TOTAL_EQUITY_t-4)",
        ("dupont", "dupontAssetTurn"): "TOTAL_OPERATE_INCOME_t / avg(TOTAL_ASSETS_t,TOTAL_ASSETS_t-4)",
    }[(family, field)]


def main() -> int:
    args = parse_args()
    index = _load_statement_index(args.landing_root)
    existing = _existing_cells(args.database)
    target_symbols = None
    if args.target_symbols.is_file():
        target_symbols = set(load_cn_symbols(args.target_symbols, exclude_etf=True))
    rows_by_symbol = _derive(index, existing, target_symbols)
    candidate_count = sum(len(rows) for rows in rows_by_symbol.values())
    persisted = 0
    if not args.dry_run and rows_by_symbol:
        uow = SQLiteUnitOfWork(args.database)
        service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
        try:
            for symbol, rows in sorted(rows_by_symbol.items()):
                now = datetime.now(timezone.utc)
                service.persist(
                    provider="eastmoney_statement_landing_derived",
                    request_id=f"cn-financial-derived-{symbol}-{uuid4()}",
                    dataset=DATASET,
                    payload=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(),
                    schema_version=SCHEMA_VERSION,
                    symbol=symbol,
                    available_at=now,
                    received_at=now,
                    market_session="research_backfill_derived",
                    data_tier=DataTier.RESEARCH_PIT,
                )
                persisted += len(rows)
        finally:
            uow.close()
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if not args.dry_run else "dry_run",
        "research_only": True,
        "formal_pit_verified": False,
        "derived_symbol_count": len(rows_by_symbol),
        "candidate_row_count": candidate_count,
        "persisted_row_count": persisted,
        "existing_cell_count": len(existing),
        "target_symbol_count": len(target_symbols) if target_symbols is not None else None,
        "derivation_audit": {
            "blocked_fields": {
                field: {
                    "status": "blocked_missing_source_inputs",
                    "required_inputs": list(inputs),
                    "input_availability": {
                        item: _field_availability(index).get(item, {"record_count": 0, "available_count": 0, "coverage": 0.0})
                        for item in inputs
                    },
                }
                for field, inputs in BLOCKED_RATIO_INPUTS.items()
            },
            "no_synthetic_fill": True,
        },
        "source_manifest": {family: str(path) for family, path in _latest_manifests(args.landing_root).items()},
        "formula_semantics": "statement amounts, prior-year same reporting period; catalog available_at is ingestion time",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
