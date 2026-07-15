from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from investment_research.domain.pit import (
    PITDataQualityStatus,
    PITDatasetManifest,
    PITDatasetPartition,
    PITFeatureRecord,
    PITSampleRecord,
)
from investment_research.domain.data_tier import DataTier, formal_data_blocking_reasons
from investment_research.domain.trusted_market import MarketSnapshot
from investment_research.domain.trusted_market import RawDataBatch
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.parquet_store import parquet_schema_hash
from investment_research.training.models import (
    CoverageGroup,
    InstrumentType,
    LabelSet,
    Market,
    TrainingSample,
)


class PITCatalogIntegrityError(RuntimeError):
    pass


class FormalPITDataset(BaseModel):
    manifest: PITDatasetManifest
    partitions: list[PITDatasetPartition]
    standard_partitions: list[PITDatasetPartition] = Field(default_factory=list)
    features: list[PITFeatureRecord]
    samples: list[PITSampleRecord]
    payload_hash: str
    schema_hashes: dict[str, str] = Field(default_factory=dict)

    def training_samples(self) -> list[TrainingSample]:
        """Rehydrate formal training rows without an intermediate pickle cache."""
        output: list[TrainingSample] = []
        coverage_group = {
            "cn": CoverageGroup.CN_A_SHARE,
            "us": CoverageGroup.US_CORE,
            "hk": CoverageGroup.HK_PROXY,
            "jp": CoverageGroup.JP_PROXY,
        }[self.manifest.market]
        for record in self.samples:
            if not record.label_available:
                continue
            labels = _label_set(record)
            features = {
                key: float(value)
                for key, value in record.features.items()
                if value is not None
            }
            output.append(
                TrainingSample(
                    symbol=record.symbol,
                    market=Market(record.market),
                    instrument_type=InstrumentType.EQUITY,
                    coverage_group=coverage_group,
                    as_of_date=record.decision_time.date(),
                    as_of_time=record.decision_time,
                    feature_cutoff=record.feature_cutoff,
                    decision_context=record.decision_context,
                    prediction_start_date=(
                        None if record.label_start is None else record.label_start.date()
                    ),
                    market_snapshot_id=str(record.market_snapshot_id),
                    feature_version=record.feature_version,
                    data_version=self.manifest.dataset_hash,
                    features=features,
                    feature_coverage=1.0 - (
                        sum(bool(value) for value in record.missing_mask.values())
                        / max(1, len(set(record.features) | set(record.missing_mask)))
                    ),
                    missing_features=sorted(
                        set(key for key, value in record.features.items() if value is None)
                        | {key for key, missing in record.missing_mask.items() if missing}
                    ),
                    labels=labels,
                    event_source_available=record.event_coverage_status.value
                    in {"events_present", "confirmed_none"},
                    event_coverage_status=record.event_coverage_status.value,
                    data_issues=(
                        []
                        if record.data_quality_status == PITDataQualityStatus.PASSED
                        else [f"pit_quality:{record.data_quality_status.value}"]
                    ),
                )
            )
        if not output:
            raise PITCatalogIntegrityError("formal scope has no label-available sample rows")
        return output


