#!/usr/bin/env python3
"""Import CNINFO-matched Eastmoney landing values into append-only research raw.

This is intentionally an *import to research-only raw*, not a formal PIT
promotion.  A value is imported only when its symbol/report period has a
CNINFO financial-report publication record.  The importer writes the official
announcement time as ``pubDate`` and leaves provider revision ordering
explicitly unverified, so downstream rebuilds still require
``--allow-unproven-visibility`` for the research-assumption layer.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable
from uuid import uuid4


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


SCHEMA_VERSION = "cn-financial-eastmoney-import-v1"
FAMILIES = ("performance", "income", "cashflow", "balance")
DIRECT_METRICS: dict[str, dict[str, tuple[tuple[str, str, float, str], ...]]] = {
    "performance": {
        "BASIC_EPS": (("profit", "epsTTM", 1.0, "currency_per_share"),),
        "WEIGHTAVG_ROE": (("profit", "roeAvg", 0.01, "ratio"), ("dupont", "dupontROE", 0.01, "ratio")),
        "XSMLL": (("profit", "gpMargin", 0.01, "ratio"),),
        "SJLTZ": (("growth", "YOYNI", 0.01, "ratio"), ("growth", "YOYPNI", 0.01, "ratio")),
    },
    "income": {},
    "cashflow": {},
    "balance": {
        "CURRENT_RATIO": (("balance", "currentRatio", 1.0, "ratio"),),
        "DEBT_ASSET_RATIO": (("balance", "liabilityToAsset", 0.01, "ratio"),),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--landing-root", type=Path, default=PROJECT / "artifacts/cn_financial_reports_eastmoney")
    parser.add_argument("--publication-map", type=Path, default=PROJECT / "artifacts/cn_financial_disclosures_cninfo/publication-map.json")
    parser.add_argument("--lifecycle", type=Path, default=PROJECT / "artifacts/cn_security_lifecycle_akshare/security_lifecycle.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_financial_eastmoney_import/latest.json")
    parser.add_argument("--report-family", choices=("all", *FAMILIES), default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Import completed families/periods for a research diagnostic; never use this for PIT activation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    families = FAMILIES if args.report_family == "all" else (args.report_family,)
    publication = _publication_map(args.publication_map)
    listing_dates = _listing_dates(args.lifecycle)
    rows_by_symbol, stats = _source_rows(args.landing_root, families, publication, listing_dates)
    stats["family_progress"] = _landing_progress(args.landing_root, families)
    stats["matched_symbol_count"] = len(rows_by_symbol)
    stats["publication_map_path"] = str(args.publication_map)
    stats["publication_map_entries"] = len(publication)
    stats["listing_date_symbol_count"] = len(listing_dates)
    stats["report_families"] = list(families)
    stats["research_only"] = True
    stats["formal_pit_verified"] = False
    stats["schema_version"] = SCHEMA_VERSION
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    incomplete_families = [
        family for family, state in stats["family_progress"].items()
        if state["completed_period_count"] < state["target_period_count"]
    ]
    if incomplete_families and not args.allow_partial:
        stats.update({
            "status": "partial",
            "completed_symbol_count": 0,
            "imported_row_count": 0,
            "dry_run": bool(args.dry_run),
            "missing_reason": "landing_families_incomplete:" + ",".join(incomplete_families),
        })
        _atomic_write(args.output, stats)
        print(json.dumps({
            "status": stats["status"],
            "completed_period_count": stats["completed_period_count"],
            "target_period_count": stats["target_period_count"],
            "incomplete_families": incomplete_families,
        }, ensure_ascii=False))
        return 1
    if not rows_by_symbol:
        stats.update({"status": "partial", "completed_symbol_count": 0, "imported_row_count": 0, "missing_reason": "no_cninfo_matched_landing_rows"})
        _atomic_write(args.output, stats)
        print(json.dumps(stats, ensure_ascii=False))
        return 1

    persisted = 0
    completed_symbols = 0
    if not args.dry_run:
        uow = SQLiteUnitOfWork(args.database)
        service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
        try:
            for symbol, rows in sorted(rows_by_symbol.items()):
                now = datetime.now(timezone.utc)
                service.persist(
                    provider="eastmoney_financial_reports",
                    request_id=f"cn-financial-eastmoney-{args.report_family}-{symbol}-{uuid4()}",
                    dataset="cn_financial_eastmoney_research",
                    payload=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(),
                    schema_version=SCHEMA_VERSION,
                    symbol=symbol,
                    available_at=now,
                    received_at=now,
                    market_session="research_backfill",
                    data_tier=DataTier.RESEARCH_PIT,
                )
                persisted += len(rows)
                completed_symbols += 1
                if completed_symbols % 100 == 0:
                    print(f"imported {completed_symbols}/{len(rows_by_symbol)} symbols", flush=True)
        finally:
            uow.close()
    else:
        persisted = sum(len(rows) for rows in rows_by_symbol.values())
        completed_symbols = len(rows_by_symbol)
    stats.update({
        "status": "complete" if (
            completed_symbols == len(rows_by_symbol)
            and stats["completed_period_count"] == stats["target_period_count"]
            and not stats["unmatched_source_row_count"]
        ) else "partial",
        "completed_symbol_count": completed_symbols,
        "imported_row_count": persisted,
        "dry_run": bool(args.dry_run),
        "missing_reason": (
            "official_publication_matched_but_provider_revision_ordering_unverified"
            if stats["completed_period_count"] == stats["target_period_count"] and not stats["unmatched_source_row_count"]
            else "landing_or_cninfo_publication_mapping_incomplete"
        ),
    })
    _atomic_write(args.output, stats)
    print(json.dumps({key: stats[key] for key in ("status", "completed_symbol_count", "imported_row_count", "matched_source_row_count", "unmatched_source_row_count")}, ensure_ascii=False))
    return 0 if stats["status"] == "complete" else 1


def _publication_map(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"publication_map_unreadable:{path}:{type(exc).__name__}") from exc
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SystemExit("publication_map_rows_missing")
    mapped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _symbol(row.get("symbol"))
        period = _period(row.get("report_period"))
        if symbol and period and row.get("published_at"):
            mapped.setdefault((symbol, period), row)
    return mapped


def _listing_dates(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    rows = payload if isinstance(payload, list) else []
    output: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _symbol(row.get("symbol"))
        listed_on = _period(row.get("listed_on"))
        if symbol and listed_on:
            output[symbol] = listed_on
    return output


def _source_rows(
    landing_root: Path,
    families: Iterable[str],
    publication: dict[tuple[str, str], dict[str, Any]],
    listing_dates: dict[str, str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    matched = 0
    unmatched = 0
    completed_periods = 0
    target_periods = 0
    source_rows = 0
    all_source_rows = 0
    outside_current_universe = 0
    pre_listing_source_rows = 0
    current_symbols = {symbol for symbol, _period_key in publication}
    listing_dates = listing_dates or {}
    for family in families:
        for manifest_path in sorted((landing_root / "landing").glob(f"eastmoney-{family}-*/manifest.json"))[-1:]:
            manifest = _read_json(manifest_path)
            periods = manifest.get("periods") if isinstance(manifest, dict) else {}
            if not isinstance(periods, dict):
                continue
            target_periods += len(periods)
            for period_key, state in sorted(periods.items()):
                if not isinstance(state, dict) or state.get("status") != "complete":
                    continue
                completed_periods += 1
                for page_path in sorted((manifest_path.parent / str(period_key)).glob("page-*.json")):
                    envelope = _read_json(page_path)
                    records = envelope.get("normalized_records") if isinstance(envelope, dict) else None
                    if not isinstance(records, list):
                        continue
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        all_source_rows += 1
                        symbol = _symbol(record.get("symbol"))
                        period = _period(record.get("report_period"))
                        if symbol not in current_symbols:
                            outside_current_universe += 1
                            continue
                        if listing_dates.get(symbol) and period < listing_dates[symbol]:
                            pre_listing_source_rows += 1
                            continue
                        source_rows += 1
                        evidence = publication.get((symbol, period))
                        if not symbol or not period or evidence is None:
                            unmatched += 1
                            continue
                        normalized = _canonical_rows(record, family, evidence, envelope)
                        if normalized:
                            output[symbol].extend(normalized)
                            matched += 1
    return dict(output), {
        "completed_period_count": completed_periods,
        "target_period_count": target_periods,
        "source_row_count": source_rows,
        "all_source_row_count": all_source_rows,
        "outside_current_universe_source_row_count": outside_current_universe,
        "pre_listing_source_row_count": pre_listing_source_rows,
        "matched_source_row_count": matched,
        "unmatched_source_row_count": unmatched,
    }


def _landing_progress(landing_root: Path, families: Iterable[str]) -> dict[str, dict[str, int]]:
    """Return period-level completion for every family selected for import."""
    output: dict[str, dict[str, int]] = {}
    for family in families:
        manifests = sorted((landing_root / "landing").glob(f"eastmoney-{family}-*/manifest.json"))
        if not manifests:
            output[family] = {"target_period_count": 0, "completed_period_count": 0}
            continue
        manifest = _read_json(manifests[-1])
        periods = manifest.get("periods") if isinstance(manifest, dict) else {}
        states = [item for item in periods.values() if isinstance(item, dict)] if isinstance(periods, dict) else []
        output[family] = {
            "target_period_count": len(states),
            "completed_period_count": sum(item.get("status") == "complete" for item in states),
        }
    return output


def _canonical_rows(record: dict[str, Any], family: str, evidence: dict[str, Any], envelope: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return []
    symbol = _symbol(record.get("symbol"))
    period = _period(record.get("report_period"))
    source = {
        "code": ("sh." if symbol.startswith(("6", "9")) else "sz.") + symbol,
        "statDate": period,
        "report_period": period,
        "pubDate": evidence.get("published_at"),
        "available_at": None,
        "revision_id": envelope.get("raw_payload_sha256"),
        "source_publication_status": "cninfo_matched_research_assumption",
        "source_provider": "eastmoney_datacenter",
        "source_uri": record.get("source_uri") or envelope.get("source_uri"),
        "source_report_family": family,
        "cninfo_announcement_id": evidence.get("announcement_id"),
        "cninfo_announcement_title": evidence.get("title"),
    }
    rows: list[dict[str, Any]] = []
    for raw_field, destinations in DIRECT_METRICS.get(family, {}).items():
        value = _number(metrics.get(raw_field))
        if value is None:
            continue
        for feature_family, field, scale, unit in destinations:
            rows.append({
                **source,
                "feature_family": feature_family,
                field: value * scale,
                "unit": unit,
                "source_metric_label": raw_field,
                "source_value_field": raw_field,
            })
    if family == "income":
        revenue = _number(metrics.get("TOTAL_OPERATE_INCOME"))
        profit = _number(metrics.get("PARENT_NETPROFIT"))
        if revenue is not None and revenue != 0 and profit is not None:
            rows.append({
                **source,
                "feature_family": "profit",
                "npMargin": profit / revenue,
                "unit": "ratio",
                "source_metric_label": "PARENT_NETPROFIT/TOTAL_OPERATE_INCOME",
                "source_value_field": "derived_from_same_statement_row",
            })
    return rows


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _symbol(value: object) -> str:
    text = str(value or "").strip().upper().rsplit(".", 1)[-1]
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else ""


def _period(value: object) -> str:
    text = str(value or "")[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else ""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object_expected:{path}")
    return value


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
