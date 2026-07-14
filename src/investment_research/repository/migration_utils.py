"""Compatibility helper for the pre-relational SQL migration scripts."""

from __future__ import annotations

from alembic import context, op
from sqlalchemy import text


def execute_sql_script(sql: str) -> None:
    bind = op.get_bind()
    if not context.is_offline_mode() and bind.dialect.name == "sqlite":
        bind.connection.executescript(sql)
        return
    for statement in sql.split(";"):
        normalized = statement.strip()
        if normalized:
            bind.execute(text(normalized))
