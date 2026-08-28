#!/usr/bin/env python3
"""Aggregate immutable CN Shadow sessions into the canonical gate artifact.

The project requirement is 60 independent valid trading dates, not 60
securities observed on one date.  This report de-duplicates session ids across
research runs and exposes both the date count and the raw session count so the
UI and release gates cannot accidentally satisfy the requirement with a wide
single-day batch.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.research_shadow import FileResearchShadowStore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT / "artifacts/research_shadow")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/research_shadow/summary.json")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--decision-context", default="close_confirmed")
    parser.add_argument("--minimum-trade-dates", type=int, default=60)
    return parser.parse_args()


def _session_roots(root: Path) -> list[Path]:
    direct = root / "sessions"
    candidates = [direct] if direct.is_dir() else []
    candidates.extend(path for path in root.glob("runs/**/sessions") if path.is_dir())
    return sorted(set(candidates))


def build_summary(root: Path, *, market: str, decision_context: str, minimum_trade_dates: int) -> dict[str, Any]:
    sessions: dict[str, Any] = {}
    outcomes: dict[int, int] = {horizon: 0 for horizon in (1, 5, 20, 60)}
    source_roots: list[str] = []
    raw_session_count = 0
    # Use the main shadow root for outcome lookup so outcomes written to
    # root/outcomes/ are found regardless of which session sub-tree a
    # session was discovered in.
    outcome_store = FileResearchShadowStore(root)
    for sessions_path in _session_roots(root):
        store = FileResearchShadowStore(sessions_path.parent)
        try:
            selected = store.list_sessions(market=market, decision_context=decision_context)
        except (OSError, ValueError):
            continue
        if selected:
            source_roots.append(str(sessions_path.parent.resolve()))
        raw_session_count += len(selected)
        for session in selected:
            key = str(session.id)
            if key in sessions:
                continue
            sessions[key] = session
            for outcome in outcome_store.list_outcomes(session.id):
                if outcome.horizon_sessions in outcomes and outcome.data_complete:
                    outcomes[outcome.horizon_sessions] += 1

    values = list(sessions.values())
    valid_dates = sorted({item.trade_date for item in values if item.evidence_valid})
    abstained = sum(bool(item.abstained) for item in values)
    date_count = len(valid_dates)
    real_predictions = sum(1 for item in values if item.frozen_prediction)
    empty_predictions = len(values) - real_predictions
    real_prediction_dates = sorted({
        item.trade_date for item in values
        if item.evidence_valid and item.frozen_prediction
    })
    empty_prediction_dates = sorted({
        item.trade_date for item in values
        if item.evidence_valid and not item.frozen_prediction
    })
    abstain_reason_counts = Counter(
        reason for item in values for reason in item.abstain_reasons
    )
    prediction_state_counts = {
        "real_prediction": real_predictions,
        "placeholder_abstain": sum(
            not item.frozen_prediction
            and item.abstain_reasons == ["empty_prediction_placeholder"]
            for item in values
        ),
        "gated_abstain": sum(
            not item.frozen_prediction
            and bool(item.abstain_reasons)
            and "empty_prediction_placeholder" not in item.abstain_reasons
            for item in values
        ),
        "invalid_evidence": sum(not item.evidence_valid for item in values),
    }
    outcome_backfill = sum(outcomes.values())
    return {
        "schema_version": "cn-research-shadow-summary-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "decision_context": decision_context,
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "status": "complete" if date_count >= minimum_trade_dates else "blocked",
        "session_count": len(values),
        "valid_session_count": date_count,
        "valid_trade_date_count": date_count,
        "minimum_required_trade_dates": minimum_trade_dates,
        "evaluated_trade_dates": [item.isoformat() for item in valid_dates],
        "answered_count": len(values) - abstained,
        "abstained_count": abstained,
        "abstain_rate": abstained / len(values) if values else 0.0,
        "average_coverage_ratio": sum(float(item.coverage_ratio) for item in values) / len(values) if values else 0.0,
        "latest_trade_date": max((item.trade_date for item in values), default=None),
        "completed_outcomes": {str(key): value for key, value in outcomes.items()},
        "real_prediction_count": real_predictions,
        "empty_prediction_count": empty_predictions,
        "real_prediction_trade_date_count": len(real_prediction_dates),
        "empty_prediction_trade_date_count": len(empty_prediction_dates),
        "prediction_trade_date_coverage": (
            len(real_prediction_dates) / date_count if date_count else 0.0
        ),
        "outcome_backfill_count": outcome_backfill,
        "abstain_reason_counts": dict(sorted(abstain_reason_counts.items())),
        "prediction_state_counts": prediction_state_counts,
        "source_roots": source_roots,
        "duplicate_session_count_removed": raw_session_count - len(values),
        "missing_reason": None if date_count >= minimum_trade_dates else "independent_valid_trade_dates_below_60",
    }


def main() -> int:
    args = _parse_args()
    payload = build_summary(
        args.root.resolve(), market=args.market,
        decision_context=args.decision_context,
        minimum_trade_dates=max(1, args.minimum_trade_dates),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "status": payload["status"],
        "session_count": payload["session_count"],
        "valid_trade_date_count": payload["valid_trade_date_count"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0 if payload["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