class PITCatalogAdapter:
    """Authoritative scope reader for PostgreSQL/SQLite catalog + object-store Parquet.

    It deliberately has no pickle methods.  A scope is usable only if every
    immutable partition and every feature/sample snapshot relation verifies.
    """

    def __init__(self, catalog, parquet: PITParquetStore, *, market_repository=None) -> None:
        self.catalog = catalog
        self.parquet = parquet
        self.market_repository = market_repository

    def approval_evidence(
        self, *, training_run_id: str, market: str, decision_context: str, task: str
    ) -> list:
        return self.catalog.approval_evidence(training_run_id, market, decision_context, task)

    def verify_approval_evidence(
        self,
        *,
        training_run_id: str,
        market: str,
        decision_context: str,
        task: str,
        expected_hashes: dict[str, str],
    ) -> list:
        """Require catalog evidence to exactly match the frozen report map."""
        rows = self.approval_evidence(
            training_run_id=training_run_id,
            market=market,
            decision_context=decision_context,
            task=task,
        )
        by_type = {item.evidence_type: item for item in rows}
        if len(by_type) != len(rows) or set(by_type) != set(expected_hashes):
            raise PITCatalogIntegrityError("catalog approval evidence set is incomplete or ambiguous")
        mismatched = [
            name for name, expected in expected_hashes.items()
            if not expected or by_type[name].artifact_hash != expected
        ]
        if mismatched:
            raise PITCatalogIntegrityError("catalog approval evidence hash mismatch")
        return [by_type[name] for name in sorted(by_type)]

    def market_snapshot(self, snapshot_id: str) -> MarketSnapshot:
        if self.market_repository is None:
            raise PITCatalogIntegrityError("market snapshot repository is not configured")
        snapshot = self.market_repository.market_snapshot(snapshot_id)
        if snapshot is None:
            raise PITCatalogIntegrityError("frozen market snapshot is missing")
        return snapshot

    def load_scope(
        self,
        *,
        training_run_id: str,
        market: str,
        decision_context: str,
        task: str,
    ) -> FormalPITDataset:
        manifest = self.catalog.manifest(
            training_run_id=training_run_id,
            market=market,
            decision_context=decision_context,
            task=task,
        )
        if manifest is None:
            raise PITCatalogIntegrityError("PIT dataset manifest is missing for exact scope")
        if manifest.data_tier != DataTier.FORMAL_PIT:
            raise PITCatalogIntegrityError("formal catalog adapter rejects non-formal data tiers")
        if manifest.quality_status != PITDataQualityStatus.PASSED:
            raise PITCatalogIntegrityError("PIT dataset manifest quality is not passed")
        partitions = self._partitions_for_manifest(manifest)
        standard_partitions = self._standard_partitions_for_manifest(manifest)
        rows_by_dataset: dict[str, list[dict[str, Any]]] = {"features": [], "samples": []}
        schema_hashes: dict[str, str] = {}
        for partition in partitions:
            rows, actual_payload_hash, actual_schema_hash = self._read_verified(partition)
            if partition.dataset not in rows_by_dataset:
                raise PITCatalogIntegrityError(f"unexpected dataset layer: {partition.dataset}")
            rows_by_dataset[partition.dataset].extend(rows)
            schema_hashes[partition.object_ref] = actual_schema_hash
            if actual_payload_hash != partition.payload_hash:
                raise PITCatalogIntegrityError("Parquet payload hash differs from catalog")
        for partition in standard_partitions:
            _rows, actual_payload_hash, actual_schema_hash = self._read_verified(partition)
            schema_hashes[partition.object_ref] = actual_schema_hash
            if actual_payload_hash != partition.payload_hash:
                raise PITCatalogIntegrityError("standard Parquet payload hash differs from catalog")
        features = [PITFeatureRecord.model_validate(_restore_maps(row)) for row in rows_by_dataset["features"]]
        samples = [PITSampleRecord.model_validate(_restore_maps(row)) for row in rows_by_dataset["samples"]]
        self._verify_scope(manifest, features, samples)
        if self.market_repository is not None:
            self._verify_market_snapshots(samples)
            self._verify_raw_lineage(samples)
        payload_hash = _hash_values([item.payload_hash for item in partitions])
        if payload_hash != manifest.dataset_hash:
            raise PITCatalogIntegrityError("dataset hash differs from immutable partition hashes")
        return FormalPITDataset(
            manifest=manifest,
            partitions=partitions,
            standard_partitions=standard_partitions,
            features=features,
            samples=samples,
            payload_hash=payload_hash,
            schema_hashes=schema_hashes,
        )

    def _verify_market_snapshots(self, samples: list[PITSampleRecord]) -> None:
        expected: dict[str, str] = {}
        for sample in samples:
            expected[str(sample.market_snapshot_id)] = sample.market_snapshot_hash
        for snapshot_id, snapshot_hash in expected.items():
            snapshot = self.market_snapshot(snapshot_id)
            if snapshot.data_tier != DataTier.FORMAL_PIT:
                raise PITCatalogIntegrityError("formal scope references a non-formal market snapshot")
            if snapshot.content_hash != snapshot_hash:
                raise PITCatalogIntegrityError("market snapshot hash differs from sample snapshot hash")

    def raw_lineage(self, sample: PITSampleRecord) -> list[RawDataBatch]:
        """Resolve and hash-verify raw payloads named by one frozen feature row."""
        if self.market_repository is None:
            raise PITCatalogIntegrityError("raw lineage repository is not configured")
        expected = sorted(set(sample.input_revision_ids))
        if not expected:
            raise PITCatalogIntegrityError("frozen feature row has no raw payload lineage")
        batches = self.market_repository.raw_batches_by_payload_hashes(expected)
        by_hash = {item.payload_hash: item for item in batches}
        missing = sorted(set(expected) - set(by_hash))
        if missing:
            raise PITCatalogIntegrityError("frozen feature row references missing raw payload batch")
        for payload_hash in expected:
            batch = by_hash[payload_hash]
            blocking = formal_data_blocking_reasons(
                data_tier=batch.data_tier, provider=batch.provider, request_id=batch.request_id,
            )
            if blocking:
                raise PITCatalogIntegrityError(
                    "formal raw lineage rejected:" + ",".join(blocking)
                )
            key = _object_key(batch.payload_ref)
            if batch.payload_ref.startswith("s3://"):
                expected_bucket = getattr(self.parquet.object_store, "bucket", None)
                actual_bucket = batch.payload_ref.removeprefix("s3://").split("/", 1)[0]
                if expected_bucket is None or actual_bucket != expected_bucket:
                    raise PITCatalogIntegrityError("raw payload bucket is not authoritative")
            try:
                payload = self.parquet.object_store.get(key)
            except Exception as exc:
                raise PITCatalogIntegrityError("raw payload object is unavailable") from exc
            if sha256(payload).hexdigest() != batch.payload_hash:
                raise PITCatalogIntegrityError("raw payload hash differs from trusted batch")
        return [by_hash[item] for item in expected]

    def _verify_raw_lineage(self, samples: list[PITSampleRecord]) -> None:
        # Shared payload hashes are rechecked once per scope load. Every
        # feature row still has to name at least one raw batch, so a forged
        # empty lineage cannot piggyback on another row's valid trace.
        verified: set[str] = set()
        for sample in samples:
            if not sample.input_revision_ids:
                raise PITCatalogIntegrityError("frozen feature row has no raw payload lineage")
            needed = set(sample.input_revision_ids) - verified
            if needed:
                self.raw_lineage(sample.model_copy(update={"input_revision_ids": sorted(needed)}))
                verified.update(needed)

    def _partitions_for_manifest(self, manifest: PITDatasetManifest) -> list[PITDatasetPartition]:
        all_partitions = self.catalog.partitions(market=manifest.market)
        by_ref = {item.object_ref: item for item in all_partitions}
        missing = [ref for ref in manifest.parquet_refs if ref not in by_ref]
        if missing:
            raise PITCatalogIntegrityError("manifest references missing catalog partition")
        partitions = [by_ref[ref] for ref in manifest.parquet_refs]
        if {item.dataset for item in partitions} != {"features", "samples"}:
            raise PITCatalogIntegrityError("formal scope requires feature and sample partitions")
        if any(item.quality_status != PITDataQualityStatus.PASSED for item in partitions):
            raise PITCatalogIntegrityError("formal scope includes degraded or failed partition")
        return partitions

    def _standard_partitions_for_manifest(
        self, manifest: PITDatasetManifest,
    ) -> list[PITDatasetPartition]:
        refs = manifest.standard_parquet_refs
        if not refs:
            if manifest.schema_version == "pit-dataset-manifest-v2":
                raise PITCatalogIntegrityError(
                    "formal v2 dataset manifest lacks immutable standard-layer lineage"
                )
            return []
        all_partitions = self.catalog.partitions(market=manifest.market)
        by_ref = {item.object_ref: item for item in all_partitions}
        missing = [ref for ref in refs if ref not in by_ref]
        if missing:
            raise PITCatalogIntegrityError("manifest references missing standard partition")
        partitions = [by_ref[ref] for ref in refs]
        allowed = {
            "standard_prices", "standard_events", "historical_universe", "corporate_actions"
        }
        if any(item.dataset not in allowed for item in partitions):
            raise PITCatalogIntegrityError("unexpected standard layer in formal manifest")
        if any(item.quality_status != PITDataQualityStatus.PASSED for item in partitions):
            raise PITCatalogIntegrityError("formal scope includes non-passed standard partition")
        expected_hash = _hash_values([item.payload_hash for item in partitions])
        if manifest.standard_layer_hash != expected_hash:
            raise PITCatalogIntegrityError("standard layer hash differs from immutable partitions")
        return partitions

    def _read_verified(self, partition: PITDatasetPartition) -> tuple[list[dict[str, Any]], str, str]:
        import pyarrow.parquet as pq
        import io

        key = _object_key(partition.object_ref)
        if partition.object_ref.startswith("s3://"):
            expected_bucket = getattr(self.parquet.object_store, "bucket", None)
            actual_bucket = partition.object_ref.removeprefix("s3://").split("/", 1)[0]
            if expected_bucket is None or actual_bucket != expected_bucket:
                raise PITCatalogIntegrityError("Parquet object reference bucket is not authoritative")
        payload = self.parquet.object_store.get(key)
        actual_payload_hash = sha256(payload).hexdigest()
        table = pq.read_table(io.BytesIO(payload))
        actual_schema_hash = parquet_schema_hash(table.schema)
        if actual_schema_hash != partition.schema_hash:
            raise PITCatalogIntegrityError("Parquet schema hash differs from catalog")
        if table.num_rows != partition.row_count:
            raise PITCatalogIntegrityError("Parquet row count differs from catalog")
        return table.to_pylist(), actual_payload_hash, actual_schema_hash

    @staticmethod
    def _verify_scope(
        manifest: PITDatasetManifest,
        features: list[PITFeatureRecord],
        samples: list[PITSampleRecord],
    ) -> None:
        if not features or not samples:
            raise PITCatalogIntegrityError("formal scope has empty feature or sample layer")
        if len(samples) != manifest.row_count:
            raise PITCatalogIntegrityError("sample row count differs from manifest")
        for feature in features:
            if (
                feature.market != manifest.market
                or feature.decision_context != manifest.decision_context
                or feature.feature_version != manifest.feature_version
            ):
                raise PITCatalogIntegrityError("feature metadata does not match scope manifest")
            if feature.data_quality_status != PITDataQualityStatus.PASSED:
                raise PITCatalogIntegrityError("formal scope includes non-passed feature row")
            if feature.feature_hash != PITFeatureRecord.hash_features(feature.features):
                raise PITCatalogIntegrityError("feature hash differs from frozen feature values")
        feature_by_key = {(item.symbol, item.decision_time): item for item in features}
        if len(feature_by_key) != len(features):
            raise PITCatalogIntegrityError("duplicate feature rows for frozen snapshot key")
        for sample in samples:
            if (
                sample.market != manifest.market
                or sample.decision_context != manifest.decision_context
                or sample.feature_version != manifest.feature_version
                or sample.label_version != manifest.label_version
            ):
                raise PITCatalogIntegrityError("sample metadata does not match scope manifest")
            if sample.data_quality_status != PITDataQualityStatus.PASSED:
                raise PITCatalogIntegrityError("formal scope includes non-passed sample row")
            feature = feature_by_key.get((sample.symbol, sample.decision_time))
            if feature is None:
                raise PITCatalogIntegrityError("sample has no exact frozen feature row")
            if (
                feature.market_snapshot_id != sample.market_snapshot_id
                or feature.market_snapshot_hash != sample.market_snapshot_hash
                or feature.feature_cutoff != sample.feature_cutoff
                or feature.features != sample.features
                or sorted(feature.input_revision_ids) != sorted(sample.input_revision_ids)
                or feature.missing_mask != sample.missing_mask
                or feature.historical_universe_version != sample.historical_universe_version
                or feature.adjustment_policy != sample.adjustment_policy
            ):
                raise PITCatalogIntegrityError("feature/sample snapshot relation is not immutable")


