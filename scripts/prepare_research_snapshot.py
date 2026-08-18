#!/usr/bin/env python3
"""Land a completed downloader output and optionally atomically activate it."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from investment_research.training.snapshot_landing import (
    ResearchSnapshotManifest,
    build_file_record,
    audit_file_contents,
    copy_into_landing,
    create_landing_run,
    activate_snapshot,
    iter_data_files,
    evaluate_snapshot_gate,
    SnapshotGateConfig,
    write_manifest,
    load_pit_leakage_audit,
)


PROTECTED_SOURCE_DIRECTORY_NAMES = {"landing", "raw", "standard", "pit", "active", "snapshots"}
READY_STATUSES = {"downloaded_local_pending_server_sync", "ready_for_landing", "completed"}


def _assert_source_ready(source_root: Path, data_root: Path, readiness_manifest: Path | None) -> None:
    """Fail closed unless a completed handoff explicitly authorizes copying.

    The downloader is a separate process.  A path existing on disk is not
    evidence that its files are complete, stable, or safe to copy.
    """
    source = source_root.resolve()
    if not source.is_dir():
        raise SystemExit(f"source root is not a directory: {source}")
    data = data_root.resolve()
    protected_roots = {
        (data / name).resolve() for name in PROTECTED_SOURCE_DIRECTORY_NAMES
    }
    if any(root == source or root in source.parents for root in protected_roots):
        raise SystemExit("source root is a protected/download-in-progress directory")
    if readiness_manifest is None:
        raise SystemExit("--source-ready-manifest is required; refuse to copy an unmarked downloader output")
    try:
        payload = json.loads(readiness_manifest.resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"source readiness manifest is invalid: {readiness_manifest}") from exc
    if not isinstance(payload, dict) or payload.get("status") not in READY_STATUSES:
        raise SystemExit("source readiness manifest does not prove a completed handoff")
    declared_root = payload.get("source_root")
    if declared_root and Path(str(declared_root)).expanduser().resolve() != source:
        raise SystemExit("source readiness manifest source_root does not match --source-root")
    missing = [
        str(item.get("path"))
        for item in payload.get("paths", [])
        if isinstance(item, dict) and item.get("exists") is False
    ]
    if missing:
        raise SystemExit("source readiness manifest lists missing paths: " + ", ".join(missing[:8]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("var/cn-research"))
    parser.add_argument(
        "--source-ready-manifest", type=Path, required=True,
        help="completed downloader handoff manifest; prevents copying a live output directory",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--metadata", type=Path, required=True, help="JSON map keyed by relative file path")
    parser.add_argument(
        "--pit-leakage-audit", type=Path, default=None,
        help="content-addressed PIT leakage report; required to prove zero leakage errors",
    )
    parser.add_argument(
        "--long-term-config", type=Path,
        default=Path("config/long_term_training.yaml"),
        help="Long-term contract used for the activation gate; pass an explicit contract for another research track.",
    )
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()

    _assert_source_ready(args.source_root, args.data_root, args.source_ready_manifest)

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise SystemExit("metadata must be a JSON object")
    manifest_metadata = metadata.get("manifest", {})
    file_metadata = metadata.get("files", metadata)
    if not isinstance(manifest_metadata, dict) or not isinstance(file_metadata, dict):
        raise SystemExit("metadata must contain optional manifest and files mappings")
    leakage_metadata = {
        key: manifest_metadata.get(key)
        for key in ("pit_leakage_error_count", "pit_leakage_audit_ref", "pit_leakage_audit_sha256")
        if manifest_metadata.get(key) is not None
    }
    if args.pit_leakage_audit is not None:
        try:
            count, ref, digest = load_pit_leakage_audit(args.pit_leakage_audit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        leakage_metadata = {
            "pit_leakage_error_count": count,
            "pit_leakage_audit_ref": ref,
            "pit_leakage_audit_sha256": digest,
        }
    landing = create_landing_run(args.data_root, args.run_id)
    copy_into_landing(args.source_root, landing)
    records = []
    for path in iter_data_files(landing):
        relative = path.relative_to(landing).as_posix()
        entry = file_metadata.get(relative)
        if not isinstance(entry, dict):
            raise SystemExit(f"missing metadata for landed file: {relative}")
        entry = dict(entry)
        record = build_file_record(
            landing,
            relative,
            dataset=str(entry.pop("dataset")),
            provider=str(entry.pop("provider")),
            metadata=entry,
        )
        audit = audit_file_contents(path, dataset=record.dataset)
        updates = {
            key: value for key, value in audit.items()
            if key in {
                "schema_valid", "duplicate_key_count", "security_code_error_count", "ohlc_error_count", "trading_date_error_count",
                "trading_status_error_count", "adjustment_error_count", "security_lifecycle_error_count",
                "reference_error_count", "pit_time_error_count",
            }
        }
        if record.row_count is None and audit.get("row_count") is not None:
            updates["row_count"] = audit["row_count"]
        records.append(record.model_copy(update=updates))
    manifest = ResearchSnapshotManifest(
        run_id=args.run_id,
        snapshot_id=args.snapshot_id,
        created_at=datetime.now(timezone.utc),
        source_root=str(landing),
        files=records,
        target_symbol_count=int(manifest_metadata.get("target_symbol_count", 0) or 0),
        observed_symbol_count=int(manifest_metadata.get("observed_symbol_count", 0) or 0),
        industry_target_symbol_count=int(manifest_metadata.get("industry_target_symbol_count", 0) or 0),
        industry_observed_symbol_count=int(manifest_metadata.get("industry_observed_symbol_count", 0) or 0),
        financial_target_field_count=int(manifest_metadata.get("financial_target_field_count", 0) or 0),
        financial_observed_field_count=int(manifest_metadata.get("financial_observed_field_count", 0) or 0),
        financial_low_coverage_fields=[
            str(value) for value in manifest_metadata.get("financial_low_coverage_fields", [])
            if value
        ],
        **leakage_metadata,
        file_success_count=sum(record.quality_status == "complete" for record in records),
        file_failure_count=sum(record.quality_status == "unavailable" for record in records),
        file_degraded_count=sum(record.quality_status == "degraded" for record in records),
    )
    manifest_path = write_manifest(manifest, landing / "manifest.json")
    if args.activate:
        from investment_research.training.long_term_config import load_long_term_training_config

        contract = load_long_term_training_config(args.long_term_config)
        activation_gate = evaluate_snapshot_gate(
            manifest.model_copy(update={"status": "active", "source_kind": "snapshot"}),
            config=SnapshotGateConfig(
                required_datasets=set(contract.required_snapshot_datasets),
                minimum_financial_coverage=contract.minimum_financial_coverage,
            ),
            labels_mature=True,
        )
        if not activation_gate.passed:
            blocked = manifest.model_copy(update={
                "status": "blocked",
                "failure_count": len(activation_gate.reasons),
                "failure_reasons": activation_gate.reasons,
                "notes": [*manifest.notes, "activation refused before active pointer swap"],
            })
            write_manifest(blocked, landing / "manifest.json")
            print(json.dumps({"status": "blocked", "reasons": activation_gate.reasons}, ensure_ascii=False))
            return 2
        validated = manifest.model_copy(update={"status": "validated"})
        write_manifest(validated, landing / "manifest.json")
        pointer = activate_snapshot(args.data_root, landing, validated)
        print(pointer)
    else:
        print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
