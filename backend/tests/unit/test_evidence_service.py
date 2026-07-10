from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from backend.evidence_service import ensure_seed_evidence, get_active_evidence, get_experience_history


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def build_source_meta(**kwargs):
    return {
        "mode": kwargs.get("mode", "demo"),
        "provider": kwargs["provider"],
        "as_of": kwargs["as_of"],
        "overrides": kwargs.get("overrides", []),
        "synthetic_ratio": kwargs.get("synthetic_ratio", 0.0),
    }


def contains_demo_placeholder(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return "demo" in lowered or "placeholder" in lowered or "占位" in value or "样例" in value


def test_ensure_seed_evidence_inserts_required_records_once(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)
    holding = {"symbol": "UNIT", "name": "Unit Test Asset", "sector": "测试行业"}

    with connect() as conn:
        ensure_seed_evidence(conn=conn, holding=holding, now_utc=lambda: fixed_now, iso=iso)
        ensure_seed_evidence(conn=conn, holding=holding, now_utc=lambda: fixed_now, iso=iso)
        conn.commit()
        rows = conn.execute("select source_type, confidence from evidence_records where symbol = 'UNIT'").fetchall()

    assert len(rows) == 5
    assert {row["source_type"] for row in rows} == {
        "market_data",
        "financial_report",
        "news_event",
        "historical_analogy",
        "model_inference",
    }
    assert all(0 <= row["confidence"] <= 1 for row in rows)


def test_get_active_evidence_archives_expired_and_returns_source_meta(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)

    with connect() as conn:
        conn.executemany(
            """
            insert into evidence_records(symbol, claim, source_type, source_name, source_url, observed_at, valid_until, confidence, is_model_inferred)
            values(?, ?, ?, ?, null, ?, ?, ?, ?)
            """,
            [
                (
                    "UNIT",
                    "expired demo placeholder claim",
                    "news_event",
                    "demo placeholder provider",
                    iso(fixed_now - timedelta(days=3)),
                    iso(fixed_now - timedelta(days=1)),
                    0.25,
                    0,
                ),
                (
                    "UNIT",
                    "active demo placeholder claim",
                    "market_data",
                    "demo placeholder provider",
                    iso(fixed_now - timedelta(hours=1)),
                    iso(fixed_now + timedelta(days=1)),
                    0.55,
                    0,
                ),
            ],
        )
        conn.commit()

    records = get_active_evidence(
        "UNIT",
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        parse_iso=parse_iso,
        build_source_meta=build_source_meta,
        contains_demo_placeholder=contains_demo_placeholder,
    )

    assert len(records) == 1
    assert records[0]["claim"] == "active demo placeholder claim"
    assert records[0]["isExpired"] is False
    assert records[0]["sourceMeta"]["provider"] == "demo placeholder provider"
    assert records[0]["sourceMeta"]["synthetic_ratio"] == 1.0

    with connect() as conn:
        archived = conn.execute(
            "select archived_at from evidence_records where symbol = 'UNIT' and claim = 'expired demo placeholder claim'"
        ).fetchone()
        history_count = conn.execute("select count(*) as count from experience_history where symbol = 'UNIT'").fetchone()["count"]

    assert archived["archived_at"] == iso(fixed_now)
    assert history_count == 1


def test_get_experience_history_uses_symbol_limit_and_schema(app, test_db_path):
    connect = make_connect(test_db_path)
    with connect() as conn:
        conn.executemany(
            """
            insert into experience_history(symbol, archived_claim, source_type, observed_at, archived_at, reason)
            values('UNIT', ?, 'news_event', '2026-07-01T00:00:00Z', ?, 'valid_until elapsed')
            """,
            [(f"claim {idx}", f"2026-07-07T0{idx}:00:00Z") for idx in range(10)],
        )
        conn.commit()

    rows = get_experience_history("UNIT", connect=connect)

    assert len(rows) == 8
    assert rows[0]["symbol"] == "UNIT"
    assert set(rows[0]) == {"id", "symbol", "archived_claim", "source_type", "observed_at", "archived_at", "reason"}
