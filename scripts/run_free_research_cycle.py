#!/usr/bin/env python3
"""Run a repeatable, fail-isolated public-data research collection cycle.

This is intentionally a research scheduler entry point, not a formal PIT
publisher.  It invokes the append-only collector one group at a time so an
unavailable provider cannot prevent the remaining public sources from being
recorded.  Use an external scheduler (cron, launchd, CI, or a container job)
to run it after each market close.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo


PROJECT = Path(__file__).resolve().parent.parent
COLLECTOR = PROJECT / "scripts" / "fetch_free_research_data.py"
REBUILDER = PROJECT / "scripts" / "rebuild_cn_research_pit.py"
sys.path.insert(0, str(PROJECT / "src"))
from investment_research.domain.decision_context import build_market_decision_context
from investment_research.domain.pit import EventCoverageStatus
from investment_research.service.research_shadow import (
    FileResearchShadowStore,
    ResearchShadowController,
    ResearchShadowSession,
    coverage_snapshot_hash,
)
DEFAULT_CYCLES = (
    ("cn", "prices"),
    ("cn", "events"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one free research collection cycle")
    parser.add_argument("--markets", nargs="+", choices=("cn", "us", "hk", "jp"))
    parser.add_argument("--groups", nargs="+", choices=("prices", "events", "macro"))
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--max-symbols", type=int, default=None, help="Optional development cap; scheduled research runs enumerate the full public CN universe by default.")
    parser.add_argument("--full-history", action="store_true", help="Ignore incremental cursors and repair complete public daily history.")
    parser.add_argument("--no-discover-cn-universe", action="store_true", help="Use the configured fixed CN research symbols; do not enumerate the public universe.")
    parser.add_argument("--rebuild-timeout-seconds", type=int, default=1800)
    parser.add_argument("--skip-rebuild", action="store_true", help="Collect raw payloads only; the default also rebuilds CN standard/snapshot/feature/sample layers.")
    parser.add_argument("--skip-collection", action="store_true", help="Do not contact public providers; use with --skip-rebuild to freeze an already generated prediction file.")
    parser.add_argument(
        "--run-directory", type=Path,
        default=PROJECT / "artifacts" / "free_research_runs",
    )
    parser.add_argument(
        "--decision-context", choices=("close_confirmed",),
        default="close_confirmed", help="The zero-budget mainline freezes only confirmed-close research.",
    )
    parser.add_argument("--trade-date", type=date.fromisoformat, default=None)
    parser.add_argument("--trading-dates-file", type=Path, help="Optional JSON/YAML mapping of market codes to authoritative exchange trading dates.")
    parser.add_argument("--freeze-shadow", action="store_true", help="Freeze research-only abstain/prediction placeholders from the coverage ledger.")
    parser.add_argument("--shadow-directory", type=Path, default=PROJECT / "artifacts" / "research_shadow")
    parser.add_argument("--prediction-file", type=Path, help="Optional frozen research prediction JSON produced by the CN research inference step.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    allowed = set(args.markets or ("cn",))
    groups = set(args.groups or ("prices", "events", "macro"))
    started = datetime.now(timezone.utc)
    run_id = f"free-research-{started:%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"
    results: list[dict[str, object]] = []
    for market, group in (() if args.skip_collection else DEFAULT_CYCLES):
        if market not in allowed or group not in groups:
            continue
        command = [
            sys.executable, str(COLLECTOR), "--markets", market, "--only", group,
        ]
        if args.max_symbols is not None:
            command.extend(["--max-symbols-per-market", str(args.max_symbols)])
        if args.full_history:
            command.append("--full-history")
        if args.no_discover_cn_universe:
            command.append("--no-discover-cn-universe")
        item: dict[str, object] = {"market": market, "group": group, "command": command}
        try:
            completed = subprocess.run(
                command, cwd=PROJECT, text=True, capture_output=True,
                timeout=args.timeout_seconds, check=False,
            )
            item.update(
                status="completed" if completed.returncode == 0 else "failed",
                return_code=completed.returncode,
                stdout=completed.stdout[-4000:], stderr=completed.stderr[-4000:],
            )
        except subprocess.TimeoutExpired as exc:
            item.update(
                status="timed_out", return_code=None,
                stdout=(exc.stdout or "")[-4000:], stderr=(exc.stderr or "")[-4000:],
            )
        results.append(item)
    if "cn" in allowed and not args.skip_rebuild:
        command = [sys.executable, str(REBUILDER)]
        item = {"market": "cn", "group": "pit_rebuild", "command": command}
        try:
            completed = subprocess.run(
                command, cwd=PROJECT, text=True, capture_output=True,
                timeout=args.rebuild_timeout_seconds, check=False,
            )
            item.update(
                status="completed" if completed.returncode == 0 else "failed",
                return_code=completed.returncode,
                stdout=completed.stdout[-4000:], stderr=completed.stderr[-4000:],
            )
        except subprocess.TimeoutExpired as exc:
            item.update(
                status="timed_out", return_code=None,
                stdout=(exc.stdout or "")[-4000:], stderr=(exc.stderr or "")[-4000:],
            )
        results.append(item)
    completed_at = datetime.now(timezone.utc)
    coverage_path = PROJECT / "artifacts" / "free_research_coverage.json"
    coverage_payload = _coverage_payload(coverage_path)
    trading_dates = _trading_dates(args.trading_dates_file)
    shadow_sessions = (
        _freeze_prediction_file(args.prediction_file, root=args.shadow_directory)
        if args.freeze_shadow and args.prediction_file is not None
        else _freeze_research_shadows(
            coverage_payload=coverage_payload, markets=allowed,
            context=args.decision_context, trade_date=args.trade_date,
            frozen_at=completed_at, root=args.shadow_directory, trading_dates=trading_dates,
        ) if args.freeze_shadow else []
    )
    report = {
        "schema_version": "free-research-cycle-v1",
        "run_id": run_id,
        "mode": "research_only",
        "formal_deployment_allowed": False,
        "synthetic_count": 0,
        "data_tier": "research_pit",
        "decision_context": args.decision_context,
        "coverage_ref": str(coverage_path),
        "research_shadow_sessions": shadow_sessions,
        "started_at": started.isoformat(),
        "completed_at": completed_at.isoformat(),
        "results": results,
    }
    args.run_directory.mkdir(parents=True, exist_ok=True)
    output = args.run_directory / f"{run_id}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0 if all(item["status"] == "completed" for item in results) else 2


def _coverage_payload(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _freeze_research_shadows(*, coverage_payload: dict, markets: set[str], context: str, trade_date: date | None, frozen_at: datetime, root: Path, trading_dates: dict[str, list[date]]) -> list[dict[str, str]]:
    by_market = {item.get("market"): item for item in coverage_payload.get("market_coverage", [])}
    calendar_by_market = {"cn": "XSHG", "us": "XNYS", "hk": "XHKG", "jp": "XTKS"}
    store = FileResearchShadowStore(root)
    output: list[dict[str, str]] = []
    for market in sorted(markets):
        zone_by_market = {"cn": "Asia/Shanghai", "us": "America/New_York", "hk": "Asia/Hong_Kong", "jp": "Asia/Tokyo"}
        local_date = trade_date or frozen_at.astimezone(ZoneInfo(zone_by_market[market])).date()
        # Schedulers should pass the exchange trade date explicitly on holiday
        # boundaries.  This default is only the market-local civil date.
        decision = build_market_decision_context(
            local_date, context, calendar_code=calendar_by_market[market],
            trading_dates=trading_dates.get(market),
        )
        ledger = by_market.get(market, {})
        event_value = ledger.get("event_coverage_status", "unsupported")
        coverage = float(ledger.get("coverage_ratio", 0.0))
        reasons = ["research_model_not_configured"]
        if coverage < 0.75:
            reasons.append("research_minimum_price_coverage_below_75pct")
        if event_value not in {"events_present", "confirmed_none"}:
            reasons.append(f"event_coverage:{event_value}")
        snapshot_hash = coverage_snapshot_hash({"ledger": ledger, "decision": decision.model_dump(mode="json")})
        session = ResearchShadowSession(
            market=market, decision_context=context, trade_date=local_date,
            frozen_at=frozen_at, market_snapshot_id=f"free-research:{market}:{context}:{local_date.isoformat()}",
            market_snapshot_hash=snapshot_hash, coverage_ratio=coverage,
            event_coverage_status=EventCoverageStatus(event_value),
            provider_chain=sorted({record.get("provider", "unknown") for record in ledger.get("records", [])}),
            abstained=True, abstain_reasons=reasons,
        )
        stored = store.freeze(session)
        output.append({"market": market, "session_id": str(stored.id), "status": "abstain"})
    return output


def _trading_dates(path: Path | None) -> dict[str, list[date]]:
    if path is None:
        return {}
    try:
        import yaml
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("trading dates file is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("trading dates file must map market codes to date lists")
    result: dict[str, list[date]] = {}
    for market, values in payload.items():
        if market not in {"cn", "us", "hk", "jp"} or not isinstance(values, list):
            raise ValueError("trading dates file has an invalid market/date list")
        result[market] = sorted({date.fromisoformat(str(value)) for value in values})
    return result


def _freeze_prediction_file(path: Path, *, root: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("predictions", [])
    if not isinstance(records, list):
        raise ValueError("prediction file must contain a predictions list")
    controller = ResearchShadowController(FileResearchShadowStore(root))
    output: list[dict[str, str]] = []
    for record in records:
        session = controller.freeze_prediction(
            market="cn", decision_context=record["decision_context"],
            cohort=record["cohort"], task=record["task"], symbol=record["symbol"],
            trade_date=date.fromisoformat(record["trade_date"]),
            frozen_at=datetime.fromisoformat(record["frozen_at"].replace("Z", "+00:00")),
            market_snapshot_id=record["market_snapshot_id"],
            market_snapshot_hash=record["market_snapshot_hash"],
            prediction=record["prediction"], prediction_price=record.get("prediction_price"),
            model_artifact_hashes=record.get("model_artifact_hashes", {}),
            # The aggregate row coverage deliberately includes unsupported
            # optional event/reference features.  Shadow validity must use
            # the same core price/market coverage gate as inference; otherwise
            # a valid price prediction is rewritten as abstain during freeze.
            coverage_ratio=_shadow_coverage(record),
            event_coverage_status=EventCoverageStatus(record["event_coverage_status"]),
            provider_chain=list(record.get("provider_chain", [])),
            evidence_coverage=float(record.get("evidence_coverage", 0.0)),
            model_disagreement=record.get("model_disagreement"),
            influence_facts=list(record.get("influence_facts", [])),
            cache_state=record.get("cache_state", "fresh"),
            provider_conflict=bool(record.get("provider_conflict", False)),
            roster_hash=record.get("roster_hash"),
            model_candidate=record.get("model_candidate"),
            market_regime=record.get("market_regime", "unknown"),
            candidate_predictions=dict(record.get("candidate_predictions", {})),
            ensemble_weights={str(key): float(value) for key, value in record.get("ensemble_weights", {}).items()},
            data_quality_mask={str(key): float(value) for key, value in record.get("data_quality_mask", {}).items()},
            event_missing_mask={str(key): float(value) for key, value in record.get("event_missing_mask", {}).items()},
            provider_id=record.get("provider_id"), revision_id=record.get("revision_id"),
            source_delay_seconds=record.get("source_delay_seconds"),
        )
        output.append({"market": "cn", "session_id": str(session.id), "status": "abstain" if session.abstained else "frozen"})
    return output


def _shadow_coverage(record: dict) -> float:
    """Resolve the price/market coverage used by the research Shadow gate.

    Older prediction files did not separate core and optional evidence, so the
    aggregate value remains a compatibility fallback.  New files always
    provide ``core_feature_coverage`` and keep unsupported event evidence in a
    separate degraded status and missing mask.
    """
    return float(record.get("core_feature_coverage", record["coverage_ratio"]))


if __name__ == "__main__":
    raise SystemExit(main())
