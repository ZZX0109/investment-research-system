from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from investment_research.domain.pit import (
    EventCoverageStatus,
    HistoricalUniverseMembership,
    PITDataQualityStatus,
    PITDatasetPartition,
    PITFeatureRecord,
    PITSampleRecord,
)
from investment_research.domain.trusted_market import MarketSnapshot, RawDataBatch
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.training.models import PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.pit_pipeline import PITDatasetPublisher
from investment_research.training.catalog_adapter import (
    PITCatalogAdapter,
    PITCatalogIntegrityError,
)


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
        missing_mask={"benchmark_ret_20d": True},
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
        missing_mask={"benchmark_ret_20d": True},
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
    raw_payload = b'{"provider":"licensed","rows":["AAPL"]}'
    raw_hash = sha256(raw_payload).hexdigest()
    raw_ref = parquet.object_store.put("raw/us/prices-1.json", raw_payload, content_type="application/json")
    uow.trusted_market.add_raw_batch(RawDataBatch(
        provider="licensed", request_id="prices-1", dataset="daily_bars", payload_ref=raw_ref,
        payload_hash=raw_hash, schema_version="v1", fetched_at=now, source_time=now,
        exchange_time=now, received_at=now, persisted_at=now, available_at=now,
    ))
    uow.trusted_market.add_market_snapshot(MarketSnapshot(
        id=snapshot_id, symbol="AAPL", decision_context="close_confirmed",
        trade_date=now.date(), decision_time=now, prediction_start_date=now.date(),
        feature_built_at=now, security_universe_version="universe-v1",
        trading_calendar_version="exchange-calendar-v1", adjustment_policy="qfq",
        data_version="dataset-v1", quality_status="passed", content_hash=snapshot_hash,
    ))
    feature = feature.model_copy(update={"input_revision_ids": [raw_hash]})
    sample = sample.model_copy(update={"input_revision_ids": [raw_hash]})
    publisher = PITDatasetPublisher(parquet, uow.pit_catalog)
    standard = publisher.publish_standard_layers(
        market="us", trade_year=2026, generated_at=now, bars=[bar], events=[],
        universe=[universe], corporate_actions=[],
    )
    manifest, report = publisher.publish_task_dataset(
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
        standard_partitions=standard,
    )
    assert report.publishable
    assert len(manifest.parquet_refs) == 2
    assert len(manifest.standard_parquet_refs) == 2
    assert manifest.standard_layer_hash is not None
    assert parquet.read_partition(manifest.parquet_refs[0])[0]["symbol"] == "AAPL"
    assert (
        uow.connection.execute(
            "SELECT COUNT(*) FROM pit_dataset_partitions"
        ).fetchone()[0]
        == 4
    )
    loaded = PITCatalogAdapter(
        uow.pit_catalog, parquet, market_repository=uow.trusted_market
    ).load_scope(
        training_run_id="run-pit",
        market="us",
        decision_context="close_confirmed",
        task="direction_1d",
    )
    assert loaded.samples[0].market_snapshot_id == snapshot_id
    assert loaded.features[0].market_snapshot_hash == snapshot_hash
    assert {item.dataset for item in loaded.standard_partitions} == {
        "standard_prices", "historical_universe"
    }
    training_rows = loaded.training_samples()
    assert training_rows[0].data_version == manifest.dataset_hash
    assert training_rows[0].market_snapshot_id == str(snapshot_id)
    assert training_rows[0].missing_features == ["benchmark_ret_20d"]
    assert training_rows[0].feature_coverage == 0.5
    assert loaded.samples[0].input_revision_ids == [raw_hash]
    assert PITCatalogAdapter(
        uow.pit_catalog, parquet, market_repository=uow.trusted_market
    ).raw_lineage(loaded.samples[0])[0].payload_hash == raw_hash
    with pytest.raises(PITCatalogIntegrityError, match="lacks immutable standard-layer lineage"):
        PITCatalogAdapter(uow.pit_catalog, parquet)._standard_partitions_for_manifest(
            manifest.model_copy(update={"standard_parquet_refs": []})
        )
    uow.close()


