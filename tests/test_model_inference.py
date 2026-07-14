from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import joblib

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import Asset, Evidence, PricePoint, PriceSeries
from investment_research.pipeline.model_inference import DeploymentModelInferenceService, SnapshotFeatureBuilder
from investment_research.pipeline.models import AnalysisSnapshot


FEATURE_ORDER = [
    "benchmark_ret_20d",
    "earnings_count_30d",
    "filing_count_30d",
    "halted_flag",
    "market_cn_flag",
    "news_count_7d",
    "relative_strength_20d",
    "ret_20d",
    "ret_5d",
    "sector_relative_strength_20d",
    "sector_ret_20d",
    "style_relative_strength_20d",
    "style_ret_20d",
    "vol_20d",
    "vol_5d",
    "volume_z_20d",
]

FULL_FEATURE_ORDER = [
    "benchmark_ret_20d",
    "earnings_count_30d",
    "earnings_surprise_score_30d",
    "event_score_1d",
    "event_score_30d",
    "event_score_7d",
    "filing_8k_count_30d",
    "filing_count_30d",
    "guidance_cut_flag_30d",
    "halted_flag",
    "market_cn_flag",
    "market_hk_flag",
    "market_jp_flag",
    "market_us_flag",
    "mna_event_flag_30d",
    "negative_event_score_7d",
    "news_count_7d",
    "official_event_score_30d",
    "regulatory_risk_score_30d",
    "relative_strength_20d",
    "ret_20d",
    "ret_5d",
    "sector_relative_strength_20d",
    "sector_ret_20d",
    "style_relative_strength_20d",
    "style_ret_20d",
    "vol_20d",
    "vol_5d",
    "volume_z_20d",
]


class FixedProbabilityModel:
    classes_ = [0, 1]

    def __init__(self, probability: float = 0.82) -> None:
        self.probability = probability

    def predict_proba(self, rows):
        return [[1.0 - self.probability, self.probability] for _ in rows]


def provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="test-feed",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        confidence=0.95,
    )


def snapshot() -> AnalysisSnapshot:
    target_asset = Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type=AssetType.EQUITY,
        provenance=provenance(),
    )
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    points = [
        PricePoint(
            asset_id=target_asset.id,
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1_000_000 + (index * 1_000),
            provenance=provenance(),
        )
        for index in range(25)
    ]
    evidence = [
        Evidence(
            asset_id=target_asset.id,
            evidence_type=EvidenceType.NEWS,
            title="Cloud demand update",
            summary="News item within seven days.",
            collected_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
            provenance=provenance(),
        ),
        Evidence(
            asset_id=target_asset.id,
            evidence_type=EvidenceType.FILING,
            title="10-Q filing",
            summary="Filing within thirty days.",
            event_type="filing",
            direction="neutral",
            intensity="normal",
            source_tier="regulatory",
            filing_type="8-K",
            collected_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
            provenance=provenance(),
        ),
        Evidence(
            asset_id=target_asset.id,
            evidence_type=EvidenceType.RESEARCH_NOTE,
            title="Earnings guidance",
            summary="Quarterly earnings guidance remains stable.",
            collected_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
            provenance=provenance(),
        ),
    ]
    return AnalysisSnapshot(
        asset_id=str(target_asset.id),
        asset_snapshot=target_asset,
        captured_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        as_of=datetime(2026, 6, 25, tzinfo=timezone.utc),
        data_modes=["real"],
        source_types=["real"],
        latest_close=124,
        latest_price_timestamp=datetime(2026, 6, 25, tzinfo=timezone.utc),
        price_freshness_status="fresh",
        evidence_freshness_status="fresh",
        price_series_snapshot=[
            PriceSeries(
                asset_id=target_asset.id,
                interval="1d",
                series_role="asset",
                points=points,
                provenance=provenance(),
            ),
            *[
                PriceSeries(
                    asset_id=target_asset.id,
                    interval="1d",
                    series_role=role,
                    reference_symbol=f"{role.upper()}-REF",
                    points=points,
                    provenance=provenance(),
                )
                for role in ("benchmark", "sector", "style")
            ],
        ],
        evidence_snapshot=evidence,
        synthetic_share=0.0,
        real_share=1.0,
    )


def test_snapshot_feature_builder_maps_frozen_snapshot_to_training_shape() -> None:
    vector = SnapshotFeatureBuilder().build(snapshot(), FEATURE_ORDER)

    assert vector.feature_order == FEATURE_ORDER
    assert len(vector.values) == 16
    assert vector.values[FEATURE_ORDER.index("ret_5d")] > 0
    assert vector.values[FEATURE_ORDER.index("ret_20d")] > 0
    assert vector.values[FEATURE_ORDER.index("news_count_7d")] == 1
    assert vector.values[FEATURE_ORDER.index("filing_count_30d")] == 1
    assert vector.values[FEATURE_ORDER.index("earnings_count_30d")] == 1
    assert vector.missing_features == []
    assert vector.feature_coverage == 1.0


