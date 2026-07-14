from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import pstdev
from uuid import UUID

from pydantic import BaseModel, Field

from investment_research.domain.base import Provenance, utc_now
from investment_research.domain.enums import DataMode, DataSourceType, JudgeVerdict
from investment_research.domain.models import (
    HistoricalScenario,
    PaperObservation,
    PortfolioRiskSnapshot,
    RefreshRun,
    ResearchAudit,
    User,
)
from investment_research.feature_contract import FEATURE_CONTRACT_VERSION
from investment_research.pipeline.model_inference import SnapshotFeatureBuilder
from investment_research.pipeline.models import AnalysisBundle
from investment_research.pipeline.service import AnalysisPipelineService
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import (
    AnalysisProviderRegistry,
    PersistedFallbackEvidenceProvider,
    PersistedFallbackMarketDataProvider,
)
from investment_research.service.training_bundle_data import (
    LivePublicPriceDataStore,
    TrainingBundleDataError,
    TrainingBundleDataStore,
)
from investment_research.service.audit_retrieval import BoundedAuthorityRetriever
from investment_research.training.catalog import UNIVERSE_PRESETS


MODEL_DIR = Path(__file__).resolve().parents[3] / "output" / "models"


class RefreshAnalysisResult(BaseModel):
    job_id: str | None = None
    refresh_run: RefreshRun
    analysis_bundle: AnalysisBundle | None = None


class ResearchCard(BaseModel):
    bundle: AnalysisBundle
    historical_analogies: list[HistoricalScenario] = Field(default_factory=list)
    portfolio_risk: PortfolioRiskSnapshot | None = None
    audit: ResearchAudit | None = None
    observation_conditions: list[str] = Field(default_factory=list)
    contrary_view: str


def _real_provenance(
    source_name: str, observed_at: datetime | None = None, confidence: float = 0.9
) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name=source_name,
        observed_at=observed_at or utc_now(),
        confidence=confidence,
    )


