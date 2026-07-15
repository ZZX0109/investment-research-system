from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256

from investment_research.domain.pit import HistoricalUniverseMembership
from investment_research.domain.trusted_market import RawDataBatch
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from investment_research.training.models import (
    CanonicalInstrument, CoverageGroup, InstrumentType, Market, PreparedPriceBar,
)
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.pit_pipeline import PITDatasetPublisher
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.pit_rebuild import (
    PITRawPayload, PITRebuildBatchOrchestrator, PITRebuildInput, PITRebuildOrchestrator,
    ProviderPreflightResult,
)


def _bars() -> list[PreparedPriceBar]:
    start = date(2024, 1, 2)
    output = []
    for index in range(55):
        day = start + timedelta(days=index)
        timestamp = datetime.combine(day, datetime.min.time(), timezone.utc)
        value = 100 + index
        output.append(PreparedPriceBar(
            symbol="AAPL", trade_date=day, open_native=value, high_native=value + 1,
            low_native=value - 1, close_native=value, open_normalized=value,
            high_normalized=value + 1, low_normalized=value - 1, close_normalized=value,
            volume=1000, currency="USD", target_currency="USD", is_halted=False,
            is_suspended=False, published_at=timestamp, available_at=timestamp,
            calendar_code="XNYS", provider="licensed",
        ))
    return output


def test_rebuild_isolated_per_scope_and_publishes_four_task_manifests(tmp_path) -> None:
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    raw = RawDataBatch(
        provider="licensed", request_id="prices-1", dataset="daily_bars",
        payload_ref="file-object://raw/one.json", payload_hash=sha256(b"raw").hexdigest(),
        schema_version="v1", fetched_at=now, source_time=now, exchange_time=now,
        received_at=now, persisted_at=now, available_at=now,
    )
    universe = HistoricalUniverseMembership(
        symbol="AAPL", market="us", exchange="XNAS", instrument_type="equity",
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc), listed_on=date(1980, 1, 1),
        available_at=datetime(2020, 1, 1, tzinfo=timezone.utc), provider="licensed",
    )
    uow = SQLiteUnitOfWork(tmp_path / "rebuild.db")
    publisher = PITDatasetPublisher(
        PITParquetStore(LocalObjectStore(tmp_path / "objects")), uow.pit_catalog
    )
    request = PITRebuildInput(
        market="us",
        instrument=CanonicalInstrument(
            symbol="AAPL", name="Apple", market=Market.US, instrument_type=InstrumentType.EQUITY,
            coverage_group=CoverageGroup.US_CORE, currency="USD", exchange="XNAS",
        ),
        price_bars=_bars(), feature_events=[], standard_events=[], universe=[universe],
        corporate_actions=[], raw_batches=[raw],
        preflight=ProviderPreflightResult(
            market="us", authorized=True, sla_name="contract", raw_payload_complete=True,
            historical_time_fields_complete=True, revision_support=True,
        ),
        generated_at=now, trade_year=2024, historical_universe_version="us-v1",
        adjustment_policy="qfq", event_coverage_status="confirmed_none",
    )
    result = PITRebuildOrchestrator(
        publisher=publisher, trusted_market_repository=uow.trusted_market
    ).rebuild(training_run_id="run-1", request=request, decision_context="close_confirmed")
    assert not result.blocked_scopes
    assert len(result.manifests) == 4
    assert all(
        {"standard_prices", "historical_universe"}
        <= {
            partition.dataset
            for partition in uow.pit_catalog.partitions(market="us")
            if partition.object_ref in manifest.standard_parquet_refs
        }
        for manifest in result.manifests.values()
    )
    assert uow.pit_catalog.manifest(
        training_run_id="run-1", market="us", decision_context="close_confirmed", task="direction_1d"
    ) is not None
    uow.close()


def test_rebuild_blocks_only_affected_context_when_provider_preflight_fails(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "blocked.db")
    request = PITRebuildInput(
        market="cn",
        instrument=CanonicalInstrument(symbol="600519.SH", name="Kweichow Moutai", market=Market.CN, instrument_type=InstrumentType.EQUITY,
            coverage_group=CoverageGroup.CN_A_SHARE, currency="CNY", exchange="XSHG"),
        price_bars=[], feature_events=[], standard_events=[], universe=[], corporate_actions=[], raw_batches=[],
        preflight=ProviderPreflightResult(market="cn", authorized=False, reasons=["authorization_missing"]),
        generated_at=datetime(2026, 7, 14, tzinfo=timezone.utc), trade_year=2026,
        historical_universe_version="cn-v1", adjustment_policy="qfq",
    )
    result = PITRebuildOrchestrator(
        publisher=PITDatasetPublisher(PITParquetStore(LocalObjectStore(tmp_path / "objects")), uow.pit_catalog)
    ).rebuild(training_run_id="run-1", request=request, decision_context="pre_open")
    assert len(result.blocked_scopes) == 4
    assert all(key.startswith("cn:pre_open:") for key in result.blocked_scopes)
    uow.close()


