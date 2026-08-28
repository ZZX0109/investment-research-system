#!/usr/bin/env python3
"""Materialize an explicit, assumption-labeled CN financial PIT research layer."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

PROJECT = Path(__file__).resolve().parents[1]


def main() -> int:
    output = PROJECT / "artifacts/cn_financial_disclosures_cninfo"
    publication = json.loads((output / "publication-map.json").read_text(encoding="utf-8"))
    mapping = {(str(row["symbol"]).zfill(6), row["report_period"]): row for row in publication.get("rows", [])}
    raw_root = PROJECT / "var/cn-research/raw"
    con = sqlite3.connect(PROJECT / "var/cn-research/catalog.db")
    batches = con.execute(
        "SELECT dataset,payload_json FROM raw_data_batches "
        "WHERE dataset IN ('cn_fundamentals_research','cn_financial_ratios_akshare_research')"
    ).fetchall()
    con.close()
    output.mkdir(parents=True, exist_ok=True)
    stats = {}
    sources = (
        ("cn_fundamentals_research", "fundamentals_pit_reconciled.jsonl", _catalog_records(batches, "cn_fundamentals_research", raw_root)),
        ("cn_financial_ratios_akshare_research", "ratios_pit_reconciled.jsonl", _catalog_records(batches, "cn_financial_ratios_akshare_research", raw_root)),
        # The all-market batch collector lives in immutable landing files
        # rather than the SQLite catalog while it is being downloaded.  It is
        # reconciled by the same evidence map and remains research-only.
        ("cn_financial_reports_eastmoney_landing", "eastmoney_reports_pit_reconciled.jsonl", _eastmoney_landing_records()),
    )
    for dataset, filename, records_by_batch in sources:
        path = output / filename
        rows = 0
        matched = 0
        cells: set[tuple[str, str]] = set()
        matched_cells: set[tuple[str, str]] = set()
        provider_available_count = 0
        provider_revision_count = 0
        with path.open("w", encoding="utf-8") as handle:
            for metadata, records in records_by_batch:
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    symbol = str(record.get("code") or record.get("symbol") or metadata.get("symbol") or "").rsplit(".", 1)[-1].zfill(6)
                    period = str(record.get("statDate") or record.get("report_period") or "")[:10]
                    key = (symbol, period)
                    evidence = mapping.get(key)
                    row = dict(record)
                    row.update({
                        "symbol": symbol,
                        "report_period": period,
                        "raw_batch_id": metadata.get("id"),
                        "source_provider": record.get("source_provider") or metadata.get("provider"),
                        "report_family": record.get("report_family") or metadata.get("report_family"),
                        "source_payload_ref": metadata.get("payload_ref"),
                        "source_payload_hash": metadata.get("payload_hash"),
                        "source_uri": _source_uri(dataset, symbol, record),
                        "provider_fetched_at": record.get("fetched_at") or metadata.get("fetched_at"),
                        "provider_received_at": record.get("received_at") or metadata.get("received_at"),
                        "provider_available_at": record.get("available_at") or metadata.get("available_at"),
                        # A provider-side revision identifier is only accepted
                        # when the source actually supplies one.  We do not
                        # synthesize a revision number from the statement
                        # period, because that would falsely prove restatement
                        # ordering.
                        "provider_revision_id": (
                            record.get("revision_id")
                            or record.get("revision")
                            or record.get("版本")
                            or record.get("公告编号")
                        ),
                        "cninfo_published_at": evidence.get("published_at") if evidence else None,
                        "pit_available_at_assumption": evidence.get("published_at") if evidence else None,
                        "pit_join_status": "matched_announcement_time" if evidence else "unmatched_announcement_time",
                        "pit_time_semantics": "cninfo_announcement_timestamp_as_availability_assumption",
                        "research_only": True,
                    })
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    rows += 1
                    provider_available_count += bool(row.get("provider_available_at"))
                    provider_revision_count += bool(row.get("provider_revision_id"))
                    cells.add(key)
                    if evidence:
                        matched += 1
                        matched_cells.add(key)
        stats[dataset] = {
            "path": str(path),
            "row_count": rows,
            "symbol_period_count": len(cells),
            "matched_row_count": matched,
            "matched_symbol_period_count": len(matched_cells),
            "row_match_coverage": matched / rows if rows else 0.0,
            "symbol_period_match_coverage": len(matched_cells) / len(cells) if cells else 0.0,
            "provider_available_at_row_coverage": provider_available_count / rows if rows else 0.0,
            "provider_revision_id_row_coverage": provider_revision_count / rows if rows else 0.0,
        }
    report = {
        "schema_version": "cn-financial-pit-reconciled-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_assumption_layer",
        "research_only": True,
        "deployment_ready": False,
        "availability_assumption": "CNINFO announcement timestamp is treated as the earliest public visibility time",
        "formal_pit_verified": False,
        "datasets": stats,
        "missing_reason": "statement revision history and provider-level available_at reconciliation are not verified",
    }
    (output / "pit-reconciled-latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _catalog_records(batches: list[tuple[str, str]], dataset: str, raw_root: Path):
    """Yield catalog payloads lazily so large financial batches stay bounded."""
    for dataset_name, metadata_json in batches:
        if dataset_name != dataset:
            continue
        metadata = json.loads(metadata_json)
        reference = str(metadata.get("payload_ref") or "")
        try:
            payload = json.loads((raw_root / reference.removeprefix("file-object://")).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        records = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
        if isinstance(records, list):
            yield metadata, records


def _eastmoney_landing_records():
    """Yield completed immutable landing pages from every financial family."""
    base = PROJECT / "artifacts" / "cn_financial_reports_eastmoney"
    manifests: set[Path] = set()
    for family in ("performance", "income", "cashflow", "balance"):
        latest_path = base / ("latest.json" if family == "performance" else f"{family}-latest.json")
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            latest = {}
        reference = latest.get("landing_manifest") if isinstance(latest, dict) else None
        path = PROJECT / str(reference) if isinstance(reference, str) else None
        if path and path.is_file():
            manifests.add(path)
        else:
            manifests.update((base / "landing").glob(f"eastmoney-{family}-*/manifest.json"))
    for manifest_path in sorted(manifests):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        periods = manifest.get("periods") if isinstance(manifest, dict) else {}
        if not isinstance(periods, dict):
            continue
        for period, state in sorted(periods.items()):
            if not isinstance(state, dict) or state.get("status") != "complete":
                continue
            for page_path in sorted(manifest_path.parent.joinpath(str(period)).glob("page-*.json")):
                try:
                    envelope = json.loads(page_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                records = envelope.get("normalized_records") if isinstance(envelope, dict) else None
                if not isinstance(records, list):
                    continue
                metadata = {
                    "id": f"eastmoney-landing:{manifest.get('run_id')}:{period}:{page_path.stem}",
                    "provider": envelope.get("provider"),
                    "report_family": envelope.get("report_family") or manifest.get("report_family") or "performance",
                    "payload_ref": str(page_path.relative_to(PROJECT)),
                    "payload_hash": envelope.get("raw_payload_sha256"),
                    "fetched_at": envelope.get("fetched_at"),
                    "received_at": envelope.get("fetched_at"),
                    "available_at": None,
                }
                yield metadata, records


def _source_uri(dataset: str, symbol: str, record: dict) -> str | None:
    explicit = record.get("source_uri") or record.get("source_url")
    if isinstance(explicit, str) and explicit:
        return explicit
    if dataset == "cn_financial_ratios_akshare_research":
        return f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{symbol}.phtml"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
