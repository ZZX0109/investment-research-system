#!/usr/bin/env python3
"""Run snapshot-bound research sample generation in resumable batches.

Each invocation processes one or more symbol batches into an isolated staging
directory.  It never changes the canonical rebuild pointer; promotion is done
explicitly with ``merge_cn_research_sample_batches.py`` after every batch has
passed validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON artifact: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON artifact must be an object: {path}")
    return value


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT / path


def _symbols(index: dict, cohort: str) -> list[str]:
    refs = index.get("cohort_refs", {})
    ref = refs.get(cohort) if isinstance(refs, dict) else None
    if not ref:
        raise SystemExit(f"base index has no cohort ref: {cohort}")
    cohort_payload = _read(_resolve(str(ref)))
    output = sorted({
        str(item["symbol"]).rsplit(".", 1)[-1].zfill(6)
        for item in cohort_payload.get("members", [])
        if isinstance(item, dict) and item.get("symbol")
    })
    if not output:
        raise SystemExit(f"cohort has no members: {cohort}")
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-index", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--batch-id", type=int, nargs="*", default=None)
    parser.add_argument("--list", action="store_true", help="Only print the deterministic batch plan.")
    parser.add_argument("--force", action="store_true", help="Re-run an existing batch index.")
    parser.add_argument("--merge", action="store_true", help="Merge all completed batches after generation.")
    parser.add_argument("--no-update-latest", action="store_true", help="Pass through to the merge command.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    base_path = _resolve(args.base_index)
    base = _read(base_path)
    if base.get("status") != "research_only" or base.get("data_tier") != "research_pit":
        raise SystemExit("base index is not a research_only research_pit rebuild")
    contexts = base.get("contexts", {})
    if not isinstance(contexts, dict) or "close_confirmed" not in contexts:
        raise SystemExit("base index has no close_confirmed context")
    snapshot_hash = str(contexts["close_confirmed"].get("snapshot_hash") or "")
    if not snapshot_hash:
        raise SystemExit("base index has no close_confirmed snapshot hash")
    output_root = _resolve(args.output_root) if args.output_root else PROJECT / "artifacts" / "free_research_sample_batches" / snapshot_hash[:12]
    symbols = _symbols(base, "cn_equity_core") + _symbols(base, "cn_etf_benchmark")
    batches = [symbols[offset:offset + args.batch_size] for offset in range(0, len(symbols), args.batch_size)]
    print(json.dumps({
        "snapshot_hash": snapshot_hash,
        "target_symbols": len(symbols),
        "batch_size": args.batch_size,
        "batch_count": len(batches),
        "batches": {str(index): {"count": len(values), "symbols": values} for index, values in enumerate(batches)},
    }, ensure_ascii=False, indent=2))
    if args.list:
        return 0
    selected = list(range(len(batches))) if args.batch_id is None else sorted(set(args.batch_id))
    invalid = [item for item in selected if item < 0 or item >= len(batches)]
    if invalid:
        raise SystemExit(f"batch id out of range: {invalid}")
    output_root.mkdir(parents=True, exist_ok=True)
    batch_indexes: list[Path] = []
    rebuild_script = PROJECT / "scripts/rebuild_cn_research_pit.py"
    for batch_id in selected:
        batch_root = output_root / f"batch-{batch_id:03d}"
        symbol_file = output_root / f"symbols-{batch_id:03d}.json"
        symbol_file.parent.mkdir(parents=True, exist_ok=True)
        symbol_file.write_text(json.dumps({"symbols": batches[batch_id]}, ensure_ascii=False, indent=2), encoding="utf-8")
        candidates = sorted(batch_root.glob("rebuild-*.json"), reverse=True)
        if candidates and not args.force:
            batch_index = candidates[0]
            print(f"batch {batch_id}: reuse {batch_index}")
            batch_indexes.append(batch_index)
            continue
        batch_root.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, str(rebuild_script),
            "--as-of", str(base.get("as_of")),
            "--output-root", str(batch_root),
            "--reuse-standard-index", str(base_path),
            "--reuse-snapshot-index", str(base_path),
            "--sample-symbols-file", str(symbol_file),
            "--allow-unproven-visibility",
            "--allow-current-cohort-breadth",
            "--resume-samples",
            "--no-update-latest",
        ]
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, check=False)
        log_path = batch_root / "batch-run.log"
        log_path.write_text(
            json.dumps({
                "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise SystemExit(f"batch {batch_id} failed; inspect {log_path}: {result.stderr[-1000:]}")
        output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not output_lines:
            raise SystemExit(f"batch {batch_id} produced no index; inspect {log_path}")
        batch_index = Path(output_lines[-1])
        if not batch_index.is_absolute():
            batch_index = PROJECT / batch_index
        if not batch_index.is_file():
            raise SystemExit(f"batch {batch_id} index is missing: {batch_index}")
        batch_indexes.append(batch_index)
        print(f"batch {batch_id}: complete {batch_index}")

    if args.merge:
        merge_script = PROJECT / "scripts/merge_cn_research_sample_batches.py"
        command = [sys.executable, str(merge_script), "--base-index", str(base_path), "--batch-indexes", *map(str, batch_indexes)]
        if args.no_update_latest:
            command.append("--no-update-latest")
        result = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise SystemExit(f"merge failed: {result.stderr[-1200:]}")
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
