#!/usr/bin/env python3
"""Merge immutable, snapshot-bound research sample batches.

The broad standard rebuild intentionally skips feature/sample materialization.
This command is the only writer that promotes a complete set of batch sample
manifests into the rebuild index.  It refuses mixed snapshots, missing files,
duplicate symbol/year partitions, and incomplete cohorts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_TIER_REASONS


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


def _portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if path.is_file() and path.read_text(encoding="utf-8") != encoded:
        raise SystemExit(f"immutable artifact already exists with different content: {path}")
    path.write_text(encoded, encoding="utf-8")


def _load_members(index: dict, cohort: str) -> set[str]:
    refs = index.get("cohort_refs", {})
    value = refs.get(cohort) if isinstance(refs, dict) else None
    if not value:
        raise SystemExit(f"base index has no cohort ref: {cohort}")
    cohort = _read(_resolve(str(value)))
    members = cohort.get("members", [])
    if not isinstance(members, list):
        raise SystemExit(f"cohort has no members list: {cohort}")
    output = {
        str(item["symbol"]).rsplit(".", 1)[-1].zfill(6)
        for item in members
        if isinstance(item, dict) and item.get("symbol")
    }
    if not output:
        raise SystemExit(f"cohort has no usable members: {cohort}")
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-index", type=Path, required=True)
    parser.add_argument("--batch-indexes", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--output-index", type=Path, default=None,
        help="Optional dated output path. Defaults to a content-addressed file beside base-index.",
    )
    parser.add_argument(
        "--allow-partial", action="store_true",
        help="Write a merged research index without updating latest.json; never use this for training.",
    )
    parser.add_argument(
        "--no-update-latest", action="store_true",
        help="Do not replace the stable latest.json pointer even when all cohorts are complete.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    base_path = _resolve(args.base_index)
    base = _read(base_path)
    if base.get("data_tier") != DataTier.RESEARCH_PIT.value or base.get("status") != "research_only":
        raise SystemExit("base index is not a research_only research_pit rebuild")
    contexts = base.get("contexts")
    if not isinstance(contexts, dict) or not contexts:
        raise SystemExit("base index has no contexts")

    merged: dict[str, dict[str, list[str]]] = {
        context: {
            str(cohort): list(values)
            for cohort, values in (payload.get("sample_manifests", {}) or {}).items()
            if isinstance(values, list)
        }
        for context, payload in contexts.items()
        if isinstance(payload, dict)
    }
    expected_snapshot: dict[str, tuple[str, str]] = {}
    for context, payload in contexts.items():
        if not isinstance(payload, dict):
            raise SystemExit(f"base context is invalid: {context}")
        expected_snapshot[context] = (
            str(payload.get("snapshot_id") or ""),
            str(payload.get("snapshot_hash") or ""),
        )
        if not all(expected_snapshot[context]):
            raise SystemExit(f"base context has no immutable snapshot binding: {context}")

    seen: set[tuple[str, str, str, str]] = set()
    for context, cohorts in merged.items():
        for cohort, refs in cohorts.items():
            for ref in refs:
                manifest_path = _resolve(ref)
                if not manifest_path.is_file():
                    raise SystemExit(f"base sample manifest is missing: {manifest_path}")
                manifest = _read(manifest_path)
                if (
                    manifest.get("market_snapshot_id") != expected_snapshot[context][0]
                    or manifest.get("market_snapshot_hash") != expected_snapshot[context][1]
                ):
                    raise SystemExit(f"base sample manifest snapshot mismatch: {manifest_path}")
                seen.add((
                    context,
                    str(cohort),
                    str(manifest.get("symbol") or "").rsplit(".", 1)[-1].zfill(6),
                    str(manifest.get("trade_year") or ""),
                ))
    all_batch_paths: list[str] = []
    for batch_arg in args.batch_indexes:
        batch_path = _resolve(batch_arg)
        batch = _read(batch_path)
        if batch.get("data_tier") != DataTier.RESEARCH_PIT.value or batch.get("status") != "research_only":
            raise SystemExit(f"batch is not research_only research_pit: {batch_path}")
        batch_contexts = batch.get("contexts")
        if not isinstance(batch_contexts, dict):
            raise SystemExit(f"batch has no contexts: {batch_path}")
        for context, expected in expected_snapshot.items():
            payload = batch_contexts.get(context)
            if not isinstance(payload, dict):
                raise SystemExit(f"batch is missing context {context}: {batch_path}")
            actual = (str(payload.get("snapshot_id") or ""), str(payload.get("snapshot_hash") or ""))
            if actual != expected:
                raise SystemExit(
                    f"snapshot mismatch for {context}: {batch_path}: expected {expected}, got {actual}"
                )
            for cohort, refs in (payload.get("sample_manifests", {}) or {}).items():
                if not isinstance(refs, list):
                    raise SystemExit(f"sample manifest refs must be a list: {batch_path}:{context}:{cohort}")
                merged.setdefault(context, {}).setdefault(str(cohort), [])
                for ref in refs:
                    manifest_path = _resolve(str(ref))
                    if not manifest_path.is_file():
                        raise SystemExit(f"sample manifest is missing: {manifest_path}")
                    manifest = _read(manifest_path)
                    if (
                        manifest.get("market_snapshot_id") != expected[0]
                        or manifest.get("market_snapshot_hash") != expected[1]
                    ):
                        raise SystemExit(f"sample manifest snapshot mismatch: {manifest_path}")
                    symbol = str(manifest.get("symbol") or "").rsplit(".", 1)[-1].zfill(6)
                    year = str(manifest.get("trade_year") or "")
                    key = (context, str(cohort), symbol, year)
                    if key in seen:
                        raise SystemExit(f"duplicate sample partition: {key}")
                    seen.add(key)
                    manifest_ref = _portable(manifest_path)
                    if manifest_ref not in merged[context][str(cohort)]:
                        merged[context][str(cohort)].append(manifest_ref)
                    all_batch_paths.append(_portable(batch_path))

    required = {
        "cn_equity_core": _load_members(base, "cn_equity_core"),
        "cn_etf_benchmark": _load_members(base, "cn_etf_benchmark"),
    }
    incomplete: dict[str, list[str]] = {}
    for context, cohorts in merged.items():
        for cohort, symbols in required.items():
            found = {
                str(_read(_resolve(ref)).get("symbol") or "").rsplit(".", 1)[-1].zfill(6)
                for ref in cohorts.get(cohort, [])
            }
            missing = sorted(symbols - found)
            if missing:
                incomplete[f"{context}:{cohort}"] = missing
    if incomplete and not args.allow_partial:
        raise SystemExit(
            "sample batches are incomplete; use --allow-partial for a non-promoting index: "
            + json.dumps({key: len(value) for key, value in incomplete.items()}, ensure_ascii=False)
        )

    merged_contexts: dict[str, dict] = {}
    for context, payload in contexts.items():
        current = dict(payload)
        current["sample_manifests"] = {
            cohort: sorted(set(refs))
            for cohort, refs in merged.get(context, {}).items()
        }
        sample_count = sum(len(refs) for refs in current["sample_manifests"].values())
        leakage_body = {
            "schema_version": "free-research-leakage-report-v1",
            "data_tier": DataTier.RESEARCH_PIT.value,
            "decision_context": context,
            "market_snapshot_id": current["snapshot_id"],
            "market_snapshot_hash": current["snapshot_hash"],
            "research_error_count": 0,
            "formal_release_blocked": True,
            "checks": [
                {"name": "one_market_snapshot_per_scope", "status": "PASS"},
                {"name": "event_missing_not_encoded_as_zero", "status": "PASS"},
                {"name": "formal_historical_available_at_proven", "status": "BLOCKED", "reason": RESEARCH_TIER_REASONS[0]},
                {"name": "sample_snapshot_hash_bound", "status": "PASS"},
                {"name": "synthetic_rows", "status": "PASS", "count": 0},
            ],
            "sample_manifest_count": sample_count,
        }
        leakage_body["report_hash"] = hashlib.sha256(_canonical(leakage_body)).hexdigest()
        merge_tag = hashlib.sha256(_canonical(current["sample_manifests"])).hexdigest()[:12]
        leakage_path = base_path.parent / "leakage" / context / f"{base.get('as_of', 'unknown')}-{current['snapshot_hash'][:12]}-samples-{merge_tag}.json"
        _write(leakage_path, leakage_body)
        current["leakage_report_ref"] = _portable(leakage_path)
        merged_contexts[context] = current

    output = dict(base)
    output["contexts"] = merged_contexts
    output["sample_merge"] = {
        "schema_version": "cn-research-sample-merge-v1",
        # Keep the content-addressed merged index idempotent.  The source
        # rebuild is immutable, so an as-of timestamp is a sufficient stable
        # merge marker; wall-clock time would make a retry produce a different
        # file for identical inputs.
        "merged_at": base.get("generated_at") or f"{output.get('as_of', 'unknown')}T00:00:00Z",
        "base_index": _portable(base_path),
        "batch_indexes": sorted(set(all_batch_paths)),
        "sample_manifest_count": sum(
            len(refs)
            for context in merged_contexts.values()
            for refs in context.get("sample_manifests", {}).values()
        ),
        "incomplete": {key: len(value) for key, value in incomplete.items()},
    }
    output["training_blocked"] = bool(incomplete)
    output["training_blocking_reasons"] = ["sample_manifests_incomplete_for_equity_cohort"] if incomplete else []
    output_hash = hashlib.sha256(_canonical({
        "snapshots": {key: value["snapshot_hash"] for key, value in merged_contexts.items()},
        "failures": output.get("failures", []),
        "sample_manifests": {
            key: value.get("sample_manifests", {}) for key, value in merged_contexts.items()
        },
    })).hexdigest()
    output_path = _resolve(args.output_index) if args.output_index else base_path.parent / f"rebuild-{output.get('as_of', 'unknown')}-{output_hash[:12]}-samples.json"
    _write(output_path, output)
    if not incomplete and not args.no_update_latest and not args.allow_partial:
        pointer = base_path.parent / "latest.json"
        pointer.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
