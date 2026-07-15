from __future__ import annotations

from pathlib import Path

from investment_research.repository.sqlite import PostgresUnitOfWork, SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore, build_object_store
from investment_research.training.catalog_adapter import PITCatalogAdapter
from investment_research.training.parquet_store import PITParquetStore


def open_formal_catalog(*, catalog_ref: str, local_object_store_root: Path | None = None):
    """Open only PostgreSQL or explicit local test catalog storage.

    The local form exists for deterministic PIT fixtures; production uses the
    PostgreSQL + configured S3-compatible object-store path.
    """
    if catalog_ref.startswith("postgresql://") or catalog_ref.startswith("postgresql+psycopg://"):
        uow = PostgresUnitOfWork(catalog_ref)
        store = build_object_store()
    elif catalog_ref.startswith("sqlite:///"):
        database = Path(catalog_ref.removeprefix("sqlite:///"))
        if local_object_store_root is None:
            raise ValueError("local PIT catalog requires explicit object-store root")
        uow = SQLiteUnitOfWork(database)
        store = LocalObjectStore(local_object_store_root)
    else:
        raise ValueError("formal PIT catalog must be postgresql:// or sqlite:/// test fixture")
    return uow, PITCatalogAdapter(
        uow.pit_catalog,
        PITParquetStore(store),
        market_repository=uow.trusted_market,
    )
