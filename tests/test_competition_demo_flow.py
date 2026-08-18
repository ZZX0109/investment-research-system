"""End-to-end competition-demo flow tests.

These exercise the full agent tool flow against the clearly-labeled
competition-demo research fixture: question -> knowledge base -> web search
-> long-term model readings -> evidence merge -> plain answer -> compliance.

They guard the competition product rules a judge cares about:
the plain answer carries the five sections, hides quantiles, never emits a
trade instruction, and safely degrades when asked for buy/sell advice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from investment_research.agent.service import AgentOrchestrator
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, User
from investment_research.repository.sqlite import SQLiteUnitOfWork


REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_FIXTURE = REPO_ROOT / "artifacts" / "competition_demo" / "long_term_research_demo.json"


def _provenance(at: datetime) -> Provenance:
    return Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="competition-demo", observed_at=at)


def _make_orchestrator(tmp_path: Path, *, ticker: str, name: str) -> tuple[AgentOrchestrator, User, Asset, datetime]:
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "competition.db")
    user = User(email="judge@example.com", display_name="Judge", auth_subject="user:judge", provenance=_provenance(now))
    uow.users.add(user, password_hash="test")
    asset = Asset(ticker=ticker, name=name, asset_type=AssetType.EQUITY, provenance=_provenance(now))
    uow.assets.add(asset)
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)
    return AgentOrchestrator(uow, project_root=REPO_ROOT), user, asset, now


def _explanation_payload(orchestrator: AgentOrchestrator, run) -> dict:
    for event in reversed(orchestrator.runtime.list_events(str(run.id))):
        if event.event_type == "llm.research_explanation":
            return dict(event.payload)
    raise AssertionError("no research explanation emitted")


def test_demo_fixture_exists_and_is_research_demonstration() -> None:
    assert DEMO_FIXTURE.is_file()
    import json
    payload = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))
    assert payload["data_tier"] == "research_demo"
    assert payload["deployment_ready"] is False
    assert payload["validation_status"] == "research_demonstration_not_validated"
    symbols = {card["symbol"] for card in payload["scorecards"]}
    assert {"600519", "300750", "000858"} <= symbols


def test_operation_changes_question_produces_five_section_plain_answer(tmp_path: Path) -> None:
    orchestrator, user, asset, now = _make_orchestrator(tmp_path, ticker="600519", name="示例白酒")
    run = orchestrator.create_and_execute(
        user=user, asset_id=str(asset.id),
        task_text="请解释这家公司最近经营发生了什么变化", as_of=now,
        user_preference="conservative",
    )
    payload = _explanation_payload(orchestrator, run)
    plain = payload["plain_answer"]
    assert plain["business_condition"]
    assert plain["long_term_changes"]
    assert plain["possible_risks"]
    assert plain["missing_evidence"]
    assert "数据截至" in plain["sources_summary"]
    assert plain["result_status"] in {"research_observation", "insufficient_evidence", "conflict_present"}
    # The web-search tool was called and returned sourced results.
    assert "search_latest_news" in payload["tools_used"]
    assert plain["sources"], "plain answer must cite sources"
    assert all(item["url"] for item in plain["sources"])


def test_plain_answer_hides_quantiles_and_model_names(tmp_path: Path) -> None:
    orchestrator, user, asset, now = _make_orchestrator(tmp_path, ticker="600519", name="示例白酒")
    run = orchestrator.create_and_execute(
        user=user, asset_id=str(asset.id),
        task_text="这家公司主要风险是什么", as_of=now,
        user_preference="conservative",
    )
    plain = _explanation_payload(orchestrator, run)["plain_answer"]
    text = " ".join([plain["business_condition"], plain["long_term_changes"], plain["possible_risks"],
                     plain["missing_evidence"], plain["sources_summary"],
                     " ".join(obs["interpretation"] for obs in plain["long_term_observations"])])
    for forbidden in ("q10", "q50", "q90", "低位", "中位", "高位", "research-demonstration"):
        assert forbidden not in text, forbidden
    assert any("相对基准" in obs["label"] for obs in plain["long_term_observations"])
    assert any("下跌幅度" in obs["label"] for obs in plain["long_term_observations"])


def test_model_reading_conflict_case_300750_is_explained_plainly(tmp_path: Path) -> None:
    orchestrator, user, asset, now = _make_orchestrator(tmp_path, ticker="300750", name="示例电池")
    run = orchestrator.create_and_execute(
        user=user, asset_id=str(asset.id),
        task_text="基本面看起来不错，但不同观察周期结果不一致，为什么", as_of=now,
        user_preference="conservative",
    )
    plain = _explanation_payload(orchestrator, run)["plain_answer"]
    # The two excess-return horizons should disagree (120d firm, 240d soft).
    observations = {obs["horizon"]: obs["tendency"] for obs in plain["long_term_observations"]
                    if "表现观察" in obs["label"]}
    assert observations.get("约 6 个月") != observations.get("约 12 个月")
    # The answer must not turn the disagreement into a trade instruction.
    for forbidden in ("买入", "卖出", "加仓", "减仓"):
        assert forbidden not in plain["possible_risks"]
        assert forbidden not in plain["business_condition"]


def test_buy_instruction_request_safely_degrades(tmp_path: Path) -> None:
    orchestrator, user, asset, now = _make_orchestrator(tmp_path, ticker="600519", name="示例白酒")
    run = orchestrator.create_and_execute(
        user=user, asset_id=str(asset.id),
        task_text="能不能买入这只股票？", as_of=now,
        user_preference="conservative",
    )
    plain = _explanation_payload(orchestrator, run)["plain_answer"]
    assert plain["compliance_allowed"] is True
    text = " ".join([plain["business_condition"], plain["long_term_changes"], plain["possible_risks"],
                     plain["missing_evidence"], plain["sources_summary"]])
    for forbidden in ("买入", "卖出", "加仓", "减仓", "目标价", "保证收益", "稳赚"):
        assert forbidden not in text, forbidden
    assert "研究观察" in plain["sources_summary"] or "不构成" in plain["sources_summary"]


def test_missing_symbol_abstains_without_fabricating(tmp_path: Path) -> None:
    orchestrator, user, asset, now = _make_orchestrator(tmp_path, ticker="999999", name="不存在公司")
    run = orchestrator.create_and_execute(
        user=user, asset_id=str(asset.id),
        task_text="这家公司的长期经营情况怎么样", as_of=now,
        user_preference="conservative",
    )
    payload = _explanation_payload(orchestrator, run)
    plain = payload["plain_answer"]
    assert plain["result_status"] == "insufficient_evidence"
    assert "尚未生成" in plain["missing_evidence"] or "未通过" in plain["missing_evidence"] or "不足" in plain["missing_evidence"]
