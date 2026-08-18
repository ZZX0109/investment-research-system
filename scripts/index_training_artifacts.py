#!/usr/bin/env python3
"""Build and verify a compact content-addressed training artifact index."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.artifacts import (
    ArtifactIndex,
    discover_local_references,
    register_artifact,
    validate_index,
    write_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="artifact directory to index")
    parser.add_argument("--output", type=Path, required=True, help="index JSON path")
    parser.add_argument("--kind", default="research_artifact")
    parser.add_argument("--retention-days", type=int, default=365)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"artifact root is not a directory: {root}")
    retention = datetime.now(timezone.utc) + timedelta(days=args.retention_days)
    paths = [
        path for path in sorted(root.rglob("*"))
        if path.is_file() and path.resolve() != args.output.resolve()
    ]
    records = [
        register_artifact(root, path, kind=args.kind, retention_until=retention)
        for path in paths
    ]
    records = [
        record.model_copy(update={
            "references": discover_local_references(root, root / record.relative_path)
        })
        for record in records
    ]
    index = ArtifactIndex(generated_at=datetime.now(timezone.utc), artifacts=records)
    write_index(index, args.output)
    errors = validate_index(root, index)
    print({"status": "ready" if not errors else "blocked", "artifact_count": len(records), "errors": errors})
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
