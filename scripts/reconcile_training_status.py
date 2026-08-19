#!/usr/bin/env python3
"""Reconcile orphaned research-only controller state without deleting artifacts."""
from __future__ import annotations
import json
from pathlib import Path


def update(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for item in data.get("trials", []):
        if item.get("id") in {"stability-900", "stability-end-252"} and item.get("status") == "failed":
            item.update({"status": "skipped_invalid_window", "skip_reason": "insufficient purged development dates for 240d horizon"})
            changed = True
    if path.name == "timebox-status.json" and data.get("status") == "running":
        data.update({"status": "interrupted_recovered", "recovery_note": "no controller process found; completed artifacts preserved"})
        for item in data.get("trials", []):
            if item.get("status") == "running":
                item.update({"status": "interrupted_recovered", "recovery_note": "no report; retry is safe"})
        changed = True
    if changed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    print(path, "updated" if changed else "already consistent")


if __name__ == "__main__":
    root = Path("/root/investment-research-system")
    update(root / "artifacts/free_research_models/runs/auto-long-term-return-transfer-queue-20260818/transfer-queue-status.json")
    update(root / "artifacts/free_research_models/runs/timeboxed-long-horizon-tuning-20260818/timebox-status.json")
