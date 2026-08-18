#!/usr/bin/env python3
"""Apply a verified incremental rebuild plan to an artifact index.

The command only updates the content-addressed index. It never deletes files,
changes an active snapshot, or replaces a model. Artifacts selected by explicit
symbol/date/snapshot/model lineage become ``rebuild_required`` until a new
artifact is registered.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.artifacts import (  # noqa: E402
    invalidate_artifacts_for_plan,
    read_index,
    validate_index,
    write_index,
)


def _plan_hash(payload: dict) -> str:
    without_hash = dict(payload)
    without_hash.pop("plan_hash", None)
    encoded = json.dumps(without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output-index", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    try:
        plan_path = args.plan.resolve()
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(plan_payload, dict) or plan_payload.get("schema_version") != "incremental-rebuild-plan-v1":
            raise ValueError("incremental rebuild plan schema is invalid")
        if plan_payload.get("plan_hash") != _plan_hash(plan_payload):
            raise ValueError("incremental rebuild plan hash mismatch")
        index_path = args.index.resolve()
        index = read_index(index_path)
        integrity = validate_index(index_path.parent, index)
        if integrity:
            raise ValueError("artifact index integrity failed: " + ";".join(integrity[:8]))
        updated, affected = invalidate_artifacts_for_plan(
            index,
            plan_payload,
            invalidated_at=datetime.now(timezone.utc),
        )
        output_index = (args.output_index or index_path).resolve()
        if output_index == index_path and output_index.name == "active.json":
            raise ValueError("active pointer cannot be used as an artifact index")
        write_index(updated, output_index)
        report = {
            "schema_version": "incremental-rebuild-application-v1",
            "status": "applied",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plan_ref": str(plan_path),
            "plan_hash": plan_payload["plan_hash"],
            "input_index": str(index_path),
            "output_index": str(output_index),
            "affected_artifact_ids": affected,
            "affected_artifact_count": len(affected),
            "notes": [
                "No data file, model file, active pointer, or snapshot was deleted or replaced.",
                "Rebuild consumers must register replacement artifacts before clearing rebuild_required.",
            ],
        }
        report_path = (args.report or output_index.with_name("incremental-rebuild-application.json")).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