def test_catalog_adapter_rejects_feature_sample_snapshot_mismatch(tmp_path) -> None:
    """A sample cannot be substituted under a different frozen market snapshot."""
    now = datetime(2026, 7, 13, 20, 10, tzinfo=timezone.utc)
    feature_snapshot = uuid4()
    sample_snapshot = uuid4()
    snapshot_hash = sha256(b"snapshot").hexdigest()
    features = {"ret_5d": 0.03}
    feature = PITFeatureRecord(
        symbol="AAPL", market="us", decision_context="close_confirmed",
        decision_time=now, feature_cutoff=now, market_snapshot_id=feature_snapshot,
        market_snapshot_hash=snapshot_hash, feature_version="investment-risk-features-v2",
        historical_universe_version="universe-v1", adjustment_policy="total_return-v1",
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        data_quality_status=PITDataQualityStatus.PASSED, coverage_ratio=1,
        features=features, feature_hash=PITFeatureRecord.hash_features(features),
    )
    sample = PITSampleRecord(
        symbol="AAPL", market="us", decision_context="close_confirmed",
        decision_time=now, feature_cutoff=now, market_snapshot_id=sample_snapshot,
        market_snapshot_hash=snapshot_hash, feature_version="investment-risk-features-v2",
        label_version="tradeable-label-v1", event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        data_quality_status=PITDataQualityStatus.PASSED, historical_universe_version="universe-v1",
        adjustment_policy="total_return-v1", label_available=True, features=features,
        labels={"future_return_1d": 0.01}, sample_hash=sha256(b"sample").hexdigest(),
    )
    bar = PreparedPriceBar(
        symbol="AAPL", trade_date=date(2026, 7, 13), close_native=100,
        close_normalized=100, volume=100, currency="USD", target_currency="USD",
        is_halted=False, is_suspended=False, published_at=now, available_at=now,
    )
    universe = HistoricalUniverseMembership(
        symbol="AAPL", market="us", exchange="XNAS", instrument_type="equity",
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        listed_on=date(1980, 12, 12), available_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        provider="licensed", revision=1,
    )
    uow = SQLiteUnitOfWork(tmp_path / "pit.db")
    parquet = PITParquetStore(LocalObjectStore(tmp_path / "objects"))
    PITDatasetPublisher(parquet, uow.pit_catalog).publish_task_dataset(
        training_run_id="run-pit", market="us", decision_context="close_confirmed",
        task="direction_1d", decision_time=now, generated_at=now, trade_year=2026,
        feature_records=[feature], sample_records=[sample], bars=[bar], events=[], universe=[universe],
        corporate_actions=[], feature_version="investment-risk-features-v2",
        label_version="tradeable-label-v1", historical_universe_version="universe-v1",
    )
    with pytest.raises(PITCatalogIntegrityError, match="snapshot relation"):
        PITCatalogAdapter(uow.pit_catalog, parquet).load_scope(
            training_run_id="run-pit", market="us", decision_context="close_confirmed", task="direction_1d"
        )
    uow.close()


def test_catalog_adapter_rejects_feature_from_other_scope_even_with_same_snapshot() -> None:
    """A matching snapshot is insufficient when a feature was built for another context."""
    now = datetime(2026, 7, 13, 20, 10, tzinfo=timezone.utc)
    snapshot_id = uuid4()
    snapshot_hash = sha256(b"snapshot").hexdigest()
    values = {"ret_5d": 0.03}
    feature = PITFeatureRecord(
        symbol="AAPL", market="us", decision_context="pre_open", decision_time=now,
        feature_cutoff=now, market_snapshot_id=snapshot_id,
        market_snapshot_hash=snapshot_hash, feature_version="investment-risk-features-v2",
        historical_universe_version="universe-v1", adjustment_policy="total_return-v1",
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        data_quality_status=PITDataQualityStatus.PASSED, coverage_ratio=1,
        features=values, feature_hash=PITFeatureRecord.hash_features(values),
    )
    sample = PITSampleRecord(
        symbol="AAPL", market="us", decision_context="close_confirmed", decision_time=now,
        feature_cutoff=now, market_snapshot_id=snapshot_id,
        market_snapshot_hash=snapshot_hash, feature_version="investment-risk-features-v2",
        label_version="tradeable-label-v1", event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        data_quality_status=PITDataQualityStatus.PASSED, historical_universe_version="universe-v1",
        adjustment_policy="total_return-v1", label_available=True, features=values,
        labels={"future_return_1d": 0.01}, sample_hash=sha256(b"sample").hexdigest(),
    )
    manifest = type("Manifest", (), {
        "market": "us", "decision_context": "close_confirmed",
        "feature_version": "investment-risk-features-v2", "label_version": "tradeable-label-v1",
        "row_count": 1,
    })()
    with pytest.raises(PITCatalogIntegrityError, match="feature metadata"):
        PITCatalogAdapter._verify_scope(manifest, [feature], [sample])


def test_catalog_adapter_rejects_escaped_or_cross_bucket_parquet_reference(tmp_path) -> None:
    with pytest.raises(PITCatalogIntegrityError, match="escapes object-store root"):
        from investment_research.training.catalog_adapter import _object_key
        _object_key("file-object://../outside.parquet")

    class AuthoritativeStore:
        bucket = "formal-pit"

        def get(self, key):  # pragma: no cover - must never be reached
            raise AssertionError(f"unexpected read: {key}")

    partition = PITDatasetPartition(
        market="us", dataset="samples", schema_version="pit-sample-v1", trade_year=2026,
        object_ref="s3://other-bucket/pit/us/samples/part.parquet", payload_hash="a" * 64,
        schema_hash="b" * 64, row_count=1, quality_status=PITDataQualityStatus.PASSED,
        created_at=datetime.now(timezone.utc),
    )
    adapter = PITCatalogAdapter(None, PITParquetStore(AuthoritativeStore()))
    with pytest.raises(PITCatalogIntegrityError, match="bucket is not authoritative"):
        adapter._read_verified(partition)
