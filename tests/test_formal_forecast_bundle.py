from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, User
from investment_research.pipeline.models import AnalysisBundle, AnalysisSnapshot
from investment_research.pipeline.run_factory import AnalysisRunFactory
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.research_forecasts import ResearchForecastService


def _bundle(*, synthetic: bool = False) -> AnalysisBundle:
    provenance = Provenance(
        data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="fixture",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc), confidence=1.0,
    )
    asset = Asset(ticker="600000.SH", name="Fixture", asset_type=AssetType.EQUITY, provenance=provenance)
    user = User(email="fixture@example.com", display_name="Fixture", auth_subject="fixture", provenance=provenance)
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id), asset_snapshot=asset,
        captured_at=datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
        as_of=datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
        market_snapshot_id="snapshot-1", market_snapshot_hash="a" * 64,
        decision_context="close_confirmed", data_modes=["real"],
        source_types=["synthetic"] if synthetic else ["real"],
        synthetic_share=1.0 if synthetic else 0.0, real_share=0.0 if synthetic else 1.0,
        price_provider_name="fixture-provider", evidence_provider_name="fixture-events",
    )
    run = AnalysisRunFactory().build_run(asset=asset, user=user, snapshot=snapshot, evidence=[])
    return AnalysisBundle(asset=asset, run=run, snapshot=snapshot)


class _Inference:
    def __init__(self, fail_task: str | None = None) -> None:
        self.fail_task = fail_task
        self.calls: list[str] = []

    def predict(self, *, task, **kwargs):
        self.calls.append(task)
        if task == self.fail_task:
            raise RuntimeError("scope unavailable")
        values = {
            "drawdown_20d": {"threshold_probability": 0.4},
            "direction_1d": {"up": 0.5, "down": 0.2, "flat": 0.3},
            "direction_5d": {"up": 0.4, "down": 0.3, "flat": 0.3},
            "return_20d": {"p10": -0.1, "p50": 0.02, "p90": 0.15},
        }[task]
        return SimpleNamespace(
            values=values, feature_coverage=1.0, model_status="approved",
            model_name=task, model_version="v1", fallback_from=None,
        )


def test_formal_bundle_keeps_tasks_independent_and_does_not_fallback_to_legacy(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "formal-forecast.db")
    bundle = _bundle()
    uow.assets.add(bundle.asset)
    uow.analysis_runs.add(bundle.run)
    inference = _Inference(fail_task="direction_5d")
    result = ResearchForecastService(uow).freeze_formal_from_analysis(
        bundle, market="cn", inference=inference
    )
    assert inference.calls == ["drawdown_20d", "direction_1d", "direction_5d", "return_20d"]
    assert result.drawdown_20d is not None
    assert result.direction_1d is not None
    assert result.direction_5d is None
    assert result.return_20d is not None
    assert any(task.task == "direction_5d" and task.status == "abstain" for task in result.tasks)
    assert result.training_status == "partial"
    assert result.prediction_status == "abstain"
    assert result.evidence_status == "partial"
    assert result.abstain_reasons


def test_formal_bundle_rejects_synthetic_before_any_model_call(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "formal-forecast-synthetic.db")
    inference = _Inference()
    bundle = _bundle(synthetic=True)
    uow.assets.add(bundle.asset)
    uow.analysis_runs.add(bundle.run)
    result = ResearchForecastService(uow).freeze_formal_from_analysis(
        bundle, market="cn", inference=inference
    )
    assert inference.calls == []
    assert result.abstained
    assert all(task.status == "abstain" for task in result.tasks)
    assert result.prediction_status == "abstain"
    assert result.evidence_status == "blocked"
