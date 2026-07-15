from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from uuid import uuid4

from investment_research.domain.pit import (
    CorporateActionRevision,
    HistoricalUniverseMembership,
    PITDataQualityStatus,
    PITDatasetManifest,
    PITDatasetPartition,
    PITFeatureRecord,
    PITSampleRecord,
    StandardEventRevision,
)
from investment_research.domain.data_tier import DataTier
from investment_research.training.leakage_audit import (
    LeakageAuditReport,
    audit_point_in_time_inputs,
    require_publishable_leakage_report,
)
from investment_research.training.models import PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore


class PITDatasetPublisher:
    """Atomic catalog boundary for standard/feature/sample Parquet partitions."""

    def __init__(self, parquet: PITParquetStore, catalog) -> None:
        self.parquet = parquet
        self.catalog = catalog

    def publish_task_dataset(
        self,
        *,
        training_run_id: str,
        market: str,
        decision_context: str,
        task: str,
        decision_time: datetime,
        generated_at: datetime,
        trade_year: int,
        feature_records: list[PITFeatureRecord],
        sample_records: list[PITSampleRecord],
        bars: list[PreparedPriceBar],
        events: list[StandardEventRevision],
        universe: list[HistoricalUniverseMembership],
        corporate_actions: list[CorporateActionRevision],
        feature_version: str,
        label_version: str,
        historical_universe_version: str,
        standard_partitions: list[PITDatasetPartition] | None = None,
        data_tier: DataTier = DataTier.FORMAL_PIT,
    ) -> tuple[PITDatasetManifest, LeakageAuditReport]:
        if data_tier != DataTier.FORMAL_PIT:
            raise ValueError("formal PIT catalog rejects non-formal data tiers")
        self._validate_scope(market, decision_context, feature_records, sample_records)
        report = audit_point_in_time_inputs(
            training_run_id=training_run_id,
            decision_time=decision_time,
            generated_at=generated_at,
            bars=bars,
            events=events,
            universe=universe,
            corporate_actions=corporate_actions,
            feature_names={
                name for record in feature_records for name in record.features
            },
            label_names={name for record in sample_records for name in record.labels},
        )
        require_publishable_leakage_report(report)
        partition_id = str(uuid4())
        refs: list[str] = []
        payload_hashes: list[str] = []
        schema_hashes: list[str] = []
        for dataset, records in (
            ("features", feature_records),
            ("samples", sample_records),
        ):
            ref, payload_hash, schema_hash, row_count = self.parquet.write_partition(
                records,
                market=market,
                dataset=dataset,
                schema_version=records[0].schema_version,
                trade_year=trade_year,
                partition_id=f"{partition_id}-{dataset}",
            )
            partition = PITDatasetPartition(
                market=market,
                dataset=dataset,
                schema_version=records[0].schema_version,
                trade_year=trade_year,
                object_ref=ref,
                payload_hash=payload_hash,
                schema_hash=schema_hash,
                row_count=row_count,
                quality_status=PITDataQualityStatus.PASSED,
                created_at=generated_at,
            )
            stored_partition = self.catalog.add_partition(partition)
            # Identical feature partitions are shared across task manifests;
            # always reference the catalog's canonical immutable object.
            refs.append(stored_partition.object_ref)
            payload_hashes.append(payload_hash)
            schema_hashes.append(schema_hash)
        dataset_hash = _hash_list(payload_hashes)
        manifest = PITDatasetManifest(
            data_tier=data_tier,
            schema_version=(
                "pit-dataset-manifest-v2" if standard_partitions else "pit-dataset-manifest-v1"
            ),
            training_run_id=training_run_id,
            market=market,
            decision_context=decision_context,
            task=task,
            parquet_refs=refs,
            standard_parquet_refs=[item.object_ref for item in standard_partitions or []],
            standard_layer_hash=(
                _hash_list([item.payload_hash for item in standard_partitions])
                if standard_partitions
                else None
            ),
            row_count=len(sample_records),
            dataset_hash=dataset_hash,
            schema_hash=_hash_list(schema_hashes),
            feature_version=feature_version,
            label_version=label_version,
            historical_universe_version=historical_universe_version,
            leakage_report_hash=report.report_hash,
            quality_status=PITDataQualityStatus.PASSED,
            created_at=generated_at,
        )
        self.catalog.add_manifest(manifest)
        return manifest, report

    def publish_standard_layers(
        self,
        *,
        market: str,
        trade_year: int,
        generated_at: datetime,
        bars: list[PreparedPriceBar],
        events: list[StandardEventRevision],
        universe: list[HistoricalUniverseMembership],
        corporate_actions: list[CorporateActionRevision],
        data_tier: DataTier = DataTier.FORMAL_PIT,
    ) -> list[PITDatasetPartition]:
        """Persist immutable normalized inputs before feature/sample layers.

        Empty optional datasets are intentionally not represented by a fake
        zero-row file: their semantic status belongs in the snapshot and event
        coverage records.  Every returned partition is content-addressed and
        can be reused by all four task manifests for the same rebuild scope.
        """
        if data_tier != DataTier.FORMAL_PIT:
            raise ValueError("formal PIT catalog rejects non-formal data tiers")
        layers = (
            ("standard_prices", "pit-standard-price-v1", bars),
            ("standard_events", "pit-standard-event-v1", events),
            ("historical_universe", "pit-historical-universe-v1", universe),
            ("corporate_actions", "pit-corporate-action-v1", corporate_actions),
        )
        partitions: list[PITDatasetPartition] = []
        for dataset, schema_version, records in layers:
            if not records:
                continue
            partition_id = str(uuid4())
            ref, payload_hash, schema_hash, row_count = self.parquet.write_partition(
                records,
                market=market,
                dataset=dataset,
                schema_version=schema_version,
                trade_year=trade_year,
                partition_id=partition_id,
            )
            partitions.append(self.catalog.add_partition(PITDatasetPartition(
                market=market,
                dataset=dataset,
                schema_version=schema_version,
                trade_year=trade_year,
                object_ref=ref,
                payload_hash=payload_hash,
                schema_hash=schema_hash,
                row_count=row_count,
                quality_status=PITDataQualityStatus.PASSED,
                created_at=generated_at,
            )))
        return partitions

    @staticmethod
    def _validate_scope(market, context, features, samples) -> None:
        if not features or not samples:
            raise ValueError("feature and sample partitions must be non-empty")
        if any(
            item.market != market or item.decision_context != context
            for item in [*features, *samples]
        ):
            raise ValueError("PIT partition cannot mix market or decision context")
        feature_hashes = {
            (item.symbol, item.decision_time): item.feature_hash for item in features
        }
        for sample in samples:
            if (sample.symbol, sample.decision_time) not in feature_hashes:
                raise ValueError("sample does not have an exact frozen feature row")


def _hash_list(values: list[str]) -> str:
    return sha256(
        json.dumps(sorted(values), separators=(",", ":")).encode()
    ).hexdigest()
