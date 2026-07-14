#!/usr/bin/env python3
"""Model card rollback tool — restore a versioned model_cards.json.

Usage:
  python scripts/rollback.py --to v3          # rollback to version v3
  python scripts/rollback.py --list           # list available versions
"""
from __future__ import annotations

import json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "output"
VERSIONS = OUTPUT / "versions"


def list_versions():
    index_path = VERSIONS / "version_index.json"
    if not index_path.exists():
        print("No versions found.")
        return []
    return json.loads(index_path.read_text())


def rollback(target_version: str) -> bool:
    index = list_versions()
    if not index:
        print("No version history. Nothing to roll back.")
        return False

    entry = next((e for e in index if e["version"] == target_version), None)
    if not entry:
        print(f"Version '{target_version}' not found.")
        print("Available versions:")
        for e in index:
            print(f"  {e['version']} — {e['created_at']}")
        return False

    src = Path(entry["file"])
    if not src.exists():
        print(f"ERROR: Version file missing: {src}")
        return False

    dst = OUTPUT / "model_cards.json"
    if dst.exists():
        backup = VERSIONS / f"model_cards_before_rollback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(dst, backup)
        print(f"Current version saved to: {backup}")

    shutil.copy2(src, dst)
    print(f"Rollback complete: model_cards.json → {target_version}")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rollback model cards to a previous version.")
    parser.add_argument("--to", help="Version tag to restore (e.g., v3)")
    parser.add_argument("--list", action="store_true", help="Show all available versions")
    args = parser.parse_args()

    versions = list_versions()

    if args.list:
        if versions:
            for v in versions:
                print(f"  {v['version']} — {v['created_at']}")
        else:
            print("No model card versions found.")
        sys.exit(0)

    if not args.to:
        parser.print_help()
        sys.exit(1)

    ok = rollback(args.to)
    sys.exit(0 if ok else 1)
