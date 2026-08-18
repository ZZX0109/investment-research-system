"""Immutable landing and activation primitives for research data snapshots.

The downloader is intentionally not coupled to the trainer.  A producer writes
into ``landing/<run_id>`` and publishes a manifest only after every file has a
stable hash and explicit quality metadata.  Activation then atomically moves
the completed run into ``snapshots/<snapshot_id>`` and swaps a small pointer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import date as date_type, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SNAPSHOT_SCHEMA_VERSION = "research-data-snapshot-v1"
QUALITY_STATUSES = {"complete", "degraded", "unavailable"}
MISSING_REASON_CODES = {
    "no_events_confirmed",
    "provider_not_covered",
    "published_time_unverified",
    "field_missing_in_source",
    "fetch_failed",
    "pending_backfill",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_identifier(value: str, *, label: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {label}: must be a safe path identifier")
    return value


class SnapshotFileRecord(BaseModel):
    """One immutable file in a landing/snapshot run."""

    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(min_length=1)
    layer: Literal["raw", "standard", "pit", "unknown"] = "unknown"
    provider: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision_id: str | None = None
    size_bytes: int = Field(ge=0)
    row_count: int | None = Field(default=None, ge=0)
    symbol: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    published_at_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    available_at_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    collected_at_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    revision_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_status: Literal["complete", "degraded", "unavailable"]
    missing_reason: str | None = None
    missing_reason_code: str | None = None
    schema_valid: bool = True
    duplicate_key_count: int = Field(default=0, ge=0)
    security_code_error_count: int = Field(default=0, ge=0)
    ohlc_error_count: int = Field(default=0, ge=0)
    trading_date_error_count: int = Field(default=0, ge=0)
    trading_status_error_count: int = Field(default=0, ge=0)
    adjustment_error_count: int = Field(default=0, ge=0)
    security_lifecycle_error_count: int = Field(default=0, ge=0)
    reference_error_count: int = Field(default=0, ge=0)
    pit_time_error_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_quality_metadata(self) -> "SnapshotFileRecord":
        if self.quality_status == "complete" and not self.revision_id:
            raise ValueError("complete files require revision_id")
        if self.quality_status != "complete" and not self.missing_reason:
            raise ValueError("degraded/unavailable files require missing_reason")
        confirmed_none = (
            self.dataset == "events"
            and self.quality_status == "complete"
            and self.missing_reason_code == "no_events_confirmed"
            and str(self.missing_reason or "").strip().lower() in {"no_events_confirmed", "no events confirmed"}
        )
        if self.quality_status == "complete" and self.missing_reason and not confirmed_none:
            raise ValueError("complete files cannot carry missing_reason")
        if self.missing_reason_code is not None and self.missing_reason_code not in MISSING_REASON_CODES:
            raise ValueError(f"unknown missing_reason_code: {self.missing_reason_code}")
        if self.dataset == "events" and self.quality_status != "complete" and not self.missing_reason_code:
            raise ValueError("event files require missing_reason_code")
        if self.quality_status == "complete" and self.missing_reason_code and not confirmed_none:
            raise ValueError("complete files cannot carry missing_reason_code")
        if self.published_at_coverage is not None and self.published_at_coverage < 1.0 and not self.missing_reason:
            raise ValueError("incomplete published_at coverage requires missing_reason")
        if self.available_at_coverage is not None and self.available_at_coverage < 1.0 and not self.missing_reason:
            raise ValueError("incomplete available_at coverage requires missing_reason")
        if self.collected_at_coverage is not None and self.collected_at_coverage < 1.0 and not self.missing_reason:
            raise ValueError("incomplete collected_at coverage requires missing_reason")
        return self


class ResearchSnapshotManifest(BaseModel):
    """Machine-readable handoff between download, PIT rebuild and training."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    run_id: str
    snapshot_id: str
    created_at: datetime
    source_kind: Literal["landing", "snapshot"] = "landing"
    status: Literal["staged", "validated", "active", "blocked"] = "staged"
    data_tier: Literal["research_pit"] = "research_pit"
    deployment_ready: bool = False
    source_root: str
    files: list[SnapshotFileRecord] = Field(default_factory=list)
    target_symbol_count: int = Field(default=0, ge=0)
    observed_symbol_count: int = Field(default=0, ge=0)
    industry_target_symbol_count: int = Field(default=0, ge=0)
    industry_observed_symbol_count: int = Field(default=0, ge=0)
    financial_target_field_count: int = Field(default=0, ge=0)
    financial_observed_field_count: int = Field(default=0, ge=0)
    financial_low_coverage_fields: list[str] = Field(default_factory=list)
    # A zero leakage count is only evidence when it is tied to an immutable
    # audit file.  Keeping these fields on the snapshot prevents a caller from
    # satisfying the hard gate by relying on a default ``0`` argument.
    pit_leakage_error_count: int | None = Field(default=None, ge=0)
    pit_leakage_audit_ref: str | None = None
    pit_leakage_audit_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    file_success_count: int = Field(default=0, ge=0)
    file_failure_count: int = Field(default=0, ge=0)
    file_degraded_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    failure_reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> "ResearchSnapshotManifest":
        validate_identifier(self.run_id, label="run_id")
        validate_identifier(self.snapshot_id, label="snapshot_id")
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest contains duplicate relative_path entries")
        if self.status == "validated" and self.failure_count:
            raise ValueError("validated manifest cannot contain failures")
        if self.status == "active" and self.source_kind != "snapshot":
            raise ValueError("active manifest must reference an immutable snapshot")
        if self.status == "active" and self.deployment_ready:
            raise ValueError("data snapshot activation cannot imply deployment readiness")
        leakage_fields = (
            self.pit_leakage_error_count,
            self.pit_leakage_audit_ref,
            self.pit_leakage_audit_sha256,
        )
        if any(value is not None for value in leakage_fields) and not all(value is not None for value in leakage_fields):
            raise ValueError("PIT leakage evidence requires error count, audit ref and audit sha256")
        return self


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_landing_run(data_root: Path, run_id: str) -> Path:
    """Create an isolated landing directory without touching active data."""
    validate_identifier(run_id, label="run_id")
    path = data_root / "landing" / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def copy_into_landing(source_root: Path, landing_root: Path) -> None:
    """Copy a completed downloader output into landing, never mutate its source."""
    source_root = source_root.resolve()
    landing_root = landing_root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"source root is not a directory: {source_root}")
    if source_root == landing_root or source_root in landing_root.parents:
        raise ValueError("landing root must not be inside the source root")
    for source in source_root.rglob("*"):
        relative = source.relative_to(source_root)
        destination = landing_root / relative
        if source.is_symlink():
            raise ValueError(f"symlinks are not allowed in snapshot input: {source}")
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def build_file_record(
    landing_root: Path,
    relative_path: str,
    *,
    dataset: str,
    provider: str,
    metadata: dict[str, Any] | None = None,
) -> SnapshotFileRecord:
    """Hash one landed file and attach explicit dataset metadata."""
    metadata = dict(metadata or {})
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("relative_path must remain within landing root")
    path = (landing_root / relative).resolve()
    root = landing_root.resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError(f"landed file does not exist below landing root: {relative_path}")
    payload = {
        "dataset": dataset,
        "provider": provider,
        "relative_path": relative.as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        **metadata,
    }
    # A normalized handoff must always retain a raw lineage hash. When the
    # producer has no separate raw object, the landed bytes are the raw
    # payload and their content hash is the correct lineage anchor.
    payload.setdefault("raw_hash", payload["sha256"])
    return SnapshotFileRecord.model_validate(payload)


