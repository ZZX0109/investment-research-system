#!/usr/bin/env python3
"""Export and validate the sample manifest list bound to one rebuild index."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rebuild_path = _resolve(args.rebuild_index)
    rebuild = json.loads(rebuild_path.read_text(encoding="utf-8"))
    context = rebuild.get("contexts", {}).get("close_confirmed", {})
    refs = [
        str(ref)
        for values in (context.get("sample_manifests", {}) or {}).values()
        if isinstance(values, list)
        for ref in values
    ]
    if not refs:
        raise SystemExit("rebuild index contains no close_confirmed sample manifests")
    missing = [
        ref for ref in refs
        if not _resolve(ref).is_file()
    ]
    if missing:
        raise SystemExit(f"sample manifest files are missing: {len(missing)}")
    body = {
        "schema_version": "research-only-bound-manifest-list-v2",
        "rebuild_index": str(rebuild_path),
        "market_snapshot_id": context.get("snapshot_id"),
        "market_snapshot_hash": context.get("snapshot_hash"),
        "sample_manifest_count": len(refs),
        "sample_manifests": refs,
        "data_tier": rebuild.get("data_tier"),
        "formal_pit_eligible": rebuild.get("formal_pit_eligible"),
        "deployment_ready": rebuild.get("deployment_ready"),
    }
    body["manifest_list_hash"] = hashlib.sha256(
        json.dumps(refs, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    output = _resolve(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
