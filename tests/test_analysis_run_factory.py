from datetime import datetime, timezone

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import Asset, Evidence, User
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.pipeline.run_factory import AnalysisRunFactory, DEFAULT_ANALYSIS_MODEL_VERSION


def provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="market-feed",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        confidence=0.94,
    )


def test_analysis_run_factory_hashes_snapshot_deterministically() -> None:
    factory = AnalysisRunFactory()
    snapshot = AnalysisSnapshot(
        asset_id="asset-1",
        captured_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        mode="real",
        provider="provider@1.0.0",
        latest_close=100.0,
    )

    first_hash = factory.hash_snapshot(snapshot)
    second_hash = factory.hash_snapshot(snapshot.model_copy(deep=True))
    changed_hash = factory.hash_snapshot(snapshot.model_copy(update={"latest_close": 101.0}))

    assert first_hash == second_hash
    assert first_hash != changed_hash


def test_analysis_run_factory_builds_traceable_run_from_frozen_snapshot() -> None:
    asset = Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type=AssetType.EQUITY,
        provenance=provenance(),
    )
    user = User(
        email="investor@example.com",
        display_name="Investor",
        auth_subject="user:investor@example.com",
        provenance=provenance(),
    )
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.RESEARCH_NOTE,
        title="Evidence",
        summary="Frozen evidence",
        collected_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        provenance=provenance(),
    )
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id),
        asset_snapshot=asset,
        captured_at=datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
        mode="real",
        provider="persisted-market@1.0.0 | persisted-evidence@1.0.0",
        as_of=datetime(2026, 7, 3, tzinfo=timezone.utc),
        overrides=["manual backfill"],
        synthetic_ratio=0.2,
        evidence_snapshot=[evidence],
    )

    run = AnalysisRunFactory().build_run(asset=asset, user=user, snapshot=snapshot, evidence=[evidence])

    assert run.triggered_by == "user:investor@example.com"
    assert run.input_snapshot_ref.endswith(str(run.id))
    assert run.input_snapshot_hash == AnalysisRunFactory().hash_snapshot(snapshot)
    assert run.model_version == DEFAULT_ANALYSIS_MODEL_VERSION
    assert run.reasoning_steps == [
        "resolve_intake_sources",
        "freeze_snapshot",
        "score_prediction",
        "evaluate_risk",
        "apply_judge_gate",
        "emit_recommendation",
    ]
    assert run.provider == "persisted-market@1.0.0 | persisted-evidence@1.0.0"
    assert run.synthetic_ratio == 0.2
    assert run.evidence_ids == [evidence.id]
    assert run.provenance.observed_at == snapshot.captured_at
    assert run.provenance.generation_chain[-1].producer == "analysis_pipeline"
