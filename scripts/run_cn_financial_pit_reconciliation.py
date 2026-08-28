#!/usr/bin/env python3
"""Build and audit the CN financial publication/PIT reconciliation chain.

The command is intentionally non-activating.  It rebuilds the publication map,
materializes the assumption-labelled PIT layer, and refreshes field coverage;
formal eligibility remains false until an authoritative available-at and
revision contract is verified.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_financial_disclosures_cninfo/pit-reconciliation-run.json")
    args = parser.parse_args()
    commands = [
        [sys.executable, "scripts/build_cn_financial_publication_map.py"],
        [sys.executable, "scripts/reconcile_cn_financial_pit.py"],
        [sys.executable, "scripts/audit_cn_financial_coverage.py"],
    ]
    results: list[dict] = []
    for command in commands:
        completed = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, check=False)
        results.append({
            "command": command,
            "return_code": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        })
    pit_path = PROJECT / "artifacts/cn_financial_disclosures_cninfo/pit-reconciled-latest.json"
    try:
        pit = json.loads(pit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        pit = {}
    payload = {
        "schema_version": "cn-financial-pit-reconciliation-run-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if pit.get("formal_pit_verified") is True and all(item["return_code"] == 0 for item in results) else "blocked",
        "formal_pit_verified": pit.get("formal_pit_verified", False),
        "deployment_ready": False,
        "pit_report_ref": str(pit_path),
        "steps": results,
        "missing_reason": pit.get("missing_reason") or "pit_reconciliation_report_missing",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "formal_pit_verified": payload["formal_pit_verified"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if payload["status"] == "complete" else 2

if __name__ == "__main__":
    raise SystemExit(main())
