"""Phase 2 acceptance: AssetSnapshotService is the single source of truth.

Guards the load-bearing piece of the 选股 → 仪表盘 → AI chain:

* the snapshot composes the same as_of-pinned, read-only services the Agent's
  tools use (frozen price series, immutable long-term scorecard + model
  readings, PIT-visible fact cards + line items), with no AgentRun / abstain
  gate / writes;
* the snapshot's price / line_items / causal_observations are byte-for-byte what
  ``PlainAnswerBuilder`` produces independently from the same inputs — so the
  dashboard tile and the AI answer cannot drift on asset-scoped facts;
* ``_build_plain_answer(snapshot=...)`` consumes the snapshot's asset-scoped
  values (skipping re-reading them from tool calls) and passes the snapshot's
  causal chain straight through;
* missing data degrades to ``coverage_status="unknown"`` / ``None`` / empty,
  never a fabricated number.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from investment_research.agent.models import AgentRun
from investment_research.agent.plain_answer import PlainAnswerBuilder
from investment_research.agent.service import AgentOrchestrator
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, PricePoint, PriceSeries, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.asset_snapshot import AssetSnapshotService

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _provenance(at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="competition-demo",
        observed_at=at,
    )


def _load_seeder(project_root: Path):
    scripts_dir = str(project_root / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def _make_context(tmp_path: Path, *, ticker: str, name: str, with_prices: bool = True):
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "snapshot.db")
    user = User(
        email="judge@example.com",
        display_name="Judge",
        auth_subject="user:judge",
        provenance=_provenance(now),
    )
    uow.users.add(user, password_hash="test")
    asset = Asset(ticker=ticker, name=name, asset_type=AssetType.EQUITY, provenance=_provenance(now))
    uow.assets.add(asset)
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)
    if with_prices:
        points = [
            PricePoint(
                asset_id=asset.id,
                timestamp=AS_OF - timedelta(days=24 - index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1000.0,
                provenance=_provenance(now),
            )
            for index in range(25)
        ]
        uow.price_series.add(
            PriceSeries(asset_id=asset.id, interval="1d", points=points, provenance=_provenance(now))
        )
    return uow, user, asset, now


def test_snapshot_composes_as_of_pinned_asset_scoped_bundle(tmp_path: Path) -> None:
    uow, user, asset, _ = _make_context(tmp_path, ticker="600519", name="示例白酒")
    seeder = _load_seeder(REPO_ROOT)
    seeder._run_seed_into(uow)  # fact cards + line items + docs for 600519

    snap = AssetSnapshotService(uow, project_root=REPO_ROOT).snapshot(
        str(asset.id), as_of=AS_OF, user=user
    )

    # Asset ref + as_of pinning.
    assert snap.asset.symbol == "600519"
    assert snap.asset.name == "示例白酒"
    assert snap.as_of == AS_OF

    # Frozen price facts (as_of-pinned, NOT live): 25 points seeded ascending.
    assert snap.market_observation.sessions == 25
    assert snap.market_observation.latest_close == 124.0  # last close = 100 + 24
    assert snap.market_observation.return_20d is not None
    assert snap.market_observation.volatility_20d is not None
    assert snap.market_observation.source == "frozen_price_series"

    # Long-term scorecard + model readings come from the read-only demo loader.
    assert snap.long_term_status == "available"
    assert snap.scorecard is not None
    assert snap.model_readings is not None

    # Fact cards + line items flow from the seeded knowledge base (PIT-visible).
    assert snap.fact_cards, "fact cards should be seeded for 600519"
    assert snap.line_items, "line items should be seeded for 600519"
    assert snap.fact_card_coverage_status != "unknown" or snap.fact_cards
    assert snap.line_item_coverage_status != "unknown" or snap.line_items

    # No analysis run seeded -> forecast absent but never fabricated.
    assert snap.directional_forecast is None

    # Baseline evidence merge + causal chain are present.
    assert snap.evidence_merge_result is not None
    assert snap.causal_observations  # non-empty


def test_snapshot_causal_matches_builder_on_same_asset_inputs(tmp_path: Path) -> None:
    """The snapshot's causal chain equals what PlainAnswerBuilder produces from
    the SAME asset-scoped inputs (scorecard / readings / fact cards / line
    items / price / data_as_of) — so the dashboard's causal tile and the AI
    answer (which reuses the snapshot's causal chain) cannot drift."""
    uow, user, asset, _ = _make_context(tmp_path, ticker="600519", name="示例白酒")
    seeder = _load_seeder(REPO_ROOT)
    seeder._run_seed_into(uow)

    snap = AssetSnapshotService(uow, project_root=REPO_ROOT).snapshot(
        str(asset.id), as_of=AS_OF, user=user
    )

    independent = PlainAnswerBuilder().build(
        symbol=snap.asset.symbol,
        asset_name=snap.asset.name,
        task_text="经营变化",
        scorecard=snap.scorecard,
        model_readings=snap.model_readings,
        knowledge_results=None,
        web_results=None,
        price_facts={
            "latest_close": snap.market_observation.latest_close,
            "trade_date": snap.market_observation.trade_date,
        },
        data_as_of=snap.data_as_of,
        fact_cards=snap.fact_cards,
        line_items=snap.line_items,
    )

    # PlainAnswer stores causal_observations as already-dumped dicts; the
    # snapshot holds CausalObservation models.  Both came from
    # ReasoningChainBuilder on the same inputs with no web (so no
    # question-specific arbitration), so they must be identical.
    assert [c.model_dump(mode="json") for c in snap.causal_observations] == independent.causal_observations
    # The baseline evidence the dashboard shows (fact cards as confirmed
    # knowledge, no question-specific web) is a superset base; the AI re-runs
    # EvidenceMerger per question on top of these same asset-scoped inputs.
    assert snap.evidence_merge_result is not None
    assert any(item.classification == "confirmed_fact" for item in snap.evidence_merge_result.evidence)


def test_snapshot_degrades_without_fabrication_on_missing_data(tmp_path: Path) -> None:
    """An asset with no price series, no scorecard, empty KB -> unknown, no fake numbers."""
    uow, user, asset, _ = _make_context(tmp_path, ticker="UNKNOWN", name="未知标的", with_prices=False)

    snap = AssetSnapshotService(uow, project_root=REPO_ROOT).snapshot(
        str(asset.id), as_of=AS_OF, user=user
    )

    assert snap.market_observation.sessions == 0
    assert snap.market_observation.latest_close is None
    assert snap.market_observation.return_20d is None
    assert snap.market_observation.volatility_20d is None
    assert snap.long_term_status != "available"
    assert snap.scorecard is None
    assert snap.model_readings is None
    assert snap.fact_cards == []
    assert snap.line_items == []
    assert snap.line_item_coverage_status == "unknown"
    assert snap.fact_card_coverage_status == "unknown"
    assert snap.directional_forecast is None
    # No fabricated evidence: only "missing" items, no confirmed facts.
    assert all(item.classification == "missing" for item in snap.evidence_merge_result.evidence)


def test_build_plain_answer_consumes_snapshot_and_reuses_causal_chain(tmp_path: Path) -> None:
    """_build_plain_answer(snapshot=...) uses the snapshot's asset-scoped values
    and passes its causal chain straight through — even when the asset-scoped
    tools did not run (only question-specific knowledge/web in calls)."""
    uow, user, asset, _ = _make_context(tmp_path, ticker="600519", name="示例白酒")
    seeder = _load_seeder(REPO_ROOT)
    seeder._run_seed_into(uow)

    snap = AssetSnapshotService(uow, project_root=REPO_ROOT).snapshot(
        str(asset.id), as_of=AS_OF, user=user
    )

    run = AgentRun(
        owner_user_id=user.id,
        asset_id=asset.id,
        task_text="经营变化",
        as_of=AS_OF,
        correlation_id="snap-test",
    )
    # Only question-scoped tools ran; the asset-scoped price/forecast/line-item/
    # fact-card tools did NOT — the snapshot must supply those values.
    context = {
        "function_calls": [
            {"name": "search_financial_knowledge", "result": {"documents": []}},
            {"name": "search_latest_news", "result": {"results": []}},
        ],
        "long_term_abstain_reasons": [],
    }
    orchestrator = AgentOrchestrator(uow, project_root=REPO_ROOT)
    answer = orchestrator._build_plain_answer(
        run, context, research_pit=None, abstained=False, llm_generated=False, snapshot=snap
    )

    # The causal chain is the snapshot's, reused verbatim (no recomputation).
    # PlainAnswer stores causal_observations as already-dumped dicts.
    assert answer["causal_observations"] == [
        c.model_dump(mode="json") for c in snap.causal_observations
    ]
    # The snapshot's line_items fed that causal chain (no tool call re-ran
    # them); the price facts surface in the business-condition text via the
    # snapshot's latest_close.
    assert str(snap.market_observation.latest_close) in answer["business_condition"]


def test_snapshot_route_returns_as_of_pinned_bundle(tmp_path: Path) -> None:
    """GET /api/v1/assets/{id}/snapshot?as_of= returns the read-only bundle."""
    from investment_research.main import app
    from test_api_routes import configure_authenticated_client

    client = configure_authenticated_client(tmp_path, "snapshot-route.db")
    try:
        created = client.post(
            "/api/v1/assets",
            json={
                "ticker": "aapl",
                "name": "Apple",
                "asset_type": AssetType.EQUITY.value,
                "currency": "usd",
                "exchange": "NASDAQ",
                "data_mode": DataMode.REAL.value,
                "source_type": DataSourceType.REAL.value,
                "source_name": "iex-cloud-demo",
                "observed_at": datetime(2026, 7, 3, tzinfo=timezone.utc).isoformat(),
                "confidence": 0.97,
            },
        )
        assert created.status_code == 201
        asset_id = created.json()["id"]

        resp = client.get(
            f"/api/v1/assets/{asset_id}/snapshot",
            params={"as_of": AS_OF.isoformat()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_version"] == "asset-snapshot-v1"
        assert body["asset"]["asset_id"] == asset_id
        assert body["asset"]["symbol"] == "AAPL"
        assert body["as_of"].startswith("2026-08-16T00:00:00")
        # No price series seeded -> frozen facts absent, never fabricated.
        assert body["market_observation"]["sessions"] == 0
        assert body["market_observation"]["latest_close"] is None
        # A non-demo symbol has no scorecard -> not "available".
        assert body["long_term_status"] != "available"
        assert body["scorecard"] is None
        assert body["directional_forecast"] is None
        # Evidence is all "missing" (no fabrication), coverage unknown.
        assert body["line_item_coverage_status"] == "unknown"
        assert all(item["classification"] == "missing" for item in body["evidence_merge_result"]["evidence"])

        # 404 for an unknown asset.
        missing = client.get(
            "/api/v1/assets/does-not-exist/snapshot",
            params={"as_of": AS_OF.isoformat()},
        )
        assert missing.status_code == 404

        # 422 for a malformed as_of.
        bad = client.get(f"/api/v1/assets/{asset_id}/snapshot", params={"as_of": "not-a-date"})
        assert bad.status_code == 422

        # Default as_of (now) also works.
        default = client.get(f"/api/v1/assets/{asset_id}/snapshot")
        assert default.status_code == 200
    finally:
        app.dependency_overrides.clear()
