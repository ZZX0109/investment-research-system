from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from investment_research.domain.data_tier import DataTier
from investment_research.domain.data_tier import formal_data_blocking_reasons
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


def test_duplicate_payloads_share_bytes_but_keep_fetch_observations(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "catalog.db")
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(tmp_path / "raw"))
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    first = service.persist(
        provider="akshare", request_id="free-akshare-1", dataset="daily_bars_raw",
        payload=b"same", schema_version="v1", symbol="600519",
        received_at=now, available_at=now, data_tier=DataTier.RESEARCH_PIT,
    )
    second = service.persist(
        provider="akshare", request_id="free-akshare-2", dataset="daily_bars_raw",
        payload=b"same", schema_version="v1", symbol="600519",
        received_at=now, available_at=now, data_tier=DataTier.RESEARCH_PIT,
    )
    assert first.id != second.id
    assert first.payload_ref == second.payload_ref
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1
    assert len(uow.trusted_market.raw_batches(dataset="daily_bars_raw")) == 2
    uow.close()


def test_formal_gate_rejects_free_provider_and_request_prefix_independently() -> None:
    assert formal_data_blocking_reasons(
        data_tier=DataTier.FORMAL_PIT, provider="akshare", request_id="licensed-looking",
    ) == ["free_research_provider_forbidden_in_formal_path"]
    assert formal_data_blocking_reasons(
        data_tier=DataTier.FORMAL_PIT, provider="licensed-cn", request_id="free-manual-1",
    ) == ["free_request_prefix_forbidden_in_formal_path"]


def test_filtered_raw_batches_do_not_fail_on_unrelated_legacy_rows(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "catalog.db")
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    # This shape mirrors pre-qualification catalog rows.  It is intentionally
    # invalid as a RawDataBatch, but belongs to qfq and must not break a raw
    # rebuild that asks for a different dataset.
    uow.connection.execute(
        "INSERT INTO raw_data_batches (id,provider,request_id,dataset,fetched_at,available_at,quality_status,data_tier,time_semantics,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid4()), "legacy", "legacy-qfq", "daily_bars_qfq", now.isoformat(),
            now.isoformat(), "degraded", "research_pit", "legacy_time_semantics",
            json.dumps({"dataset": "daily_bars_qfq", "symbol": "920011"}),
        ),
    )
    uow.connection.commit()
    assert uow.trusted_market.raw_batches(dataset="daily_bars_raw") == []
    assert uow.trusted_market.raw_batches(dataset="daily_bars_qfq", strict=False) == []
    assert len(uow.trusted_market.last_raw_batch_errors) == 1
    uow.close()
