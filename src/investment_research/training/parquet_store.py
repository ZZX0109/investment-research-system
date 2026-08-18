from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from investment_research.service.object_store import ObjectStore


class PITParquetStore:
    """Schema-bearing Parquet datasets in object storage with deterministic hashes."""

    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    def write_partition(
        self,
        records: Iterable[BaseModel],
        *,
        market: str,
        dataset: str,
        schema_version: str,
        trade_year: int,
        partition_id: str,
    ) -> tuple[str, str, str, int]:
        import pyarrow as pa
        import pyarrow.parquet as pq

        rows = [_parquet_safe(record.model_dump(mode="json")) for record in records]
        if not rows:
            raise ValueError("cannot write an empty PIT parquet partition")
        table = pa.Table.from_pylist(rows)
        sink = io.BytesIO()
        pq.write_table(table, sink, compression="zstd", version="2.6")
        payload = sink.getvalue()
        payload_hash = hashlib.sha256(payload).hexdigest()
        # Parquet writers may canonicalize timestamp units or attach metadata;
        # hash the persisted schema rather than the pre-serialization table.
        persisted = pq.read_table(io.BytesIO(payload))
        schema_hash = parquet_schema_hash(persisted.schema)
        key = (
            f"pit/{market}/{dataset}/{schema_version}/trade_year={trade_year}/"
            f"part-{partition_id}-{payload_hash[:12]}.parquet"
        )
        ref = self.object_store.put(
            key, payload, content_type="application/vnd.apache.parquet"
        )
        return ref, payload_hash, schema_hash, table.num_rows

    def read_partition(self, key: str, *, expected_payload_hash: str | None = None) -> list[dict]:
        import pyarrow.parquet as pq

        payload = self.object_store.get(_object_key(key))
        if expected_payload_hash is not None:
            observed = hashlib.sha256(payload).hexdigest()
            if observed != expected_payload_hash:
                raise ValueError(
                    f"parquet_payload_hash_mismatch:{key}:expected={expected_payload_hash}:observed={observed}"
                )
        return pq.read_table(io.BytesIO(payload)).to_pylist()


def _object_key(ref: str) -> str:
    if ref.startswith("file-object://"):
        return _safe_object_key(ref.removeprefix("file-object://"))
    if ref.startswith("s3://"):
        parts = ref.removeprefix("s3://").split("/", 1)
        if len(parts) != 2:
            raise ValueError("invalid S3 object reference")
        return _safe_object_key(parts[1])
    return _safe_object_key(ref)


def _safe_object_key(key: str) -> str:
    path = Path(key)
    if not key or path.is_absolute() or ".." in path.parts:
        raise ValueError("object-store reference escapes configured root")
    return key


def _parquet_safe(row: dict) -> dict:
    """Keep dynamic maps schema-stable; empty Arrow structs are not writable."""
    return {
        key: json.dumps(value, sort_keys=True, separators=(",", ":"))
        if isinstance(value, dict)
        else value
        for key, value in row.items()
    }


def parquet_schema_hash(schema) -> str:
    """Hash logical Arrow schema, excluding writer-added metadata."""
    canonical = schema.remove_metadata() if schema.metadata else schema
    return hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()
