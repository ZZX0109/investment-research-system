from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import uuid4

from investment_research.domain.pit import (
    EventCoverageStatus,
    HistoricalUniverseMembership,
    PITDataQualityStatus,
    PITFeatureRecord,
    PITSampleRecord,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.training.models import PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.pit_pipeline import PITDatasetPublisher


def test_pit_pipeline_publishes_schema_parquet_and_catalog(tmp_path) -> None:
    now = datetime(2026, 7, 13, 20, 10, tzinfo=timezone.utc)
    snapshot_id = uuid4()
    snapshot_hash = sha256(b"snapshot").hexdigest()
    features = {"ret_5d": 0.03}
    feature = PITFeatureRecord(
        symbol="AAPL",
        market="us",
        decision_context="close_confirmed",
        decision_time=now,
        feature_cutoff=now,
        market_snapshot_id=snapshot_id,
        market_snapshot_hash=snapshot_hash,
        feature_version="investment-risk-features-v2",
        historical_universe_version="universe-v1",
        adjustment_policy="total_return-v1",
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        data_quality_status=PITDataQualityStatus.PASSED,
        coverage_ratio=1,
        features=features,
        feature_hash=PITFeatureRecord.hash_features(features),
    )
    sample = PITSampleRecord(
        symbol="AAPL",
        market="us",
        decision_context="close_confirmed",
        decision_time=now,
        feature_cutoff=now,
        market_snapshot_id=snapshot_id,
        market_snapshot_hash=snapshot_hash,
        feature_version="investment-risk-features-v2",
        label_version="tradeable-label-v1",
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        data_quality_status=PITDataQualityStatus.PASSED,
        historical_universe_version="universe-v1",
        adjustment_policy="total_return-v1",
        label_available=True,
        features=features,
        labels={"future_return_1d": 0.01},
        sample_hash=sha256(b"sample").hexdigest(),
    )
    bar = PreparedPriceBar(
        symbol="AAPL",
        trade_date=date(2026, 7, 13),
        close_native=100,
        close_normalized=100,
        volume=100,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=now,
        available_at=now,
    )
    universe = HistoricalUniverseMembership(
        symbol="AAPL",
        market="us",
        exchange="XNAS",
        instrument_type="equity",
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        listed_on=date(1980, 12, 12),
        available_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        provider="licensed",
        revision=1,
    )
    uow = SQLiteUnitOfWork(tmp_path / "pit.db")
    parquet = PITParquetStore(LocalObjectStore(tmp_path / "objects"))
    manifest, report = PITDatasetPublisher(
        parquet, uow.pit_catalog
    ).publish_task_dataset(
        training_run_id="run-pit",
        market="us",
        decision_context="close_confirmed",
        task="direction_1d",
        decision_time=now,
        generated_at=now,
        trade_year=2026,
        feature_records=[feature],
        sample_records=[sample],
        bars=[bar],
        events=[],
        universe=[universe],
        corporate_actions=[],
        feature_version="investment-risk-features-v2",
        label_version="tradeable-label-v1",
        historical_universe_version="universe-v1",
    )
    assert report.publishable
    assert len(manifest.parquet_refs) == 2
    assert parquet.read_partition(manifest.parquet_refs[0])[0]["symbol"] == "AAPL"
    assert (
        uow.connection.execute(
            "SELECT COUNT(*) FROM pit_dataset_partitions"
        ).fetchone()[0]
        == 2
    )
    uow.close()
