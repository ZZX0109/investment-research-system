from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from investment_research.domain.trusted_market import RawDataBatch
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import ObjectStore, build_object_store


class RawPayloadIngestionService:
    """Persist provider bytes before normalization so every batch is replayable."""

    def __init__(self, uow: SQLiteUnitOfWork, *, object_store: ObjectStore | None = None) -> None:
        self.uow = uow
        self.object_store = object_store or build_object_store()

    def persist(
        self,
        *,
        provider: str,
        request_id: str,
        dataset: str,
        payload: bytes,
        schema_version: str,
        available_at: datetime,
        symbol: str | None = None,
        interval: str | None = None,
        source_time: datetime | None = None,
        market_session: str | None = None,
    ) -> RawDataBatch:
        existing = self.uow.trusted_market.raw_batch_by_request(provider, request_id)
        digest = hashlib.sha256(payload).hexdigest()
        if existing is not None:
            if existing.payload_hash != digest:
                raise ValueError("Provider request_id was reused with different payload bytes")
            return existing
        fetched_at = datetime.now(timezone.utc)
        key = f"raw-market/{fetched_at:%Y/%m/%d}/{provider}/{request_id}-{digest[:12]}.json"
        payload_ref = self.object_store.put(key, payload, content_type="application/json")
        batch = RawDataBatch(
            provider=provider,
            request_id=request_id,
            dataset=dataset,
            payload_ref=payload_ref,
            payload_hash=digest,
            schema_version=schema_version,
            symbol=symbol,
            interval=interval,
            market_session=market_session,
            fetched_at=fetched_at,
            source_time=source_time,
            available_at=available_at,
        )
        try:
            return self.uow.trusted_market.add_raw_batch(batch)
        except Exception:
            self.object_store.delete(key)
            raise


class ProviderChain:
    def __init__(self, primary, backup) -> None:
        self.primary = primary
        self.backup = backup

    def call(self, method: str, *args, **kwargs):
        failures: list[str] = []
        for role, provider in (("primary", self.primary), ("backup", self.backup)):
            try:
                result = getattr(provider, method)(*args, **kwargs)
                return result, role, failures
            except Exception as exc:
                failures.append(f"{role}:{type(exc).__name__}:{exc}")
        raise RuntimeError("All configured market data providers failed: " + "; ".join(failures))
