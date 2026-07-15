from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from investment_research.domain.pit import ShadowRunOutcome, ShadowRunSession
from investment_research.domain.forecasts import TaskApprovalManifest


class ShadowRunController:
    """Freeze daily shadow evidence and derive release eligibility from it."""

    def __init__(self, repository, *, outcomes_repository=None, required_sessions: int = 20) -> None:
        self.repository = repository
        self.outcomes_repository = outcomes_repository
        self.required_sessions = required_sessions

    def freeze(
        self,
        *,
        training_run_id: str,
        market: str,
        decision_context: str,
        task: str,
        trade_date: date,
        frozen_at: datetime,
        market_snapshot_id: UUID,
        market_snapshot_hash: str,
        artifact_hashes: dict[str, str],
        expected_artifact_hashes: dict[str, str] | None,
        coverage_ratio: float,
        formal_synthetic_output_count: int,
        provider_switch_count: int = 0,
        abstained: bool = False,
    ) -> ShadowRunSession:
        reasons: list[str] = []
        if coverage_ratio < 0.98:
            reasons.append("critical_data_coverage_below_98pct")
        if formal_synthetic_output_count:
            reasons.append("formal_synthetic_output_nonzero")
        if not artifact_hashes or any(not value for value in artifact_hashes.values()):
            reasons.append("artifact_hash_incomplete")
        # The worker supplies hashes recomputed from the files it executed;
        # the expected map comes from the approved exact-scope manifest. A
        # session without that comparison is not formal shadow evidence.
        if expected_artifact_hashes is None:
            reasons.append("approved_artifact_hashes_missing")
        elif artifact_hashes != expected_artifact_hashes:
            reasons.append("artifact_hash_mismatch")
        session = ShadowRunSession(
            training_run_id=training_run_id,
            market=market,
            decision_context=decision_context,
            task=task,
            trade_date=trade_date,
            frozen_at=frozen_at,
            market_snapshot_id=market_snapshot_id,
            market_snapshot_hash=market_snapshot_hash,
            artifact_hashes=artifact_hashes,
            coverage_ratio=coverage_ratio,
            formal_synthetic_output_count=formal_synthetic_output_count,
            provider_switch_count=provider_switch_count,
            abstained=abstained,
            valid=not reasons,
            invalid_reasons=reasons,
        )
        return self.repository.add(session)

    def freeze_for_manifest(
        self,
        *,
        manifest: TaskApprovalManifest,
        trade_date: date,
        frozen_at: datetime,
        market_snapshot_id: UUID,
        market_snapshot_hash: str,
        actual_artifact_hashes: dict[str, str],
        coverage_ratio: float,
        formal_synthetic_output_count: int,
        provider_switch_count: int = 0,
        abstained: bool = False,
    ) -> ShadowRunSession:
        """Freeze a session bound directly to one approved manifest.

        This is the production entrypoint: scope and expected artifact hashes
        are read from the manifest rather than supplied as unrelated worker
        parameters, preventing an accidental cross-scope comparison.
        """
        return self.freeze(
            training_run_id=manifest.training_run_id,
            market=manifest.market,
            decision_context=manifest.decision_context,
            task=manifest.task,
            trade_date=trade_date,
            frozen_at=frozen_at,
            market_snapshot_id=market_snapshot_id,
            market_snapshot_hash=market_snapshot_hash,
            artifact_hashes=actual_artifact_hashes,
            expected_artifact_hashes=manifest.artifact_hashes,
            coverage_ratio=coverage_ratio,
            formal_synthetic_output_count=formal_synthetic_output_count,
            provider_switch_count=provider_switch_count,
            abstained=abstained,
        )

    def valid_session_count(self, *, training_run_id: str, market: str, decision_context: str, task: str) -> int:
        return sum(
            item.valid
            for item in self.repository.list_scope(
                training_run_id=training_run_id,
                market=market,
                decision_context=decision_context,
                task=task,
            )
        )

    def release_ready(self, **scope: str) -> bool:
        return self.valid_session_count(**scope) >= self.required_sessions

    def backfill_outcome(
        self, *, shadow_session_id: UUID, horizon_sessions: int, filled_at: datetime,
        realized_return: float | None, realized_max_drawdown: float | None,
        mae: float | None, mfe: float | None, direction: str = "unavailable",
        data_complete: bool = False, suspended_during_window: bool = False,
        limit_event_during_window: bool = False, error_category: str | None = None,
    ) -> ShadowRunOutcome:
        if self.outcomes_repository is None:
            raise RuntimeError("shadow outcome repository is not configured")
        return self.outcomes_repository.add(ShadowRunOutcome(
            shadow_session_id=shadow_session_id, horizon_sessions=horizon_sessions,
            filled_at=filled_at, realized_return=realized_return,
            realized_max_drawdown=realized_max_drawdown, mae=mae, mfe=mfe,
            direction=direction, data_complete=data_complete,
            suspended_during_window=suspended_during_window,
            limit_event_during_window=limit_event_during_window, error_category=error_category,
        ))