def audit_file_contents(path: Path, *, dataset: str) -> dict[str, Any]:
    """Run conservative, format-aware integrity checks on one landed file."""
    rows: list[Any]
    try:
        if path.suffix == ".parquet":
            import pyarrow.parquet as parquet

            rows = parquet.read_table(path).to_pylist()
        elif path.suffix in {".jsonl", ".ndjson"}:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        elif path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                candidate = payload.get("rows") or payload.get("data") or payload.get("records")
                rows = candidate if isinstance(candidate, list) else [payload]
            else:
                rows = []
        else:
            return _audit_result(schema_valid=True, row_count=None)
    except Exception:
        return _audit_result(schema_valid=False, row_count=None, pit_time_error_count=1)
    schema_valid = all(isinstance(row, dict) for row in rows)
    if not schema_valid:
        return _audit_result(schema_valid=False, row_count=len(rows))
    duplicate_keys: set[tuple[str, str]] = set()
    duplicate_count = 0
    security_code_errors = 0
    ohlc_errors = 0
    trading_date_errors = 0
    trading_status_errors = 0
    adjustment_errors = 0
    lifecycle_errors = 0
    pit_time_errors = 0
    dataset_name = dataset.lower()
    for row in rows:
        symbol = str(_first_value(row, ("symbol", "code", "证券代码", "股票代码")) or "").strip()
        code_audit_dataset = (
            "daily_bars" in dataset_name
            or any(token in dataset_name for token in (
                "adjustment", "trading_status", "security", "industry",
                "universe", "margin_financing", "corporate_action",
            ))
        )
        if code_audit_dataset and (not symbol or not _valid_cn_symbol(symbol)):
            security_code_errors += 1
        effective = _first_value(row, ("trade_date", "tradeDate", "date", "日期", "effective_date", "statDate", "pubDate"))
        parsed_date = _parse_date(effective)
        if parsed_date is not None:
            if parsed_date.weekday() >= 5:
                trading_date_errors += 1
            key = (symbol, parsed_date.isoformat())
            if key in duplicate_keys:
                duplicate_count += 1
            duplicate_keys.add(key)
        elif effective is not None:
            trading_date_errors += 1
        if _first_value(row, ("published_at", "publishedAt", "pubDate", "发布时间")) is None or _first_value(row, ("available_at", "availableAt", "可用时间")) is None:
            pit_time_errors += 1
        open_value = _number_value(_first_value(row, ("open", "开盘", "open_price")))
        high_value = _number_value(_first_value(row, ("high", "最高", "high_price")))
        low_value = _number_value(_first_value(row, ("low", "最低", "low_price")))
        close_value = _number_value(_first_value(row, ("close", "收盘", "close_price")))
        if None not in {open_value, high_value, low_value, close_value}:
            if high_value < max(open_value, close_value) or low_value > min(open_value, close_value) or min(open_value, high_value, low_value, close_value) < 0:
                ohlc_errors += 1
        if "trading_status" in dataset_name:
            status_fields = (
                "status", "trade_status", "trading_status", "is_tradeable", "is_tradable",
                "is_halted", "is_suspended", "停牌", "交易状态",
            )
            if not any(name in row for name in status_fields):
                trading_status_errors += 1
        if "adjustment" in dataset_name or "qfq" in dataset_name or "hfq" in dataset_name:
            factor = _number_value(_first_value(row, ("adjustment_factor", "adj_factor", "factor", "split_factor", "复权因子")))
            if factor is not None and factor <= 0:
                adjustment_errors += 1
            raw_close = _number_value(_first_value(row, ("raw_close", "close", "收盘", "close_price")))
            adjusted_close = _number_value(_first_value(row, ("adjusted_close", "adj_close", "复权收盘")))
            if factor is not None and raw_close is not None and adjusted_close is not None:
                expected = raw_close * factor
                tolerance = max(1e-6, abs(adjusted_close) * 1e-4)
                if abs(adjusted_close - expected) > tolerance:
                    adjustment_errors += 1
        if "security" in dataset_name or "lifecycle" in dataset_name or "universe" in dataset_name:
            effective_from = _parse_date(_first_value(row, ("effective_from", "valid_from", "list_date", "listing_date", "上市日期")))
            effective_to = _parse_date(_first_value(row, ("effective_to", "valid_to", "delist_date", "delisting_date", "退市日期")))
            if effective_from is not None and effective_to is not None and effective_to < effective_from:
                lifecycle_errors += 1
    return {
        **_audit_result(schema_valid=schema_valid, row_count=len(rows)),
        "duplicate_key_count": duplicate_count,
        "security_code_error_count": security_code_errors,
        "ohlc_error_count": ohlc_errors,
        "trading_date_error_count": trading_date_errors,
        "trading_status_error_count": trading_status_errors,
        "adjustment_error_count": adjustment_errors,
        "security_lifecycle_error_count": lifecycle_errors,
        "pit_time_error_count": pit_time_errors,
    }


