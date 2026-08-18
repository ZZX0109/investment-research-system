#!/usr/bin/env python3
"""Safely materialize the four long-term model readings.

The command is deliberately dry-run by default.  It never discovers input
data from ``var/cn-research`` and it refuses paths that could be written by a
download or that belong to an active snapshot.  A real inference run must be
given an explicit, already-frozen JSON sequence artifact produced after the
snapshot/PIT gates have passed.

Input shape::

    {"schema_version": "long-term-sequence-input-v1",
     "examples_by_task": {"excess_return_120d": [{...}], ...}}

Alternatively, pass ``--samples`` with ``{"schema_version":
"long-term-sample-input-v1", "samples": [{...}]}``; the service then builds
the latest aligned 20-session windows for all four tasks from those frozen PIT
rows.

Each example is the JSON representation of ``SequenceExample``.  JSON is
used intentionally instead of pickle so a dry-run or CI check cannot execute
arbitrary code from a cache file.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.deep_long_term import (  # noqa: E402
    DeepLongTermArtifactError,
    DeepLongTermInferenceService,
    LONG_TERM_TASKS,
    load_deep_long_term_registry_summary,
)
from investment_research.training.sequence_dataset import SequenceExample  # noqa: E402
from investment_research.training.models import TrainingSample  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path, help="frozen JSON sequence artifact")
    inputs.add_argument(
        "--samples", type=Path,
        help="frozen JSON/JSONL sample artifact; the service builds the latest aligned 20-session windows",
    )
    parser.add_argument(
        "--as-of", type=str, default=None,
        help="optional timezone-aware ISO cutoff for latest-window construction",
    )
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument(
        "--execute", action="store_true",
        help="load the four models and atomically write artifacts/long_term_model_readings/latest.json",
    )
    return parser.parse_args()


def _guard_input_path(project_root: Path, input_path: Path) -> Path:
    root = project_root.resolve()
    path = input_path.expanduser().resolve()
    artifacts = (root / "artifacts").resolve()
    if artifacts != path and artifacts not in path.parents:
        raise DeepLongTermArtifactError("sequence_input_must_be_under_artifacts")
    protected_names = {"landing", "raw", "standard", "pit", "active"}
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.name in protected_names or "active" in parent.name.lower():
            raise DeepLongTermArtifactError("sequence_input_protected_or_active_path")
    if path.suffix.lower() not in {".json", ".jsonl"}:
        raise DeepLongTermArtifactError("sequence_input_json_required")
    if not path.is_file():
        raise DeepLongTermArtifactError("sequence_input_file_missing")
    return path


def _load_examples(project_root: Path, input_path: Path) -> dict[str, list[SequenceExample]]:
    path = _guard_input_path(project_root, input_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepLongTermArtifactError("sequence_input_json_invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "long-term-sequence-input-v1":
        raise DeepLongTermArtifactError("sequence_input_schema_invalid")
    raw_groups = payload.get("examples_by_task")
    if not isinstance(raw_groups, dict) or set(raw_groups) != set(LONG_TERM_TASKS):
        raise DeepLongTermArtifactError("sequence_input_tasks_incomplete")
    groups: dict[str, list[SequenceExample]] = {}
    for task in LONG_TERM_TASKS:
        rows = raw_groups.get(task)
        if not isinstance(rows, list) or not rows:
            raise DeepLongTermArtifactError(f"sequence_input_task_empty:{task}")
        try:
            validator = getattr(SequenceExample, "model_validate", None)
            groups[task] = [
                (validator(row) if validator else SequenceExample.parse_obj(row))
                for row in rows
            ]
        except Exception as exc:  # Pydantic version-independent fail-closed boundary.
            raise DeepLongTermArtifactError(f"sequence_input_example_invalid:{task}") from exc
    return groups


def _load_samples(project_root: Path, input_path: Path) -> list[TrainingSample]:
    """Load an explicit frozen sample artifact without touching active data."""
    path = _guard_input_path(project_root, input_path)
    try:
        if path.suffix.lower() == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            payload = rows
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepLongTermArtifactError("sample_input_json_invalid") from exc
    if isinstance(payload, dict):
        if payload.get("schema_version") != "long-term-sample-input-v1":
            raise DeepLongTermArtifactError("sample_input_schema_invalid")
        rows = payload.get("samples")
    else:
        rows = payload
    if not isinstance(rows, list) or not rows:
        raise DeepLongTermArtifactError("sample_input_empty")
    try:
        validator = getattr(TrainingSample, "model_validate", None)
        samples = [validator(row) if validator else TrainingSample.parse_obj(row) for row in rows]
    except Exception as exc:  # Pydantic version-independent fail-closed boundary.
        raise DeepLongTermArtifactError("sample_input_row_invalid") from exc
    return samples


def _parse_as_of(value: str | None):
    if value is None:
        return None
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeepLongTermArtifactError("as_of_timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeepLongTermArtifactError("as_of_timestamp_timezone_missing")
    return parsed


def _summary(project_root: Path, registry: Path | None) -> dict[str, Any]:
    summary = load_deep_long_term_registry_summary(project_root=project_root, registry_path=registry)
    return {
        "status": summary.get("status"),
        "deployment_ready": summary.get("deployment_ready"),
        "model_count": len(summary.get("models") or []),
        "candidate_count": summary.get("candidate_count", 0),
        "tasks": [item.get("task") for item in summary.get("models") or []],
        "blocking_reasons": summary.get("blocking_reasons", []),
    }


def main() -> int:
    args = _args()
    root = args.project_root.resolve()
    try:
        result: dict[str, Any] = {
            "schema_version": "long-term-model-readings-run-v1",
            "mode": "execute" if args.execute else "dry_run",
            "project_root": str(root),
            "registry": str(args.registry.resolve()) if args.registry else None,
            "registry_summary": _summary(root, args.registry),
        }
        if args.input is None and args.samples is None:
            if args.execute:
                raise DeepLongTermArtifactError("execute_requires_explicit_json_input_or_samples")
            result["input_status"] = "not_supplied_dry_run_only"
        elif args.input is not None:
            groups = _load_examples(root, args.input)
            result["input"] = str(_guard_input_path(root, args.input))
            result["example_counts"] = {task: len(groups[task]) for task in LONG_TERM_TASKS}
            result["input_status"] = "validated"
            if args.execute:
                output = DeepLongTermInferenceService(root, registry_path=args.registry).predict_all_and_persist(groups)
                result["output"] = str(output)
                result["output_status"] = "written_atomically"
        else:
            samples = _load_samples(root, args.samples)
            result["samples"] = str(_guard_input_path(root, args.samples))
            result["sample_count"] = len(samples)
            result["input_status"] = "validated"
            if args.execute:
                output = DeepLongTermInferenceService(root, registry_path=args.registry).predict_latest_from_samples(
                    samples,
                    as_of=_parse_as_of(args.as_of),
                )
                result["output"] = str(output)
                result["output_status"] = "written_atomically"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except DeepLongTermArtifactError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
