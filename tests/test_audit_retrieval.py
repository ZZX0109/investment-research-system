from __future__ import annotations

from investment_research.service import audit_retrieval
from investment_research.service.audit_retrieval import BoundedAuthorityRetriever


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return b"<html><body>Official filing update</body></html>"


def test_authority_retrieval_enforces_allowlist_domain_and_total_budgets(
    monkeypatch,
) -> None:
    requested: list[str] = []

    def fake_open(request, timeout):
        requested.append(request.full_url)
        assert timeout == 4
        return Response()

    monkeypatch.setattr(audit_retrieval, "urlopen", fake_open)
    retriever = BoundedAuthorityRetriever(
        enabled=True, max_evidence=4, max_rounds=2, per_domain=2
    )
    results, rounds = retriever.retrieve(
        [
            "https://www.sec.gov/a",
            "https://www.sec.gov/b",
            "https://www.sec.gov/c",
            "https://www.hkexnews.hk/d",
            "https://example.com/not-allowed",
        ]
    )

    assert rounds == 1
    assert len(results) == 3
    assert len(requested) == 3
    assert all(item.status == "fetched" for item in results)
    assert all(item.content_hash for item in results)


def test_authority_retrieval_is_offline_by_default(monkeypatch) -> None:
    monkeypatch.delenv("RESEARCH_AUDIT_NETWORK_ENABLED", raising=False)

    results, rounds = BoundedAuthorityRetriever().retrieve(["https://www.sec.gov/a"])

    assert results == []
    assert rounds == 0