def _audit_result(*, schema_valid: bool, row_count: int | None, pit_time_error_count: int = 0) -> dict[str, Any]:
    return {
        "schema_valid": schema_valid,
        "row_count": row_count,
        "duplicate_key_count": 0,
        "security_code_error_count": 0,
        "ohlc_error_count": 0,
        "trading_date_error_count": 0,
        "trading_status_error_count": 0,
        "adjustment_error_count": 0,
        "security_lifecycle_error_count": 0,
        "reference_error_count": 0,
        "pit_time_error_count": pit_time_error_count,
    }


def _first_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _parse_date(value: Any) -> date_type | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    if isinstance(value, str):
        try:
            return date_type.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _number_value(value: Any) -> float | None:
    try:
        return None if value in (None, "", "-") else float(value)
    except (TypeError, ValueError):
        return None


def _valid_cn_symbol(value: str) -> bool:
    """Accept six-digit CN equity/ETF codes with an optional exchange suffix."""
    import re

    normalized = value.upper()
    return bool(
        re.fullmatch(r"\d{6}(?:\.(?:SH|SZ|BJ))?", normalized)
        or re.fullmatch(r"(?:SH|SZ|BJ)\.\d{6}", normalized)
    )


def write_manifest(manifest: ResearchSnapshotManifest, path: Path) -> Path:
    """Write a manifest atomically so readers never observe partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(manifest.model_dump_json(indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_manifest(path: Path) -> ResearchSnapshotManifest:
    return ResearchSnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))


def validate_landing_manifest(landing_root: Path, manifest: ResearchSnapshotManifest) -> list[str]:
    """Return all integrity errors; no activation is allowed when non-empty."""
    errors: list[str] = []
    if manifest.source_kind != "landing":
        errors.append("manifest source_kind must be landing before activation")
    if manifest.status not in {"staged", "validated"}:
        errors.append(f"manifest status cannot be validated from {manifest.status}")
    root = landing_root.resolve()
    if not root.is_dir():
        return [f"landing root missing: {root}"]
    for item in manifest.files:
        relative = Path(item.relative_path)
        path = (root / relative).resolve()
        if root not in path.parents:
            errors.append(f"file escapes landing root: {item.relative_path}")
            continue
        if not path.is_file():
            errors.append(f"manifest file missing: {item.relative_path}")
            continue
        if path.stat().st_size != item.size_bytes:
            errors.append(f"size mismatch: {item.relative_path}")
        if sha256_file(path) != item.sha256:
            errors.append(f"sha256 mismatch: {item.relative_path}")
        if not item.schema_valid:
            errors.append(f"schema invalid: {item.relative_path}")
        if item.duplicate_key_count:
            errors.append(f"duplicate keys: {item.relative_path}")
        if item.security_code_error_count:
            errors.append(f"security code errors: {item.relative_path}")
        if item.ohlc_error_count:
            errors.append(f"ohlc errors: {item.relative_path}")
        if item.trading_date_error_count:
            errors.append(f"trading date errors: {item.relative_path}")
        if item.trading_status_error_count:
            errors.append(f"trading status errors: {item.relative_path}")
        if item.adjustment_error_count:
            errors.append(f"adjustment consistency errors: {item.relative_path}")
        if item.security_lifecycle_error_count:
            errors.append(f"security lifecycle errors: {item.relative_path}")
        if item.reference_error_count:
            errors.append(f"file reference errors: {item.relative_path}")
        if item.pit_time_error_count:
            errors.append(f"PIT time errors: {item.relative_path}")
    tracked = {Path(item.relative_path).as_posix() for item in manifest.files}
    for path in iter_data_files(root):
        relative = path.relative_to(root).as_posix()
        if relative not in tracked:
            errors.append(f"untracked data file: {relative}")
    if manifest.target_symbol_count and manifest.observed_symbol_count > manifest.target_symbol_count:
        errors.append("observed_symbol_count exceeds target_symbol_count")
    if manifest.industry_target_symbol_count and manifest.industry_observed_symbol_count > manifest.industry_target_symbol_count:
        errors.append("industry_observed_symbol_count exceeds industry_target_symbol_count")
    if manifest.failure_count != len(manifest.failure_reasons):
        errors.append("failure_count does not match failure_reasons")
    quality_counts = (
        manifest.file_success_count,
        manifest.file_failure_count,
        manifest.file_degraded_count,
    )
    observed_quality_counts = (
        sum(item.quality_status == "complete" for item in manifest.files),
        sum(item.quality_status == "unavailable" for item in manifest.files),
        sum(item.quality_status == "degraded" for item in manifest.files),
    )
    # Counts are part of the handoff contract, not optional decoration. A
    # manifest with files but three zero counters would otherwise look
    # superficially complete while hiding a failed/degraded file.
    if quality_counts != observed_quality_counts:
        errors.append("file quality counts do not match manifest files")
    return errors


def load_active_manifest(data_root: Path) -> ResearchSnapshotManifest:
    """Load the active pointer and reject paths outside ``snapshots``."""
    pointer_path = data_root / "active.json"
    if not pointer_path.is_file():
        raise ValueError(f"active snapshot pointer is missing: {pointer_path}")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        manifest_path = Path(str(pointer["manifest"])).resolve()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("active snapshot pointer is invalid") from exc
    snapshots_root = (data_root / "snapshots").resolve()
    if snapshots_root not in manifest_path.parents:
        raise ValueError("active snapshot manifest escapes snapshots root")
    manifest = read_manifest(manifest_path)
    if manifest.status != "active" or manifest.source_kind != "snapshot":
        raise ValueError("active pointer does not reference an active snapshot manifest")
    if pointer.get("snapshot_id") != manifest.snapshot_id:
        raise ValueError("active pointer snapshot_id does not match manifest")
    return manifest


class SnapshotGateConfig(BaseModel):
    """Minimum data evidence required before a training job may start."""

    model_config = ConfigDict(extra="forbid")

    minimum_market_coverage: float = Field(default=0.99, ge=0.0, le=1.0)
    minimum_industry_coverage: float = Field(default=0.98, ge=0.0, le=1.0)
    required_datasets: set[str] = Field(default_factory=lambda: {"daily_bars_raw", "daily_bars_qfq"})
    required_layers: set[str] = Field(default_factory=lambda: {"raw", "standard", "pit"})
    minimum_published_at_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_available_at_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_collected_at_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_revision_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_financial_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    dataset_aliases: dict[str, set[str]] = Field(default_factory=lambda: {
        "cn_corporate_actions_research": {"cn_corporate_actions_detailed"},
        "cn_margin_financing_sh": {"cn_margin_financing"},
        "cn_margin_financing_sz": {"cn_margin_financing"},
        "cn_trading_status": {"trading_status"},
    })


class SnapshotGateResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    observed_symbol_count: int = 0
    target_symbol_count: int = 0
    dataset_names: list[str] = Field(default_factory=list)
    pit_leakage_error_count: int | None = None
    pit_leakage_audit_ref: str | None = None


def evaluate_snapshot_gate(
    manifest: ResearchSnapshotManifest,
    *,
    config: SnapshotGateConfig | None = None,
    pit_leakage_errors: int | None = None,
    pit_leakage_audit_ref: str | Path | None = None,
    pit_leakage_audit_sha256: str | None = None,
    labels_mature: bool = True,
) -> SnapshotGateResult:
    """Evaluate training preflight evidence without mutating the snapshot."""
    config = config or SnapshotGateConfig()
    reasons: list[str] = []
    dataset_names = sorted({item.dataset for item in manifest.files})
    layer_names = {item.layer for item in manifest.files}
    if manifest.status != "active":
        reasons.append("snapshot_not_active")
    if manifest.failure_count:
        reasons.append("snapshot_download_failures_present")
    if manifest.file_failure_count:
        reasons.append("snapshot_file_failures_present")
    if manifest.file_degraded_count:
        reasons.append("snapshot_file_quality_degraded")
    if manifest.target_symbol_count:
        coverage = manifest.observed_symbol_count / manifest.target_symbol_count
        if coverage < config.minimum_market_coverage:
            reasons.append(f"market_coverage_below_{config.minimum_market_coverage:.2%}")
    if manifest.industry_target_symbol_count:
        industry_coverage = manifest.industry_observed_symbol_count / manifest.industry_target_symbol_count
        if industry_coverage < config.minimum_industry_coverage:
            reasons.append(f"industry_coverage_below_{config.minimum_industry_coverage:.2%}")
    elif config.minimum_industry_coverage > 0:
        reasons.append("industry_coverage_not_declared")
    if manifest.financial_target_field_count:
        financial_coverage = manifest.financial_observed_field_count / manifest.financial_target_field_count
        if financial_coverage < config.minimum_financial_coverage:
            reasons.append(f"financial_coverage_below_{config.minimum_financial_coverage:.2%}")
        if manifest.financial_low_coverage_fields:
            reasons.append(
                "financial_fields_below_"
                f"{config.minimum_financial_coverage:.2%}:"
                + ",".join(sorted(manifest.financial_low_coverage_fields))
            )
    elif config.minimum_financial_coverage > 0:
        reasons.append("financial_coverage_not_declared")
    available_datasets = set(dataset_names)
    missing_datasets = sorted(
        required
        for required in config.required_datasets
        if required not in available_datasets
        and not (config.dataset_aliases.get(required, set()) & available_datasets)
    )
    if missing_datasets:
        reasons.append("required_datasets_missing:" + ",".join(missing_datasets))
    incomplete_datasets = sorted({
        item.dataset
        for item in manifest.files
        if any(
            item.dataset == required or item.dataset in config.dataset_aliases.get(required, set())
            for required in config.required_datasets
        ) and item.quality_status != "complete"
    })
    if incomplete_datasets:
        reasons.append("required_datasets_not_complete:" + ",".join(incomplete_datasets))
    missing_layers = sorted(config.required_layers - layer_names)
    if missing_layers:
        reasons.append("required_layers_missing:" + ",".join(missing_layers))
    for item in manifest.files:
        if item.published_at_coverage is None or item.published_at_coverage < config.minimum_published_at_coverage:
            reasons.append(f"published_at_coverage_insufficient:{item.relative_path}")
        if item.available_at_coverage is None or item.available_at_coverage < config.minimum_available_at_coverage:
            reasons.append(f"available_at_coverage_insufficient:{item.relative_path}")
        if item.collected_at_coverage is None or item.collected_at_coverage < config.minimum_collected_at_coverage:
            reasons.append(f"collected_at_coverage_insufficient:{item.relative_path}")
        if item.revision_coverage is None or item.revision_coverage < config.minimum_revision_coverage:
            reasons.append(f"revision_coverage_insufficient:{item.relative_path}")
    leakage_count, leakage_ref, leakage_reasons = _validate_pit_leakage_evidence(
        manifest,
        explicit_error_count=pit_leakage_errors,
        explicit_ref=pit_leakage_audit_ref,
        explicit_sha256=pit_leakage_audit_sha256,
    )
    reasons.extend(leakage_reasons)
    if leakage_count is not None and leakage_count > 0:
        reasons.append("pit_leakage_errors_present")
    if not labels_mature:
        reasons.append("labels_not_mature")
    return SnapshotGateResult(
        passed=not reasons,
        reasons=sorted(set(reasons)),
        snapshot_id=manifest.snapshot_id,
        observed_symbol_count=manifest.observed_symbol_count,
        target_symbol_count=manifest.target_symbol_count,
        dataset_names=dataset_names,
        pit_leakage_error_count=leakage_count,
        pit_leakage_audit_ref=leakage_ref,
    )


def _validate_pit_leakage_evidence(
    manifest: ResearchSnapshotManifest,
    *,
    explicit_error_count: int | None,
    explicit_ref: str | Path | None,
    explicit_sha256: str | None,
) -> tuple[int | None, str | None, list[str]]:
    """Verify a PIT leakage report before treating zero as a passing result.

    The old API defaulted ``pit_leakage_errors`` to zero, which made an absent
    audit indistinguishable from an audit that actually found zero errors.  A
    report is now required, content-addressed, and must contain an explicit
    count (``error_count`` or ``research_error_count``).
    """
    count = explicit_error_count if explicit_error_count is not None else manifest.pit_leakage_error_count
    ref_value = explicit_ref if explicit_ref is not None else manifest.pit_leakage_audit_ref
    expected_hash = explicit_sha256 if explicit_sha256 is not None else manifest.pit_leakage_audit_sha256
    ref = None if ref_value is None else str(ref_value)
    reasons: list[str] = []
    if count is None or not ref or not expected_hash:
        return count, ref, ["pit_leakage_evidence_not_declared"]
    if count < 0:
        return count, ref, ["pit_leakage_error_count_invalid"]
    try:
        path = Path(ref).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return count, ref, ["pit_leakage_audit_ref_invalid"]
    if not path.is_file():
        return count, ref, ["pit_leakage_audit_missing"]
    try:
        actual_hash = sha256_file(path)
    except OSError:
        return count, ref, ["pit_leakage_audit_unreadable"]
    if actual_hash != expected_hash:
        reasons.append("pit_leakage_audit_hash_mismatch")
        return count, ref, reasons
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return count, ref, ["pit_leakage_audit_invalid_json"]
    if not isinstance(payload, dict):
        return count, ref, ["pit_leakage_audit_invalid_payload"]
    count_values: list[int] = []
    for key in ("pit_leakage_error_count", "error_count", "research_error_count"):
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return count, ref, ["pit_leakage_audit_count_invalid"]
        count_values.append(value)
    if not count_values:
        return count, ref, ["pit_leakage_audit_count_missing"]
    if len(set(count_values)) != 1 or count_values[0] != count:
        return count, ref, ["pit_leakage_audit_count_mismatch"]
    return count, ref, reasons


def load_pit_leakage_audit(path: Path) -> tuple[int, str, str]:
    """Load and content-address a PIT leakage report for snapshot metadata."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"PIT leakage audit does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"PIT leakage audit is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("PIT leakage audit must be a JSON object")
    values: list[int] = []
    for key in ("pit_leakage_error_count", "error_count", "research_error_count"):
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"PIT leakage audit count is invalid: {key}")
        values.append(value)
    if not values:
        raise ValueError("PIT leakage audit has no explicit error count")
    if len(set(values)) != 1:
        raise ValueError("PIT leakage audit contains conflicting error counts")
    return values[0], str(path), sha256_file(path)


