#!/usr/bin/env python3
"""Validate and stage an authorized point-in-time data delivery.

This command is the hand-off boundary between a licensed provider and the
research pipeline.  It deliberately does *not* create ``active.json`` or
mark a snapshot as deployable.  The input must carry a strict record contract
and an authorization attestation; after validation the bytes are copied to a
content-addressed landing directory and an immutable manifest is written.

Accepted inputs are JSON/JSONL, CSV and Parquet.  Each normalized record must
contain the following fields (the command may fill provider metadata from the
CLI/attestation, but it never invents time or revision values)::

    dataset, symbol, observation_period, effective_at, published_at,
    available_at, fetched_at, revision_id, raw_payload_hash,
    normalized_record_hash, quality_status

The exact canonical JSON used to verify ``normalized_record_hash`` is part of
the manifest, so another process can reproduce the check without trusting
this script's in-memory state.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable
from uuid import uuid4


PROJECT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "authorized-pit-intake-v1"
CANONICAL_HASH_RULE = "sha256(json.dumps(record_without_hash_fields,sort_keys=True,separators=(',',':'),ensure_ascii=False))"
REQUIRED_FIELDS = (
    "dataset",
    "symbol",
    "observation_period",
    "effective_at",
    "published_at",
    "available_at",
    "fetched_at",
    "revision_id",
    "raw_payload_hash",
    "normalized_record_hash",
    "quality_status",
)
REQUIRED_AUTH_CAPABILITIES = (
    "historical_available_at",
    "publication_timestamps",
    "revision_history",
)
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
QUALITY_STATUSES = {"complete", "degraded", "unavailable"}
HASH_FIELDS = {"raw_payload_hash", "normalized_record_hash"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True, help="JSON/JSONL/CSV/Parquet input; repeatable")
    parser.add_argument("--attestation", type=Path, required=True, help="provider authorization JSON attestation")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--license-scope", required=True)
    parser.add_argument(
        "--landing-root",
        type=Path,
        default=PROJECT / "artifacts/authorized_pit_intake/landing",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "artifacts/authorized_pit_intake/latest.json",
    )
    parser.add_argument("--run-id", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or f"authorized-pit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:10]}"
    report = _base_report(run_id, args)
    try:
        attestation = _read_json_object(args.attestation)
        report["source_authorization"] = _validate_attestation(
            attestation,
            provider=args.provider,
            source_uri=args.source_uri,
            license_scope=args.license_scope,
        )
    except IntakeError as exc:
        report["status"] = "blocked"
        report["blocking_reasons"] = [str(exc)]
        _atomic_write(args.output, report)
        print(json.dumps({"status": report["status"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False))
        return EXIT_BLOCKED

    all_rows: list[dict[str, Any]] = []
    input_files: list[dict[str, Any]] = []
    errors: list[str] = []
    for input_path in args.input:
        try:
            payload = input_path.read_bytes()
            source_hash = hashlib.sha256(payload).hexdigest()
            rows = list(_read_rows(input_path, payload))
            normalized: list[dict[str, Any]] = []
            for index, row in enumerate(rows, start=1):
                try:
                    normalized.append(
                        _normalize_record(
                            row,
                            provider=args.provider,
                            dataset=args.dataset,
                            source_uri=args.source_uri,
                            license_scope=args.license_scope,
                        )
                    )
                except IntakeError as exc:
                    errors.append(f"{input_path}:{index}:{exc}")
            input_files.append({
                "path": str(input_path.resolve()),
                "source_sha256": source_hash,
                "row_count": len(rows),
                "valid_row_count": len(normalized),
            })
            all_rows.extend(normalized)
        except IntakeError as exc:
            errors.append(f"{input_path}:{exc}")
        except OSError as exc:
            errors.append(f"{input_path}:input_unreadable:{type(exc).__name__}")

    errors.extend(_validate_revision_chains(all_rows))
    report["inputs"] = input_files
    report["row_count"] = len(all_rows)
    report["unique_symbol_count"] = len({row["symbol"] for row in all_rows})
    report["logical_key_count"] = len({_logical_key(row) for row in all_rows})
    report["coverage"] = _coverage(all_rows)
    report["validation"] = {
        "canonical_hash_rule": CANONICAL_HASH_RULE,
        "required_fields": list(REQUIRED_FIELDS),
        "error_count": len(errors),
        "errors": errors[:200],
        "errors_truncated": max(0, len(errors) - 200),
    }
    if errors:
        report.update({
            "status": "blocked",
            "blocking_reasons": ["record_contract_invalid"],
            "formal_pit_verified": False,
            "active_snapshot_eligible": False,
        })
        _atomic_write(args.output, report)
        print(json.dumps({"status": report["status"], "row_count": len(all_rows), "error_count": len(errors)}, ensure_ascii=False))
        return EXIT_BLOCKED

    try:
        normalized_bytes = _jsonl_bytes(all_rows)
        normalized_hash = hashlib.sha256(normalized_bytes).hexdigest()
        run_root = args.landing_root / run_id
        normalized_ref = _put_content_addressed(run_root / "normalized", normalized_hash, ".jsonl", normalized_bytes)
        source_refs = []
        for item in input_files:
            source_path = Path(item["path"])
            raw_bytes = source_path.read_bytes()
            raw_hash = item["source_sha256"]
            source_refs.append(_put_content_addressed(run_root / "raw", raw_hash, source_path.suffix.lower() or ".bin", raw_bytes))
        report["artifacts"] = {
            "normalized_records_ref": str(normalized_ref),
            "normalized_records_sha256": normalized_hash,
            "raw_input_refs": [str(ref) for ref in source_refs],
        }
    except OSError as exc:
        report.update({"status": "blocked", "blocking_reasons": [f"landing_write_failed:{type(exc).__name__}"]})
        _atomic_write(args.output, report)
        print(json.dumps({"status": report["status"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False))
        return EXIT_BLOCKED

    report.update({
        "status": "ready_for_pit",
        "data_tier": "formal_pit_candidate",
        "formal_pit_verified": True,
        "active_snapshot_eligible": False,
        "deployment_ready": False,
        "blocking_reasons": ["downstream_snapshot_quality_and_leakage_audits_required"],
    })
    report["manifest_sha256"] = _report_hash(report)
    _atomic_write(args.output, report)
    print(json.dumps({
        "status": report["status"],
        "run_id": run_id,
        "row_count": report["row_count"],
        "unique_symbol_count": report["unique_symbol_count"],
        "normalized_records_ref": report["artifacts"]["normalized_records_ref"],
        "active_snapshot_eligible": report["active_snapshot_eligible"],
    }, ensure_ascii=False))
    return EXIT_READY


EXIT_READY = 0
EXIT_BLOCKED = 20


class IntakeError(ValueError):
    """Input or authorization contract failure."""


def _base_report(run_id: str, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "provider": args.provider,
        "dataset": args.dataset,
        "source_uri": args.source_uri,
        "license_scope": args.license_scope,
        "status": "blocked",
        "formal_pit_verified": False,
        "active_snapshot_eligible": False,
        "deployment_ready": False,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeError(f"attestation_unreadable:{type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise IntakeError("attestation_must_be_object")
    return value


def _validate_attestation(
    attestation: dict[str, Any],
    *,
    provider: str,
    source_uri: str,
    license_scope: str,
) -> dict[str, Any]:
    if attestation.get("authorized") is not True:
        raise IntakeError("authorization_attestation_not_authorized")
    if str(attestation.get("provider") or "") != provider:
        raise IntakeError("authorization_provider_mismatch")
    if str(attestation.get("source_uri") or "") != source_uri:
        raise IntakeError("authorization_source_uri_mismatch")
    if str(attestation.get("license_scope") or "") != license_scope:
        raise IntakeError("authorization_license_scope_mismatch")
    for key in REQUIRED_AUTH_CAPABILITIES:
        if attestation.get(key) is not True:
            raise IntakeError(f"authorization_capability_missing:{key}")
    if not str(attestation.get("attestation_id") or "").strip():
        raise IntakeError("authorization_attestation_id_missing")
    return {
        "attestation_id": str(attestation["attestation_id"]),
        "provider": provider,
        "source_uri": source_uri,
        "license_scope": license_scope,
        "authorized": True,
        "capabilities": {key: True for key in REQUIRED_AUTH_CAPABILITIES},
        "valid_from": _optional_timestamp(attestation.get("valid_from"), "valid_from"),
        "valid_to": _optional_timestamp(attestation.get("valid_to"), "valid_to"),
        "attestation_sha256": hashlib.sha256(
            json.dumps(attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _read_rows(path: Path, payload: bytes) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        for index, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IntakeError(f"jsonl_invalid_line:{index}") from exc
            if not isinstance(row, dict):
                raise IntakeError(f"jsonl_row_not_object:{index}")
            yield row
        return
    if suffix == ".json":
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntakeError("json_invalid") from exc
        rows = value if isinstance(value, list) else value.get("rows") if isinstance(value, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise IntakeError("json_rows_missing_or_not_objects")
        yield from rows
        return
    if suffix == ".csv":
        try:
            text = payload.decode("utf-8-sig")
            yield from csv.DictReader(text.splitlines())
        except UnicodeDecodeError as exc:
            raise IntakeError("csv_not_utf8") from exc
        return
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
            import pyarrow as pa

            table = pq.read_table(pa.BufferReader(payload))
            yield from table.to_pylist()
        except Exception as exc:  # pragma: no cover - provider environment dependent
            raise IntakeError(f"parquet_unreadable:{type(exc).__name__}") from exc
        return
    raise IntakeError(f"unsupported_input_extension:{suffix or '<none>'}")


def _normalize_record(
    row: dict[str, Any],
    *,
    provider: str,
    dataset: str,
    source_uri: str,
    license_scope: str,
) -> dict[str, Any]:
    record = dict(row)
    _inject_or_match(record, "dataset", dataset)
    _inject_or_match(record, "source_provider", provider)
    _inject_or_match(record, "source_uri", source_uri)
    _inject_or_match(record, "license_scope", license_scope)
    missing = [field for field in REQUIRED_FIELDS if record.get(field) in (None, "")]
    if missing:
        raise IntakeError("required_fields_missing:" + ",".join(missing))
    for field in ("published_at", "available_at", "fetched_at"):
        record[field] = _required_timestamp(record[field], field)
    record["effective_at"] = _required_timestamp(record["effective_at"], "effective_at")
    record["observation_period"] = _normalize_observation_period(record["observation_period"])
    record["symbol"] = _normalize_symbol(record["symbol"])
    record["revision_id"] = str(record["revision_id"])
    record["quality_status"] = str(record["quality_status"]).lower()
    if record["quality_status"] not in QUALITY_STATUSES:
        raise IntakeError("quality_status_invalid")
    if record["quality_status"] != "complete" and not str(record.get("missing_reason_code") or "").strip():
        raise IntakeError("missing_reason_code_required_for_non_complete_record")
    for field in ("raw_payload_hash", "normalized_record_hash"):
        value = str(record[field])
        if not HEX64.fullmatch(value):
            raise IntakeError(f"{field}_must_be_sha256")
        record[field] = value.lower()
    if record["available_at"] < record["published_at"]:
        raise IntakeError("available_at_before_published_at")
    if record["fetched_at"] < record["available_at"]:
        raise IntakeError("fetched_at_before_available_at")
    if record.get("revised_at") not in (None, ""):
        record["revised_at"] = _required_timestamp(record["revised_at"], "revised_at")
        if record["revised_at"] < record["published_at"]:
            raise IntakeError("revised_at_before_published_at")
    if record.get("supersedes_revision_id") in (None, ""):
        record.pop("supersedes_revision_id", None)
    else:
        record["supersedes_revision_id"] = str(record["supersedes_revision_id"])
    expected_hash = _normalized_record_hash(record)
    if expected_hash != record["normalized_record_hash"]:
        raise IntakeError("normalized_record_hash_mismatch")
    return record


def _inject_or_match(record: dict[str, Any], key: str, expected: str) -> None:
    observed = record.get(key)
    if observed not in (None, "") and str(observed) != expected:
        raise IntakeError(f"{key}_mismatch")
    record[key] = expected


def _validate_revision_chains(rows: list[dict[str, Any]]) -> list[str]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_logical_key(row)].append(row)
    errors: list[str] = []
    for key, group in grouped.items():
        by_revision: dict[str, dict[str, Any]] = {}
        for row in group:
            revision = row["revision_id"]
            if revision in by_revision:
                errors.append(f"duplicate_revision:{key}:{revision}")
            by_revision[revision] = row
        roots = [row for row in group if not row.get("supersedes_revision_id")]
        if len(group) > 1 and len(roots) != 1:
            errors.append(f"revision_chain_root_count:{key}:{len(roots)}")
        for row in group:
            previous_id = row.get("supersedes_revision_id")
            if not previous_id:
                continue
            previous = by_revision.get(previous_id)
            if previous is None:
                errors.append(f"revision_predecessor_missing:{key}:{previous_id}")
                continue
            if previous_id == row["revision_id"]:
                errors.append(f"revision_self_reference:{key}:{previous_id}")
            if previous["available_at"] > row["available_at"]:
                errors.append(f"revision_available_at_regressed:{key}:{previous_id}")
        # A valid finite chain must terminate at one leaf; disconnected
        # branches are not a safe interpretation of a vendor restatement log.
        referenced = {row.get("supersedes_revision_id") for row in group if row.get("supersedes_revision_id")}
        leaves = [row for row in group if row["revision_id"] not in referenced]
        if len(group) > 1 and len(leaves) != 1:
            errors.append(f"revision_chain_leaf_count:{key}:{len(leaves)}")
    return errors


def _coverage(rows: list[dict[str, Any]]) -> dict[str, float]:
    total = len(rows)
    if not total:
        return {"published_at": 0.0, "available_at": 0.0, "revision_id": 0.0, "normalized_record_hash": 0.0}
    return {
        "published_at": sum(bool(row.get("published_at")) for row in rows) / total,
        "available_at": sum(bool(row.get("available_at")) for row in rows) / total,
        "revision_id": sum(bool(row.get("revision_id")) for row in rows) / total,
        "normalized_record_hash": sum(bool(row.get("normalized_record_hash")) for row in rows) / total,
    }


def _logical_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row["dataset"]), str(row["symbol"]), str(row["observation_period"])


def _normalized_record_hash(record: dict[str, Any]) -> str:
    value = {key: item for key, item in record.items() if key not in HASH_FIELDS}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in sorted(rows, key=lambda item: (_logical_key(item), item["available_at"], item["revision_id"]))
    )


def _normalize_symbol(value: Any) -> str:
    symbol = str(value).strip()
    if not symbol:
        raise IntakeError("symbol_missing")
    if symbol.isdigit() and len(symbol) <= 6:
        symbol = symbol.zfill(6)
    return symbol


def _normalize_observation_period(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise IntakeError("observation_period_missing")
    return text


def _required_timestamp(value: Any, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            raise IntakeError(f"{field}_missing")
        parsed = _parse_timestamp(text, field)
    if parsed.tzinfo is None:
        raise IntakeError(f"{field}_timezone_missing")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_timestamp(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _required_timestamp(value, field)


def _parse_timestamp(value: str, field: str) -> datetime:
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise IntakeError(f"{field}_invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise IntakeError(f"{field}_timezone_missing")
    return parsed


def _put_content_addressed(root: Path, digest: str, suffix: str, payload: bytes) -> Path:
    target = root / digest[:2] / f"{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise OSError(f"content_addressed_hash_collision:{target}")
        return target
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".incoming-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return target


def _report_hash(report: dict[str, Any]) -> str:
    value = {key: item for key, item in report.items() if key != "manifest_sha256"}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".report-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
