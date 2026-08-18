#!/usr/bin/env python3
"""Register the downloaded four-task models as immutable research artifacts.

The command never copies model files and never changes a model, snapshot or
active pointer.  Without ``--write`` it only validates the roster and prints
the registration payload; ``--write`` atomically writes a reference manifest
under ``artifacts/long_term_model_registry``.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.deep_long_term import (  # noqa: E402
    DeepLongTermArtifactError,
    build_deep_long_term_artifact_manifest,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="atomically write the registration manifest")
    return parser.parse_args()


def _safe_output(root: Path, output: Path) -> Path:
    target = output.expanduser().resolve()
    expected = (root / "artifacts" / "long_term_model_registry").resolve()
    if target != expected and expected not in target.parents:
        raise DeepLongTermArtifactError("artifact_registration_output_outside_artifacts")
    if target.suffix.lower() != ".json" or target.name.startswith("."):
        raise DeepLongTermArtifactError("artifact_registration_output_invalid")
    protected = {"landing", "raw", "standard", "pit", "active", "snapshots"}
    if any(parent.name in protected for parent in (target, *target.parents)):
        raise DeepLongTermArtifactError("artifact_registration_output_protected")
    return target


def _write_atomic(target: Path, payload: dict) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return target


def main() -> int:
    args = _parse_args()
    root = args.project_root.resolve()
    try:
        payload = build_deep_long_term_artifact_manifest(
            project_root=root,
            registry_path=args.registry,
            generated_at=datetime.now(timezone.utc),
        )
        if args.write:
            target = _safe_output(
                root,
                args.output or (root / "artifacts" / "long_term_model_registry" / "latest.json"),
            )
            _write_atomic(target, payload)
            payload = {"status": "written", "output": str(target), "task_count": payload["task_count"], "tasks": payload["tasks"]}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (DeepLongTermArtifactError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
