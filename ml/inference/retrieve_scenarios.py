from __future__ import annotations

import argparse
import json
from typing import Any

from ml.common import FEATURE_VERSION, connect, now_iso
from ml.data.build_dataset import DEFAULT_SYMBOL_MARKETS, load_history
from ml.data.feature_store import build_feature_metadata, persist_feature_record, validate_feature_metadata
from ml.features.labels import forward_max_drawdown, forward_return, forward_volatility
from ml.features.market import FEATURE_NAMES, tabular_snapshot, window_features
from ml.models.scenario_encoder import cosine, scenario_embedding
from ml.training.registry import ensure_ml_schema, latest_approved_model


def seed_historical_snapshots(symbol: str, model_id: str, max_snapshots: int = 36) -> int:
    ensure_ml_schema()
    symbol = symbol.upper()
    with connect() as conn:
        existing = conn.execute("select count(*) as count from feature_snapshots where symbol = ?", (symbol,)).fetchone()["count"]
    if existing >= max(8, max_snapshots // 3):
        return 0
    rows = load_history(symbol, allow_synthetic=True)
    if len(rows) < 190:
        return 0
    closes = [float(row["close_price"]) for row in rows]
    volumes = [float(row["volume"]) for row in rows]
    dates = [str(row["trade_date"]) for row in rows]
    source_names = [str(row["source_name"]) for row in rows]
    source_status = "degraded" if any("synthetic" in str(row["source_name"]).lower() for row in rows) else "live"
    start = 120
    end = len(rows) - 64
    if end <= start:
        return 0
    step = max(1, (end - start) // max_snapshots)
    created_at = now_iso()
    inserted = 0
    with connect() as conn:
        for index in range(start, end, step):
            as_of_date = str(rows[index]["trade_date"])
            field_metadata = build_feature_metadata(
                as_of_date=as_of_date,
                source=", ".join(sorted(set(source_names))),
                dates=dates[: index + 1],
                sources=source_names[: index + 1],
                tabular_field_count=len(FEATURE_NAMES),
                windows={"window120": 120},
            )
            payload = {
                "featureNames": FEATURE_NAMES,
                "tabular": tabular_snapshot(closes, volumes, index),
                "window120": window_features(closes, volumes, index, 120),
                "fieldMetadata": field_metadata,
                "pointInTimeAudit": validate_feature_metadata(field_metadata),
            }
            cursor = conn.execute(
                """
                insert or ignore into feature_snapshots(symbol, market, as_of_date, feature_version, features_json, source_status_json, created_at)
                values(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    DEFAULT_SYMBOL_MARKETS.get(symbol, "us"),
                    as_of_date,
                    FEATURE_VERSION,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(
                        {
                            "sourceStatus": source_status,
                            "seededBy": "historical_scenario_retrieval",
                            "modelId": model_id,
                            "pointInTimeAudit": payload["pointInTimeAudit"],
                        },
                        ensure_ascii=False,
                    ),
                    created_at,
                ),
            )
            inserted += max(0, cursor.rowcount)
        conn.commit()
    for index in range(start, end, step):
        as_of_date = str(rows[index]["trade_date"])
        features = {
            "featureNames": FEATURE_NAMES,
            "tabular": tabular_snapshot(closes, volumes, index),
            "window120": window_features(closes, volumes, index, 120),
        }
        field_metadata = build_feature_metadata(
            as_of_date=as_of_date,
            source=", ".join(sorted(set(source_names))),
            dates=dates[: index + 1],
            sources=source_names[: index + 1],
            tabular_field_count=len(FEATURE_NAMES),
            windows={"window120": 120},
        )
        persist_feature_record(symbol, DEFAULT_SYMBOL_MARKETS.get(symbol, "us"), as_of_date, features, field_metadata)
    return inserted


def read_feature_snapshots(model_id: str) -> list[dict[str, Any]]:
    ensure_ml_schema()
    with connect() as conn:
        rows = conn.execute("select * from feature_snapshots order by as_of_date").fetchall()
    snapshots = []
    for row in rows:
        features = json.loads(row["features_json"])
        snapshots.append({**dict(row), "features": features, "embedding": scenario_embedding(features.get("window120", [])), "model_id": model_id})
    return snapshots


def retrieve(symbol: str, as_of_date: str | None = None, top_k: int = 5, write_sqlite: bool = True) -> dict[str, Any]:
    model = latest_approved_model()
    if not model:
        return {"ok": False, "reason": "No approved model.", "similarScenarios": []}
    seed_historical_snapshots(symbol, model["model_id"])
    snapshots = read_feature_snapshots(model["model_id"])
    query_candidates = [item for item in snapshots if item["symbol"] == symbol.upper()]
    if as_of_date:
        query_candidates = [item for item in query_candidates if item["as_of_date"] == as_of_date]
    if not query_candidates:
        return {"ok": False, "reason": "No query feature snapshot.", "similarScenarios": []}
    query = query_candidates[-1]
    matches = []
    for item in snapshots:
        if item["symbol"] == query["symbol"] and item["as_of_date"] == query["as_of_date"]:
            continue
        matches.append({**item, "similarity": cosine(query["embedding"], item["embedding"])})
    matches = sorted(matches, key=lambda item: item["similarity"], reverse=True)[:top_k]
    scenarios = [
        {
            "matchedSymbol": item["symbol"],
            "matchedAsOfDate": item["as_of_date"],
            "similarity": round(float(item["similarity"]), 4),
            **scenario_outcomes(item["symbol"], item["as_of_date"]),
            "modelId": model["model_id"],
        }
        for item in matches
    ]
    if write_sqlite:
        write_embeddings_and_matches(query, snapshots, scenarios)
    return {"ok": True, "querySymbol": query["symbol"], "queryAsOfDate": query["as_of_date"], "modelId": model["model_id"], "similarScenarios": scenarios}


def scenario_outcomes(symbol: str, as_of_date: str) -> dict[str, float]:
    rows = load_history(symbol, allow_synthetic=True)
    closes = [float(row["close_price"]) for row in rows]
    index = next((idx for idx, row in enumerate(rows) if str(row["trade_date"]) == as_of_date), -1)
    if index < 0:
        return {"return1w": 0.0, "return1m": 0.0, "return3m": 0.0, "maxDrawdown1w": 0.0, "maxDrawdown1m": 0.0, "maxDrawdown3m": 0.0, "volatility1m": 0.0}
    return {
        "return1w": round(forward_return(closes, index, 5), 4),
        "return1m": round(forward_return(closes, index, 21), 4),
        "return3m": round(forward_return(closes, index, 63), 4),
        "maxDrawdown1w": round(forward_max_drawdown(closes, index, 5), 4),
        "maxDrawdown1m": round(forward_max_drawdown(closes, index, 21), 4),
        "maxDrawdown3m": round(forward_max_drawdown(closes, index, 63), 4),
        "volatility1m": round(forward_volatility(closes, index, 21), 4),
    }


def write_embeddings_and_matches(query: dict[str, Any], snapshots: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> None:
    created_at = now_iso()
    with connect() as conn:
        for item in snapshots:
            conn.execute(
                """
                insert or replace into scenario_embeddings(symbol, market, as_of_date, window_size, model_id, embedding_json, source_status, created_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["symbol"],
                    item["market"],
                    item["as_of_date"],
                    120,
                    item["model_id"],
                    json.dumps(item["embedding"]),
                    json.loads(item["source_status_json"]).get("sourceStatus", "unknown"),
                    created_at,
                ),
            )
        for scenario in scenarios:
            conn.execute(
                """
                insert into similar_scenarios(query_symbol, query_as_of_date, matched_symbol, matched_as_of_date, similarity, return_1w, return_1m, return_3m, max_drawdown_1w, max_drawdown_1m, max_drawdown_3m, volatility_1m, model_id, created_at)
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query["symbol"],
                    query["as_of_date"],
                    scenario["matchedSymbol"],
                    scenario["matchedAsOfDate"],
                    scenario["similarity"],
                    scenario["return1w"],
                    scenario["return1m"],
                    scenario["return3m"],
                    scenario["maxDrawdown1w"],
                    scenario["maxDrawdown1m"],
                    scenario["maxDrawdown3m"],
                    scenario["volatility1m"],
                    scenario["modelId"],
                    created_at,
                ),
            )
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--write-sqlite", action="store_true")
    args = parser.parse_args()
    print(json.dumps(retrieve(args.symbol, args.as_of_date, args.top_k, args.write_sqlite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
