#!/usr/bin/env python3
"""List or explicitly remove expired unreferenced training artifacts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.artifacts import read_index, validate_index, write_index


def _reference_keys(root: Path, reference: str) -> set[str]:
    """Resolve a local reference to the index keys it may identify."""
    if not isinstance(reference, str) or not reference or urlparse(reference).scheme:
        return set()
    keys = {reference}
    candidate = Path(reference)
    options = [candidate]
    if candidate.parts and candidate.parts[0] == root.name:
        options.append(Path(*candidate.parts[1:]))
    for option in options:
        try:
            resolved = option.resolve() if option.is_absolute() else (root / option).resolve()
            if root.resolve() in resolved.parents:
                keys.add(resolved.relative_to(root.resolve()).as_posix())
        except (OSError, ValueError):
            continue
    return keys


def _expired_unreferenced(index, root: Path, now: datetime, *, include_rebuild_required: bool = False):
    """Return safe cleanup candidates without following only outgoing refs.

    A report's ``references`` are outgoing edges.  The old implementation
    checked only that field on the candidate itself, so it could remove a
    prediction file that another report still referenced.  Build reverse
    edges first and retain invalidated artifacts unless cleanup is explicitly
    widened by the caller.
    """
    incoming: set[str] = set()
    for owner in index.artifacts:
        for reference in owner.references:
            incoming.update(_reference_keys(root, reference))
    candidates = []
    for item in index.artifacts:
        if not item.retention_until or item.retention_until > now:
            continue
        if item.references:
            continue
        if not include_rebuild_required and item.lifecycle == "rebuild_required":
            continue
        if item.artifact_id in incoming or item.relative_path in incoming:
            continue
        candidates.append(item)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="delete expired unreferenced files")
    parser.add_argument(
        "--include-rebuild-required",
        action="store_true",
        help="also allow cleanup of invalidated artifacts (default: retain for replay)",
    )
    args = parser.parse_args()
    index = read_index(args.index)
    integrity = validate_index(args.root, index)
    if integrity:
        print({"status": "blocked", "integrity_errors": integrity})
        return 2
    now = datetime.now(timezone.utc)
    expired = _expired_unreferenced(
        index,
        args.root,
        now,
        include_rebuild_required=args.include_rebuild_required,
    )
    if args.apply:
        for item in expired:
            path = (args.root / item.relative_path).resolve()
            if args.root.resolve() not in path.parents:
                raise SystemExit(f"refusing path outside root: {path}")
            path.unlink()
        remaining = [item for item in index.artifacts if item not in expired]
        write_index(index.model_copy(update={"generated_at": now, "artifacts": remaining}), args.index)
    print({"status": "pruned" if args.apply else "dry_run", "expired_count": len(expired), "paths": [item.relative_path for item in expired]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
