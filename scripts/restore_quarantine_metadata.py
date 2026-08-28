#!/usr/bin/env python3
"""Undo the first quarantine pass when it only recorded row-count metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

PROJECT = Path(__file__).resolve().parents[1]


def restore(database: Path) -> int:
    connection = sqlite3.connect(database)
    rows = connection.execute(
        "SELECT id,payload_json FROM raw_data_batches WHERE quality_status='rejected'"
    ).fetchall()
    restored = 0
    try:
        for batch_id, payload_json in rows:
            payload = json.loads(payload_json)
            if payload.get("quality_issues") != ["row_count"]:
                continue
            payload.pop("quality_issues", None)
            payload.pop("quarantine_reason", None)
            payload.pop("quarantined_at", None)
            connection.execute(
                "UPDATE raw_data_batches SET quality_status=?, payload_json=? WHERE id=?",
                ("passed", json.dumps(payload, ensure_ascii=False), batch_id),
            )
            restored += 1
        connection.commit()
    finally:
        connection.close()
    print(json.dumps({"status": "restored", "batch_count": restored}, ensure_ascii=False))
    return restored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    args = parser.parse_args()
    restore(args.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
