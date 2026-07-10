from __future__ import annotations

import sqlite3
from typing import Any


def upsert_tool_registry(conn: sqlite3.Connection, *, tools: list[dict[str, Any]], updated_at: str) -> None:
    conn.executemany(
        """
        insert into tool_registry(tool_id, name, category, description, freshness_rule, output_contract, updated_at)
        values(:toolId, :name, :category, :description, :freshnessRule, :outputContract, :updatedAt)
        on conflict(tool_id) do update set
          name = excluded.name,
          category = excluded.category,
          description = excluded.description,
          freshness_rule = excluded.freshness_rule,
          output_contract = excluded.output_contract,
          updated_at = excluded.updated_at
        """,
        [{**tool, "updatedAt": updated_at} for tool in tools],
    )


def insert_tool_invocation(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    tool_id: str,
    symbol: str,
    input_json: str,
    output_summary: str,
    source_name: str,
    observed_at: str,
    status: str,
    failure_reason: str | None,
    evidence_id: int | None,
) -> None:
    conn.execute(
        """
        insert into tool_invocations(
          run_id, tool_id, symbol, input_json, output_summary, source_name,
          observed_at, status, failure_reason, evidence_id
        )
        values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            tool_id,
            symbol,
            input_json,
            output_summary,
            source_name,
            observed_at,
            status,
            failure_reason,
            evidence_id,
        ),
    )


def fetch_tool_invocation_rows(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          tool_invocations.*,
          tool_registry.name,
          tool_registry.category,
          tool_registry.description,
          tool_registry.freshness_rule,
          tool_registry.output_contract
        from tool_invocations
        join tool_registry on tool_registry.tool_id = tool_invocations.tool_id
        where run_id = ?
        order by tool_invocations.id
        """,
        (run_id,),
    ).fetchall()
