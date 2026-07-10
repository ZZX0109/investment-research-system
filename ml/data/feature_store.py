from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from ml.common import FEATURE_VERSION, connect, now_iso
from ml.features.market import FEATURE_NAMES


@dataclass(frozen=True)
class FeatureFieldMeta:
    asOfDate: str
    source: str
    availableAt: str
    revisionId: str


def parse_day(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def revision_id(source: str, available_at: str, payload: Any | None = None) -> str:
    raw = json.dumps({"source": source, "availableAt": available_at, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def assert_feature_meta(meta: dict[str, Any], field_name: str) -> None:
    required = ["asOfDate", "source", "availableAt", "revisionId"]
    missing = [key for key in required if not meta.get(key)]
    if missing:
        raise AssertionError(f"feature {field_name} missing PIT metadata: {', '.join(missing)}")
    if parse_day(meta["availableAt"]) > parse_day(meta["asOfDate"]):
        raise AssertionError(
            f"future data leakage: feature {field_name} availableAt {meta['availableAt']} after asOfDate {meta['asOfDate']}"
        )


def validate_feature_metadata(field_metadata: dict[str, dict[str, Any]], expected_fields: list[str] | None = None) -> dict[str, Any]:
    expected = expected_fields or list(field_metadata.keys())
    missing_fields = [field for field in expected if field not in field_metadata]
    violations: list[str] = []
    for field in expected:
        meta = field_metadata.get(field)
        if not meta:
            continue
        try:
            assert_feature_meta(meta, field)
        except AssertionError as exc:
            violations.append(str(exc))
    return {
        "ok": not missing_fields and not violations,
        "checkedFieldCount": len(expected),
        "missingFieldCount": len(missing_fields),
        "futureLeakageCount": len([item for item in violations if "future data leakage" in item]),
        "violations": [*missing_fields[:10], *violations[:10]],
    }


def field_names_for_window(window_name: str, window_size: int) -> list[str]:
    return [f"{window_name}[{idx}].{name}" for idx in range(window_size) for name in FEATURE_NAMES]


def expected_feature_fields(features: dict[str, Any]) -> list[str]:
    fields = [f"tabular.{name}" for name in features.get("featureNames", FEATURE_NAMES)]
    for key in ["window60", "window120", "window252"]:
        window = features.get(key) or []
        if window:
            fields.extend(field_names_for_window(key, len(window)))
    return fields


def build_feature_metadata(
    *,
    as_of_date: str,
    source: str,
    dates: list[str],
    sources: list[str] | None = None,
    tabular_field_count: int | None = None,
    windows: dict[str, int] | None = None,
) -> dict[str, dict[str, str]]:
    tabular_count = tabular_field_count or len(FEATURE_NAMES)
    windows = windows or {}
    sources = sources or [source for _ in dates]
    field_metadata: dict[str, dict[str, str]] = {}
    as_of_source = sources[-1] if sources else source
    as_of_revision = revision_id(as_of_source, as_of_date, {"asOfDate": as_of_date})
    for name in FEATURE_NAMES[:tabular_count]:
        field_metadata[f"tabular.{name}"] = {
            "asOfDate": as_of_date,
            "source": as_of_source,
            "availableAt": as_of_date,
            "revisionId": as_of_revision,
        }
    for window_name, window_size in windows.items():
        start = len(dates) - window_size
        window_dates = dates[start:]
        window_sources = sources[start:]
        for row_index, available_at in enumerate(window_dates):
            row_source = window_sources[row_index] if row_index < len(window_sources) else source
            row_revision = revision_id(row_source, available_at, {"asOfDate": as_of_date, "window": window_name, "row": row_index})
            for name in FEATURE_NAMES:
                field_metadata[f"{window_name}[{row_index}].{name}"] = {
                    "asOfDate": as_of_date,
                    "source": row_source,
                    "availableAt": available_at,
                    "revisionId": row_revision,
                }
    audit = validate_feature_metadata(field_metadata)
    if not audit["ok"]:
        raise AssertionError(f"invalid point-in-time feature metadata: {audit['violations']}")
    return field_metadata


def flatten_feature_values(features: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    names = features.get("featureNames", FEATURE_NAMES)
    for idx, value in enumerate(features.get("tabular", [])):
        name = names[idx] if idx < len(names) else f"feature_{idx}"
        values[f"tabular.{name}"] = value
    for key in ["window60", "window120", "window252"]:
        for row_idx, row in enumerate(features.get(key) or []):
            for col_idx, value in enumerate(row):
                name = names[col_idx] if col_idx < len(names) else f"feature_{col_idx}"
                values[f"{key}[{row_idx}].{name}"] = value
    return values


def ensure_feature_store_schema() -> None:
    with connect() as conn:
        conn.execute(
            """
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
            )
            """
        )
        conn.commit()


def persist_feature_record(symbol: str, market: str, as_of_date: str, features: dict[str, Any], field_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ensure_feature_store_schema()
    values = flatten_feature_values(features)
    audit = validate_feature_metadata(field_metadata, list(values.keys()))
    if not audit["ok"]:
        raise AssertionError(f"cannot persist invalid PIT features: {audit['violations']}")
    created_at = now_iso()
    with connect() as conn:
        for field_name, value in values.items():
            meta = field_metadata[field_name]
            conn.execute(
                """
                insert or replace into point_in_time_features(symbol, market, as_of_date, feature_version, field_name, field_value_json, source, available_at, revision_id, created_at)
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    market,
                    as_of_date,
                    FEATURE_VERSION,
                    field_name,
                    json.dumps(value, ensure_ascii=False),
                    meta["source"],
                    meta["availableAt"],
                    meta["revisionId"],
                    created_at,
                ),
            )
        conn.commit()
    return audit


def latest_feature_store_audit(symbol: str) -> dict[str, Any]:
    ensure_feature_store_schema()
    with connect() as conn:
        as_of_row = conn.execute(
            "select as_of_date from point_in_time_features where symbol = ? order by as_of_date desc, created_at desc limit 1",
            (symbol.upper(),),
        ).fetchone()
        if not as_of_row:
            return {"ok": False, "status": "missing", "checkedFieldCount": 0, "futureLeakageCount": 0, "violations": ["no point-in-time features"]}
        rows = conn.execute(
            """
            select field_name, as_of_date, source, available_at, revision_id
            from point_in_time_features
            where symbol = ? and as_of_date = ?
            """,
            (symbol.upper(), as_of_row["as_of_date"]),
        ).fetchall()
    metadata = {
        row["field_name"]: {
            "asOfDate": row["as_of_date"],
            "source": row["source"],
            "availableAt": row["available_at"],
            "revisionId": row["revision_id"],
        }
        for row in rows
    }
    audit = validate_feature_metadata(metadata)
    return {**audit, "status": "valid" if audit["ok"] else "failed", "asOfDate": as_of_row["as_of_date"]}
