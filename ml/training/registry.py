from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml.common import connect, now_iso


def ensure_ml_schema() -> None:
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists model_registry (
              model_id text primary key,
              model_type text not null,
              version text not null,
              feature_version text not null,
              trained_until text not null,
              validation_window text not null,
              test_window text not null,
              metrics_json text not null,
              artifact_path text not null,
              status text not null default 'candidate',
              created_at text not null
            );

            create table if not exists feature_snapshots (
              id integer primary key autoincrement,
              symbol text not null,
              market text not null,
              as_of_date text not null,
              feature_version text not null,
              features_json text not null,
              source_status_json text not null,
              created_at text not null,
              unique(symbol, as_of_date, feature_version)
            );

            create table if not exists point_in_time_features (
              id integer primary key autoincrement,
              symbol text not null,
              market text not null,
              as_of_date text not null,
              feature_version text not null,
              field_name text not null,
              field_value_json text not null,
              source text not null,
              available_at text not null,
              revision_id text not null,
              created_at text not null,
              unique(symbol, as_of_date, feature_version, field_name, revision_id)
            );

            create table if not exists risk_predictions (
              id integer primary key autoincrement,
              symbol text not null,
              market text not null,
              as_of_date text not null,
              model_id text not null,
              horizon text not null,
              risk_regime text not null,
              drawdown_p50 real not null,
              drawdown_p90 real not null,
              volatility_p50 real not null,
              confidence real not null,
              calibration_status text not null,
              valid_until text not null,
              created_at text not null
            );

            create table if not exists scenario_embeddings (
              id integer primary key autoincrement,
              symbol text not null,
              market text not null,
              as_of_date text not null,
              window_size integer not null,
              model_id text not null,
              embedding_json text not null,
              source_status text not null,
              created_at text not null,
              unique(symbol, as_of_date, window_size, model_id)
            );

            create table if not exists similar_scenarios (
              id integer primary key autoincrement,
              query_symbol text not null,
              query_as_of_date text not null,
              matched_symbol text not null,
              matched_as_of_date text not null,
              similarity real not null,
              return_1w real not null,
              return_1m real not null,
              return_3m real not null,
              max_drawdown_1w real not null default 0,
              max_drawdown_1m real not null,
              max_drawdown_3m real not null,
              volatility_1m real not null default 0,
              model_id text not null,
              created_at text not null
            );
            """
        )
        try:
            conn.execute("alter table similar_scenarios add column volatility_1m real not null default 0")
        except Exception:
            pass
        try:
            conn.execute("alter table similar_scenarios add column max_drawdown_1w real not null default 0")
        except Exception:
            pass
        conn.commit()


def approval_gates(metrics: dict[str, Any], model_type: str) -> list[dict[str, Any]]:
    if model_type != "tabular_baseline":
        return [
            {
                "name": "production_model_type",
                "passed": False,
                "value": model_type,
                "limit": "tabular_baseline only; deep models require human model-card review",
            }
        ]
    judge_v2 = metrics.get("judge_v2") or {}
    if judge_v2.get("gates"):
        return list(judge_v2["gates"])
    source_status = metrics.get("source_status") or {}
    return [
        {
            "name": "calibration_ece_limit",
            "passed": float(metrics.get("calibration_ece", 1.0)) <= 0.12,
            "value": metrics.get("calibration_ece"),
            "limit": "<=0.12",
        },
        {
            "name": "pinball_loss_limit",
            "passed": float(metrics.get("pinball_loss", 1.0)) <= 0.2,
            "value": metrics.get("pinball_loss"),
            "limit": "<=0.2",
        },
        {
            "name": "crps_limit",
            "passed": float(metrics.get("crps", 1.0)) <= 0.4,
            "value": metrics.get("crps"),
            "limit": "<=0.4",
        },
        {
            "name": "var_breach_upper_bound",
            "passed": float(metrics.get("var_breach_rate", 1.0)) <= 0.35,
            "value": metrics.get("var_breach_rate"),
            "limit": "<=0.35",
        },
        {
            "name": "walk_forward_multiple_windows",
            "passed": int(metrics.get("walk_forward", {}).get("windowCount") or 0) >= 2,
            "value": metrics.get("walk_forward", {}).get("windowCount"),
            "limit": ">=2",
        },
        {
            "name": "purged_cv_three_folds",
            "passed": int(metrics.get("purged_cv", {}).get("foldCount") or 0) >= 3,
            "value": metrics.get("purged_cv", {}).get("foldCount"),
            "limit": ">=3",
        },
        {
            "name": "out_of_sample_evaluation",
            "passed": int(metrics.get("evaluated_sample_count") or 0) > 0,
            "value": metrics.get("evaluated_sample_count"),
            "limit": ">0",
        },
        {
            "name": "no_degraded_training_samples",
            "passed": int(source_status.get("degraded", 0) or 0) == 0,
            "value": source_status,
            "limit": "degraded=0",
        },
    ]


def approval_status(metrics: dict[str, Any], model_type: str) -> str:
    return "approved" if all(item["passed"] for item in approval_gates(metrics, model_type)) else "candidate"


def register_model(
    model_id: str,
    model_type: str,
    feature_version: str,
    metrics: dict[str, Any],
    artifact_path: Path,
    trained_until: str,
) -> dict[str, Any]:
    ensure_ml_schema()
    status = approval_status(metrics, model_type)
    row = {
        "model_id": model_id,
        "model_type": model_type,
        "version": model_id,
        "feature_version": feature_version,
        "trained_until": trained_until,
        "validation_window": "2023-01-01..2023-12-31",
        "test_window": "2024-01-01..2025-12-31",
        "metrics_json": json.dumps(metrics, ensure_ascii=False),
        "artifact_path": str(artifact_path),
        "status": status,
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            insert or replace into model_registry(model_id, model_type, version, feature_version, trained_until, validation_window, test_window, metrics_json, artifact_path, status, created_at)
            values(:model_id, :model_type, :version, :feature_version, :trained_until, :validation_window, :test_window, :metrics_json, :artifact_path, :status, :created_at)
            """,
            row,
        )
        conn.commit()
    return {**row, "metrics": metrics}


def list_models() -> list[dict[str, Any]]:
    ensure_ml_schema()
    with connect() as conn:
        rows = conn.execute("select * from model_registry order by created_at desc").fetchall()
    return [{**dict(row), "metrics": json.loads(row["metrics_json"])} for row in rows]


def latest_approved_model() -> dict[str, Any] | None:
    ensure_ml_schema()
    with connect() as conn:
        row = conn.execute("select * from model_registry where status = 'approved' order by created_at desc limit 1").fetchone()
    return {**dict(row), "metrics": json.loads(row["metrics_json"])} if row else None
