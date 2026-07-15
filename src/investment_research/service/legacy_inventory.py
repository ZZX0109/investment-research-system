from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


QUARANTINE_REASON = "legacy_four_market_public_data"
BLOCKED_PROVIDERS = ("yfinance", "sec", "hkex", "fred")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(root: Path, directories: list[Path]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            provider = next(
                (name for name in BLOCKED_PROVIDERS if name in relative.lower()),
                "unknown_public_provider",
            )
            entries.append(
                {
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                    "provider": provider,
                    "classification": QUARANTINE_REASON,
                    "eligible_for_cn_training": False,
                }
            )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "legacy-public-data-inventory-v1",
        "classification": QUARANTINE_REASON,
        "data_tier": "research_pit",
        "time_semantics": "legacy_time_semantics",
        "eligible_for_cn_training": False,
        "entry_count": len(entries),
        "total_size_bytes": sum(entry["size_bytes"] for entry in entries),
        "content_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "entries": entries,
    }