def test_rebuild_persists_raw_bytes_before_using_their_lineage(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "raw-first.db")
    request = PITRebuildInput(
        market="us", instrument=CanonicalInstrument(symbol="AAPL", name="Apple", market=Market.US,
            instrument_type=InstrumentType.EQUITY, coverage_group=CoverageGroup.US_CORE, currency="USD"),
        price_bars=[], feature_events=[], standard_events=[], universe=[], corporate_actions=[], raw_batches=[],
        raw_payloads=[PITRawPayload(provider="licensed", request_id="raw-1", dataset="daily_bars",
            payload=b'{"rows":[]}', schema_version="v1", available_at=now, received_at=now)],
        preflight=ProviderPreflightResult(market="us", authorized=True, sla_name="contract",
            raw_payload_complete=True, historical_time_fields_complete=True, revision_support=True),
        generated_at=now, trade_year=2026, historical_universe_version="us-v1", adjustment_policy="qfq",
    )
    orchestrator = PITRebuildOrchestrator(
        publisher=PITDatasetPublisher(PITParquetStore(LocalObjectStore(tmp_path / "parquet")), uow.pit_catalog),
        raw_ingestion_service=RawPayloadIngestionService(uow, object_store=LocalObjectStore(tmp_path / "raw")),
    )
    persisted = orchestrator._persist_raw_payloads(request)
    assert len(persisted.raw_batches) == 1
    assert persisted.raw_batches[0].payload_hash == sha256(b'{"rows":[]}').hexdigest()
    assert uow.trusted_market.raw_batch_by_request("licensed", "raw-1") is not None
    uow.close()


def test_snapshot_hash_changes_when_visible_normalized_revision_changes(tmp_path) -> None:
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    raw = RawDataBatch(
        provider="licensed", request_id="prices-1", dataset="daily_bars",
        payload_ref="file-object://raw/one.json", payload_hash=sha256(b"raw").hexdigest(),
        schema_version="v1", fetched_at=now, source_time=now, exchange_time=now,
        received_at=now, persisted_at=now, available_at=now,
    )
    instrument = CanonicalInstrument(symbol="AAPL", name="Apple", market=Market.US,
        instrument_type=InstrumentType.EQUITY, coverage_group=CoverageGroup.US_CORE,
        currency="USD", exchange="XNAS")
    request = PITRebuildInput(
        market="us", instrument=instrument, price_bars=_bars(), feature_events=[], standard_events=[],
        universe=[], corporate_actions=[], raw_batches=[raw],
        preflight=ProviderPreflightResult(market="us", authorized=True, sla_name="contract",
            raw_payload_complete=True, historical_time_fields_complete=True, revision_support=True),
        generated_at=now, trade_year=2024, historical_universe_version="us-v1", adjustment_policy="qfq",
    )
    sample = TrainingDatasetBuilder(feature_version="investment-risk-features-v2", data_version="v1").build_samples(
        instrument=instrument, price_bars=request.price_bars, decision_context="close_confirmed",
    )[0]
    uow = SQLiteUnitOfWork(tmp_path / "hash.db")
    orchestrator = PITRebuildOrchestrator(
        publisher=PITDatasetPublisher(PITParquetStore(LocalObjectStore(tmp_path / "objects")), uow.pit_catalog)
    )
    original = orchestrator._snapshot(sample, request, "close_confirmed")
    revised_bars = list(request.price_bars)
    revised_bars[0] = revised_bars[0].model_copy(update={"revision": 2, "normalized_hash": "b" * 64})
    revised = orchestrator._snapshot(sample, replace(request, price_bars=revised_bars), "close_confirmed")
    assert original.content_hash != revised.content_hash
    uow.close()


def test_batch_rebuild_isolates_failed_market_and_runs_both_contexts(tmp_path) -> None:
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    raw = RawDataBatch(
        provider="licensed", request_id="prices-us", dataset="daily_bars",
        payload_ref="file-object://raw/us.json", payload_hash=sha256(b"us").hexdigest(),
        schema_version="v1", fetched_at=now, source_time=now, exchange_time=now,
        received_at=now, persisted_at=now, available_at=now,
    )
    healthy = PITRebuildInput(
        market="us",
        instrument=CanonicalInstrument(symbol="AAPL", name="Apple", market=Market.US,
            instrument_type=InstrumentType.EQUITY, coverage_group=CoverageGroup.US_CORE,
            currency="USD", exchange="XNAS"),
        price_bars=_bars(), feature_events=[], standard_events=[], corporate_actions=[],
        raw_batches=[raw], generated_at=now, trade_year=2024,
        historical_universe_version="us-v1", adjustment_policy="qfq",
        universe=[HistoricalUniverseMembership(
            symbol="AAPL", market="us", exchange="XNAS", instrument_type="equity",
            effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc), listed_on=date(1980, 1, 1),
            available_at=datetime(2020, 1, 1, tzinfo=timezone.utc), provider="licensed",
        )],
        preflight=ProviderPreflightResult(market="us", authorized=True, sla_name="contract",
            raw_payload_complete=True, historical_time_fields_complete=True, revision_support=True),
    )
    blocked = PITRebuildInput(
        market="cn", instrument=healthy.instrument.model_copy(update={"symbol": "600519", "market": Market.CN}),
        price_bars=[], feature_events=[], standard_events=[], universe=[], corporate_actions=[], raw_batches=[],
        preflight=ProviderPreflightResult(market="cn", authorized=False, reasons=["authorization_missing"]),
        generated_at=now, trade_year=2024, historical_universe_version="cn-v1", adjustment_policy="qfq",
    )
    uow = SQLiteUnitOfWork(tmp_path / "batch.db")
    single = PITRebuildOrchestrator(
        publisher=PITDatasetPublisher(PITParquetStore(LocalObjectStore(tmp_path / "objects")), uow.pit_catalog)
    )
    result = PITRebuildBatchOrchestrator(single).rebuild_all(
        training_run_id="run-batch", requests=[healthy, blocked]
    )
    assert set(result.by_scope) == {
        "us:close_confirmed", "us:pre_open", "cn:close_confirmed", "cn:pre_open"
    }
    assert len(result.manifests) == 8
    assert len(result.blocked_scopes) == 8
    assert all(key.startswith("cn:") for key in result.blocked_scopes)
    uow.close()
