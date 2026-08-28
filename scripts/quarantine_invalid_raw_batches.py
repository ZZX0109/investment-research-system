#!/usr/bin/env python3
"""Reject malformed immutable raw batches after a validated replacement exists.

Raw bytes are never deleted.  The catalog row is marked ``rejected`` with the
audit findings, so downstream manifests ignore it while the quarantine report
keeps a recoverable lineage reference.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from investment_research.training.snapshot_landing import audit_file_contents

PROJECT = Path(__file__).resolve().parents[1]


def quarantine(database: Path, raw_root: Path, output: Path) -> dict:
    connection = sqlite3.connect(database)
    rows = connection.execute(
        "SELECT id,provider,dataset,payload_json,quality_status FROM raw_data_batches"
    ).fetchall()
    findings: list[dict] = []
    try:
        for batch_id, provider, dataset, payload_json, quality_status in rows:
            if quality_status == "rejected":
                try:
                    payload = json.loads(payload_json)
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                findings.append({
                    "batch_id": batch_id,
                    "provider": provider,
                    "dataset": dataset,
                    "symbol": payload.get("symbol"),
                    "payload_ref": payload.get("payload_ref"),
                    "quality_issues": payload.get("quality_issues", []),
                    "audit": {"status": "already_rejected"},
                })
                continue
            try:
                payload = json.loads(payload_json)
            except (TypeError, json.JSONDecodeError):
                continue
            reference = str(payload.get("payload_ref", "")).removeprefix("file-object://")
            path = (raw_root / reference).resolve() if reference else None
            if path is None or not path.is_file():
                continue
            result = audit_file_contents(path, dataset=str(dataset), symbol_hint=payload.get("symbol"))
            errors = {
                key: value for key, value in result.items()
                if key.endswith("_count") and key != "row_count" and value not in (None, 0)
            }
            if result.get("schema_valid") is not True or errors:
                payload["quality_issues"] = sorted({*payload.get("quality_issues", []), *errors.keys()})
                payload["quarantine_reason"] = "content_audit_failed"
                payload["quarantined_at"] = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "UPDATE raw_data_batches SET quality_status=?, payload_json=? WHERE id=?",
                    ("rejected", json.dumps(payload, ensure_ascii=False), batch_id),
                )
                findings.append({
                    "batch_id": batch_id,
                    "provider": provider,
                    "dataset": dataset,
                    "symbol": payload.get("symbol"),
                    "payload_ref": payload.get("payload_ref"),
                    "quality_issues": payload.get("quality_issues", []),
                    "audit": result,
                })
        connection.commit()
    finally:
        connection.close()
    report = {
        "schema_version": "raw-quarantine-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "raw_files_deleted": 0,
        "rejected_batch_count": len(findings),
        "findings": findings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "rejected_batch_count": len(findings)}, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/data_quarantine/latest.json")
    args = parser.parse_args()
    quarantine(args.database, args.raw_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