def activate_snapshot(
    data_root: Path,
    landing_root: Path,
    manifest: ResearchSnapshotManifest,
) -> Path:
    """Atomically promote a validated landing run and swap ``active.json``."""
    if manifest.status != "validated":
        raise ValueError("only a validated landing manifest may be activated")
    errors = validate_landing_manifest(landing_root, manifest)
    if errors:
        raise ValueError("snapshot validation failed: " + "; ".join(errors[:8]))
    data_root = data_root.resolve()
    landing_root = landing_root.resolve()
    expected_landing = (data_root / "landing" / manifest.run_id).resolve()
    if landing_root != expected_landing:
        raise ValueError("landing root must be data_root/landing/<run_id>")
    snapshot_root = data_root / "snapshots" / manifest.snapshot_id
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    if snapshot_root.exists():
        raise FileExistsError(f"snapshot already exists: {snapshot_root}")
    # Rename within the same data root: no partially copied snapshot can become active.
    os.replace(landing_root, snapshot_root)
    active_manifest = manifest.model_copy(
        update={"source_kind": "snapshot", "status": "active", "source_root": str(snapshot_root)}
    )
    manifest_path = write_manifest(active_manifest, snapshot_root / "manifest.json")
    pointer = data_root / "active.json"
    pointer_payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": manifest.snapshot_id,
        "manifest": str(manifest_path),
        "activated_at": utc_now().isoformat(),
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=data_root, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(pointer_payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, pointer)
    return pointer


def iter_data_files(root: Path) -> Iterable[Path]:
    """Yield regular data files while ignoring a manifest itself."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            yield path
