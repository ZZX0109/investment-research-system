from datetime import datetime, timezone

from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import Asset, Evidence, AnalysisRun
from investment_research.domain.models import InvestmentRecommendation, JudgeScore, ModelPrediction, RiskConclusion
from investment_research.pipeline.models import AnalysisBundle, AnalysisSnapshot, RunLineageEntry
from investment_research.pipeline.run_view_builders import (
    build_run_dossier_summary,
    build_run_lineage_timeline,
    build_run_replay_summary,
)


def _fixture_evidence() -> Evidence:
    return Evidence(
        asset_id="a0be5d0e-1234-4a1a-8f2d-000000000001",
        evidence_type=EvidenceType.RESEARCH_NOTE,
        title="Fact check",
        summary="Provider fallback note",
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="realtime-news",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=0.96,
        ),
        collected_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )


def _fixture_run(asset_id: str) -> AnalysisRun:
    return AnalysisRun(
        asset_id=asset_id,
        triggered_by="user:test",
        input_snapshot_ref="sqlite://snap/test",
        evidence_ids=["b9ce5d0e-1234-4a1a-8f2d-000000000002"],
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="pipeline",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=0.94,
        ),
    )


def test_lineage_entry_evidence_items_are_models() -> None:
    asset = Asset(
        ticker="AAPL",
        name="Apple",
        asset_type="equity",
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="seed",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=0.95,
        ),
    )
    evidence = _fixture_evidence()
    run = _fixture_run(str(asset.id))
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id),
        captured_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )
    bundle = AnalysisBundle(
        asset=asset,
        run=run,
        snapshot=snapshot,
        evidence=[evidence],
        predictions=[
            ModelPrediction(
                asset_id=asset.id,
                analysis_run_id=run.id,
                model_name="x",
                model_version="1",
                horizon="7d",
                signal="neutral",
                confidence=0.5,
                rationale="",
                provenance=run.provenance,
            )
        ],
        risk_conclusions=[
            RiskConclusion(
                asset_id=asset.id,
                analysis_run_id=run.id,
                risk_level="low",
                summary="ok",
                evidence_ids=[evidence.id],
                provenance=run.provenance,
            )
        ],
        recommendations=[
            InvestmentRecommendation(
                asset_id=asset.id,
                analysis_run_id=run.id,
                action="hold",
                conviction=0.3,
                reasoning="base",
                provenance=run.provenance,
            )
        ],
        judge_scores=[
            JudgeScore(
                analysis_run_id=run.id,
                score=0.8,
                verdict="pass",
                provenance=run.provenance,
            )
        ],
        reports=[],
    )

    timeline = build_run_lineage_timeline(str(asset.id), [bundle], [])
    first = timeline.entries[0]

    assert isinstance(first, RunLineageEntry)
    assert first.evidence_items[0].id == str(evidence.id)
    assert first.evidence_items[0].title == "Fact check"


def test_run_views_expose_explicit_source_layer_metadata() -> None:
    asset = Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type="equity",
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="seed",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=0.95,
        ),
    )
    evidence = _fixture_evidence()
    run = _fixture_run(str(asset.id))
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id),
        captured_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        mode="real",
        provider="persisted-market@1.0.0 | persisted-evidence@1.0.0",
        as_of=datetime(2026, 7, 3, tzinfo=timezone.utc),
        overrides=["manual backfill used for missing live price tick"],
        synthetic_ratio=0.25,
        source_meta={
            "mode": "real",
            "provider": "persisted-market@1.0.0 | persisted-evidence@1.0.0",
            "as_of": datetime(2026, 7, 3, tzinfo=timezone.utc),
            "overrides": ["manual backfill used for missing live price tick"],
            "synthetic_ratio": 0.25,
        },
    )
    bundle = AnalysisBundle(
        asset=asset,
        run=run,
        snapshot=snapshot,
        source_meta=snapshot.source_meta,
        evidence=[evidence],
        predictions=[],
        risk_conclusions=[],
        recommendations=[],
        judge_scores=[],
        reports=[],
    )

    replay = build_run_replay_summary(bundle)
    dossier = build_run_dossier_summary(bundle)

    assert replay.source_meta.mode == "real"
    assert replay.source_meta.provider.startswith("persisted-market")
    assert replay.source_meta.synthetic_ratio == 0.25
    assert dossier.source_meta.overrides == ["manual backfill used for missing live price tick"]
