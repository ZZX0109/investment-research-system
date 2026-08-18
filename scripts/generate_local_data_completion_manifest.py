#!/usr/bin/env python3
"""Create the reproducible local-data handoff manifest used before server sync."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

PATHS = [
    "var/cn-research",
    "artifacts/cn_financial_ratios_akshare",
    "artifacts/cn_security_lifecycle_akshare",
    "artifacts/cn_security_master",
    "artifacts/cn_event_backfill_full",
    "artifacts/cn_event_backfill",
    "artifacts/cn_financial_disclosures_cninfo",
    "artifacts/cn_financial_disclosures_cninfo_recheck",
    "artifacts/cn_security_status_disclosures_cninfo",
    "artifacts/cn_security_name_history_sina",
    "artifacts/cn_macro_release_calendar_nbs",
    "artifacts/subagent_financial_pit",
    "artifacts/subagent_security_status",
    "artifacts/subagent_macro_release",
    "artifacts/subagent_membership_breadth",
    "artifacts/cn_financial_coverage",
    "artifacts/cn_data_completion_audit",
    "artifacts/cn_research_auxiliary",
    "artifacts/download_manifests/latest.json",
    "docs/server-data-inventory-20260817.md",
]


def describe(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path.relative_to(PROJECT)), "exists": False, "file_count": 0, "bytes": 0, "sha256": None}
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    digest = None
    if path.is_file() and total <= 64 * 1024 * 1024:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path.relative_to(PROJECT)),
        "exists": True,
        "file_count": len(files),
        "bytes": total,
        "sha256": digest,
    }


def main() -> int:
    manifest = {
        "schema_version": "local-data-completion-manifest-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "downloaded_local_pending_server_sync",
        "paths": [describe(PROJECT / rel) for rel in PATHS],
        "notes": [
            "No GPU or paid server required for local downloads.",
            "Strict PIT remains blocked where public sources do not expose verified historical publication/availability semantics.",
            "historical_universe_memberships uses an explicit listing-date availability assumption and remains degraded.",
            "CNINFO security-status announcements are evidence only and do not establish daily ST/suspension state.",
        ],
    }
    out = PROJECT / "artifacts/local_data_completion_manifest_20260817.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    print("total_bytes", sum(item["bytes"] for item in manifest["paths"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
