from __future__ import annotations

from datetime import datetime, timezone

from investment_research.repository.sqlite import SQLiteUnitOfWork


def test_financial_knowledge_search_supports_chinese_and_point_in_time(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "knowledge.db")

    before_seed = uow.financial_knowledge.search(
        "公司公告有什么时间规则",
        as_of=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    after_seed = uow.financial_knowledge.search(
        "公司公告有什么时间规则",
        as_of=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )

    assert before_seed == []
    assert after_seed
    assert all(item.document.available_at <= datetime(2026, 7, 27, tzinfo=timezone.utc) for item in after_seed)
    assert all(item.document.data_tier == "research_pit" for item in after_seed)
    assert any(item.matched_terms for item in after_seed)
