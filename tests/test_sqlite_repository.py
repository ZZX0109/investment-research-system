from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from investment_research.api.schemas import AssetCreateRequest
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.workbench import WorkbenchService


def build_asset() -> Asset:
    return Asset(
        ticker="QQQ",
        name="Invesco QQQ Trust",
        asset_type=AssetType.ETF,
        provenance=Provenance(
            data_mode=DataMode.SANDBOX,
            source_type=DataSourceType.BACKFILLED,
            source_name="fixture-loader",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=0.93,
        ),
    )


def test_sqlite_asset_repository_round_trips_traceable_asset(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "test.db")
    asset = uow.assets.add(build_asset())
    stored = uow.assets.get(str(asset.id))
    version_row = uow.connection.execute("SELECT version_num FROM alembic_version").fetchone()
    uow.close()

    assert stored is not None
    assert stored.ticker == "QQQ"
    assert stored.provenance.source_type == DataSourceType.BACKFILLED
    assert stored.version.schema_version == "1.0.0"
    assert version_row is not None
    assert version_row["version_num"] == "0013_pit_data_catalog"


def test_workbench_service_persists_demo_analysis_run(tmp_path: Path) -> None:
    service = WorkbenchService(SQLiteUnitOfWork(tmp_path / "workbench.db"))

    run = service.persist_demo_analysis_run()
    reloaded = WorkbenchService(SQLiteUnitOfWork(tmp_path / "workbench.db")).get_analysis_run(str(run.id))

    assert reloaded is not None
    assert reloaded.id == run.id
    assert reloaded.provenance.data_mode == DataMode.DEMO
    assert reloaded.judge_score_ids


def test_workbench_service_creates_asset_from_request(tmp_path: Path) -> None:
    service = WorkbenchService(SQLiteUnitOfWork(tmp_path / "assets.db"))

    asset = service.create_asset(
        AssetCreateRequest(
            ticker="msft",
            name="Microsoft",
            asset_type=AssetType.EQUITY,
            currency="usd",
            exchange="NASDAQ",
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="polygon-demo",
            observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            confidence=0.99,
        )
    )
    listed = WorkbenchService(SQLiteUnitOfWork(tmp_path / "assets.db")).list_assets(source_type="real")

    assert asset.ticker == "MSFT"
    assert listed
    assert listed[0].provenance.source_name == "polygon-demo"


def test_sqlite_unit_of_work_can_cross_fastapi_worker_threads(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "threaded.db")
    uow.assets.add(build_asset())

    with ThreadPoolExecutor(max_workers=1) as pool:
        assets = pool.submit(uow.assets.list).result(timeout=5)

    uow.close()
    assert [asset.ticker for asset in assets] == ["QQQ"]
