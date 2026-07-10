from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.ml_service import build_latest_ml_risk_summary


def test_latest_ml_risk_summary_missing_model_has_source_metadata(tmp_path):
    db_path = tmp_path / "ml.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            create table risk_predictions (
                symbol text,
                created_at text
            )
            """
        )
        conn.execute(
            """
            create table similar_scenarios (
                query_symbol text,
                created_at text,
                similarity real
            )
            """
        )

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def build_source_meta(**kwargs):
        return kwargs

    summary = build_latest_ml_risk_summary(
        "NVDA",
        connect=connect,
        build_source_meta=build_source_meta,
        current_data_mode=lambda: "sandbox",
        now_utc=lambda: datetime(2026, 7, 6, tzinfo=timezone.utc),
        iso=lambda value: value.isoformat().replace("+00:00", "Z"),
        parse_iso=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    )

    assert summary["modelStatus"] == "missing"
    assert summary["calibrationStatus"] == "missing"
    assert summary["sourceMeta"]["provider"] == "missing_model_registry"
    assert summary["sourceMeta"]["mode"] == "sandbox"
    assert summary["sourceMeta"]["synthetic_ratio"] == 1.0


def test_latest_ml_risk_summary_uses_backend_prediction_when_feature_audit_rows_are_absent(tmp_path):
    db_path = tmp_path / "ml_prediction.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            create table risk_predictions (
                symbol text,
                market text,
                as_of_date text,
                model_id text,
                horizon text,
                risk_regime text,
                drawdown_p50 real,
                drawdown_p90 real,
                volatility_p50 real,
                confidence real,
                calibration_status text,
                valid_until text,
                created_at text
            );
            create table similar_scenarios (
                query_symbol text,
                query_as_of_date text,
                matched_symbol text,
                matched_as_of_date text,
                similarity real,
                return_1w real,
                return_1m real,
                return_3m real,
                max_drawdown_1w real,
                max_drawdown_1m real,
                max_drawdown_3m real,
                volatility_1m real,
                model_id text,
                created_at text
            );
            create table model_registry (
                model_id text,
                model_type text,
                trained_until text,
                metrics_json text
            );
            """
        )
        conn.execute(
            """
            insert into risk_predictions values(
                'UNITFALLBACK', 'us', '2026-07-07', 'risk-model-unit', '1m', 'medium',
                -0.03, -0.08, 0.2, 0.72, 'valid', '2026-07-08T00:00:00Z', '2026-07-07T10:00:00Z'
            )
            """
        )
        conn.execute(
            "insert into model_registry values(?, ?, ?, ?)",
            (
                "risk-model-unit",
                "tabular_baseline",
                "2026-07-01",
                '{"calibration_ece":0.04,"pinball_loss":0.05,"crps":0.06,"var_breach_rate":0.02,"walk_forward":{"windowCount":1},"purged_cv":{"foldCount":1}}',
            ),
        )

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    summary = build_latest_ml_risk_summary(
        "UNITFALLBACK",
        connect=connect,
        build_source_meta=lambda **kwargs: kwargs,
        current_data_mode=lambda: "demo",
        now_utc=lambda: datetime(2026, 7, 7, tzinfo=timezone.utc),
        iso=lambda value: value.isoformat().replace("+00:00", "Z"),
        parse_iso=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    )

    assert summary["featureStoreAudit"]["ok"] is True
    assert summary["featureStoreAudit"]["status"] == "backend-linked"
    assert summary["featureStoreAudit"]["futureLeakageCount"] == 0
