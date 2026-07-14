"""Minimal DB-API compatibility adapter for the existing repository contracts.

It translates the SQLite repository dialect (qmark parameters and replace-style
upserts) to PostgreSQL so `/api/v1` can use PostgreSQL during the cutover.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


class PostgresRow:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.columns = tuple(values)

    def __getitem__(self, key: int | str) -> Any:
        return self.values[key] if isinstance(key, str) else self.values[self.columns[key]]


class PostgresCursor:
    def __init__(self, cursor) -> None:
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return None if row is None else PostgresRow(dict(row))

    def fetchall(self):
        return [PostgresRow(dict(row)) for row in self.cursor.fetchall()]

    @property
    def rowcount(self) -> int:
        return int(getattr(self.cursor, "rowcount", 0))


class PostgresConnection:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL runtime") from exc
        self._connection = psycopg.connect(dsn, row_factory=dict_row)
        self.row_factory = None

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> PostgresCursor:
        if sql.strip().upper().startswith("PRAGMA"):
            return PostgresCursor(_EmptyCursor())
        cursor = self._connection.execute(_translate_sql(sql), tuple(params or ()))
        return PostgresCursor(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


class _EmptyCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


def _translate_sql(sql: str) -> str:
    normalized = sql.strip()
    replace_match = re.match(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if replace_match:
        table, raw_columns = replace_match.groups()
        columns = [column.strip() for column in raw_columns.split(",")]
        conflict_key = "id" if "id" in columns else "run_id" if "run_id" in columns else columns[0]
        updates = ", ".join(
            f"{column}=EXCLUDED.{column}" for column in columns if column != conflict_key
        )
        normalized = re.sub(
            r"INSERT\s+OR\s+REPLACE\s+INTO",
            "INSERT INTO",
            normalized,
            count=1,
            flags=re.IGNORECASE,
        )
        normalized = f"{normalized} ON CONFLICT ({conflict_key}) DO UPDATE SET {updates}"
    elif re.match(r"INSERT\s+OR\s+IGNORE\s+INTO", normalized, flags=re.IGNORECASE):
        normalized = re.sub(
            r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", normalized, count=1, flags=re.IGNORECASE
        )
        normalized = f"{normalized} ON CONFLICT DO NOTHING"
    return normalized.replace("?", "%s")
