from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Callable

from .analysis_run_repository import (
    fetch_recent_research_runs,
    fetch_research_run,
    fetch_report_snapshot,
    insert_research_run,
    upsert_report_snapshot,
)
from .schemas import AnalysisRunCreate, AnalysisRunRecord, RecentRunRecord, ReportSnapshotRecord


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def stable_snapshot_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def create_analysis_run(
    symbol: str,
    preference: str,
    risk_score: float,
    summary: str,
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    input_snapshot: dict[str, Any] | None = None,
    model_version: str | None = None,
    evidence_ids: list[int] | None = None,
    reasoning_steps: list[dict[str, Any]] | None = None,
    judge_payload: dict[str, Any] | None = None,
    risk_conclusion: dict[str, Any] | None = None,
    report_version: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = AnalysisRunCreate(
        symbol=symbol,
        preference=preference,
        risk_score=risk_score,
        summary=summary,
        input_snapshot=input_snapshot or {},
        model_version=model_version,
        evidence_ids=evidence_ids or [],
        reasoning_steps=reasoning_steps or [],
        judge_payload=judge_payload or {},
        risk_conclusion=risk_conclusion or {},
        report_version=report_version,
        source_meta=source_meta,
    )
    started_at = now_utc()
    finished_at = now_utc()
    source_meta_payload = dump_model(payload.source_meta) if payload.source_meta else {}
    resolved_report_version = payload.report_version or f"report-{started_at.strftime('%Y%m%d%H%M%S')}"
    row = {
        "run_id": f"{payload.symbol}-{payload.preference}-{started_at.strftime('%Y%m%d%H%M%S%f')}",
        "symbol": payload.symbol,
        "preference": payload.preference,
        "started_at": iso(started_at),
        "finished_at": iso(finished_at),
        "data_status": payload.data_status,
        "risk_score": payload.risk_score,
        "summary": payload.summary,
        "input_snapshot_hash": stable_snapshot_hash(payload.input_snapshot) if payload.input_snapshot else None,
        "input_snapshot_json": json.dumps(payload.input_snapshot, ensure_ascii=False),
        "model_version": payload.model_version,
        "evidence_ids_json": json.dumps(payload.evidence_ids, ensure_ascii=False),
        "reasoning_steps_json": json.dumps(payload.reasoning_steps, ensure_ascii=False),
        "judge_json": json.dumps(payload.judge_payload, ensure_ascii=False),
        "risk_conclusion_json": json.dumps(payload.risk_conclusion, ensure_ascii=False),
        "report_version": resolved_report_version,
        "source_meta_json": json.dumps(source_meta_payload, ensure_ascii=False),
    }
    with closing(connect()) as conn:
        insert_research_run(conn, row)
        conn.commit()
    return dump_model(
        AnalysisRunRecord(
            runId=row["run_id"],
            symbol=row["symbol"],
            preference=row["preference"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            dataStatus=row["data_status"],
            riskScore=row["risk_score"],
            summary=row["summary"],
            inputSnapshotHash=row["input_snapshot_hash"],
            inputSnapshot=payload.input_snapshot,
            modelVersion=row["model_version"],
            evidenceIds=payload.evidence_ids,
            reasoningSteps=payload.reasoning_steps,
            judge=payload.judge_payload,
            riskConclusion=payload.risk_conclusion,
            reportVersion=resolved_report_version,
            sourceMeta=source_meta_payload,
        )
    )


def recent_analysis_runs(
    symbol: str,
    *,
    connect: Callable[[], sqlite3.Connection],
    limit: int = 5,
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_recent_research_runs(conn, symbol, limit)
    return [
        dump_model(
            RecentRunRecord(
                runId=row["run_id"],
                symbol=row["symbol"],
                preference=row["preference"],
                startedAt=row["started_at"],
                riskScore=row["risk_score"],
                summary=row["summary"],
                reportVersion=row["report_version"],
                qualityGateStatus=(parse_json(row["judge_json"], {}).get("qualityGate") or {}).get("status"),
                sourceMeta=parse_json(row["source_meta_json"], {}),
            )
        )
        for row in rows
    ]


def analysis_run_by_id(
    *,
    connect: Callable[[], sqlite3.Connection],
    run_id: str,
) -> dict[str, Any] | None:
    with closing(connect()) as conn:
        row = fetch_research_run(conn, run_id)
    if not row:
        return None
    input_snapshot = parse_json(row["input_snapshot_json"] if "input_snapshot_json" in row.keys() else None, {})
    return dump_model(
        AnalysisRunRecord(
            runId=row["run_id"],
            symbol=row["symbol"],
            preference=row["preference"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            dataStatus=row["data_status"],
            riskScore=row["risk_score"],
            summary=row["summary"],
            inputSnapshotHash=row["input_snapshot_hash"],
            inputSnapshot=input_snapshot,
            modelVersion=row["model_version"],
            evidenceIds=parse_json(row["evidence_ids_json"], []),
            reasoningSteps=parse_json(row["reasoning_steps_json"], []),
            judge=parse_json(row["judge_json"], {}),
            riskConclusion=parse_json(row["risk_conclusion_json"], {}),
            reportVersion=row["report_version"],
            sourceMeta=parse_json(row["source_meta_json"], {}),
        )
    )


def store_report_snapshot(
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    run_id: str,
    symbol: str,
    preference: str,
    report_version: str,
    markdown: str,
) -> None:
    with closing(connect()) as conn:
        upsert_report_snapshot(
            conn,
            run_id=run_id,
            symbol=symbol,
            preference=preference,
            report_version=report_version,
            markdown=markdown,
            created_at=iso(now_utc()),
        )
        conn.commit()


def get_report_snapshot(
    *,
    connect: Callable[[], sqlite3.Connection],
    run_id: str,
) -> dict[str, Any] | None:
    with closing(connect()) as conn:
        row = fetch_report_snapshot(conn, run_id)
    if not row:
        return None
    return dump_model(ReportSnapshotRecord(**dict(row)))


def previous_run_delta(
    symbol: str,
    current_score: float,
    *,
    connect: Callable[[], sqlite3.Connection],
) -> dict[str, Any]:
    runs = recent_analysis_runs(symbol, connect=connect)
    previous = runs[0] if runs else None
    if not previous:
        return {"hasPrevious": False, "riskScoreDelta": 0, "summary": "暂无上一版报告，可从本次 run 开始建立版本复盘。"}
    delta = round(current_score - float(previous["riskScore"]), 1)
    direction = "上升" if delta > 0 else "下降" if delta < 0 else "持平"
    return {
        "hasPrevious": True,
        "previousRunId": previous["runId"],
        "riskScoreDelta": delta,
        "summary": f"相比上一版报告，风险评分{direction} {abs(delta)} 分。需要查看证据变化和触发器状态。",
    }
