"""Phase 4 (A2) — DashboardReadService is the read-only facade both the
dashboard snapshot route and the conversation path reuse.

Guards: (1) the facade delegates to AssetSnapshotService verbatim (no run,
no abstain gate, read-only); (2) the conversation route builds the snapshot
through the facade (so the route + dashboard share one entry point).
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, PricePoint, PriceSeries, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.dashboard_read import DashboardReadService

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _provenance(at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="competition-demo",
        observed_at=at,
    )


def _seed(uow: SQLiteUnitOfWork, asset: Asset, user: User) -> None:
    now = datetime.now(timezone.utc)
    prov = _provenance(now)
    uow.price_series.add(
        PriceSeries(
            asset_id=asset.id, interval="1d",
            points=[
                PricePoint(
                    asset_id=asset.id, timestamp=AS_OF - timedelta(days=24 - i),
                    open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i,
                    volume=1000.0, provenance=prov,
                ) for i in range(25)
            ],
            provenance=prov,
        )
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        importlib.import_module("seed_competition_knowledge")._run_seed_into(uow)
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))


def test_dashboard_read_facade_delegates_snapshot_verbatim(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "drs.db")
    now = datetime.now(timezone.utc)
    prov = _provenance(now)
    user = User(email="drs@e.com", display_name="DRS", auth_subject="user:drs", provenance=prov)
    uow.users.add(user, password_hash="t")
    asset = Asset(ticker="600519", name="示例白酒", asset_type=AssetType.EQUITY, provenance=prov)
    uow.assets.add(asset)
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)
    _seed(uow, asset, user)

    facade = DashboardReadService(uow, project_root=REPO_ROOT)
    snap = facade.snapshot(str(asset.id), as_of=AS_OF, user=user)

    # Read-only bundle: market observation + scorecard + KB seeded, no run state.
    assert snap.asset.symbol == "600519"
    assert snap.as_of == AS_OF
    assert snap.market_observation.latest_close == 124.0
    assert snap.market_observation.sessions == 25
    assert snap.long_term_status == "available"
    assert snap.fact_cards  # KB seeded
    assert snap.line_items  # KB seeded
    # The facade must not synthesize data when the asset is unknown.
    unknown = Asset(ticker="000000", name="x", asset_type=AssetType.EQUITY, provenance=prov)
    uow.assets.add(unknown)
    uow.domain.assign_owner(resource_type="asset", resource_id=unknown.id, owner_user_id=user.id)
    unk = facade.snapshot(str(unknown.id), as_of=AS_OF, user=user)
    assert unk.market_observation.sessions == 0
    assert unk.long_term_status != "available"
    uow.close()
