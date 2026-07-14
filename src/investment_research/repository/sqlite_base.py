from __future__ import annotations

import json
import sqlite3

from investment_research.domain.base import DomainEntity


class NamedTupleRow(tuple):
    def __new__(cls, values: tuple[object, ...], columns: tuple[str, ...]):
        instance = super().__new__(cls, values)
        instance._columns = columns
        return instance

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            return super().__getitem__(self._columns.index(key))
        return super().__getitem__(key)


def named_tuple_row_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> NamedTupleRow:
    columns = tuple(description[0] for description in cursor.description)
    return NamedTupleRow(row, columns)


class SQLiteRepositoryMixin:
    table_name: str
    model_cls: type[DomainEntity]

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def _serialize_entity(self, entity: DomainEntity) -> tuple[str, str, str, int, str, str, str, str]:
        payload = entity.model_dump(mode="json")
        return (
            str(entity.id),
            entity.status.value,
            entity.version.schema_version,
            entity.version.entity_version,
            entity.provenance.data_mode.value,
            entity.provenance.source_type.value,
            entity.provenance.observed_at.isoformat(),
            json.dumps(payload),
        )

    def _deserialize_entity(self, payload: str):
        return self.model_cls.model_validate_json(payload)

    def _payload_from_row(self, row: tuple[object, ...]) -> str:
        return str(row[0])