class AssetRefreshService:
    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        bundle_store: TrainingBundleDataStore | None = None,
        live_store: LivePublicPriceDataStore | None = None,
    ) -> None:
        self.uow = uow
        self.bundle_store = bundle_store or TrainingBundleDataStore()
        self.live_store = live_store or LivePublicPriceDataStore()

    def refresh_and_analyze(
        self, asset_id: str, *, user: User, refresh_mode: str = "auto"
    ) -> RefreshAnalysisResult:
        asset = self.uow.assets.get(asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        started = utc_now()
        from investment_research.service.ingestion_jobs import IngestionJobService
        jobs = IngestionJobService(self.uow, clock=lambda: started)
        job = jobs.enqueue(
            job_type="daily_close_confirmation",
            symbols=[asset.ticker],
            requested_by=user.auth_subject,
            idempotency_key=f"manual-refresh:{asset_id}:{started.isoformat()}",
            priority=10,
        )
        job = jobs.mark_running(job)
        refresh = RefreshRun(
            asset_id=asset.id,
            triggered_by=user.auth_subject,
            refresh_mode=refresh_mode,
            started_at=started,
            provenance=_real_provenance("asset-refresh", started),
        )
        self.uow.refresh_runs.add(refresh)
        attempts: list[dict[str, object]] = []
        failures: list[str] = []
        try:
            series = None
            if refresh_mode in {"online", "auto"}:
                try:
                    series = self.live_store.price_series_for_asset(asset)
                    attempts.append(
                        {
                            "provider": "live_public_price_registry",
                            "status": "succeeded",
                            "at": utc_now().isoformat(),
                        }
                    )
                except Exception as exc:
                    failures.append(str(exc))
                    attempts.append(
                        {
                            "provider": "live_public_price_registry",
                            "status": "failed",
                            "reason": str(exc),
                            "at": utc_now().isoformat(),
                        }
                    )
            cache_hit = series is None
            if series is None:
                series = self.bundle_store.price_series_for_asset(asset)
            try:
                evidence = self.bundle_store.evidence_for_asset(asset)
                cache_hit = True
            except TrainingBundleDataError as exc:
                evidence = []
                failures.append(str(exc))
            for item in series:
                self.uow.price_series.add(item)
            for item in evidence:
                self.uow.evidence.add(item)
            attempts.append(
                {
                    "provider": "authoritative_real_bundle",
                    "status": "succeeded",
                    "cache": True,
                    "at": utc_now().isoformat(),
                }
            )
            completed = utc_now()
            state = (
                "degraded"
                if failures or (refresh_mode in {"online", "auto"} and cache_hit)
                else "succeeded"
            )
            refresh = refresh.model_copy(
                update={
                    "state": state,
                    "completed_at": completed,
                    "provider_attempts": attempts,
                    "cache_hit": cache_hit,
                    "price_count": sum(len(item.points) for item in series),
                    "evidence_count": len(evidence),
                    "failure_reasons": failures,
                    "data_version": max(
                        (item.data_version or "unknown" for item in evidence),
                        default="live-public",
                    ),
                }
            )
            self.uow.refresh_runs.add(refresh)
            registry = AnalysisProviderRegistry(
                PersistedFallbackMarketDataProvider(),
                PersistedFallbackEvidenceProvider(),
            )
            bundle = AnalysisPipelineService(
                self.uow, provider_registry=registry
            ).build_analysis_for_asset(asset_id, user=user)
            feature_hash = self._feature_hash(bundle)
            updated_run = bundle.run.model_copy(
                update={
                    "refresh_run_id": refresh.id,
                    "feature_contract_version": FEATURE_CONTRACT_VERSION,
                    "feature_vector_hash": feature_hash,
                }
            )
            self.uow.analysis_runs.add(updated_run)
            bundle = bundle.model_copy(update={"run": updated_run})
            from investment_research.service.research_forecasts import ResearchForecastService
            forecast = ResearchForecastService(self.uow).freeze_from_analysis(bundle, refresh=refresh)
            prediction = bundle.predictions[0] if bundle.predictions else None
            self.uow.paper_observations.add(
                PaperObservation(
                    asset_id=asset.id,
                    analysis_run_id=updated_run.id,
                    prediction_as_of=bundle.snapshot.as_of or completed,
                    predicted_risk=None
                    if prediction is None
                    else prediction.risk_probability,
                    prediction_price=bundle.snapshot.latest_close,
                    latest_price=bundle.snapshot.latest_close,
                    evaluation_due_at=(bundle.snapshot.as_of or completed)
                    + timedelta(days=28),
                    forecast_bundle_id=forecast.id,
                    market_snapshot_id=forecast.market_snapshot_id,
                    market_snapshot_hash=forecast.market_snapshot_hash,
                    decision_context=forecast.decision_context,
                    data_version=refresh.data_version,
                    evidence_snapshot_hash=hashlib.sha256(
                        json.dumps(sorted(str(item.id) for item in bundle.evidence)).encode()
                    ).hexdigest(),
                    model_versions={task.task: task.model_version for task in forecast.tasks if task.model_version},
                    frozen_probabilities={
                        "direction_1d": None if forecast.direction_1d is None else forecast.direction_1d.model_dump(),
                        "direction_5d": None if forecast.direction_5d is None else forecast.direction_5d.model_dump(),
                        "return_20d": None if forecast.return_20d is None else forecast.return_20d.model_dump(),
                        "drawdown_20d": None if forecast.drawdown_20d is None else forecast.drawdown_20d.model_dump(),
                    },
                    gate_conclusion="abstain" if forecast.abstained else "approved",
                    abstained=forecast.abstained,
                    abstain_reasons=forecast.gating_reasons if forecast.abstained else [],
                    provenance=_real_provenance("paper-observation", completed),
                )
            )
            job = jobs.complete(
                job,
                degraded=state == "degraded",
                coverage_ratio=1.0 if series else 0.0,
                quality_issues=failures,
                artifact_version=refresh.data_version,
                latest_source_time=bundle.snapshot.as_of or completed,
            )
            return RefreshAnalysisResult(job_id=str(job.id), refresh_run=refresh, analysis_bundle=bundle)
        except (TrainingBundleDataError, ValueError, RuntimeError) as exc:
            failures.append(str(exc))
            attempts.append(
                {
                    "provider": "authoritative_real_bundle",
                    "status": "failed",
                    "reason": str(exc),
                    "at": utc_now().isoformat(),
                }
            )
            refresh = refresh.model_copy(
                update={
                    "state": "failed",
                    "completed_at": utc_now(),
                    "provider_attempts": attempts,
                    "failure_reasons": failures,
                }
            )
            self.uow.refresh_runs.add(refresh)
            job = jobs.fail(job, exc)
            return RefreshAnalysisResult(job_id=str(job.id), refresh_run=refresh)

    def _feature_hash(self, bundle: AnalysisBundle) -> str | None:
        path = MODEL_DIR / "feature_order.json"
        if not path.exists():
            return None
        order = json.loads(path.read_text(encoding="utf-8")).get("feature_order", [])
        vector = SnapshotFeatureBuilder().build(bundle.snapshot, order)
        raw = json.dumps(
            {"order": vector.feature_order, "values": vector.values}, sort_keys=True
        ).encode()
        return hashlib.sha256(raw).hexdigest()


class HistoricalAnalogyService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def find(
        self,
        asset_id: str,
        *,
        as_of: datetime | None = None,
        analysis_run_id: UUID | None = None,
        limit: int = 5,
    ) -> list[HistoricalScenario]:
        asset = self.uow.assets.get(asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        series = next(
            (
                s
                for s in self.uow.price_series.list_for_asset(asset_id)
                if s.series_role == "asset"
            ),
            None,
        )
        if series is None or len(series.points) < 100:
            return []
        points = sorted(series.points, key=lambda p: p.timestamp)
        cutoff = as_of or points[-1].timestamp
        points = [p for p in points if p.timestamp <= cutoff]
        if len(points) < 100:
            return []
        current = self._state(points, len(points) - 1)
        candidates = []
        start = max(20, len(points) - 756)
        for idx in range(start, len(points) - 63, 5):
            state = self._state(points, idx)
            distance = math.sqrt(sum((state[k] - current[k]) ** 2 for k in current))
            similarity = 1 / (1 + distance)
            closes = [p.close for p in points]
            outcomes = {
                "return_1w": closes[idx + 5] / closes[idx] - 1,
                "return_1m": closes[idx + 21] / closes[idx] - 1,
                "return_3m": closes[idx + 63] / closes[idx] - 1,
                "max_drawdown_3m": self._max_drawdown(closes[idx : idx + 64]),
            }
            candidates.append((similarity, idx, state, outcomes))
        output = []
        for similarity, idx, state, outcomes in sorted(
            candidates, reverse=True, key=lambda x: x[0]
        )[:limit]:
            item = HistoricalScenario(
                asset_id=asset.id,
                analysis_run_id=analysis_run_id,
                as_of=cutoff,
                candidate_date=points[idx].timestamp,
                similarity=min(1.0, similarity),
                regime=self._regime(state),
                feature_snapshot=state,
                provenance=_real_provenance("historical-analogy", cutoff),
                **outcomes,
            )
            self.uow.historical_scenarios.add(item)
            output.append(item)
        return output

    def _state(self, points, index):
        closes = [p.close for p in points]
        vols = [float(p.volume or 0) for p in points]
        recent = closes[index - 19 : index + 1]
        returns = [b / a - 1 for a, b in zip(recent, recent[1:]) if a]
        peak = max(recent)
        avg_vol = sum(vols[index - 19 : index + 1]) / 20 or 1
        return {
            "valuation_percentile": 0.5,
            "pre_earnings_window": 0.0,
            "event_sentiment": 0.0,
            "return_20d": recent[-1] / recent[0] - 1,
            "volume_z": (vols[index] / avg_vol) - 1,
            "volatility_percentile": min(
                1.0, (pstdev(returns) if len(returns) > 1 else 0) * 20
            ),
            "drawdown_20d": recent[-1] / peak - 1,
        }

    def _regime(self, state):
        if state["volatility_percentile"] > 0.7:
            return "high_vol"
        if state["return_20d"] > 0.08:
            return "bull"
        if state["return_20d"] < -0.08:
            return "bear"
        return "range"

    def _max_drawdown(self, closes):
        peak = closes[0]
        worst = 0.0
        for close in closes:
            peak = max(peak, close)
            worst = min(worst, close / peak - 1)
        return worst


class PortfolioRiskService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def calculate(self, *, user: User) -> PortfolioRiskSnapshot:
        positions = self.uow.positions.list_for_user(str(user.id))
        rows = []
        returns_by_asset = {}
        for position in positions:
            asset = self.uow.assets.get(str(position.asset_id))
            series = self.uow.price_series.list_for_asset(str(position.asset_id))
            asset_series = next((s for s in series if s.series_role == "asset"), None)
            if asset is None or asset_series is None or not asset_series.points:
                continue
            pts = sorted(asset_series.points, key=lambda p: p.timestamp)
            value = position.quantity * pts[-1].close
            closes = [p.close for p in pts[-61:]]
            rets = [b / a - 1 for a, b in zip(closes, closes[1:]) if a]
            returns_by_asset[str(asset.id)] = rets
            preset = UNIVERSE_PRESETS.get(asset.ticker.upper())
            rows.append((position, asset, value, rets, preset))
        total = sum(r[2] for r in rows)
        weights = {str(r[1].id): (r[2] / total if total else 0) for r in rows}
        market = {}
        industry = {}
        contributions = {}
        for _, asset, _, rets, preset in rows:
            w = weights[str(asset.id)]
            m = "unknown" if preset is None else preset.market.value
            i = "unknown" if preset is None else preset.industry_key
            market[m] = market.get(m, 0) + w
            industry[i] = industry.get(i, 0) + w
            contributions[str(asset.id)] = w * (pstdev(rets) if len(rets) > 1 else 0)
        matrix = {
            a: {
                b: self._corr(returns_by_asset[a], returns_by_asset[b])
                for b in returns_by_asset
            }
            for a in returns_by_asset
        }
        portfolio_returns = []
        if rows:
            n = min((len(r[3]) for r in rows), default=0)
            portfolio_returns = (
                [
                    sum(weights[str(r[1].id)] * r[3][-n + j] for r in rows)
                    for j in range(n)
                ]
                if n
                else []
            )
        snapshot = PortfolioRiskSnapshot(
            user_id=user.id,
            as_of=utc_now(),
            total_market_value=total,
            concentration_hhi=sum(w * w for w in weights.values()),
            volatility_20d=pstdev(portfolio_returns[-20:])
            if len(portfolio_returns) >= 2
            else None,
            max_drawdown=self._drawdown(portfolio_returns),
            market_exposure=market,
            industry_exposure=industry,
            position_risk_contributions=contributions,
            correlation_matrix=matrix,
            stress_scenarios={
                "market_minus_10pct": -0.10 * total,
                "high_volatility": -0.15 * total,
                "event_shock": -0.08 * total,
            },
            warnings=[] if rows else ["No priced positions available"],
            provenance=_real_provenance("portfolio-risk"),
        )
        stored = self.uow.portfolio_risks.add(snapshot)
        if self.uow.domain.is_registered_user(user.id):
            self.uow.domain.record_portfolio_snapshot(
                snapshot=stored,
                owner=user,
                correlation_id=f"portfolio:{stored.id}",
            )
        return stored

    def _corr(self, a, b):
        n = min(len(a), len(b))
        if n < 2:
            return 0.0
        a = a[-n:]
        b = b[-n:]
        ma = sum(a) / n
        mb = sum(b) / n
        da = sum((x - ma) ** 2 for x in a)
        db = sum((x - mb) ** 2 for x in b)
        return (
            0.0
            if da * db == 0
            else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(da * db)
        )

    def _drawdown(self, returns):
        value = peak = 1.0
        worst = 0.0
        for r in returns:
            value *= 1 + r
            peak = max(peak, value)
            worst = min(worst, value / peak - 1)
        return worst if returns else None


class ResearchAuditService:
    AUTHORITY_TOKENS = (
        "sec.gov",
        "cninfo.com.cn",
        "hkexnews.hk",
        "nasdaq.com",
        "nyse.com",
        "sse.com.cn",
        "szse.cn",
    )

    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        retriever: BoundedAuthorityRetriever | None = None,
    ) -> None:
        self.uow = uow
        self.retriever = retriever or BoundedAuthorityRetriever()

    def audit(self, run_id: str, *, user: User | None = None) -> ResearchAudit:
        bundle = AnalysisPipelineService(self.uow).get_bundle(run_id)
        if bundle is None:
            raise ValueError("Analysis run not found")
        if user is not None and bundle.run.triggered_by != user.auth_subject:
            raise ValueError("Analysis run not found")
        prediction = bundle.predictions[0] if bundle.predictions else None
        checks = []

        def check(name, passed, reason, severity="warn"):
            checks.append(
                {"name": name, "passed": passed, "reason": reason, "severity": severity}
            )

        check(
            "model_approved",
            bool(prediction and prediction.deployment_approved),
            "Approved deployment model required",
            "block",
        )
        check(
            "feature_coverage",
            bool(prediction and prediction.feature_coverage >= 0.75),
            "Feature coverage must be at least 75%",
            "block",
        )
        check(
            "evidence_present",
            len(bundle.evidence) >= 2,
            "At least two evidence records required",
            "hold",
        )
        check(
            "pit_timestamps",
            all(
                (e.published_at or e.collected_at)
                <= (bundle.snapshot.as_of or bundle.snapshot.captured_at)
                for e in bundle.evidence
            ),
            "Evidence must be public by run as-of",
            "block",
        )
        authoritative = sum(
            1
            for e in bundle.evidence
            if e.source_url
            and any(t in e.source_url.lower() for t in self.AUTHORITY_TOKENS)
        )
        check(
            "authority_mix",
            authoritative > 0,
            "At least one authority-allowlisted source expected",
            "warn",
        )
        retrievals, rounds_used = self.retriever.retrieve(
            [e.source_url for e in bundle.evidence if e.source_url]
        )
        fetched = sum(1 for item in retrievals if item.status == "fetched")
        if self.retriever.enabled:
            check(
                "authority_network_verification",
                fetched > 0,
                "At least one allowlisted authority page should be reachable",
                "warn",
            )
        check(
            "freshness",
            bundle.snapshot.price_freshness_status == "fresh"
            and bundle.snapshot.evidence_freshness_status == "fresh",
            "Price and evidence freshness required",
            "hold",
        )
        failed = [c for c in checks if not c["passed"]]
        verdict = JudgeVerdict.PASS
        if any(c["severity"] == "block" for c in failed):
            verdict = JudgeVerdict.BLOCK
        elif any(c["severity"] == "hold" for c in failed):
            verdict = JudgeVerdict.HOLD
        elif failed:
            verdict = JudgeVerdict.WARN
        negative = [e.id for e in bundle.evidence if e.direction == "negative"][:12]
        token_chars = sum(len(e.summary) for e in bundle.evidence[:12]) + sum(
            len(item.summary) for item in retrievals
        )
        audit = ResearchAudit(
            analysis_run_id=bundle.run.id,
            verdict=verdict,
            score=max(0.0, 1 - len(failed) * 0.15),
            checks=checks,
            contrary_evidence_ids=negative,
            evidence_budget=12,
            rounds_used=rounds_used,
            token_estimate=min(4000, token_chars // 3),
            summary=f"{len(checks) - len(failed)}/{len(checks)} checks passed; verdict={verdict.value}",
            provenance=_real_provenance("research-audit"),
        )
        self.uow.research_audits.add(audit)
        self.uow.analysis_runs.add(bundle.run.model_copy(update={"audit_id": audit.id}))
        return audit


class ResearchCardService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def get(self, asset_id: str, *, user: User) -> ResearchCard:
        runs = [
            run
            for run in self.uow.analysis_runs.list_for_asset(asset_id)
            if run.triggered_by == user.auth_subject
        ]
        if not runs:
            raise ValueError("Analysis run not found")
        bundle = AnalysisPipelineService(self.uow).get_bundle(str(runs[0].id))
        if bundle is None:
            raise ValueError("Analysis bundle not found")
        analogies = HistoricalAnalogyService(self.uow).find(
            asset_id, as_of=bundle.snapshot.as_of, analysis_run_id=bundle.run.id
        )
        portfolio = PortfolioRiskService(self.uow).calculate(user=user)
        audit = self.uow.research_audits.get_for_run(
            str(bundle.run.id)
        ) or ResearchAuditService(self.uow).audit(str(bundle.run.id), user=user)
        conditions = [
            "Refresh when price data exceeds one trading day",
            "Re-run after a new filing or material announcement",
            "Keep the conclusion observational while Judge is not pass",
        ]
        contrary = (
            "Negative or contradictory evidence remains limited."
            if not audit.contrary_evidence_ids
            else f"{len(audit.contrary_evidence_ids)} negative evidence items challenge the base case."
        )
        return ResearchCard(
            bundle=bundle,
            historical_analogies=analogies,
            portfolio_risk=portfolio,
            audit=audit,
            observation_conditions=conditions,
            contrary_view=contrary,
        )