def test_snapshot_feature_builder_satisfies_full_deployment_contract() -> None:
    vector = SnapshotFeatureBuilder().build(snapshot(), FULL_FEATURE_ORDER)

    assert len(vector.values) == 29
    assert vector.feature_coverage == 1.0
    assert vector.values[FULL_FEATURE_ORDER.index("market_us_flag")] == 1.0
    assert vector.values[FULL_FEATURE_ORDER.index("official_event_score_30d")] > 0
    assert vector.values[FULL_FEATURE_ORDER.index("filing_8k_count_30d")] == 1.0


def test_deployment_inference_uses_only_approved_manifest_model(tmp_path) -> None:
    approved_path = tmp_path / "linear-baseline_model.pkl"
    joblib.dump(FixedProbabilityModel(), approved_path)
    (tmp_path / "model_manifest.json").write_text(
        json.dumps(
            {
                "deployment_ready": True,
                "training_generated_at": "2026-07-08T08:21:00+00:00",
                "approved_trainers": ["linear-baseline"],
                "models": {
                    "linear-baseline": {
                        "path": str(approved_path),
                        "status": "approved",
                        "trainer_name": "linear-baseline",
                        "target_name": "future_max_drawdown_20d",
                    },
                    "random-forest": {
                        "path": str(tmp_path / "random-forest_model.pkl"),
                        "status": "candidate_research",
                        "trainer_name": "random-forest",
                    },
                },
            }
        )
    )
    (tmp_path / "feature_order.json").write_text(json.dumps({"feature_order": FEATURE_ORDER}))
    (tmp_path / "scaler_params.json").write_text(
        json.dumps(
            {
                "mean": [0.0 for _ in FEATURE_ORDER],
                "scale": [1.0 for _ in FEATURE_ORDER],
                "feature_order": FEATURE_ORDER,
            }
        )
    )

    result = DeploymentModelInferenceService(model_dir=tmp_path).predict(snapshot())

    assert result.model_name == "linear-baseline"
    assert result.model_status == "approved"
    assert result.deployment_approved is True
    assert result.risk_probability == 0.82
    assert result.signal == "risk_high"
    assert result.feature_coverage == 1.0
    assert result.missing_features == []
    assert result.inference_warnings == []


def test_deployment_inference_uses_primary_model_and_falls_back_to_champion(tmp_path) -> None:
    primary_path = tmp_path / "random-forest_model.pkl"
    fallback_path = tmp_path / "linear-baseline_model.pkl"
    joblib.dump(FixedProbabilityModel(0.71), primary_path)
    joblib.dump(FixedProbabilityModel(0.33), fallback_path)
    (tmp_path / "model_manifest.json").write_text(
        json.dumps(
            {
                "deployment_ready": True,
                "training_generated_at": "2026-07-08T08:21:00+00:00",
                "primary_model": {"trainer_name": "random-forest"},
                "champion_fallback": {"trainer_name": "linear-baseline"},
                "approved_trainers": ["linear-baseline", "random-forest"],
                "models": {
                    "linear-baseline": {
                        "path": str(fallback_path),
                        "status": "approved",
                        "trainer_name": "linear-baseline",
                        "target_name": "future_max_drawdown_20d",
                    },
                    "random-forest": {
                        "path": str(primary_path),
                        "status": "approved",
                        "trainer_name": "random-forest",
                        "target_name": "future_max_drawdown_20d",
                    },
                },
            }
        )
    )
    (tmp_path / "feature_order.json").write_text(json.dumps({"feature_order": FEATURE_ORDER}))
    (tmp_path / "scaler_params.json").write_text(
        json.dumps({"mean": [0.0 for _ in FEATURE_ORDER], "scale": [1.0 for _ in FEATURE_ORDER]})
    )

    result = DeploymentModelInferenceService(model_dir=tmp_path).predict(snapshot())

    assert result.model_name == "random-forest"
    assert result.risk_probability == 0.71

    primary_path.unlink()
    fallback_result = DeploymentModelInferenceService(model_dir=tmp_path).predict(snapshot())

    assert fallback_result.model_name == "linear-baseline"
    assert fallback_result.risk_probability == 0.33
    assert any("primary model random-forest unavailable" in warning for warning in fallback_result.inference_warnings)
