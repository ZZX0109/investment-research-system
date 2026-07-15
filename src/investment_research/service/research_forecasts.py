from __future__ import annotations

from investment_research.domain.forecasts import (
    DataStatus,
    DirectionDistribution,
    DrawdownDistribution,
    ModelTaskStatus,
    ResearchForecastBundle,
    ReturnDistribution,
)
from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.domain.pit import EventCoverageStatus
from investment_research.pipeline.models import AnalysisBundle
from investment_research.repository.sqlite import SQLiteUnitOfWork


class ResearchForecastService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def freeze_from_analysis(self, bundle: AnalysisBundle, *, refresh=None) -> ResearchForecastBundle:
        existing = self.uow.research_forecasts.for_run(str(bundle.run.id))
        if existing is not None:
            return existing
        # Compatibility analysis runs may contain a legacy risk prediction, but
        # that artifact has old cutoff semantics. Research mode must never
        # promote it into the new four-task contract; only a verified
        # scope-specific ResearchModelRoster may provide task outputs.
        prediction = None
        as_of = bundle.snapshot.as_of or bundle.snapshot.captured_at
        synthetic = bundle.snapshot.synthetic_share > 0 or "synthetic" in bundle.snapshot.source_types
        feature_coverage = 0.0
        stale = bool(bundle.snapshot.stale_reasons) or bundle.snapshot.price_freshness_status in {"stale", "expired", "unavailable"}
        quality = "failed" if synthetic else "degraded" if stale or (refresh is not None and refresh.state == "degraded") else "passed"
        cache_state = "stale_usable" if refresh is not None and refresh.cache_hit and quality != "failed" else "fresh" if quality != "failed" else "unavailable"
        reasons = list(dict.fromkeys([
            *bundle.snapshot.fallback_reasons,
            *bundle.snapshot.stale_reasons,
            *([] if not synthetic else ["synthetic_data_forbidden_in_research_output"]),
            "research_roster_required_legacy_model_disabled",
        ]))
        # The legacy analysis path has no qualified formal-PIT catalog proof.
        # It can remain useful for research comparison, but must never surface
        # as an approved forecast simply because an old prediction carried an
        # approval bit.
        risk_available_for_research = False
        risk_status = "unavailable"
        tasks = [
            ModelTaskStatus(task="direction_1d", status="unavailable", gating_reasons=["research_roster_missing"]),
            ModelTaskStatus(task="direction_5d", status="unavailable", gating_reasons=["research_roster_missing"]),
            ModelTaskStatus(task="return_20d", status="unavailable", gating_reasons=["research_roster_missing"]),
            ModelTaskStatus(
                task="drawdown_20d",
                status=risk_status,
                model_name=None if prediction is None else prediction.model_name,
                model_version=None if prediction is None else prediction.model_version,
                manifest_version=None if prediction is None else prediction.manifest_version,
                gating_reasons=["research_roster_required_legacy_model_disabled"],
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
            drawdown_20d=None if not risk_available_for_research or prediction is None or prediction.risk_probability is None else DrawdownDistribution(threshold_probability=prediction.risk_probability),
            evidence_coverage=bundle.snapshot.real_share,
            feature_coverage=feature_coverage,
            data_status=DataStatus(
                data_tier=DataTier.RESEARCH_PIT,
                research_only=True,
                historical_visibility_assumption=RESEARCH_VISIBILITY_ASSUMPTION,
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
                event_coverage_status=_event_coverage(bundle.snapshot.event_coverage_status),
                degraded_symbols=[bundle.asset.ticker] if quality != "passed" else [],
                provider_chain=[name for name in [bundle.snapshot.price_provider_name, bundle.snapshot.evidence_provider_name] if name != "unknown"],
                reasons=reasons,
            ),
            tasks=tasks,
            gating_reasons=[*reasons, *[reason for task in tasks for reason in task.gating_reasons]],
            influence_facts=[],
            risk_level=(
                "unavailable" if prediction is None or prediction.risk_probability is None
                else "high" if prediction.risk_probability >= 0.65
                else "medium" if prediction.risk_probability >= 0.45
                else "low"
            ),
            abstained=not risk_available_for_research,
        )
        return self.uow.research_forecasts.add(frozen)

    def for_run(self, run_id: str) -> ResearchForecastBundle:
        item = self.uow.research_forecasts.for_run(run_id)
        if item is None:
            raise ValueError("Research forecast bundle not found")
        return item

    def freeze_formal_from_analysis(self, bundle: AnalysisBundle, *, market: str, inference) -> ResearchForecastBundle:
        """Freeze four independently routed formal task results for one run.

        This is separate from the legacy compatibility path above. Callers that
        select formal research must provide the formal inference boundary; no
        root-model or synthetic fallback is consulted here.
        """
        existing = self.uow.research_forecasts.for_run(str(bundle.run.id))
        if existing is not None:
            return existing
        snapshot = bundle.snapshot
        as_of = snapshot.as_of or snapshot.captured_at
        synthetic = snapshot.synthetic_share > 0 or "synthetic" in snapshot.source_types
        tasks: list[ModelTaskStatus] = []
        values = {}
        reasons: list[str] = []
        for task in ("drawdown_20d", "direction_1d", "direction_5d", "return_20d"):
            if synthetic:
                tasks.append(ModelTaskStatus(task=task, status="abstain", gating_reasons=["synthetic_data_forbidden_in_formal_forecast"]))
                continue
            try:
                prediction = inference.predict(
                    snapshot=snapshot, market=market,
                    decision_context=snapshot.decision_context, task=task,
                )
                values[task] = prediction
                tasks.append(ModelTaskStatus(
                    task=task, status=prediction.model_status,
                    model_name=prediction.model_name, model_version=prediction.model_version,
                    fallback_from=prediction.fallback_from,
                ))
            except Exception as exc:
                reason = f"formal_{task}_unavailable:{type(exc).__name__}"
                reasons.append(reason)
                tasks.append(ModelTaskStatus(task=task, status="abstain", gating_reasons=[reason]))
        risk = values.get("drawdown_20d")
        direction_1d = values.get("direction_1d")
        direction_5d = values.get("direction_5d")
        returns = values.get("return_20d")
        coverage = min((item.feature_coverage for item in values.values()), default=0.0)
        abstained = any(item.status == "abstain" for item in tasks)
        quality = "failed" if synthetic else "degraded" if abstained else "passed"
        return self.uow.research_forecasts.add(ResearchForecastBundle(
            analysis_run_id=bundle.run.id, asset_id=bundle.asset.id, market=market,
            data_tier=DataTier.FORMAL_PIT,
            market_snapshot_id=snapshot.market_snapshot_id, market_snapshot_hash=snapshot.market_snapshot_hash,
            decision_context=snapshot.decision_context, decision_time=snapshot.decision_time,
            feature_built_at=snapshot.feature_built_at, as_of=as_of,
            direction_1d=None if direction_1d is None else DirectionDistribution(
                horizon_days=1, **{key: direction_1d.values[key] for key in ("up", "down", "flat")}),
            direction_5d=None if direction_5d is None else DirectionDistribution(
                horizon_days=5, **{key: direction_5d.values[key] for key in ("up", "down", "flat")}),
            return_20d=None if returns is None else ReturnDistribution(
                p10=returns.values["p10"], p50=returns.values["p50"], p90=returns.values["p90"]),
            drawdown_20d=None if risk is None else DrawdownDistribution(
                threshold_probability=risk.values["threshold_probability"]),
            evidence_coverage=snapshot.real_share, feature_coverage=coverage,
            data_status=DataStatus(
                data_tier=DataTier.FORMAL_PIT,
                research_only=False,
                historical_visibility_assumption=None,
                as_of=as_of, latest_source_time=snapshot.latest_price_timestamp,
                fetched_at=snapshot.captured_at, received_at=snapshot.captured_at,
                coverage_ratio=snapshot.real_share, quality_status=quality,
                cache_state="unavailable" if abstained else "fresh",
                event_coverage_status=_event_coverage(snapshot.event_coverage_status),
                degraded_symbols=[bundle.asset.ticker] if quality != "passed" else [],
                provider_chain=[name for name in [snapshot.price_provider_name, snapshot.evidence_provider_name] if name != "unknown"],
                reasons=reasons,
            ),
            tasks=tasks, gating_reasons=reasons, abstained=abstained,
        ))


def _event_coverage(value: str) -> EventCoverageStatus:
    aliases = {"complete": "events_present", "none": "confirmed_none", "unknown": "unsupported"}
    try:
        return EventCoverageStatus(aliases.get(value, value))
    except ValueError:
        return EventCoverageStatus.UNSUPPORTED
