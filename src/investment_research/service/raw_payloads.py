from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from investment_research.domain.trusted_market import RawDataBatch


class AppendOnlyRawPayloadService:
    """Persist provider bytes before normalization; request reuse is immutable."""

    def __init__(self, object_store, trusted_market_repository) -> None:
        self.object_store = object_store
        self.repository = trusted_market_repository

    def persist(
        self,
        payload: bytes,
        *,
        provider: str,
        request_id: str,
        dataset: str,
        schema_version: str,
        fetched_at: datetime,
        available_at: datetime,
        symbol: str | None = None,
        interval: str | None = None,
        source_time: datetime | None = None,
        received_at: datetime | None = None,
        coverage_start: datetime | None = None,
        coverage_end: datetime | None = None,
        market_session: str | None = None,
    ) -> RawDataBatch:
        digest = sha256(payload).hexdigest()
        existing = self.repository.raw_batch_by_request(provider, request_id)
        if existing is not None:
            if existing.payload_hash != digest:
                raise ValueError(
                    "provider request_id cannot be rewritten with different bytes"
                )
            return existing
        key = f"raw/{provider}/{dataset}/{fetched_at:%Y/%m/%d}/{digest}.bin"
        payload_ref = self.object_store.put(
            key, payload, content_type="application/octet-stream"
        )
        persisted_at = datetime.now(fetched_at.tzinfo)
        item = RawDataBatch(
            provider=provider,
            request_id=request_id,
            dataset=dataset,
            payload_ref=payload_ref,
            payload_hash=digest,
            schema_version=schema_version,
            symbol=symbol,
            interval=interval,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            market_session=market_session,
            fetched_at=fetched_at,
            source_time=source_time,
            received_at=received_at or fetched_at,
            persisted_at=persisted_at,
            available_at=available_at,
        )
        try:
            return self.repository.add_raw_batch(item)
        except Exception:
            # Hash-addressed objects are safe to retain for recovery/reconciliation.
            raise
