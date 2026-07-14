from datetime import datetime, timezone

import pytest

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, User
from investment_research.pipeline.models import AnalysisBundle, AnalysisSnapshot
from investment_research.pipeline.replay_guard import FixedRunReplayError, FixedRunReplayGuard
from investment_research.pipeline.run_factory import AnalysisRunFactory


def _provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="market-feed",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        confidence=0.92,
    )


def _bundle() -> AnalysisBundle:
    asset = Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type=AssetType.EQUITY,
        provenance=_provenance(),
    )
    user = User(
        email="investor@example.com",
        display_name="Investor",
        auth_subject="user:investor",
        provenance=_provenance(),
    )
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id),
        asset_snapshot=asset,
        captured_at=datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
        mode="real",
        provider="persisted-market@1.0.0 | persisted-evidence@1.0.0",
        as_of=datetime(2026, 7, 3, tzinfo=timezone.utc),
        data_modes=["real"],
        source_types=["real"],
    )
    run = AnalysisRunFactory().build_run(asset=asset, user=user, snapshot=snapshot, evidence=[])
    return AnalysisBundle(asset=asset, run=run, snapshot=snapshot)


def test_fixed_run_replay_guard_accepts_hash_matched_source_complete_bundle() -> None:
    FixedRunReplayGuard().validate_report_bundle(_bundle())


def test_fixed_run_replay_guard_rejects_missing_snapshot_hash() -> None:
    bundle = _bundle()
    broken = bundle.model_copy(update={"run": bundle.run.model_copy(update={"input_snapshot_hash": None})})

    with pytest.raises(FixedRunReplayError, match="missing input snapshot hash"):
        FixedRunReplayGuard().validate_report_bundle(broken)


def test_fixed_run_replay_guard_rejects_missing_source_metadata() -> None:
    bundle = _bundle()
    broken_snapshot = bundle.snapshot.model_copy(update={"provider": "unknown", "as_of": None})
    broken_run = bundle.run.model_copy(update={"input_snapshot_hash": AnalysisRunFactory().hash_snapshot(broken_snapshot)})
    broken = bundle.model_copy(update={"snapshot": broken_snapshot, "run": broken_run})

    with pytest.raises(FixedRunReplayError, match="missing provider"):
        FixedRunReplayGuard().validate_report_bundle(broken)
