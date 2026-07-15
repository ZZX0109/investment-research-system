from datetime import datetime, timezone
from pathlib import Path

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
