from __future__ import annotations

from investment_research.domain.forecasts import (
    DataStatus,
    DrawdownDistribution,
    ModelTaskStatus,
    ResearchForecastBundle,
)
from investment_research.pipeline.models import AnalysisBundle
from investment_research.repository.sqlite import SQLiteUnitOfWork


class ResearchForecastService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def freeze_from_analysis(self, bundle: AnalysisBundle, *, refresh=None) -> ResearchForecastBundle:
        existing = self.uow.research_forecasts.for_run(str(bundle.run.id))
        if existing is not None:
            return existing
        prediction = bundle.predictions[0] if bundle.predictions else None
        as_of = bundle.snapshot.as_of or bundle.snapshot.captured_at
        synthetic = bundle.snapshot.synthetic_share > 0 or "synthetic" in bundle.snapshot.source_types
        feature_coverage = 0.0 if prediction is None else prediction.feature_coverage
        stale = bool(bundle.snapshot.stale_reasons) or bundle.snapshot.price_freshness_status in {"stale", "expired", "unavailable"}
        quality = "failed" if synthetic else "degraded" if stale or (refresh is not None and refresh.state == "degraded") else "passed"
        cache_state = "stale_usable" if refresh is not None and refresh.cache_hit and quality != "failed" else "fresh" if quality != "failed" else "unavailable"
        reasons = list(dict.fromkeys([
            *bundle.snapshot.fallback_reasons,
            *bundle.snapshot.stale_reasons,
            *([] if not synthetic else ["synthetic_data_forbidden_in_formal_forecast"]),
        ]))
        drift_verdict = None if prediction is None else self.uow.agent_runtime.latest_drift_verdict(prediction.model_name)
        if drift_verdict == "hold":
            reasons.append("runtime_drift_gate_requested_abstention")
        risk_approved = bool(prediction and prediction.deployment_approved and not synthetic and feature_coverage >= 0.75 and drift_verdict != "hold")
        risk_status = "approved" if risk_approved else "abstain"
        tasks = [
            ModelTaskStatus(task="direction_1d", status="unavailable", gating_reasons=["No independently approved 1-day direction model is frozen for this run"]),
            ModelTaskStatus(task="direction_5d", status="unavailable", gating_reasons=["No independently approved 5-day direction model is frozen for this run"]),
            ModelTaskStatus(task="return_20d", status="unavailable", gating_reasons=["No independently approved 20-day return distribution model is frozen for this run"]),
            ModelTaskStatus(
                task="drawdown_20d",
                status=risk_status,
                model_name=None if prediction is None else prediction.model_name,
                model_version=None if prediction is None else prediction.model_version,
                manifest_version=None if prediction is None else prediction.manifest_version,
                gating_reasons=[] if risk_approved else ["Approved drawdown model unavailable or runtime gate failed"],
            ),
        ]
        frozen = ResearchForecastBundle(
            analysis_run_id=bundle.run.id,
            asset_id=bundle.asset.id,
            market_snapshot_id=bundle.snapshot.market_snapshot_id,
            market_snapshot_hash=bundle.snapshot.market_snapshot_hash,
            decision_context=bundle.snapshot.decision_context,
            decision_time=bundle.snapshot.decision_time,
            feature_built_at=bundle.snapshot.feature_built_at,
            as_of=as_of,
            drawdown_20d=None if not risk_approved or prediction is None or prediction.risk_probability is None else DrawdownDistribution(threshold_probability=prediction.risk_probability),
            evidence_coverage=bundle.snapshot.real_share,
            feature_coverage=feature_coverage,
            data_status=DataStatus(
                as_of=as_of,
                latest_source_time=bundle.snapshot.latest_price_timestamp,
                fetched_at=bundle.snapshot.captured_at,
                received_at=bundle.snapshot.captured_at,
                latency_seconds=(
                    None
                    if bundle.snapshot.latest_price_timestamp is None
                    else max(
                        0.0,
                        (
                            bundle.snapshot.captured_at
                            - bundle.snapshot.latest_price_timestamp
                        ).total_seconds(),
                    )
                ),
                coverage_ratio=bundle.snapshot.real_share,
                quality_status=quality,
                cache_state=cache_state,
                degraded_symbols=[bundle.asset.ticker] if quality != "passed" else [],
                provider_chain=[name for name in [bundle.snapshot.price_provider_name, bundle.snapshot.evidence_provider_name] if name != "unknown"],
                reasons=reasons,
            ),
            tasks=tasks,
            gating_reasons=[*reasons, *[reason for task in tasks for reason in task.gating_reasons]],
            abstained=not risk_approved,
        )
        return self.uow.research_forecasts.add(frozen)

    def for_run(self, run_id: str) -> ResearchForecastBundle:
        item = self.uow.research_forecasts.for_run(run_id)
        if item is None:
            raise ValueError("Research forecast bundle not found")
        return item
