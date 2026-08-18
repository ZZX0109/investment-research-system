"""Bounded automation for the zero-budget A-share research lifecycle.

The service is intentionally policy-heavy and model-agnostic.  It decides
*when* a research job is due and whether a candidate has enough evidence for a
research-only promotion.  It never changes labels, thresholds, data tier, or
formal deployment state.  Training and inference remain the existing
deterministic pipeline; this module only supplies the durable lifecycle
contract around them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Literal
from zoneinfo import ZoneInfo

from investment_research.domain.data_tier import DataTier
from investment_research.domain.trusted_market import IngestionJob, JobType
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.ingestion_jobs import IngestionJobService


ResearchJobKind = Literal[
    "research_daily_close",
    "research_weekly_monitor",
    "research_monthly_training",
    "research_quarterly_challenger",
    "research_label_backfill",
    "research_model_promotion",
    "research_model_rollback",
    "knowledge_daily_incremental",
    "knowledge_weekly_audit",
    "knowledge_monthly_reindex",
    "knowledge_historical_backfill",
]


@dataclass(frozen=True)
class ResearchCadence:
    """Default cadence for the CN close-confirmed research path."""

    timezone_name: str = "Asia/Shanghai"
    daily_close_hour: int = 15
    daily_close_minute: int = 10
    max_label_horizon_sessions: int = 20
    weekly_weekday: int = 4  # Friday when using a complete exchange calendar.


@dataclass(frozen=True)
class LifecyclePlan:
    latest_trade_date: date | None
    mature_training_cutoff: date | None
    jobs: tuple[ResearchJobKind, ...]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MonitorThresholds:
    minimum_coverage_ratio: float = 0.98
    maximum_psi: float = 0.20
    maximum_brier_delta: float = 0.01
    maximum_ece_delta: float = 0.03
    maximum_abstain_rate: float = 0.75
    maximum_provider_failure_rate: float = 0.20
    maximum_leakage_errors: int = 0


@dataclass(frozen=True)
class MonitorDecision:
    status: Literal["healthy", "retrain_recommended", "blocked"]
    trigger_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromotionDecision:
    eligible: bool
    reasons: tuple[str, ...] = ()
    status: Literal["candidate", "approved_research_candidate", "blocked"] = "blocked"


def latest_completed_trade_date(
    candidate: date,
    trading_dates: Iterable[date] | None = None,
) -> date | None:
    """Return the latest exchange date not later than ``candidate``.

    A supplied exchange calendar is authoritative.  Without one, weekends are
    excluded as a safe local fallback; holidays remain unresolved and are
    therefore represented by ``None``/a caller-provided calendar rather than
    being silently treated as trading days.
    """
    if trading_dates is not None:
        dates = sorted({item for item in trading_dates if item <= candidate})
        return dates[-1] if dates else None
    if candidate.weekday() >= 5:
        candidate -= timedelta(days=candidate.weekday() - 4)
    return candidate


def matured_training_cutoff(
    latest_trade_date: date,
    trading_dates: Iterable[date] | None,
    *,
    horizon_sessions: int = 20,
) -> date | None:
    """Find the last date whose forward label window is fully observable."""
    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be positive")
    if trading_dates is None:
        # Do not pretend calendar days equal trading sessions.  The fallback
        # is only useful for local fixtures and remains explicitly labelled.
        return latest_trade_date - timedelta(days=horizon_sessions)
    dates = sorted(set(trading_dates))
    if not dates:
        return None
    eligible = [item for item in dates if item <= latest_trade_date]
    if len(eligible) <= horizon_sessions:
        return None
    return eligible[-horizon_sessions - 1]


class ResearchLifecycleService:
    """Plan and enqueue idempotent research lifecycle jobs."""

    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        clock=None,
        cadence: ResearchCadence | None = None,
    ) -> None:
        self.uow = uow
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cadence = cadence or ResearchCadence()

    def plan(
        self,
        *,
        now: datetime | None = None,
        trading_dates: Iterable[date] | None = None,
        market: str = "cn",
        decision_context: str = "close_confirmed",
        enqueue: bool = True,
    ) -> LifecyclePlan:
        current = now or self.clock()
        calendar = None if trading_dates is None else sorted(set(trading_dates))
        local_now = current
        if current.tzinfo is not None:
            local_now = current.astimezone(ZoneInfo(self.cadence.timezone_name))
        candidate_date = local_now.date()
        close_at = local_now.replace(
            hour=self.cadence.daily_close_hour,
            minute=self.cadence.daily_close_minute,
            second=0,
            microsecond=0,
        )
        # Before the configured close-confirmation time, today's daily bar is
        # not an available research snapshot.  Plan against the previous
        # calendar session instead; an explicit exchange calendar resolves
        # holidays while the weekend fallback remains safe for fixtures.
        if local_now < close_at:
            candidate_date -= timedelta(days=1)
        latest = latest_completed_trade_date(candidate_date, calendar)
        if latest is None:
            return LifecyclePlan(None, None, (), ("exchange_calendar_has_no_completed_trade_date",))
        cutoff = matured_training_cutoff(
            latest,
            calendar,
            horizon_sessions=self.cadence.max_label_horizon_sessions,
        )
        jobs: list[ResearchJobKind] = ["research_daily_close"]
        jobs.append("knowledge_daily_incremental")
        if self._is_week_boundary(latest, calendar):
            jobs.append("research_weekly_monitor")
            jobs.append("knowledge_weekly_audit")
        if self._is_month_boundary(latest, calendar) and cutoff is not None:
            jobs.append("research_monthly_training")
            jobs.append("knowledge_monthly_reindex")
        if self._is_quarter_boundary(latest, calendar) and cutoff is not None:
            jobs.append("research_quarterly_challenger")
        jobs.append("research_label_backfill")
        reasons: list[str] = []
        if cutoff is None:
            reasons.append("insufficient_mature_sessions_for_training")
        if enqueue:
            for kind in jobs:
                self.enqueue(
                    kind,
                    market=market,
                    decision_context=decision_context,
                    trade_date=latest,
                    cutoff_time=current,
                    dataset_hash=None,
                )
        return LifecyclePlan(latest, cutoff, tuple(jobs), tuple(reasons))

    def enqueue(
        self,
        job_type: ResearchJobKind,
        *,
        market: str = "cn",
        decision_context: str = "close_confirmed",
        trade_date: date,
        cutoff_time: datetime,
        dataset_hash: str | None = None,
        training_run_id: str | None = None,
        candidate_version: str | None = None,
        report_hash: str | None = None,
        scheduled_for: datetime | None = None,
    ) -> IngestionJob:
        if job_type not in {
            "research_daily_close", "research_weekly_monitor",
            "research_monthly_training", "research_quarterly_challenger",
            "research_label_backfill", "research_model_promotion",
            "research_model_rollback",
            "knowledge_daily_incremental", "knowledge_weekly_audit",
            "knowledge_monthly_reindex", "knowledge_historical_backfill",
        }:
            raise ValueError(f"unsupported research lifecycle job: {job_type}")
        service = IngestionJobService(self.uow, clock=self.clock)
        key = f"{job_type}:{market}:{decision_context}:{trade_date.isoformat()}"
        return service.enqueue(
            job_type=job_type,
            symbols=[],
            requested_by="research-lifecycle",
            idempotency_key=key,
            priority=20 if job_type in {"research_daily_close", "knowledge_daily_incremental"} else 60,
            scheduled_for=scheduled_for,
            market=market,
            decision_context=decision_context,
            trade_date=trade_date,
            cutoff_time=cutoff_time,
            dataset_hash=dataset_hash,
            training_run_id=training_run_id,
            candidate_version=candidate_version,
            report_hash=report_hash,
            data_tier=DataTier.RESEARCH_PIT.value,
        )

    def monitor(
        self,
        metrics: Mapping[str, Any],
        *,
        thresholds: MonitorThresholds | None = None,
    ) -> MonitorDecision:
        policy = thresholds or MonitorThresholds()
        reasons: list[str] = []
        if _number(metrics, "coverage_ratio") < policy.minimum_coverage_ratio:
            reasons.append("coverage_below_98pct")
        if _number(metrics, "psi") > policy.maximum_psi:
            reasons.append("input_psi_above_threshold")
        if _number(metrics, "brier_delta") > policy.maximum_brier_delta:
            reasons.append("brier_degradation")
        if _number(metrics, "ece_delta") > policy.maximum_ece_delta:
            reasons.append("ece_degradation")
        if _number(metrics, "abstain_rate") > policy.maximum_abstain_rate:
            reasons.append("abstain_rate_above_threshold")
        if _number(metrics, "provider_failure_rate") > policy.maximum_provider_failure_rate:
            reasons.append("provider_failure_rate_above_threshold")
        if int(_number(metrics, "leakage_errors")) > policy.maximum_leakage_errors:
            reasons.append("leakage_audit_error")
        if reasons:
            return MonitorDecision("blocked" if "leakage_audit_error" in reasons else "retrain_recommended", tuple(reasons))
        return MonitorDecision("healthy")

    @staticmethod
    def evaluate_candidate(evidence: Mapping[str, Any]) -> PromotionDecision:
        """Evaluate a research-only candidate without changing any roster."""
        reasons: list[str] = []
        if evidence.get("data_tier") != DataTier.RESEARCH_PIT.value:
            reasons.append("candidate_data_tier_not_research_pit")
        if evidence.get("status") not in {None, "candidate", "exploratory", "research_only", "approved_research_candidate"}:
            reasons.append("candidate_status_not_research_only")
        if evidence.get("deployment_ready") is not False:
            reasons.append("candidate_deployment_boundary_invalid")
        if int(evidence.get("leakage_errors", 0) or 0) != 0:
            reasons.append("leakage_audit_error")
        if int(evidence.get("synthetic_count", 0) or 0) != 0:
            reasons.append("synthetic_data_present")
        if not bool(evidence.get("artifact_hashes_valid", False)):
            reasons.append("artifact_hash_validation_failed")
        if not bool(evidence.get("holdout_passed", False)):
            reasons.append("final_holdout_failed")
        if not bool(evidence.get("stress_passed", False)):
            reasons.append("stress_window_failed")
        if not bool(evidence.get("baseline_not_regressed", False)):
            reasons.append("baseline_regression")
        if not bool(evidence.get("regime_stable", False)):
            reasons.append("regime_instability")
        if not bool(evidence.get("seed_stable", False)):
            reasons.append("random_seed_instability")
        if int(evidence.get("valid_shadow_sessions", 0) or 0) < 20:
            reasons.append("shadow_below_20_valid_sessions")
        if not bool(evidence.get("shadow_better_than_primary", False)):
            reasons.append("shadow_not_better_than_primary")
        if reasons:
            return PromotionDecision(False, tuple(reasons), "blocked")
        return PromotionDecision(True, (), "approved_research_candidate")

    @classmethod
    def promote_candidate(
        cls,
        *,
        scope: str,
        candidate: Mapping[str, Any],
        promotion_root: Path,
        previous: Mapping[str, Any] | None = None,
        promoted_at: datetime | None = None,
    ) -> tuple[PromotionDecision, Path | None]:
        """Atomically promote an eligible research candidate.

        This is the only supported replacement entrypoint.  It returns a
        blocked decision without touching the roster when any gate fails;
        callers can persist that decision as a lifecycle job/report and retry
        after new mature Shadow evidence arrives.
        """
        decision = cls.evaluate_candidate(candidate)
        if not decision.eligible:
            return decision, None
        path = ResearchPromotionStore(promotion_root).promote(
            scope=scope,
            candidate=candidate,
            previous=previous,
            promoted_at=promoted_at,
        )
        return decision, path

    @staticmethod
    def _is_week_boundary(latest: date, calendar: list[date] | None) -> bool:
        if calendar:
            same_week = [item for item in calendar if item.isocalendar()[:2] == latest.isocalendar()[:2]]
            return bool(same_week) and latest == max(same_week)
        return latest.weekday() == 4

    @staticmethod
    def _is_month_boundary(latest: date, calendar: list[date] | None) -> bool:
        if calendar:
            future = [item for item in calendar if item > latest]
            return not future or future[0].month != latest.month
        return latest.day >= 28

    @classmethod
    def _is_quarter_boundary(cls, latest: date, calendar: list[date] | None) -> bool:
        return latest.month in {3, 6, 9, 12} and cls._is_month_boundary(latest, calendar)


def _number(metrics: Mapping[str, Any], key: str) -> float:
    try:
        return float(metrics.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


class ResearchPromotionStore:
    """Atomic research roster pointer with immutable promotion history."""

    _safe_scope = re.compile(r"^[a-zA-Z0-9_.-]+$")

    def __init__(self, root: Path) -> None:
        self.root = root

    def promote(self, *, scope: str, candidate: Mapping[str, Any], previous: Mapping[str, Any] | None = None, promoted_at: datetime | None = None) -> Path:
        self._validate_scope(scope)
        decision = ResearchLifecycleService.evaluate_candidate(candidate)
        if not decision.eligible:
            raise ValueError("candidate is not eligible: " + ",".join(decision.reasons))
        now = promoted_at or datetime.now(timezone.utc)
        payload = {
            "schema_version": "research-promotion-v1",
            "scope": scope,
            "promoted_at": now.isoformat(),
            "data_tier": DataTier.RESEARCH_PIT.value,
            "status": "research_only",
            "deployment_ready": False,
            "candidate": dict(candidate),
            "previous": None if previous is None else dict(previous),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        scope_root = self.root / scope
        history = scope_root / "promotions"
        history.mkdir(parents=True, exist_ok=True)
        digest = _sha256_text(encoded)
        history_path = history / f"{now:%Y%m%dT%H%M%SZ}-{digest[:12]}.json"
        if history_path.exists() and history_path.read_text(encoding="utf-8") != encoded:
            raise ValueError("promotion history collision")
        history_path.write_text(encoded, encoding="utf-8")
        current = scope_root / "current.json"
        temporary = current.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(current)
        return history_path

    def rollback(self, *, scope: str, version: Mapping[str, Any]) -> Path:
        self._validate_scope(scope)
        if (
            version.get("data_tier") != DataTier.RESEARCH_PIT.value
            or version.get("status") != "research_only"
            or version.get("deployment_ready") is not False
        ):
            raise ValueError("rollback version violates research deployment boundary")
        scope_root = self.root / scope
        scope_root.mkdir(parents=True, exist_ok=True)
        current = scope_root / "current.json"
        encoded = json.dumps(dict(version), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        temporary = current.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(current)
        return current

    def read_current(self, *, scope: str) -> dict[str, Any] | None:
        """Read the current research-only pointer without scanning model files."""
        self._validate_scope(scope)
        current = self.root / scope / "current.json"
        if not current.is_file():
            return None
        try:
            payload = json.loads(current.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid research promotion pointer: {current}") from exc
        if not isinstance(payload, dict):
            raise ValueError("research promotion pointer must be an object")
        if payload.get("data_tier") != DataTier.RESEARCH_PIT.value or payload.get("status") != "research_only" or payload.get("deployment_ready") is not False:
            raise ValueError("research promotion pointer violates deployment boundary")
        return payload

    @classmethod
    def _validate_scope(cls, scope: str) -> None:
        if not scope or not cls._safe_scope.fullmatch(scope):
            raise ValueError("invalid research promotion scope")


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
