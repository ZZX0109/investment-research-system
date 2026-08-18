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
    for dataset in ("cn_fundamentals_research", "cn_financial_ratios_akshare_research"):
        path = output / ("fundamentals_pit_reconciled.jsonl" if dataset == "cn_fundamentals_research" else "ratios_pit_reconciled.jsonl")
        rows = 0
        matched = 0
        cells: set[tuple[str, str]] = set()
        matched_cells: set[tuple[str, str]] = set()
        with path.open("w", encoding="utf-8") as handle:
            for dataset_name, metadata_json in batches:
                if dataset_name != dataset:
                    continue
                metadata = json.loads(metadata_json)
                reference = str(metadata.get("payload_ref") or "")
                payload = json.loads((raw_root / reference.removeprefix("file-object://")).read_text(encoding="utf-8"))
                records = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
                if not isinstance(records, list):
                    continue
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    symbol = str(record.get("code") or metadata.get("symbol") or "").rsplit(".", 1)[-1].zfill(6)
                    period = str(record.get("statDate") or "")[:10]
                    key = (symbol, period)
                    evidence = mapping.get(key)
                    row = dict(record)
                    row.update({
                        "symbol": symbol,
                        "report_period": period,
                        "cninfo_published_at": evidence.get("published_at") if evidence else None,
                        "pit_available_at_assumption": evidence.get("published_at") if evidence else None,
                        "pit_join_status": "matched_announcement_time" if evidence else "unmatched_announcement_time",
                        "pit_time_semantics": "cninfo_announcement_timestamp_as_availability_assumption",
                        "research_only": True,
                    })
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    rows += 1
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


if __name__ == "__main__":
    raise SystemExit(main())