def _restore_maps(row: dict[str, Any]) -> dict[str, Any]:
    restored = dict(row)
    for key in ("features", "labels", "missing_mask"):
        if isinstance(restored.get(key), str):
            restored[key] = json.loads(restored[key])
    if isinstance(restored.get("input_revision_ids"), str):
        restored["input_revision_ids"] = json.loads(restored["input_revision_ids"])
    return restored


def _label_set(record: PITSampleRecord) -> LabelSet:
    payload = dict(record.labels)
    payload.update(
        {
            "symbol": record.symbol,
            "as_of_date": record.decision_time.date(),
            "label_available": record.label_available,
            "label_unavailable_reason": record.label_unavailable_reason,
            "entry_delay_sessions": record.entry_delay_trading_days,
            "label_start": None if record.label_start is None else record.label_start.date(),
            "label_end": None if record.label_end is None else record.label_end.date(),
        }
    )
    return LabelSet.model_validate(payload)


def _hash_values(values: list[str]) -> str:
    return sha256(json.dumps(sorted(values), separators=(",", ":")).encode()).hexdigest()


def _object_key(ref: str) -> str:
    if ref.startswith("file-object://"):
        return _safe_object_key(ref.removeprefix("file-object://"))
    if ref.startswith("s3://"):
        parts = ref.removeprefix("s3://").split("/", 1)
        if len(parts) != 2:
            raise PITCatalogIntegrityError("invalid S3 object reference")
        return _safe_object_key(parts[1])
    raise PITCatalogIntegrityError("PIT catalog object reference must be file-object:// or s3://")


def _safe_object_key(key: str) -> str:
    path = Path(key)
    if not key or path.is_absolute() or ".." in path.parts:
        raise PITCatalogIntegrityError("PIT catalog object reference escapes object-store root")
    return key
